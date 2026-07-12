"""
Persistent storage for alpha candidates, simulation runs, and promoted survivors.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path

from genalpha.config import DB_PATH, SIM_HISTORY


class AlphaStore:
    """SQLite-backed experiment store for candidate lineage and outcomes."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL: one writer (pipeline) + many readers (api_server) without blocking.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_expression TEXT NOT NULL,
                    expression TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    source TEXT,
                    template_name TEXT,
                    hypothesis_family TEXT,
                    field_id TEXT,
                    mutation_type TEXT,
                    parent_candidate_id INTEGER,
                    priority REAL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'generated',
                    validation_notes TEXT,
                    metadata_json TEXT,
                    ast_json TEXT,
                    derived INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(canonical_expression, settings_json)
                );

                CREATE TABLE IF NOT EXISTS papers (
                    entry_id TEXT PRIMARY KEY,
                    domain TEXT,
                    title TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    anomaly_json TEXT,
                    created_at REAL,
                    updated_at REAL
                );

                CREATE TABLE IF NOT EXISTS llm_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id TEXT,
                    candidate_id INTEGER,
                    role TEXT NOT NULL,
                    round INTEGER DEFAULT 0,
                    model TEXT,
                    prompt_tokens INTEGER,
                    response_json TEXT,
                    created_at REAL
                );

                CREATE TABLE IF NOT EXISTS simulation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    sharpe REAL,
                    fitness REAL,
                    turnover REAL,
                    returns REAL,
                    drawdown REAL,
                    alpha_id TEXT,
                    checks_json TEXT,
                    error_text TEXT,
                    raw_result_json TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(id)
                );

                CREATE TABLE IF NOT EXISTS promoted_alphas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL UNIQUE,
                    expression TEXT NOT NULL,
                    canonical_expression TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    fitness REAL,
                    sharpe REAL,
                    novelty_score REAL,
                    robustness_score REAL,
                    rationale_json TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(id)
                );

                CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
                CREATE INDEX IF NOT EXISTS idx_runs_candidate_id ON simulation_runs(candidate_id);
                CREATE INDEX IF NOT EXISTS idx_runs_fitness ON simulation_runs(fitness);
                CREATE INDEX IF NOT EXISTS idx_promoted_canonical ON promoted_alphas(canonical_expression);
                CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
                """
            )
            # Older DBs may predate the ast_json/derived columns.
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(candidates)")}
            if "ast_json" not in existing:
                conn.execute("ALTER TABLE candidates ADD COLUMN ast_json TEXT")
            if "derived" not in existing:
                conn.execute("ALTER TABLE candidates ADD COLUMN derived INTEGER DEFAULT 0")

    def upsert_candidate(self, candidate):
        """Insert or update a candidate and return its ID."""
        settings_json = json.dumps(candidate["settings"], sort_keys=True)
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, parent_candidate_id FROM candidates
                WHERE canonical_expression = ? AND settings_json = ?
                """,
                (candidate["canonical_expression"], settings_json),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE candidates
                    SET expression = ?, source = ?, template_name = ?, hypothesis_family = ?,
                        field_id = ?, mutation_type = ?, priority = ?, status = ?,
                        validation_notes = ?, metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        candidate["expression"],
                        candidate.get("source"),
                        candidate.get("template_name"),
                        candidate.get("hypothesis_family"),
                        candidate.get("field"),
                        candidate.get("mutation_type"),
                        candidate.get("priority", 0),
                        candidate.get("status", "generated"),
                        candidate.get("validation_notes"),
                        json.dumps(candidate.get("metadata", {}), sort_keys=True),
                        now,
                        row["id"],
                    ),
                )
                return row["id"]

            cursor = conn.execute(
                """
                INSERT INTO candidates (
                    canonical_expression, expression, settings_json, source, template_name,
                    hypothesis_family, field_id, mutation_type, parent_candidate_id,
                    priority, status, validation_notes, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate["canonical_expression"],
                    candidate["expression"],
                    settings_json,
                    candidate.get("source"),
                    candidate.get("template_name"),
                    candidate.get("hypothesis_family"),
                    candidate.get("field"),
                    candidate.get("mutation_type"),
                    candidate.get("parent_candidate_id"),
                    candidate.get("priority", 0),
                    candidate.get("status", "generated"),
                    candidate.get("validation_notes"),
                    json.dumps(candidate.get("metadata", {}), sort_keys=True),
                    now,
                    now,
                ),
            )
            return cursor.lastrowid

    def set_candidate_status(self, candidate_id, status, validation_notes=None):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE candidates
                SET status = ?, validation_notes = COALESCE(?, validation_notes), updated_at = ?
                WHERE id = ?
                """,
                (status, validation_notes, time.time(), candidate_id),
            )

    def get_candidate_by_id(self, candidate_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
        return dict(row) if row else None

    def record_simulation(self, candidate_id, status, result=None, error_text=None):
        result = result or {}
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO simulation_runs (
                    candidate_id, status, sharpe, fitness, turnover, returns, drawdown,
                    alpha_id, checks_json, error_text, raw_result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    status,
                    result.get("sharpe"),
                    result.get("fitness"),
                    result.get("turnover"),
                    result.get("returns"),
                    result.get("drawdown"),
                    result.get("alpha_id"),
                    json.dumps(result.get("checks", [])),
                    error_text,
                    json.dumps(result, sort_keys=True),
                    time.time(),
                ),
            )
            conn.execute(
                "UPDATE candidates SET status = ?, updated_at = ? WHERE id = ?",
                ("simulated" if status == "complete" else "rejected", time.time(), candidate_id),
            )

    def promote_candidate(self, candidate_id, expression, canonical_expression, settings, result, novelty_score, robustness_score, rationale):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO promoted_alphas (
                    candidate_id, expression, canonical_expression, settings_json, fitness, sharpe,
                    novelty_score, robustness_score, rationale_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    expression,
                    canonical_expression,
                    json.dumps(settings, sort_keys=True),
                    result.get("fitness"),
                    result.get("sharpe"),
                    novelty_score,
                    robustness_score,
                    json.dumps(rationale, sort_keys=True),
                    time.time(),
                ),
            )
            conn.execute(
                "UPDATE candidates SET status = ?, updated_at = ? WHERE id = ?",
                ("survivor", time.time(), candidate_id),
            )

    def get_history_entries(self):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.expression, c.settings_json, c.source, c.template_name, c.hypothesis_family,
                       c.field_id, c.mutation_type, c.metadata_json, r.*
                FROM simulation_runs r
                JOIN candidates c ON c.id = r.candidate_id
                WHERE r.status = 'complete' AND COALESCE(c.derived, 0) = 0
                ORDER BY r.id
                """
            ).fetchall()
        entries = []
        for row in rows:
            entries.append(
                {
                    "timestamp": row["created_at"],
                    "expression": row["expression"],
                    "settings": json.loads(row["settings_json"]),
                    "source": row["source"],
                    "template_name": row["template_name"],
                    "hypothesis_family": row["hypothesis_family"],
                    "field_id": row["field_id"],
                    "mutation_type": row["mutation_type"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                    "sharpe": row["sharpe"],
                    "fitness": row["fitness"],
                    "turnover": row["turnover"],
                    "returns": row["returns"],
                    "drawdown": row["drawdown"],
                    "checks": json.loads(row["checks_json"] or "[]"),
                }
            )
        return entries

    def get_promoted_signatures(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT canonical_expression, rationale_json, novelty_score, robustness_score FROM promoted_alphas"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_successful_candidates(self, min_fitness=0.6, limit=50):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.expression, c.settings_json, c.source, c.template_name, c.hypothesis_family,
                       c.field_id, c.mutation_type, c.metadata_json, MAX(r.fitness) AS best_fitness
                FROM candidates c
                JOIN simulation_runs r ON r.candidate_id = c.id
                WHERE r.status = 'complete' AND COALESCE(c.derived, 0) = 0
                GROUP BY c.id
                HAVING MAX(r.fitness) >= ?
                ORDER BY best_fitness DESC
                LIMIT ?
                """,
                (min_fitness, limit),
            ).fetchall()
        results = []
        for row in rows:
            results.append(
                {
                    "candidate_id": row["id"],
                    "expression": row["expression"],
                    "settings": json.loads(row["settings_json"]),
                    "source": row["source"],
                    "template_name": row["template_name"],
                    "hypothesis_family": row["hypothesis_family"],
                    "field": row["field_id"],
                    "mutation_type": row["mutation_type"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                    "fitness": row["best_fitness"],
                }
            )
        return results

    # ── Paper tracking (replaces processed_papers.json) ──────────
    def get_paper_ids(self, statuses=("processed", "not_tradeable"), max_retries=3):
        """Paper entry_ids that should not be re-processed.

        Includes retry-exhausted failures so a paper that keeps crashing the
        LLM step can't burn quota forever.
        """
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT entry_id FROM papers WHERE status IN ({placeholders}) "
                f"OR (status = 'failed' AND retry_count >= ?)",
                tuple(statuses) + (max_retries,),
            ).fetchall()
        return {row["entry_id"] for row in rows}

    def get_paper(self, entry_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM papers WHERE entry_id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None

    def record_paper(self, entry_id, domain=None, title=None, status="pending", anomaly=None):
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO papers (entry_id, domain, title, status, retry_count, anomaly_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET
                    status = excluded.status,
                    anomaly_json = COALESCE(excluded.anomaly_json, papers.anomaly_json),
                    retry_count = papers.retry_count + (CASE WHEN excluded.status = 'failed' THEN 1 ELSE 0 END),
                    updated_at = excluded.updated_at
                """,
                (entry_id, domain, title, status,
                 json.dumps(anomaly) if anomaly else None, now, now),
            )

    # ── LLM interaction audit trail (actor-critic / Chain-of-Alpha) ──
    def record_llm_interaction(self, role, response, paper_id=None, candidate_id=None,
                               round_idx=0, model=None, prompt_tokens=None):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_interactions (paper_id, candidate_id, role, round, model, prompt_tokens, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (paper_id, candidate_id, role, round_idx, model, prompt_tokens,
                 json.dumps(response, sort_keys=True) if response is not None else None,
                 time.time()),
            )

    # ── One-time migration from JSON Lines history ───────────────
    def migrate_history_jsonl(self, path=None, analyze=None):
        """Import legacy JSONL history in ONE transaction (atomic: all or nothing).

        `analyze` is alpha_validation.analyze_expression bound to a field index;
        passing it in avoids a circular import.
        Returns (candidates_inserted, runs_inserted).
        """
        path = str(path or SIM_HISTORY)
        entries = []
        if not Path(path).exists():
            return 0, 0
        with open(path) as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        runs = 0
        now = time.time()
        with self._lock, self._connect() as conn:
            for entry in entries:
                expr = entry.get("expression", "")
                if isinstance(expr, dict):
                    expr = expr.get("code", json.dumps(expr, sort_keys=True))
                if not expr:
                    continue
                settings = entry.get("settings", {}) or {}
                settings_json = json.dumps(settings, sort_keys=True)
                if analyze:
                    try:
                        canonical, metadata = analyze(expr)
                    except Exception:
                        canonical, metadata = expr, {}
                else:
                    canonical, metadata = expr, {}
                alpha_id = entry.get("alpha_id") or ""
                derived = 1 if str(alpha_id).startswith("inv_") else 0

                row = conn.execute(
                    "SELECT id FROM candidates WHERE canonical_expression = ? AND settings_json = ?",
                    (canonical, settings_json),
                ).fetchone()
                if row:
                    candidate_id = row["id"]
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO candidates (
                            canonical_expression, expression, settings_json, source, template_name,
                            hypothesis_family, field_id, mutation_type, priority, status,
                            metadata_json, derived, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'simulated', ?, ?, ?, ?)
                        """,
                        (canonical, expr, settings_json,
                         entry.get("source", "legacy"), entry.get("template_name"),
                         metadata.get("hypothesis_family"), metadata.get("field_id"),
                         entry.get("mutation_type", "none"),
                         json.dumps(metadata, sort_keys=True), derived,
                         entry.get("timestamp", now), now),
                    )
                    candidate_id = cursor.lastrowid

                fitness = entry.get("fitness")
                status = "complete" if fitness is not None else (entry.get("status") or "failed").lower()
                if status == "complete" and fitness is None:
                    status = "failed"
                conn.execute(
                    """
                    INSERT INTO simulation_runs (
                        candidate_id, status, sharpe, fitness, turnover, returns, drawdown,
                        alpha_id, checks_json, error_text, raw_result_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, '{}', ?)
                    """,
                    (candidate_id, status, entry.get("sharpe"), fitness,
                     entry.get("turnover"), entry.get("returns"), entry.get("drawdown"),
                     alpha_id or None, entry.get("error"), entry.get("timestamp", now)),
                )
                runs += 1
            count = conn.execute("SELECT COUNT(*) AS n FROM candidates").fetchone()["n"]
        return count, runs
