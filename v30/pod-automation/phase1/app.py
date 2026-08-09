"""
app.py

Phase 1: the actual customer-facing single-player kiosk picker, as a
small local Flask web app. Meant to run full-screen in a browser on
each pod, replacing phase0_test.py's command-line harness with
something a customer can click (or, in a later phase, drive with the
wheel/pedals) through themselves.

Scope of this pass, deliberately: single-player only. Multiplayer's
invite-first flow is its own later phase. Wheel/pedal navigation is
not wired up yet either — the frontend's keyboard handling (arrow
keys to move focus, Enter to select, Backspace to go back) is
structured so that a wheel/pedal input layer can drive the same
actions later without restructuring the UI.

Known gap, called out rather than silently skipped: the 1-60 minute
session-length slider sets race.ini's DURATION_MINUTES directly for
Practice sessions (a real, verified field). For Race sessions, AC
takes a lap count instead of a duration (race.ini's LAPS field, per
race_ini.py) -- there's no verified way to make a native AC race
session simply "run for N minutes". So for Race, this picker still
shows the same duration slider (matching the original requirement:
customers choose session length regardless of mode), but converts it
to a generous fixed lap count for now and does NOT yet enforce a real
time-based cutoff. Actually stopping a race session at the customer's
chosen time (or when their booked time runs out) needs the external
session-time-monitor component from the architecture brief -- a
separate piece, not built in this pass.

Run it with:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000 in a browser (or point the pod's
kiosk browser at it directly).
"""

import json
import os
import random
import sys

from flask import Flask, jsonify, request, send_file, send_from_directory

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

from direct_launch import write_and_launch  # noqa: E402
from race_ini import RaceConfig, RemoteConfig, AIOpponent, build_race_ini  # noqa: E402

import content_scan
import packs

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
PACKS_JSON_PATH = os.path.join(APP_DIR, "packs.json")
MP_CONFIG_PATH = os.path.join(APP_DIR, "mp_config.json")

app = Flask(__name__, static_folder=None)

_config_cache = None
_mp_config_cache = None
_mp_config_loaded = False


def get_mp_config():
    """This pod's multiplayer identity (pod_id) and where to find the
    control PC's coordinator service. Separate from packs.json/get_config()
    and optional -- a pod with no mp_config.json just doesn't offer
    multiplayer (single-player still works fine), rather than the whole
    app failing to start. See mp_config.example.json."""
    global _mp_config_cache, _mp_config_loaded
    if not _mp_config_loaded:
        _mp_config_loaded = True
        if os.path.isfile(MP_CONFIG_PATH):
            with open(MP_CONFIG_PATH, "r", encoding="utf-8") as f:
                _mp_config_cache = json.load(f)
        else:
            _mp_config_cache = None
    return _mp_config_cache


