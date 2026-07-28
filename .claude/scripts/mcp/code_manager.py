#!/usr/bin/env python3
"""Code Manager MCP Server.

Provides language-agnostic tools for code quality monitoring, module routing,
health checks, and review acknowledgment. All routing and review data stored
in .claude/claude.db.
"""

import asyncio
import re
import sys
from datetime import date, datetime
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Add shared module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_db, json_loads
from routing import refresh_code_routing
from projects import resolve_project, WORKSPACE_ID


def get_project_root() -> Path:
    return Path.cwd()


def echo(slug: str, text: str) -> list[TextContent]:
    """Wrap a project-scoped success response with the `[project: <slug>]` echo."""
    return [TextContent(type="text", text=f"[project: {slug}]\n{text}")]


# --- Keyword Matching ---


def _keyword_in_query(kw: str, query: str) -> str | None:
    if not kw:
        return None
    if len(kw) <= 3:
        if re.search(rf"\b{re.escape(kw)}\b", query):
            return "exact"
        return None
    if re.search(rf"\b{re.escape(kw)}\b", query):
        return "exact"
    if kw in query:
        return "partial"
    return None


def score_module(row, query: str, source_files: list[str]) -> float:
    score = 0.0
    query_lower = query.lower()

    curated = json_loads(row["keywords"])
    auto = json_loads(row["auto_keywords"])

    for keyword in curated:
        match = _keyword_in_query(keyword.lower(), query_lower)
        if match == "exact":
            score += 1.5
        elif match == "partial":
            score += 0.75

    for keyword in auto:
        match = _keyword_in_query(keyword.lower(), query_lower)
        if match == "exact":
            score += 0.8
        elif match == "partial":
            score += 0.3

    mod_path = row["path"]
    for source_file in source_files:
        normalized = source_file.replace("\\", "/")
        if normalized == mod_path:
            score += 5.0
        elif mod_path in normalized or normalized in mod_path:
            score += 2.0

    return score


# --- Stale Tasks (now from SQLite) ---


def find_stale_tasks(project_id: int) -> list[str]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT task_id, title, updated_date FROM tasks "
            "WHERE status = 'working' AND project_id = ?",
            (project_id,),
        ).fetchall()

        stale = []
        today = date.today()
        for row in rows:
            try:
                updated = datetime.strptime(row["updated_date"], "%Y-%m-%d").date()
                days = (today - updated).days
                if days >= 7:
                    stale.append(f"{row['task_id']}: {row['title']} ({days} days since last update)")
            except ValueError:
                stale.append(f"{row['task_id']}: {row['title']} (unknown last update)")

        return stale
    finally:
        conn.close()


# --- MCP Server ---

