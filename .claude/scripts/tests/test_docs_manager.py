"""docs_manager validation: projects-first docs_manager (routing scope + two-tier constitution).

Self-running (no pytest dependency). Builds a real temp workspace, os.chdir into
it (the MCP handlers resolve get_db()/get_project_root() from Path.cwd(), so the
cwd MUST be the temp root), seeds two real projects plus the always-present
workspace, and drives the actual handler functions.

    .claude/venv/bin/python .claude/scripts/tests/test_docs_manager.py
"""

import json
import os
import sys
import tempfile
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
    """Unwrap a handler's [TextContent] return into a plain string."""
    return result[0].text


def build_workspace(root: Path):
    config = {
        "enforcement": "full",
        "source_roots": ["src"],
        "source_extensions": [".py"],
        "projects": [
            {"slug": "web", "name": "Web", "path": "apps/web"},
            {"slug": "api", "name": "API", "path": "services/api"},
        ],
    }
    write(root / ".claude" / "project-config.json", json.dumps(config))
    # docs on disk so size/exists checks have something to read
    write(root / "docs" / "ws.md", "# Workspace doc\n## Shared overview\n")
    write(root / "apps" / "web" / "docs" / "web.md", "# Web doc\n## Login keyword unique\n")
    write(root / "services" / "api" / "docs" / "api.md", "# API doc\n## Endpoint keyword unique\n")


