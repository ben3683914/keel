#!/usr/bin/env python3
"""Documentation Manager MCP Server.

Provides tools for context-aware doc loading, doc health checks,
review acknowledgment, constitution management, and ADR replacement.
All routing and health data stored in .claude/claude.db.
"""

import asyncio
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Add shared module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_db, json_dumps, json_loads
from projects import (
    WORKSPACE_ID,
    get_project_by_id,
    project_label,
    resolve_project,
)
from routing import refresh_doc_routing
from slugify import slugify


def get_project_root() -> Path:
    return Path.cwd()


def project_echo(slug: str) -> str:
    """Prefix prepended to project-scoped responses (per the echo rule)."""
    return f"[project: {slug}]\n"


def project_const_dir(conn, project_id: int) -> Path:
    """Constitution dir for a project: workspace tier -> docs/constitution;
    project tier -> <project.path>/docs/constitution. An empty path (the
    workspace project) collapses the join back to root/docs/constitution."""
    root = get_project_root()
    row = get_project_by_id(conn, project_id)
    rel = (row["path"] if row else "") or ""
    rel = rel.replace("\\", "/").strip("/")
    base = root / rel if rel else root
    return base / "docs" / "constitution"


def load_project_config() -> dict:
    path = get_project_root() / ".claude" / "project-config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def count_lines(file_path: Path) -> int:
    try:
        return len(file_path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


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


def score_doc(row, query: str, source_files: list[str]) -> float:
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

    for source_path in source_files:
        normalized = source_path.replace("\\", "/")
        for mapped_path in json_loads(row["source_paths"]):
            if normalized.startswith(mapped_path) or mapped_path in normalized:
                score += 2.0
                break

    return score


# --- Constitution Compact Injection ---


def get_compact_constitution(
    active_project_id: int, categories: list[str] | None = None
) -> str:
    """Return compact constitution summary for injection into tool responses.

    Two-tier: the effective set for a project is its own rows plus the always-on
    workspace tier (project_id IN (active, workspace)). The slug prefix on the
    article label disambiguates the now per-project (repeating) numbers.

    Returns slug/number, category tag, title, and full rule_text. If categories
    is provided, only include articles matching those categories.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT project_id, number, title, category, rule_text FROM constitution "
            "WHERE project_id IN (?, ?) AND status IN ('ratified', 'amended') "
            "ORDER BY project_id, number",
            (active_project_id, WORKSPACE_ID),
        ).fetchall()

        if not rows:
            return ""

        filtered = rows
        if categories:
            filtered = [r for r in rows if r["category"] in categories]

        if not filtered:
            return ""

        slug_for = {
            pid: project_label(conn, pid)
            for pid in {r["project_id"] for r in filtered}
        }

        lines = [f"\n---\n**Constitution ({len(filtered)} articles):**\n"]
        for row in filtered:
            cat = row["category"] or "general"
            slug = slug_for[row["project_id"]]
            lines.append(
                f"{slug}/{row['number']:03d} [{cat}] {row['title']} — {row['rule_text']}\n"
            )

        return "\n".join(lines)
    finally:
        conn.close()


# --- Staleness Markers ---


def find_markers(file_path: Path) -> list[str]:
    markers = []
    try:
        content = file_path.read_text(encoding="utf-8")
        for i, line in enumerate(content.splitlines(), 1):
            for pattern in [r"\bTODO\b", r"\bFIXME\b", r"\bHACK\b", r"\bNEEDS DESIGN\b", r"\bPLACEHOLDER\b"]:
                if re.search(pattern, line, re.IGNORECASE):
                    markers.append(f"  Line {i}: {line.strip()[:100]}")
                    break
    except OSError:
        pass
    return markers


# --- Constitution Markdown Generation ---


def generate_article_markdown(row) -> str:
    """Generate markdown content for a single constitution article."""
    status_line = f"{row['status'].title()}"
    if row["ratified_date"]:
        status_line += f" ({row['ratified_date']})"
    elif row["created_date"]:
        status_line += f" ({row['created_date']})"
    if row["status"] == "revoked" and row["revoked_date"]:
        status_line += f" | Revoked: {row['revoked_date']}"

    parts = [
        "> **This file is auto-generated from SQLite. Do not edit directly.**\n"
        "> Use `amend_article` or `revoke_article` to make changes.\n",
        f"# Article {row['number']:03d}: {row['title']}\n",
    ]
    category = row["category"] if "category" in row.keys() else "general"
    parts.append(f"**Category:** {category}\n")
    parts.append(f"## Status\n\n{status_line}\n")
    if row["context"]:
        parts.append(f"## Context\n\n{row['context']}\n")
    parts.append(f"## Rule\n\n{row['rule_text']}\n")
    if row["consequences"]:
        parts.append(f"## Consequences\n\n{row['consequences']}\n")
    if row["enforcement"]:
        parts.append(f"## Enforcement\n\n{row['enforcement']}\n")
    if row["status"] == "revoked" and row["revoked_reason"]:
        parts.append(f"## Revocation Reason\n\n{row['revoked_reason']}\n")

    return "\n".join(parts)


def generate_constitution_index(conn, project_id: int) -> str:
    """Generate the constitution index.md for ONE project's articles."""
    rows = conn.execute(
        "SELECT * FROM constitution WHERE project_id = ? ORDER BY number",
        (project_id,),
    ).fetchall()

    lines = [
        "> **This file is auto-generated from SQLite. Do not edit directly.**\n"
        "> Use `propose_article`, `ratify_article`, `amend_article`, or `revoke_article` to make changes.\n",
        "# Project Constitution\n",
    ]
    if not rows:
        lines.append("No articles yet. Use `propose_article` to create one.\n")
        return "\n".join(lines)

    lines.append("| # | Title | Status | Date |")
    lines.append("|---|-------|--------|------|")
    for row in rows:
        slug = re.sub(r"[^a-z0-9]+", "-", row["title"].lower()).strip("-")
        filename = f"article-{row['number']:03d}-{slug}.md"
        date_str = row["ratified_date"] or row["created_date"]
        lines.append(
            f"| [{row['number']:03d}]({filename}) | {row['title']} | {row['status'].title()} | {date_str} |"
        )

    return "\n".join(lines) + "\n"


def regenerate_constitution_files(conn, project_id: int):
    """Regenerate ONE project's constitution markdown files from SQLite.

    Workspace tier -> docs/constitution; project tier -> <path>/docs/constitution.
    Only the affected project's dir is touched; other projects are untouched."""
    const_dir = project_const_dir(conn, project_id)
    const_dir.mkdir(parents=True, exist_ok=True)

    # Write index (scoped to this project)
    index_content = generate_constitution_index(conn, project_id)
    (const_dir / "index.md").write_text(index_content, encoding="utf-8", newline="\n")

    # Write individual articles for this project
    rows = conn.execute(
        "SELECT * FROM constitution WHERE project_id = ? ORDER BY number",
        (project_id,),
    ).fetchall()
    existing_files = set(f.name for f in const_dir.glob("article-*.md"))
    expected_files = set()

    for row in rows:
        slug = re.sub(r"[^a-z0-9]+", "-", row["title"].lower()).strip("-")
        filename = f"article-{row['number']:03d}-{slug}.md"
        expected_files.add(filename)
        content = generate_article_markdown(row)
        (const_dir / filename).write_text(content, encoding="utf-8", newline="\n")

    # Remove orphaned article files (within this project's dir only)
    for orphan in existing_files - expected_files:
        (const_dir / orphan).unlink(missing_ok=True)


def check_constitution_drift_impl(active_project_id: int) -> list[str]:
    """Compare SQLite articles against markdown files for the effective tier set
    (active project + workspace), each in its own per-project dir. Returns issues.

    Scope is active+workspace (mirrors the routing/health scope and the
    'effective set = project ∪ workspace' framing) rather than every project, so
    a multi-project repo with an as-yet-uncreated sub-project dir is not flagged.
    """
    issues = []

    conn = get_db()
    try:
        tiers = [active_project_id]
        if WORKSPACE_ID not in tiers:
            tiers.append(WORKSPACE_ID)

        for pid in tiers:
            const_dir = project_const_dir(conn, pid)
            slug = project_label(conn, pid)
            rows = conn.execute(
                "SELECT * FROM constitution WHERE project_id = ? ORDER BY number",
                (pid,),
            ).fetchall()

            if not const_dir.exists():
                if rows:
                    issues.append(
                        f"[{slug}] Constitution directory missing but articles exist in DB"
                    )
                continue

            expected_files = set()
            for row in rows:
                fslug = re.sub(r"[^a-z0-9]+", "-", row["title"].lower()).strip("-")
                filename = f"article-{row['number']:03d}-{fslug}.md"
                expected_files.add(filename)
                filepath = const_dir / filename

                if not filepath.exists():
                    issues.append(f"[{slug}] MISSING: {filename} (article {row['number']:03d} exists in DB)")
                else:
                    expected_content = generate_article_markdown(row)
                    actual_content = filepath.read_text(encoding="utf-8")
                    if hashlib.sha256(expected_content.encode()).hexdigest() != hashlib.sha256(actual_content.encode()).hexdigest():
                        issues.append(f"[{slug}] DRIFT: {filename} content differs from DB")

            actual_files = set(f.name for f in const_dir.glob("article-*.md"))
            for extra in actual_files - expected_files:
                issues.append(f"[{slug}] ORPHAN: {extra} exists on disk but not in DB")
    finally:
        conn.close()

    return issues


# --- MCP Server ---

server = Server("docs-manager")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_relevant_docs",
            description=(
                "Find which documentation files are relevant to a task or set of source files. "
                "Uses keyword matching and source path mapping to return ranked results."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "What you're working on",
                    },
                    "source_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Source files being modified",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project slug or id to scope to. Defaults to the active project; results always include the workspace tier.",
                    },
                },
            },
        ),
        Tool(
            name="get_startup_docs",
            description=(
                "Return docs marked for initial session loading (load_at_start=1 in doc_routing). "
                "Returns full inline content of each doc. Call at session start to load system context."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="set_startup_loading",
            description=(
                "Mark a doc or code file for initial session loading (load_at_start flag). "
                "This controls what get_startup_docs returns. Requires user approval."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path in routing table (e.g. 'docs/claude/workflow.md')",
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "true to load at start, false to remove from startup",
                    },
                    "table": {
                        "type": "string",
                        "enum": ["doc", "code"],
                        "description": "Which routing table: doc or code. Default: doc",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project slug or id whose routing entry to toggle. Defaults to the active project.",
                    },
                },
                "required": ["path", "enabled"],
            },
        ),
        Tool(
            name="check_doc_health",
            description=(
                "Check documentation health: oversized docs, staleness markers, "
                "constitution drift, and whether a full audit is due."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project slug or id to check. Defaults to the active project.",
                    },
                },
            },
        ),
        Tool(
            name="refresh_doc_routing",
            description="Scan docs/ and update the doc routing table in SQLite.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="write_doc",
            description=(
                "Write a documentation file and immediately refresh doc routing. "
                "Use this instead of bare Write/Edit when creating new documentation files. "
                "Partial edits to existing docs can still use Edit directly."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path for the doc file (e.g. 'docs/features/auth.md' or 'myproject1/docs/api.md')",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full markdown content to write",
                    },
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="delete_doc",
            description=(
                "Delete a documentation file and immediately refresh doc routing. "
                "Use this instead of bare Bash rm when removing documentation files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path of the doc file to delete (e.g. 'docs/features/old.md')",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="acknowledge_review",
            description=(
                "Mark that documentation has been reviewed for this session. "
                "Requires code_review to be completed first (review order enforcement)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Brief summary of what was reviewed/updated"},
                    "unresolved_issues": {
                        "type": ["integer", "string"],
                        "description": "Number of unresolved documentation issues. Default: 0",
                    },
                },
                "required": ["summary"],
            },
        ),
        Tool(
            name="propose_article",
            description=(
                "Propose a new constitution article. Creates it with status 'proposed'. "
                "Use ratify_article to make it active."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Article title, e.g. 'No ORM Usage'"},
                    "context": {"type": "string", "description": "Why this rule exists"},
                    "rule_text": {"type": "string", "description": "The actual mandate"},
                    "consequences": {"type": "string", "description": "What happens if violated"},
                    "enforcement": {"type": "string", "description": "How Claude should check for violations"},
                    "category": {
                        "type": "string",
                        "enum": ["design", "documentation", "workflow", "collaboration", "general"],
                        "description": "Article category for filtering injection. Default: general",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project slug or id this article belongs to. Defaults to the active project. Numbering is per project.",
                    },
                },
                "required": ["title", "rule_text"],
            },
        ),
        Tool(
            name="ratify_article",
            description="Ratify a proposed constitution article, making it active and enforceable.",
            inputSchema={
                "type": "object",
                "properties": {
                    "number": {"type": "integer", "description": "Article number to ratify"},
                    "project": {
                        "type": "string",
                        "description": "Project slug or id the article belongs to. Defaults to the active project (number is unique only within a project).",
                    },
                },
                "required": ["number"],
            },
        ),
        Tool(
            name="amend_article",
            description=(
                "Amend an existing constitution article. Updates any field(s) you "
                "provide and sets status to 'amended'. Only 'number' is required; "
                "pass any of title/context/rule_text/consequences/enforcement/category "
                "to change just those fields. In the template, an amended article must "
                "be re-affirmed with ratify_article before it will export to the "
                "scaffold or ship in a release."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "number": {"type": "integer", "description": "Article number to amend"},
                    "title": {"type": "string", "description": "Updated title (changing this does NOT change source_id)"},
                    "context": {"type": "string", "description": "Updated context — why this rule exists"},
                    "rule_text": {"type": "string", "description": "Updated rule text — the actual mandate"},
                    "consequences": {"type": "string", "description": "Updated consequences if violated"},
                    "enforcement": {"type": "string", "description": "Updated enforcement — how Claude should check for violations"},
                    "category": {
                        "type": "string",
                        "enum": ["design", "documentation", "workflow", "collaboration", "general"],
                        "description": "Updated category for filtering injection",
                    },
                    "reason": {"type": "string", "description": "Why this change is needed"},
                    "project": {
                        "type": "string",
                        "description": "Project slug or id the article belongs to. Defaults to the active project (number is unique only within a project).",
                    },
                },
                "required": ["number"],
            },
        ),
        Tool(
            name="revoke_article",
            description="Revoke a constitution article with documented reason.",
            inputSchema={
                "type": "object",
                "properties": {
                    "number": {"type": "integer", "description": "Article number to revoke"},
                    "reason": {"type": "string", "description": "Why this article is being revoked"},
                    "project": {
                        "type": "string",
                        "description": "Project slug or id the article belongs to. Defaults to the active project (number is unique only within a project).",
                    },
                },
                "required": ["number", "reason"],
            },
        ),
        Tool(
            name="list_articles",
            description=(
                "List constitution articles. Defaults to the active project plus the "
                "workspace tier; pass project='all' to list every project's articles."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "string",
                        "enum": ["proposed", "ratified", "amended", "revoked"],
                        "description": "Filter by status (optional)",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project slug or id to scope to (default: active + workspace). Use 'all' for every project.",
                    },
                },
            },
        ),
        Tool(
            name="check_constitution_drift",
            description="Compare constitution articles in SQLite against markdown files on disk.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        handlers = {
            "get_relevant_docs": handle_get_relevant_docs,
            "get_startup_docs": handle_get_startup_docs,
            "set_startup_loading": handle_set_startup_loading,
            "check_doc_health": handle_check_doc_health,
            "refresh_doc_routing": handle_refresh_doc_routing,
            "write_doc": handle_write_doc,
            "delete_doc": handle_delete_doc,
            "acknowledge_review": handle_acknowledge_review,
            "propose_article": handle_propose_article,
            "ratify_article": handle_ratify_article,
            "amend_article": handle_amend_article,
            "revoke_article": handle_revoke_article,
            "list_articles": handle_list_articles,
            "check_constitution_drift": handle_check_constitution_drift,
        }
        handler = handlers.get(name)
        if handler:
            return handler(arguments)
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


