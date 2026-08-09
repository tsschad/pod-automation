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

**Now run on real hardware, partially working.** A solo hosted session
(see `phase1/README.md`'s "Testing with only one pod online") gets all
the way through: coordinator picks a pooled instance, writes config,
launches `acServer.exe`, the pod builds `race.ini`'s `REMOTE` section
and launches `acs.exe` -- but AC's own connection attempt failed with
"Failed to connect: handshake failed" (a UDP-level failure inside AC's
networking, not an error from anything this project builds). Firewall
was ruled out (Chad confirmed disabling it entirely didn't fix this).
Three things addressed/investigated so far:

1. **Fixed:** `POST /api/groups/<id>/start` used to publish
   `session_started` (telling pods to connect) immediately after
   launching `acServer.exe` -- but a freshly-started process isn't
   necessarily listening for connections yet. It now polls the
   instance's own HTTP status endpoint (`acserver_status.py`) and waits
   for it to respond, up to 10s, before telling any pod to join.
2. **Ruled out:** a firewall blocking `acServer.exe`'s game port --
   confirmed not the cause (disabling the firewall entirely didn't fix
   it).
3. **Fixed, real mistake found:** `race.ini`'s `[REMOTE]` section had
   two wrong keys (`NAME`, `TEAM` -- not real fields at all) and was
   missing `SERVER_NAME`, caught by checking against the actual code
   Content Manager itself uses to write this section (AcTools'
   `Game.OnlineProperties.Set()`, same author, public source). See
   `common/race_ini.py`'s module docstring for the source link and
   full detail. Whether this alone explains "handshake failed" is
   still unconfirmed -- worth retesting before assuming there's more
   to fix.
4. **Leading remaining theory, needs checking on the actual pod:**
   `acs.exe` launched directly (not through Steam) may not have a
   valid Steamworks GUID available at handshake time unless Steam is
   actually running and logged in on that machine when it launches.
   Single-player direct launch never needed this (no server-side
   identity check), but a real multiplayer handshake very plausibly
   does. **Check: is Steam open and logged into an account on the pod
   when AC launches for a multiplayer session?** If not, try leaving
   Steam running and logged in, then retest. If Steam genuinely
   shouldn't run on these machines, the fallback is a `steam_appid.txt`
   file containing `244210` next to `acs.exe` -- a well-known trick for
   launching a Steam game's exe directly without Steam itself running,
   though its effect on server-side GUID validation specifically is
   unconfirmed and would need its own test.
5. **New evidence, points at the network itself:** Chad opened AC's
   own LAN server browser directly on a pod and refreshed -- it found
   zero servers, despite a real acServer instance confirmed running.
   LAN discovery works via UDP *broadcast*, a completely different
   mechanism from the point-to-point join, so both failing together
   independently is a real signal, not a coincidence. Pattern: every
   HTTP-based thing between a pod and this coordinator (registration,
   the admin GUI, acServer's own `/INFO` status check) has worked
   fine; the only two things that have failed on real hardware are
   both UDP. `../common/udp_probe.py` was built specifically to answer
   "is UDP even getting through between these two machines" with
   nothing AC-related in the way -- see its own docstring, or run:
   ```
   # on the control PC:
   python common/udp_probe.py serve --port 9601
   # on a pod:
   python common/udp_probe.py client --ip <control-pc-ip> --port 9601
   ```
   A clean REACHABLE/NOT REACHABLE answer here should settle whether
   this is a network/firewall/VPN issue vs. something still wrong in
   how this project builds `race.ini` or configures acServer.

`acserver_manager.py`'s `server_cfg.ini`/`entry_list.ini` format is
reconstructed from public AC dedicated-server documentation, **not**
verified against a real file — the same situation `race_ini.py` was in
before Chad captured a real reference file and it got corrected. If
you already have working acServer instances running, capturing one of
their real `server_cfg.ini`/`entry_list.ini` files and comparing would
settle this fast.

**Process model — two tiers, not one.** Vanilla `acServer.exe` can only
run a single server per OS process; that's just how the software
works, not a guess. So "one acServer instance running several
independent servers on different ports" (Chad's real setup, via his
"Assetto Corsa Server Manager" GUI tool and its saved presets like
S1-LMP1/GT3, S2-Hypercars, etc.) has to mean something is running
multiple `acServer.exe` processes behind a single-looking interface.

- **Pooled instances** (`instances` in `acserver_pool.json`, 4 of
  them): this coordinator owns their full lifecycle for customer
  bookings — one shared `acserver_exe` path, launched via subprocess
  up to 4 times, each pointed at its own config folder/port via
  `-c`/`-e`. Same thing Chad's Manager tool almost certainly does
  under the hood for its presets, just driven by this coordinator
  instead of a GUI, so a fresh customer session can get its own
  track/cars written and the process restarted to pick them up.
- **Watched servers** (`watched_servers` in `acserver_pool.json`,
  optional): servers Chad runs himself through his own Manager tool,
  independent of any booking (his "Test Hotlap", "Server 8", etc.
  presets). This coordinator never starts, stops, or reconfigures
  these — just label + `server_ip` + `http_port`, queried the same way
  as the pooled instances, for display only.

`GET /api/instances` returns both tiers. For both, live per-server
status (track, session, connected drivers) comes from querying each
instance's own HTTP endpoint directly (`acserver_status.py`) rather
than trusting this coordinator's own bookkeeping. **Confirmed working**
against one of Chad's real running instances (2026-08-09, `curl
http://192.168.86.200:8081/INFO` against "S1 - LMP1/GT3") — `GET
/INFO` on the HTTP_PORT returns JSON shaped like `{"name":...,
"clients":0,"maxclients":24,"track":"spa","cars":[...]}`. The admin
GUI shows a friendly one-line summary (`track · clients/maxclients`)
built from these confirmed field names, plus the full raw response
underneath for anything that summary doesn't cover.

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
   - `watched_servers` (optional) — any servers you run yourself
     through your own Manager tool that you just want visible in the
     admin GUI: `label`, `server_ip`, `http_port`. Leave this out
     entirely if you don't have any.

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Run it:
   ```
   python coordinator.py
   ```
   Listens on `0.0.0.0:8090`. (Not `6000` — Chrome and Firefox both
   refuse to connect to port `6000` at all, treating it as an "unsafe
   port" left over from X11, and will fail with `ERR_UNSAFE_PORT`
   with no useful explanation. Found the hard way; see the module
   docstring in `coordinator.py` if you ever need to change the port
   again — steer clear of the browser-blocked list linked there.)

4. Each pod needs `phase1/mp_config.json` pointing at this machine —
   see `phase1/README.md`.

5. Admin GUI: open `http://<this machine's LAN IP>:8090/admin` from any
   browser on the same network (the control PC itself, or your phone/
   laptop). No login — see the security note below.

## Admin GUI (`/admin`)

For Chad, not customers. Shows all 4 pooled instances as cards
(polling `GET /api/instances` every 3s) with a **Start…**/**Reassign…**
button and, once running, a **Stop** button. Below that, if
`watched_servers` is configured, a read-only "Other servers" table
(online/not-reachable + live status, no controls at all). Below that,
a read-only table of registered pods (id, IP, status, current group,
last seen).

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
Don't expose port 8090 outside the local network.

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

## Confirmed against real hardware

Unlike everything else on this page (all Flask-stub logic tests, no
real acServer), `acserver_status.py`'s `/INFO` status query has been
run against one of Chad's actual live acServer instances and works
exactly as documented in its module docstring. This is the one piece
of the acServer integration that's no longer a guess.

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
- Watched servers: `GET /api/instances` reports `reachable: true` and
  a real `live_status` for a watched server that's actually up,
  `reachable: false`/`live_status: null` for one that isn't, and no
  start/stop/config route exists for them at all — confirmed by
  checking the app's own route table. `acserver_pool.json` files
  written before this feature existed (no `watched_servers` key) still
  work, defaulting to an empty list.

Also verified directly (no Flask needed, since it's plain
`urllib`): `acserver_status.query_instance_status` fails soft to
`None` against an unreachable/empty address, and correctly parses a
real HTTP JSON response when one exists.

Not tested (can't be, without Flask/a browser/real hardware): the
actual HTTP/SSE wiring, CORS behavior in a real browser, the `/admin`
page's own JS/DOM rendering in an actual browser, or anything
involving `acServer.exe`/`acs.exe` actually running.
