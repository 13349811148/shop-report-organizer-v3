#!/usr/bin/env python
"""Create the non-destructive V3 operations-database directory skeleton."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from database_layout import REQUIRED_DIRECTORIES, ensure_layout


def default_database_root() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "运营数据库"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize the V3 operations database layout.")
    parser.add_argument("--database-root", default=str(default_database_root()))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.database_root).resolve()
    created = ensure_layout(root)
    print(f"database root: {root}")
    if created:
        for path in created:
            print(f"created: {path}")
    else:
        print("layout already complete")
    print("required folders:")
    for name in REQUIRED_DIRECTORIES:
        print(f"- {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
