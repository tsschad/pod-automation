"""
packs.py

Loads the hand-edited packs.json config: where AC is installed, where
acs.exe lives, and the admin-curated content packs customers pick
from in single-player mode.

This is a stand-in for the real admin GUI (a later phase) — for now,
Chad edits packs.json directly. The schema is intentionally simple so
that swap-in is straightforward later: the admin GUI would just read
and write this same file (or the DB row it becomes).

packs.json shape:
{
  "ac_install_dir": "C:\\...\\steamapps\\common\\assettocorsa",
  "acs_exe": "C:\\...\\assettocorsa\\acs.exe",
  "packs": {
    "gt3_favorites": {
      "label": "GT3 Favorites",
      "cars": ["ks_nissan_gtr_gt3", "ks_ferrari_488_gt3"],
      "tracks": ["ks_red_bull_ring", "ks_laguna_seca"]
    }
  }
}
"""

import json
import os

# Synthetic pack id for "browse everything installed" rather than a
# curated list — not a real entry in packs.json's "packs" dict. app.py
# special-cases this id in api_pack_detail (using content_scan's
# list_installed_car_ids/list_installed_track_ids) rather than looking
# it up here, since packs.py deliberately doesn't know about
# content_scan / the filesystem.
ALL_CONTENT_PACK_ID = "__all__"
ALL_CONTENT_PACK_LABEL = "All Cars & Tracks"


class PacksConfigError(Exception):
    pass


def load_config(path: str) -> dict:
    if not os.path.isfile(path):
        raise PacksConfigError(
            f"{path} not found. Copy packs.example.json to packs.json and "
            f"fill in ac_install_dir / acs_exe / your packs."
        )
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    for required in ("ac_install_dir", "acs_exe", "packs"):
        if required not in cfg:
            raise PacksConfigError(f"packs.json is missing required key '{required}'.")

    return cfg


def list_packs(cfg: dict) -> list:
    """Returns [{"id": ..., "label": ...}, ...] for the picker's first
    screen — the curated packs from packs.json, plus a synthetic "All
    Cars & Tracks" entry at the end for browsing everything installed."""
    curated = [
        {"id": pack_id, "label": pack.get("label", pack_id)}
        for pack_id, pack in cfg["packs"].items()
    ]
    return curated + [{"id": ALL_CONTENT_PACK_ID, "label": ALL_CONTENT_PACK_LABEL}]


def get_pack(cfg: dict, pack_id: str) -> dict:
    pack = cfg["packs"].get(pack_id)
    if pack is None:
        raise PacksConfigError(f"No pack '{pack_id}' in packs.json.")
    return pack
