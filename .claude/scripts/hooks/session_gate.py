#!/usr/bin/env python3
"""Stop hook: validates enforcement rules and generates board snapshot.

Reads from SQLite to check that all required steps were completed
when source files were modified. After all checks pass, generates
project/board-snapshot.md with current board state and Mermaid charts.

Only runs in project mode (workspace_scope == "project").
Exit code 2 blocks session exit with violation messages.
"""

import json
import re
import sys
from datetime import date, datetime
from fnmatch import fnmatch
from pathlib import Path

# Add shared module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_db, get_project_root, json_loads
from routing import is_source_file
from projects import (
    list_projects,
    get_project_by_id,
    project_for_path,
    WORKSPACE_ID,
)


def workspace_is_minimal(config) -> bool:
    """True when enforcement is off for the workspace (scratchpad). Honors the
    new `enforcement` key and the legacy `project_mode == 'scratchpad'`."""
    enforcement = config.get("enforcement")
    if enforcement:
        return enforcement == "minimal"
    return config.get("project_mode") == "scratchpad"


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


def matches_any(file_path, patterns):
    normalized = file_path.replace("\\", "/")
    for pattern in patterns:
        pattern = pattern.replace("\\", "/")
        if "**/" in pattern:
            prefix, suffix = pattern.split("**/", 1)
            if prefix and not normalized.startswith(prefix):
                continue
            remaining = normalized[len(prefix):]
            parts = remaining.split("/")
            for i in range(len(parts)):
                sub = "/".join(parts[i:])
                if fnmatch(sub, suffix):
                    return True
        elif fnmatch(normalized, pattern):
            return True
    return False


def make_relative(file_path, cwd):
    """Path relative to the workspace root, tolerant of symlinked roots.

    `file_path` arrives from the hook payload spelled however the tool reported
    it, while `cwd` is the ALREADY-RESOLVED workspace root (get_project_root
    resolves). When the workspace sits under a symlink -- macOS /tmp and /var,
    a symlinked home or code directory -- the two spellings differ, relative_to
    raises, and returning the absolute path makes every downstream prefix match
    silently fail. Retry with both sides resolved before falling back."""
    try:
        rel = Path(file_path).relative_to(cwd)
        return str(rel).replace("\\", "/")
    except ValueError:
        pass
    try:
        rel = Path(file_path).resolve().relative_to(Path(cwd).resolve())
        return str(rel).replace("\\", "/")
    except (ValueError, OSError):
        return str(file_path).replace("\\", "/")


def _project_board_section(conn, lines, proj):
    """Append one project's board (phase, columns, done counts) to `lines`."""
    pid = proj["id"]
    lines.append(f"# {proj['slug']} — Phase: {proj['phase']} | Blockers: {proj['blockers']}\n")

    counts = {}
    for row in conn.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks WHERE project_id = ? GROUP BY status",
        (pid,),
    ).fetchall():
        counts[row["status"]] = row["cnt"]

    for board_status, title in [("working", "Working"), ("testing", "Testing"), ("todo", "To Do")]:
        tasks = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND status = ? ORDER BY priority, task_id",
            (pid, board_status),
        ).fetchall()

        lines.append(f"## {title} ({counts.get(board_status, 0)})")
        if tasks:
            lines.append("| ID | Title | Priority | Agent | Depends On |")
            lines.append("|----|-------|----------|-------|------------|")
            for t in tasks:
                lines.append(
                    f"| {t['task_id']} | {t['title']} | {t['priority'] or '--'} | "
                    f"{t['agent'] or '--'} | {t['depends_on'] or '--'} |"
                )
        else:
            lines.append("(none)")
        lines.append("")

    lines.append(
        f"## Done: {counts.get('done', 0)} | Freezer: {counts.get('freezer', 0)} "
        f"| Trash: {counts.get('trash', 0)}\n"
    )


