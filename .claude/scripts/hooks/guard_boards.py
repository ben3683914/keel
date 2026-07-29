#!/usr/bin/env python3
"""PreToolUse hook: blocks direct edits to auto-generated files.

Protects board-snapshot.md and constitution article files since they
are generated from SQLite. Forces use of MCP tools for all state changes.

Only runs in project mode (workspace_scope == "project").
Exit code 2 blocks the tool use and sends stderr to Claude as feedback.
"""

import json
import sys
from fnmatch import fnmatch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from db import get_project_root  # noqa: E402


def load_project_config(cwd):
    config_path = Path(cwd) / ".claude" / "project-config.json"
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


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


PROTECTED_PATTERNS = [
    "project/board-snapshot.md",
    "docs/constitution/*.md",
    # Per-project constitution dirs (<project-path>/docs/constitution/*.md).
    "*/docs/constitution/*.md",
]


def is_protected(rel_path):
    normalized = rel_path.replace("\\", "/")
    for pattern in PROTECTED_PATTERNS:
        if fnmatch(normalized, pattern):
            return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    # Resolve UP to the workspace root: a drifted shell cwd would otherwise make
    # load_project_config miss the config (disabling the guard) and skew the
    # relative path used to match PROTECTED_PATTERNS. get_project_root only does
    # path math -- it never opens or creates a DB.
    cwd = get_project_root(data.get("cwd"))

    if not file_path:
        sys.exit(0)

    project_config = load_project_config(cwd)
    if not project_config:
        sys.exit(0)

    if project_config.get("workspace_scope") != "project":
        sys.exit(0)

    rel = make_relative(file_path, cwd)

    if is_protected(rel):
        print(
            "BLOCKED: This file is auto-generated from SQLite and should not be "
            "edited directly. Use the appropriate MCP tools instead:\n"
            "  Board snapshot: auto-generated at session end from task data\n"
            "  Constitution articles: use propose_article, ratify_article, "
            "amend_article, revoke_article\n"
            "  Tasks: use create_task, start_task, update_task, etc.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
