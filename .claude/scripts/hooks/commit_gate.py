#!/usr/bin/env python3
"""PreToolUse hook: enforcement checks for git commit (single-purpose / multi-purpose only).

Fires on Bash tool calls. Checks if the command is a git commit.
Enforces (in order):
4. Routing freshness (refresh_doc_routing + refresh_code_routing called)
5. Code review acknowledgment (critical_issues == 0)
6. Docs review acknowledgment (unresolved_issues == 0)
7. Security review acknowledgment
8. Task validated (validate_task called)
9. Tests acknowledgment

Basic quality checks (build, message format, branding) live in commit_quality.py
and run in ALL modes. This hook only runs in enforcement modes.

All state read from SQLite (.claude/claude.db).
"""

import json
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

# Add shared module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_db, get_project_root, json_loads
from routing import is_source_file
from projects import get_project_by_id, project_for_path, WORKSPACE_ID


def load_project_config(cwd):
    config_path = Path(cwd) / ".claude" / "project-config.json"
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def workspace_is_minimal(config) -> bool:
    """True when enforcement is off (scratchpad). Honors the new `enforcement`
    key and the legacy `project_mode == 'scratchpad'`."""
    enforcement = config.get("enforcement")
    if enforcement:
        return enforcement == "minimal"
    return config.get("project_mode") == "scratchpad"


def group_by_project(conn, files):
    """Map each relative file path to its project id (workspace fallback)."""
    grouped = {}
    for f in files:
        pid = project_for_path(conn, f) or WORKSPACE_ID
        grouped.setdefault(pid, []).append(f)
    return grouped


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


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command", "")
    if not re.search(r"\bgit\s+commit\b", command):
        sys.exit(0)

    session_id = data.get("session_id", "unknown")
    # Resolve UP to the real workspace root: the commit gate must consult the
    # real DB and config, never a freshly-bootstrapped shadow copy that a
    # drifted shell cwd would point at (which could wrongly pass or block).
    cwd = get_project_root(data.get("cwd"))
    project_config = load_project_config(cwd)

    # Skip if not in project scope
    if not project_config or project_config.get("workspace_scope") != "project":
        sys.exit(0)

    # Defense-in-depth: skip if the workspace is minimal/scratchpad (this hook
    # shouldn't be registered then, but if it is, don't enforce)
    if workspace_is_minimal(project_config):
        sys.exit(0)

    conn = get_db(cwd)
    try:
        # Load session state
        session = conn.execute(
            "SELECT * FROM session_state WHERE session_id = ?", (session_id,)
        ).fetchone()

        if not session:
            sys.exit(0)

        modified_files = json_loads(session["modified_files"])
        mcp_tools = json_loads(session["mcp_tools"])

        if not modified_files:
            sys.exit(0)

        doc_patterns = project_config.get("doc_patterns", ["docs/**/*.md"])

        rel_files = [make_relative(f, cwd) for f in modified_files]
        source_files = [f for f in rel_files if is_source_file(f)]
        doc_files = [f for f in rel_files if matches_any(f, doc_patterns)]
        source_modified = bool(source_files)

        # (Routing freshness is NOT gated here: track_modifications.py refreshes
        # doc/code routing automatically on every source/doc edit, so requiring a
        # manual refresh_*_routing call only produced false blocks.)

        has_deferred = "task-manager:report_security_findings" in mcp_tools
        source_by_project = group_by_project(conn, source_files)
        # Doc review applies to any project whose source OR docs changed.
        doc_review_pids = set(source_by_project) | set(group_by_project(conn, doc_files))

        def proj_tag(pid):
            proj = get_project_by_id(conn, pid)
            return proj, f"[project: {proj['slug'] if proj else 'workspace'}]"

        # --- Per-project review_order gates (Checks 5-7, 9) ---
        for pid, files in source_by_project.items():
            proj, tag = proj_tag(pid)
            if proj and proj["enforcement"] == "minimal":
                continue
            review = conn.execute(
                "SELECT * FROM review_order WHERE project_id = ?", (pid,)
            ).fetchone()

            # Check 5: code review
            if not review or not review["code_review_done"]:
                print(f"{tag} Code review required.", file=sys.stderr)
                print("\nRequired: spawn code-reviewer, then call acknowledge_code_review.", file=sys.stderr)
                sys.exit(2)
            if review["code_review_critical"] > 0:
                print(f"{tag} Code review has {review['code_review_critical']} critical issue(s).", file=sys.stderr)
                sys.exit(2)

            # Check 7: security review (per project, or session-wide deferral)
            if not review["security_review_done"] and not has_deferred:
                print(f"{tag} Security review required.", file=sys.stderr)
                print("\nRequired: spawn security-reviewer, then call acknowledge_security_review.", file=sys.stderr)
                sys.exit(2)

            # Check 9: tests
            if not review["tests_done"]:
                print(f"{tag} Tests required.", file=sys.stderr)
                print("\nRequired: find_untested_files, spawn test-runner, then acknowledge_tests.", file=sys.stderr)
                sys.exit(2)
            if review["tests_failures"] > 0:
                print(f"{tag} WARNING: Tests acknowledged with {review['tests_failures']} failure(s).", file=sys.stderr)

        # --- Check 6: Docs review (projects whose source or docs changed) ---
        for pid in doc_review_pids:
            proj, tag = proj_tag(pid)
            if proj and proj["enforcement"] == "minimal":
                continue
            review = conn.execute(
                "SELECT * FROM review_order WHERE project_id = ?", (pid,)
            ).fetchone()
            if not review or not review["doc_review_done"]:
                print(f"{tag} Doc review required.", file=sys.stderr)
                print("\nRequired: spawn docs-reviewer, then call acknowledge_review.", file=sys.stderr)
                sys.exit(2)
            if review["doc_review_unresolved"] > 0:
                print(f"{tag} Doc review has {review['doc_review_unresolved']} unresolved issue(s).", file=sys.stderr)
                sys.exit(2)

        # --- Check 8: Task validated (session-global) ---
        if source_modified and "task-manager:start_task" in mcp_tools:
            if "task-manager:validate_task" not in mcp_tools:
                print("Task validation required before commit.", file=sys.stderr)
                print(
                    "\nFlow: reviews -> move_to_testing -> user validates -> validate_task -> commit.\n"
                    "Required: call task-manager validate_task before committing.",
                    file=sys.stderr,
                )
                sys.exit(2)
    finally:
        conn.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
