"""
phase0_test.py

Run this ON A POD (Windows, with Assetto Corsa + Content Manager
already installed and licensed) to confirm the acmanager:// URI
handoff actually works on your real setup, before anything else gets
built on top of it. This is the entire scope of Phase 0 from the
architecture brief.

Examples
--------
The `race` command (via Content Manager's acmanager://race/config URI)
did NOT work in testing — see direct_launch.py and the `direct`
command below for the working alternative. Kept here for reference in
case a future CM version or a different parameter format resolves it.

Write race.ini directly and launch the game exe (the approach that
replaced `race`):
    python phase0_test.py direct --exe "C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\acs.exe" --car ks_mazda_mx5_cup --track ks_laguna_seca

Same, but also auto-click the "Drive" (steering wheel) icon on the
post-launch "Session information" screen — no CSP/CM setting was found
to suppress that screen, so this automates the one manual click that's
left (see drive_click.py):
    python phase0_test.py direct --exe "...\acs.exe" --car ks_mazda_mx5_cup --track ks_laguna_seca --click-image drive_icon.png

Or with a fixed coordinate instead of image matching:
    python phase0_test.py direct --exe "...\acs.exe" --car ks_mazda_mx5_cup --track ks_laguna_seca --click-xy 960,540

If pyautogui's click reports success but nothing happens in-game (the
cursor visibly hovers/highlights the target, but the press itself
doesn't register), switch to the AutoHotkey SendPlay backend instead
-- requires AutoHotkey v2 installed (see ahk_click.py):
    python phase0_test.py direct --exe "...\acs.exe" --car ks_mazda_mx5_cup --track ks_laguna_seca --click-image drive_icon.png --click-backend ahk

Launch a single-player practice session (untested path, see above):
    python phase0_test.py race --car ks_mazda_mx5_cup --track ks_laguna_seca

Launch a race with 3 AI opponents:
    python phase0_test.py race --car ks_mazda_mx5_cup --track ks_laguna_seca ^
        --session race --laps 5 --ai 3 --ai-level 95

Join a specific acServer instance directly (skip the server browser):
    python phase0_test.py join --ip 192.168.1.50 --port 8081

Test whether a race.ini's REMOTE section can join AND set your
multiplayer name in one shot (see race_ini.py's module docstring for
why this matters — it may resolve the multiplayer-driver-name question
without needing a separate settings write):
    python phase0_test.py mp-ini --ip 192.168.1.50 --http-port 10081 --port 11601 --name "Test Driver"

What "success" looks like
--------------------------
`race`:  Content Manager opens (briefly, or not at all if it's already
         running) and Assetto Corsa launches straight into the session
         you specified — no clicks needed in CM's own UI.
`join`:  Content Manager opens and connects straight into the acServer
         instance at the given IP/port — no server browser.

If either doesn't work, the script prints the exact URI it sent to
Content Manager and the race.ini it generated (for `race`) — paste
both back along with whatever Content Manager shows on screen, and
we'll fix whatever field/format is off.

Finding car/track folder IDs
-----------------------------
These are the folder names Content Manager uses internally, not the
display names. Easiest way to find them: in Content Manager, open the
car or track's detail page — the folder id is usually shown in the
UI or in the address bar of CM's content browser. They also match the
folder names under:
    ...\\Assetto Corsa\\content\\cars\\<car_id>
    ...\\Assetto Corsa\\content\\tracks\\<track_id>
"""

import argparse
import os
import sys

# race_ini.py, direct_launch.py, etc. now live in ../common — shared with
# phase1's kiosk app rather than duplicated. This makes them importable
# the same flat way (`from race_ini import ...`) regardless of where
# `python phase0_test.py` is actually run from.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))

from cm_launcher import launch_race, join_online_server
from direct_launch import write_and_launch, race_ini_path, find_all_race_ini
from drive_click import wait_and_click_image, click_at
from race_ini import RaceConfig, RemoteConfig, AIOpponent, build_race_ini


