#!/usr/bin/env python3
"""Test Manager MCP Server.

Provides tools for test discovery, execution, and acknowledgment.
Language-agnostic: reads test conventions and commands from
.claude/project-config.json. Supports monorepo layouts.
"""

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Add shared module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_db
from projects import (
    WORKSPACE_SLUG,
    get_project_by_slug,
    project_for_path,
    project_label,
    resolve_project,
)
from routing import get_source_config


def get_project_root() -> Path:
    return Path.cwd()


def load_project_config() -> dict:
    path = get_project_root() / ".claude" / "project-config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def config_entry_for_slug(slug: str | None) -> dict | None:
    """The config `projects[]` entry whose slug matches, or None (workspace /
    unknown slug). Projects-first config uses `projects[]`, not `sub_projects[]`."""
    if not slug:
        return None
    config = load_project_config()
    for entry in config.get("projects", []) or []:
        if entry.get("slug") == slug:
            return entry
    return None


def echo(slug: str | None, text: str) -> str:
    """Prepend the `[project: <slug>]` scope line to a response body.

    Workspace-scoped responses are NOT prefixed (the workspace pseudo-project is
    the fallback, not a real board); pass slug None or 'workspace' to suppress.
    """
    if slug and slug != WORKSPACE_SLUG:
        return f"[project: {slug}]\n{text}"
    return text


def get_test_convention() -> dict:
    config = load_project_config()
    return config.get("test_convention", {
        "source_dir": "src",
        "test_dir": "tests",
        "suffix": ".test",
        "extension": ".ts",
    })


def get_skip_patterns() -> list[str]:
    config = load_project_config()
    return config.get("skip_test_patterns", ["*.d.ts", "index.*"])


def get_test_command(project: str | dict | None = None) -> str:
    """Resolve the test command for a project.

    `project` is a project SLUG (or an already-resolved config `projects[]`
    entry). The per-project `test_command` wins; absent it, the top-level
    `test_command` is used; absent that, the default.
    """
    config = load_project_config()
    entry = project if isinstance(project, dict) else config_entry_for_slug(project)
    if entry and entry.get("test_command"):
        return entry["test_command"]
    return config.get("test_command", "npm test")


def source_to_test_path(source_path: str) -> str:
    """Convert a source file path to its expected test file path using config conventions."""
    convention = get_test_convention()
    source_dir = convention.get("source_dir", "src")
    test_dir = convention.get("test_dir", "tests")
    suffix = convention.get("suffix", ".test")
    extension = convention.get("extension", ".ts")

    normalized = source_path.replace("\\", "/")

    # Strip source_dir prefix
    if normalized.startswith(f"{source_dir}/"):
        relative = normalized[len(source_dir) + 1:]
    else:
        relative = normalized

    # Remove existing extension and add test suffix + extension
    # Handle multi-part extensions like .test.ts
    base = re.sub(r"\.[^/]+$", "", relative)

    return f"{test_dir}/{base}{suffix}{extension}"


def should_skip(source_path: str) -> str | None:
    """Check if a source file should be skipped for testing."""
    normalized = source_path.replace("\\", "/")
    convention = get_test_convention()
    source_dir = convention.get("source_dir", "src")
    skip_patterns = get_skip_patterns()

    # Only test files under source_dir
    if not normalized.startswith(f"{source_dir}/"):
        return f"Skipped: {normalized} (not under {source_dir}/)"

    filename = normalized.split("/")[-1]

    # Check against skip patterns
    for pattern in skip_patterns:
        # Simple glob matching
        if pattern.startswith("*"):
            if filename.endswith(pattern[1:]):
                return f"Skipped: {normalized} (matches skip pattern: {pattern})"
        elif pattern.endswith(".*"):
            base = pattern[:-2]
            file_base = filename.rsplit(".", 1)[0] if "." in filename else filename
            if file_base == base:
                return f"Skipped: {normalized} (matches skip pattern: {pattern})"
        elif filename == pattern:
            return f"Skipped: {normalized} (matches skip pattern: {pattern})"

    return None


def detect_project_for_file(source_path: str) -> str | None:
    """Slug of the declared project a file belongs to, or None.

    Projects-first: attribution is a longest-path-prefix match over the DB
    `projects` registry (workspace, path='', is never matched). Returns the
    project's slug so callers can resolve cwd/test_command from it.
    """
    conn = get_db()
    try:
        pid = project_for_path(conn, source_path)
        return project_label(conn, pid) if pid else None
    finally:
        conn.close()


# --- MCP Server ---

