#!/usr/bin/env python3
"""PreToolUse hook: blocks task-lifecycle and onboarding MCP mutations while
the template repo has `template_dev: true` in project-config.json.

See docs/features/template-dev-guardrail.md for the design.

Fail-open: if config is missing or malformed, pass the tool call through.
"""

import json
import sys
from pathlib import Path

BLOCKED_TOOLS = frozenset({
    "mcp__task-manager__create_task",
    "mcp__task-manager__start_task",
    "mcp__task-manager__move_to_testing",
    "mcp__task-manager__move_to_todo",
    "mcp__task-manager__validate_task",
    "mcp__task-manager__update_task",
    "mcp__task-manager__freeze_task",
    "mcp__task-manager__unfreeze_task",
    "mcp__task-manager__trash_task",
    "mcp__task-manager__log_activity",
    "mcp__task-manager__report_security_findings",
    "mcp__task-manager__update_onboarding",
    "mcp__task-manager__update_project_status",
    "mcp__code-manager__acknowledge_code_review",
    "mcp__code-manager__acknowledge_security_review",
    "mcp__docs-manager__acknowledge_review",
    "mcp__test-manager__acknowledge_tests",
})


def find_project_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".claude").is_dir():
            return parent
    return cwd


def is_template_dev() -> bool:
    config_path = find_project_root() / ".claude" / "project-config.json"
    if not config_path.exists():
        return False
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"template_dev_guard: could not read project-config.json ({e}); passing through", file=sys.stderr)
        return False
    return config.get("template_dev") is True


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name not in BLOCKED_TOOLS:
        sys.exit(0)

    if not is_template_dev():
        sys.exit(0)

    print(
        f"Template-dev mode — {tool_name} is disabled to prevent session state "
        "from leaking into the template's tracked claude.db. Run onboarding "
        "(which commits a real project setup and runs assemble.py) to disable this "
        "guard, or use /prep-release before tagging.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
