"""Project registry + active-project resolution for the projects-first model.

The data model is projects-first: there is always a `projects` collection. A
single-project workspace is one real project plus the always-present `workspace`
pseudo-project (id=1). Per-project state (tasks, review_order, health,
constitution, routing) keys off `projects.id`.

ACTIVE PROJECT. MCP `call_tool(name, arguments)` receives no session id, so no
MCP server can read `session_state`. The active project is therefore a
workspace-global singleton pointer (`workspace_state.active_project_id`) that
both MCP servers and hooks resolve. Resolution order for a project-scoped op:

    1. explicit `project=<slug>` argument           (wins)
    2. the active-project pointer                    (workspace-global)
    3. inference from files in play (longest path)   (then sets the pointer)
    4. the `workspace` project                       (fallback)

Import pattern (same as db.py):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
    from projects import resolve_project, get_active_project_id
"""

import sqlite3

WORKSPACE_ID = 1
WORKSPACE_SLUG = "workspace"

# Per-kind health defaults seeded for every project (mirror db.BOOTSTRAP).
_HEALTH_DEFAULTS = {
    "doc": (7, 500),
    "code": (2, 1500),
}


# --- Lookups ---


def get_project_by_id(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def get_project_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()


def get_workspace_project(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return get_project_by_id(conn, WORKSPACE_ID)


def list_projects(
    conn: sqlite3.Connection, include_workspace: bool = False
) -> list[sqlite3.Row]:
    """All projects ordered by id. The workspace pseudo-project is excluded
    unless include_workspace=True (it is rarely a board the user works in)."""
    if include_workspace:
        return conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM projects WHERE is_workspace = 0 ORDER BY id"
    ).fetchall()


def project_label(conn: sqlite3.Connection, project_id: int) -> str:
    """The slug used for the `[project: <slug>]` echo on MCP responses."""
    row = get_project_by_id(conn, project_id)
    return row["slug"] if row else WORKSPACE_SLUG


# --- Active-project pointer (workspace-global singleton) ---


def get_active_project_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT active_project_id FROM workspace_state WHERE id = 1"
    ).fetchone()
    resolved = WORKSPACE_ID
    if row and row["active_project_id"]:
        # Guard against a dangling pointer (project deleted out from under it).
        if get_project_by_id(conn, row["active_project_id"]):
            resolved = row["active_project_id"]
    # The workspace is the umbrella, never a working board. A single-project
    # workspace must therefore default to its one real project — even when the
    # pointer resolves to the workspace (the bootstrap seed, an unset pointer, or
    # a stale value), so a fresh session never lands on the empty umbrella. Only
    # a genuinely ambiguous workspace (0 or >1 real projects) stays on the
    # workspace. Explicit `project=workspace` is honored earlier in
    # resolve_project, so this default never blocks reaching the umbrella on purpose.
    if resolved == WORKSPACE_ID:
        reals = conn.execute(
            "SELECT id FROM projects WHERE is_workspace = 0 ORDER BY id"
        ).fetchall()
        if len(reals) == 1:
            return reals[0]["id"]
    return resolved


