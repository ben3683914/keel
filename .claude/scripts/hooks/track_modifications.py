#!/usr/bin/env python3
"""PostToolUse hook: tracks files and MCP tools Claude uses during a session.

Fires on Edit, Write, and MCP tool calls. Records to SQLite session_state table.
Works in both project and scratch modes.
"""

import json
import sys
from pathlib import Path

# Add shared module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_db, get_project_root, json_loads, json_dumps
from routing import refresh_doc_routing, refresh_code_routing, is_source_file
from projects import project_for_path, get_active_project_id, set_active_project


def make_relative(file_path, cwd):
    try:
        return str(Path(file_path).relative_to(cwd)).replace("\\", "/")
    except ValueError:
        return file_path.replace("\\", "/")


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    session_id = data.get("session_id", "unknown")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})

    refresh_docs = False
    refresh_code = False

    # The payload `cwd` is the drifting shell cwd, not the workspace root. Pin
    # the root once via the same resolver get_db uses, then make every path
    # relative to THAT (not the raw cwd) so a `cd` into a sub-directory can't
    # register subdir-relative routing or mis-infer the active project.
    root = get_project_root(data.get("cwd"))
    conn = get_db(root)
    try:
        # Ensure session row exists
        existing = conn.execute(
            "SELECT * FROM session_state WHERE session_id = ?", (session_id,)
        ).fetchone()

        if not existing:
            conn.execute(
                "INSERT INTO session_state (session_id) VALUES (?)",
                (session_id,),
            )
            conn.commit()
            existing = conn.execute(
                "SELECT * FROM session_state WHERE session_id = ?", (session_id,)
            ).fetchone()

        modified_files = json_loads(existing["modified_files"])
        mcp_tools = json_loads(existing["mcp_tools"])
        updates = {}

        # Track Edit/Write file modifications
        if tool_name in ("Edit", "Write"):
            file_path = tool_input.get("file_path", "")
            if not file_path:
                sys.exit(0)
            if isinstance(tool_response, dict) and tool_response.get("success") is False:
                sys.exit(0)
            normalized = file_path.replace("\\", "/")
            if normalized not in modified_files:
                modified_files.append(normalized)
                updates["modified_files"] = json_dumps(modified_files)
            if normalized.endswith(".md"):
                refresh_docs = True
            elif is_source_file(normalized):
                refresh_code = True

            # Inference-on-edit: the active project follows the files being
            # edited. If this file belongs to a different project, move the
            # workspace-global pointer so board ops follow the work. The
            # `[project: <slug>]` echo on MCP responses surfaces the switch.
            rel = make_relative(file_path, root)
            inferred = project_for_path(conn, rel)
            if inferred is not None and inferred != get_active_project_id(conn):
                set_active_project(conn, inferred)

        # Track MCP tool calls
        elif tool_name.startswith("mcp__"):
            parts = tool_name.split("__", 2)
            if len(parts) == 3:
                server_name = parts[1]
                mcp_tool_name = parts[2]
                entry = f"{server_name}:{mcp_tool_name}"
                if entry not in mcp_tools:
                    mcp_tools.append(entry)
                    updates["mcp_tools"] = json_dumps(mcp_tools)

                # Capture acknowledgment data
                if entry == "docs-manager:acknowledge_review":
                    try:
                        updates["docs_unresolved_issues"] = int(tool_input.get("unresolved_issues", 0))
                    except (TypeError, ValueError):
                        updates["docs_unresolved_issues"] = 0

                elif entry == "test-manager:acknowledge_tests":
                    try:
                        updates["tests_failures"] = int(tool_input.get("failures", 0))
                    except (TypeError, ValueError):
                        updates["tests_failures"] = 0

                elif entry == "code-manager:acknowledge_security_review":
                    try:
                        updates["security_issues"] = int(tool_input.get("security_issues", 0))
                    except (TypeError, ValueError):
                        updates["security_issues"] = 0
                    updates["security_deferred"] = 1 if tool_input.get("deferred", False) else 0

                elif entry == "code-manager:acknowledge_code_review":
                    try:
                        updates["code_critical_issues"] = int(tool_input.get("critical_issues", 0))
                    except (TypeError, ValueError):
                        updates["code_critical_issues"] = 0
                    try:
                        updates["code_advisory_issues"] = int(tool_input.get("advisory_issues", 0))
                    except (TypeError, ValueError):
                        updates["code_advisory_issues"] = 0

        if updates:
            updates["updated_at"] = "datetime('now')"
            # Build update manually to handle the datetime function
            set_parts = []
            params = []
            for k, v in updates.items():
                if v == "datetime('now')":
                    set_parts.append(f"{k} = datetime('now')")
                else:
                    set_parts.append(f"{k} = ?")
                    params.append(v)
            params.append(session_id)

            conn.execute(
                f"UPDATE session_state SET {', '.join(set_parts)} WHERE session_id = ?",
                params,
            )
            conn.commit()
    finally:
        conn.close()

    if refresh_docs:
        try:
            refresh_doc_routing()
        except Exception:
            pass
    elif refresh_code:
        try:
            refresh_code_routing()
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()