# --- Tool Handlers ---


def handle_get_relevant_docs(args: dict) -> list[TextContent]:
    task_desc = args.get("task_description", "")
    source_files = args.get("source_files", [])

    if not task_desc and not source_files:
        return [TextContent(type="text", text="Provide a task_description and/or source_files to find relevant docs")]

    conn = get_db()
    try:
        pid, slug = resolve_project(conn, args, source_files=source_files)
        echo = project_echo(slug)

        # Scope to the active/explicit project plus the always-on workspace tier.
        rows = conn.execute(
            "SELECT * FROM doc_routing WHERE project_id IN (?, ?)",
            (pid, WORKSPACE_ID),
        ).fetchall()
        if not rows:
            return [TextContent(type="text", text=echo + "No doc routing data. Run refresh_doc_routing first.")]

        root = get_project_root()
        scored = []
        for row in rows:
            s = score_doc(row, task_desc, source_files)
            if s > 0:
                doc_path = root / row["path"]
                lines = count_lines(doc_path) if doc_path.exists() else 0
                scored.append({"path": row["path"], "score": s, "lines": lines, "exists": doc_path.exists()})

        scored.sort(key=lambda x: x["score"], reverse=True)

        if not scored:
            lines = [f"No docs matched your query. Task: {task_desc}"]
            if source_files:
                lines.append(f"Source files: {', '.join(source_files)}")
            lines.append("\nAvailable docs:")
            for row in rows:
                lines.append(f"  {row['path']}")
            return [TextContent(type="text", text=echo + "\n".join(lines))]

        lines = ["Relevant docs (ranked by relevance):\n"]
        for item in scored:
            status = f"{item['lines']} lines" if item["exists"] else "MISSING"
            lines.append(f"  [{item['score']:.1f}] {item['path']} ({status})")

        top = [s for s in scored if s["score"] >= 1.0 and s["exists"]]
        if top:
            lines.append(f"\nRecommended to read: {', '.join(s['path'] for s in top[:4])}")

        # Inject compact constitution (skip for a minimal-enforcement workspace)
        config = load_project_config()
        enforcement = config.get("enforcement", "") if config else ""
        if enforcement != "minimal":
            compact = get_compact_constitution(
                pid, categories=["documentation", "design", "collaboration"]
            )
            if compact:
                lines.append(compact)

        return [TextContent(type="text", text=echo + "\n".join(lines))]
    finally:
        conn.close()


