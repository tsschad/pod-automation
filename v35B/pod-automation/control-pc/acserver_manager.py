"""
acserver_manager.py

Writes acServer's two config files (server_cfg.ini, entry_list.ini)
for one of the 4 pooled dedicated-server instances, and starts/stops
the acServer.exe process for that instance.

STATUS: best-effort, NOT verified against a real acServer instance or
a real captured server_cfg.ini/entry_list.ini, the way race_ini.py was
corrected against Chad's real reference file before it could be
trusted. The field names/sections below are reconstructed from public
Assetto Corsa dedicated-server documentation, not from a known-working
file. Treat this the same way race_ini.py was treated before that
correction: plausible, not proven. If acServer rejects one of these
files or behaves unexpectedly, capture a working server_cfg.ini /
entry_list.ini from one of Chad's already-running acServer instances
(he mentioned he already runs some) and diff against this module's
output the same way race_ini.py was fixed.

Each pooled instance gets its own config folder (so 4 instances can
run independently without fighting over one file) and is launched with
acServer's -c / -e command-line flags pointing at that folder's
server_cfg.ini / entry_list.ini.

Process model confirmed by Chad: one shared acServer.exe install is
capable of running several genuinely independent server processes at
once, each on its own port -- exactly what his own "Assetto Corsa
Server Manager" GUI tool does with its saved presets (S1-LMP1/GT3,
S2-Hypercars, etc., each with its own ports). This module does the
same thing programmatically: one shared acserver_exe path, launched up
to 4 times (once per pooled instance) with -c/-e pointed at that
instance's own config folder -- rather than integrating with that GUI
tool directly. See acserver_status.py for querying a running
instance's live status once it's up.
"""

import os
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Driver:
    car: str
    skin: str = ""
    driver_name: str = ""
    team: str = ""
    guid: str = ""  # left blank deliberately -- see race_ini.py's note on this


@dataclass
class ServerSessionConfig:
    name: str                  # server's display name, shown in the in-game server browser
    track: str
    track_layout: str = ""
    cars: List[str] = field(default_factory=list)   # allowed car models, e.g. one shared car for the group
    session_type: str = "practice"   # "practice" or "race"
    duration_minutes: int = 20       # practice
    laps: int = 5                    # race
    udp_port: int = 9600
    tcp_port: int = 9600
    http_port: int = 8081
    max_clients: int = 4
    password: str = ""


def build_server_cfg(cfg: ServerSessionConfig) -> str:
    lines: List[str] = []
    lines.append("[SERVER]")
    lines.append(f"NAME={cfg.name}")
    lines.append(f"CARS={','.join(cfg.cars)}")
    lines.append(f"TRACK={cfg.track}")
    lines.append(f"CONFIG_TRACK={cfg.track_layout}")
    lines.append(f"UDP_PORT={cfg.udp_port}")
    lines.append(f"TCP_PORT={cfg.tcp_port}")
    lines.append(f"HTTP_PORT={cfg.http_port}")
    lines.append(f"MAX_CLIENTS={cfg.max_clients}")
    lines.append(f"PASSWORD={cfg.password}")
    lines.append("REGISTER_TO_LOBBY=0")  # local/private kiosk sessions only
    lines.append("PICKUP_MODE_ENABLED=1")
    lines.append("LOOP_MODE=0")
    lines.append("SUN_ANGLE=48")
    lines.append("SLEEP_TIME=1")
    lines.append("NUM_THREADS=2")
    lines.append("VOTING_QUORUM=0")
    lines.append("")

    if cfg.session_type == "practice":
        lines.append("[SESSION_0]")
        lines.append("NAME=Practice")
        lines.append("TYPE=1")
        lines.append(f"TIME={cfg.duration_minutes}")
        lines.append("IS_OPEN=1")
    elif cfg.session_type == "race":
        lines.append("[SESSION_0]")
        lines.append("NAME=Race")
        lines.append("TYPE=3")
        lines.append(f"LAPS={cfg.laps}")
        lines.append("IS_OPEN=1")
    else:
        raise ValueError(f"Unknown session_type: {cfg.session_type!r}")
    lines.append("")

    return "\n".join(lines) + "\n"


def build_entry_list(drivers: List[Driver]) -> str:
    lines: List[str] = []
    for i, d in enumerate(drivers):
        lines.append(f"[CAR_{i}]")
        lines.append(f"MODEL={d.car}")
        lines.append(f"SKIN={d.skin}")
        lines.append(f"SPECTATOR_MODE=0")
        lines.append(f"DRIVERNAME={d.driver_name}")
        lines.append(f"TEAM={d.team}")
        lines.append(f"GUID={d.guid}")
        lines.append("BALLAST=0")
        lines.append("RESTRICTOR=0")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_instance_config(config_dir: str, server_cfg_text: str, entry_list_text: str) -> None:
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "server_cfg.ini"), "w", encoding="utf-8") as f:
        f.write(server_cfg_text)
    with open(os.path.join(config_dir, "entry_list.ini"), "w", encoding="utf-8") as f:
        f.write(entry_list_text)


def start_instance(acserver_exe: str, config_dir: str) -> subprocess.Popen:
    """Launch acServer.exe for one pooled instance, pointed at its own
    config folder via -c/-e -- one shared exe launched multiple times,
    confirmed workable per the module docstring. The server_cfg.ini/
    entry_list.ini *contents* themselves are still the unverified part
    (see module docstring)."""
    if not os.path.isfile(acserver_exe):
        raise FileNotFoundError(f"Can't find acServer.exe at {acserver_exe}")
    server_cfg_path = os.path.join(config_dir, "server_cfg.ini")
    entry_list_path = os.path.join(config_dir, "entry_list.ini")
    return subprocess.Popen(
        [acserver_exe, "-c", server_cfg_path, "-e", entry_list_path],
        cwd=os.path.dirname(acserver_exe),
    )


def stop_instance(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    try:
        process.terminate()
    except Exception:
        pass


def restart_instance(acserver_exe: str, config_dir: str, existing_process: Optional[subprocess.Popen]) -> subprocess.Popen:
    """acServer only picks up config changes on (re)start (per the
    original architecture brief), so every new group session restarts
    its assigned instance from scratch rather than trying to hot-reload
    config into a running process."""
    stop_instance(existing_process)
    return start_instance(acserver_exe, config_dir)