def get_active_project(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return get_project_by_id(conn, get_active_project_id(conn))


def set_active_project(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute(
        "INSERT INTO workspace_state (id, active_project_id) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET active_project_id = excluded.active_project_id",
        (project_id,),
    )
    conn.commit()


# --- Project creation / sync ---


def seed_project_singletons(conn: sqlite3.Connection, project_id: int) -> None:
    """Create the per-project review_order + health rows (idempotent)."""
    conn.execute(
        "INSERT OR IGNORE INTO review_order (project_id) VALUES (?)", (project_id,)
    )
    for kind, (interval, threshold) in _HEALTH_DEFAULTS.items():
        conn.execute(
            "INSERT OR IGNORE INTO health_metadata "
            "(project_id, kind, full_audit_interval_days, size_threshold_lines) "
            "VALUES (?, ?, ?, ?)",
            (project_id, kind, interval, threshold),
        )


def ensure_project(
    conn: sqlite3.Connection,
    slug: str,
    name: str,
    path: str = "",
    description: str = "",
    enforcement: str = "full",
    is_workspace: int = 0,
) -> int:
    """Upsert a project by slug; seed its per-project singletons. Returns its id.

    Identity fields (name/path/description/enforcement) follow config on update;
    runtime fields (phase/blockers) are preserved for an existing row.
    """
    existing = get_project_by_slug(conn, slug)
    if existing:
        conn.execute(
            "UPDATE projects SET name = ?, path = ?, description = ?, enforcement = ? "
            "WHERE slug = ?",
            (name, path, description, enforcement, slug),
        )
        project_id = existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO projects (slug, name, path, description, is_workspace, enforcement) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, path, description, is_workspace, enforcement),
        )
        project_id = cur.lastrowid
    seed_project_singletons(conn, project_id)
    conn.commit()
    return project_id


def sync_projects_from_config(conn: sqlite3.Connection, config: dict) -> None:
    """Ensure a DB project row exists for every config `projects[]` entry.

    Config is authoritative for identity; the DB owns runtime state. Called at
    MCP-server / hook entry so the registry tracks the declarative config.
    """
    for entry in config.get("projects", []) or []:
        slug = entry.get("slug")
        if not slug:
            continue
        ensure_project(
            conn,
            slug=slug,
            name=entry.get("name", slug),
            path=entry.get("path", ""),
            description=entry.get("description", ""),
            enforcement=entry.get("enforcement", config.get("enforcement", "full")),
        )


# --- Inference + resolution ---


def project_for_path(conn: sqlite3.Connection, filepath: str) -> int | None:
    """Longest-path-prefix match of a file to a REAL project. The workspace
    project (path='') is never matched here; it is the fallback, not a prefix."""
    norm = filepath.replace("\\", "/").lstrip("./")
    best_id = None
    best_len = -1
    for proj in conn.execute(
        "SELECT id, path FROM projects WHERE is_workspace = 0 AND path != ''"
    ).fetchall():
        p = proj["path"].replace("\\", "/").rstrip("/")
        if norm == p or norm.startswith(p + "/"):
            if len(p) > best_len:
                best_id, best_len = proj["id"], len(p)
    return best_id


def resolve_project(
    conn: sqlite3.Connection,
    args: dict | None = None,
    source_files: list[str] | None = None,
    set_active_on_infer: bool = True,
) -> tuple[int, str]:
    """Resolve the project for an operation. Returns (project_id, slug).

    Order: explicit `project=` arg > active pointer > file inference > workspace.
    On a successful file inference that differs from the current pointer, the
    pointer is updated (so subsequent board ops follow the work) unless
    set_active_on_infer is False.
    """
    args = args or {}

    # 1. Explicit override (accept slug or numeric id).
    explicit = args.get("project")
    if explicit not in (None, "", "all"):
        row = None
        if isinstance(explicit, int) or (isinstance(explicit, str) and explicit.isdigit()):
            row = get_project_by_id(conn, int(explicit))
        if row is None:
            row = get_project_by_slug(conn, str(explicit))
        if row:
            return row["id"], row["slug"]
        # Unknown explicit project: fall through to resolution rather than guess.

    # 3 (tried before 2 only when files are present): infer from files in play.
    if source_files:
        inferred = None
        for f in source_files:
            pid = project_for_path(conn, f)
            if pid is not None:
                inferred = pid if inferred in (None, pid) else -1  # -1 = ambiguous
        if inferred not in (None, -1):
            if set_active_on_infer and inferred != get_active_project_id(conn):
                set_active_project(conn, inferred)
            return inferred, project_label(conn, inferred)

    # 2. Active pointer (or 4. workspace fallback via get_active_project_id).
    pid = get_active_project_id(conn)
    return pid, project_label(conn, pid)
