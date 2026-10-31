"""Packaging script for Autonomous AI Supply Chain War Room.

Builds a distributable zip archive in the parent directory with:
- The project folder name at the root of the archive
- Pre-populated SQLite database and scenario replanning timeline data
- Exclusion of virtual environments, caches, git internals, environment secrets, and logs.
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARENT_DIR = PROJECT_ROOT.parent
ZIP_NAME = "Autonomous AI Supply Chain War Room.zip"
ZIP_PATH = PARENT_DIR / ZIP_NAME

# Directories to exclude completely
EXCLUDED_DIR_NAMES = {
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".git",
}

# File extensions or specific filenames to exclude
EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".log",
}

EXCLUDED_FILES = {
    ".env",
}


def should_exclude(rel_path: Path) -> bool:
    """Determine whether a relative path should be excluded from packaging."""
    parts = rel_path.parts

    # Exclude any directory or file matching excluded folder names
    for p in parts:
        if p in EXCLUDED_DIR_NAMES:
            return True

    # Exclude specific files
    if rel_path.name in EXCLUDED_FILES:
        return True

    # Exclude specific extensions
    if rel_path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True

    return False


def build_package() -> None:
    print("=" * 70)
    print("Packaging Autonomous AI Supply Chain War Room")
    print("=" * 70)
    print(f"[*] Source directory : {PROJECT_ROOT}")
    print(f"[*] Destination zip  : {ZIP_PATH}")

    root_dir_name = PROJECT_ROOT.name
    files_to_pack: list[tuple[Path, str]] = []

    for root, dirs, files in os.walk(PROJECT_ROOT):
        # In-place prune dirs to avoid recursing into large excluded trees
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES]

        for f in files:
            file_path = Path(root) / f
            rel_path = file_path.relative_to(PROJECT_ROOT)

            if should_exclude(rel_path):
                continue

            # Format archive path with project folder name at root
            arcname = f"{root_dir_name}/{rel_path.as_posix()}"
            files_to_pack.append((file_path, arcname))

    print(f"[*] Total files matched for packaging: {len(files_to_pack)}")

    # Create zip file with standard DEFLATED compression
    with zipfile.ZipFile(ZIP_PATH, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path, arcname in files_to_pack:
            zf.write(file_path, arcname=arcname)

    size_bytes = ZIP_PATH.stat().st_size
    size_mb = size_bytes / (1024 * 1024)

    print("\n" + "-" * 70)
    print("PACKAGE SUMMARY")
    print("-" * 70)
    print(f"  Zip Path    : {ZIP_PATH.resolve()}")
    print(f"  Zip Size    : {size_mb:.2f} MB ({size_bytes:,} bytes)")
    print(f"  File Count  : {len(files_to_pack)} files")
    print("-" * 70)

    # Verification phase
    verify_package(ZIP_PATH)


def verify_package(zip_path: Path) -> None:
    print("\n" + "=" * 70)
    print("PACKAGE VERIFICATION")
    print("=" * 70)

    with zipfile.ZipFile(zip_path, mode="r") as zf:
        namelist = zf.namelist()
        total_entries = len(namelist)
        print(f"[*] Reading archive contents ({total_entries} entries)...")

        # List first 30 entries
        print("\n--- FIRST 30 ENTRIES ---")
        for i, entry in enumerate(namelist[:30], 1):
            print(f"  {i:2d}. {entry}")

        # Validate exclusion rules across every entry
        violation_found = False
        for entry in namelist:
            parts = entry.split("/")

            # Check directory exclusions
            for p in parts:
                if p in EXCLUDED_DIR_NAMES:
                    print(f"[!] VIOLATION: Excluded directory '{p}' found in entry: {entry}")
                    violation_found = True

            # Check filename exclusions
            filename = parts[-1]
            if filename in EXCLUDED_FILES:
                print(f"[!] VIOLATION: Excluded file '{filename}' found in entry: {entry}")
                violation_found = True

            if any(filename.lower().endswith(ext) for ext in EXCLUDED_EXTENSIONS):
                print(f"[!] VIOLATION: Excluded extension found in entry: {entry}")
                violation_found = True

        # Validate inclusion requirements
        required_inclusions = [
            f"{PROJECT_ROOT.name}/data/warroom.db",
            f"{PROJECT_ROOT.name}/data/csv/suppliers.csv",
            f"{PROJECT_ROOT.name}/data/replan/timeline.json",
        ]

        print("\n--- INCLUSION INTEGRITY CHECK ---")
        for req in required_inclusions:
            if req in namelist:
                print(f"  [+] Confirmed included: {req}")
            else:
                print(f"  [!] MISSING required inclusion: {req}")
                violation_found = True

        print("-" * 70)
        if violation_found:
            print("[!] Verification status: FAILED (Exclusion or inclusion violations detected)")
            sys.exit(1)
        else:
            print("[+] Verification status: PASSED (All exclusions enforced, required data included)")
    print("=" * 70)


if __name__ == "__main__":
    build_package()
