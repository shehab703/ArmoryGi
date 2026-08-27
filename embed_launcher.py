"""ArmoryGIS Pro — embed launcher for WinForms host."""
from __future__ import annotations

import argparse
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.environ.setdefault("ARMORYGIS_EMBEDDED", "1")


def _relaunch_with_venv_python() -> None:
    if sys.platform != "win32":
        return
    venv_pyw = os.path.join(APP_DIR, "venv", "Scripts", "pythonw.exe")
    venv_py = os.path.join(APP_DIR, "venv", "Scripts", "python.exe")
    target = venv_pyw if os.path.isfile(venv_pyw) else venv_py
    if not os.path.isfile(target):
        return
    if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(os.path.abspath(target)):
        return
    os.execv(target, [target, *sys.argv])


_relaunch_with_venv_python()

from runtime_bootstrap import ensure_runtime  # noqa: E402

ensure_runtime(APP_DIR)

from main import run_app  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ArmoryGIS Pro embed launcher")
    parser.add_argument("--skip-login", action="store_true", default=True)
    parser.add_argument("--embedded", action="store_true", default=True)
    parser.add_argument(
        "--username",
        default=os.environ.get("ARMORYGIS_EMBED_USER", "analyst"),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    code = run_app(
        skip_login=True,
        embedded=True,
        username=args.username,
    )
    sys.exit(code if isinstance(code, int) else 0)
