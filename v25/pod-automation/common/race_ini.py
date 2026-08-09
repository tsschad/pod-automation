"""
race_ini.py

Builds an Assetto Corsa `race.ini` file (as text) from a small set of
high-level parameters, so it can be handed to Content Manager via the
acmanager://race/config URI (see cm_launcher.py).

STATUS (updated against a real reference file from Chad's system,
captured 2026-08-08 — a single-player Practice session, one car, no
AI opponents, multiplayer REMOTE inactive):

  Confirmed correct against the reference file:
    HEADER.VERSION, RACE.{TRACK,CONFIG_TRACK,MODEL,MODEL_CONFIG,CARS,
    AI_LEVEL,FIXED_SETUP,PENALTIES}, CAR_0.{MODEL_CONFIG,SKIN,
    DRIVER_NAME,NATIONALITY,NATION_CODE}, SESSION_0.{NAME,TYPE,
    DURATION_MINUTES,SPAWN_SET}, TEMPERATURE, WEATHER, LIGHTING
    (including CLOUD_SPEED and the negative SUN_ANGLE sign), WIND,
    DYNAMIC_TRACK, GROOVE, LAP_INVALIDATOR, GHOST_CAR, and the inactive
    boilerplate sections (AUTOSPAWN, BENCHMARK, REPLAY, REMOTE-when-off).

  Corrected from the first draft:
    - HEADER.VERSION is 1, not 2.
    - RACE has no DRIFT_MODE key at all (removed — AC just doesn't
      write it when unused; leaving it out matches the working file).
    - RACE.MODEL_CONFIG exists and was missing.
    - CAR_0.MODEL is literally "-" in the reference file rather than
      repeating the car id — apparently shorthand for "same as
      RACE.MODEL". Kept as the default here since it's what a proven
      file uses; happy to switch to the explicit id if testing shows
      "-" doesn't behave the same way when driven externally.
    - CAR_0.SKIN was populated with a real skin id ("0_nissan_12") in
      the reference file, not left blank. Blank may or may not be
      safe — treat "figure out real default skin ids per car" as a
      Phase 1/2 task for the content-pack system, not something to
      assume works.
    - LIGHTING needed CLOUD_SPEED, and SUN_ANGLE was negative (-48) in
      the reference file, not positive.
    - A handful of sections didn't exist in the first draft at all:
      AUTOSPAWN, BENCHMARK, DYNAMIC_TRACK, GHOST_CAR, GROOVE,
      LAP_INVALIDATOR, REPLAY, WIND. These appear to always be present
      (even when inactive/default), so they're now emitted as fixed
      boilerplate — customers/admins never need to configure them.

  New capability found in the reference file, not previously known:
    The REMOTE section can carry a full multiplayer connection
    (SERVER_IP, SERVER_HTTP_PORT, SERVER_PORT, PASSWORD,
    REQUESTED_CAR, TEAM, GUID) *and a NAME field* directly inside
    race.ini. That NAME field looks like it may be exactly what
    controls the player's displayed name in a multiplayer session —
    which would resolve the open question about how to set the
    multiplayer driver name, without needing to touch any separate AC
    settings file. This needs a real test: build a race.ini with
    REMOTE.ACTIVE=1 and a NAME set, fire it via race/config, and see
    whether it connects with that name. See phase0_test.py's `mp-ini`
    command.

  Still unverified (no reference file yet for these):
    - A Race-type session (TYPE=3) — whether it uses LAPS,
      DURATION_MINUTES, or both, and under what key names.
    - A grid with AI opponents present — CAR_1, CAR_2, etc. structure
      is still a best guess (MODEL, SKIN, AI_LEVEL, AI_AGGRESSION,
      DRIVER_NAME, NATIONALITY, MODEL_CONFIG).
    - Whether REMOTE.ACTIVE=1 fired through race/config actually joins
      a server the way race/online/join does (see above).

Capture another reference file (a Race session, and/or one with AI
opponents, and/or a real REMOTE.ACTIVE=1 join) and this module can be
tightened further — paste the file back the same way you did this one.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AIOpponent:
    """One AI-driven car in the grid. Structure is still a best guess —
    no reference file with AI opponents has been captured yet."""
    car: str                     # AC car folder id, e.g. "ks_mazda_mx5_cup"
    skin: str = ""                # skin folder name — see note above about blank skins
    ai_level: int = 97            # effective range is roughly 80-100
    ai_aggression: int = 50       # 0-100
    driver_name: str = ""         # "" = let AC assign a default AI name
    nationality: str = ""


@dataclass
class RemoteConfig:
    """Multiplayer connection details, embeddable directly in race.ini
    via the REMOTE section. Unverified whether firing this through
    race/config actually connects — test before relying on it (see
    phase0_test.py's `mp-ini` command). If it works, `name` is
    likely the fix for the multiplayer-driver-name open question."""
    server_ip: str
    server_http_port: int
    server_port: int
    name: str                     # player's displayed name in the session
    password: str = ""
    requested_car: str = ""       # car id to request from the server's entry list
    team: str = ""
    guid: str = ""                # Steam64 id; usually best left blank and let AC fill it in


@dataclass
class RaceConfig:
    """Everything needed to build one race.ini."""
    track: str                        # AC track folder id, e.g. "ks_red_bull_ring"
    track_layout: str = ""            # layout/config name, e.g. "layout_gp"; "" if none
    player_car: str = "ks_mazda_mx5_cup"
    player_car_model_config: str = ""
    player_skin: str = "0"            # see note above: blank may not be safe, needs a real id
    driver_name: str = "Guest Driver"
    nationality: str = ""
    nation_code: str = ""

    session_type: str = "practice"    # "practice" or "race"
    duration_minutes: int = 20        # used when session_type == "practice"
    laps: int = 5                     # used when session_type == "race" — UNVERIFIED key name

    ai_opponents: List[AIOpponent] = field(default_factory=list)

    # Track/weather conditions. Reasonable defaults matching the
    # reference file; expose these later in the admin GUI if wanted.
    ambient_temp: int = 26
    road_temp: int = 34
    weather: str = "4_mid_clear"
    sun_angle: int = -48
    cloud_speed: float = 0.2

    penalties: bool = False
    fixed_setup: bool = False

    # If set, embeds a multiplayer connection directly in this race.ini
    # (see RemoteConfig docstring — unverified end-to-end).
    remote: Optional[RemoteConfig] = None


def _kv(lines: List[str], key: str, value) -> None:
    if isinstance(value, bool):
        value = 1 if value else 0
    lines.append(f"{key}={value}")


def build_race_ini(cfg: RaceConfig) -> str:
    """Render a RaceConfig into race.ini text. Section order mirrors
    the reference file rather than alphabetical/logical grouping, on
    the theory that matching a known-working file exactly is safer
    than assuming order doesn't matter."""
    total_cars = 1 + len(cfg.ai_opponents)
    lines: List[str] = []

    lines.append("[AUTOSPAWN]")
    _kv(lines, "ACTIVE", 0)
    lines.append("")

    lines.append("[BENCHMARK]")
    _kv(lines, "ACTIVE", 0)
    lines.append("")

    lines.append("[DYNAMIC_TRACK]")
    _kv(lines, "LAP_GAIN", 1)
    _kv(lines, "PRESET", 5)
    _kv(lines, "RANDOMNESS", 0)
    _kv(lines, "SESSION_START", 100)
    _kv(lines, "SESSION_TRANSFER", 100)
    lines.append("")

    lines.append("[GHOST_CAR]")
    _kv(lines, "FILE", "")
    _kv(lines, "LOAD", 1)
    _kv(lines, "PLAYING", 0)
    _kv(lines, "RECORDING", 0)
    _kv(lines, "SECONDS_ADVANTAGE", 0)
    lines.append("")

    lines.append("[GROOVE]")
    _kv(lines, "MAX_LAPS", 30)
    _kv(lines, "STARTING_LAPS", 0)
    _kv(lines, "VIRTUAL_LAPS", 10)
    lines.append("")

    lines.append("[HEADER]")
    _kv(lines, "VERSION", 1)
    lines.append("")

    lines.append("[LAP_INVALIDATOR]")
    _kv(lines, "ALLOWED_TYRES_OUT", -1)
    lines.append("")

    lines.append("[LIGHTING]")
    _kv(lines, "CLOUD_SPEED", cfg.cloud_speed)
    _kv(lines, "SUN_ANGLE", cfg.sun_angle)
    _kv(lines, "TIME_MULT", 1)
    lines.append("")

    lines.append("[RACE]")
    global_ai_level = max((o.ai_level for o in cfg.ai_opponents), default=97)
    _kv(lines, "AI_LEVEL", global_ai_level)
    _kv(lines, "CARS", total_cars)
    _kv(lines, "CONFIG_TRACK", cfg.track_layout)
    _kv(lines, "FIXED_SETUP", cfg.fixed_setup)
    _kv(lines, "MODEL", cfg.player_car)
    _kv(lines, "MODEL_CONFIG", cfg.player_car_model_config)
    _kv(lines, "PENALTIES", cfg.penalties)
    _kv(lines, "TRACK", cfg.track)
    lines.append("")

    lines.append("[REMOTE]")
    if cfg.remote:
        _kv(lines, "ACTIVE", 1)
        _kv(lines, "GUID", cfg.remote.guid)
        _kv(lines, "NAME", cfg.remote.name)
        _kv(lines, "PASSWORD", cfg.remote.password)
        _kv(lines, "REQUESTED_CAR", cfg.remote.requested_car)
        _kv(lines, "SERVER_HTTP_PORT", cfg.remote.server_http_port)
        _kv(lines, "SERVER_IP", cfg.remote.server_ip)
        _kv(lines, "SERVER_PORT", cfg.remote.server_port)
        _kv(lines, "TEAM", cfg.remote.team)
    else:
        _kv(lines, "ACTIVE", 0)
    lines.append("")

    lines.append("[REPLAY]")
    _kv(lines, "ACTIVE", 0)
    _kv(lines, "FILENAME", "")
    lines.append("")

    lines.append("[TEMPERATURE]")
    _kv(lines, "AMBIENT", cfg.ambient_temp)
    _kv(lines, "ROAD", cfg.road_temp)
    lines.append("")

    lines.append("[WEATHER]")
    _kv(lines, "NAME", cfg.weather)
    lines.append("")

    lines.append("[WIND]")
    _kv(lines, "DIRECTION_DEG", -1)
    _kv(lines, "SPEED_KMH_MAX", 40)
    _kv(lines, "SPEED_KMH_MIN", 2)
    lines.append("")

    if cfg.session_type == "practice":
        lines.append("[SESSION_0]")
        _kv(lines, "NAME", "Practice")
        _kv(lines, "TYPE", 1)
        _kv(lines, "DURATION_MINUTES", cfg.duration_minutes)
        _kv(lines, "SPAWN_SET", "PIT")
    elif cfg.session_type == "race":
        # UNVERIFIED: no reference file for a race session yet. Keeping
        # LAPS as the best guess; if you capture a race.ini from a real
        # race, check whether it's LAPS, DURATION_MINUTES, or both.
        lines.append("[SESSION_0]")
        _kv(lines, "NAME", "Race")
        _kv(lines, "TYPE", 3)
        _kv(lines, "LAPS", cfg.laps)
        _kv(lines, "SPAWN_SET", "PIT")
    else:
        raise ValueError(f"Unknown session_type: {cfg.session_type!r} (expected 'practice' or 'race')")
    lines.append("")

    lines.append("[CAR_0]")
    _kv(lines, "MODEL", "-")  # reference file uses "-"; see module docstring
    _kv(lines, "MODEL_CONFIG", cfg.player_car_model_config)
    _kv(lines, "SKIN", cfg.player_skin)
    _kv(lines, "DRIVER_NAME", cfg.driver_name)
    _kv(lines, "NATIONALITY", cfg.nationality)
    _kv(lines, "NATION_CODE", cfg.nation_code)
    lines.append("")

    # AI opponent sections — UNVERIFIED structure, no reference file
    # with AI opponents captured yet.
    for i, ai in enumerate(cfg.ai_opponents, start=1):
        lines.append(f"[CAR_{i}]")
        _kv(lines, "MODEL", ai.car)
        _kv(lines, "MODEL_CONFIG", "")
        _kv(lines, "SKIN", ai.skin)
        _kv(lines, "AI_LEVEL", ai.ai_level)
        _kv(lines, "AI_AGGRESSION", ai.ai_aggression)
        if ai.driver_name:
            _kv(lines, "DRIVER_NAME", ai.driver_name)
        if ai.nationality:
            _kv(lines, "NATIONALITY", ai.nationality)
        lines.append("")

    return "\n".join(lines) + "\n"
