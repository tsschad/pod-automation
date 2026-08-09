# Phase 1 — the kiosk picker (single-player + multiplayer)

The actual customer-facing app: a small local web app that replaces
`phase0`'s command-line test harness with a full-screen picker a
customer clicks (or later, drives with the wheel/pedals) through
themselves — name entry, mode choice, content pack, car, track,
Practice/Race, session length, AI opponents (single-player Race only),
confirm, launch. Multiplayer adds an invite-first flow before all of
that (see below).

## Scope of this pass

Keyboard and mouse/touch both work today in parallel; wheel/pedal
navigation isn't wired up yet, but the frontend is structured so it
can be added without a rewrite (see the comment at the top of
`static/app.js`).

Two extras beyond the original picker flow:

- **"All Cars & Tracks"** shows up automatically as an extra option
  on the pack-selection screen, alongside your curated packs from
  `packs.json` — no config needed. Picking it scans and lists
  everything actually installed under `ac_install_dir`, live, instead
  of a curated subset. Every pack card (curated or "All") shows a
  random preview image pulled from one of its own cars/tracks, tried
  in random order until one with an actual image on disk is found.
- **Random Car / Random Track** cards are prepended to the car and
  track carousels. Picking one immediately selects a uniformly random
  item from whatever list is currently showing — so it respects
  whichever pack (or "All") the customer is currently browsing, rather
  than pulling from the whole library regardless of context.

**Known gap, called out rather than left silent:** the 1-60 minute
duration slider sets `race.ini`'s `DURATION_MINUTES` directly for
Practice sessions (a verified, working field). Race sessions in AC
take a lap count instead — there's no verified way to make a native
race session just "run for N minutes" — so for Race this picker still
shows the same slider (matching the original requirement that
customers pick a length regardless of mode), but for now converts it
to a generous fixed lap count (50) and does **not** actually enforce
that time limit. Real time-based cutoffs (including the harder
requirement — ending a session early if a customer's *booked* time
runs out) need the external session-time-monitor component described
in the architecture brief. That's a separate, not-yet-built piece.

## What's in this folder

- `app.py` — the Flask backend: serves the picker UI, exposes the
  content-pack API, serves car/track preview images straight off disk,
  and handles `POST /api/session/start` (builds race.ini via
  `../common/race_ini.py` and launches via `../common/direct_launch.py`
  — the same proven mechanism `phase0` uses).
- `content_scan.py` — reads real installed AC content (car/track names,
  brand, preview images) straight from the same files Content Manager
  itself reads. Falls back gracefully (folder id as name, no preview)
  if a car/track's UI files are missing or a mod's install is
  incomplete — one broken car shouldn't take down the whole picker.
- `packs.py` + `packs.example.json` — loads the admin-curated content
  packs customers choose from. This stands in for the real admin GUI
  (a later phase); for now, packs are hand-edited JSON.
- `static/` — the actual picker UI: `index.html`, `style.css` (fixed
  dark kiosk theme — this runs full-screen on a pod display, not a
  normal browser tab, so it doesn't follow the host's light/dark
  setting), and `app.js` (all the screen logic and navigation).

## Setup

1. Copy `packs.example.json` to `packs.json` and fill in:
   - `ac_install_dir` — the pod's AC install folder (where `content/`
     lives)
   - `acs_exe` — full path to `acs.exe`
   - `packs` — your curated car/track lists, using the same folder ids
     as `phase0` (e.g. `ks_mazda_mx5_cup`, `ks_laguna_seca`)

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Run it:
   ```
   python app.py
   ```

4. Open `http://localhost:5000` in a browser — full-screen it (F11) to
   see it the way a customer would on the pod.

## Auto-clicking past the "Session information" screen

Same unresolved AC/CSP quirk as `phase0`: after launch, AC stops on a
pre-drive screen until you click the Drive (steering wheel) icon. This
is a per-pod setting (same icon, same screen, every session), so it
lives in `packs.json` rather than being something the customer or the
UI configures:

```json
"drive_click": {
  "enabled": true,
  "image": "drive_icon.png",
  "xy": "960,540",
  "backend": "pyautogui",
  "ahk_exe": "C:\\Program Files\\AutoHotkey\\v2\\AutoHotkey64.exe",
  "window_title": "assetto",
  "delay_seconds": 5,
  "timeout_seconds": 25,
  "hold_seconds": 0.12,
  "click_count": 1
}
```

Two ways to find the click target, same choice `phase0`'s
`--click-image` / `--click-xy` flags offered:

- **`"image"`** — path to a cropped screenshot of just the icon
  (relative paths resolve against this `phase1/` folder). Polls the
  screen for it and clicks its center. More robust to small layout
  shifts, but needs a clean crop.
