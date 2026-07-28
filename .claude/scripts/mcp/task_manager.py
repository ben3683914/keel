#!/usr/bin/env python3
"""Task Manager MCP Server.

Provides structured tools for managing project tasks via SQLite.
All task state lives in .claude/claude.db. Board markdown files are
no longer used -- the board-snapshot.md is auto-generated at session end.
"""

import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Add shared module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_db, json_dumps, json_loads
from projects import (
    resolve_project,
    get_active_project_id,
    get_project_by_slug,
    list_projects,
    project_label,
)

# --- Configuration ---

STATUSES = ["todo", "working", "testing", "done", "freezer", "trash"]

BOARD_TITLES = {
    "todo": "To Do",
    "working": "In Progress",
    "testing": "Testing",
    "done": "Done",
    "freezer": "Freezer",
    "trash": "Trash",
}

CATEGORIES = {
    "tasks": {"prefix": "T", "section": "Feature Tasks"},
    "bugs": {"prefix": "B", "section": "Bug Fixes"},
    "security": {"prefix": "S", "section": "Security Issues"},
}

UPDATABLE_FIELDS = [
    "agent", "priority", "depends_on", "description",
    "acceptance", "notes", "severity", "test_plan",
]


# --- Helpers ---


def normalize_task_id(task_id: str) -> str:
    """Normalize task ID: T-1 -> T-001, t-23 -> T-023."""
    match = re.match(r"^([TBStbs])-?(\d+)$", task_id.strip())
    if match:
        return f"{match.group(1).upper()}-{int(match.group(2)):03d}"
    return task_id.strip().upper()


def infer_category(task_id: str) -> str:
    prefix = task_id.split("-")[0].upper()
    for cat, info in CATEGORIES.items():
        if info["prefix"] == prefix:
            return cat
    return "tasks"


def get_next_task_id(conn, prefix: str = "T") -> str:
    """Get the next available task ID for a prefix."""
    row = conn.execute(
        "SELECT task_id FROM tasks WHERE task_id LIKE ? ORDER BY task_id DESC LIMIT 1",
        (f"{prefix}-%",),
    ).fetchone()
    if row:
        num = int(row["task_id"].split("-")[1])
        return f"{prefix}-{num + 1:03d}"
    return f"{prefix}-001"


def _looks_like_bug(title: str, description: str) -> bool:
    text = f"{title} {description}".lower()
    if re.match(r"^fix\b", title, re.IGNORECASE):
        return True
    bug_keywords = [
        r"\bbroken\b", r"\bnot working\b", r"\bregression\b", r"\bbug\b",
        r"\bcrash(?:es|ing)?\b", r"\bfailing\b", r"\bincorrect(?:ly)?\b",
    ]
    return any(re.search(kw, text) for kw in bug_keywords)


def task_summary(row) -> str:
    """Format a task row as a summary line."""
    parts = [f"[{row['task_id']}] {row['title']}"]
    if row["priority"]:
        parts.append(f"(Priority: {row['priority']})")
    if row["severity"]:
        parts.append(f"[{row['severity']}]")
    if row["agent"]:
        parts.append(f"[Agent: {row['agent']}]")
    return " ".join(parts)


def task_detail(row) -> str:
    """Format a task row with full details."""
    lines = [f"**[{row['task_id']}] {row['title']}**", f"Board: {row['status']}"]
    field_labels = {
        "priority": "Priority", "agent": "Agent", "depends_on": "Depends On",
        "description": "Description", "acceptance": "Acceptance",
        "test_plan": "Test Plan", "notes": "Notes", "severity": "Severity",
        "source": "Source", "completed_date": "Completed",
    }
    for field, label in field_labels.items():
        val = row[field]
        if val:
            lines.append(f"  {label}: {val}")
    return "\n".join(lines)


def _echo(slug: str, text: str) -> list[TextContent]:
    """Prepend the project echo so the active/target project is always visible."""
    return [TextContent(type="text", text=f"[project: {slug}]\n{text}")]


