"""Schema + resolver validation: projects-first schema + active-project resolver.

Self-running (no pytest dependency). Exercises real db.py / projects.py against
an isolated temp db so the tracked .claude/claude.db is never touched.

    .claude/venv/bin/python .claude/scripts/tests/test_schema.py
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

SHARED = Path(__file__).resolve().parent.parent / "shared"
sys.path.insert(0, str(SHARED))
from db import get_db, get_db_path, get_project_root  # noqa: E402
import projects as P  # noqa: E402

_checks = 0
_failures = []


def check(label, cond):
    global _checks
    _checks += 1
    if not cond:
        _failures.append(label)
        print(f"  FAIL: {label}")
    else:
        print(f"  ok:   {label}")


def expect_integrity_error(label, fn):
    global _checks
    _checks += 1
    try:
        fn()
    except sqlite3.IntegrityError:
        print(f"  ok:   {label}")
    else:
        _failures.append(label)
        print(f"  FAIL: {label} (expected IntegrityError)")


def run(conn):
    # --- schema shape ---
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    check("projects table exists", "projects" in tables)
    check("workspace_state table exists", "workspace_state" in tables)
    check("project_status table removed", "project_status" not in tables)

    # --- workspace bootstrap ---
    ws = P.get_workspace_project(conn)
    check("workspace project id=1", ws and ws["id"] == 1)
    check("workspace is_workspace=1", ws and ws["is_workspace"] == 1)
    check("workspace has phase/blockers cols", ws and ws["phase"] == "Setup")
    check("active pointer -> workspace", P.get_active_project_id(conn) == 1)
    check(
        "workspace review_order seeded",
        conn.execute(
            "SELECT 1 FROM review_order WHERE project_id = 1"
        ).fetchone()
        is not None,
    )
    check(
        "workspace health rows seeded (doc+code)",
        conn.execute(
            "SELECT COUNT(*) c FROM health_metadata WHERE project_id = 1"
        ).fetchone()["c"]
        == 2,
    )

    # --- FK enforcement ---
    expect_integrity_error(
        "task with bad project_id rejected",
        lambda: conn.execute(
            "INSERT INTO tasks (task_id, project_id, title, created_date, updated_date) "
            "VALUES ('T-x', 999, 't', '2026-01-01', '2026-01-01')"
        ),
    )

    # --- create a real project via the resolver module ---
    web_id = P.ensure_project(conn, "web", "Web", "apps/web", enforcement="full")
    api_id = P.ensure_project(conn, "api", "API", "services/api")
    check("ensure_project returns distinct ids", web_id != api_id and web_id > 1)
    check(
        "new project review_order seeded",
        conn.execute(
            "SELECT 1 FROM review_order WHERE project_id = ?", (web_id,)
        ).fetchone()
        is not None,
    )
    check(
        "new project health seeded",
        conn.execute(
            "SELECT COUNT(*) c FROM health_metadata WHERE project_id = ?", (web_id,)
        ).fetchone()["c"]
        == 2,
    )
    check("ensure_project idempotent by slug", P.ensure_project(conn, "web", "Web", "apps/web") == web_id)

    # --- per-project constitution numbering ---
    for pid in (1, web_id, api_id):
        conn.execute(
            "INSERT INTO constitution (project_id, number, title, rule_text, created_date) "
            "VALUES (?, 1, 'A1', 'rule', '2026-01-01')",
            (pid,),
        )
    conn.commit()
    check(
        "same number=1 allowed across 3 projects",
        conn.execute("SELECT COUNT(*) c FROM constitution WHERE number = 1").fetchone()["c"]
        == 3,
    )
    expect_integrity_error(
        "duplicate (project_id, number) rejected",
        lambda: conn.execute(
            "INSERT INTO constitution (project_id, number, title, rule_text, created_date) "
            "VALUES (1, 1, 'dup', 'r', '2026-01-01')"
        ),
    )

    # --- per-project routing path uniqueness ---
    conn.execute("INSERT INTO doc_routing (project_id, path) VALUES (1, 'docs/index.md')")
    conn.execute("INSERT INTO doc_routing (project_id, path) VALUES (?, 'docs/index.md')", (web_id,))
    conn.commit()
    check("same path allowed across projects", True)
    expect_integrity_error(
        "duplicate (project_id, path) rejected",
        lambda: conn.execute("INSERT INTO doc_routing (project_id, path) VALUES (1, 'docs/index.md')"),
    )

    # --- active pointer roundtrip ---
    P.set_active_project(conn, web_id)
    check("set/get active pointer", P.get_active_project_id(conn) == web_id)

    # --- path inference (longest prefix) ---
    check("infer apps/web file -> web", P.project_for_path(conn, "apps/web/src/a.ts") == web_id)
    check("infer services/api file -> api", P.project_for_path(conn, "services/api/m.py") == api_id)
    check("infer unrelated file -> None", P.project_for_path(conn, "scratch/notes.md") is None)

    # --- resolve_project order ---
    P.set_active_project(conn, 1)
    pid, slug = P.resolve_project(conn, {"project": "api"})
    check("resolve explicit slug wins", pid == api_id and slug == "api")
    pid, slug = P.resolve_project(conn, {})
    check("resolve falls back to active pointer", pid == 1 and slug == "workspace")
    pid, slug = P.resolve_project(conn, {}, source_files=["apps/web/src/a.ts"])
    check("resolve infers from files", pid == web_id)
    check("inference updated active pointer", P.get_active_project_id(conn) == web_id)
    pid, slug = P.resolve_project(conn, {}, source_files=["nowhere/x"])
    check("resolve unknown file -> active pointer (web)", pid == web_id)

    # --- sync from config ---
    P.sync_projects_from_config(conn, {"projects": [{"slug": "docs-site", "name": "Docs", "path": "sites/docs"}]})
    check("sync_projects_from_config creates row", P.get_project_by_slug(conn, "docs-site") is not None)


def run_root_resolution():
    """Root resolution must never spawn a stray .claude/claude.db when the
    caller's cwd has drifted into a sub-directory, yet must still honor a
    genuinely fresh root exactly (not walk up into an unrelated ~/.claude)."""

    # 1. Hook fired from a sub-directory resolves UP to the real workspace DB,
    #    and creates NO stray .claude/ in the sub-directory.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        get_db(root).close()                       # bootstrap the workspace DB
        sub = root / "frontend"
        (sub / "src").mkdir(parents=True)
        resolved = get_db_path(sub)
        check("subdir cwd resolves to workspace DB",
              resolved == root / ".claude" / "claude.db")
        get_db(sub).close()                        # opening from the subdir...
        check("no stray .claude/ created in sub-directory",
              not (sub / ".claude").exists())

    # 2. A genuinely fresh root (no ancestor DB) is honored EXACTLY -- it must
    #    NOT walk up into the user's bare ~/.claude config dir. This pins the
    #    home-pollution hazard: the naive _find_project_root-on-cwd fix regresses
    #    here because ~/.claude is a dir and its .claude heuristic matches.
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp).resolve()
        resolved = get_db_path(fresh)
        check("fresh root honored exactly",
              resolved == fresh / ".claude" / "claude.db")
        # The hazard is collapsing onto the user's bare ~/.claude config dir
        # (which exists but holds no claude.db). The temp dir legitimately lives
        # *under* home on Windows, so "under home" is fine -- "IS the home
        # config DB" is the regression to guard against.
        try:
            home_db = Path.home().resolve() / ".claude" / "claude.db"
            check("fresh root does not collapse onto ~/.claude/claude.db",
                  resolved != home_db)
        except (RuntimeError, OSError):
            pass  # home not resolvable in this environment; skip the assertion

    # 3. Nearest existing DB wins even when an unrelated .git sits in between
    #    (e.g. a vendored repo nested under the workspace).
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        get_db(root).close()
        vendored = root / "vendor" / "lib"
        vendored.mkdir(parents=True)
        (root / "vendor" / ".git").mkdir()
        check("nearest existing DB beats an intermediate .git",
              get_db_path(vendored) == root / ".claude" / "claude.db")

    # 4. get_project_root mirrors get_db_path's resolution exactly.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        get_db(root).close()
        sub = root / "frontend"
        sub.mkdir()
        check("get_project_root mirrors get_db_path",
              get_project_root(sub) == get_db_path(sub).parent.parent == root)


def main():
    run_root_resolution()
    with tempfile.TemporaryDirectory() as tmp:
        conn = get_db(Path(tmp))
        try:
            run(conn)
        finally:
            conn.close()
    print()
    if _failures:
        print(f"SCHEMA: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"SCHEMA: all {_checks} checks passed")


if __name__ == "__main__":
    main()
