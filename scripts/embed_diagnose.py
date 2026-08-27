"""Preflight checks for ArmoryGIS embed / offline install."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from utils.venv_health import check_venv, write_embed_log  # noqa: E402


def _check_offline_packages() -> tuple[bool, str]:
    pkg_dir = APP_DIR / "offline_packages"
    if not pkg_dir.is_dir():
        return False, f"offline_packages folder missing: {pkg_dir}"
    wheels = list(pkg_dir.glob("*.whl"))
    if not wheels:
        return False, f"No .whl files in {pkg_dir}"
    return True, f"{len(wheels)} wheel(s) in offline_packages"


def main() -> int:
    parser = argparse.ArgumentParser(description="ArmoryGIS embed preflight")
    parser.add_argument("--quiet", action="store_true", help="Only print on failure")
    args = parser.parse_args()

    lines = [f"ArmoryGIS embed diagnose — {datetime.now().isoformat(timespec='seconds')}"]
    ok = True

    embed_script = APP_DIR / "embed_launcher.py"
    if embed_script.is_file():
        lines.append(f"[OK] embed_launcher.py: {embed_script}")
    else:
        ok = False
        lines.append(f"[FAIL] embed_launcher.py missing: {embed_script}")

    pkg_ok, pkg_msg = _check_offline_packages()
    lines.append(f"[{'OK' if pkg_ok else 'WARN'}] {pkg_msg}")

    venv_ok, venv_msg = check_venv(str(APP_DIR), full=True)
    if venv_ok:
        lines.append("[OK] venv + PyQt6 WebEngine verified")
    else:
        ok = False
        lines.append("[FAIL] venv check:")
        lines.append(venv_msg)

    report = "\n".join(lines)
    if not args.quiet or not ok:
        print(report)

    if not ok:
        log_path = write_embed_log(str(APP_DIR), report)
        print(f"\nDetails written to: {log_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
