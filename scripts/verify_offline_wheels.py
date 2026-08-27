"""Verify offline_packages contains wheels for requirements-offline.txt."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ_FILE = ROOT / "requirements-offline.txt"
PKG_DIR = ROOT / "offline_packages"


def _normalize_dist(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _parse_requirements(path: Path) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pkg = re.split(r"[<>=!~]", line, maxsplit=1)[0].strip()
        specs.append((pkg, line))
    return specs


def _wheel_dist_name(filename: str) -> str:
    stem = filename[:-4] if filename.lower().endswith(".whl") else filename
    parts = stem.split("-")
    dist_parts: list[str] = []
    for part in parts[1:]:
        if re.match(r"^\d", part):
            break
        dist_parts.append(part)
    if not dist_parts and parts:
        return parts[0]
    return "-".join([parts[0], *dist_parts]) if dist_parts else parts[0]


def _matches_package(wheel_name: str, package_name: str) -> bool:
    return _normalize_dist(_wheel_dist_name(wheel_name)) == _normalize_dist(package_name)


def _abi_tag() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def _wheel_abi_ok(wheel_name: str, abi: str) -> bool:
    lowered = wheel_name.lower()
    if "py3-none-any" in lowered:
        return True
    if "-abi3-" in lowered:
        return True
    if "py3-none-win_amd64" in lowered:
        return True
    return f"-{abi}-" in lowered


def main(argv: list[str]) -> int:
    check_current = "--for-current-python" in argv

    if not PKG_DIR.is_dir():
        print("[FAIL] offline_packages folder not found.")
        return 1

    if not REQ_FILE.is_file():
        print(f"[FAIL] Missing {REQ_FILE.name}")
        return 1

    wheels = sorted(PKG_DIR.glob("*.whl"))
    if len(wheels) < 5:
        print(f"[FAIL] Too few wheel files in offline_packages ({len(wheels)}).")
        return 1

    specs = _parse_requirements(REQ_FILE)
    missing_any: list[str] = []
    missing_abi: list[str] = []
    abi = _abi_tag() if check_current else ""

    for pkg, spec in specs:
        matched = [w for w in wheels if _matches_package(w.name, pkg)]
        if not matched:
            missing_any.append(spec)
            continue
        if check_current and not any(_wheel_abi_ok(w.name, abi) for w in matched):
            missing_abi.append(spec)

    if missing_any:
        print("[FAIL] No wheel file found for:")
        for spec in missing_any:
            print(f"  - {spec}")
        print("Re-run download_offline_packages.bat on a PC with internet.")

    if missing_abi:
        print(f"[FAIL] Wheels exist but none match Python {abi} (win_amd64) for:")
        for spec in missing_abi:
            print(f"  - {spec}")
        print("Re-run download_offline_packages.bat (downloads 3.10/3.11/3.12 wheels).")

    if missing_any or missing_abi:
        return 1

    print(f"[OK] All {len(specs)} requirements have local wheels ({len(wheels)} files).")
    if check_current:
        print(f"[OK] Compatible with Python {abi}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