def cmd_race(args: argparse.Namespace) -> None:
    ai_opponents = [
        AIOpponent(
            car=args.ai_car or args.car,
            ai_level=args.ai_level,
            ai_aggression=args.ai_aggression,
        )
        for _ in range(args.ai)
    ]

    cfg = RaceConfig(
        track=args.track,
        track_layout=args.layout,
        player_car=args.car,
        player_skin=args.skin,
        driver_name=args.name,
        session_type=args.session,
        laps=args.laps,
        duration_minutes=args.minutes,
        ai_opponents=ai_opponents,
    )
    ini_text = build_race_ini(cfg)

    print("----- Generated race.ini -----")
    print(ini_text)
    print("-------------------------------")

    uri = launch_race(ini_text)
    print(f"\nOpened URI ({len(uri)} chars total, truncated below):")
    print(uri[:200] + ("..." if len(uri) > 200 else ""))
    print(
        "\nIf Assetto Corsa didn't launch, or launched with the wrong "
        "settings, compare the race.ini above against a reference file "
        "captured from Content Manager's own UI (see README.md)."
    )


def cmd_direct(args: argparse.Namespace) -> None:
    """Bypass Content Manager's URI protocol entirely: write race.ini
    to the exact path AC reads it from, then launch the game exe
    directly. See direct_launch.py for why."""
    ai_opponents = [
        AIOpponent(
            car=args.ai_car or args.car,
            ai_level=args.ai_level,
            ai_aggression=args.ai_aggression,
        )
        for _ in range(args.ai)
    ]

    cfg = RaceConfig(
        track=args.track,
        track_layout=args.layout,
        player_car=args.car,
        player_skin=args.skin,
        driver_name=args.name,
        session_type=args.session,
        laps=args.laps,
        duration_minutes=args.minutes,
        ai_opponents=ai_opponents,
    )
    ini_text = build_race_ini(cfg)

    print("----- Generated race.ini -----")
    print(ini_text)
    print("-------------------------------")
    print(f"Will write to: {race_ini_path()}")
    print(f"Will launch: {args.exe}")

    path = write_and_launch(ini_text, args.exe)
    print(f"\nWrote race.ini to {path} and launched {args.exe}.")
    print(
        "\nIf Assetto Corsa launched but ignored the race.ini (e.g. showed "
        "its normal menu instead of jumping into the session), that command "
        "line likely needs an argument telling it to read race.ini on "
        "startup rather than just being enough to write the file. Let me "
        "know exactly what happened."
    )

    if args.click_backend == "ahk":
        _do_ahk_click(args)
    else:
        _do_pyautogui_click(args)


def _do_pyautogui_click(args: argparse.Namespace) -> None:
    if args.click_image:
        print(
            f"\nWaiting up to {args.click_timeout}s (after a {args.click_delay}s "
            f"head start) for {args.click_image} to appear on screen, then "
            "clicking it (pyautogui backend)..."
        )
        try:
            loc = wait_and_click_image(
                args.click_image,
                timeout=args.click_timeout,
                confidence=args.click_confidence,
                initial_delay=args.click_delay,
                window_title=args.click_window,
                debug=args.click_debug,
                hold=args.click_hold,
                click_count=args.click_count,
            )
            print(f"Clicked Drive icon at {loc}.")
        except TimeoutError as exc:
            print(f"\n{exc}")
            print(
                "The crop probably doesn't match what's on screen closely "
                "enough. Re-crop drive_icon.png tighter around just the "
                "steering wheel icon (no surrounding background), or try "
                "--click-xy as a fallback."
            )
    elif args.click_xy:
        try:
            x_str, y_str = args.click_xy.split(",")
            x, y = int(x_str.strip()), int(y_str.strip())
        except ValueError:
            print(f"\n--click-xy must be 'X,Y' (got {args.click_xy!r}) — skipping click.")
        else:
            print(f"\nWaiting {args.click_delay}s, then clicking ({x}, {y}) (pyautogui backend)...")
            click_at(
                x, y,
                delay=args.click_delay,
                window_title=args.click_window,
                debug=args.click_debug,
                hold=args.click_hold,
                click_count=args.click_count,
            )
            print("Clicked.")


