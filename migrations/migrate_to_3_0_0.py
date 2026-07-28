#!/usr/bin/env python3
"""
Upgrade-Migration Legacy → 3.x (Wrapper).

Die eigentliche Logik liegt in migrate_to_3_0_1_full_upgrade.py
(modellbasierte Tabellen-/Spalten-Sync + Daten-Backfills).

Aufruf:
  python migrations/migrate_to_3_0_0.py
  python migrations/migrate_to_3_0_0.py --force
  python migrations/run_all.py
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from migrate_to_3_0_1_full_upgrade import migrate  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Legacy-Upgrade (Wrapper auf 3.0.1 Full Upgrade)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Schema-Sync erneut ausführen",
    )
    args = parser.parse_args()
    ok = migrate(force=args.force)
    sys.exit(0 if ok else 1)
