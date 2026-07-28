"""Shared SQLite database module for all MCP servers and hooks.

Provides a single project database at .claude/claude.db with WAL mode.
Schema is created automatically on first access (idempotent).

Import pattern:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
    from db import get_db, get_db_path
"""

import json
import sqlite3
from pathlib import Path


SCHEMA = """
-- Projects (projects-first model). Declared FIRST: it is the FK target for
-- every per-project table. A single-project workspace is just one row here
-- besides the always-present `workspace` pseudo-project (id=1, is_workspace=1).
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    path TEXT DEFAULT '',
    description TEXT DEFAULT '',
    is_workspace INTEGER DEFAULT 0,
    enforcement TEXT DEFAULT 'full',        -- 'full' | 'minimal' (scratchpad)
    phase TEXT DEFAULT 'Setup',             -- absorbs the old project_status singleton
    blockers TEXT DEFAULT 'None',
    created_date TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Workspace state (singleton): the active-project pointer. MCP servers cannot
-- read session_state (no session_id reaches call_tool), so the active project
-- is a workspace-global pointer that both MCP servers and hooks resolve.
CREATE TABLE IF NOT EXISTS workspace_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active_project_id INTEGER REFERENCES projects(id)
);

-- Tasks (replaces all board-*.md files). task_id stays globally unique.
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE NOT NULL,
    project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'todo',
    category TEXT NOT NULL DEFAULT 'tasks',
    priority TEXT DEFAULT '',
    agent TEXT DEFAULT '',
    depends_on TEXT DEFAULT '',
    description TEXT DEFAULT '',
    acceptance TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    severity TEXT DEFAULT '',
    source TEXT DEFAULT '',
    test_plan TEXT DEFAULT '',
    completed_date TEXT DEFAULT '',
    created_date TEXT NOT NULL,
    updated_date TEXT NOT NULL
);

-- Activity Log (replaces status.md activity table). Scoped per project.
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
    date TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- (project_status table removed: phase/blockers now live on each projects row.)

-- Doc Routing (replaces doc-routing.json). Path uniqueness is per project so a
-- workspace and a sub-project can each register an overlapping relative path.
CREATE TABLE IF NOT EXISTS doc_routing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
    path TEXT NOT NULL,
    keywords TEXT DEFAULT '[]',
    auto_keywords TEXT DEFAULT '[]',
    source_paths TEXT DEFAULT '[]',
    load_at_start INTEGER DEFAULT 0,
    UNIQUE(project_id, path)
);

-- Code Routing (replaces code-routing.json). Per-project path uniqueness.
CREATE TABLE IF NOT EXISTS code_routing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
    path TEXT NOT NULL,
    description TEXT DEFAULT '',
    line_count INTEGER DEFAULT 0,
    exports TEXT DEFAULT '[]',
    dependencies TEXT DEFAULT '[]',
    keywords TEXT DEFAULT '[]',
    auto_keywords TEXT DEFAULT '[]',
    load_at_start INTEGER DEFAULT 0,
    UNIQUE(project_id, path)
);

-- Session State (replaces session-state/*.json)
CREATE TABLE IF NOT EXISTS session_state (
    session_id TEXT PRIMARY KEY,
    modified_files TEXT DEFAULT '[]',
    mcp_tools TEXT DEFAULT '[]',
    docs_unresolved_issues INTEGER DEFAULT 0,
    tests_failures INTEGER DEFAULT 0,
    security_issues INTEGER DEFAULT 0,
    security_deferred INTEGER DEFAULT 0,
    code_critical_issues INTEGER DEFAULT 0,
    code_advisory_issues INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Review Order (one row per project: the per-project review pipeline state).
CREATE TABLE IF NOT EXISTS review_order (
    project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    code_review_done INTEGER DEFAULT 0,
    code_review_critical INTEGER DEFAULT 0,
    code_review_advisory INTEGER DEFAULT 0,
    doc_review_done INTEGER DEFAULT 0,
    doc_review_unresolved INTEGER DEFAULT 0,
    security_review_done INTEGER DEFAULT 0,
    security_review_issues INTEGER DEFAULT 0,
    security_review_deferred INTEGER DEFAULT 0,
    tests_done INTEGER DEFAULT 0,
    tests_failures INTEGER DEFAULT 0
);

-- Constitution Articles (two-tier: workspace tier = the workspace project's
-- rows; project tier = each project's rows). Numbering is per project, so the
-- workspace and each project number their articles independently from 1.
CREATE TABLE IF NOT EXISTS constitution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    category TEXT DEFAULT 'general',
    context TEXT DEFAULT '',
    rule_text TEXT NOT NULL,
    consequences TEXT DEFAULT '',
    enforcement TEXT DEFAULT '',
    created_date TEXT NOT NULL,
    ratified_date TEXT DEFAULT '',
    amended_date TEXT DEFAULT '',
    revoked_date TEXT DEFAULT '',
    revoked_reason TEXT DEFAULT '',
    source_id TEXT DEFAULT NULL,
    UNIQUE(project_id, number)
);
-- Cross-repo identity for articles. NULL = locally authored;
-- `template:<slug>` = shipped by the template; `project:<slug>` = project-local.
-- Unique per project so two projects may each carry the same source slug.

-- Template Version Tracking (singleton)
CREATE TABLE IF NOT EXISTS template_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    template_version TEXT NOT NULL DEFAULT '1.0.0',
    last_updated TEXT DEFAULT '',
    update_history TEXT DEFAULT '[]'
);

-- Health Metadata (per project, per kind: 'doc' or 'code').
CREATE TABLE IF NOT EXISTS health_metadata (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    last_full_audit TEXT DEFAULT '1970-01-01',
    full_audit_interval_days INTEGER DEFAULT 7,
    size_threshold_lines INTEGER DEFAULT 500,
    PRIMARY KEY (project_id, kind)
);

-- Onboarding (first-run setup wizard)
CREATE TABLE IF NOT EXISTS onboarding (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    complete INTEGER DEFAULT 0,
    project_mode TEXT DEFAULT '',
    project_name TEXT DEFAULT '',
    project_purpose TEXT DEFAULT '',
    tech_stack TEXT DEFAULT '',
    goals TEXT DEFAULT '',
    branching_strategy TEXT DEFAULT '',
    commit_conventions TEXT DEFAULT '',
    review_strictness TEXT DEFAULT '',
    testing_approach TEXT DEFAULT '',
    coding_conventions TEXT DEFAULT '',
    deployment_strategy TEXT DEFAULT '',
    team_structure TEXT DEFAULT '',
    is_existing_repo INTEGER DEFAULT 0,
    analysis_phases TEXT DEFAULT '[]',
    current_phase INTEGER DEFAULT 0,
    phase_progress TEXT DEFAULT '{}',
    greeting TEXT DEFAULT '',
    started_at TEXT DEFAULT '',
    completed_at TEXT DEFAULT ''
);

-- Indexes on per-project foreign keys (every per-project read filters on these).
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_activity_project ON activity_log(project_id);
CREATE INDEX IF NOT EXISTS idx_doc_routing_project ON doc_routing(project_id);
CREATE INDEX IF NOT EXISTS idx_code_routing_project ON code_routing(project_id);
CREATE INDEX IF NOT EXISTS idx_constitution_project ON constitution(project_id);
-- Cross-repo identity, unique per project (NULLs compare distinct, so multiple
-- locally-authored NULL-source_id articles per project are allowed).
CREATE UNIQUE INDEX IF NOT EXISTS idx_constitution_source_id
    ON constitution(project_id, source_id);
"""