def _run_drive_click(cfg: dict) -> None:
    """Optional post-launch step: click the Drive icon on AC's
    post-launch "Session information" screen, if configured via
    packs.json's "drive_click" block (see packs.example.json). This is
    a per-pod setting, not something a customer chooses -- same icon,
    same screen, every session -- so it lives in config rather than
    being passed per-request.

    Reuses common/drive_click.py (pyautogui) and common/ahk_click.py
    (AutoHotkey SendPlay, for when pyautogui's click reports success
    but doesn't actually register in-game -- see their module
    docstrings for the full story). Best-effort: prints a warning and
    returns rather than failing the request if the click doesn't work,
    since the game has already launched successfully by this point
    either way."""
    dc = cfg.get("drive_click") or {}
    if not dc.get("enabled"):
        return

    backend = dc.get("backend", "pyautogui")
    window_title = dc.get("window_title", "assetto")
    delay = float(dc.get("delay_seconds", 5))
    timeout = float(dc.get("timeout_seconds", 25))
    hold = float(dc.get("hold_seconds", 0.12))
    click_count = int(dc.get("click_count", 1))

    # Two ways to find the click target -- same choice phase0's
    # --click-image / --click-xy offered. Image match wins if both
    # "image" and "xy" are set; to force coordinate mode, either leave
    # "image" out of packs.json entirely or set it to "".
    image = dc.get("image", "")
    image_path = None
    if image:
        image_path = image if os.path.isabs(image) else os.path.join(APP_DIR, image)
        if not os.path.isfile(image_path):
            print(
                f"[app] drive_click.image is set but the file wasn't found "
                f"at {image_path!r} -- falling back to drive_click.xy if set, "
                f"otherwise skipping the auto-click.",
                flush=True,
            )
            image_path = None

    xy = dc.get("xy", "")
    xy_coords = None
    if xy:
        try:
            x_str, y_str = str(xy).split(",")
            xy_coords = (int(x_str.strip()), int(y_str.strip()))
        except ValueError:
            print(f"[app] drive_click.xy must be 'X,Y' (got {xy!r}) -- ignoring it.", flush=True)

    if not image_path and not xy_coords:
        print(
            "[app] drive_click.enabled is true but neither a valid 'image' "
            "nor 'xy' is configured -- skipping the auto-click. See "
            "phase1/README.md.",
            flush=True,
        )
        return

    try:
        if backend == "ahk":
            from ahk_click import click_image, click_xy
            ahk_exe = dc.get("ahk_exe", r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe")
            if image_path:
                click_image(
                    image_path,
                    ahk_exe=ahk_exe,
                    hold_ms=int(hold * 1000),
                    delay_ms=int(delay * 1000),
                    window_title=window_title,
                    timeout_ms=int(timeout * 1000),
                )
            else:
                click_xy(
                    xy_coords[0], xy_coords[1],
                    ahk_exe=ahk_exe,
                    hold_ms=int(hold * 1000),
                    delay_ms=int(delay * 1000),
                    window_title=window_title,
                )
        else:
            from drive_click import wait_and_click_image, click_at
            if image_path:
                wait_and_click_image(
                    image_path,
                    timeout=timeout,
                    initial_delay=delay,
                    window_title=window_title,
                    hold=hold,
                    click_count=click_count,
                )
            else:
                click_at(
                    xy_coords[0], xy_coords[1],
                    delay=delay,
                    window_title=window_title,
                    hold=hold,
                    click_count=click_count,
                )
        print("[app] Drive-icon auto-click: done.", flush=True)
    except Exception as exc:
        print(
            f"[app] Drive-icon auto-click failed ({exc}) -- the session is "
            f"still running, a customer may just need to click it manually "
            f"this time.",
            flush=True,
        )


def get_config() -> dict:
    """Loaded once and cached -- restart the app if you edit packs.json.
    Fine for a kiosk process that's already restarted between customers/
    sessions; revisit if that stops being true."""
    global _config_cache
    if _config_cache is None:
        _config_cache = packs.load_config(PACKS_JSON_PATH)
    return _config_cache


# ---------------------------------------------------------------- SPA


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/app.js")
def app_js():
    return send_from_directory(STATIC_DIR, "app.js")


@app.route("/style.css")
def style_css():
    return send_from_directory(STATIC_DIR, "style.css")


# ---------------------------------------------------------------- API


@app.route("/api/packs")
def api_packs():
    try:
        cfg = get_config()
    except packs.PacksConfigError as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"packs": packs.list_packs(cfg)})


