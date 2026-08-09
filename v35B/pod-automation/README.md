# Pod automation — The Swing Spot

Custom software to run 4 Assetto Corsa sim-racing pods against a central
control PC: a self-serve kiosk UI on each pod (single player vs.
multiplayer, curated content packs, wheel/pedal navigation, time-based
sessions tied to bookings) and an admin GUI on the control PC (content
packs, live pod/server status, customer check-in, driver stats).

See the full feasibility and architecture brief (shared separately as a
Word doc) for the complete design. This repo is the actual code, built up
phase by phase against that plan.

## Layout

- `common/` — the shared launch mechanics used by every phase: builds
  `race.ini` (`race_ini.py`), writes it to the right path and launches
  `acs.exe` directly (`direct_launch.py`), the now-deprecated Content
  Manager URI approach (`cm_launcher.py`, kept for reference), and the
  Drive-icon auto-click workaround for the post-launch "Session
  information" screen (`drive_click.py` / `ahk_click.py` +
  `drive_click.ahk`).
- `phase0/` — the command-line proof-of-concept (`phase0_test.py`) that
  exercises everything in `common/` from the terminal, for testing
  directly on a pod without any UI. See `phase0/README.md`.
- `phase1/` — the real customer-facing kiosk picker: a small local Flask
  app + full-screen web UI, covering both single-player (content pack,
  car, track, Practice/Race, session length, AI opponents, confirm,
  launch) and multiplayer (invite-first flow, live status via the
  control PC coordinator). Reads real installed AC content for car/track
  names and preview images. See `phase1/README.md`.
- `control-pc/` — the control PC's multiplayer coordinator service: pod
  registry, invites/groups, live config broadcast, and the 4-instance
  acServer pool (writing `server_cfg.ini`/`entry_list.ini`, starting/
  stopping instances, and querying each running instance's own live
  status). Also serves the admin GUI at `/admin` — manually start,
  stop, or reassign any of the 4 pooled acServer instances directly,
  outside the customer invite flow. See `control-pc/README.md`.

Later phases (driver stats/results, the booking-clock integration for
real time-based cutoffs, content-pack management in the admin GUI)
will land here as they're built.

## Status

Phase 0 complete enough to build on: `race_ini.py` is validated against a
real single-player Practice race.ini from a pod, and the direct
write-race.ini-then-launch-acs.exe mechanism is proven on real hardware
(right car/track loads). Open items: a Race-type session capture (to
confirm LAPS vs. DURATION_MINUTES), a capture with AI opponents in the
grid, the result-file format/location, and getting past the post-launch
"Session information" screen without a manual click (currently tracked
as a to-do — see `phase0/README.md`, and `phase1/README.md`'s
`drive_click` config for the same mechanism wired into the kiosk app).

Phase 1's single-player picker has been tested on real hardware and
several real bugs fixed along the way (see git history) — car/track
selection, launch, and the foreground-focus fix all confirmed working.

Phase 1's multiplayer flow + the control PC coordinator (including the
`/admin` GUI for manually managing the 4 pooled acServer instances)
are built and logic-tested (state machine, authorization, decline/
timeout/end behavior, admin start/stop/reassign — see
`control-pc/README.md`), but **not yet run on real hardware**. The
multiplayer join mechanism itself (`race.ini`'s `REMOTE` section) and
the acServer config format are both best-effort, unverified the same
way single-player's launch mechanism was before Phase 0 testing caught
the issues with it — test this early rather than assuming it works.