# Bootstrap rows seeded at DB creation. FK-safe order: the workspace project
# (id=1) is inserted FIRST so the active-project pointer and every per-project
# singleton can reference it. review_order/health rows for REAL projects are
# seeded by shared/projects.py at project-creation time (this block only knows
# the always-present workspace project).
BOOTSTRAP = """
INSERT OR IGNORE INTO projects (id, slug, name, path, is_workspace, enforcement)
    VALUES (1, 'workspace', 'Workspace', '', 1, 'full');
INSERT OR IGNORE INTO workspace_state (id, active_project_id) VALUES (1, 1);
INSERT OR IGNORE INTO review_order (project_id) VALUES (1);
INSERT OR IGNORE INTO health_metadata (project_id, kind, full_audit_interval_days, size_threshold_lines)
    VALUES (1, 'doc', 7, 500);
INSERT OR IGNORE INTO health_metadata (project_id, kind, full_audit_interval_days, size_threshold_lines)
    VALUES (1, 'code', 2, 1500);
INSERT OR IGNORE INTO onboarding (id) VALUES (1);
INSERT OR IGNORE INTO template_meta (id, template_version) VALUES (1, '1.0.0');
"""


def _nearest_existing_db(start: Path) -> Path | None:
    """Nearest ancestor of `start` (inclusive) that already holds a
    .claude/claude.db, or None. This is the SAFE half of root resolution: it can
    only ever point at a real, already-bootstrapped project DB, so it never
    invents a new root."""
    start = start.resolve()
    for parent in [start, *start.parents]:
        if (parent / ".claude" / "claude.db").exists():
            return parent
    return None