def _do_ahk_click(args: argparse.Namespace) -> None:
    """Same click, driven through AutoHotkey's SendPlay mode instead
    of pyautogui — try this if pyautogui reports a successful click
    but nothing happens in-game (see ahk_click.py for why)."""
    from ahk_click import click_xy, click_image

    hold_ms = int(args.click_hold * 1000)
    delay_ms = int(args.click_delay * 1000)

    if args.click_image:
        print(
            f"\n[AHK] Waiting up to {args.click_timeout}s (after a "
            f"{args.click_delay}s head start) for {args.click_image} to "
            "appear on screen, then clicking it via SendPlay..."
        )
        try:
            click_image(
                args.click_image,
                ahk_exe=args.ahk_exe,
                hold_ms=hold_ms,
                delay_ms=delay_ms,
                window_title=args.click_window,
                timeout_ms=int(args.click_timeout * 1000),
            )
            print("AHK reported a successful click.")
        except (TimeoutError, RuntimeError, FileNotFoundError) as exc:
            print(f"\n{exc}")
    elif args.click_xy:
        try:
            x_str, y_str = args.click_xy.split(",")
            x, y = int(x_str.strip()), int(y_str.strip())
        except ValueError:
            print(f"\n--click-xy must be 'X,Y' (got {args.click_xy!r}) — skipping click.")
            return
        print(f"\n[AHK] Waiting {args.click_delay}s, then clicking ({x}, {y}) via SendPlay...")
        try:
            click_xy(
                x, y,
                ahk_exe=args.ahk_exe,
                hold_ms=hold_ms,
                delay_ms=delay_ms,
                window_title=args.click_window,
            )
            print("AHK reported a successful click.")
        except (RuntimeError, FileNotFoundError) as exc:
            print(f"\n{exc}")


def cmd_find_ini(args: argparse.Namespace) -> None:
    """Search the filesystem for every race.ini, to settle the real
    path empirically instead of guessing. Run this, then look at which
    one has a recent modified time after you've raced or used Quick
    Drive in Content Manager — that's the real one."""
    import datetime

    print(f"Searching under: {args.root or '(user profile)'} ... this can take a minute.\n")
    results = find_all_race_ini(args.root)
    if not results:
        print("No race.ini found anywhere under that root.")
        return
    print(f"Found {len(results)} file(s) named race.ini:\n")
    for path, mtime in sorted(results, key=lambda r: (r[1] or 0), reverse=True):
        when = datetime.datetime.fromtimestamp(mtime).isoformat(timespec="seconds") if mtime else "unknown"
        print(f"  {when}   {path}")
    print(
        "\nThe one with the most recent timestamp right after you race or "
        "use Quick Drive is the real one AC reads. Compare it against what "
        "race_ini_path() in direct_launch.py currently computes — tell me "
        "if they don't match and I'll fix the path logic."
    )
    print(f"\ndirect_launch.py currently computes: {race_ini_path()}")


def cmd_join(args: argparse.Namespace) -> None:
    uri = join_online_server(args.ip, args.port, args.password)
    print(f"Opened URI:\n{uri}")
    print(
        "\nIf Content Manager didn't connect, double-check --port is the "
        "acServer instance's HTTP port (not its raw UDP port), and that "
        "the instance is actually running."
    )