# --- MCP Server ---

server = Server("task-manager")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_tasks",
            description="List tasks from project boards. Returns task IDs, titles, priorities, and agents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "board": {
                        "type": "string",
                        "enum": STATUSES + ["all"],
                        "description": "Which board to list tasks from. Default: all",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["tasks", "security", "bugs", "all"],
                        "description": "Filter by category. Default: all",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project slug (or id) to scope to. Default: active project. "
                                       "Pass 'all' to list tasks across every project, grouped by project.",
                    },
                },
            },
        ),
        Tool(
            name="read_task",
            description="Get full details of a specific task by its ID (e.g., T-023, S-001, B-005).",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID, e.g. T-023 or S-001 or B-005",
                    }
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="create_task",
            description="Create a new task on the todo board.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short task title"},
                    "description": {"type": "string", "description": "Detailed description of the task"},
                    "priority": {
                        "type": "string",
                        "enum": ["P0", "P1", "P2"],
                        "description": "Priority level. Default: P1",
                    },
                    "depends_on": {"type": "string", "description": "Task dependencies, e.g. 'T-023'"},
                    "acceptance": {"type": "string", "description": "Acceptance criteria"},
                    "category": {
                        "type": "string",
                        "enum": ["tasks", "security", "bugs"],
                        "description": "Task category. Default: tasks",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        "description": "Severity for security/bug items",
                    },
                    "test_plan": {"type": "string", "description": "How to test this task"},
                    "project": {
                        "type": "string",
                        "description": "Project slug (or id) to file this task under. Default: active project.",
                    },
                },
                "required": ["title", "description"],
            },
        ),
        Tool(
            name="start_task",
            description="Move a task from todo to the working (in-progress) board and set the agent.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to start, e.g. T-023"},
                    "agent": {"type": "string", "description": "Who is working on it. Default: claude"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="move_to_testing",
            description="Move a task to the testing board for user verification.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID, e.g. T-023"},
                    "test_plan": {"type": "string", "description": "Step-by-step verification instructions"},
                    "notes": {"type": "string", "description": "Completion notes"},
                },
                "required": ["task_id", "test_plan"],
            },
        ),
        Tool(
            name="validate_task",
            description="Validate a tested task. Moves from testing to done with completion date.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to approve"},
                    "notes": {"type": "string", "description": "Completion notes"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="update_task",
            description="Update a specific field on a task. Use field='project' with a project "
                        "slug as the value to reparent (re-file) a task into another project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to update"},
                    "field": {
                        "type": "string",
                        "enum": UPDATABLE_FIELDS + ["project"],
                        "description": "Field to update. 'project' reparents the task (value = project slug).",
                    },
                    "value": {"type": "string", "description": "New value for the field"},
                },
                "required": ["task_id", "field", "value"],
            },
        ),
        Tool(
            name="log_activity",
            description="Add an entry to the activity log.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Activity description to log"},
                    "project": {
                        "type": "string",
                        "description": "Project slug (or id) to scope the log entry to. Default: active project.",
                    },
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="freeze_task",
            description="Move a task to the freezer board (deferred).",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to freeze"},
                    "reason": {"type": "string", "description": "Why this task is being deferred"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="unfreeze_task",
            description="Move a frozen task back to the todo board.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to unfreeze"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="move_to_todo",
            description="Move a task from any board (working, testing, done, trash) back to todo.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to move"},
                    "reason": {"type": "string", "description": "Why this task is being moved back"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="trash_task",
            description="Soft-delete a task by moving it to the trash board. Can be restored.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to trash"},
                    "reason": {"type": "string", "description": "Why this task is being trashed"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="report_security_findings",
            description="Bulk-create security issues from structured findings.",
            inputSchema={
                "type": "object",
                "properties": {
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "Short finding title"},
                                "severity": {
                                    "type": "string",
                                    "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                                    "description": "Severity level",
                                },
                                "description": {"type": "string", "description": "Detailed description"},
                            },
                            "required": ["title", "severity", "description"],
                        },
                        "description": "List of security findings to create as issues",
                    },
                    "source": {"type": "string", "description": "Where these findings came from"},
                    "project": {
                        "type": "string",
                        "description": "Project slug (or id) to file these security issues under. Default: active project.",
                    },
                },
                "required": ["findings"],
            },
        ),
        Tool(
            name="get_onboarding_status",
            description="Check if first-run onboarding is complete. Returns onboarding state.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="update_onboarding",
            description="Update onboarding fields during the first-run setup wizard.",
            inputSchema={
                "type": "object",
                "properties": {
                    "field": {
                        "type": "string",
                        "enum": [
                            "project_mode", "project_name", "project_purpose", "tech_stack",
                            "goals", "branching_strategy", "commit_conventions",
                            "review_strictness", "testing_approach", "coding_conventions",
                            "deployment_strategy", "team_structure", "greeting",
                            "is_existing_repo", "analysis_phases",
                            "current_phase", "phase_progress", "complete",
                        ],
                        "description": "Onboarding field to update",
                    },
                    "value": {"type": "string", "description": "New value for the field"},
                },
                "required": ["field", "value"],
            },
        ),
        Tool(
            name="get_project_status",
            description="Get current project phase and blockers, scoped task counts, recent "
                        "activity, and a per-project rollup across all real projects.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project slug (or id) to report. Default: active project.",
                    },
                },
            },
        ),
        Tool(
            name="update_project_status",
            description="Update the project phase or blockers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "phase": {"type": "string", "description": "Current project phase"},
                    "blockers": {"type": "string", "description": "Current blockers (or 'None')"},
                    "project": {
                        "type": "string",
                        "description": "Project slug (or id) to update. Default: active project.",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        handlers = {
            "list_tasks": handle_list_tasks,
            "read_task": handle_read_task,
            "create_task": handle_create_task,
            "start_task": handle_start_task,
            "move_to_testing": handle_move_to_testing,
            "validate_task": handle_validate_task,
            "update_task": handle_update_task,
            "log_activity": handle_log_activity,
            "freeze_task": handle_freeze_task,
            "unfreeze_task": handle_unfreeze_task,
            "move_to_todo": handle_move_to_todo,
            "trash_task": handle_trash_task,
            "report_security_findings": handle_report_security_findings,
            "get_onboarding_status": handle_get_onboarding_status,
            "update_onboarding": handle_update_onboarding,
            "get_project_status": handle_get_project_status,
            "update_project_status": handle_update_project_status,
        }
        handler = handlers.get(name)
        if handler:
            return handler(arguments)
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


# --- Tool Handlers ---


def handle_list_tasks(args: dict) -> list[TextContent]:
    board = args.get("board", "all")
    category = args.get("category", "all")
    project_arg = args.get("project")
    show_all = isinstance(project_arg, str) and project_arg == "all"

    conn = get_db()
    try:
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []

        if not show_all:
            # Scope to a single project (explicit slug/id or the active pointer).
            project_id, slug = resolve_project(conn, args)
            query += " AND project_id = ?"
            params.append(project_id)

        if board != "all":
            query += " AND status = ?"
            params.append(board)

        if category != "all":
            query += " AND category = ?"
            params.append(category)

        if show_all:
            # Group by project first, then status, so each project's board is contiguous.
            query += " ORDER BY project_id, status, category, task_id"
        else:
            query += " ORDER BY status, category, task_id"
        rows = conn.execute(query, params).fetchall()

        if not rows:
            empty = "No tasks found."
            return _echo("all" if show_all else slug, empty)

        lines = []
        if show_all:
            current_project = None
            current_status = None
            for row in rows:
                if row["project_id"] != current_project:
                    current_project = row["project_id"]
                    current_status = None
                    lines.append(f"\n# project: {project_label(conn, current_project)}")
                if row["status"] != current_status:
                    current_status = row["status"]
                    title = BOARD_TITLES.get(current_status, current_status.title())
                    lines.append(f"\n## {title}")
                lines.append(f"  {task_summary(row)}")
            return _echo("all", "\n".join(lines))

        current_status = None
        for row in rows:
            if row["status"] != current_status:
                current_status = row["status"]
                title = BOARD_TITLES.get(current_status, current_status.title())
                lines.append(f"\n## {title}")
            lines.append(f"  {task_summary(row)}")

        return _echo(slug, "\n".join(lines))
    finally:
        conn.close()


def handle_read_task(args: dict) -> list[TextContent]:
    task_id = normalize_task_id(args["task_id"])

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return [TextContent(type="text", text=f"Task {task_id} not found")]
        return _echo(project_label(conn, row["project_id"]), task_detail(row))
    finally:
        conn.close()


def handle_create_task(args: dict) -> list[TextContent]:
    title = args["title"]
    description = args["description"]
    category = args.get("category", "tasks")
    priority = args.get("priority", "P1")
    today = date.today().isoformat()

    if category not in CATEGORIES:
        return [TextContent(type="text", text=f"Unknown category: {category}")]

    # Auto-reclassify bug-like tasks
    recategorized = False
    if category == "tasks" and _looks_like_bug(title, description):
        category = "bugs"
        recategorized = True

    prefix = CATEGORIES[category]["prefix"]

    conn = get_db()
    try:
        # task_id stays GLOBALLY unique -> do not scope get_next_task_id.
        project_id, slug = resolve_project(conn, args)
        task_id = get_next_task_id(conn, prefix)
        conn.execute(
            "INSERT INTO tasks (task_id, project_id, title, status, category, priority, agent, "
            "depends_on, description, acceptance, notes, severity, source, test_plan, "
            "completed_date, created_date, updated_date) "
            "VALUES (?, ?, ?, 'todo', ?, ?, '', ?, ?, ?, '', ?, ?, ?, '', ?, ?)",
            (
                task_id, project_id, title, category, priority,
                args.get("depends_on", ""), description,
                args.get("acceptance", ""),
                args.get("severity", ""),
                args.get("source", ""),
                args.get("test_plan", ""),
                today, today,
            ),
        )
        conn.commit()

        msg = f"Created [{task_id}] {title} on todo board"
        if recategorized:
            msg += " (auto-reclassified from tasks -> bugs: title/description indicates a fix)"
        return _echo(slug, msg)
    finally:
        conn.close()


def handle_start_task(args: dict) -> list[TextContent]:
    task_id = normalize_task_id(args["task_id"])
    agent = args.get("agent", "claude")

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return [TextContent(type="text", text=f"Task {task_id} not found")]
        if row["status"] == "working":
            return _echo(
                project_label(conn, row["project_id"]),
                f"Task {task_id} is already in progress",
            )

        conn.execute(
            "UPDATE tasks SET status = 'working', agent = ?, updated_date = ? WHERE task_id = ?",
            (agent, date.today().isoformat(), task_id),
        )
        conn.commit()
        return _echo(
            project_label(conn, row["project_id"]),
            f"Started [{task_id}] {row['title']} -> working (agent: {agent})",
        )
    finally:
        conn.close()


def handle_move_to_testing(args: dict) -> list[TextContent]:
    task_id = normalize_task_id(args["task_id"])
    test_plan = args["test_plan"]
    notes = args.get("notes", "")

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return [TextContent(type="text", text=f"Task {task_id} not found")]

        updates = {"status": "testing", "test_plan": test_plan, "updated_date": date.today().isoformat()}
        if notes:
            updates["notes"] = notes

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE task_id = ?",
            (*updates.values(), task_id),
        )
        conn.commit()
        return _echo(
            project_label(conn, row["project_id"]),
            f"Moved [{task_id}] {row['title']} -> testing",
        )
    finally:
        conn.close()


def handle_validate_task(args: dict) -> list[TextContent]:
    task_id = normalize_task_id(args["task_id"])
    notes = args.get("notes", "")

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return [TextContent(type="text", text=f"Task {task_id} not found")]
        if row["status"] != "testing":
            return _echo(
                project_label(conn, row["project_id"]),
                f"Task {task_id} is not on testing board (currently: {row['status']}). "
                "Only tasks on the testing board can be validated.",
            )

        today = date.today().isoformat()
        updates = {"status": "done", "completed_date": today, "updated_date": today}
        if notes:
            updates["notes"] = notes

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE task_id = ?",
            (*updates.values(), task_id),
        )
        conn.commit()
        return _echo(
            project_label(conn, row["project_id"]),
            f"Validated [{task_id}] {row['title']} -> done (completed: {today})",
        )
    finally:
        conn.close()


