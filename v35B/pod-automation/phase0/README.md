# Phase 0 — proving the Content Manager URI handoff

This is the first piece of code for the pod automation project, matching
Phase 0 of the architecture brief: confirm that a Python script can launch
Assetto Corsa (single-player) and join a specific acServer instance
(multiplayer), entirely through Content Manager's `acmanager://` URI
protocol, with no clicking inside Content Manager itself.

Nothing else in the project depends on anything you can't test right here,
on one pod, in a few minutes.

## What's in this folder

- `phase0_test.py` — a command-line script that ties everything together,
  so you can fire a real test launch without writing any code yourself.

The actual launch mechanics (`race_ini.py`, `direct_launch.py`,
`cm_launcher.py`, `drive_click.py`, `ahk_click.py` + `drive_click.ahk`)
now live in `../common/` — moved there so `phase1`'s kiosk picker app can
reuse them without duplicating code. `phase0_test.py` still runs exactly
the same as before; it just imports from `../common` under the hood.

No third-party packages needed for the core flow — everything there is
Python standard library. The `--click-image`/`--click-xy` auto-click
fallback needs `pyautogui` (see `requirements.txt`); the `--click-backend
ahk` option needs AutoHotkey v2 installed separately (see below).

## Requirements

- One pod, with Assetto Corsa and Content Manager already installed and
  licensed (as they are today).
- Python 3.9 or newer installed on that pod. Windows doesn't ship with
  Python — grab it from python.org if it's not already there, and check
  "Add python.exe to PATH" during install.

## Running it

Copy this `phase0` folder onto a pod, open a command prompt in it, and run:

```
python phase0_test.py race --car ks_mazda_mx5_cup --track ks_laguna_seca
```

