# Control PC — coordinator + admin GUI

Runs on the control PC (the same machine that runs the 4 acServer
instances). Every pod's browser talks to this service directly for
anything multiplayer-related — who's online, sending and responding to
invites, live config updates as the host picks a pack/car/track, and
starting/ending a shared session. It also serves the admin GUI at
`/admin` — a page for Chad, not customers, to directly manage each of
the 4 pooled acServer instances (start/stop/reassign any of them by
hand, see who's actually online) independent of the customer invite
flow. See `coordinator.py`'s module docstring for the full state
model.

## Status

Built and logic-tested (state machine, authorization checks, decline/
timeout/end behavior — see below), but **not run on real hardware
yet**, and the multiplayer *join* mechanism itself
(`race.ini`'s `REMOTE` section + direct launch, in `phase1/app.py`'s
`/api/mp/join`) has never been tested on a real pod either — same
caveat `race_ini.py` and `phase0_test.py`'s `mp-ini` command have
carried since before single-player was proven out. Test this early,
the same way Phase 0 shook out the issues with the single-player path.

`acserver_manager.py`'s `server_cfg.ini`/`entry_list.ini` format is
reconstructed from public AC dedicated-server documentation, **not**
verified against a real file — the same situation `race_ini.py` was in
before Chad captured a real reference file and it got corrected. If
you already have working acServer instances running, capturing one of
their real `server_cfg.ini`/`entry_list.ini` files and comparing would
settle this fast.

**Process model, confirmed:** Chad's real setup is one acServer
install capable of running several independent server processes at
once, each on its own port — his "Assetto Corsa Server Manager" GUI
tool does exactly this with its saved presets (S1-LMP1/GT3,
S2-Hypercars, etc.). This coordinator does the same thing
programmatically rather than driving that GUI tool: one shared
`acserver_exe` path, launched via subprocess up to 4 times (once per
pooled instance in `acserver_pool.json`), each pointed at its own
config folder/port via `-c`/`-e`. Confirmed as the right approach — no
longer an open question. `GET /api/instances` additionally queries
each running instance's own HTTP status endpoint
(`acserver_status.py`) so live per-server status (track, session,
connected drivers) is available without trusting this coordinator's
own bookkeeping alone — that endpoint's `/INFO` path and response
shape are still unverified the same way the config file format is;
capture a real response from one of Chad's running instances to
confirm.

## Setup

1. Copy `acserver_pool.example.json` to `acserver_pool.json` and fill
   in:
   - `acserver_exe` — path to `acServer.exe`
   - 4 `instances`, each with its own `config_dir` (a folder this
     service writes `server_cfg.ini`/`entry_list.ini` into), `port`,
     `http_port`, and `server_ip` (the control PC's LAN IP — used both
     for pods to connect and for this coordinator's own status queries
     to that instance). One shared `acServer.exe` launched multiple
     times with `-c`/`-e` is the confirmed approach — see
     `acserver_manager.py`'s module docstring.

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Run it:
   ```
   python coordinator.py
   ```
   Listens on `0.0.0.0:6000`.

4. Each pod needs `phase1/mp_config.json` pointing at this machine —
   see `phase1/README.md`.

5. Admin GUI: open `http://<this machine's LAN IP>:6000/admin` from any
   browser on the same network (the control PC itself, or your phone/
   laptop). No login — see the security note below.

## Admin GUI (`/admin`)

For Chad, not customers. Shows all 4 pooled instances as cards
(polling `GET /api/instances` every 3s) with a **Start…**/**Reassign…**
button and, once running, a **Stop** button. Below that, a read-only
table of registered pods (id, IP, status, current group, last seen).

**Start / Reassign** opens a form for track, car(s) (comma-separated
IDs, matching the same IDs used in `packs.json`), session type,
duration or laps, max clients, and an optional password — the "quick
controls" subset of what `acserver_manager.py`'s `ServerSessionConfig`
supports, not the full settings surface Chad's "Assetto Corsa Server
Manager" tool exposes (assists, realism, dynamic track, voting/
banning stay at their built-in defaults for now — a reasonable next
step if the quick controls turn out to be too limited). No
pre-registered drivers for an admin-started session — pickup mode lets
anyone connect and claim a free car slot, same as walking up to any
public AC server.

**Overriding a live customer session is allowed, not blocked** — this
was an explicit choice (Chad confirmed "allow it with a confirm
dialog" over "block it"). If an instance is currently running a
customer group, the dialog says so before you confirm; starting or
stopping anyway ends that group the same way `POST /api/groups/<id>/
end` would (frees its pods, tells their kiosk apps the session ended)
rather than leaving stale state pointing at a server that's now doing
something else.

**Security note:** `/admin` has no authentication, same as the rest of
this coordinator's API — it relies entirely on the control PC's LAN
being closed to the public (see the CORS comment in `coordinator.py`).
Don't expose port 6000 outside the local network.

## Scope decision, flagged rather than assumed

The **host/inviter picks the pack, car, track, session type, and
duration for the whole group** — everyone races the same car, not each
person picking their own. This keeps `entry_list.ini` assignment
simple and the invite flow easy to follow for a first pass. Extending
to per-player car choice is a reasonable next step once the core join
mechanism is actually proven working on hardware — that's the bigger
unknown here, not this decision.

## Known gap, not built here

Nothing currently calls `_end_group(..., reason="time_expired")`
automatically. That needs the booking-system clock hook described in
the architecture brief (Section 4) — still not built, same gap already
flagged for `phase1`'s single-player Race sessions. The `/api/groups/
<id>/end` endpoint is ready for a future booking-time-monitor
component to call; nothing wires it up yet.

## What was actually tested (without Flask installed)

Flask isn't installable in the sandbox this was built in, so testing
worked the same way it did for `phase1`: stub out `flask`'s `Flask`/
`jsonify`/`request`/`Response` and call the route functions directly.
Verified:

- Full happy path: register 2+ pods → create a group → inviter updates
  config → invitees accept (with their name merged in via `/respond`,
  since only the inviter can call `/config`) → `all_accepted` → start
  (reaches `acserver_manager`, fails cleanly on a fake `acServer.exe`
  path, as expected in a sandbox with no real install).
- A decline ends the whole group and frees every member pod back to
  `idle` — matches the explicit multiplayer decision from earlier in
  the project (not a "only that pod drops out" behavior).
- Authorization: only the inviter can update config or start the
  session; a non-member can't respond to a group they're not in.
- `end_session` frees pods and releases the acServer instance
  regardless of what state the group was in.
- Admin routes: starting an idle instance from `/admin` tracks it in
  `_admin_sessions`; missing required fields (e.g. no track) reject
  with 400 and mutate nothing; `_free_instance_id` correctly skips an
  admin-held instance when the normal invite flow looks for a free
  one; `GET /api/instances` reports the right `assignment.type` for
  both an admin session and a customer group at the same time;
  reassigning an instance that's running a live customer group ends
  that group first (pods freed back to `idle`, `ended_reason` set)
  before the admin's new config takes over; stopping an instance frees
  it (`running: false`, `assignment: null`); stopping an already-idle
  instance is a harmless no-op.

Also verified directly (no Flask needed, since it's plain
`urllib`): `acserver_status.query_instance_status` fails soft to
`None` against an unreachable/empty address, and correctly parses a
real HTTP JSON response when one exists.

Not tested (can't be, without Flask/a browser/real hardware): the
actual HTTP/SSE wiring, CORS behavior in a real browser, the `/admin`
page's own JS/DOM rendering in an actual browser, or anything
involving `acServer.exe`/`acs.exe` actually running.
