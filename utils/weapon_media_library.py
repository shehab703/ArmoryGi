from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

from config import APP_DATA_DIR


# User-requested folder naming (kept as-is for compatibility with existing ops wording).
GALLERY_ROOT = APP_DATA_DIR / "weapouns_gallaries"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
MODEL_EXTS = {".obj", ".glb", ".gltf", ".usdz", ".dae", ".stl", ".ply", ".fbx"}
GALLERY_2D_EXTENSIONS_KEY = "media/gallery_2d_extensions"
DEFAULT_GALLERY_2D_EXTENSIONS = ".png,.jpg,.jpeg,.tif,.tiff,.webp"


def _safe_name(text: str) -> str:
    raw = (text or "").strip()
    raw = re.sub(r"[^\w\-\. ]+", "_", raw, flags=re.UNICODE)
    raw = re.sub(r"\s+", "_", raw)
    return raw[:80] if raw else "weapon"


def _weapon_folder_name(weapon: Dict) -> str:
    model = _safe_name(str(weapon.get("model") or "weapon"))
    wid = str(weapon.get("id") or "0")
    return f"{model}_{wid}"


def parse_image_extensions_csv(value: str | None) -> set[str]:
    tokens = [str(part).strip().lower() for part in str(value or "").split(",")]
    exts = set()
    for token in tokens:
        if not token:
            continue
        if not token.startswith("."):
            token = f".{token}"
        exts.add(token)
    return exts or set(IMAGE_EXTS)


def ensure_weapon_media_dirs(weapon: Dict) -> Tuple[Path, Path]:
    base = GALLERY_ROOT / _weapon_folder_name(weapon)
    images_dir = base / "images"
    models_dir = base / "models"
    images_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    return images_dir, models_dir


def weapon_media_root(weapon: Dict) -> Path:
    """Parent folder for this weapon (contains ``images`` and ``models``). Ensures dirs exist."""
    images_dir, _ = ensure_weapon_media_dirs(weapon)
    return images_dir.parent


def stage_gallery_image(weapon: Dict, src_path: str) -> str:
    src = Path(src_path).expanduser().resolve(strict=False)
    if not src.exists() or not src.is_file():
        return str(src_path)
    images_dir, _ = ensure_weapon_media_dirs(weapon)
    dst = images_dir / src.name
    if dst.exists():
        stem = src.stem
        ext = src.suffix
        i = 1
        while dst.exists():
            dst = images_dir / f"{stem}_{i}{ext}"
            i += 1
    shutil.copy2(src, dst)
    return str(dst.resolve(strict=False))


def stage_model_file(weapon: Dict, src_path: str) -> str:
    src = Path(src_path).expanduser().resolve(strict=False)
    if not src.exists() or not src.is_file():
        return str(src_path)
    _, models_dir = ensure_weapon_media_dirs(weapon)
    dst = models_dir / src.name
    if dst.exists():
        stem = src.stem
        ext = src.suffix
        i = 1
        while dst.exists():
            dst = models_dir / f"{stem}_{i}{ext}"
            i += 1
    shutil.copy2(src, dst)
    return str(dst.resolve(strict=False))


def discover_gallery_images(weapon: Dict, allowed_exts: set[str] | None = None) -> List[str]:
    images_dir, _ = ensure_weapon_media_dirs(weapon)
    exts = allowed_exts or IMAGE_EXTS
    out = []
    for p in sorted(images_dir.iterdir(), key=lambda x: x.name.lower()):
        if p.is_file() and p.suffix.lower() in exts:
            out.append(str(p.resolve(strict=False)))
    return out


def discover_models(weapon: Dict) -> List[str]:
    _, models_dir = ensure_weapon_media_dirs(weapon)
    out = []
    for p in sorted(models_dir.iterdir(), key=lambda x: x.name.lower()):
        if p.is_file() and p.suffix.lower() in MODEL_EXTS:
            out.append(str(p.resolve(strict=False)))
    return out

