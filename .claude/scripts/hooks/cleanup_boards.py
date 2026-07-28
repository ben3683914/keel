#!/usr/bin/env python3
"""SessionStart hook: cleans up old data to keep context lean.

Archives old done tasks, trims activity log, cleans stale sessions,
resets review order for fresh workflow. All via SQLite.

Only runs in project mode (workspace_scope == "project").
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add shared module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_db, get_project_root
from projects import get_active_project, list_projects, sync_projects_from_config


def load_project_config(cwd):
    config_path = Path(cwd) / ".claude" / "project-config.json"
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_doc_enforcement(cwd):
    config_path = Path(cwd) / ".claude" / "doc-enforcement.json"
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # Resolve UP to the workspace root so a session launched from a
    # sub-directory still reads the real config and DB (not a shadow copy).
    cwd = get_project_root(data.get("cwd"))

    project_config = load_project_config(cwd)
    if not project_config:
        sys.exit(0)

    if project_config.get("workspace_scope") != "project":
        sys.exit(0)

    doc_config = load_doc_enforcement(cwd)
    cleanup_cfg = doc_config.get("cleanup", {}) if doc_config else {}
    max_done = cleanup_cfg.get("max_done_entries", 10)
    max_status = cleanup_cfg.get("max_status_entries", 10)

    conn = get_db(cwd)
    try:
        # Ensure the DB project registry matches config.projects[] at session
        # start (routing also syncs, but only when files change).
        sync_projects_from_config(conn, project_config)

        # Trim done tasks (keep most recent N by completed_date)
        done_count = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'done'"
        ).fetchone()[0]
        if done_count > max_done:
            # Delete oldest done tasks beyond the limit
            conn.execute(
                "DELETE FROM tasks WHERE status = 'done' AND id NOT IN "
                "(SELECT id FROM tasks WHERE status = 'done' ORDER BY completed_date DESC LIMIT ?)",
                (max_done,),
            )

        # Trim activity log (keep most recent N)
        log_count = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
        if log_count > max_status:
            conn.execute(
                "DELETE FROM activity_log WHERE id NOT IN "
                "(SELECT id FROM activity_log ORDER BY id DESC LIMIT ?)",
                (max_status,),
            )

        # Clean stale session state (older than 24 hours)
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        conn.execute(
            "DELETE FROM session_state WHERE created_at < ?", (cutoff,)
        )

        # Reset review order for fresh workflow -- every project's pipeline.
        conn.execute(
            "UPDATE review_order SET "
            "code_review_done=0, code_review_critical=0, code_review_advisory=0, "
            "doc_review_done=0, doc_review_unresolved=0, "
            "security_review_done=0, security_review_issues=0, security_review_deferred=0, "
            "tests_done=0, tests_failures=0"
        )

        conn.commit()

        # Output onboarding status for Claude to see in hook result
        row = conn.execute("SELECT complete, current_phase FROM onboarding WHERE id = 1").fetchone()
        if row and row[0] == 1:
            print("ONBOARDING_STATUS: complete")
        elif row and row[1] > 0:
            print(f"ONBOARDING_STATUS: interrupted (phase {row[1]})")
        else:
            print("ONBOARDING_STATUS: not_started")

        # Emit enforcement level for CLAUDE.md session start logic.
        enforcement = project_config.get("enforcement")
        if not enforcement:
            # Legacy fallback: derive from the old project_mode key.
            enforcement = "minimal" if project_config.get("project_mode") == "scratchpad" else "full"
        print(f"ENFORCEMENT: {enforcement}")

        # Emit the active project + the project roster so the agent can confirm
        # which board it is operating on (the active project is workspace-global).
        active = get_active_project(conn)
        if active:
            print(f"ACTIVE_PROJECT: {active['slug']}")
        real = list_projects(conn, include_workspace=False)
        if real:
            print(f"PROJECTS: {', '.join(p['slug'] for p in real)}")

        # Emit greeting so Claude displays it without needing to read a file
        if row and row[0] == 1:
            greeting = project_config.get("greeting", "")
            if greeting:
                print(f"GREETING: {greeting}")
    finally:
        conn.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
