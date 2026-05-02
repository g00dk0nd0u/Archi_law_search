#!/usr/bin/env python3
"""
Create a lightweight ChatGPT search pack ZIP for this repository.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist"
PACK_NAME_PREFIX = "chatgpt_law_search_pack"
REQUIRED_FILES = (
    ("data/laws.db", REPO_ROOT / "data" / "laws.db"),
    ("chatgpt_pack/search_laws.py", REPO_ROOT / "chatgpt_pack" / "search_laws.py"),
    (
        "chatgpt_pack/CHATGPT_INSTRUCTIONS.md",
        REPO_ROOT / "chatgpt_pack" / "CHATGPT_INSTRUCTIONS.md",
    ),
    ("chatgpt_pack/README.md", REPO_ROOT / "chatgpt_pack" / "README.md"),
)


def build_zip_name(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{PACK_NAME_PREFIX}_{timestamp}.zip"


def validate_required_files() -> list[tuple[str, Path]]:
    missing = [arcname for arcname, path in REQUIRED_FILES if not path.exists()]
    if missing:
        lines = ["Required files are missing:"]
        lines.extend(f"- {item}" for item in missing)
        raise FileNotFoundError("\n".join(lines))
    return list(REQUIRED_FILES)


def create_chatgpt_pack(output_dir: Path | None = None, now: datetime | None = None) -> Path:
    files_to_pack = validate_required_files()
    target_dir = (output_dir or DIST_DIR).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    if not target_dir.is_dir():
        raise NotADirectoryError(f"Output path is not a directory: {target_dir}")

    zip_path = target_dir / build_zip_name(now=now)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, source_path in files_to_pack:
            zf.write(source_path, arcname)

    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a ChatGPT-ready law search pack ZIP."
    )
    parser.add_argument(
        "--output",
        default=str(DIST_DIR),
        help="Output directory. Default: ./dist",
    )
    args = parser.parse_args()

    try:
        zip_path = create_chatgpt_pack(Path(args.output))
    except KeyboardInterrupt:
        print("\n[ERROR] Export cancelled by user.")
        return 130
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1

    print(f"Created ChatGPT pack: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
