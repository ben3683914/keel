"""test_manager validation: projects-first test_manager (slug-keyed).

Self-running (no pytest dependency). Builds a real multi-project temp workspace
with a `projects[]` config, chdir's into it so load_project_config()/get_db()
resolve there, and exercises the slug-based resolution in test_manager:

  - detect_project_for_file returns the SLUG of the owning project, None otherwise
  - get_test_command resolves the per-slug test_command from config
  - resolve_run_target maps slug -> projects-row path for cwd + per-slug command
    (asserted WITHOUT running a subprocess)
  - acknowledge_tests writes to the ACTIVE project's review_order row and leaves
    a second project's row untouched

    .claude/venv/bin/python .claude/scripts/tests/test_test_manager.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

MCP = Path(__file__).resolve().parent.parent / "mcp"
SHARED = Path(__file__).resolve().parent.parent / "shared"
sys.path.insert(0, str(MCP))
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
        "test_command": "pytest",
        "projects": [
            {"slug": "web", "name": "Web", "path": "apps/web",
             "source_roots": ["src"], "source_extensions": [".ts"],
             "test_command": "npm test"},
            {"slug": "api", "name": "API", "path": "services/api",
             "source_roots": ["."], "source_extensions": [".py"],
             "test_command": "echo api-tests"},
        ],
    }
    write(root / ".claude" / "project-config.json", json.dumps(config))
    # A real source file under each project (used for detection + coverage scope).
    write(root / "apps" / "web" / "src" / "auth.ts", "function loginUser() {}\n")
    write(root / "services" / "api" / "handler.py", "def handle_request():\n    pass\n")
    write(root / "src" / "core.py", "def core_thing():\n    pass\n")
    return config


def run(root: Path):
    import test_manager as TM
    import projects as P
    from db import get_db

    # Register the two projects in the DB (config is authoritative for identity).
    conn = get_db()
    try:
        P.sync_projects_from_config(conn, TM.load_project_config())
        web_id = P.get_project_by_slug(conn, "web")["id"]
        api_id = P.get_project_by_slug(conn, "api")["id"]
    finally:
        conn.close()

    # --- detect_project_for_file: returns the SLUG, not a path ---
    check("detect web file -> 'web'", TM.detect_project_for_file("apps/web/src/auth.ts") == "web")
    check("detect api file -> 'api'", TM.detect_project_for_file("services/api/handler.py") == "api")
    check("detect backslash path -> 'web'", TM.detect_project_for_file("apps\\web\\src\\auth.ts") == "web")
    check("detect unrelated file -> None", TM.detect_project_for_file("scratch/notes.md") is None)

    # --- get_test_command: per-slug command, with top-level fallback ---
    check("test_command for 'web' slug", TM.get_test_command("web") == "npm test")
    check("test_command for 'api' slug", TM.get_test_command("api") == "echo api-tests")
    check("test_command unknown slug -> top-level", TM.get_test_command("nope") == "pytest")
    check("test_command None -> top-level", TM.get_test_command(None) == "pytest")
    # Accepts an already-resolved config entry too.
    web_entry = TM.config_entry_for_slug("web")
    check("test_command accepts config entry", TM.get_test_command(web_entry) == "npm test")

    # --- resolve_run_target: slug -> projects-row path for cwd + per-slug command ---
    # (asserted statically; NO subprocess is launched)
    web_t = TM.resolve_run_target({"project": "web"})
    check("run cwd from web row path (apps/web)", Path(web_t["cwd"]).resolve() == (root / "apps" / "web").resolve())
    check("run cmd is web test_command", web_t["test_cmd"] == "npm test")
    check("run slug echoed as 'web'", web_t["slug"] == "web")

    api_t = TM.resolve_run_target({"project": "api"})
    check("run cwd from api row path (services/api)", Path(api_t["cwd"]).resolve() == (root / "services" / "api").resolve())
    check("run cmd is api test_command", api_t["test_cmd"] == "echo api-tests")

    # Auto-detect slug from files (single project) -> web's command + cwd.
    auto_t = TM.resolve_run_target({"files": ["apps/web/src/auth.ts"]})
    check("auto-detect slug from files -> 'web'", auto_t["slug"] == "web")
    check("auto-detect resolves web cwd", Path(auto_t["cwd"]).resolve() == (root / "apps" / "web").resolve())

    # No project + no files -> workspace-scoped: root cwd, top-level command, no echo.
    ws_t = TM.resolve_run_target({})
    check("workspace run cwd is root", Path(ws_t["cwd"]).resolve() == root.resolve())
    check("workspace run uses top-level command", ws_t["test_cmd"] == "pytest")
    check("workspace run slug is None (no echo)", ws_t["slug"] is None)

    # Files appended to the command when not running `all`.
    files_t = TM.resolve_run_target({"project": "api", "files": ["services/api/test_handler.py"]})
    check("files appended to cmd_parts", files_t["cmd_parts"][-1] == "services/api/test_handler.py")

    # --- acknowledge_tests: writes the ACTIVE project's row; sibling untouched ---
    # Gate requires security_review_done on the target row; seed it for web only.
    conn = get_db()
    try:
        conn.execute("UPDATE review_order SET security_review_done = 1 WHERE project_id = ?", (web_id,))
        conn.commit()
        P.set_active_project(conn, web_id)
    finally:
        conn.close()

    # Active = web; acknowledge with 0 failures -> web row tests_done=1, api untouched.
    res = TM.handle_acknowledge_tests({"summary": "all green"})
    body = res[0].text
    check("acknowledge echoes active slug 'web'", body.startswith("[project: web]\n"))
    check("acknowledge success text", "Tests acknowledged" in body)

    conn = get_db()
    try:
        web_row = conn.execute("SELECT * FROM review_order WHERE project_id = ?", (web_id,)).fetchone()
        api_row = conn.execute("SELECT * FROM review_order WHERE project_id = ?", (api_id,)).fetchone()
        check("active (web) row tests_done = 1", web_row["tests_done"] == 1)
        check("active (web) row failures = 0", web_row["tests_failures"] == 0)
        check("sibling (api) row tests_done still 0", api_row["tests_done"] == 0)
    finally:
        conn.close()

    # Explicit project= overrides the active pointer (target a different slug).
    conn = get_db()
    try:
        conn.execute("UPDATE review_order SET security_review_done = 1 WHERE project_id = ?", (api_id,))
        conn.commit()
    finally:
        conn.close()
    res2 = TM.handle_acknowledge_tests({"summary": "api ok", "project": "api", "failures": 2})
    body2 = res2[0].text
    check("explicit project= echoes 'api'", body2.startswith("[project: api]\n"))
    conn = get_db()
    try:
        api_row = conn.execute("SELECT * FROM review_order WHERE project_id = ?", (api_id,)).fetchone()
        check("explicit api row recorded failures=2 (tests_done=0)", api_row["tests_done"] == 0 and api_row["tests_failures"] == 2)
    finally:
        conn.close()

    # --- acknowledge_tests gate fires when security_review not done ---
    # 'api' was active? No -- active is web (explicit didn't move pointer). Seed a
    # fresh project with no security review and target it explicitly.
    conn = get_db()
    try:
        gate_id = P.ensure_project(conn, "gate", "Gate", "pkgs/gate")
    finally:
        conn.close()
    blocked = TM.handle_acknowledge_tests({"summary": "x", "project": "gate"})
    btext = blocked[0].text
    check("gate (no security review) is blocked", "Cannot acknowledge tests" in btext)
    check("blocked response echoes 'gate'", btext.startswith("[project: gate]\n"))
    conn = get_db()
    try:
        gate_row = conn.execute("SELECT * FROM review_order WHERE project_id = ?", (gate_id,)).fetchone()
        check("blocked write did not set tests_done", gate_row["tests_done"] == 0)
    finally:
        conn.close()

    # --- find_untested_files: scopes to project source config + echoes ---
    # Inputs are REPO-RELATIVE (same shape detect_project_for_file/phase-0 use):
    # a web source file is 'apps/web/src/auth.ts', NOT 'src/auth.ts'.
    res3 = TM.handle_find_untested_files({"source_files": ["apps/web/src/auth.ts"], "project": "web"})
    text3 = res3[0].text
    check("find_untested echoes 'web'", text3.startswith("[project: web]\n"))
    check("repo-relative web .ts file IS in web scope", "outside project" not in text3)
    # It must be genuinely EVALUATED (no test file exists -> Untested), not
    # silently dropped via the source_dir-coupling skip. Expected-test path is
    # re-prefixed back under the project (repo-relative).
    check("web .ts file reported untested (not skipped away)", "## Untested" in text3 and "(not under" not in text3)
    check("expected-test path is repo-relative under apps/web", "apps/web/tests/" in text3)
    # A repo-relative .py under web's path is outside web's (.ts-only) extensions.
    res4 = TM.handle_find_untested_files({"source_files": ["apps/web/src/thing.py"], "project": "web"})
    check("py file under web path out of scope (ext mismatch)", "outside project 'web'" in res4[0].text)
    # A file under a DIFFERENT project's path is outside the web subtree entirely.
    res5 = TM.handle_find_untested_files({"source_files": ["services/api/handler.py"], "project": "web"})
    check("api-path file out of web subtree", "outside project 'web'" in res5[0].text)
    # Workspace-scoped find_untested_files does NOT emit an echo line.
    # (find_untested resolves explicit>active>workspace; reset active to workspace
    #  so this exercises the true workspace fallback, not the lingering web pointer.)
    conn = get_db()
    try:
        P.set_active_project(conn, P.WORKSPACE_ID)
    finally:
        conn.close()
    res6 = TM.handle_find_untested_files({"source_files": ["src/core.py"]})
    check("workspace find_untested has no echo line", not res6[0].text.startswith("[project:"))


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
        print(f"TEST-MANAGER: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"TEST-MANAGER: all {_checks} checks passed")


if __name__ == "__main__":
    main()