@app.route("/api/packs/<pack_id>")
def api_pack_detail(pack_id):
    cfg = get_config()
    ac_dir = cfg["ac_install_dir"]

    if pack_id == packs.ALL_CONTENT_PACK_ID:
        # Not a curated pack -- every installed car/track, scanned live.
        # Can be slow-ish on a heavily-modded install (one JSON read +
        # file-existence check per item); acceptable for a one-time
        # per-pack-open cost on a local kiosk, not optimized further yet.
        label = packs.ALL_CONTENT_PACK_LABEL
        car_ids = content_scan.list_installed_car_ids(ac_dir)
        track_ids = content_scan.list_installed_track_ids(ac_dir)
    else:
        try:
            pack = packs.get_pack(cfg, pack_id)
        except packs.PacksConfigError as exc:
            return jsonify({"error": str(exc)}), 404
        label = pack.get("label", pack_id)
        car_ids = pack.get("cars", [])
        track_ids = pack.get("tracks", [])

    cars = []
    for car_id in car_ids:
        info = content_scan.car_info(ac_dir, car_id)
        cars.append({"id": info.car_id, "name": info.name, "brand": info.brand})

    tracks = []
    for track_id in track_ids:
        info = content_scan.track_info(ac_dir, track_id)
        tracks.append({
            "id": info.track_id,
            "name": info.name,
            "layouts": [{"id": l.layout_id, "name": l.name} for l in info.layouts],
        })

    return jsonify({"id": pack_id, "label": label, "cars": cars, "tracks": tracks})


@app.route("/api/packs/<pack_id>/preview")
def api_pack_preview(pack_id):
    """A representative image for the pack's own card on the pack-
    selection screen: a random preview from among its cars/tracks,
    tried in random order until one with an actual image on disk is
    found (falls through to 404, which the frontend shows as "No
    preview", if literally none of them have one)."""
    cfg = get_config()
    ac_dir = cfg["ac_install_dir"]

    if pack_id == packs.ALL_CONTENT_PACK_ID:
        car_ids = content_scan.list_installed_car_ids(ac_dir)
        track_ids = content_scan.list_installed_track_ids(ac_dir)
    else:
        try:
            pack = packs.get_pack(cfg, pack_id)
        except packs.PacksConfigError:
            return "", 404
        car_ids = pack.get("cars", [])
        track_ids = pack.get("tracks", [])

    candidates = [("car", cid) for cid in car_ids] + [("track", tid) for tid in track_ids]
    random.shuffle(candidates)

    for kind, content_id in candidates:
        if kind == "car":
            path = content_scan.car_info(ac_dir, content_id).preview_path
        else:
            info = content_scan.track_info(ac_dir, content_id)
            path = info.layouts[0].preview_path if info.layouts else None
        if path:
            return send_file(path)

    return "", 404


@app.route("/api/content/car/<car_id>/preview")
def api_car_preview(car_id):
    cfg = get_config()
    info = content_scan.car_info(cfg["ac_install_dir"], car_id)
    if not info.preview_path:
        return "", 404
    return send_file(info.preview_path)


@app.route("/api/content/track/<track_id>/preview")
def api_track_preview(track_id):
    layout_id = request.args.get("layout", "")
    cfg = get_config()
    info = content_scan.track_info(cfg["ac_install_dir"], track_id)
    for layout in info.layouts:
        if layout.layout_id == layout_id:
            if not layout.preview_path:
                return "", 404
            return send_file(layout.preview_path)
    return "", 404


