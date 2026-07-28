"""code_manager validation: project-scoped code_manager MCP handlers.

Exercises the real code_manager handlers against an isolated temp workspace.
Handlers call get_db() (which uses Path.cwd()), so the test chdir's into the
temp dir -- mirroring test_routing.py -- and the tracked .claude/claude.db
is never touched.

Covers:
  * get_relevant_modules returns ONLY active+workspace modules (a foreign
    project's module, seeded with identical keywords, is excluded by SCOPING
    rather than by scoring).
  * acknowledge_code_review / acknowledge_security_review write to the ACTIVE
    project's review_order row; a second project's row stays untouched.
  * check_code_health reads the active project's health row (low threshold ->
    active routing row flagged) and scopes routing reads (foreign row absent).

    .claude/venv/bin/python .claude/scripts/tests/test_code_manager.py
"""

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

SHARED = Path(__file__).resolve().parent.parent / "shared"
MCP = Path(__file__).resolve().parent.parent / "mcp"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(MCP))

_checks = 0
_failures = []


def check(label, cond):
    global _checks
    _checks += 1
    print(f"  {'ok:  ' if cond else 'FAIL:'} {label}")
    if not cond:
        _failures.append(label)


def write(p: Path, text: str = "x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def text_of(result):
    """Flatten a handler's list[TextContent] to a single string."""
    return "\n".join(tc.text for tc in result)


def build_workspace(root: Path):
    # Two real projects so cross-project isolation is observable.
    config = {
        "enforcement": "full",
        "source_roots": ["src"],
        "source_extensions": [".py"],
        "projects": [
            {"slug": "alpha", "name": "Alpha", "path": "apps/alpha"},
            {"slug": "beta", "name": "Beta", "path": "apps/beta"},
        ],
    }
    write(root / ".claude" / "project-config.json", json.dumps(config))


def seed(conn, P):
    """Create projects + per-project routing/health/review rows, return ids."""
    alpha = P.ensure_project(conn, "alpha", "Alpha", "apps/alpha", enforcement="full")
    beta = P.ensure_project(conn, "beta", "Beta", "apps/beta", enforcement="full")
    ws = P.WORKSPACE_ID

    today = date.today().isoformat()

    # --- code_routing: identical keywords across projects so any exclusion is
    # attributable to project scoping, never to keyword scoring. ---
    KW = json.dumps(["authentication"])
    rows = [
        # (project_id, path, line_count)
        (ws, "src/ws_login.py", 10),
        (alpha, "apps/alpha/src/login.py", 200),   # active: big enough to flag at threshold 100
        (beta, "apps/beta/src/login.py", 5000),    # foreign: must never surface
    ]
    for pid, path, lc in rows:
        conn.execute(
            "INSERT INTO code_routing (project_id, path, line_count, keywords, auto_keywords) "
            "VALUES (?, ?, ?, ?, '[]')",
            (pid, path, lc, KW),
        )

    # --- health_metadata: ensure_project already seeded ('doc'/'code') rows.
    # Give ALPHA a low code threshold + today's audit date (skip the audit path,
    # which would otherwise run refresh_code_routing and delete seeded rows).
    # Leave BETA at the default 1500 threshold so a wrong-row read is detectable.
    conn.execute(
        "UPDATE health_metadata SET size_threshold_lines = 100, last_full_audit = ? "
        "WHERE project_id = ? AND kind = 'code'",
        (today, alpha),
    )
    conn.execute(
        "UPDATE health_metadata SET last_full_audit = ? "
        "WHERE project_id = ? AND kind = 'code'",
        (today, beta),
    )

    # --- review_order: ensure_project seeded zeroed rows for both projects.
    # acknowledge_security_review gates on doc_review_done, so set it on both
    # (so the gate is never the reason a write is missing).
    conn.execute("UPDATE review_order SET doc_review_done = 1 WHERE project_id = ?", (alpha,))
    conn.execute("UPDATE review_order SET doc_review_done = 1 WHERE project_id = ?", (beta,))
    conn.commit()
    return alpha, beta, ws


def run(root: Path):
    import projects as P
    import code_manager as CM
    from db import get_db

    conn = get_db()
    try:
        alpha, beta, ws = seed(conn, P)
        # Active project = alpha for the whole suite.
        P.set_active_project(conn, alpha)

        # --- get_relevant_modules: active + workspace only ---
        res = CM.handle_get_relevant_modules(
            {"task_description": "authentication"}  # no source_files -> no inference
        )
        out = text_of(res)
        check("echo prefix names active project", out.startswith("[project: alpha]"))
        check("includes active project's module", "apps/alpha/src/login.py" in out)
        check("includes workspace module", "src/ws_login.py" in out)
        check("EXCLUDES foreign project's module (scoping, not scoring)",
              "apps/beta/src/login.py" not in out)

        # Explicit project override scopes to beta instead.
        res_b = CM.handle_get_relevant_modules(
            {"task_description": "authentication", "project": "beta"}
        )
        out_b = text_of(res_b)
        check("explicit project=beta echoes beta", out_b.startswith("[project: beta]"))
        check("explicit project=beta surfaces beta module", "apps/beta/src/login.py" in out_b)
        check("explicit project=beta excludes alpha module", "apps/alpha/src/login.py" not in out_b)

        # --- acknowledge_code_review writes to ACTIVE (alpha) only ---
        res = CM.handle_acknowledge_code_review(
            {"summary": "looks good", "critical_issues": 0, "advisory_issues": 2}
        )
        check("ack_code_review echoes active project", text_of(res).startswith("[project: alpha]"))
        a_row = conn.execute(
            "SELECT * FROM review_order WHERE project_id = ?", (alpha,)
        ).fetchone()
        b_row = conn.execute(
            "SELECT * FROM review_order WHERE project_id = ?", (beta,)
        ).fetchone()
        check("alpha code_review_done set", a_row["code_review_done"] == 1)
        check("alpha code_review_advisory recorded", a_row["code_review_advisory"] == 2)
        check("beta code_review_done UNTOUCHED", b_row["code_review_done"] == 0)
        check("beta code_review_advisory UNTOUCHED", b_row["code_review_advisory"] == 0)

        # critical_issues > 0 must NOT mark done (and still only touches alpha).
        CM.handle_acknowledge_code_review({"summary": "oops", "critical_issues": 3})
        a_row = conn.execute(
            "SELECT * FROM review_order WHERE project_id = ?", (alpha,)
        ).fetchone()
        check("alpha critical recorded, done cleared", a_row["code_review_critical"] == 3 and a_row["code_review_done"] == 0)

        # --- acknowledge_security_review writes to ACTIVE (alpha) only ---
        res = CM.handle_acknowledge_security_review({"summary": "no findings", "security_issues": 0})
        check("ack_security_review echoes active project", text_of(res).startswith("[project: alpha]"))
        a_row = conn.execute(
            "SELECT * FROM review_order WHERE project_id = ?", (alpha,)
        ).fetchone()
        b_row = conn.execute(
            "SELECT * FROM review_order WHERE project_id = ?", (beta,)
        ).fetchone()
        check("alpha security_review_done set", a_row["security_review_done"] == 1)
        check("beta security_review_done UNTOUCHED", b_row["security_review_done"] == 0)

        # security gate: a project whose doc_review_done=0 is refused (and not written).
        gamma = P.ensure_project(conn, "gamma", "Gamma", "apps/gamma")
        res_g = CM.handle_acknowledge_security_review({"summary": "x", "project": "gamma"})
        out_g = text_of(res_g)
        check("security gate blocks when doc_review missing", "doc_review has not been completed" in out_g)
        g_row = conn.execute(
            "SELECT * FROM review_order WHERE project_id = ?", (gamma,)
        ).fetchone()
        check("gamma security_review_done NOT written on gate failure", g_row["security_review_done"] == 0)

        # --- check_code_health reads the right health row + scopes routing ---
        res = CM.handle_check_code_health({})
        out = text_of(res)
        check("health echoes active project", out.startswith("[project: alpha]"))
        # alpha threshold=100, alpha routing row line_count=200 -> flagged.
        # (Only oversized files are listed by path; the small workspace file is
        # not, so its inclusion is asserted via the totals below, not by path.)
        check("active module flagged against active threshold", "apps/alpha/src/login.py" in out)
        # beta routing row (5000 lines) must never leak in regardless of size.
        check("foreign routing row absent from active health", "apps/beta/src/login.py" not in out)
        # 2 routing rows in scope (alpha + workspace), not 3 -> proves workspace
        # is counted AND beta is excluded. Line total 200 + 10 = 210 confirms the
        # workspace row (10 lines) is in scope, not beta's 5000.
        check("health totals only active+workspace files", "Total: 2 source files" in out)
        check("health line total = active(200) + workspace(10)", "210 lines" in out)

        # Same call scoped to beta: beta's default threshold (1500) means its
        # 5000-line row IS flagged there, and alpha's row is absent -- proving
        # check_code_health reads beta's OWN health row + routing scope.
        res_b = CM.handle_check_code_health({"project": "beta"})
        out_b = text_of(res_b)
        check("beta health echoes beta", out_b.startswith("[project: beta]"))
        check("beta module flagged in beta health", "apps/beta/src/login.py" in out_b)
        check("alpha module absent from beta health", "apps/alpha/src/login.py" not in out_b)
    finally:
        conn.close()


def main():
    prev = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_workspace(root)
        os.chdir(root)
        try:
            run(root)
        finally:
            os.chdir(prev)
    print()
    if _failures:
        print(f"CODE-MANAGER: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"CODE-MANAGER: all {_checks} checks passed")


if __name__ == "__main__":
    main()
