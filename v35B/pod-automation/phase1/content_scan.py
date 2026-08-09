"""
content_scan.py

Reads real, already-installed Assetto Corsa content (cars and tracks)
directly off disk to get display names and preview images for the
kiosk picker — the same files Content Manager itself reads, so what
customers see here should look like what they'd see in CM.

Layout AC uses on disk (standard for every car/track, CM or not):

    <AC install>/content/cars/<car_id>/
        ui/ui_car.json          -- {"name": "...", "brand": "...", ...}
        ui/badge.png            -- small brand/series badge (fallback image)
        skins/<skin_id>/preview.jpg   -- the big preview image CM shows
                                          (per-skin; we just use the
                                          first skin found as the
                                          pack's default preview)

    <AC install>/content/tracks/<track_id>/
        ui/ui_track.json        -- {"name": "...", "description": "...", ...}
        ui/preview.png          -- track preview image (single-layout tracks)
        ui/outline.png          -- fallback if preview.png is missing

    Multi-layout tracks (e.g. Nordschleife's various configs) nest an
    extra folder per layout instead of a flat ui/ folder:
        ui/<layout_id>/ui_track.json
        ui/<layout_id>/preview.png

Every function here is defensive — missing folders, missing JSON,
missing images, or a bad install path all just fall back to sensible
defaults (folder id as the name, no preview image) instead of raising.
A pod's install is real-world messy (mods with incomplete UI files are
common), and one broken car shouldn't take down the whole picker.
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TrackLayout:
    layout_id: str  # "" for a single-layout track (no subfolder)
    name: str
    preview_path: Optional[str]


@dataclass
class CarInfo:
    car_id: str
    name: str
    brand: str
    preview_path: Optional[str]


@dataclass
class TrackInfo:
    track_id: str
    name: str
    layouts: List[TrackLayout] = field(default_factory=list)


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _first_existing(*paths: str) -> Optional[str]:
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def car_info(ac_install_dir: str, car_id: str) -> CarInfo:
    car_dir = os.path.join(ac_install_dir, "content", "cars", car_id)
    ui = _read_json(os.path.join(car_dir, "ui", "ui_car.json"))

    preview_path = None
    skins_dir = os.path.join(car_dir, "skins")
    if os.path.isdir(skins_dir):
        for skin_id in sorted(os.listdir(skins_dir)):
            candidate = _first_existing(
                os.path.join(skins_dir, skin_id, "preview.jpg"),
                os.path.join(skins_dir, skin_id, "preview.png"),
            )
            if candidate:
                preview_path = candidate
                break

    if not preview_path:
        preview_path = _first_existing(os.path.join(car_dir, "ui", "badge.png"))

    return CarInfo(
        car_id=car_id,
        name=ui.get("name") or car_id,
        brand=ui.get("brand") or "",
        preview_path=preview_path,
    )


def _layout_preview(ui_root: str, subfolder: str) -> Optional[str]:
    """Check both .png and .jpg for preview/outline in a layout's own
    ui folder, then fall back to the track's shared top-level ui/
    folder (some tracks use one preview image for every layout rather
    than a separate one per layout)."""
    per_layout = _first_existing(
        os.path.join(ui_root, subfolder, "preview.png"),
        os.path.join(ui_root, subfolder, "preview.jpg"),
        os.path.join(ui_root, subfolder, "outline.png"),
        os.path.join(ui_root, subfolder, "outline.jpg"),
    )
    if per_layout:
        return per_layout
    return _first_existing(
        os.path.join(ui_root, "preview.png"),
        os.path.join(ui_root, "preview.jpg"),
        os.path.join(ui_root, "outline.png"),
        os.path.join(ui_root, "outline.jpg"),
    )


def track_info(ac_install_dir: str, track_id: str) -> TrackInfo:
    track_dir = os.path.join(ac_install_dir, "content", "tracks", track_id)
    ui_root = os.path.join(track_dir, "ui")

    # A flat ui/ui_track.json means a single-layout track.
    flat_json = os.path.join(ui_root, "ui_track.json")
    if os.path.isfile(flat_json):
        ui = _read_json(flat_json)
        preview = _first_existing(
            os.path.join(ui_root, "preview.png"),
            os.path.join(ui_root, "preview.jpg"),
            os.path.join(ui_root, "outline.png"),
            os.path.join(ui_root, "outline.jpg"),
        )
        return TrackInfo(
            track_id=track_id,
            name=ui.get("name") or track_id,
            layouts=[TrackLayout(layout_id="", name=ui.get("name") or track_id, preview_path=preview)],
        )

    # Otherwise, look for per-layout subfolders under ui/, each with
    # their own ui_track.json.
    layouts: List[TrackLayout] = []
    display_name = track_id
    if os.path.isdir(ui_root):
        for entry in sorted(os.listdir(ui_root)):
            layout_json = os.path.join(ui_root, entry, "ui_track.json")
            if os.path.isfile(layout_json):
                ui = _read_json(layout_json)
                preview = _layout_preview(ui_root, entry)
                layout_name = ui.get("name") or entry
                display_name = ui.get("name") or display_name
                layouts.append(TrackLayout(layout_id=entry, name=layout_name, preview_path=preview))

    if not layouts:
        # Nothing readable at all — still return something so the
        # track doesn't just vanish from a pack silently.
        layouts = [TrackLayout(layout_id="", name=track_id, preview_path=None)]

    return TrackInfo(track_id=track_id, name=display_name, layouts=layouts)


def list_installed_car_ids(ac_install_dir: str) -> List[str]:
    cars_dir = os.path.join(ac_install_dir, "content", "cars")
    if not os.path.isdir(cars_dir):
        return []
    return sorted(d for d in os.listdir(cars_dir) if os.path.isdir(os.path.join(cars_dir, d)))


def list_installed_track_ids(ac_install_dir: str) -> List[str]:
    tracks_dir = os.path.join(ac_install_dir, "content", "tracks")
    if not os.path.isdir(tracks_dir):
        return []
    return sorted(d for d in os.listdir(tracks_dir) if os.path.isdir(os.path.join(tracks_dir, d)))