def handle_update_task(args: dict) -> list[TextContent]:
    task_id = normalize_task_id(args["task_id"])
    field = args["field"]
    value = args["value"]

    # 'project' is a reparent, not a column write -- handle it BEFORE the column
    # guard ('project' is not a real column; the table column is project_id).
    if field == "project":
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                return [TextContent(type="text", text=f"Task {task_id} not found")]

            target = get_project_by_slug(conn, str(value))
            if target is None and str(value).isdigit():
                from projects import get_project_by_id
                target = get_project_by_id(conn, int(value))
            if target is None:
                # Never write a bad id into the NOT NULL FK; surface the error.
                return _echo(
                    project_label(conn, row["project_id"]),
                    f"Unknown project '{value}' -- task {task_id} not reparented.",
                )

            conn.execute(
                "UPDATE tasks SET project_id = ?, updated_date = ? WHERE task_id = ?",
                (target["id"], date.today().isoformat(), task_id),
            )
            conn.commit()
            return _echo(
                target["slug"],
                f"Reparented [{task_id}] {row['title']} -> project {target['slug']}",
            )
        finally:
            conn.close()

    if field not in UPDATABLE_FIELDS:
        return [TextContent(type="text", text=f"Cannot update field: {field}")]

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return [TextContent(type="text", text=f"Task {task_id} not found")]

        conn.execute(
            f"UPDATE tasks SET {field} = ?, updated_date = ? WHERE task_id = ?",
            (value, date.today().isoformat(), task_id),
        )
        conn.commit()
        return _echo(
            project_label(conn, row["project_id"]),
            f"Updated [{task_id}] {field} = {value}",
        )
    finally:
        conn.close()


