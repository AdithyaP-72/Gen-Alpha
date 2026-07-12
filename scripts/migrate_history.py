#!/usr/bin/env python3
"""
One-time migration: simulation_history.json (JSON Lines) → alpha_lab.db (SQLite).

Safe by design:
  - Backs up the JSONL file first (timestamped copy).
  - Imports inside a single transaction — a crash leaves the store unchanged.
  - Idempotent: re-running dedupes on (canonical_expression, settings_json).
  - Rows whose alpha_id starts with 'inv_' (locally fabricated "negated" results
    from the old sign-flip code path) are flagged derived=1 and excluded from
    ML training and mutation targeting.

Run while the pipeline is stopped:
    python3 scripts/migrate_history.py
"""

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from genalpha import config
from genalpha.alpha_store import AlphaStore
from genalpha.alpha_validation import analyze_expression

HISTORY = config.SIM_HISTORY


def main():
    if not HISTORY.exists():
        print("No simulation_history.json found — nothing to migrate.")
        return

    backup = HISTORY.with_name(f"simulation_history.backup-{time.strftime('%Y%m%d-%H%M%S')}.json")
    shutil.copy2(HISTORY, backup)
    print(f"Backed up history to {backup}")

    field_index = {}
    if config.BRAIN_FIELDS.exists():
        with open(config.BRAIN_FIELDS) as f:
            field_index = {fl["id"]: fl for fl in json.load(f)}

    jsonl_lines = sum(1 for line in open(HISTORY) if line.strip())

    store = AlphaStore()
    with store._connect() as conn:
        existing_runs = conn.execute("SELECT COUNT(*) AS n FROM simulation_runs").fetchone()["n"]
    if existing_runs > 0:
        print(f"Store already contains {existing_runs} simulation runs — refusing to double-import.")
        print("Delete alpha_lab.db first if you really want to re-migrate.")
        return
    candidates, runs = store.migrate_history_jsonl(
        str(HISTORY),
        analyze=lambda expr: analyze_expression(expr, field_index),
    )

    print(f"JSONL rows:            {jsonl_lines}")
    print(f"Simulation runs added: {runs}")
    print(f"Candidates in store:   {candidates}")
    if runs < jsonl_lines:
        print(f"Note: {jsonl_lines - runs} rows were skipped (empty/unparseable expressions).")
    print("Done. train_recommender.py will now read from the SQLite store automatically.")


if __name__ == "__main__":
    main()