- **`"xy"`** — a fixed `"X,Y"` screen coordinate, just clicks there
  after `delay_seconds`. Simpler, but breaks if resolution/layout
  changes.

**`"image"` wins if both are set.** To go back to coordinate-only
clicking, either delete the `"image"` line entirely or set it to
`""` — then `"xy"` is what gets used.

Steps:

1. Set `"enabled": true`.
2. Pick one: crop a screenshot of just the Drive/steering-wheel icon
   and save it as `drive_icon.png` here in `phase1/` for `"image"`
   mode, or find the pixel coordinate for `"xy"` mode (leave `"image"`
   empty to force this mode).
3. `"backend"` is `"pyautogui"` or `"ahk"` — same two options as
   `phase0`'s `--click-backend`. Use `"ahk"` if `pyautogui`'s click
   reports success but doesn't actually register in-game (a known
   fullscreen-input quirk — see `common/ahk_click.py`); it needs
   AutoHotkey v2 installed (https://www.autohotkey.com).
4. `pip install -r requirements.txt` again if you haven't already —
   it now includes `pyautogui` (only actually needed if
   `"backend": "pyautogui"`, but installed either way for simplicity).

Leave `"enabled": false` (or omit the whole `drive_click` block) and
this step is skipped entirely — the picker still launches sessions
fine, a customer would just need to click the icon manually.

## Multiplayer

**Status: built and logic-tested, not run on real hardware yet.** The
actual multiplayer join mechanism (`race.ini`'s `REMOTE` section +
direct launch) has never been tested on a pod — test this early rather
than assuming it works the way single-player's direct launch turned
out to. See `../control-pc/README.md` for the full picture; this is
just the pod-side setup.

1. Set up and run `../control-pc/coordinator.py` first (see its
   README).
2. Copy `mp_config.example.json` to `mp_config.json` on this pod and
   fill in:
   ```json
   { "pod_id": "pod1", "control_pc_url": "http://192.168.1.50:6000" }
   ```
   `pod_id` must be unique per pod (`pod1`, `pod2`, etc.). Do this on
   every pod, each with its own `pod_id`, all pointing at the same
   control PC.
3. `pip install -r requirements.txt` — no new dependencies beyond what
   single-player already needs.
4. Restart `python app.py` on each pod.

If a pod has no `mp_config.json`, it simply never offers Multiplayer
as an option (checked via `GET /api/mp/config`) — single-player works
identically either way, so this is safe to leave unset while testing.

**How it works, briefly:** each pod's browser opens one persistent
connection to the coordinator (Server-Sent Events) as soon as the app
loads — that's how a pod finds out it's been invited even while
sitting idle. The host picks who to invite *before* choosing
anything else, then goes through the same pack/car/track/session/
duration screens single-player uses (reused, not duplicated — see
`postMpConfig` calls sprinkled through `static/app.js`), broadcasting
each choice live to invited pods. The host picks the pack/car/track/
session for the whole group, not each player independently — a
scope decision explained in `../control-pc/README.md`. Once everyone
accepts, the host starts the session; the coordinator assigns one of
the 4 pooled acServer instances and every pod (host included) gets
told to join it.

**What isn't built:** ending a session automatically when a
participant's *booked* time runs out (needs the not-yet-built booking-
clock hook, same gap noted for single-player Race sessions), and each
player picking their own car independently.

## Trying it without real AC content

`content_scan.py` degrades gracefully if `ac_install_dir` doesn't
point at a real AC install, or a car/track id doesn't exist there: car
and track names just fall back to their folder id, and preview images
come back as a 404 (the picker shows "No preview" in that card instead
of breaking). So you can test the whole picker flow — packs, cars,
tracks, session setup, confirm — with a `packs.json` that references
ids that don't actually exist on the machine you're testing from.
Only the final "Start Session" launch step needs a real `acs_exe` path
and installed content to actually do anything.

## What's next

- Wire up wheel/pedal input (rotate = left/right, gas = select, brake
  = back) as a fast follow — `app.js`'s `mountCarousel`/`mountMenu`/
  `mountSlider` helpers are the three places that would read from a
  wheel input source instead of (or alongside) keyboard events.
- Testing multiplayer end-to-end on real pods — the join mechanism
  specifically is unverified (see the Multiplayer section above).
- Per-player car choice in multiplayer, instead of the host picking
  one car for the whole group.
- Real time-based session cutoffs, tied to the booking system's clock
  (separate phase — see the architecture brief's Section 4).
- Driver stats / results capture and the post-session results screen
  (separate phase).
- The admin GUI to replace hand-edited `packs.json` (separate phase).
