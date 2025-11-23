"""
Safe helper to build `src/app.py` into a Windows exe using PyInstaller.

Usage (PowerShell):
    python exe_packaging.py --onefile
    # or
    python exe_packaging.py          # onedir (default, faster startup)

What this script does:
1) Installs PyInstaller if missing (optionally upgrades).
2) Runs PyInstaller against `src/app.py` with a minimal config.
3) Drops the exe under `dist/`.

If you move the entrypoint, adjust MAIN_SCRIPT below.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = ROOT / "src" / "app.py"


def pip_install(pkg: str) -> None:
    """Install a package via pip in the current interpreter."""
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


def ensure_pyinstaller(upgrade: bool = False) -> None:
    """Install or upgrade PyInstaller as needed."""
    if upgrade:
        pip_install("pyinstaller --upgrade")
    else:
        pip_install("pyinstaller")


def build_exe(onefile: bool) -> None:
    """Invoke PyInstaller with a minimal, reproducible configuration."""
    if not MAIN_SCRIPT.exists():
        raise FileNotFoundError(f"Main script not found: {MAIN_SCRIPT}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(MAIN_SCRIPT),
        "--clean",
        "--noconfirm",
        "--name",
        "building_code_search",
        "--collect-all",
        "textual",
        "--collect-all",
        "rich",
    ]

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")  # keeps DLLs extracted; faster startup

    subprocess.check_call(cmd, cwd=ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build src/app.py into an exe with PyInstaller.")
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build a single-file exe (slower startup, larger download). Default: onedir.",
    )
    parser.add_argument(
        "--upgrade-pyinstaller",
        action="store_true",
        help="Upgrade PyInstaller before building.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_pyinstaller(upgrade=args.upgrade_pyinstaller)
    build_exe(onefile=args.onefile)


if __name__ == "__main__":
    main()