server = Server("code-manager")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_relevant_modules",
            description=(
                "Find which source modules are relevant to modified files or a task. "
                "Returns each file's description, line count, and keywords."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Source files being modified",
                    },
                    "task_description": {
                        "type": "string",
                        "description": "What you're working on (optional)",
                    },
                    "project": {
                        "type": "string",
                        "description": (
                            "Project slug to scope to. Optional; defaults to the active "
                            "project (or inferred from source_files). The workspace's own "
                            "modules are always included."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="check_code_health",
            description="Check code quality: file sizes, stale tasks, periodic audit.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project slug to scope to. Optional; defaults to the active project.",
                    },
                },
            },
        ),
        Tool(
            name="refresh_code_routing",
            description="Scan source files and update code routing table in SQLite.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="delete_module",
            description=(
                "Delete a source file and immediately refresh code routing. "
                "Use this instead of bare Bash rm when removing source files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path of the source file to delete (e.g. 'src/auth/login.py')",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="acknowledge_code_review",
            description=(
                "Mark code review completed. First step in review order (always allowed). "
                "Records in SQLite review_order table."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Brief summary of code review findings"},
                    "critical_issues": {
                        "type": ["integer", "string"],
                        "description": "Number of critical issues (blocks if > 0). Default: 0",
                    },
                    "advisory_issues": {
                        "type": ["integer", "string"],
                        "description": "Number of advisory issues (logged, don't block). Default: 0",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project slug to scope to. Optional; defaults to the active project.",
                    },
                },
                "required": ["summary"],
            },
        ),
        Tool(
            name="acknowledge_security_review",
            description=(
                "Mark security review completed. "
                "Requires doc_review to be completed first (review order enforcement)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Brief summary of security review findings"},
                    "security_issues": {
                        "type": ["integer", "string"],
                        "description": "Number of unresolved security issues. Default: 0",
                    },
                    "deferred": {
                        "type": "boolean",
                        "description": "Set to true when issues are deferred to security board.",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project slug to scope to. Optional; defaults to the active project.",
                    },
                },
                "required": ["summary"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        handlers = {
            "get_relevant_modules": handle_get_relevant_modules,
            "check_code_health": handle_check_code_health,
            "refresh_code_routing": handle_refresh_code_routing,
            "delete_module": handle_delete_module,
            "acknowledge_code_review": handle_acknowledge_code_review,
            "acknowledge_security_review": handle_acknowledge_security_review,
        }
        handler = handlers.get(name)
        if handler:
            return handler(arguments)
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


# --- Tool Handlers ---


def handle_get_relevant_modules(args: dict) -> list[TextContent]:
    source_files = args.get("source_files", [])
    task_desc = args.get("task_description", "")

    if not source_files and not task_desc:
        return [TextContent(type="text", text="Provide source_files and/or task_description.")]

    conn = get_db()
    try:
        # Scope to the active project plus the always-shared workspace modules.
        pid, slug = resolve_project(conn, args, source_files=source_files)
        rows = conn.execute(
            "SELECT * FROM code_routing WHERE project_id IN (?, ?)",
            (pid, WORKSPACE_ID),
        ).fetchall()
        if not rows:
            return echo(slug, "No code routing data. Run refresh_code_routing first.")

        scored = []
        for row in rows:
            s = score_module(row, task_desc, source_files)
            if s > 0:
                scored.append({"path": row["path"], "score": s, "description": row["description"], "line_count": row["line_count"]})

        scored.sort(key=lambda x: x["score"], reverse=True)

        if not scored:
            lines = ["No modules matched your query."]
            if task_desc:
                lines.append(f"  Task: {task_desc}")
            return echo(slug, "\n".join(lines))

        lines = ["# Relevant Modules\n"]
        for item in scored[:15]:
            desc = item["description"] or "(no description)"
            lines.append(f"## [{item['score']:.1f}] {item['path']}")
            lines.append(f"  Description: {desc}")
            lines.append(f"  Lines: {item['line_count']}")
            lines.append("")

        return echo(slug, "\n".join(lines))
    finally:
        conn.close()


def handle_check_code_health(args: dict) -> list[TextContent]:
    conn = get_db()
    try:
        pid, slug = resolve_project(conn, args)
        health = conn.execute(
            "SELECT * FROM health_metadata WHERE project_id = ? AND kind = 'code'",
            (pid,),
        ).fetchone()

        size_threshold = health["size_threshold_lines"]
        audit_interval = health["full_audit_interval_days"]
        last_audit_str = health["last_full_audit"]

        try:
            last_audit = datetime.strptime(last_audit_str, "%Y-%m-%d").date()
        except ValueError:
            last_audit = date(1970, 1, 1)

        days_since_audit = (date.today() - last_audit).days
        full_audit_due = days_since_audit >= audit_interval

        lines = ["# Code Health Check\n"]

        # Routing rows for the active project plus the shared workspace.
        rows = conn.execute(
            "SELECT * FROM code_routing WHERE project_id IN (?, ?)",
            (pid, WORKSPACE_ID),
        ).fetchall()
        if not rows:
            lines.append("No code routing data. Run `refresh_code_routing` to generate it.\n")
            return echo(slug, "\n".join(lines))

        # Size check
        critical_files = []
        warn_files = []
        warn_threshold = size_threshold  # 1500 default
        mid_threshold = int(size_threshold * 0.67)  # ~1000

        for row in rows:
            lc = row["line_count"]
            if lc > warn_threshold:
                critical_files.append((row["path"], lc))
            elif lc > mid_threshold:
                warn_files.append((row["path"], lc))

        if critical_files:
            lines.append(f"## CRITICAL: Files Over {warn_threshold} Lines\n")
            for path, count in critical_files:
                lines.append(f"  {path} -- {count} lines")
            lines.append("")

        if warn_files:
            lines.append(f"## WARNING: Files Over {mid_threshold} Lines\n")
            for path, count in warn_files:
                lines.append(f"  {path} -- {count} lines")
            lines.append("")

        if not critical_files and not warn_files:
            lines.append(f"All files under {mid_threshold} line threshold.\n")

        # Stale tasks (active project only)
        stale_tasks = find_stale_tasks(pid)
        if stale_tasks:
            lines.append("## Stale Tasks (7+ days, no activity)\n")
            for task in stale_tasks:
                lines.append(f"  {task}")
            lines.append("")

        # Full audit
        if full_audit_due:
            lines.append(f"## Full Audit (last: {last_audit_str}, {days_since_audit} days ago)\n")
            routing_changes = refresh_code_routing()
            if routing_changes:
                lines.append(f"### Routing Updated ({len(routing_changes)} changes)\n")
                for change in routing_changes[:20]:
                    lines.append(f"  {change}")
                if len(routing_changes) > 20:
                    lines.append(f"  ... and {len(routing_changes) - 20} more")
                lines.append("")

            conn.execute(
                "UPDATE health_metadata SET last_full_audit = ? "
                "WHERE project_id = ? AND kind = 'code'",
                (date.today().isoformat(), pid),
            )
            conn.commit()
            lines.append(f"Full audit complete. Next in {audit_interval} days.")
        else:
            days_until = audit_interval - days_since_audit
            lines.append(f"Next full audit in {days_until} day(s) (last: {last_audit_str}).")

        total_lines = sum(row["line_count"] for row in rows)
        lines.append(f"\nTotal: {len(rows)} source files, {total_lines:,} lines")

        return echo(slug, "\n".join(lines))
    finally:
        conn.close()


def handle_delete_module(args: dict) -> list[TextContent]:
    rel_path = args.get("path", "").replace("\\", "/").lstrip("/")
    if not rel_path:
        return [TextContent(type="text", text="path is required")]

    root = get_project_root()
    target = root / rel_path
    if not target.exists():
        return [TextContent(type="text", text=f"File not found: {rel_path}")]

    target.unlink()
    refresh_code_routing()
    return [TextContent(type="text", text=f"Deleted: {rel_path}")]


def handle_refresh_code_routing(args: dict) -> list[TextContent]:
    changes = refresh_code_routing()
    if changes:
        lines = [f"Updated code routing ({len(changes)} changes):\n"]
        for change in changes:
            lines.append(f"  {change}")
        return [TextContent(type="text", text="\n".join(lines))]
    return [TextContent(type="text", text="Code routing is up to date. No changes needed.")]


def handle_acknowledge_code_review(args: dict) -> list[TextContent]:
    summary = args.get("summary", "Code review completed")
    try:
        critical = int(args.get("critical_issues", 0))
    except (TypeError, ValueError):
        critical = 0
    try:
        advisory = int(args.get("advisory_issues", 0))
    except (TypeError, ValueError):
        advisory = 0

    conn = get_db()
    try:
        pid, slug = resolve_project(conn, args)
        # Code review is always allowed (first step)
        conn.execute(
            "UPDATE review_order SET code_review_done = ?, code_review_critical = ?, "
            "code_review_advisory = ? WHERE project_id = ?",
            (1 if critical == 0 else 0, critical, advisory, pid),
        )
        conn.commit()

        if critical > 0:
            return echo(
                slug,
                f"Code review acknowledged with {critical} CRITICAL issue(s): {summary}\n"
                "WARNING: Fix the issues and call acknowledge_code_review again with critical_issues=0.",
            )

        msg = f"Code review acknowledged: {summary}"
        if advisory > 0:
            msg += f" ({advisory} advisory issue(s) logged, not blocking)"
        return echo(slug, msg)
    finally:
        conn.close()


def handle_acknowledge_security_review(args: dict) -> list[TextContent]:
    summary = args.get("summary", "Security review completed")
    try:
        security_issues = int(args.get("security_issues", 0))
    except (TypeError, ValueError):
        security_issues = 0
    deferred = bool(args.get("deferred", False))

    conn = get_db()
    try:
        pid, slug = resolve_project(conn, args)
        # Check review order: doc_review must be done first (for this project)
        review = conn.execute(
            "SELECT * FROM review_order WHERE project_id = ?", (pid,)
        ).fetchone()
        if not review or not review["doc_review_done"]:
            return echo(
                slug,
                "Cannot acknowledge security review: doc_review has not been completed yet. "
                "Review order: code_review -> doc_review -> security_review -> tests. "
                "Complete the doc review first using acknowledge_review.",
            )

        done = 1 if (security_issues == 0 or deferred) else 0
        conn.execute(
            "UPDATE review_order SET security_review_done = ?, security_review_issues = ?, "
            "security_review_deferred = ? WHERE project_id = ?",
            (done, security_issues, 1 if deferred else 0, pid),
        )
        conn.commit()

        if security_issues > 0 and deferred:
            return echo(
                slug,
                f"Security review acknowledged with {security_issues} issue(s) deferred: {summary}\n"
                "Ensure report_security_findings was called to record them.",
            )
        if security_issues > 0:
            return echo(
                slug,
                f"Security review acknowledged with {security_issues} issue(s): {summary}\n"
                "WARNING: Security issues should be resolved before committing.\n"
                "Tip: Defer with acknowledge_security_review deferred=true after "
                "recording them with report_security_findings.",
            )
        return echo(slug, f"Security review acknowledged: {summary}")
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
