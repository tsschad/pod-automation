"""
drive_click.py

Pragmatic unblock for the "Session information" screen that appears
after a direct acs.exe launch (see direct_launch.py) — no CSP or
Content Manager setting was found to suppress it, so this automates
the one manual step Chad confirmed unblocks everything: clicking the
steering wheel ("Drive") icon.

This is a normal, legitimate technique for fixed-layout kiosk software
(not a hack) — the pods are dedicated machines with a known, constant
screen resolution and UI, so simulating this one click is reliable
*once two easy-to-miss Windows gotchas are handled*:

1. DPI scaling. If Windows display scaling is anything other than
   100% (125%/150% is a common default), pyautogui's coordinates can
   be silently off from the real screen pixels, so it "clicks
   successfully" at the wrong spot. Fixed by marking this process
   DPI-aware at import time, below.

2. Foreground focus. A synthetic click goes to whatever window
   currently has OS focus — not wherever the mouse cursor visually
   is. If the terminal the script is running from still has focus
   when the click fires, the click is swallowed by the terminal and
   Assetto Corsa never sees it. Fixed by explicitly bringing the AC
   window to the foreground right before clicking.

Both of these produce exactly the symptom of "script says Clicked,
nothing happens in-game" — no exception, because the click itself
succeeded, just not on the window you wanted.

Two ways to find where to click, in order of robustness:

1. Image match (recommended): give it a small screenshot crop of just
   the steering wheel icon (drive_icon.png). It polls the screen until
   that icon appears, then clicks its center.

2. Fixed coordinate: just clicks (x, y) after a flat delay.

Requires the `pyautogui` package (plus Pillow, which it pulls in).
Image matching with `confidence=` additionally needs `opencv-python`
(or `opencv-python-headless`) — if that's not installed, this falls
back to an exact pixel match, which is more brittle but still works.

Install on the pod with:
    pip install pyautogui opencv-python-headless
"""

import os
import time

# Screenshots always go here — the actual folder this file lives in —
# regardless of what directory you happened to run `python` from.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Must happen before pyautogui (or anything else) queries screen size/
# cursor position, so this runs at import time, not inside a function.
try:
    import ctypes
    if hasattr(ctypes, "windll"):
        try:
            # PROCESS_PER_MONITOR_DPI_AWARE — most accurate on modern Windows.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
except Exception:
    pass


