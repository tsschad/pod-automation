"""
ahk_click.py

Alternative to drive_click.py's pyautogui-based click: drives the
"click the Drive icon" step through AutoHotkey's SendPlay mode instead
of pyautogui's default Windows input injection.

Why: on real hardware, the pyautogui click was landing on the right
spot (the icon visibly hovered/highlighted, confirming position and
window focus were both fine) but the click itself wasn't registering
in-game. That's a known symptom for fullscreen games/apps that don't
respond to OS-level synthetic input (SendInput/mouse_event).
AutoHotkey's "Play" send mode is built specifically for this: instead
of injecting at the OS input level, it pushes events directly into the
target window's message queue. See the AHK community thread on
SendPlay for games: https://www.autohotkey.com/board/topic/95412-sendplay/

This module just shells out to AutoHotkey -- drive_click.ahk (next to
this file) does the actual clicking.

Requires AutoHotkey v2 installed on the pod:
    https://www.autohotkey.com  (free, small installer)

Default install path is assumed below; override with --ahk-exe if
yours differs (e.g. the 32-bit AutoHotkey32.exe, or a custom install
location).
"""

import os
import subprocess
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_AHK_SCRIPT = os.path.join(_SCRIPT_DIR, "drive_click.ahk")

DEFAULT_AHK_EXE = r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"


def _run(ahk_exe: str, args: list) -> int:
    if not os.path.isfile(ahk_exe):
        raise FileNotFoundError(
            f"Can't find AutoHotkey at {ahk_exe}. Install it from "
            f"https://www.autohotkey.com (get the v2 version), or pass "
            f"the correct path with --ahk-exe."
        )
    cmd = [ahk_exe, _AHK_SCRIPT] + [str(a) for a in args]
    print(f"[ahk_click] Running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd)
    return result.returncode


def click_xy(
    x: int,
    y: int,
    ahk_exe: str = DEFAULT_AHK_EXE,
    hold_ms: int = 120,
    delay_ms: int = 5000,
    window_title: str = "Assetto Corsa",
) -> None:
    """Wait `delay_ms`, focus `window_title`, then press-hold-release
    at (x, y) via AutoHotkey's SendPlay mode."""
    rc = _run(ahk_exe, ["xy", x, y, hold_ms, delay_ms, window_title])
    if rc != 0:
        raise RuntimeError(f"drive_click.ahk exited with unexpected code {rc}")


def click_image(
    image_path: str,
    ahk_exe: str = DEFAULT_AHK_EXE,
    hold_ms: int = 120,
    delay_ms: int = 3000,
    window_title: str = "Assetto Corsa",
    timeout_ms: int = 25000,
) -> None:
    """Wait `delay_ms`, focus `window_title`, then poll the screen for
    `image_path` (a cropped screenshot of the Drive icon) for up to
    `timeout_ms`, and click its center via SendPlay as soon as it's
    found."""
    rc = _run(
        ahk_exe,
        ["image", image_path, hold_ms, delay_ms, window_title, timeout_ms],
    )
    if rc == 1:
        raise TimeoutError(
            f"AutoHotkey couldn't find {image_path} on screen within {timeout_ms}ms."
        )
    elif rc != 0:
        raise RuntimeError(f"drive_click.ahk exited with unexpected code {rc}")