@app.route("/api/session/start", methods=["POST"])
def api_session_start():
    cfg = get_config()
    body = request.get_json(force=True, silent=True) or {}

    required = ["customer_name", "car_id", "track_id", "session_type", "duration_minutes"]
    missing = [k for k in required if k not in body]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    session_type = body["session_type"]
    if session_type not in ("practice", "race"):
        return jsonify({"error": "session_type must be 'practice' or 'race'"}), 400

    ai_opponents = []
    if session_type == "race":
        ai_count = int(body.get("ai_count", 0))
        ai_level = int(body.get("ai_level", 95))
        for _ in range(ai_count):
            ai_opponents.append(AIOpponent(car=body["car_id"], ai_level=ai_level))

    race_cfg = RaceConfig(
        track=body["track_id"],
        track_layout=body.get("track_layout", ""),
        player_car=body["car_id"],
        driver_name=body["customer_name"] or "Guest Driver",
        session_type=session_type,
        duration_minutes=int(body["duration_minutes"]),
        # See module docstring: race sessions can't take a duration
        # natively yet, so we use a generous lap count as a stand-in
        # until the real time-based cutoff monitor exists.
        laps=50,
        ai_opponents=ai_opponents,
    )
    ini_text = build_race_ini(race_cfg)

    # Printed to the terminal running `python app.py` (which is already
    # being watched during testing) so a bad launch can be diagnosed
    # from the exact race.ini AC actually got, the same way phase0_test.py's
    # command-line output was used earlier -- rather than guessing blind.
    print("----- Generated race.ini -----", flush=True)
    print(ini_text, flush=True)
    print("-------------------------------", flush=True)
    print(f"TRACK={race_cfg.track}  CONFIG_TRACK={race_cfg.track_layout!r}  MODEL={race_cfg.player_car}", flush=True)

    try:
        written_path = write_and_launch(ini_text, cfg["acs_exe"])
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 500

    # Optional, config-driven (see _run_drive_click / packs.example.json's
    # "drive_click" block) -- clicks past AC's post-launch "Session
    # information" screen if set up. No-op if not configured, so this
    # is safe to leave in place either way.
    _run_drive_click(cfg)

    return jsonify({"status": "launched", "race_ini_path": written_path})


# ------------------------------------------------------------- Multiplayer
#
# The invite/group/live-status logic lives on the control PC's
# coordinator.py, not here -- the frontend talks to it directly (see
# mp_config.json / GET /api/mp/config below for how it finds it).
# This app only needs one more thing the browser genuinely can't do
# itself: writing race.ini and launching acs.exe once a session starts.


@app.route("/api/mp/config")
def api_mp_config():
    """Tells the frontend this pod's identity and where the control
    PC's coordinator lives, so it knows whether to offer Multiplayer
    at all and where to send its API calls / open its SSE connection."""
    mp_cfg = get_mp_config()
    if mp_cfg is None:
        return jsonify({"available": False})
    return jsonify({"available": True, "pod_id": mp_cfg["pod_id"], "control_pc_url": mp_cfg["control_pc_url"]})


@app.route("/api/mp/join", methods=["POST"])
def api_mp_join():
    """Called once this pod's frontend receives a "session_started"
    event from the coordinator with connection details for the
    assigned acServer instance. Builds a race.ini with REMOTE populated
    (see race_ini.py's RemoteConfig) and direct-launches acs.exe --
    same write-then-launch mechanism as single-player, just joining a
    server instead of starting a local session.

    STATUS: unverified end-to-end on real hardware, same caveat noted
    in race_ini.py and phase0_test.py's `mp-ini` command -- this is the
    natural extension of what's already proven to work for
    single-player, but multiplayer join specifically hasn't been
    tested yet. Test this early."""
    body = request.get_json(force=True, silent=True) or {}

    required = ["server_ip", "server_port", "server_http_port", "car_id", "customer_name"]
    missing = [k for k in required if k not in body]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    cfg = get_config()

    race_cfg = RaceConfig(
        track=body.get("track_id", ""),
        track_layout=body.get("track_layout", ""),
        player_car=body["car_id"],
        driver_name=body["customer_name"] or "Guest Driver",
        remote=RemoteConfig(
            server_ip=body["server_ip"],
            server_http_port=int(body["server_http_port"]),
            server_port=int(body["server_port"]),
            requested_car=body["car_id"],
        ),
    )
    ini_text = build_race_ini(race_cfg)

    print("----- Generated race.ini (multiplayer REMOTE) -----", flush=True)
    print(ini_text, flush=True)
    print("-----------------------------------------------------", flush=True)

    try:
        written_path = write_and_launch(ini_text, cfg["acs_exe"])
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 500

    _run_drive_click(cfg)

    return jsonify({"status": "launched", "race_ini_path": written_path})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