def handle_log_activity(args: dict) -> list[TextContent]:
    message = args["message"]
    today = date.today().isoformat()

    conn = get_db()
    try:
        # Stamp the active project (honors explicit project= for symmetry).
        project_id, slug = resolve_project(conn, args)
        conn.execute(
            "INSERT INTO activity_log (project_id, date, message) VALUES (?, ?, ?)",
            (project_id, today, message),
        )
        conn.commit()
        return _echo(slug, f"Logged: {today} | {message}")
    finally:
        conn.close()


def _move_task(task_id: str, target_status: str, note_prefix: str = "", reason: str = "") -> list[TextContent]:
    """Generic task move handler."""
    task_id = normalize_task_id(task_id)

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return [TextContent(type="text", text=f"Task {task_id} not found")]
        if row["status"] == target_status:
            return _echo(
                project_label(conn, row["project_id"]),
                f"Task {task_id} is already on {target_status}",
            )

        old_status = row["status"]
        updates = {"status": target_status, "updated_date": date.today().isoformat()}
        if reason and note_prefix:
            updates["notes"] = f"{note_prefix}: {reason}"

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE task_id = ?",
            (*updates.values(), task_id),
        )
        conn.commit()
        return _echo(
            project_label(conn, row["project_id"]),
            f"Moved [{task_id}] {row['title']} from {old_status} -> {target_status}",
        )
    finally:
        conn.close()