def cmd_mp_ini(args: argparse.Namespace) -> None:
    """Build (and optionally launch) a race.ini with REMOTE populated,
    to join a server directly via acs.exe -- no Content Manager
    involved. Field names confirmed against AcTools' actual join code
    (see race_ini.py's module docstring); driver display name comes
    from --name via [CAR_0].DRIVER_NAME as normal, not from REMOTE
    itself (an earlier theory that REMOTE had its own NAME field was
    wrong, fixed 2026-08-09)."""
    cfg = RaceConfig(
        track=args.track or "ks_red_bull_ring",
        track_layout=args.layout,
        player_car=args.car or "ks_nissan_gtr_gt3",
        driver_name=args.name,
        remote=RemoteConfig(
            server_ip=args.ip,
            server_http_port=args.http_port,
            server_port=args.port,
            password=args.password,
            requested_car=args.car or "",
        ),
    )
    ini_text = build_race_ini(cfg)

    print("----- Generated race.ini (REMOTE section) -----")
    print(ini_text)
    print("-------------------------------------------------")

    uri = launch_race(ini_text)
    print(f"\nOpened URI ({len(uri)} chars total, truncated below):")
    print(uri[:200] + ("..." if len(uri) > 200 else ""))
    print(
        "\nCheck two things once connected: (1) did it connect at all, "
        "and (2) does your in-game/scoreboard name show as --name rather "
        "than whatever AC's own player-name setting says. If both are "
        "yes, this is a cleaner path for multiplayer than the separate "
        "race/online/join URI plus a settings write."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 0 test harness: confirms the Content Manager "
                    "acmanager:// URI handoff works on this pod."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_race = sub.add_parser("race", help="Launch a single-player session.")
    p_race.add_argument("--car", required=True, help="Player's car folder id, e.g. ks_mazda_mx5_cup")
    p_race.add_argument("--track", required=True, help="Track folder id, e.g. ks_laguna_seca")
    p_race.add_argument("--layout", default="", help="Track layout/config name, if the track has one")
    p_race.add_argument("--name", default="Test Driver", help="Driver name to test name entry")
    p_race.add_argument("--skin", default="0", help="Skin folder id/index; blank is unverified as safe, default '0'")
    p_race.add_argument("--session", choices=["practice", "race"], default="practice")
    p_race.add_argument("--laps", type=int, default=5, help="Used when --session race")
    p_race.add_argument("--minutes", type=int, default=20, help="Used when --session practice")
    p_race.add_argument("--ai", type=int, default=0, help="Number of AI opponents")
    p_race.add_argument("--ai-car", dest="ai_car", default="", help="AI car id; defaults to --car if omitted")
    p_race.add_argument("--ai-level", dest="ai_level", type=int, default=97, help="AI skill, ~80-100")
    p_race.add_argument("--ai-aggression", dest="ai_aggression", type=int, default=50, help="AI aggression, 0-100")
    p_race.set_defaults(func=cmd_race)

    p_direct = sub.add_parser("direct", help="Write race.ini + launch acs.exe directly, bypassing CM's URI protocol.")
    p_direct.add_argument("--exe", required=True, help=r"Full path to acs.exe, e.g. C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\acs.exe")
    p_direct.add_argument("--car", required=True, help="Player's car folder id, e.g. ks_mazda_mx5_cup")
    p_direct.add_argument("--track", required=True, help="Track folder id, e.g. ks_laguna_seca")
    p_direct.add_argument("--layout", default="", help="Track layout/config name, if the track has one")
    p_direct.add_argument("--name", default="Test Driver", help="Driver name to test name entry")
    p_direct.add_argument("--skin", default="0", help="Skin folder id/index")
    p_direct.add_argument("--session", choices=["practice", "race"], default="practice")
    p_direct.add_argument("--laps", type=int, default=5, help="Used when --session race")
    p_direct.add_argument("--minutes", type=int, default=20, help="Used when --session practice")
    p_direct.add_argument("--ai", type=int, default=0, help="Number of AI opponents")
    p_direct.add_argument("--ai-car", dest="ai_car", default="", help="AI car id; defaults to --car if omitted")
    p_direct.add_argument("--ai-level", dest="ai_level", type=int, default=97, help="AI skill, ~80-100")
    p_direct.add_argument("--ai-aggression", dest="ai_aggression", type=int, default=50, help="AI aggression, 0-100")
    p_direct.add_argument("--click-image", dest="click_image", default="", help="Path to a cropped screenshot of the Drive/steering-wheel icon; if given, waits for it to appear on screen and clicks it")
    p_direct.add_argument("--click-xy", dest="click_xy", default="", help="Fallback: fixed 'X,Y' screen coordinate to click instead of image matching")
    p_direct.add_argument("--click-delay", dest="click_delay", type=float, default=5.0, help="Seconds to wait after launch before clicking/searching (AC load time)")
    p_direct.add_argument("--click-timeout", dest="click_timeout", type=float, default=25.0, help="Seconds to keep searching for --click-image before giving up")
    p_direct.add_argument("--click-confidence", dest="click_confidence", type=float, default=0.85, help="Image match confidence 0-1 (needs opencv-python installed; ignored otherwise)")
    p_direct.add_argument("--click-window", dest="click_window", default="Assetto Corsa", help="Substring of the game window's title to focus before clicking (fixes clicks being swallowed by the terminal)")
    p_direct.add_argument("--click-debug", dest="click_debug", action="store_true", help="Save click_before.png/click_after.png screenshots so you can see exactly what was on screen and where the click landed")
    p_direct.add_argument("--click-hold", dest="click_hold", type=float, default=0.12, help="Seconds to hold the mouse button down before releasing (some UIs ignore very short presses)")
    p_direct.add_argument("--click-count", dest="click_count", type=int, default=1, help="Number of times to press-hold-release, in case a single click doesn't register")
    p_direct.add_argument("--click-backend", dest="click_backend", choices=["pyautogui", "ahk"], default="pyautogui", help="How to simulate the click. 'ahk' uses AutoHotkey's SendPlay mode, which works with fullscreen apps that ignore pyautogui's clicks (requires AutoHotkey v2 installed)")
    p_direct.add_argument("--ahk-exe", dest="ahk_exe", default=r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe", help="Path to AutoHotkey64.exe, if using --click-backend ahk and it's not in the default install location")
    p_direct.set_defaults(func=cmd_direct)

    p_find = sub.add_parser("find-ini", help="Search the filesystem for every race.ini, to settle the real path.")
    p_find.add_argument("--root", default="", help="Where to search; defaults to your whole user profile")
    p_find.set_defaults(func=cmd_find_ini)

    p_join = sub.add_parser("join", help="Join a multiplayer acServer instance directly.")
    p_join.add_argument("--ip", required=True, help="Control PC's LAN IP")
    p_join.add_argument("--port", type=int, required=True, help="acServer instance's HTTP port")
    p_join.add_argument("--password", default="", help="Server password, if set")
    p_join.set_defaults(func=cmd_join)

    p_mp = sub.add_parser("mp-ini", help="Test joining + naming via a race.ini REMOTE section instead of race/online/join.")
    p_mp.add_argument("--ip", required=True, help="Control PC's LAN IP")
    p_mp.add_argument("--http-port", dest="http_port", type=int, required=True, help="acServer instance's HTTP port")
    p_mp.add_argument("--port", type=int, required=True, help="acServer instance's raw UDP/game port")
    p_mp.add_argument("--name", default="Test Driver", help="Name to test showing up as in the session")
    p_mp.add_argument("--password", default="", help="Server password, if set")
    p_mp.add_argument("--car", default="", help="Car id to request; leave blank to let the server assign one")
    p_mp.add_argument("--track", default="", help="Only used to fill out the local race.ini fields; shouldn't matter for joining")
    p_mp.add_argument("--layout", default="")
    p_mp.set_defaults(func=cmd_mp_ini)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