Swap in car/track IDs you actually have installed — these are folder
names, not display names. You can find them in Content Manager on the
car/track's detail page, or by looking at the folder names under
`...\Assetto Corsa\content\cars\` and `...\Assetto Corsa\content\tracks\`.

**What should happen:** Content Manager (if not already running) opens
briefly, and Assetto Corsa launches straight into a practice session with
that car and track. No clicks needed inside Content Manager.

Try a race with AI opponents:

```
python phase0_test.py race --car ks_mazda_mx5_cup --track ks_laguna_seca --session race --laps 5 --ai 3 --ai-level 95
```

And a direct multiplayer join, against one of your existing acServer
instances:

```
python phase0_test.py join --ip 192.168.1.50 --port 8081
```

(Use the acServer instance's **HTTP port**, not its raw UDP port — that's
what Content Manager's join command expects.)

**What should happen:** Content Manager opens and connects straight into
that server — no server browser, no manual clicks.

## The "Session information" screen and the Drive click

After a `direct` launch, Assetto Corsa loads the right car/track but
stops on a pre-drive "Session information" screen with a sidebar of
icons — you have to click the steering wheel ("Drive") icon to
actually start driving. No Content Manager or Custom Shaders Patch
setting was found to suppress this screen, so `direct` can optionally
automate that one click.

Install the extra dependency once:

```
pip install -r requirements.txt
```

**Recommended: image match.** Take a screenshot of the pod's screen
while the Session information panel is showing, crop it down tightly
to *just* the steering wheel icon (no surrounding background — the
tighter the crop, the more reliable the match), and save it as
`drive_icon.png` in this folder. Then:

```
python phase0_test.py direct --exe "...\acs.exe" --car ks_mazda_mx5_cup --track ks_laguna_seca --click-image drive_icon.png
```

It waits `--click-delay` seconds (default 5, for AC to actually load
the track) before it starts polling for the icon, then keeps looking
for up to `--click-timeout` seconds (default 25) and clicks the
moment it appears. This survives the icon being in a slightly
different spot next time.

**Fallback: fixed coordinate.** If the icon match isn't reliable, or
you just want to get moving faster, click a fixed screen position
instead — find the (x, y) pixel by hovering the mouse there and
checking Windows' cursor position, or via any screenshot tool:

```
python phase0_test.py direct --exe "...\acs.exe" --car ks_mazda_mx5_cup --track ks_laguna_seca --click-xy 960,540
```

This is brittle if the screen resolution or CSP sidebar layout ever
changes, but since the pods are fixed kiosks it should be stable in
practice.

**If it says "Clicked" but nothing happens in-game**, that's almost
always one of two things, both handled automatically now: Windows
display scaling making pyautogui's click land at the wrong physical
pixel, or the click landing on the terminal window instead of
Assetto Corsa because the terminal still had OS focus. If it's still
not working, add `--click-debug` — it prints the exact full path it
saved `click_before.png` / `click_after.png` to (always in this
`phase0` folder itself, regardless of what directory you ran `python`
from) so you can see exactly what was on screen and where the click
landed. Send those over and that'll be enough to diagnose further.

**If the target visibly highlights (hovers) but the click itself
doesn't register** — position/focus are correct, so the issue is the
press event itself. Two knobs to try:

```
python phase0_test.py direct ... --click-image drive_icon.png --click-hold 0.25 --click-count 2
```

`--click-hold` holds the mouse button down longer before releasing
(default 0.12s — some UIs ignore very short presses). `--click-count`
fires the whole press-release sequence more than once.

**If that still doesn't work: switch backends to AutoHotkey.** This is
a known failure mode — some fullscreen apps don't respond to the
OS-level synthetic input pyautogui uses (SendInput/mouse_event), even
though the cursor position itself is fine (hence the hover/highlight
working). AutoHotkey has a send mode built specifically for this,
`SendPlay`, which pushes events directly into the target window's
message queue instead of injecting at the OS input level.

1. Install AutoHotkey v2 on the pod: https://www.autohotkey.com (free,
   small installer, default settings are fine).
2. Add `--click-backend ahk` to the same command you were already
   running:
   ```
   python phase0_test.py direct --exe "...\acs.exe" --car ks_mazda_mx5_cup --track ks_laguna_seca --click-image drive_icon.png --click-backend ahk
   ```
   (Or `--click-xy` instead of `--click-image`, same as before.)

`ahk_click.py` shells out to `drive_click.ahk` (also in this folder)
to do the actual clicking — nothing else changes; race.ini writing and
the game launch itself are unaffected. If AutoHotkey isn't at the
default path (`C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe`), pass
`--ahk-exe "C:\path\to\AutoHotkey64.exe"`.

## If something doesn't work

The script prints the exact race.ini it generated and the exact URI it
sent to Content Manager. If the launch fails, is wrong, or Content Manager
shows an error, send those back along with whatever CM displayed — that's
enough to diagnose without needing remote access to a pod.

## Reference file status — updated 2026-08-08

Chad captured a real `race.ini` from a single-player Practice session
(one car, no AI, multiplayer inactive) and it's already been checked
against `race_ini.py` — see the module docstring at the top of that
file for the full list of what was confirmed correct and what got
fixed (HEADER.VERSION was wrong, several always-present sections were
missing entirely, LIGHTING was missing a field and had a sign error,
and a few others). The generator now reproduces that reference file
almost exactly (the only differences are cosmetic default values).

One good find from that file: its `[REMOTE]` section shows a `NAME`
field alongside the server connection details, suggesting a race.ini
with `REMOTE.ACTIVE=1` might be able to join a multiplayer server
*and* set the display name in one shot — which would resolve the
multiplayer-driver-name open question without a separate settings
write. Test it with:

```
python phase0_test.py mp-ini --ip 192.168.1.50 --http-port 10081 --port 11601 --name "Test Driver" --car ks_mazda_mx5_cup
```

Join a server this way and check whether your in-game name actually
shows as "Test Driver" rather than whatever AC's own player-name
setting says.

Still worth capturing, if you get the chance:

- **A Race-type session** (not Practice) — to confirm whether it uses
  `LAPS`, `DURATION_MINUTES`, or both, which matters for the time-based
  session slider described in the brief.
- **A session with AI opponents** — the `CAR_1`, `CAR_2`, etc.
  structure in `race_ini.py` is still an unverified guess.
- **Result file location.** Finish a race (through CM's UI or this
  script) and look for whatever result file AC/Content Manager writes
  afterward (lap times, best lap, position). This is what Section
  5.7/5.8 of the brief (driver stats and the post-session results
  screen) will be built on.

Same process as before: configure it in Content Manager's own UI,
find the race.ini AC actually used (`%USERPROFILE%\Documents\Assetto
Corsa\cfg\race.ini`), and paste it back the same way.

## What's next

Once this works on a real pod, Phase 1 is the actual single-player picker
UI — a small local web app that replaces this command-line script with
something a customer clicks through. That'll reuse `race_ini.py` and
`cm_launcher.py` exactly as they are here.