def handle_freeze_task(args: dict) -> list[TextContent]:
    return _move_task(args["task_id"], "freezer", "Frozen", args.get("reason", ""))


def handle_unfreeze_task(args: dict) -> list[TextContent]:
    task_id = normalize_task_id(args["task_id"])
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            return [TextContent(type="text", text=f"Task {task_id} not found")]
        if row["status"] != "freezer":
            return _echo(
                project_label(conn, row["project_id"]),
                f"Task {task_id} is not frozen (currently: {row['status']})",
            )

        # Clear frozen note if present
        notes = row["notes"]
        if notes and notes.startswith("Frozen: "):
            notes = ""

        conn.execute(
            "UPDATE tasks SET status = 'todo', notes = ?, updated_date = ? WHERE task_id = ?",
            (notes, date.today().isoformat(), task_id),
        )
        conn.commit()
        return _echo(
            project_label(conn, row["project_id"]),
            f"Unfrozen [{task_id}] {row['title']} -> todo",
        )
    finally:
        conn.close()


def handle_move_to_todo(args: dict) -> list[TextContent]:
    return _move_task(args["task_id"], "todo", "Moved back", args.get("reason", ""))


def handle_trash_task(args: dict) -> list[TextContent]:
    return _move_task(args["task_id"], "trash", "Trashed", args.get("reason", ""))


