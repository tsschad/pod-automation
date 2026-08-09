"""
acserver_status.py

Queries a *running* acServer instance's own built-in HTTP status
endpoint -- separate from acserver_manager.py, which writes config and
starts/stops the process. This module never touches the process; it
just asks an instance that's already running "what's happening right
now" (track, cars, connected drivers), the way any tool that displays
a public AC server list does.

STATUS: same best-effort caveat as acserver_manager.py's config-file
format. Dedicated acServer exposes a plain HTTP JSON endpoint on each
instance's HTTP_PORT -- conventionally `GET /INFO` -- documented
publicly but not verified here against one of Chad's real running
instances. If the path or field names below don't match, capture a
real response with `curl http://<pod-or-controlpc-ip>:<http_port>/INFO`
against one of his already-running servers and adjust `_INFO_PATH` /
the returned dict shape accordingly. Fails soft either way: any
unreachable/unexpected response just comes back as `None` rather than
raising, since this is a "nice to have" status display, not something
that should ever block starting or joining a session.
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
