"""
Central configuration: every file path and env-driven setting in one place.

All locations can be overridden from .env:
  ALPHA_DB_PATH        — SQLite experiment store (default runtime/alpha_lab.db)
  GENALPHA_DATA_DIR    — tracked reference data + result exports (default data/)
  GENALPHA_RUNTIME_DIR — gitignored state: logs, caches, models (default runtime/)
  API_PORT, FLASK_DEBUG — backend server settings
"""

import os
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")


def _env_path(var, default):
    """Resolve an env-provided path; relative values are repo-root-relative."""
    raw = os.getenv(var)
    if not raw:
        return Path(default)
    p = Path(raw).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p


DATA_DIR = _env_path("GENALPHA_DATA_DIR", REPO_ROOT / "data")
RUNTIME_DIR = _env_path("GENALPHA_RUNTIME_DIR", REPO_ROOT / "runtime")
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

# ── SQLite experiment store ───────────────────────────────────────
DB_PATH = _env_path("ALPHA_DB_PATH", RUNTIME_DIR / "alpha_lab.db")

# ── Reference data (tracked in git) ──────────────────────────────
BRAIN_FIELDS = DATA_DIR / "brain_fields.json"
BRAIN_OPERATORS = DATA_DIR / "brain_operators.json"
BRAIN_SUMMARY = DATA_DIR / "brain_summary.json"
RESEARCH_TEMPLATES = DATA_DIR / "research_templates.json"

# ── Result exports (tracked in git) ──────────────────────────────
SIM_HISTORY = DATA_DIR / "simulation_history.json"
FOUND_ALPHAS = DATA_DIR / "found_alphas.json"
LLM_ALPHAS = DATA_DIR / "llm_generated_alphas.json"

# ── Runtime state (gitignored) ────────────────────────────────────
PIPELINE_STATE = RUNTIME_DIR / "pipeline_state.json"
PIPELINE_LOG = RUNTIME_DIR / "pipeline_progress.log"
RECOVERY_FILE = RUNTIME_DIR / "recovery_queue.json"
LATEST_RUN = RUNTIME_DIR / "latest_run.json"
PNL_CACHE_DIR = RUNTIME_DIR / "cache" / "pnl"
FITNESS_MODEL = RUNTIME_DIR / "fitness_model.pkl"
ALPHA_INTELLIGENCE = RUNTIME_DIR / "alpha_intelligence.json"
FITNESS_PLOT = RUNTIME_DIR / "fitness_progression.png"
PLOTS_DIR = RUNTIME_DIR / "plots"
LEGACY_PAPERS_FILE = RUNTIME_DIR / "processed_papers.json"

# Optional local credential fallback (gitignored)
CREDENTIALS_FILE = REPO_ROOT / "credential.txt"

# ── Server ────────────────────────────────────────────────────────
API_PORT = int(os.getenv("API_PORT", "5001"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