def generate_board_snapshot(conn, cwd):
    """Generate project/board-snapshot.md from SQLite data, one section per project."""
    snapshot_path = Path(cwd) / "project" / "board-snapshot.md"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Project Board Snapshot\nGenerated: {now}\n"]

    # One board per real project; include the workspace project only if it owns tasks.
    sections = list(list_projects(conn, include_workspace=False))
    ws = get_project_by_id(conn, WORKSPACE_ID)
    ws_task_count = conn.execute(
        "SELECT COUNT(*) c FROM tasks WHERE project_id = ?", (WORKSPACE_ID,)
    ).fetchone()["c"]
    if ws and (ws_task_count > 0 or not sections):
        sections = [ws] + sections

    for proj in sections:
        _project_board_section(conn, lines, proj)

    # Recent activity (workspace-wide)
    activities = conn.execute(
        "SELECT * FROM activity_log ORDER BY id DESC LIMIT 10"
    ).fetchall()
    if activities:
        lines.append("## Recent Activity")
        lines.append("| Date | Activity |")
        lines.append("|------|----------|")
        for act in activities:
            lines.append(f"| {act['date']} | {act['message']} |")
        lines.append("")

    # Dependency graph (Mermaid), workspace-wide
    deps = conn.execute(
        "SELECT task_id, depends_on FROM tasks WHERE depends_on != '' AND status NOT IN ('done', 'trash')"
    ).fetchall()
    if deps:
        lines.append("## Dependencies")
        lines.append("```mermaid")
        lines.append("graph TD")
        for d in deps:
            dep_refs = re.findall(r"[TBS]-\d+", d["depends_on"])
            for ref in dep_refs:
                lines.append(f"    {d['task_id']} --> {ref}")
        lines.append("```")
        lines.append("")

    # Gantt chart for active tasks
    active = conn.execute(
        "SELECT * FROM tasks WHERE status IN ('working', 'testing') ORDER BY task_id"
    ).fetchall()
    if active:
        lines.append("## Timeline")
        lines.append("```mermaid")
        lines.append("gantt")
        lines.append("    title Active Tasks")
        lines.append("    dateFormat YYYY-MM-DD")
        for t in active:
            status_label = "active" if t["status"] == "working" else "done"
            task_key = t["task_id"].lower().replace("-", "")
            start_date = t["updated_date"] or t["created_date"]
            lines.append(f"    section {t['status'].title()}")
            lines.append(f"    {t['title'][:30]} :{status_label}, {task_key}, {start_date}, 3d")
        lines.append("```")

    snapshot_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    session_id = data.get("session_id", "unknown")
    # Resolve the payload cwd UP to the real workspace root before it is used to
    # load config, open the DB, make paths relative, or write the board
    # snapshot -- a drifted shell cwd must not point any of these at a
    # sub-directory. (session_gate uses cwd only for these root-relative
    # purposes, never to run a shell command.)
    cwd = get_project_root(data.get("cwd"))

    project_config = load_project_config(cwd)
    if not project_config:
        sys.exit(0)

    if project_config.get("workspace_scope") != "project":
        sys.exit(0)

    # Defense-in-depth: skip enforcement for a minimal (scratchpad) workspace
    # (this hook shouldn't be registered then, but if it is, don't enforce).
    if workspace_is_minimal(project_config):
        conn = get_db(cwd)
        try:
            generate_board_snapshot(conn, cwd)
        finally:
            conn.close()
        sys.exit(0)

    # Loop guard: if we are already inside a stop-hook-induced continuation, the
    # agent has nothing left to do (it is parked waiting for the user). Blocking
    # again with exit 2 would re-invoke the agent and spin forever. Generate the
    # snapshot and let it stop. Real enforcement still happens at commit time in
    # commit_gate.py, which is independent of this hook.
    if data.get("stop_hook_active"):
        conn = get_db(cwd)
        try:
            generate_board_snapshot(conn, cwd)
        finally:
            conn.close()
        sys.exit(0)

    doc_config = load_doc_enforcement(cwd)
    if not doc_config:
        sys.exit(0)

    conn = get_db(cwd)
    try:
        # Load session state
        session = conn.execute(
            "SELECT * FROM session_state WHERE session_id = ?", (session_id,)
        ).fetchone()

        if not session:
            # No modifications tracked -- generate snapshot and exit
            generate_board_snapshot(conn, cwd)
            sys.exit(0)

        modified_files = json_loads(session["modified_files"])
        mcp_tools = json_loads(session["mcp_tools"])

        if not modified_files:
            generate_board_snapshot(conn, cwd)
            sys.exit(0)

        # Check if source files were modified
        source_modified = [
            make_relative(f, cwd) for f in modified_files
            if is_source_file(make_relative(f, cwd))
        ]

        if not source_modified:
            generate_board_snapshot(conn, cwd)
            sys.exit(0)

        rules = [r for r in doc_config.get("rules", []) if r.get("when") == "source_modified"]
        requires = {r.get("require", "") for r in rules}

        # Session-wide lifecycle checks (task start/validate live in the global
        # session mcp_tools list, not a per-project row).
        if "task_started" in requires and "task-manager:start_task" not in mcp_tools:
            print("Source files modified but no task was started.", file=sys.stderr)
            print(f"\nSource files: {', '.join(source_modified[:10])}", file=sys.stderr)
            print("\nRequired: start a task with task-manager start_task.", file=sys.stderr)
            sys.exit(2)
        # NOTE: task_validated is intentionally NOT gated here. Validation
        # requires the user to re-test and confirm, which cannot happen during a
        # Stop-hook continuation -- gating it here caused an infinite loop
        # whenever the agent parked to wait for the user. It is enforced at
        # commit time by commit_gate.py instead, which is independent of Stop.

        # Per-project review checks: attribute each modified source file to a
        # project, then gate each project (skipping minimal-enforcement ones)
        # against ITS OWN review_order. Finishing project A's reviews must not
        # unblock a session that also modified project B.
        files_by_project = {}
        for f in source_modified:
            pid = project_for_path(conn, f) or WORKSPACE_ID
            files_by_project.setdefault(pid, []).append(f)

        for pid, files in files_by_project.items():
            proj = get_project_by_id(conn, pid)
            if proj and proj["enforcement"] == "minimal":
                continue
            tag = f"[project: {proj['slug'] if proj else 'workspace'}]"
            review = conn.execute(
                "SELECT * FROM review_order WHERE project_id = ?", (pid,)
            ).fetchone()

            if "code_reviewed" in requires:
                if not review or not review["code_review_done"]:
                    print(f"{tag} Source files modified but code review was not completed.", file=sys.stderr)
                    print(f"\nFiles: {', '.join(files[:10])}", file=sys.stderr)
                    print("\nRequired: spawn code-reviewer, then call acknowledge_code_review.", file=sys.stderr)
                    sys.exit(2)
                if review["code_review_critical"] > 0:
                    print(f"{tag} Code review has {review['code_review_critical']} CRITICAL issue(s).", file=sys.stderr)
                    sys.exit(2)

            if "doc_reviewed" in requires and (not review or not review["doc_review_done"]):
                print(f"{tag} Source files modified but doc review was not completed.", file=sys.stderr)
                print("\nRequired: spawn docs-reviewer, then call acknowledge_review.", file=sys.stderr)
                sys.exit(2)

            if "security_reviewed" in requires and (not review or not review["security_review_done"]):
                print(f"{tag} Source files modified but security review was not completed.", file=sys.stderr)
                print("\nRequired: spawn security-reviewer, then call acknowledge_security_review.", file=sys.stderr)
                sys.exit(2)

            if "tests_acknowledged" in requires:
                if not review or not review["tests_done"]:
                    print(f"{tag} Source files modified but tests were not acknowledged.", file=sys.stderr)
                    print("\nRequired: find_untested_files, spawn test-runner, then acknowledge_tests.", file=sys.stderr)
                    sys.exit(2)
                if review["tests_failures"] > 0:
                    print(f"{tag} WARNING: Tests acknowledged with {review['tests_failures']} failure(s).", file=sys.stderr)

        # All checks passed -- generate board snapshot
        generate_board_snapshot(conn, cwd)

    finally:
        conn.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
