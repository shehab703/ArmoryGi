"""Bootstrap bundled venv before importing PyQt6 modules."""
from __future__ import annotations

import os
import sys

from utils.venv_health import check_venv, write_embed_log


def _prepend_path(path: str) -> None:
    if path and os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)


def _is_windowless_launch() -> bool:
    if os.environ.get("ARMORYGIS_EMBEDDED", "").strip() in {"1", "true", "yes"}:
        return True
    if "--embedded" in sys.argv:
        return True
    try:
        return os.path.basename(sys.executable).lower() == "pythonw.exe"
    except Exception:
        return False


def _venv_python(app_dir: str) -> str | None:
    if sys.platform == "win32":
        if _is_windowless_launch():
            pyw = os.path.join(app_dir, "venv", "Scripts", "pythonw.exe")
            if os.path.isfile(pyw):
                return pyw
        candidate = os.path.join(app_dir, "venv", "Scripts", "python.exe")
    else:
        candidate = os.path.join(app_dir, "venv", "bin", "python")
    return candidate if os.path.isfile(candidate) else None


def _same_executable(left: str, right: str) -> bool:
    try:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
    except OSError:
        return False


def _reexec_with_venv(venv_python: str) -> None:
    argv = [venv_python, *sys.argv]
    try:
        os.execv(venv_python, argv)
    except OSError as exc:
        print(
            f"Failed to launch bundled Python:\n  {venv_python}\n\n{exc}\n\n"
            "Run: venv\\Scripts\\pythonw.exe embed_launcher.py",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def _fail_runtime(app_dir: str, message: str) -> None:
    log_path = write_embed_log(app_dir, message)
    full = (
        f"{message}\n\n"
        f"Log: {log_path}\n"
        "On this PC run install_offline.bat inside armorygis_pro.\n"
        "Do not copy venv from another machine."
    )
    print(full, file=sys.stderr, flush=True)
    raise SystemExit(1)


def ensure_runtime(app_dir: str) -> None:
    app_dir = os.path.abspath(app_dir)
    if _is_windowless_launch():
        os.environ.setdefault("ARMORYGIS_EMBEDDED", "1")

    venv_python = _venv_python(app_dir)
    venv_root = os.path.join(app_dir, "venv")

    if os.path.isdir(venv_root):
        full_check = os.environ.get("ARMORYGIS_VENV_FULL_CHECK", "").strip().lower() in {
            "1", "true", "yes",
        }
        ok, reason = check_venv(app_dir, full=full_check)
        if not ok:
            _fail_runtime(app_dir, reason)
    elif _is_windowless_launch():
        _fail_runtime(
            app_dir,
            f"Virtual environment not found at:\n{venv_root}",
        )

    if venv_python and not _same_executable(sys.executable, venv_python):
        _reexec_with_venv(venv_python)

    _prepend_path(app_dir)

    if not os.path.isdir(venv_root):
        return

    candidates = [
        os.path.join(venv_root, "Lib", "site-packages"),
        os.path.join(venv_root, "Lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages"),
    ]
    for path in candidates:
        _prepend_path(path)

    scripts = os.path.join(venv_root, "Scripts")
    if os.path.isdir(scripts):
        path_env = os.environ.get("PATH", "")
        if scripts.lower() not in path_env.lower():
            os.environ["PATH"] = scripts + os.pathsep + path_env
