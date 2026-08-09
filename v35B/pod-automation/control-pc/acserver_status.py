"""
acserver_status.py

Queries a *running* acServer instance's own built-in HTTP status
endpoint -- separate from acserver_manager.py, which writes config and
starts/stops the process. This module never touches the process; it
just asks an instance that's already running "what's happening right
now" (track, cars, connected drivers), the way any tool that displays
a public AC server list does.

STATUS: confirmed against a real running instance (2026-08-09, one of
Chad's own servers, "S1 - LMP1/GT3" on port 9601/8081). `GET /INFO` on
the HTTP_PORT is right, and returns JSON shaped like:

    {"ip":"","port":9601,"cport":8081,"name":"S1 - LMP1/GT3",
     "clients":0,"maxclients":24,"track":"spa","cars":[...]}

(`cport` is the HTTP_PORT itself, not a separate thing.) This module
doesn't hard-code field names -- it just returns the parsed dict as-is
-- so it already works as-is; the confirmation just means the "unable
to verify" caveat that used to live here is gone. Fails soft either
way: any unreachable/unexpected response comes back as `None` rather
than raising, since this is a "nice to have" status display, not
something that should ever block starting or joining a session.

Testing this by hand on Windows: PowerShell's `curl` is aliased to
Invoke-WebRequest, which warns about script execution risk for a
`text/plain` response (acServer's `Content-Type` on /INFO) -- answer
`y`, or add `-UseBasicParsing` to skip the prompt. Doesn't affect this
module at all; Python's urllib here doesn't care about Content-Type.
"""

import json
import urllib.error
import urllib.request
from typing import Optional

_INFO_PATH = "/INFO"
DEFAULT_TIMEOUT_SECONDS = 2.0


def query_instance_status(ip: str, http_port: int, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Optional[dict]:
    """Best-effort live status for one running acServer instance.

    Returns the parsed JSON dict on success, or None if the instance
    isn't reachable (not started yet, wrong port, still booting,
    network hiccup, unexpected response shape, etc.) -- callers should
    treat None as "no status available right now", not an error.
    """
    if not ip:
        return None
    url = f"http://{ip}:{http_port}{_INFO_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        return None