def handle_get_startup_docs(args: dict) -> list[TextContent]:
    """Return full content of docs marked load_at_start=1."""
    conn = get_db()
    try:
        pid, slug = resolve_project(conn, args)
        echo = project_echo(slug)

        rows = conn.execute(
            "SELECT path FROM doc_routing WHERE load_at_start = 1 AND project_id IN (?, ?) "
            "ORDER BY path",
            (pid, WORKSPACE_ID),
        ).fetchall()

        if not rows:
            return [TextContent(type="text", text=echo + "No docs marked for startup loading. Set load_at_start=1 in doc_routing.")]

        root = get_project_root()
        sections = [f"# Startup Docs ({len(rows)} files)\n"]

        for row in rows:
            doc_path = root / row["path"]
            if not doc_path.exists():
                sections.append(f"## {row['path']}\n\nFILE MISSING\n")
                continue
            try:
                content = doc_path.read_text(encoding="utf-8")
                sections.append(f"## {row['path']}\n\n{content}\n")
            except OSError as e:
                sections.append(f"## {row['path']}\n\nRead error: {e}\n")

        sections.append(
            "## Startup Loading Notes\n\n"
            "If you find a doc or code file that would be valuable to load at every session start, "
            "suggest it to the user via `set_startup_loading`. This requires user approval. "
            "Good candidates: frequently referenced docs, core architecture files, key module interfaces."
        )

        # Inject compact constitution (all categories at startup, skip for scratchpad)
        config = load_project_config()
        mode = config.get("project_mode", "single-purpose") if config else "single-purpose"
        if mode != "scratchpad":
            compact = get_compact_constitution(pid)
            if compact:
                sections.append(compact)

        return [TextContent(type="text", text=echo + "\n---\n".join(sections))]
    finally:
        conn.close()