def _find_project_root(start: Path) -> Path:
    """Walk up from `start` to the real project root so a process launched in a
    sub-directory (or a sub-agent whose cwd resolved oddly) doesn't create a
    stray .claude/claude.db. Prefers an existing db, then a .claude/ dir, then
    a .git dir; falls back to `start` if none is found."""
    start = start.resolve()
    nearest = _nearest_existing_db(start)
    if nearest is not None:
        return nearest
    for parent in [start, *start.parents]:
        if (parent / ".claude").is_dir() or (parent / ".git").exists():
            return parent
    return start


def get_db_path(cwd: str | Path | None = None) -> Path:
    """Resolve the path to .claude/claude.db at the project root.

    The workspace root is derived from a *drifting* cwd (a hook's payload `cwd`
    follows the persistent shell, so a single `cd frontend` poisons it for the
    rest of the session). To avoid spawning a stray DB in a sub-directory we
    always resolve UP to the nearest ancestor that already holds a real
    claude.db:

    - explicit `cwd`: if an ancestor DB exists, use it; otherwise honor `cwd`
      exactly. We deliberately do NOT apply the .claude/.git heuristic here --
      under a home directory that contains a bare ~/.claude config dir it would
      wrongly resolve fresh roots (tests, first-run setup) to the home dir and
      bootstrap a DB inside the user's global config.
    - `cwd` is None: walk up from the current directory via _find_project_root
      (the heuristic is acceptable here -- a bare cwd means no caller-supplied
      root to honor)."""
    if cwd:
        start = Path(cwd).resolve()
        nearest = _nearest_existing_db(start)
        root = nearest if nearest is not None else start
    else:
        root = _find_project_root(Path.cwd())
    return root / ".claude" / "claude.db"


def get_project_root(cwd: str | Path | None = None) -> Path:
    """Resolve the workspace root directory, mirroring get_db_path exactly.

    For hook callers that need the root itself (config load, make_relative,
    board-snapshot path) rather than the DB path. Deriving it from the resolved
    DB path guarantees these stay consistent with the DB actually opened -- so a
    drifted `cwd` can no longer register subdir-relative routing or write the
    board snapshot into a sub-directory."""
    return get_db_path(cwd).parent.parent


def get_db(cwd: str | Path | None = None) -> sqlite3.Connection:
    """Open the project database, creating schema if needed.

    Returns a connection with WAL mode and row_factory set to sqlite3.Row.
    Caller is responsible for closing the connection.
    """
    db_path = get_db_path(cwd)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # SCHEMA and BOOTSTRAP are idempotent (CREATE IF NOT EXISTS / INSERT OR
    # IGNORE), so they run on every open whether the db is new or existing.
    conn.executescript(SCHEMA)
    conn.executescript(BOOTSTRAP)
    conn.commit()

    return conn


# --- Convenience helpers ---


def json_loads(text: str) -> list | dict:
    """Safely parse a JSON text field, returning empty list/dict on failure."""
    if not text:
        return []
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []


def json_dumps(obj: list | dict) -> str:
    """Serialize a list or dict to compact JSON text."""
    return json.dumps(obj, separators=(",", ":"))
