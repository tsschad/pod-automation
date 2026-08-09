"""
cm_launcher.py

Fires Content Manager's `acmanager://` URI protocol to launch a
single-player race or join a multiplayer server directly, without
touching Content Manager's own UI.

Requires:
  - Content Manager already installed and licensed (it registers the
    acmanager:// protocol handler with Windows on first run).
  - This has to run ON THE POD ITSELF (Windows). `os.startfile` is a
    Windows-only API; on any other OS this just prints what it would
    have done, so you can still sanity-check the generated URI/ini
    from a dev machine.

No third-party dependencies — standard library only.
"""

import base64
import os
import platform
import subprocess
import sys
from urllib.parse import urlencode


def _open_uri(uri: str) -> None:
    """Hand a URI to the OS so its registered protocol handler
    (Content Manager, for acmanager://) picks it up."""
    system = platform.system()
    if system == "Windows":
        try:
            os.startfile(uri)  # type: ignore[attr-defined]
            return
        except Exception as exc:
            print(f"[cm_launcher] os.startfile failed ({exc}); "
                  f"falling back to 'start'.", file=sys.stderr)
        subprocess.Popen(["cmd", "/c", "start", "", uri])
    else:
        print(f"[cm_launcher] Not running on Windows — nothing to launch here. "
              f"URI that would be opened:\n{uri}", file=sys.stderr)


def launch_race(race_ini_text: str) -> str:
    """Launch a single-player session from race.ini text via CM's
    `race/config` command.

    The query parameter is `settings` (confirmed empirically on
    2026-08-08 — the first guess, `data`, produced "Oops, can't
    process request... settings are not specified" from Content
    Manager, which was the tell).

    Returns the URI that was opened, for logging/debugging.
    """
    encoded = base64.b64encode(race_ini_text.encode("utf-8")).decode("ascii")
    uri = "acmanager://race/config?" + urlencode({"settings": encoded})
    _open_uri(uri)
    return uri


def join_online_server(ip: str, http_port: int, password: str = "") -> str:
    """Join a specific acServer instance directly via CM's
    `race/online/join` command — no server browser, no manual clicks.

    `http_port` is the acServer instance's HTTP port (not the raw UDP
    port), per Content Manager's documented parameters.
    """
    params = {"ip": ip, "httpPort": http_port}
    if password:
        params["password"] = password
    uri = "acmanager://race/online/join?" + urlencode(params)
    _open_uri(uri)
    return uri