def handle_set_startup_loading(args: dict) -> list[TextContent]:
    """Toggle load_at_start flag for a doc or code routing entry."""
    path = args["path"]
    enabled = args["enabled"]
    table = args.get("table", "doc")
    table_name = "doc_routing" if table == "doc" else "code_routing"

    conn = get_db()
    try:
        # Resolve from explicit/active only. We do NOT infer from `path`: that
        # would flip the global active pointer as a side effect of a flag toggle,
        # and a workspace doc (no project prefix) would never infer anyway. Instead
        # we look up across the effective tier (active/explicit + workspace) and
        # operate on whichever tier actually owns the row.
        pid, slug = resolve_project(conn, args)
        echo = project_echo(slug)

        # Prefer the active/explicit tier if a path somehow exists in both tiers.
        row = conn.execute(
            f"SELECT project_id FROM {table_name} WHERE project_id IN (?, ?) AND path = ? "
            "ORDER BY (project_id = ?) DESC LIMIT 1",
            (pid, WORKSPACE_ID, path, pid),
        ).fetchone()
        if not row:
            return [TextContent(type="text", text=echo + f"Path not found in {table_name}: {path}")]
        owner_pid = row["project_id"]

        conn.execute(
            f"UPDATE {table_name} SET load_at_start = ? WHERE project_id = ? AND path = ?",
            (1 if enabled else 0, owner_pid, path),
        )
        conn.commit()

        action = "added to" if enabled else "removed from"
        return [TextContent(type="text", text=echo + f"{path} {action} startup loading.")]
    finally:
        conn.close()