def handle_report_security_findings(args: dict) -> list[TextContent]:
    findings = args.get("findings", [])
    source = args.get("source", "security review")

    if not findings:
        return [TextContent(type="text", text="No findings to report.")]

    today = date.today().isoformat()
    conn = get_db()
    try:
        project_id, slug = resolve_project(conn, args)
        created = []
        for finding in findings:
            task_id = get_next_task_id(conn, "S")
            conn.execute(
                "INSERT INTO tasks (task_id, project_id, title, status, category, priority, "
                "description, severity, source, created_date, updated_date) "
                "VALUES (?, ?, ?, 'todo', 'security', 'P1', ?, ?, ?, ?, ?)",
                (
                    task_id,
                    project_id,
                    finding["title"],
                    finding["description"],
                    finding["severity"],
                    source,
                    today,
                    today,
                ),
            )
            created.append(f"  [{task_id}] {finding['title']} [{finding['severity']}]")

        conn.commit()
        msg = f"Created {len(created)} security issue(s) from {source}:\n" + "\n".join(created)
        return _echo(slug, msg)
    finally:
        conn.close()


# --- Onboarding & Project Status Handlers ---


def handle_get_onboarding_status(args: dict) -> list[TextContent]:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM onboarding WHERE id = 1").fetchone()
        if not row:
            return [TextContent(type="text", text="Onboarding not initialized.")]

        if row["complete"]:
            return [TextContent(
                type="text",
                text=f"Onboarding: COMPLETE (finished: {row['completed_at']})\n"
                     f"Project: {row['project_name']} -- {row['project_purpose']}",
            )]

        # Not complete -- report progress
        lines = ["Onboarding: IN PROGRESS"]
        if row["started_at"]:
            lines.append(f"Started: {row['started_at']}")

        mode = row["project_mode"] if row["project_mode"] else ""
        if mode:
            lines.append(f"Mode: {mode}")

        # Fields required depend on project mode
        if mode == "scratchpad":
            required_fields = ["project_name"]
        else:
            required_fields = [
                "project_name", "project_purpose", "tech_stack", "goals",
                "branching_strategy", "commit_conventions", "review_strictness",
                "testing_approach", "coding_conventions", "deployment_strategy",
                "team_structure",
            ]

        filled = []
        empty = []
        for field in required_fields:
            if row[field]:
                filled.append(field)
            else:
                empty.append(field)

        lines.append(f"Answered: {len(filled)}/{len(required_fields)}")
        if empty:
            lines.append(f"Remaining: {', '.join(empty)}")

        if row["is_existing_repo"] and row["current_phase"] > 0:
            phases = json_loads(row["analysis_phases"])
            lines.append(f"Analysis: phase {row['current_phase']}/{len(phases)}")

        return [TextContent(type="text", text="\n".join(lines))]
    finally:
        conn.close()


