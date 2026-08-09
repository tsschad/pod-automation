"""
coordinator.py

The control PC's multiplayer coordinator: the single source of truth
for which pods exist, who's inviting whom, what the inviter has
configured so far, and which of the 4 acServer instances is assigned
to an active group. Pods' browsers talk to this service directly
(CORS-enabled below) rather than through their own pod's Flask app,
except for the one step that has to happen locally on each pod --
actually writing race.ini and launching acs.exe once a session starts
(that's phase1/app.py's /api/mp/join, on each pod).

State model
-----------
Pod: {pod_id, ip, status, last_seen, group_id}
    status: "idle" | "invited" | "in_group"

Group: {
    group_id, inviter_pod_id, member_pod_ids (inviter first),
    invite_status: {pod_id: "pending"|"accepted"|"declined"},
    state: "pending" | "active" | "ended",
    config: {pack_id, car_id, track_id, track_layout, session_type,
              duration_minutes, customer_names: {pod_id: name}},
    acserver_instance: int | None,
    created_at, ended_reason,
}

Scope decision, flagged rather than silently assumed: the INVITER
picks pack/car/track/session/duration for the whole group (same car
for everyone), not each pod picking its own car independently. Keeps
the acServer entry_list.ini assignment simple (see acserver_manager.py)
and the invite flow easy to follow. Straightforward to extend to
per-pod car choice later once the core join mechanism is proven on
real hardware -- that's the bigger unknown here, not this.

Live updates: each pod holds one persistent SSE connection to
GET /api/pods/<pod_id>/events, opened as soon as its kiosk app loads
(even before joining any group -- that's how it finds out it's been
invited in the first place). Whatever group that pod is part of, all
of that group's events (config changes, accept/decline, session
started/ended) get pushed down that same connection.

Known gap, not built here: nothing currently calls
end_group(..., reason="time_expired") automatically. That needs the
booking-clock hook described in the architecture brief (Section 4) --
still not built, same gap noted for phase1's single-player race
sessions. The capability is here and ready; nothing wires it up yet.

acServer process model, confirmed: one shared acServer.exe, launched
once per pooled instance via -c/-e flags pointing at that instance's
own config folder/port (acserver_manager.py) -- each pooled instance
is a genuinely independent running process on its own port, matching
what Chad's "Assetto Corsa Server Manager" screenshot showed is
possible (multiple independent servers from one acServer install,
different ports). This coordinator owns starting/stopping those
processes itself rather than relying on that GUI tool.

GET /api/instances additionally queries each running instance's own
HTTP status endpoint (acserver_status.py) so the coordinator -- and
the admin GUI at /admin -- can show live per-server status (track,
session, connected drivers) without trusting its own bookkeeping
alone.

Admin GUI (/admin, served from the admin/ folder): lets Chad manually
start/stop/reassign any pooled instance directly -- independent of the
customer invite flow -- for testing, hotlap setup, or just running a
server nobody had to book. An instance is "assigned" to exactly one of
two things at a time, tracked separately: a customer group (started via
POST /api/groups/<id>/start, the normal invite flow) or an admin
session (started via POST /api/admin/instances/<id>/start, this GUI).
Manually starting/stopping an instance that's mid-customer-session is
allowed -- Chad confirmed the admin GUI should be able to override with
a confirmation dialog rather than being blocked -- so reassigning an
instance out from under an active group ends that group first (frees
its pods back to idle, tells its members the session ended) rather
than leaving stale state pointing at a server that's now running
something else.

Run with:
    pip install -r requirements.txt
    python coordinator.py
Listens on 0.0.0.0:6000 by default. Admin GUI: http://<this-machine>:6000/admin
"""

import json
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from flask import Flask, jsonify, request, Response, send_from_directory

import acserver_manager
import acserver_status

APP_DIR = os.path.dirname(os.path.abspath(__file__))
POOL_CONFIG_PATH = os.path.join(APP_DIR, "acserver_pool.json")
ADMIN_DIR = os.path.join(APP_DIR, "admin")