def focus_window(title_substring: str = "Assetto Corsa", timeout: float = 5.0) -> bool:
    """Windows-only: bring a window whose title contains
    `title_substring` to the foreground. Best-effort — returns False
    (without raising) if it can't find or focus the window, since a
    click might still land correctly without this in some setups, and
    we'd rather try the click than abort."""
    if not hasattr(ctypes, "windll"):
        return False

    user32 = ctypes.windll.user32
    deadline = time.time() + timeout
    found = {"hwnd": None}

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _enum_handler(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_substring.lower() in buf.value.lower():
                found["hwnd"] = hwnd
                return False
        return True

    while time.time() < deadline and found["hwnd"] is None:
        try:
            user32.EnumWindows(_enum_handler, 0)
        except Exception:
            return False
        if found["hwnd"] is None:
            time.sleep(0.3)

    if found["hwnd"] is None:
        return False

    return _force_foreground(found["hwnd"])


def _force_foreground(hwnd) -> bool:
    """Plain SetForegroundWindow silently does nothing when called from
    a background process (no error, no effect) -- Windows only allows
    it for the process that's already foreground, or one that recently
    received user input. Our caller here is a Flask server responding
    to a browser click, which is exactly the case Windows blocks. This
    is why the AC window kept opening behind everything even though
    the original code "succeeded" with no exception.

    Standard workaround: temporarily attach our thread's input state to
    the current foreground window's thread via AttachThreadInput, which
    satisfies the condition Windows checks, then SetForegroundWindow
    actually works. SwitchToThisWindow is an extra (undocumented, but
    long-standing and widely used) fallback for the same goal."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE, in case minimized
        user32.ShowWindow(hwnd, 5)  # SW_SHOW

        current_thread_id = kernel32.GetCurrentThreadId()
        foreground_hwnd = user32.GetForegroundWindow()
        foreground_thread_id = user32.GetWindowThreadProcessId(foreground_hwnd, None) if foreground_hwnd else 0
        target_thread_id = user32.GetWindowThreadProcessId(hwnd, None)

        attached_fg = False
        attached_target = False
        if foreground_thread_id and foreground_thread_id != current_thread_id:
            attached_fg = bool(user32.AttachThreadInput(current_thread_id, foreground_thread_id, True))
        if target_thread_id and target_thread_id != current_thread_id:
            attached_target = bool(user32.AttachThreadInput(current_thread_id, target_thread_id, True))

        try:
            user32.BringWindowToTop(hwnd)
            result = bool(user32.SetForegroundWindow(hwnd))
        finally:
            if attached_fg:
                user32.AttachThreadInput(current_thread_id, foreground_thread_id, False)
            if attached_target:
                user32.AttachThreadInput(current_thread_id, target_thread_id, False)

        if not result:
            try:
                user32.SwitchToThisWindow(hwnd, True)
            except Exception:
                pass

        time.sleep(0.3)  # let the window manager actually switch focus
        return True
    except Exception:
        return False


def _save_debug_screenshot(name: str) -> str:
    """Save a screenshot as `name` in _SCRIPT_DIR and return the
    absolute path — or print exactly why it failed, rather than
    swallowing the error. Screenshot saving has quietly failed before
    (e.g. missing Pillow, or a screen-capture permission issue), which
    looks identical to 'the debug flag doesn't do anything' unless we
    say so explicitly."""
    import pyautogui

    path = os.path.join(_SCRIPT_DIR, name)
    try:
        pyautogui.screenshot(path)
        print(f"[drive_click] Saved {path}")
        return path
    except Exception as exc:
        print(f"[drive_click] Failed to save {path}: {exc}")
        return ""


def _do_click(
    x: int,
    y: int,
    window_title: str = "Assetto Corsa",
    debug_prefix: str = "",
    hold: float = 0.12,
    click_count: int = 1,
):
    """Move to (x, y) once, let the cursor settle, then press-hold-
    release explicitly (rather than pyautogui.click(x, y), which
    quietly does its own extra moveTo right before a near-0-duration
    down/up). Some game UIs — including what we're seeing here, where
    the icon visibly highlights on hover but a plain .click() doesn't
    register — don't count a press that short, or get thrown off by
    the redundant re-move landing a pixel differently. Explicit
    mouseDown/sleep/mouseUp with the cursor already parked is the more
    reliable pattern for this kind of UI automation.

    `click_count` > 1 fires the whole press-hold-release sequence
    multiple times, in case a single press still doesn't register.
    """
    import pyautogui

    focused = focus_window(window_title)
    if not focused:
        print(
            f"[drive_click] Couldn't find/focus a window matching "
            f"'{window_title}' — clicking anyway, but if this keeps "
            f"failing, that's likely why (the click is probably landing "
            f"on the terminal instead of the game)."
        )

    saved = []

    # Move once and let it settle *before* the debug "before" shot, so
    # that screenshot actually shows the cursor sitting on the target.
    pyautogui.moveTo(x, y, duration=0.2)
    time.sleep(0.2)

    if debug_prefix:
        saved.append(_save_debug_screenshot(f"{debug_prefix}_before.png"))

    for i in range(max(1, click_count)):
        pyautogui.mouseDown(x, y)
        time.sleep(hold)
        pyautogui.mouseUp(x, y)
        if i < click_count - 1:
            time.sleep(0.15)

    time.sleep(0.15)

    if debug_prefix:
        saved.append(_save_debug_screenshot(f"{debug_prefix}_after.png"))

    return [p for p in saved if p]


def wait_and_click_image(
    image_path: str,
    timeout: float = 25.0,
    poll_interval: float = 0.5,
    confidence: float = 0.85,
    initial_delay: float = 3.0,
    window_title: str = "Assetto Corsa",
    debug: bool = False,
    hold: float = 0.12,
    click_count: int = 1,
):
    """Poll the screen for `image_path` (a cropped screenshot of the
    Drive icon) and click its center as soon as it appears.

    `initial_delay` gives Assetto Corsa a moment to actually get to
    the session-info screen before we start looking — tune this up if
    the pod is slow to load a track.

    If `debug` is True, saves click_before.png / click_after.png next
    to this script so you can see exactly what was on screen and
    where the click landed.
    """
    import pyautogui

    time.sleep(initial_delay)
    deadline = time.time() + timeout
    last_exc = None

    while time.time() < deadline:
        loc = None
        try:
            try:
                loc = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
            except TypeError:
                # Older pyautogui, or opencv not installed: confidence=
                # isn't supported, so fall back to an exact match.
                loc = pyautogui.locateCenterOnScreen(image_path)
        except Exception as exc:  # includes pyautogui.ImageNotFoundException
            last_exc = exc

        if loc:
            _do_click(
                loc.x, loc.y,
                window_title=window_title,
                debug_prefix="click" if debug else "",
                hold=hold,
                click_count=click_count,
            )
            return loc  # pyautogui Point — .x / .y usable, and unpacks like a 2-tuple

        time.sleep(poll_interval)

    msg = f"Couldn't find {image_path} on screen within {timeout}s."
    if last_exc:
        msg += f" Last error: {last_exc}"
    raise TimeoutError(msg)


def click_at(
    x: int,
    y: int,
    delay: float = 6.0,
    window_title: str = "Assetto Corsa",
    debug: bool = False,
    hold: float = 0.12,
    click_count: int = 1,
):
    """Simple fallback: wait `delay` seconds, then click a fixed
    screen coordinate. No image search — brittle if resolution or
    layout changes, but zero setup."""
    time.sleep(delay)
    _do_click(x, y, window_title=window_title, debug_prefix="click" if debug else "", hold=hold, click_count=click_count)
    return (x, y)