server = Server("test-manager")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="find_untested_files",
            description=(
                "Find which source files lack corresponding test files. "
                "Uses test conventions from project-config.json to map source files to test paths."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of modified source file paths",
                    },
                    "project": {
                        "type": "string",
                        "description": (
                            "Project SLUG to scope coverage to (uses that project's "
                            "source config). Defaults to the active project, else the workspace."
                        ),
                    },
                },
                "required": ["source_files"],
            },
        ),
        Tool(
            name="run_tests",
            description=(
                "Run tests using the configured test command from project-config.json. "
                "Returns raw stdout/stderr output."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific test files to run (appended to test command)",
                    },
                    "all": {
                        "type": "boolean",
                        "description": "Run all tests (default: false)",
                    },
                    "project": {
                        "type": "string",
                        "description": (
                            "Project SLUG (uses that project's test_command and runs in "
                            "its path). Auto-detected from `files` when omitted."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="acknowledge_tests",
            description=(
                "Mark that tests have been run for this session. "
                "Requires security_review to be completed first (review order enforcement). "
                "Records completion in SQLite review_order table."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of test results",
                    },
                    "failures": {
                        "type": ["integer", "string"],
                        "description": "Number of test failures. Default: 0",
                    },
                    "project": {
                        "type": "string",
                        "description": (
                            "Project SLUG whose review_order row to update. "
                            "Defaults to the active project, else the workspace."
                        ),
                    },
                },
                "required": ["summary"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "find_untested_files":
            return handle_find_untested_files(arguments)
        elif name == "run_tests":
            return await handle_run_tests(arguments)
        elif name == "acknowledge_tests":
            return handle_acknowledge_tests(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]


# --- Tool Handlers ---


def handle_find_untested_files(args: dict) -> list[TextContent]:
    source_files = args.get("source_files", [])
    if not source_files:
        return [TextContent(type="text", text="No source files provided")]

    # Resolve the project to scope coverage to: explicit slug > active > workspace.
    conn = get_db()
    try:
        _pid, slug = resolve_project(conn, args, set_active_on_infer=False)
    finally:
        conn.close()
    is_workspace = slug == "workspace"
    entry = config_entry_for_slug(None if is_workspace else slug)
    roots, exts, _excludes = get_source_config(entry)
    roots_norm = [r.replace("\\", "/").strip("/") for r in roots if r not in (None, "")]
    ext_set = set(exts)
    # Files arrive repo-relative (e.g. 'apps/web/src/auth.ts'); a declared
    # project's source_roots are relative to its own path, so strip that prefix
    # before matching. Workspace has no prefix.
    proj_prefix = ""
    if entry is not None:
        proj_prefix = (entry.get("path") or "").replace("\\", "/").strip("/")

    def project_relative(rel: str) -> str | None:
        """Repo-relative path -> project-relative path if it belongs to this
        project's source config (under its subtree, beneath a source_root,
        matching its extensions); else None. roots=['.'] / [] => any root in
        subtree. The relative form is what the test-path convention expects,
        since source_dir is project-relative ('src', not 'apps/web/src')."""
        # Restrict to the project's subtree, then make the path project-relative.
        if proj_prefix:
            if rel == proj_prefix:
                sub = ""
            elif rel.startswith(proj_prefix + "/"):
                sub = rel[len(proj_prefix) + 1:]
            else:
                return None  # file lives outside this project's path
        else:
            sub = rel
        last = sub.split("/")[-1]
        ext = ("." + last.rsplit(".", 1)[-1]) if "." in last else ""
        if ext_set and ext not in ext_set:
            return None
        if not roots_norm or "." in roots_norm:
            return sub
        if any(sub == r or sub.startswith(r + "/") for r in roots_norm):
            return sub
        return None

    def repo_path(sub: str) -> str:
        """Re-prefix a project-relative path back to repo-relative for display."""
        return f"{proj_prefix}/{sub}" if proj_prefix else sub

    root = get_project_root()
    tested = []
    untested = []
    skipped = []

    for source_path in source_files:
        normalized = source_path.replace("\\", "/")

        rel = project_relative(normalized)
        if rel is None:
            skipped.append(f"Skipped: {normalized} (outside project '{slug}' source config)")
            continue

        # Map within the project's own tree (convention's source_dir is
        # project-relative), then re-prefix results back to repo-relative.
        skip_reason = should_skip(rel)
        if skip_reason:
            skipped.append(skip_reason.replace(rel, normalized))
            continue

        test_rel = source_to_test_path(rel)
        test_path = repo_path(test_rel)
        full_test_path = root / test_path

        if full_test_path.exists():
            tested.append({"source": normalized, "test": test_path})
        else:
            untested.append({"source": normalized, "expectedTest": test_path})

    lines = ["# Test Coverage Report\n"]

    if tested:
        lines.append(f"## Tested ({len(tested)} files)")
        for item in tested:
            lines.append(f"  {item['source']} -> {item['test']}")

    if untested:
        lines.append(f"\n## Untested ({len(untested)} files)")
        for item in untested:
            lines.append(f"  {item['source']} -> {item['expectedTest']} (MISSING)")

    if skipped:
        lines.append(f"\n## Skipped ({len(skipped)} files)")
        for reason in skipped:
            lines.append(f"  {reason}")

    if not untested:
        lines.append("\nAll testable source files have corresponding tests.")
    else:
        lines.append(f"\n{len(untested)} file(s) need tests.")

    return [TextContent(type="text", text=echo(slug, "\n".join(lines)))]


def resolve_run_target(args: dict) -> dict:
    """Pure resolution for run_tests (no subprocess, no pointer mutation).

    Maps the run request to a concrete target. `project` is a SLUG; when absent
    it is auto-detected from `files` (only when they all sit in ONE project).
    The cwd comes from the resolved project's `path` (slug -> projects row ->
    path), NOT the slug: `web` -> `apps/web`; the workspace (path '') -> root.

    Returns {slug, cwd, test_cmd, cmd_parts}. `slug` is None when the run is
    workspace-scoped (no project resolved), which suppresses the echo line.
    """
    files = args.get("files", [])
    run_all = args.get("all", False)
    slug = args.get("project") or None
    root = get_project_root()

    # Auto-detect from files when no explicit slug (single-project runs only).
    if not slug and files:
        detected = {p for p in (detect_project_for_file(f) for f in files) if p}
        if len(detected) == 1:
            slug = detected.pop()

    # Resolve slug -> projects row (for cwd path) + config entry (for command).
    entry = config_entry_for_slug(slug)
    rel_path = ""
    if slug:
        conn = get_db()
        try:
            row = get_project_by_slug(conn, slug)
        finally:
            conn.close()
        if row is not None:
            rel_path = (row["path"] or "").replace("\\", "/").strip("/")
        elif entry is not None:
            rel_path = (entry.get("path") or "").replace("\\", "/").strip("/")

    cwd = str(root / rel_path) if rel_path else str(root)
    test_cmd = get_test_command(entry if entry is not None else slug)

    # Split the test command (handles "npm test", "pytest", "cargo test", etc.).
    cmd_parts = test_cmd.split()
    if files and not run_all:
        cmd_parts.extend(files)

    return {"slug": slug, "cwd": cwd, "test_cmd": test_cmd, "cmd_parts": cmd_parts}


async def handle_run_tests(args: dict) -> list[TextContent]:
    target = resolve_run_target(args)
    project = target["slug"]
    cwd = target["cwd"]
    test_cmd = target["test_cmd"]
    cmd_parts = target["cmd_parts"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=120
            )
        except asyncio.TimeoutError:
            proc.kill()
            return [TextContent(type="text", text=echo(project, "Test run timed out after 120 seconds"))]

        result_stdout = stdout_bytes.decode("utf-8", errors="replace")
        result_stderr = stderr_bytes.decode("utf-8", errors="replace")
        result_returncode = proc.returncode
    except FileNotFoundError:
        return [
            TextContent(
                type="text",
                text=echo(
                    project,
                    f"Test command not found: {test_cmd}\nEnsure dependencies are installed.",
                ),
            )
        ]

    # Return raw output
    lines = ["# Test Results\n"]
    lines.append(f"Command: {test_cmd}")
    lines.append(f"Exit code: {result_returncode}")

    if result_stdout:
        lines.append(f"\n## Output\n```\n{result_stdout[:5000]}\n```")
    if result_stderr:
        lines.append(f"\n## Errors\n```\n{result_stderr[:3000]}\n```")

    if result_returncode == 0:
        lines.append("\nTests passed.")
    else:
        lines.append(f"\nTests failed (exit code {result_returncode}).")

    return [TextContent(type="text", text=echo(project, "\n".join(lines)))]


def handle_acknowledge_tests(args: dict) -> list[TextContent]:
    summary = args.get("summary", "Tests completed")
    try:
        failures = int(args.get("failures", 0))
    except (TypeError, ValueError):
        failures = 0

    # Resolve the project whose review_order row this acknowledges:
    # explicit `project=` slug > active pointer > workspace. No file inference.
    conn = get_db()
    try:
        pid, slug = resolve_project(conn, args, set_active_on_infer=False)

        # Check review order: this project's security_review must be done first.
        review = conn.execute(
            "SELECT * FROM review_order WHERE project_id = ?", (pid,)
        ).fetchone()
        if not review or not review["security_review_done"]:
            return [
                TextContent(
                    type="text",
                    text=echo(
                        slug,
                        "Cannot acknowledge tests: security_review has not been completed yet. "
                        "Review order: code_review -> doc_review -> security_review -> tests. "
                        "Complete the security review first using acknowledge_security_review.",
                    ),
                )
            ]

        # Record test completion on this project's row.
        conn.execute(
            "UPDATE review_order SET tests_done = ?, tests_failures = ? WHERE project_id = ?",
            (1 if failures == 0 else 0, failures, pid),
        )
        conn.commit()
    finally:
        conn.close()

    if failures > 0:
        return [
            TextContent(
                type="text",
                text=echo(
                    slug,
                    f"Tests acknowledged with {failures} failure(s): {summary}\n"
                    f"WARNING: Test failures should be addressed before completing the task.",
                ),
            )
        ]
    return [
        TextContent(
            type="text",
            text=echo(slug, f"Tests acknowledged: {summary}"),
        )
    ]


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