def run(root: Path):
    import projects as P
    import docs_manager as D
    from db import get_db

    conn = get_db()
    try:
        web = P.ensure_project(conn, "web", "Web", "apps/web", enforcement="full")
        api = P.ensure_project(conn, "api", "API", "services/api", enforcement="full")

        # Seed doc_routing for workspace + both projects with a discriminating keyword.
        conn.execute(
            "INSERT INTO doc_routing (project_id, path, keywords) VALUES (1, 'docs/ws.md', ?)",
            (json.dumps(["sharedkw"]),),
        )
        conn.execute(
            "INSERT INTO doc_routing (project_id, path, keywords) VALUES (?, 'apps/web/docs/web.md', ?)",
            (web, json.dumps(["webonlykw"])),
        )
        conn.execute(
            "INSERT INTO doc_routing (project_id, path, keywords) VALUES (?, 'services/api/docs/api.md', ?)",
            (api, json.dumps(["apionlykw"])),
        )
        conn.commit()
    finally:
        conn.close()

    # ---- get_relevant_docs: only active + workspace tier ----
    conn = get_db()
    try:
        P.set_active_project(conn, web)
    finally:
        conn.close()

    # Query that mentions BOTH the web keyword and the api keyword. With web active,
    # only web's doc (+ workspace) is in the row set; api's doc must be excluded.
    res = text_of(D.handle_get_relevant_docs({"task_description": "webonlykw apionlykw sharedkw"}))
    check("get_relevant_docs echoes active project", res.startswith("[project: web]"))
    check("get_relevant_docs includes web (active) doc", "apps/web/docs/web.md" in res)
    check("get_relevant_docs includes workspace doc", "docs/ws.md" in res)
    check("get_relevant_docs EXCLUDES foreign (api) doc", "services/api/docs/api.md" not in res)

    # Explicit project override scopes to api instead.
    res_api = text_of(D.handle_get_relevant_docs(
        {"task_description": "webonlykw apionlykw", "project": "api"}
    ))
    check("get_relevant_docs explicit project=api echoes api", res_api.startswith("[project: api]"))
    check("explicit api scope includes api doc", "services/api/docs/api.md" in res_api)
    check("explicit api scope excludes web doc", "apps/web/docs/web.md" not in res_api)

    # ---- per-project constitution numbering ----
    conn = get_db()
    try:
        P.set_active_project(conn, web)
    finally:
        conn.close()

    r = text_of(D.handle_propose_article({"title": "Web Rule One", "rule_text": "web mandate"}))
    check("propose on web -> web/001", "web/001" in r)
    r = text_of(D.handle_propose_article({"title": "Web Rule Two", "rule_text": "web mandate 2"}))
    check("second web article -> web/002", "web/002" in r)

    # Same number 1 must be independently available on api.
    r = text_of(D.handle_propose_article({"title": "Api Rule One", "rule_text": "api mandate", "project": "api"}))
    check("propose on api -> api/001 (number reused per project)", "api/001" in r)

    # Workspace tier article.
    r = text_of(D.handle_propose_article({"title": "Workspace Rule", "rule_text": "ws mandate", "project": "workspace"}))
    check("propose on workspace -> workspace/001", "workspace/001" in r)

    conn = get_db()
    try:
        cnt_web1 = conn.execute(
            "SELECT COUNT(*) c FROM constitution WHERE project_id = ? AND number = 1", (web,)
        ).fetchone()["c"]
        cnt_api1 = conn.execute(
            "SELECT COUNT(*) c FROM constitution WHERE project_id = ? AND number = 1", (api,)
        ).fetchone()["c"]
        check("web art number=1 exists", cnt_web1 == 1)
        check("api art number=1 coexists with web art 1", cnt_api1 == 1)
        # source_id namespace: project tier embeds slug; workspace tier does not.
        web1_src = conn.execute(
            "SELECT source_id FROM constitution WHERE project_id = ? AND number = 1", (web,)
        ).fetchone()["source_id"]
        ws1_src = conn.execute(
            "SELECT source_id FROM constitution WHERE project_id = 1 AND number = 1"
        ).fetchone()["source_id"]
        check("project-tier source_id embeds slug (project:web:...)", web1_src.startswith("project:web:"))
        check("workspace-tier source_id has no slug embed", ":web:" not in (ws1_src or ""))
    finally:
        conn.close()

    # ---- ratify/amend/revoke resolve by (project, number) ----
    # api/001 and web/001 both exist; ratifying api/001 must not touch web/001.
    text_of(D.handle_ratify_article({"number": 1, "project": "api"}))
    conn = get_db()
    try:
        api1 = conn.execute(
            "SELECT status FROM constitution WHERE project_id = ? AND number = 1", (api,)
        ).fetchone()["status"]
        web1 = conn.execute(
            "SELECT status FROM constitution WHERE project_id = ? AND number = 1", (web,)
        ).fetchone()["status"]
        check("ratify api/001 -> api/001 ratified", api1 == "ratified")
        check("ratify api/001 left web/001 untouched (still proposed)", web1 == "proposed")
    finally:
        conn.close()

    text_of(D.handle_amend_article({"number": 1, "rule_text": "amended api rule", "project": "api"}))
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT status, rule_text FROM constitution WHERE project_id = ? AND number = 1", (api,)
        ).fetchone()
        check("amend api/001 sets status amended", row["status"] == "amended")
        check("amend api/001 updated rule_text", row["rule_text"] == "amended api rule")
    finally:
        conn.close()

    text_of(D.handle_revoke_article({"number": 2, "reason": "no longer needed", "project": "web"}))
    conn = get_db()
    try:
        web2 = conn.execute(
            "SELECT status FROM constitution WHERE project_id = ? AND number = 2", (web,)
        ).fetchone()["status"]
        check("revoke web/002 -> revoked", web2 == "revoked")
    finally:
        conn.close()

    # Wrong-project lookup must miss (number alone is not unique).
    miss = text_of(D.handle_ratify_article({"number": 2, "project": "api"}))
    check("ratify api/002 (does not exist) -> not found", "not found" in miss.lower())

    # ---- two-tier compact constitution: both tiers, slug-prefixed numbers ----
    conn = get_db()
    try:
        # Ratify a web article and the workspace article so they render in compact
        # (compact only shows ratified/amended).
        D.handle_ratify_article({"number": 1, "project": "web"})
        D.handle_ratify_article({"number": 1, "project": "workspace"})
        compact = D.get_compact_constitution(web)
    finally:
        conn.close()
    check("compact shows workspace tier (workspace/001)", "workspace/001" in compact)
    check("compact shows project tier (web/001)", "web/001" in compact)
    check("compact does NOT show foreign api tier", "api/001" not in compact)

    # ---- regen writes to the right per-project dir ----
    ws_dir = root / "docs" / "constitution"
    web_dir = root / "apps" / "web" / "docs" / "constitution"
    api_dir = root / "services" / "api" / "docs" / "constitution"
    check("workspace constitution dir exists at docs/constitution", ws_dir.exists())
    check("web constitution dir under apps/web/docs/constitution", web_dir.exists())
    check("api constitution dir under services/api/docs/constitution", api_dir.exists())
    # web/001 file lands in the web dir, NOT the workspace dir.
    web_articles = {f.name for f in web_dir.glob("article-*.md")}
    ws_articles = {f.name for f in ws_dir.glob("article-*.md")}
    check("web article-001 file in web dir", any(a.startswith("article-001-") for a in web_articles))
    check("web article file NOT duplicated into workspace dir",
          not any("web-rule-one" in a for a in ws_articles))
    check("workspace index.md generated", (ws_dir / "index.md").exists())

    # ---- list_articles default scope vs project=all ----
    conn = get_db()
    try:
        P.set_active_project(conn, web)
    finally:
        conn.close()
    lst = text_of(D.handle_list_articles({}))
    check("list_articles default echoes active (web)", lst.startswith("[project: web]"))
    check("list_articles default shows web tier", "web/001" in lst)
    check("list_articles default shows workspace tier", "workspace/001" in lst)
    check("list_articles default hides foreign api tier", "api/001" not in lst)
    lst_all = text_of(D.handle_list_articles({"project": "all"}))
    check("list_articles project=all shows api tier too", "api/001" in lst_all)
    check("list_articles project=all shows web tier", "web/001" in lst_all)

    # ---- check_doc_health (first call: audit path) ----
    # web's health row starts at 1970-01-01, so the full audit fires. That branch
    # calls the (intentionally global) refresh_doc_routing maintenance pass, whose
    # change-list legitimately surfaces every project. So we assert the thing that
    # actually matters post-migration: the audit UPDATE touched ONLY web's row.
    from datetime import date as _date
    health = text_of(D.handle_check_doc_health({"project": "web"}))
    check("check_doc_health echoes project", health.startswith("[project: web]"))
    check("check_doc_health sees web doc", "apps/web/docs/web.md" in health)
    check("check_doc_health sees workspace doc", "docs/ws.md" in health)
    conn = get_db()
    try:
        today = _date.today().isoformat()
        web_audit = conn.execute(
            "SELECT last_full_audit FROM health_metadata WHERE project_id = ? AND kind = 'doc'", (web,)
        ).fetchone()["last_full_audit"]
        api_audit = conn.execute(
            "SELECT last_full_audit FROM health_metadata WHERE project_id = ? AND kind = 'doc'", (api,)
        ).fetchone()["last_full_audit"]
        ws_audit = conn.execute(
            "SELECT last_full_audit FROM health_metadata WHERE project_id = 1 AND kind = 'doc'"
        ).fetchone()["last_full_audit"]
        check("audit UPDATE set web/doc last_full_audit to today", web_audit == today)
        check("audit UPDATE did NOT touch api/doc row", api_audit == "1970-01-01")
        check("audit UPDATE did NOT touch workspace/doc row", ws_audit == "1970-01-01")
    finally:
        conn.close()

    # ---- check_doc_health (second call: steady-state, audit skipped) ----
    # days_since_audit is now 0 (< interval), so the global refresh does not run
    # and the output reflects ONLY the active+workspace scoped size read. (Doc
    # paths are listed only by the audit branch; in steady state the size check
    # summarizes, so we assert on the scoped total — 2 docs = web + workspace —
    # and on the explicit exclusion of the foreign api doc.)
    health2 = text_of(D.handle_check_doc_health({"project": "web"}))
    check("steady-state check_doc_health echoes project", health2.startswith("[project: web]"))
    # The reported total must equal the on-disk doc_routing rows scoped to
    # web+workspace (the audit refresh may have swept generated constitution .md
    # files into routing, so we derive the expected count rather than hardcode it).
    conn = get_db()
    try:
        expected_total = 0
        for r in conn.execute(
            "SELECT path FROM doc_routing WHERE project_id IN (?, 1)", (web,)
        ).fetchall():
            if (root / r["path"]).exists():
                expected_total += 1
        api_total = conn.execute(
            "SELECT COUNT(*) c FROM doc_routing WHERE project_id = ?", (api,)
        ).fetchone()["c"]
    finally:
        conn.close()
    check(f"steady-state Total matches scoped web+workspace count ({expected_total})",
          f"Total: {expected_total} docs" in health2)
    check("api tier actually has docs (so exclusion is meaningful)", api_total >= 1)
    check("steady-state EXCLUDES foreign api doc", "services/api/docs/api.md" not in health2)

    # ---- set_startup_loading: workspace doc reachable while a project is active ----
    # The workspace doc has no project prefix; with `web` active, the toggle must
    # still find and flip the workspace-tier row (and must not flip the pointer).
    conn = get_db()
    try:
        P.set_active_project(conn, web)
        before_active = P.get_active_project_id(conn)
    finally:
        conn.close()
    sres = text_of(D.handle_set_startup_loading({"path": "docs/ws.md", "enabled": True}))
    check("set_startup_loading echoes active (web)", sres.startswith("[project: web]"))
    check("set_startup_loading found the workspace-tier doc", "added to startup" in sres)
    conn = get_db()
    try:
        flag = conn.execute(
            "SELECT load_at_start FROM doc_routing WHERE project_id = 1 AND path = 'docs/ws.md'"
        ).fetchone()["load_at_start"]
        check("workspace doc load_at_start flipped to 1", flag == 1)
        check("set_startup_loading did NOT move the active pointer",
              P.get_active_project_id(conn) == before_active)
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
        print(f"DOCS-MANAGER: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"DOCS-MANAGER: all {_checks} checks passed")


if __name__ == "__main__":
    main()
