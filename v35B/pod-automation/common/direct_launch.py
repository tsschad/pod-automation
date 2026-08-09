"""
direct_launch.py

Alternative to cm_launcher.py's launch_race(): instead of fighting
Content Manager's undocumented (and, on the evidence so far, possibly
cloud-dependent) acmanager://race/config URI, write race.ini to the
exact path Assetto Corsa reads it from, then launch the game
executable directly. This is what every launcher — including Content
Manager — does under the hood; we're just doing the first half
ourselves and skipping CM's URI parsing for this one step.

Why: two attempts at acmanager://race/config (with "data" and with
"settings" as the parameter name) both failed with the identical
generic "settings are not specified" error, and Content Manager's own
"Share" feature turned out to produce a short opaque id
(acmanager://shared?id=...) that it resolves via its own online
service rather than embedding real data in the link — evidence that
guessing our way to the right race/config payload format isn't a
reliable path forward.

Requires knowing where acs.exe (or AssettoCorsa.exe) actually lives on
this machine. Common locations:
    C:\\Program Files (x86)\\Steam\\steamapps\\common\\assettocorsa\\acs.exe
    C:\\Program Files (x86)\\Steam\\steamapps\\common\\assettocorsa\\acs_x86.exe
but this varies by install. Content Manager's own Settings page
usually shows the AC root folder if you're not sure; the exe sits
directly inside it.
"""

import os
import platform
import subprocess
import sys
import time


def _real_documents_folder() -> str:
    """Ask Windows for the ACTUAL Documents folder rather than assuming
    <profile>\\Documents. Documents is frequently redirected — OneDrive
    "Backup" / "Known Folder Move" is the most common cause, but group
    policy and manual redirection do it too. On Chad's first attempt,
    race.ini silently wasn't being read, which is consistent with the
    naive path guess missing a redirect like this."""
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            value, _ = winreg.QueryValueEx(key, "Personal")
            return os.path.expandvars(value)
        except Exception as exc:
            print(f"[direct_launch] Couldn't read the real Documents folder "
                  f"from the registry ({exc}); falling back to the naive "
                  f"guess. This may be exactly the problem if race.ini still "
                  f"isn't being picked up.", file=sys.stderr)
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Documents")


def race_ini_path() -> str:
    """The exact file Assetto Corsa reads on startup."""
    return os.path.join(_real_documents_folder(), "Assetto Corsa", "cfg", "race.ini")


def write_race_ini(race_ini_text: str) -> str:
    """Write race.ini to the path AC actually reads. Returns that path."""
    path = race_ini_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(race_ini_text)
    return path


def _bring_to_foreground(timeout: float = 15.0) -> None:
    """Windows normally blocks a newly-launched process from stealing
    foreground focus from whatever window launched it -- here, that's
    the Flask server's own console/terminal (or nothing visible at
    all, when it's running as a background service), not AC. Without
    this, AC opens correctly but sits behind whatever the customer's
    browser (or the terminal) was showing, exactly as seen in testing.

    Reuses drive_click.py's focus_window(), which already solves this
    same problem for the post-launch Drive-icon click -- no need for a
    second implementation. Best-effort: prints a note and moves on if
    it can't find/focus the window, rather than blocking the launch."""
    try:
        from drive_click import focus_window
    except Exception as exc:
        print(f"[direct_launch] Couldn't import focus_window ({exc}); "
              f"AC may open behind other windows -- bring it forward "
              f"manually if so.", file=sys.stderr)
        return

    # Give the process a moment to actually create its window before
    # searching for it -- searching immediately after Popen() usually
    # finds nothing yet.
    time.sleep(2.0)
    # "assetto" (no space, lowercase) rather than "Assetto Corsa" --
    # looser match in case the window title during loading/session-info
    # differs slightly in spacing or casing from the full game name.
    focused = focus_window("assetto", timeout=timeout)
    if not focused:
        print(f"[direct_launch] Couldn't find/focus an Assetto Corsa window "
              f"within {timeout}s -- it may still be loading, or the title "
              f"doesn't contain 'assetto'. Bring it forward manually if it "
              f"opened behind something else.", file=sys.stderr)


def launch_game_direct(acs_exe_path: str) -> None:
    """Launch the AC game executable directly. It reads race.ini from
    the standard path on startup — no arguments needed if that file
    is already in place."""
    if not os.path.isfile(acs_exe_path):
        raise FileNotFoundError(
            f"Can't find {acs_exe_path}. Check the path to acs.exe on this "
            f"machine (Content Manager's Settings page usually shows the AC "
            f"root folder if you're unsure)."
        )
    # cwd matters for some AC builds (it expects to find its own DLLs/data
    # relative to where it's run from), so launch from its own folder.
    subprocess.Popen([acs_exe_path], cwd=os.path.dirname(acs_exe_path))
    _bring_to_foreground()


def write_and_launch(race_ini_text: str, acs_exe_path: str) -> str:
    """Write race.ini then launch the game. Returns the path race.ini
    was written to, for logging/debugging."""
    path = write_race_ini(race_ini_text)
    print(f"[direct_launch] Wrote race.ini to: {path}", file=sys.stderr)
    launch_game_direct(acs_exe_path)
    return path


def find_all_race_ini(search_root: str = None):
    """Search the filesystem for every file literally named race.ini,
    to settle the real path empirically instead of guessing again.
    Defaults to searching the whole user profile, which is slow-ish
    but only needs to be run once."""
    root = search_root or os.environ.get("USERPROFILE", os.path.expanduser("~"))
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower() == "race.ini":
                full = os.path.join(dirpath, name)
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    mtime = None
                found.append((full, mtime))
    return found
