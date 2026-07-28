"""Hooks validation: enforcement hooks under the projects-first model.

Drives each hook as a subprocess (they are stdin/exit-code programs) against a
temp multi-project workspace. Verifies: SessionStart emits ENFORCEMENT/ACTIVE_PROJECT
and resets every project's review_order; PostToolUse moves the active pointer to the
edited file's project; Stop and commit gates block per-project with a [project: slug]
tag and pass once that project's reviews are acknowledged.

    .claude/venv/bin/python .claude/scripts/tests/test_hooks.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SHARED = REPO / ".claude" / "scripts" / "shared"
HOOKS = REPO / ".claude" / "scripts" / "hooks"
PYTHON = REPO / ".claude" / "venv" / "bin" / "python"
sys.path.insert(0, str(SHARED))

_checks = 0
_failures = []


def check(label, cond):
    global _checks
    _checks += 1
    print(f"  {'ok:  ' if cond else 'FAIL:'} {label}")
    if not cond:
        _failures.append(label)


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def run_hook(name: str, payload: dict, cwd: Path):
    r = subprocess.run(
        [str(PYTHON), str(HOOKS / name)],
        input=json.dumps(payload),
        capture_output=True, text=True, cwd=str(cwd),
    )
    return r.returncode, r.stdout, r.stderr


def build(root: Path):
    config = {
        "enforcement": "full",
        "workspace_scope": "project",
        "source_roots": ["src"],
        "source_extensions": [".py"],
        "doc_patterns": ["docs/**/*.md"],
        "projects": [
            {"slug": "web", "name": "Web", "path": "apps/web",
             "source_roots": ["src"], "source_extensions": [".ts"]},
            {"slug": "api", "name": "API", "path": "services/api",
             "source_roots": ["."], "source_extensions": [".py"]},
        ],
    }
    write(root / ".claude" / "project-config.json", json.dumps(config))
    write(root / ".claude" / "doc-enforcement.json", json.dumps({
        "rules": [
            {"when": "source_modified", "require": "task_started"},
            {"when": "source_modified", "require": "code_reviewed"},
            {"when": "source_modified", "require": "doc_reviewed"},
            {"when": "source_modified", "require": "security_reviewed"},
            {"when": "source_modified", "require": "task_validated"},
            {"when": "source_modified", "require": "tests_acknowledged"},
        ],
        "cleanup": {"max_status_entries": 10, "max_done_entries": 10},
    }))
    write(root / "apps" / "web" / "src" / "auth.ts", "function login() {}\n")


def main():
    from db import get_db, json_dumps
    import projects as P

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build(root)
        web_file = str(root / "apps" / "web" / "src" / "auth.ts")

        # 1. SessionStart (cleanup_boards): syncs projects, emits status lines.
        rc, out, err = run_hook("cleanup_boards.py", {"cwd": str(root)}, root)
        check("SessionStart exits 0", rc == 0)
        check("emits ENFORCEMENT: full", "ENFORCEMENT: full" in out)
        check("emits ACTIVE_PROJECT", "ACTIVE_PROJECT:" in out)
        check("emits PROJECTS roster web+api", "web" in out and "api" in out and "PROJECTS:" in out)
        check("emits ONBOARDING_STATUS", "ONBOARDING_STATUS:" in out)

        conn = get_db(root)
        web_id = P.get_project_by_slug(conn, "web")["id"]
        api_id = P.get_project_by_slug(conn, "api")["id"]
        check("projects synced into DB", web_id and api_id and web_id != api_id)
        # seed a review_order dirty value to prove the reset clears it
        conn.execute("UPDATE review_order SET code_review_done=1 WHERE project_id=?", (web_id,))
        conn.commit()
        conn.close()
        run_hook("cleanup_boards.py", {"cwd": str(root)}, root)
        conn = get_db(root)
        check(
            "SessionStart reset every project's review_order",
            conn.execute("SELECT code_review_done FROM review_order WHERE project_id=?", (web_id,)).fetchone()[0] == 0,
        )
        conn.close()

        # 2. PostToolUse (track_modifications): editing a web file moves the pointer.
        conn = get_db(root)
        P.set_active_project(conn, P.WORKSPACE_ID)
        conn.close()
        rc, out, err = run_hook("track_modifications.py", {
            "session_id": "s1", "cwd": str(root), "tool_name": "Edit",
            "tool_input": {"file_path": web_file}, "tool_response": {},
        }, root)
        check("PostToolUse exits 0", rc == 0)
        conn = get_db(root)
        check("active pointer moved to web", P.get_active_project_id(conn) == web_id)
        conn.close()

        # 3. Stop gate (session_gate): web source modified, lifecycle done, NO reviews -> block.
        conn = get_db(root)
        conn.execute(
            "INSERT OR REPLACE INTO session_state (session_id, modified_files, mcp_tools) VALUES (?,?,?)",
            ("s2", json_dumps([web_file]),
             json_dumps(["task-manager:start_task", "task-manager:validate_task"])),
        )
        conn.commit()
        conn.close()
        rc, out, err = run_hook("session_gate.py", {"session_id": "s2", "cwd": str(root)}, root)
        check("Stop gate blocks (exit 2)", rc == 2)
        check("Stop gate tags [project: web]", "[project: web]" in err)
        check("Stop gate cites code review", "code review" in err.lower())

        # acknowledge web's full pipeline -> Stop gate passes
        conn = get_db(root)
        conn.execute(
            "UPDATE review_order SET code_review_done=1, doc_review_done=1, "
            "security_review_done=1, tests_done=1 WHERE project_id=?", (web_id,))
        conn.commit()
        conn.close()
        rc, out, err = run_hook("session_gate.py", {"session_id": "s2", "cwd": str(root)}, root)
        check("Stop gate passes after web reviews (exit 0)", rc == 0)
        check("board snapshot written", (root / "project" / "board-snapshot.md").exists())

        # 3b. Stop gate does NOT block on missing validation (regression: this used
        #     to exit 2 forever while the agent waited for the user to re-test).
        #     Reviews are done (from above); task started but NOT validated.
        #     The doc-enforcement fixture still lists task_validated -- proving the
        #     hook ignores that rule by code, independent of config.
        conn = get_db(root)
        conn.execute(
            "INSERT OR REPLACE INTO session_state (session_id, modified_files, mcp_tools) VALUES (?,?,?)",
            ("s2b", json_dumps([web_file]), json_dumps(["task-manager:start_task"])),
        )
        conn.commit()
        conn.close()
        rc, out, err = run_hook("session_gate.py", {"session_id": "s2b", "cwd": str(root)}, root)
        check("Stop gate does NOT block on missing validation (exit 0)", rc == 0)
        check("Stop gate omits the validation message", "validation required" not in err.lower())

        # 3c. stop_hook_active short-circuits even an otherwise-blocking state
        #     (reviews NOT done) -- breaks the whole infinite-loop class.
        conn = get_db(root)
        conn.execute("UPDATE review_order SET code_review_done=0, doc_review_done=0, "
                     "security_review_done=0, tests_done=0 WHERE project_id=?", (web_id,))
        conn.execute(
            "INSERT OR REPLACE INTO session_state (session_id, modified_files, mcp_tools) VALUES (?,?,?)",
            ("s2c", json_dumps([web_file]), json_dumps(["task-manager:start_task"])),
        )
        conn.commit()
        conn.close()
        rc, out, err = run_hook(
            "session_gate.py",
            {"session_id": "s2c", "cwd": str(root), "stop_hook_active": True}, root)
        check("Stop gate yields when stop_hook_active despite missing reviews (exit 0)", rc == 0)

        # 4. commit_gate: routing freshness is NOT gated (track_modifications auto-
        #    refreshes); instead it blocks per-project on missing reviews.
        conn = get_db(root)
        conn.execute("UPDATE review_order SET code_review_done=0, doc_review_done=0, "
                     "security_review_done=0, tests_done=0 WHERE project_id=?", (web_id,))
        conn.execute(
            "INSERT OR REPLACE INTO session_state (session_id, modified_files, mcp_tools) VALUES (?,?,?)",
            ("s3", json_dumps([web_file]), json_dumps([])),
        )
        conn.commit()
        conn.close()
        rc, out, err = run_hook("commit_gate.py", {
            "session_id": "s3", "cwd": str(root), "tool_name": "Bash",
            "tool_input": {"command": "git commit -m x"},
        }, root)
        check("commit_gate blocks per-project on missing code review (exit 2)", rc == 2)
        check("commit_gate tags [project: web]", "[project: web]" in err)
        check("commit_gate does NOT gate routing freshness", "routing" not in err.lower())

        # 5. Stop gate skips a minimal-enforcement project.
        conn = get_db(root)
        conn.execute("UPDATE projects SET enforcement='minimal' WHERE id=?", (web_id,))
        conn.execute("UPDATE review_order SET code_review_done=0, doc_review_done=0, "
                     "security_review_done=0, tests_done=0 WHERE project_id=?", (web_id,))
        conn.execute(
            "INSERT OR REPLACE INTO session_state (session_id, modified_files, mcp_tools) VALUES (?,?,?)",
            ("s4", json_dumps([web_file]),
             json_dumps(["task-manager:start_task", "task-manager:validate_task"])),
        )
        conn.commit()
        conn.close()
        rc, out, err = run_hook("session_gate.py", {"session_id": "s4", "cwd": str(root)}, root)
        check("Stop gate skips minimal-enforcement project (exit 0)", rc == 0)

        # 6. PostToolUse fired from a SUB-DIRECTORY cwd (a drifted shell after
        #    `cd apps`) must NOT spawn a stray .claude/claude.db in the subdir;
        #    the write lands in the real workspace DB and project inference still
        #    works because paths are made relative to the resolved root.
        conn = get_db(root)
        P.set_active_project(conn, P.WORKSPACE_ID)
        conn.execute("DELETE FROM session_state WHERE session_id='s5'")
        conn.commit()
        conn.close()
        subdir = root / "apps"  # a real sub-directory of the workspace
        rc, out, err = run_hook("track_modifications.py", {
            "session_id": "s5", "cwd": str(subdir), "tool_name": "Edit",
            "tool_input": {"file_path": web_file}, "tool_response": {},
        }, subdir)
        check("PostToolUse from subdir exits 0", rc == 0)
        check("no stray .claude/ created under subdir cwd",
              not (subdir / ".claude").exists())
        conn = get_db(root)
        check("subdir-cwd edit moved pointer in workspace DB",
              P.get_active_project_id(conn) == web_id)
        check("subdir-cwd edit tracked session in workspace DB",
              conn.execute("SELECT 1 FROM session_state WHERE session_id='s5'").fetchone() is not None)
        conn.close()

        # 7. Gate integrity from a SUB-DIRECTORY cwd: the Stop gate must read the
        #    real workspace review_order (not a shadow DB) and still block when
        #    web's reviews are incomplete. This pins the highest-severity harm --
        #    a drifted cwd making an enforcement gate read the wrong state.
        conn = get_db(root)
        conn.execute("UPDATE review_order SET code_review_done=0, doc_review_done=0, "
                     "security_review_done=0, tests_done=0 WHERE project_id=?", (web_id,))
        conn.execute("UPDATE projects SET enforcement='full' WHERE id=?", (web_id,))
        conn.execute(
            "INSERT OR REPLACE INTO session_state (session_id, modified_files, mcp_tools) VALUES (?,?,?)",
            ("s6", json_dumps([web_file]),
             json_dumps(["task-manager:start_task", "task-manager:validate_task"])),
        )
        conn.commit()
        conn.close()
        rc, out, err = run_hook("session_gate.py",
                                {"session_id": "s6", "cwd": str(root / "apps")}, root)
        check("Stop gate from subdir cwd reads workspace DB and blocks (exit 2)", rc == 2)
        check("Stop gate from subdir cwd tags [project: web]", "[project: web]" in err)

    print()
    if _failures:
        print(f"HOOKS: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"HOOKS: all {_checks} checks passed")


if __name__ == "__main__":
    main()
