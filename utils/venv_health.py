"""Validate bundled venv before embed / GUI launch."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _venv_python(app_dir: str) -> Path | None:
    root = Path(app_dir).resolve()
    if sys.platform == "win32":
        for name in ("pythonw.exe", "python.exe"):
            candidate = root / "venv" / "Scripts" / name
            if candidate.is_file():
                return candidate
        return None
    candidate = root / "venv" / "bin" / "python"
    return candidate if candidate.is_file() else None


def _read_pyvenv_home(app_dir: str) -> str:
    cfg = Path(app_dir).resolve() / "venv" / "pyvenv.cfg"
    if not cfg.is_file():
        return ""
    try:
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("home"):
                _, _, value = line.partition("=")
                return value.strip()
    except OSError:
        pass
    return ""


def check_venv(app_dir: str, *, full: bool = False) -> tuple[bool, str]:
    """Return (ok, message). Message is empty when ok.

    full=False skips the slow PyQt6 subprocess import (used at normal startup).
    full=True is for embed_diagnose / repair scripts.
    """
    app_dir = os.path.abspath(app_dir)
    venv_root = Path(app_dir) / "venv"
    if not venv_root.is_dir():
        return (
            False,
            "Virtual environment not found.\n"
            f"Expected: {venv_root}\n\n"
            "On this PC run install_offline.bat inside armorygis_pro.\n"
            "Do not copy venv from another machine — it is not portable.",
        )

    py = _venv_python(app_dir)
    if py is None:
        return (
            False,
            f"venv exists but Python executable is missing under:\n{venv_root}",
        )

    home = _read_pyvenv_home(app_dir)
    if home and not Path(home).is_dir():
        return (
            False,
            "Bundled venv points to a Python install that does not exist on this PC.\n"
            f"pyvenv.cfg home: {home}\n\n"
            "Delete the venv folder and run install_offline.bat again on this machine.",
        )

    if not full:
        return True, ""

    try:
        proc = subprocess.run(
            [str(py), "-c", "import PyQt6; import PyQt6.QtWebEngineWidgets"],
            capture_output=True,
            text=True,
            timeout=45,
            cwd=app_dir,
        )
    except subprocess.TimeoutExpired:
        return False, "Timed out while verifying PyQt6 in bundled venv."
    except OSError as exc:
        return False, f"Could not run bundled Python:\n{py}\n\n{exc}"

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return (
            False,
            "Bundled venv is broken or incomplete (PyQt6 WebEngine check failed).\n\n"
            + (detail or "No details from Python.")
            + "\n\nRun install_offline.bat on this PC.",
        )

    return True, ""


def write_embed_log(app_dir: str, message: str) -> Path:
    logs_dir = Path(app_dir).resolve() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "embed_error.log"
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(message.rstrip() + "\n\n")
    except OSError:
        pass
    return log_path