def handle_update_onboarding(args: dict) -> list[TextContent]:
    field = args["field"]
    value = args["value"]

    valid_fields = {
        "project_mode", "project_name", "project_purpose", "tech_stack",
        "goals", "branching_strategy", "commit_conventions",
        "review_strictness", "testing_approach", "coding_conventions",
        "deployment_strategy", "team_structure", "greeting",
        "is_existing_repo", "analysis_phases",
        "current_phase", "phase_progress", "complete",
    }

    if field not in valid_fields:
        return [TextContent(type="text", text=f"Invalid onboarding field: {field}")]

    conn = get_db()
    try:
        # Handle special fields
        if field == "complete" and value in ("1", "true", "True"):
            conn.execute(
                "UPDATE onboarding SET complete = 1, completed_at = ? WHERE id = 1",
                (date.today().isoformat(),),
            )
        elif field in ("is_existing_repo", "current_phase", "complete"):
            conn.execute(
                f"UPDATE onboarding SET {field} = ? WHERE id = 1",
                (int(value),),
            )
        else:
            conn.execute(
                f"UPDATE onboarding SET {field} = ? WHERE id = 1",
                (value,),
            )

        # Set started_at on first update
        row = conn.execute("SELECT started_at FROM onboarding WHERE id = 1").fetchone()
        if not row["started_at"]:
            conn.execute(
                "UPDATE onboarding SET started_at = ? WHERE id = 1",
                (date.today().isoformat(),),
            )

        conn.commit()
        return [TextContent(type="text", text=f"Onboarding: {field} = {value}")]
    finally:
        conn.close()


def _project_task_counts(conn, project_id: int) -> dict:
    counts = {}
    for row in conn.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks WHERE project_id = ? GROUP BY status",
        (project_id,),
    ).fetchall():
        counts[row["status"]] = row["cnt"]
    return counts


def handle_get_project_status(args: dict) -> list[TextContent]:
    conn = get_db()
    try:
        # Phase/blockers now live on the projects row (project_status table removed).
        project_id, slug = resolve_project(conn, args)
        proj = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
            return [TextContent(type="text", text="No project status found.")]

        # Task counts scoped to the resolved project.
        counts = _project_task_counts(conn, project_id)

        lines = [
            f"Phase: {proj['phase']}",
            f"Blockers: {proj['blockers']}",
            f"Tasks: todo={counts.get('todo', 0)} working={counts.get('working', 0)} "
            f"testing={counts.get('testing', 0)} done={counts.get('done', 0)}",
        ]

        # Recent activity scoped to the resolved project.
        recent = conn.execute(
            "SELECT date, message FROM activity_log WHERE project_id = ? ORDER BY id DESC LIMIT 3",
            (project_id,),
        ).fetchall()
        if recent:
            lines.append("Recent:")
            for act in recent:
                lines.append(f"  {act['date']} | {act['message']}")

        # Always append a compact per-project rollup across every real project.
        projects = list_projects(conn)
        if projects:
            lines.append("")
            lines.append("Projects:")
            for p in projects:
                c = _project_task_counts(conn, p["id"])
                lines.append(
                    f"  {p['slug']}: phase={p['phase']} "
                    f"todo={c.get('todo', 0)} working={c.get('working', 0)} "
                    f"testing={c.get('testing', 0)} done={c.get('done', 0)}"
                )

        return _echo(slug, "\n".join(lines))
    finally:
        conn.close()


def handle_update_project_status(args: dict) -> list[TextContent]:
    conn = get_db()
    try:
        # Phase/blockers now live on the projects row. Resolve target (default
        # active, honors explicit project=).
        project_id, slug = resolve_project(conn, args)

        updates = {}
        if "phase" in args:
            updates["phase"] = args["phase"]
        if "blockers" in args:
            updates["blockers"] = args["blockers"]

        if not updates:
            return _echo(slug, "No fields to update.")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE projects SET {set_clause} WHERE id = ?",
            (*updates.values(), project_id),
        )
        conn.commit()
        return _echo(slug, f"Project status updated: {updates}")
    finally:
        conn.close()


# --- Entry Point ---


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
