from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


GMDB_DIR_KEY = "map/gmdb_dir"


def get_gmdb_dir(settings) -> str:
    if settings is None:
        return ""
    return str(settings.value(GMDB_DIR_KEY, "", str) or "").strip()


def list_gmdb_files(directory: str) -> List[Path]:
    if not directory:
        return []
    root = Path(directory).expanduser().resolve(strict=False)
    if not root.exists() or not root.is_dir():
        return []
    return sorted(root.glob("*.gmdb"), key=lambda p: p.name.lower())


def get_gmdb_options(settings) -> List[Tuple[str, str]]:
    """
    Return list of (label, data) where data is a basemap token:
    gmdb|<absolute_path>
    """
    options: List[Tuple[str, str]] = []
    for file_path in list_gmdb_files(get_gmdb_dir(settings)):
        label = f"GMDB: {file_path.stem}"
        data = f"gmdb|{str(file_path)}"
        options.append((label, data))
    return options

