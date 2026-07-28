"""Routing validation: per-project routing in shared/routing.py.

Builds a real multi-project temp workspace (workspace docs/src + two sub-projects)
and confirms refresh_doc_routing / refresh_code_routing tag each path with the
right project_id and that the workspace scan does not double-claim sub-project files.

    .claude/venv/bin/python .claude/scripts/tests/test_routing.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

SHARED = Path(__file__).resolve().parent.parent / "shared"
sys.path.insert(0, str(SHARED))

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


def build_workspace(root: Path):
    config = {
        "enforcement": "full",
        "source_roots": ["src"],
        "source_extensions": [".py"],
        "projects": [
            {"slug": "web", "name": "Web", "path": "apps/web",
             "source_roots": ["src"], "source_extensions": [".ts"]},
            {"slug": "api", "name": "API", "path": "services/api",
             "source_roots": ["."], "source_extensions": [".py"]},
        ],
    }
    write(root / ".claude" / "project-config.json", json.dumps(config))
    # workspace docs + src
    write(root / "docs" / "index.md", "# Root\n## Architecture overview\n")
    write(root / "src" / "core.py", "def core_thing():\n    pass\n")
    # web project docs + src
    write(root / "apps" / "web" / "docs" / "web.md", "# Web\n## Login flow\n")
    write(root / "apps" / "web" / "src" / "auth.ts", "function loginUser() {}\n")
    # api project docs + src
    write(root / "services" / "api" / "docs" / "api.md", "# API\n## Endpoint contract\n")
    write(root / "services" / "api" / "handler.py", "def handle_request():\n    pass\n")


def run(root: Path):
    import routing
    import projects as P
    from db import get_db

    routing.refresh_doc_routing()
    routing.refresh_code_routing()

    conn = get_db()
    try:
        web = P.get_project_by_slug(conn, "web")["id"]
        api = P.get_project_by_slug(conn, "api")["id"]

        docs = {(r["path"], r["project_id"]) for r in conn.execute("SELECT path, project_id FROM doc_routing")}
        code = {(r["path"], r["project_id"]) for r in conn.execute("SELECT path, project_id FROM code_routing")}

        check("workspace doc tagged to workspace(1)", ("docs/index.md", 1) in docs)
        check("web doc tagged to web", ("apps/web/docs/web.md", web) in docs)
        check("api doc tagged to api", ("services/api/docs/api.md", api) in docs)
        check("workspace did not claim web doc", ("apps/web/docs/web.md", 1) not in docs)

        check("workspace src tagged to workspace(1)", ("src/core.py", 1) in code)
        check("web src tagged to web", ("apps/web/src/auth.ts", web) in code)
        check("api src tagged to api", ("services/api/handler.py", api) in code)
        # workspace source_roots=['src'] so it should NOT pick up apps/web or services/api
        ws_code = {p for (p, pid) in code if pid == 1}
        check("workspace code limited to its own src", ws_code == {"src/core.py"})
        # web uses .ts only -> should not pick up any .py
        web_code = {p for (p, pid) in code if pid == web}
        check("web code only .ts under apps/web", web_code == {"apps/web/src/auth.ts"})

        # idempotency: a second refresh yields no changes
        check("doc refresh idempotent", routing.refresh_doc_routing() == [])
        check("code refresh idempotent", routing.refresh_code_routing() == [])
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
        print(f"ROUTING: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"ROUTING: all {_checks} checks passed")


if __name__ == "__main__":
    main()