INVITE_TIMEOUT_SECONDS = 60
SWEEP_INTERVAL_SECONDS = 5

app = Flask(__name__)
_lock = threading.Lock()

pods: Dict[str, dict] = {}
groups: Dict[str, dict] = {}
_subscribers: Dict[str, List["queue.Queue"]] = {}
_running_instances: Dict[int, object] = {}  # instance id -> subprocess.Popen
_admin_sessions: Dict[int, dict] = {}  # instance id -> config summary, for instances started from /admin rather than a customer group


def _load_pool_config() -> dict:
    if not os.path.isfile(POOL_CONFIG_PATH):
        raise FileNotFoundError(
            f"{POOL_CONFIG_PATH} not found. Copy acserver_pool.example.json "
            f"to acserver_pool.json and fill in your acServer.exe path and "
            f"the 4 instances' ports/config folders."
        )
    with open(POOL_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _publish(pod_id: str, event: str, data: dict) -> None:
    payload = json.dumps(data)
    for q in _subscribers.get(pod_id, []):
        q.put((event, payload))


def _publish_to_group(group: dict, event: str, data: dict) -> None:
    for pod_id in group["member_pod_ids"]:
        _publish(pod_id, event, data)


def _free_instance_id(pool_cfg: dict) -> Optional[int]:
    """Caller must hold _lock. An instance the admin GUI has claimed
    for a manual session counts as used too, so the automatic
    invite-flow assignment (POST /api/groups/<id>/start) doesn't grab
    an instance out from under something Chad started by hand."""
    used = {g["acserver_instance"] for g in groups.values() if g["state"] == "active" and g["acserver_instance"]}
    used |= set(_admin_sessions.keys())
    for inst in pool_cfg["instances"]:
        if inst["id"] not in used:
            return inst["id"]
    return None


def _instance_assignment_locked(instance_id: int) -> Optional[dict]:
    """Caller must hold _lock. What's currently using this pooled
    instance, if anything -- a customer group (normal invite flow) or
    an admin-started session (the /admin GUI). At most one of these at
    a time; see module docstring."""
    group = next(
        (g for g in groups.values() if g["state"] == "active" and g["acserver_instance"] == instance_id),
        None,
    )
    if group is not None:
        return {
            "type": "group",
            "group_id": group["group_id"],
            "inviter_pod_id": group["inviter_pod_id"],
            "member_pod_ids": list(group["member_pod_ids"]),
            "config": dict(group["config"]),
        }
    admin_session = _admin_sessions.get(instance_id)
    if admin_session is not None:
        return {"type": "admin", "config": dict(admin_session)}
    return None


def _end_group_on_instance_locked(instance_id: int, reason: str) -> None:
    """Caller must hold _lock. If a customer group currently owns this
    instance, end it (frees its pods, notifies its members) -- used
    when the admin GUI reassigns/stops an instance out from under an
    active session."""
    group = next(
        (g for g in groups.values() if g["state"] == "active" and g["acserver_instance"] == instance_id),
        None,
    )
    if group is not None:
        _end_group(group, reason=reason)


def _end_group(group: dict, reason: str) -> None:
    """Caller must hold _lock."""
    if group["state"] == "ended":
        return
    group["state"] = "ended"
    group["ended_reason"] = reason

    if group["acserver_instance"] is not None:
        proc = _running_instances.pop(group["acserver_instance"], None)
        acserver_manager.stop_instance(proc)
        group["acserver_instance"] = None

    for pod_id in group["member_pod_ids"]:
        pod = pods.get(pod_id)
        if pod:
            pod["status"] = "idle"
            pod["group_id"] = None

    _publish_to_group(group, "session_ended", {"group_id": group["group_id"], "reason": reason})


def _sweep_expired_invites() -> None:
    while True:
        time.sleep(SWEEP_INTERVAL_SECONDS)
        with _lock:
            now = time.time()
            for group in list(groups.values()):
                if group["state"] != "pending":
                    continue
                if now - group["created_at"] < INVITE_TIMEOUT_SECONDS:
                    continue
                still_pending = [
                    pod_id for pod_id, status in group["invite_status"].items()
                    if status == "pending"
                ]
                if still_pending:
                    for pod_id in still_pending:
                        group["invite_status"][pod_id] = "timed_out"
                    _end_group(group, reason="timed_out")


threading.Thread(target=_sweep_expired_invites, daemon=True).start()


@app.after_request
def _add_cors_headers(resp):
    # Pods' browsers (served from each pod's own Flask app, a different
    # origin than this coordinator) call this API directly.
    # Closed LAN kiosk system -- wide-open CORS is fine here.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.route("/api/pods/<pod_id>/register", methods=["POST", "OPTIONS"])
def api_register_pod(pod_id):
    if request.method == "OPTIONS":
        return ""
    with _lock:
        pod = pods.get(pod_id)
        if pod is None:
            pod = {"pod_id": pod_id, "ip": "", "status": "idle", "group_id": None}
            pods[pod_id] = pod
        # The browser can't reliably know its own LAN IP; the source
        # address of this very request is a better answer anyway.
        pod["ip"] = request.remote_addr or pod["ip"]
        pod["last_seen"] = time.time()
        return jsonify(pod)


@app.route("/api/pods")
def api_list_pods():
    with _lock:
        return jsonify({"pods": list(pods.values())})


@app.route("/api/pods/<pod_id>/events")
def api_pod_events(pod_id):
    q: "queue.Queue" = queue.Queue()
    with _lock:
        _subscribers.setdefault(pod_id, []).append(q)

    def stream():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    event, payload = q.get(timeout=15)
                    yield f"event: {event}\ndata: {payload}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _lock:
                subs = _subscribers.get(pod_id, [])
                if q in subs:
                    subs.remove(q)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/groups", methods=["POST", "OPTIONS"])
def api_create_group():
    if request.method == "OPTIONS":
        return ""
    body = request.get_json(force=True, silent=True) or {}
    inviter_id = body.get("inviter_pod_id")
    invitee_ids = body.get("invitee_pod_ids", [])
    inviter_name = body.get("inviter_name", "") or inviter_id

    with _lock:
        if inviter_id not in pods:
            return jsonify({"error": f"Unknown pod '{inviter_id}'"}), 404
        for pid in invitee_ids:
            if pid not in pods:
                return jsonify({"error": f"Unknown pod '{pid}'"}), 404
            if pods[pid]["status"] != "idle":
                return jsonify({"error": f"Pod '{pid}' is not idle"}), 409

        group_id = uuid.uuid4().hex[:8]
        member_ids = [inviter_id] + invitee_ids
        group = {
            "group_id": group_id,
            "inviter_pod_id": inviter_id,
            "member_pod_ids": member_ids,
            "invite_status": {pid: ("accepted" if pid == inviter_id else "pending") for pid in member_ids},
            "state": "pending",
            # customer_names is set by each pod itself -- the inviter
            # here, invitees via /respond when they accept -- rather
            # than through /config (which only the inviter can call
            # and which does a shallow dict.update, so it can't safely
            # merge into a nested dict other pods also write to).
            "config": {"customer_names": {inviter_id: inviter_name}},
            "acserver_instance": None,
            "created_at": time.time(),
            "ended_reason": None,
        }
        groups[group_id] = group

        pods[inviter_id]["status"] = "in_group"
        pods[inviter_id]["group_id"] = group_id
        for pid in invitee_ids:
            pods[pid]["status"] = "invited"
            pods[pid]["group_id"] = group_id

        _publish_to_group(group, "invited", group)
        return jsonify(group)


@app.route("/api/groups/<group_id>")
def api_get_group(group_id):
    with _lock:
        group = groups.get(group_id)
        if group is None:
            return jsonify({"error": "No such group"}), 404
        return jsonify(group)


@app.route("/api/groups/<group_id>/respond", methods=["POST", "OPTIONS"])
def api_respond(group_id):
    if request.method == "OPTIONS":
        return ""
    body = request.get_json(force=True, silent=True) or {}
    pod_id = body.get("pod_id")
    response = body.get("response")  # "accept" | "decline"
    customer_name = body.get("customer_name", "")

    with _lock:
        group = groups.get(group_id)
        if group is None:
            return jsonify({"error": "No such group"}), 404
        if pod_id not in group["invite_status"]:
            return jsonify({"error": f"Pod '{pod_id}' is not a member of this group"}), 403
        if group["state"] != "pending":
            return jsonify({"error": f"Group is '{group['state']}', can't respond now"}), 409
        if response not in ("accept", "decline"):
            return jsonify({"error": "response must be 'accept' or 'decline'"}), 400

        group["invite_status"][pod_id] = "accepted" if response == "accept" else "declined"
        if response == "accept" and pod_id in pods:
            pods[pod_id]["status"] = "in_group"
            group["config"]["customer_names"][pod_id] = customer_name or pod_id

        _publish_to_group(group, "member_responded", {"group_id": group_id, "pod_id": pod_id, "response": response})

        if response == "decline":
            # Whole shared session ends if anyone declines -- explicit
            # earlier decision, not an oversight.
            _end_group(group, reason=f"declined_by_{pod_id}")
        else:
            all_accepted = all(v == "accepted" for v in group["invite_status"].values())
            if all_accepted:
                _publish_to_group(group, "all_accepted", {"group_id": group_id})

        return jsonify(group)


@app.route("/api/groups/<group_id>/config", methods=["POST", "OPTIONS"])
def api_update_config(group_id):
    if request.method == "OPTIONS":
        return ""
    body = request.get_json(force=True, silent=True) or {}
    pod_id = body.get("pod_id")

    with _lock:
        group = groups.get(group_id)
        if group is None:
            return jsonify({"error": "No such group"}), 404
        if pod_id != group["inviter_pod_id"]:
            return jsonify({"error": "Only the inviter can update session config"}), 403
        if group["state"] != "pending":
            return jsonify({"error": f"Group is '{group['state']}', can't change config now"}), 409

        fields = {k: v for k, v in body.items() if k not in ("pod_id",)}
        group["config"].update(fields)
        _publish_to_group(group, "config_updated", {"group_id": group_id, "config": group["config"]})
        return jsonify(group)


@app.route("/api/groups/<group_id>/start", methods=["POST", "OPTIONS"])
def api_start_session(group_id):
    if request.method == "OPTIONS":
        return ""
    body = request.get_json(force=True, silent=True) or {}
    pod_id = body.get("pod_id")

    with _lock:
        group = groups.get(group_id)
        if group is None:
            return jsonify({"error": "No such group"}), 404
        if pod_id != group["inviter_pod_id"]:
            return jsonify({"error": "Only the inviter can start the session"}), 403
        if group["state"] != "pending":
            return jsonify({"error": f"Group is already '{group['state']}'"}), 409
        if not all(v == "accepted" for v in group["invite_status"].values()):
            return jsonify({"error": "Not everyone has accepted yet"}), 409

        try:
            pool_cfg = _load_pool_config()
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 500

        instance_id = _free_instance_id(pool_cfg)
        if instance_id is None:
            return jsonify({"error": "All 4 acServer instances are currently in use"}), 409

        instance = next(i for i in pool_cfg["instances"] if i["id"] == instance_id)
        cfg = group["config"]

        server_cfg_text = acserver_manager.build_server_cfg(
            acserver_manager.ServerSessionConfig(
                name=f"Kiosk group {group_id}",
                track=cfg.get("track_id", ""),
                track_layout=cfg.get("track_layout", ""),
                cars=[cfg.get("car_id", "")],
                session_type=cfg.get("session_type", "practice"),
                duration_minutes=int(cfg.get("duration_minutes", 20)),
                laps=50,
                udp_port=instance["port"],
                tcp_port=instance["port"],
                http_port=instance["http_port"],
                max_clients=len(group["member_pod_ids"]),
            )
        )
        drivers = [
            acserver_manager.Driver(
                car=cfg.get("car_id", ""),
                driver_name=cfg["customer_names"].get(pid, pid),
            )
            for pid in group["member_pod_ids"]
        ]
        entry_list_text = acserver_manager.build_entry_list(drivers)
        acserver_manager.write_instance_config(instance["config_dir"], server_cfg_text, entry_list_text)

        try:
            proc = acserver_manager.restart_instance(
                pool_cfg["acserver_exe"], instance["config_dir"], _running_instances.get(instance_id)
            )
            _running_instances[instance_id] = proc
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 500

        group["acserver_instance"] = instance_id
        group["state"] = "active"

        connection = {
            "server_ip": instance.get("server_ip", ""),
            "server_port": instance["port"],
            "server_http_port": instance["http_port"],
        }
        _publish_to_group(group, "session_started", {"group_id": group_id, "connection": connection, "config": cfg})
        return jsonify(group)


@app.route("/api/instances")
def api_list_instances():
    """Live view of all 4 pooled acServer instances: what's assigned
    to each (a customer group, an admin-started session, or nothing),
    and a best-effort status snapshot queried straight from that
    instance's own HTTP endpoint (see acserver_status.py) -- car/
    track/session/connected drivers, when it's actually running and
    reachable. This is the "show status of each server" piece from the
    real acServer setup: each pooled instance is a genuinely
    independent running acServer process on its own port, so its
    status is queried independently too, not inferred from this
    coordinator's own bookkeeping alone.
    """
    try:
        pool_cfg = _load_pool_config()
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 500

    with _lock:
        running_ids = set(_running_instances.keys())
        instances_snapshot = list(pool_cfg["instances"])
        assignments = {inst["id"]: _instance_assignment_locked(inst["id"]) for inst in instances_snapshot}

    result = []
    for inst in instances_snapshot:
        running = inst["id"] in running_ids
        live_status = None
        if running:
            live_status = acserver_status.query_instance_status(
                inst.get("server_ip", "127.0.0.1"), inst["http_port"]
            )
        result.append({
            "id": inst["id"],
            "port": inst["port"],
            "http_port": inst["http_port"],
            "running": running,
            "assignment": assignments[inst["id"]],
            "live_status": live_status,
        })
    return jsonify({"instances": result})


@app.route("/api/admin/instances/<int:instance_id>/start", methods=["POST", "OPTIONS"])
def api_admin_start_instance(instance_id):
    """Manually start (or reconfigure/restart) one pooled instance from
    the admin GUI -- not tied to any pod invite flow. Quick-controls
    scope: track, car(s), session type, duration/laps, max clients,
    password. If a customer group currently owns this instance, it
    gets ended first (Chad confirmed override-with-confirm is fine;
    the confirmation itself happens client-side in the admin GUI)."""
    if request.method == "OPTIONS":
        return ""
    body = request.get_json(force=True, silent=True) or {}
    name = (body.get("name") or f"Admin server {instance_id}").strip()
    track = (body.get("track") or body.get("track_id") or "").strip()
    track_layout = (body.get("track_layout") or "").strip()
    cars_raw = body.get("cars", [])
    if isinstance(cars_raw, str):
        cars = [c.strip() for c in cars_raw.split(",") if c.strip()]
    else:
        cars = [str(c).strip() for c in cars_raw if str(c).strip()]
    session_type = body.get("session_type", "practice")
    try:
        duration_minutes = int(body.get("duration_minutes", 20) or 20)
        laps = int(body.get("laps", 10) or 10)
        max_clients = int(body.get("max_clients", 4) or 4)
    except (TypeError, ValueError):
        return jsonify({"error": "duration_minutes, laps, and max_clients must be numbers"}), 400
    password = body.get("password", "") or ""

    if not track:
        return jsonify({"error": "track is required"}), 400
    if not cars:
        return jsonify({"error": "at least one car is required"}), 400
    if session_type not in ("practice", "race"):
        return jsonify({"error": "session_type must be 'practice' or 'race'"}), 400

    with _lock:
        try:
            pool_cfg = _load_pool_config()
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 500

        instance = next((i for i in pool_cfg["instances"] if i["id"] == instance_id), None)
        if instance is None:
            return jsonify({"error": f"No pooled instance with id {instance_id}"}), 404

        _end_group_on_instance_locked(instance_id, reason="admin_reassigned_instance")

        server_cfg_text = acserver_manager.build_server_cfg(
            acserver_manager.ServerSessionConfig(
                name=name,
                track=track,
                track_layout=track_layout,
                cars=cars,
                session_type=session_type,
                duration_minutes=duration_minutes,
                laps=laps,
                udp_port=instance["port"],
                tcp_port=instance["port"],
                http_port=instance["http_port"],
                max_clients=max_clients,
                password=password,
            )
        )
        # No pre-registered drivers for an admin-started session -- one
        # entry_list slot per allowed car, blank driver name/GUID, same
        # as pickup mode lets any client connect and claim a free slot.
        entry_list_text = acserver_manager.build_entry_list([acserver_manager.Driver(car=c) for c in cars])
        acserver_manager.write_instance_config(instance["config_dir"], server_cfg_text, entry_list_text)

        try:
            proc = acserver_manager.restart_instance(
                pool_cfg["acserver_exe"], instance["config_dir"], _running_instances.get(instance_id)
            )
            _running_instances[instance_id] = proc
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 500

        _admin_sessions[instance_id] = {
            "name": name,
            "track": track,
            "track_layout": track_layout,
            "cars": cars,
            "session_type": session_type,
            "duration_minutes": duration_minutes,
            "laps": laps,
            "max_clients": max_clients,
            "password_protected": bool(password),
            "started_at": time.time(),
        }
        assignment = _instance_assignment_locked(instance_id)

    return jsonify({
        "id": instance["id"],
        "port": instance["port"],
        "http_port": instance["http_port"],
        "running": True,
        "assignment": assignment,
        "live_status": None,
    })


@app.route("/api/admin/instances/<int:instance_id>/stop", methods=["POST", "OPTIONS"])
def api_admin_stop_instance(instance_id):
    """Stop one pooled instance from the admin GUI, whatever's
    currently using it -- an admin session, or (with the admin GUI's
    confirm dialog already shown) a live customer group, which gets
    ended the same way it would from POST /api/groups/<id>/end."""
    if request.method == "OPTIONS":
        return ""
    body = request.get_json(force=True, silent=True) or {}
    reason = body.get("reason", "admin_stopped")

    with _lock:
        try:
            pool_cfg = _load_pool_config()
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 500
        instance = next((i for i in pool_cfg["instances"] if i["id"] == instance_id), None)
        if instance is None:
            return jsonify({"error": f"No pooled instance with id {instance_id}"}), 404

        _end_group_on_instance_locked(instance_id, reason=reason)

        proc = _running_instances.pop(instance_id, None)
        acserver_manager.stop_instance(proc)
        _admin_sessions.pop(instance_id, None)

        assignment = _instance_assignment_locked(instance_id)
        running = instance_id in _running_instances

    return jsonify({
        "id": instance["id"],
        "port": instance["port"],
        "http_port": instance["http_port"],
        "running": running,
        "assignment": assignment,
        "live_status": None,
    })


@app.route("/admin")
@app.route("/admin/")
def admin_index():
    return send_from_directory(ADMIN_DIR, "index.html")


@app.route("/admin/<path:filename>")
def admin_static(filename):
    return send_from_directory(ADMIN_DIR, filename)


@app.route("/api/groups/<group_id>/end", methods=["POST", "OPTIONS"])
def api_end_session(group_id):
    if request.method == "OPTIONS":
        return ""
    body = request.get_json(force=True, silent=True) or {}
    pod_id = body.get("pod_id")
    reason = body.get("reason", "ended_by_participant")

    with _lock:
        group = groups.get(group_id)
        if group is None:
            return jsonify({"error": "No such group"}), 404
        if pod_id not in group["member_pod_ids"]:
            return jsonify({"error": f"Pod '{pod_id}' is not a member of this group"}), 403
        _end_group(group, reason=reason)
        return jsonify(group)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6000, threaded=True)