def handle_check_doc_health(args: dict) -> list[TextContent]:
    conn = get_db()
    try:
        pid, slug = resolve_project(conn, args)
        echo = project_echo(slug)

        health = conn.execute(
            "SELECT * FROM health_metadata WHERE project_id = ? AND kind = 'doc'", (pid,)
        ).fetchone()
        root = get_project_root()

        size_threshold = health["size_threshold_lines"]
        audit_interval = health["full_audit_interval_days"]
        last_audit_str = health["last_full_audit"]

        try:
            last_audit = datetime.strptime(last_audit_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            last_audit = date(1970, 1, 1)

        days_since_audit = (date.today() - last_audit).days
        full_audit_due = days_since_audit >= audit_interval

        lines = ["# Documentation Health Check\n"]

        # Check doc sizes (active project + workspace tier)
        rows = conn.execute(
            "SELECT * FROM doc_routing WHERE project_id IN (?, ?)", (pid, WORKSPACE_ID)
        ).fetchall()
        oversized = []
        all_docs = []
        for row in rows:
            doc_path = root / row["path"]
            if doc_path.exists():
                lc = count_lines(doc_path)
                all_docs.append((row["path"], lc))
                if lc > size_threshold:
                    oversized.append((row["path"], lc))

        if oversized:
            lines.append(f"## Oversized Docs (>{size_threshold} lines)\n")
            for path, count in oversized:
                lines.append(f"  WARNING: {path} -- {count} lines (consider splitting)")
        else:
            lines.append(f"All docs under {size_threshold} line threshold.")

        # Pending articles (effective tier: active project + workspace)
        proposed = conn.execute(
            "SELECT number, title, rule_text, context, created_date FROM constitution "
            "WHERE status = 'proposed' AND project_id IN (?, ?) ORDER BY project_id, number",
            (pid, WORKSPACE_ID),
        ).fetchall()
        if proposed:
            lines.append(f"\n## ACTION REQUIRED: Pending Articles ({len(proposed)} unratified)\n")
            for row in proposed:
                lines.append(f"  Article {row['number']}: {row['title']} (proposed {row['created_date']})")
                lines.append(f"    Context: {row['context']}")
                lines.append(f"    Rule: {row['rule_text']}")
            lines.append("")
            lines.append("  IMPORTANT: You MUST present pending articles to the user BEFORE")
            lines.append("  moving on to tasks. For each pending article, use AskUserQuestion with the")
            lines.append("  article title as header and options: Ratify, Revoke, Skip for now.")
            lines.append("  Format your presentation with a bold header like:")
            lines.append('  **Pending Article {number} — {title}**')
            lines.append("  Then show the rule text so the user can make an informed decision.")

        # Pending re-affirmation (template authoring only). An 'amended' template
        # article is an un-finalized edit: it will NOT export to the scaffold and a
        # release is blocked until it is re-affirmed or revoked. Downstream consumers
        # are never nudged — there, 'amended' means intentional local divergence that
        # must be preserved, so re-ratifying would strip its divergence protection.
        if load_project_config().get("template_dev") is True:
            amended = conn.execute(
                "SELECT number, title, amended_date FROM constitution "
                "WHERE status = 'amended' AND source_id LIKE 'template:%' "
                "AND project_id IN (?, ?) ORDER BY project_id, number",
                (pid, WORKSPACE_ID),
            ).fetchall()
            if amended:
                lines.append(f"\n## ACTION REQUIRED: Pending Re-affirmation ({len(amended)} amended)\n")
                for row in amended:
                    lines.append(f"  Article {row['number']}: {row['title']} (amended {row['amended_date']})")
                lines.append("")
                lines.append("  These template articles were edited but not re-affirmed. They will")
                lines.append("  NOT export to the scaffold and a release is BLOCKED until each is")
                lines.append("  re-affirmed with ratify_article (or revoked). Present each to the")
                lines.append("  user and ask whether to re-affirm now.")

        # Constitution drift check (active project + workspace tier)
        drift_issues = check_constitution_drift_impl(pid)
        if drift_issues:
            lines.append(f"\n## Constitution Drift ({len(drift_issues)} issues)\n")
            for issue in drift_issues:
                lines.append(f"  {issue}")
        else:
            lines.append("\nConstitution: no drift detected.")

        # Full audit
        if full_audit_due:
            lines.append(f"\n## Full Audit (last: {last_audit_str}, {days_since_audit} days ago)\n")
            for row in rows:
                doc_path = root / row["path"]
                if not doc_path.exists():
                    lines.append(f"  MISSING: {row['path']}")
                    continue
                markers = find_markers(doc_path)
                if markers:
                    lines.append(f"  {row['path']} -- {len(markers)} markers:")
                    for m in markers[:5]:
                        lines.append(f"    {m}")

            routing_changes = refresh_doc_routing()
            if routing_changes:
                lines.append(f"\n## Routing Updated ({len(routing_changes)} changes)\n")
                for change in routing_changes:
                    lines.append(f"  {change}")

            conn.execute(
                "UPDATE health_metadata SET last_full_audit = ? WHERE project_id = ? AND kind = 'doc'",
                (date.today().isoformat(), pid),
            )
            conn.commit()
            lines.append(f"\nFull audit complete. Next in {audit_interval} days.")
        else:
            days_until = audit_interval - days_since_audit
            lines.append(f"\nNext full audit in {days_until} days (last: {last_audit_str}).")

        total_lines = sum(c for _, c in all_docs)
        lines.append(f"\nTotal: {len(all_docs)} docs, {total_lines} lines")

        return [TextContent(type="text", text=echo + "\n".join(lines))]
    finally:
        conn.close()


def handle_refresh_doc_routing(args: dict) -> list[TextContent]:
    changes = refresh_doc_routing()
    if changes:
        lines = [f"Updated doc routing ({len(changes)} changes):\n"]
        for change in changes:
            lines.append(f"  {change}")
        return [TextContent(type="text", text="\n".join(lines))]
    return [TextContent(type="text", text="Doc routing is up to date. No changes needed.")]


def handle_write_doc(args: dict) -> list[TextContent]:
    rel_path = args.get("path", "").replace("\\", "/").lstrip("/")
    content = args.get("content", "")
    if not rel_path:
        return [TextContent(type="text", text="path is required")]
    if not rel_path.endswith(".md"):
        return [TextContent(type="text", text="path must end in .md")]

    root = get_project_root()
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")

    changes = refresh_doc_routing()
    kw_msg = ""
    for c in changes:
        if rel_path in c and c.startswith(("ADDED:", "AUTO_KEYWORDS:")):
            kw_msg = f" ({c})"
            break

    return [TextContent(type="text", text=f"Written: {rel_path}{kw_msg}")]


def handle_delete_doc(args: dict) -> list[TextContent]:
    rel_path = args.get("path", "").replace("\\", "/").lstrip("/")
    if not rel_path:
        return [TextContent(type="text", text="path is required")]

    root = get_project_root()
    target = root / rel_path
    if not target.exists():
        return [TextContent(type="text", text=f"File not found: {rel_path}")]

    target.unlink()
    refresh_doc_routing()
    return [TextContent(type="text", text=f"Deleted: {rel_path}")]


def handle_acknowledge_review(args: dict) -> list[TextContent]:
    summary = args.get("summary", "Review completed")
    try:
        unresolved = int(args.get("unresolved_issues", 0))
    except (TypeError, ValueError):
        unresolved = 0

    conn = get_db()
    try:
        pid, slug = resolve_project(conn, args)
        echo = project_echo(slug)
        # Check review order: code_review must be done first (this project's pipeline)
        review = conn.execute(
            "SELECT * FROM review_order WHERE project_id = ?", (pid,)
        ).fetchone()
        if not review or not review["code_review_done"]:
            return [TextContent(
                type="text",
                text=echo + (
                    "Cannot acknowledge doc review: code_review has not been completed yet. "
                    "Review order: code_review -> doc_review -> security_review -> tests. "
                    "Complete the code review first using acknowledge_code_review."
                ),
            )]

        conn.execute(
            "UPDATE review_order SET doc_review_done = ?, doc_review_unresolved = ? WHERE project_id = ?",
            (1 if unresolved == 0 else 0, unresolved, pid),
        )
        conn.commit()

        if unresolved > 0:
            return [TextContent(
                type="text",
                text=echo + f"Doc review acknowledged with {unresolved} unresolved issue(s): {summary}\n"
                     "WARNING: Fix the issues and call acknowledge_review again with unresolved_issues=0.",
            )]

        # Check for [Pending] markers in feature docs
        root = get_project_root()
        pending_docs = []
        features_dir = root / "docs" / "features"
        if features_dir.exists():
            for md_file in features_dir.rglob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    if re.search(r"\[Pending\]", content, re.IGNORECASE):
                        rel = str(md_file.relative_to(root)).replace("\\", "/")
                        pending_docs.append(rel)
                except OSError:
                    pass

        msg = echo + f"Documentation review acknowledged: {summary}"
        if pending_docs:
            msg += (
                f"\n\nNOTE: {len(pending_docs)} feature doc(s) have [Pending] sections. "
                "Consider creating tasks to complete them:\n"
            )
            for doc in pending_docs:
                msg += f"  - {doc}\n"

        return [TextContent(type="text", text=msg)]
    finally:
        conn.close()


# --- Constitution Handlers ---


def handle_propose_article(args: dict) -> list[TextContent]:
    title = args["title"]
    rule_text = args["rule_text"]
    context = args.get("context", "")
    consequences = args.get("consequences", "")
    enforcement = args.get("enforcement", "")
    category = args.get("category", "general")
    today = date.today().isoformat()

    config = load_project_config()
    base_slug = slugify(title)

    conn = get_db()
    try:
        pid, slug_label = resolve_project(conn, args)
        echo = project_echo(slug_label)

        # source_id namespace. Workspace tier keeps the cross-repo identity scheme:
        # template_dev=true ships as template:<slug>, else project:<slug>. The
        # project tier embeds the project slug (project:<slug>:<article-slug>) so
        # the source_id stays globally unique across tiers; the unique index is
        # (project_id, source_id) but the slug prefix also keeps it readable.
        if pid == WORKSPACE_ID:
            prefix = "template" if config.get("template_dev") is True else "project"
        else:
            prefix = f"project:{slug_label}"

        # Next number is PER PROJECT.
        row = conn.execute(
            "SELECT MAX(number) as max_num FROM constitution WHERE project_id = ?", (pid,)
        ).fetchone()
        next_num = (row["max_num"] or 0) + 1

        # Resolve slug collisions PER PROJECT (unique index is (project_id, source_id)).
        slug = base_slug
        suffix = 2
        while conn.execute(
            "SELECT 1 FROM constitution WHERE project_id = ? AND source_id = ?",
            (pid, f"{prefix}:{slug}"),
        ).fetchone():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        source_id = f"{prefix}:{slug}"

        conn.execute(
            "INSERT INTO constitution (project_id, number, title, status, category, context, rule_text, "
            "consequences, enforcement, created_date, source_id) "
            "VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?)",
            (pid, next_num, title, category, context, rule_text, consequences,
             enforcement, today, source_id),
        )
        conn.commit()
        regenerate_constitution_files(conn, pid)

        return [TextContent(
            type="text",
            text=echo + f"Proposed Article {slug_label}/{next_num:03d}: {title}\n"
                 f"Status: PROPOSED (not yet enforceable)\n"
                 f"Source ID: {source_id}\n"
                 f"Use ratify_article to make it active.",
        )]
    finally:
        conn.close()


def handle_ratify_article(args: dict) -> list[TextContent]:
    number = args["number"]
    today = date.today().isoformat()

    conn = get_db()
    try:
        pid, slug_label = resolve_project(conn, args)
        echo = project_echo(slug_label)

        row = conn.execute(
            "SELECT * FROM constitution WHERE project_id = ? AND number = ?", (pid, number)
        ).fetchone()
        if not row:
            return [TextContent(type="text", text=echo + f"Article {slug_label}/{number:03d} not found")]
        if row["status"] == "ratified":
            return [TextContent(type="text", text=echo + f"Article {slug_label}/{number:03d} is already ratified")]

        conn.execute(
            "UPDATE constitution SET status = 'ratified', ratified_date = ? "
            "WHERE project_id = ? AND number = ?",
            (today, pid, number),
        )
        conn.commit()
        regenerate_constitution_files(conn, pid)

        return [TextContent(
            type="text",
            text=echo + f"RATIFIED Article {slug_label}/{number:03d}: {row['title']}\n"
                 f"This rule is now active and enforceable.",
        )]
    finally:
        conn.close()


def handle_amend_article(args: dict) -> list[TextContent]:
    number = args["number"]
    reason = args.get("reason", "")
    today = date.today().isoformat()

    # Only the fields actually supplied are updated — everything else is left
    # untouched. This lets a caller amend just the enforcement text, or just the
    # title, without having to restate the whole article.
    editable = ["title", "context", "rule_text", "consequences", "enforcement", "category"]
    updates = {field: args[field] for field in editable if field in args and args[field] is not None}

    if not updates:
        return [TextContent(
            type="text",
            text="No fields to amend. Pass at least one of: "
                 "title, context, rule_text, consequences, enforcement, category.",
        )]

    conn = get_db()
    try:
        pid, slug_label = resolve_project(conn, args)
        echo = project_echo(slug_label)

        row = conn.execute(
            "SELECT * FROM constitution WHERE project_id = ? AND number = ?", (pid, number)
        ).fetchone()
        if not row:
            return [TextContent(type="text", text=echo + f"Article {slug_label}/{number:03d} not found")]

        set_clause = ", ".join(f"{field} = ?" for field in updates)
        params = list(updates.values()) + [today, pid, number]
        conn.execute(
            f"UPDATE constitution SET {set_clause}, status = 'amended', amended_date = ? "
            "WHERE project_id = ? AND number = ?",
            params,
        )
        conn.commit()
        regenerate_constitution_files(conn, pid)

        changed = ", ".join(updates.keys())
        msg = echo + f"AMENDED Article {slug_label}/{number:03d}: {row['title']}"
        msg += f"\nFields changed: {changed}"
        if reason:
            msg += f"\nReason: {reason}"
        msg += (
            "\n\nStatus is now 'amended'. To make this the canonical rule again "
            "(and let it export to the scaffold / ship in a release), re-affirm it "
            "with ratify_article. Until then it is treated as an un-finalized edit."
        )
        return [TextContent(type="text", text=msg)]
    finally:
        conn.close()


def handle_revoke_article(args: dict) -> list[TextContent]:
    number = args["number"]
    reason = args["reason"]
    today = date.today().isoformat()

    conn = get_db()
    try:
        pid, slug_label = resolve_project(conn, args)
        echo = project_echo(slug_label)

        row = conn.execute(
            "SELECT * FROM constitution WHERE project_id = ? AND number = ?", (pid, number)
        ).fetchone()
        if not row:
            return [TextContent(type="text", text=echo + f"Article {slug_label}/{number:03d} not found")]

        conn.execute(
            "UPDATE constitution SET status = 'revoked', revoked_date = ?, revoked_reason = ? "
            "WHERE project_id = ? AND number = ?",
            (today, reason, pid, number),
        )
        conn.commit()
        regenerate_constitution_files(conn, pid)

        return [TextContent(
            type="text",
            text=echo + f"REVOKED Article {slug_label}/{number:03d}: {row['title']}\nReason: {reason}",
        )]
    finally:
        conn.close()


def handle_list_articles(args: dict) -> list[TextContent]:
    status_filter = args.get("status_filter")
    # 'all' is a deliberate no-op for resolve_project, so special-case it here to
    # drop the project_id scope entirely rather than route through resolution.
    show_all = args.get("project") == "all"

    conn = get_db()
    try:
        echo = ""
        conditions: list[str] = []
        params: list = []

        if not show_all:
            pid, slug_label = resolve_project(conn, args)
            echo = project_echo(slug_label)
            conditions.append("project_id IN (?, ?)")
            params.extend([pid, WORKSPACE_ID])

        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM constitution {where} ORDER BY project_id, number", params
        ).fetchall()

        if not rows:
            filter_msg = f" with status '{status_filter}'" if status_filter else ""
            return [TextContent(type="text", text=echo + f"No constitution articles found{filter_msg}.")]

        slug_for = {
            pid_: project_label(conn, pid_) for pid_ in {r["project_id"] for r in rows}
        }

        lines = ["# Project Constitution\n"]
        lines.append("| Article | Title | Status | Date |")
        lines.append("|---------|-------|--------|------|")
        for row in rows:
            date_str = row["ratified_date"] or row["created_date"]
            label = f"{slug_for[row['project_id']]}/{row['number']:03d}"
            lines.append(f"| {label} | {row['title']} | {row['status'].title()} | {date_str} |")

        return [TextContent(type="text", text=echo + "\n".join(lines))]
    finally:
        conn.close()


def handle_check_constitution_drift(args: dict) -> list[TextContent]:
    conn = get_db()
    try:
        pid, slug = resolve_project(conn, args)
    finally:
        conn.close()
    echo = project_echo(slug)
    issues = check_constitution_drift_impl(pid)
    if not issues:
        return [TextContent(type="text", text=echo + "Constitution: no drift detected. All files match SQLite.")]
    lines = [f"Constitution drift detected ({len(issues)} issues):\n"]
    for issue in issues:
        lines.append(f"  {issue}")
    lines.append("\nRun propose/ratify/amend tools to fix, or regenerate files from SQLite.")
    return [TextContent(type="text", text=echo + "\n".join(lines))]


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
