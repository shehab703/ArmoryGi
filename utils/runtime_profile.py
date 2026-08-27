"""Runtime overrides when ArmoryGIS is embedded inside C# WinForms."""
from __future__ import annotations

import os
from pathlib import Path

_EMBEDDED = False


def activate_embedded_profile() -> None:
    global _EMBEDDED
    _EMBEDDED = True

    app_dir = Path(__file__).resolve().parent.parent
    data_dir = app_dir / "app_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = data_dir / "tile_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("ARMORYGIS_EMBEDDED", "1")
    os.environ.setdefault("ARMORYGIS_DATA_DIR", str(data_dir))
    os.environ.setdefault("ARMORYGIS_CACHE_DIR", str(cache_dir))
    os.environ.setdefault("ARMORYGIS_DEBUG", "false")

    marker = app_dir / "_armorygis_embed_hwnd.txt"
    if marker.is_file():
        try:
            marker.unlink()
        except OSError:
            pass


def is_embedded_profile() -> bool:
    return _EMBEDDED


def effective_theme(stored: str | None = None) -> str:
    value = (stored or "light").strip()
    return value if value in {"dark", "cyber_neon", "light"} else "light"


def effective_language(stored: str | None = None) -> str:
    return (stored or "ar").strip() or "ar"
