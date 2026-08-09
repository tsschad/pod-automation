"""
cm_launcher.py

Fires Content Manager's `acmanager://` URI protocol to launch a
single-player race or join a multiplayer server directly, without
touching Content Manager's own UI.

STATUS (2026-08-09): the multiplayer join functions here are now
confirmed working against a real acServer instance on real hardware --
the first time anything in this project's multiplayer join path has
actually connected. `join_online_server()` (race/online/join) was
proven first, by hand. `join_online_server_direct()` (race/online) is
the one actually wired into phase1/app.py's /api/mp/join for the real
kiosk flow, since it skips CM's confirmation dialog and carries the
customer's car/track/name through -- not yet independently confirmed
on hardware itself, but built directly from the same source research
that got the first one right, and uses the identical underlying
CM/Steam connection path. `launch_race()` (race/config, single-player)
remains the one abandoned approach here -- kept only for reference.

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
    """Join a specific acServer instance via CM's `race/online/join`
    command. CONFIRMED WORKING on real hardware 2026-08-09 -- but it
    always opens Content Manager's server-info dialog (track/car list,
    ping, a "Join" button) and needs a manual click; there's no
    parameter to skip it (confirmed against AcTools' actual source,
    ProcessRaceOnlineJoin() in ArgumentsHandler.Race.cs -- it
    unconditionally shows a ModernDialog, full stop). Kept as a
    fallback/manual-test option; join_online_server_direct() below is
    the one to use for the actual customer-facing kiosk flow.

    `http_port` is the acServer instance's HTTP port (not the raw UDP
    port).
    """
    params = {"ip": ip, "httpPort": http_port}
    if password:
        params["password"] = password
    uri = "acmanager://race/online/join?" + urlencode(params)
    _open_uri(uri)
    return uri


def join_online_server_direct(
    ip: str,
    port: int,
    http_port: int,
    car: str,
    skin: str = "",
    track: str = "",
    name: str = "",
    nationality: str = "",
    password: str = "",
    allow_without_steam_id: bool = False,
) -> str:
    """Join a specific acServer instance via CM's `race/online` command
    (note: NOT `race/online/join` -- a different action). Connects
    immediately -- no dialog, no manual click -- confirmed against
    AcTools' actual source, ProcessRaceOnline() in
    ArgumentsHandler.Race.cs: if `car`/`port` resolve to something
    valid it calls GameWrapper.StartAsync(...) directly. This is also
    how the customer's chosen car/track/name actually carry through to
    a multiplayer join -- join_online_server()'s race/online/join only
    ever takes ip/httpPort/password, nothing about content or identity.

    Two things this needs that join_online_server() didn't:
      - `port`: the game's raw UDP port, NOT the HTTP port. Both are
        required here.
      - `car`: must be a real, locally-installed car folder id or this
        throws inside Content Manager instead of falling back to a
        picker -- make sure it matches what's actually on this pod
        (same ids content_scan.py already reads).

    `allow_without_steam_id`, left off by default: an escape hatch CM
    itself exposes for joining without a valid Steamworks identity --
    only worth setting if a future test traces a failure back to GUID/
    Steam-session problems specifically; leave alone otherwise.
    """
    params = {"ip": ip, "port": port, "httpPort": http_port, "car": car}
    if skin:
        params["skin"] = skin
    if track:
        params["track"] = track
    if name:
        params["name"] = name
    if nationality:
        params["nationality"] = nationality
    if password:
        params["password"] = password
    if allow_without_steam_id:
        params["allowWithoutSteamId"] = "1"
    uri = "acmanager://race/online?" + urlencode(params)
    _open_uri(uri)
    return uri
