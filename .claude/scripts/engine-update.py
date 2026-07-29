"""Engine update script for template-based projects.

Allows projects created from a template to receive engine-level updates
(hooks, MCP servers, skills, agents) without overwriting project-specific
content (constitution, architecture, config, tasks).

All output is JSON for machine consumption by the /patch skill.

Usage:
    python .claude/scripts/engine-update.py --status
    python .claude/scripts/engine-update.py --dry-run --source <path>
    python .claude/scripts/engine-update.py --source <path> --categories engine,engine_docs --yes
"""

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared DB import
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent / "shared"))
from db import get_db, json_loads, json_dumps

# ---------------------------------------------------------------------------
# Project root (two levels up from this script)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Version manifest
# ---------------------------------------------------------------------------

# Each entry describes one version bump. Add new versions at the end.
# When you release a template update, add an entry here describing what changed.
VERSIONS = [
    # Example (uncomment and modify for first real update):
    # {
    #     "version": "1.1.0",
    #     "description": "Description of changes",
    #     "migrations": [],  # list of migration keys from MIGRATIONS dict
    #     "changes": {
    #         "engine": [
    #             {"action": "overwrite", "path": ".claude/scripts/hooks/commit_gate.py"},
    #         ],
    #         "engine_docs": [
    #             {"action": "overwrite", "path": "docs/claude/hooks.md"},
    #         ],
    #         "hybrid": [
    #             {"action": "merge_json", "path": ".claude/settings.json", "strategy": "deep_merge_hooks"},
    #         ],
    #     },
    # },

    {
        "version": "1.1.0",
        "description": "Engine versioning, push skill, inspect/status fixes",
        "migrations": ["add_table_template_meta"],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
                {"action": "overwrite", "path": ".claude/scripts/shared/db.py"},
                {"action": "overwrite", "path": ".claude/scripts/shared/git_push.py"},
                {"action": "overwrite", "path": ".claude/scripts/shared/inspect_db.py"},
                {"action": "overwrite", "path": ".claude/scripts/shared/patch_builder.py"},
                {"action": "overwrite", "path": ".claude/skills/inspect/SKILL.md"},
                {"action": "add", "path": ".claude/skills/push/SKILL.md"},
                {"action": "add", "path": ".claude/skills/release-engine/SKILL.md"},
                {"action": "add", "path": ".claude/skills/update-engine/SKILL.md"},
                {"action": "overwrite", "path": "setup.bat"},
            ],
            "engine_docs": [
            ],
            "hybrid": [
                {"action": "merge_json", "path": ".claude/settings.json", "strategy": "deep_merge_hooks"},
                {"action": "merge_section", "path": "CLAUDE.md", "section": "## Session Start"},
                {"action": "merge_section", "path": "docs/guides/setup.md", "section": "## Getting Started"},
            ],
        },
    },

    {
        "version": "1.1.1",
        "description": "Fix merge_section heading match and categories arg parsing",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
                {"action": "overwrite", "path": ".claude/scripts/shared/patch_builder.py"},
            ],
            "hybrid": [
                {"action": "merge_section", "path": "CLAUDE.md", "section": "## Session Start"},
                {"action": "merge_section", "path": "docs/guides/setup.md", "section": "## Getting Started"},
            ],
        },
    },

    {
        "version": "1.1.2",
        "description": "Add clean worktree guard before applying updates",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
            ],
        },
    },

    {
        "version": "1.2.0",
        "description": "Rename propose-rule to propose-amendment, surface pending amendments in health check",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/mcp/docs_manager.py"},
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
                {"action": "add", "path": ".claude/skills/propose-amendment/SKILL.md"},
                {"action": "delete", "path": ".claude/skills/propose-rule/SKILL.md"},
            ],
            "hybrid": [
                {"action": "merge_section", "path": "CLAUDE.md", "section": "## Skills"},
            ],
        },
    },

    {
        "version": "1.2.1",
        "description": "Worktree guard excludes claude.db, shows dirty file list",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
            ],
        },
    },

    {
        "version": "1.2.2",
        "description": "Worktree guard ignores untracked files",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
            ],
        },
    },

    {
        "version": "1.3.0",
        "description": "Surface pending amendments at session start with full article text",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/mcp/docs_manager.py"},
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
            ],
            "hybrid": [
                {"action": "merge_section", "path": "CLAUDE.md", "section": "## Session Start"},
            ],
        },
    },

    {
        "version": "1.3.1",
        "description": "Fix start-workspace.bat not launching VSCode, add classification",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": "start-workspace.bat"},
                {"action": "overwrite", "path": ".claude/scripts/shared/patch_builder.py"},
            ],
        },
    },

    {
        "version": "1.3.2",
        "description": "Fix extension install redirect parse error in start-workspace.bat",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": "start-workspace.bat"},
            ],
        },
    },

    {
        "version": "1.3.3",
        "description": "Fix extension install parsing with PowerShell JSON reader",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": "start-workspace.bat"},
            ],
        },
    },

    {
        "version": "1.4.0",
        "description": "Auto-trust workspace in VSCode, add_missing and remove_keys merge strategies",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
            ],
            "hybrid": [
                {"action": "merge_json", "path": ".vscode/settings.json", "strategy": "add_missing"},
            ],
        },
    },

    {
        "version": "1.4.1",
        "description": "Allow cd && git commands in permissions",
        "migrations": [],
        "changes": {
            "hybrid": [
                {"action": "merge_json", "path": ".claude/settings.json", "strategy": "deep_merge_hooks"},
            ],
        },
    },

    {
        "version": "1.4.2",
        "description": "Support JSONC comments in merge_json for .vscode/settings.json",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
            ],
            "hybrid": [
                {"action": "merge_json", "path": ".vscode/settings.json", "strategy": "add_missing"},
            ],
        },
    },

    {
        "version": "1.4.3",
        "description": "Fix start-workspace.bat cmd window staying open after VSCode launch",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": "start-workspace.bat"},
            ],
        },
    },

    {
        "version": "1.5.0",
        "description": "Project modes, scaffolds assembly, template-dev guardrail, source_roots/extensions/excludes triad, constitution propagation (Article 011)",
        "migrations": ["add_source_id_to_constitution"],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/engine-update.py"},
                {"action": "add", "path": ".claude/scripts/assemble.py"},
                {"action": "add", "path": ".claude/scripts/reset_for_distribution.py"},
                {"action": "overwrite", "path": ".claude/scripts/shared/db.py"},
                {"action": "add", "path": ".claude/scripts/shared/routing.py"},
                {"action": "overwrite", "path": ".claude/scripts/shared/patch_builder.py"},
                {"action": "add", "path": ".claude/scripts/shared/slugify.py"},
                {"action": "add", "path": ".claude/scripts/shared/constitution_export.py"},
                {"action": "overwrite", "path": ".claude/scripts/mcp/code_manager.py"},
                {"action": "overwrite", "path": ".claude/scripts/mcp/docs_manager.py"},
                {"action": "overwrite", "path": ".claude/scripts/mcp/task_manager.py"},
                {"action": "overwrite", "path": ".claude/scripts/mcp/test_manager.py"},
                {"action": "overwrite", "path": ".claude/scripts/hooks/cleanup_boards.py"},
                {"action": "overwrite", "path": ".claude/scripts/hooks/commit_gate.py"},
                {"action": "add", "path": ".claude/scripts/hooks/commit_quality.py"},
                {"action": "overwrite", "path": ".claude/scripts/hooks/session_gate.py"},
                {"action": "add", "path": ".claude/scripts/hooks/template_dev_guard.py"},
                {"action": "overwrite", "path": ".claude/scripts/hooks/track_modifications.py"},
                {"action": "add", "path": ".claude/skills/add-project/SKILL.md"},
                {"action": "add", "path": ".claude/skills/prep-release/SKILL.md"},
                {"action": "delete", "path": ".claude/skills/clean-slate/SKILL.md"},
                {"action": "delete", "path": ".claude/skills/update-manifest/SKILL.md"},
                {"action": "add", "path": ".claude/scaffolds/agent-teams.md"},
                {"action": "add", "path": ".claude/scaffolds/base.md"},
                {"action": "add", "path": ".claude/scaffolds/doc-map.md"},
                {"action": "add", "path": ".claude/scaffolds/instructions-project.md"},
                {"action": "add", "path": ".claude/scaffolds/instructions-scratchpad.md"},
                {"action": "add", "path": ".claude/scaffolds/mode-header-project.md"},
                {"action": "add", "path": ".claude/scaffolds/mode-header-scratchpad.md"},
                {"action": "add", "path": ".claude/scaffolds/session-start-base.md"},
                {"action": "add", "path": ".claude/scaffolds/session-start-project.md"},
                {"action": "add", "path": ".claude/scaffolds/skills-project.md"},
                {"action": "add", "path": ".claude/scaffolds/skills-scratchpad.md"},
                {"action": "add", "path": ".claude/scaffolds/tutorial.md"},
                {"action": "add", "path": ".claude/scaffolds/settings/base.json"},
                {"action": "add", "path": ".claude/scaffolds/settings/hooks-enforcement.json"},
                {"action": "add", "path": ".claude/scaffolds/settings/mcp-servers.json"},
            ],
            "engine_docs": [
                {"action": "overwrite", "path": "docs/claude/hooks.md"},
                {"action": "overwrite", "path": "docs/claude/mcp-tools.md"},
                {"action": "overwrite", "path": "docs/claude/workflow.md"},
            ],
            "hybrid": [
                {"action": "merge_json", "path": ".claude/settings.json", "strategy": "deep_merge_hooks"},
                {"action": "merge_json", "path": ".claude/doc-enforcement.json", "strategy": "deep_merge_rules"},
                {"action": "merge_section", "path": "CLAUDE.md", "section": "## Session Start"},
                {"action": "merge_section", "path": "CLAUDE.md", "section": "## AI Agent Instructions"},
                {"action": "merge_section", "path": "CLAUDE.md", "section": "## Architecture Snapshot"},
            ],
            "constitution": [
                {"action": "apply_constitution_scaffold", "path": ".claude/scaffolds/constitution.json"},
            ],
        },
    },

    {
        "version": "1.5.1",
        "description": "Rename /status skill to /project-status to avoid collision with built-in Claude Code /status",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "delete", "path": ".claude/skills/status/SKILL.md"},
                {"action": "add", "path": ".claude/skills/project-status/SKILL.md"},
                {"action": "overwrite", "path": ".claude/scaffolds/skills-project.md"},
                {"action": "overwrite", "path": ".claude/scaffolds/skills-scratchpad.md"},
            ],
            "hybrid": [
                {"action": "merge_section", "path": "CLAUDE.md", "section": "## Skills"},
            ],
        },
    },

    {
        "version": "1.6.0",
        "description": "Multi-field amend_article with re-affirm flow and release-time gate, patch_builder most-specific classification fix, and constitution content fixes (Articles 002/004/005/006)",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/mcp/docs_manager.py"},
                {"action": "overwrite", "path": ".claude/scripts/shared/constitution_export.py"},
                {"action": "overwrite", "path": ".claude/scripts/shared/patch_builder.py"},
                {"action": "overwrite", "path": ".claude/scripts/reset_for_distribution.py"},
                {"action": "overwrite", "path": ".claude/skills/prep-release/SKILL.md"},
                {"action": "overwrite", "path": ".claude/skills/propose-amendment/SKILL.md"},
            ],
            "engine_docs": [
                {"action": "overwrite", "path": "docs/claude/mcp-tools.md"},
            ],
            "constitution": [
                {"action": "apply_constitution_scaffold", "path": ".claude/scaffolds/constitution.json"},
            ],
        },
    },

    {
        "version": "1.6.1",
        "description": "Push tooling carries annotated release tags (git_push --follow-tags/--tags); release-engine tags releases and syncs version sources",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/shared/git_push.py"},
                {"action": "overwrite", "path": ".claude/skills/push/SKILL.md"},
                {"action": "overwrite", "path": ".claude/skills/release-engine/SKILL.md"},
            ],
        },
    },

    {
        "version": "1.6.2",
        "description": "patch_builder scan baselines on the last release tag so committed-but-unreleased changes are caught; release-engine step 0 prompts to run /prep-release first",
        "migrations": [],
        "changes": {
            "engine": [
                {"action": "overwrite", "path": ".claude/scripts/shared/patch_builder.py"},
                {"action": "overwrite", "path": ".claude/skills/release-engine/SKILL.md"},
            ],
        },
    },

    {
        "version": "2.0.0",
        "description": "v2.0.0 projects-first rewrite: single project = projects[] of length 1; full per-project scoping (boards, status, reviews, health, two-tier constitution); workspace-global active project; /document-project skill; review-pipeline + engine fixes. BREAKING DB schema, no migration -- pre-2.0 installs must re-clone, not in-place upgrade.",
        "migrations": [],
        "changes": {
            "engine": [
                {"path": ".claude/agents/code-reviewer.md", "action": "overwrite"},
                {"path": ".claude/agents/docs-reviewer.md", "action": "overwrite"},
                {"path": ".claude/agents/security-reviewer.md", "action": "overwrite"},
                {"path": ".claude/agents/test-runner.md", "action": "overwrite"},
                {"path": ".claude/scaffolds/base.md", "action": "add"},
                {"path": ".claude/scaffolds/instructions-project.md", "action": "add"},
                {"path": ".claude/scaffolds/mode-header-project.md", "action": "add"},
                {"path": ".claude/scaffolds/skills-project.md", "action": "add"},
                {"path": ".claude/scaffolds/tutorial.md", "action": "add"},
                {"path": ".claude/scripts/assemble.py", "action": "overwrite"},
                {"path": ".claude/scripts/engine-update.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/cleanup_boards.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/commit_gate.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/guard_boards.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/session_gate.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/template_dev_guard.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/track_modifications.py", "action": "overwrite"},
                {"path": ".claude/scripts/mcp/code_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/mcp/docs_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/mcp/task_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/mcp/test_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/reset_for_distribution.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/db.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/inspect_db.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/patch_builder.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/projects.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/routing.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_assemble.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_code_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_docs_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_hooks.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_routing.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_schema.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_task_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_test_manager.py", "action": "overwrite"},
                {"path": ".claude/skills/add-project/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/board/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/document-project/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/health/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/inspect/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/project-status/SKILL.md", "action": "overwrite"},
            ],
            "engine_docs": [
                {"path": "docs/claude/hooks.md", "action": "overwrite"},
                {"path": "docs/claude/mcp-tools.md", "action": "overwrite"},
                {"path": "docs/claude/workflow.md", "action": "overwrite"},
            ],
            "constitution": [
                {"path": ".claude/scaffolds/constitution.json", "action": "apply_constitution_scaffold"},
            ],
            "hybrid": [
                {"path": ".claude/doc-enforcement.json", "action": "merge_json", "strategy": "deep_merge_rules"},
                {"path": ".claude/settings.json", "action": "merge_json", "strategy": "deep_merge_hooks"},
                {"path": "CLAUDE.md", "action": "merge_section", "section": "## Architecture Snapshot"},
                {"path": "CLAUDE.md", "action": "merge_section", "section": "## AI Agent Instructions"},
            ],
        },
    },

    {
        "version": "2.0.1",
        "description": "v2.0.1 fix: engine-update JSONC comment stripper is now string-aware -- glob patterns containing /* or */ (e.g. \"**/*.pyc\", \"**/bin/Debug\" in .vscode/settings.json merges) are no longer mangled by the block-comment regex. Adds a regression test.",
        "migrations": [],
        "changes": {
            "engine": [
                {"path": ".claude/scripts/engine-update.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_engine_update.py", "action": "overwrite"},
            ],
            "constitution": [
                {"path": ".claude/scaffolds/constitution.json", "action": "apply_constitution_scaffold"},
            ],
        },
    },

    {
        "version": "2.1.0",
        "description": "commit guidance: stage claude.db + prep-release invocable",
        "migrations": [],
        "changes": {
            "engine": [
                {"path": ".claude/skills/prep-release/SKILL.md", "action": "overwrite"},
            ],
            "engine_docs": [
                {"path": "docs/claude/workflow.md", "action": "overwrite"},
            ],
            "hybrid": [
                {"action": "merge_section", "path": "CLAUDE.md", "section": "## AI Agent Instructions"},
            ],
        },
    },

    {
        "version": "2.5.0",
        "description": "v2.5.0 projects-first workspace: every project lives in its own ./<slug>/ folder as a real projects[] row (no more single/scratch special cases), existing-codebase onboarding via /document-project, /tutorial skill, /constitution replaces /propose-amendment, and Linux/WSL/macOS setup.sh replaces the removed Windows setup.bat. Also hardens workspace-root resolution so a drifted cwd can no longer fork a stray claude.db. Two fixes every install needs: setup.sh now pins 'mcp>=1.9,<2' (mcp 2.0 removed the decorator API all four MCP servers are built on, so an unpinned install left every server dead at import) and verifies by loading a real server module instead of just importing Server, which passed on a broken install; and path matching in the hooks and routing now retries with both sides resolved, so a workspace under a symlink (macOS /var, a symlinked home or code dir) no longer silently fails to attribute files to projects or fire the enforcement gates.",
        "migrations": [],
        "changes": {
            "engine": [
                {"path": ".claude/scaffolds/base.md", "action": "overwrite"},
                {"path": ".claude/scaffolds/instructions-project.md", "action": "overwrite"},
                {"path": ".claude/scaffolds/session-start-base.md", "action": "overwrite"},
                {"path": ".claude/scaffolds/session-start-project.md", "action": "overwrite"},
                {"path": ".claude/scaffolds/settings/base.json", "action": "overwrite"},
                {"path": ".claude/scaffolds/settings/hooks-enforcement.json", "action": "overwrite"},
                {"path": ".claude/scaffolds/skills-project.md", "action": "overwrite"},
                {"path": ".claude/scaffolds/skills-scratchpad.md", "action": "overwrite"},
                {"path": ".claude/scaffolds/tutorial.md", "action": "overwrite"},
                {"path": ".claude/scripts/assemble.py", "action": "overwrite"},
                {"path": ".claude/scripts/engine-update.py", "action": "overwrite"},
                {"path": ".claude/scripts/new_project.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/cleanup_boards.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/commit_gate.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/commit_quality.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/guard_boards.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/session_gate.py", "action": "overwrite"},
                {"path": ".claude/scripts/hooks/track_modifications.py", "action": "overwrite"},
                {"path": ".claude/scripts/mcp/docs_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/constitution_export.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/db.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/git_push.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/patch_builder.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/projects.py", "action": "overwrite"},
                {"path": ".claude/scripts/shared/routing.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_assemble.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_code_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_docs_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_engine_update.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_hooks.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_new_project.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_routing.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_schema.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_task_manager.py", "action": "overwrite"},
                {"path": ".claude/scripts/tests/test_test_manager.py", "action": "overwrite"},
                {"path": ".claude/skills/add-project/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/constitution/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/document-project/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/inspect/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/prep-release/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/project-status/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/push/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/release-engine/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/tutorial/SKILL.md", "action": "overwrite"},
                {"path": ".claude/skills/update-engine/SKILL.md", "action": "overwrite"},
                {"path": ".mcp.json", "action": "overwrite"},
                {"path": "setup.sh", "action": "overwrite"},
                {"path": "setup.bat", "action": "delete"},
            ],
            "engine_docs": [
                {"path": "docs/claude/hooks.md", "action": "overwrite"},
                {"path": "docs/claude/mcp-tools.md", "action": "overwrite"},
                {"path": "docs/claude/workflow.md", "action": "overwrite"},
            ],
            "hybrid": [
                {"path": ".claude/doc-enforcement.json", "action": "merge_json", "strategy": "deep_merge_rules"},
                {"path": ".claude/settings.json", "action": "merge_json", "strategy": "deep_merge_hooks"},
                {"path": ".gitignore", "action": "merge_append"},
                {"path": "CLAUDE.md", "action": "merge_section", "section": "## Session Start"},
                {"path": "CLAUDE.md", "action": "merge_section", "section": "## Skills"},
                {"path": "docs/guides/setup.md", "action": "merge_section", "section": "## Getting Started"},
                {"path": "docs/guides/setup.md", "action": "merge_section", "section": "## Python Virtual Environment"},
            ],
            "constitution": [
                {"path": ".claude/scaffolds/constitution.json", "action": "apply_constitution_scaffold"},
            ],
        },
    },
]

# Each migration is idempotent SQL. Key is referenced by version entries.
MIGRATIONS = {
    # Example:
    # "add_column_tasks_labels": "ALTER TABLE tasks ADD COLUMN labels TEXT DEFAULT '';",

    "add_table_template_meta": """CREATE TABLE IF NOT EXISTS template_meta (id INTEGER PRIMARY KEY CHECK (id = 1), template_version TEXT NOT NULL DEFAULT '1.0.0', last_updated TEXT DEFAULT '', update_history TEXT DEFAULT '[]'); INSERT OR IGNORE INTO template_meta (id, template_version) VALUES (1, '1.0.0');""",

    # Add cross-repo identity column to constitution. ALTER TABLE has no
    # IF NOT EXISTS; the apply loop treats "duplicate column" as idempotent
    # success so re-running the migration is safe.
    "add_source_id_to_constitution": """ALTER TABLE constitution ADD COLUMN source_id TEXT DEFAULT NULL; CREATE UNIQUE INDEX IF NOT EXISTS idx_constitution_source_id ON constitution(source_id);""",
}

# ---------------------------------------------------------------------------
# Semver helpers
# ---------------------------------------------------------------------------


def parse_version(v: str) -> tuple[int, ...]:
    """Parse a semver string into a tuple of ints."""
    return tuple(int(x) for x in v.split("."))


def version_gt(a: str, b: str) -> bool:
    """Return True if version a is strictly greater than version b."""
    return parse_version(a) > parse_version(b)


# ---------------------------------------------------------------------------
# JSON output helpers
# ---------------------------------------------------------------------------


def emit(obj: dict, exit_code: int = 0) -> None:
    """Print a JSON object to stdout and exit."""
    print(json.dumps(obj, indent=2))
    sys.exit(exit_code)


def emit_error(message: str) -> None:
    """Print a JSON error and exit with code 1."""
    emit({"error": message}, exit_code=1)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def read_meta(conn: sqlite3.Connection) -> dict:
    """Read the template_meta singleton row."""
    row = conn.execute("SELECT * FROM template_meta WHERE id = 1").fetchone()
    return {
        "version": row["template_version"],
        "last_updated": row["last_updated"],
        "history": json_loads(row["update_history"]),
    }


def write_meta(conn: sqlite3.Connection, version: str, history_entry: dict) -> None:
    """Update template_meta after a successful version apply."""
    row = conn.execute("SELECT update_history FROM template_meta WHERE id = 1").fetchone()
    history = json_loads(row["update_history"])
    history.append(history_entry)
    today = date.today().isoformat()
    conn.execute(
        "UPDATE template_meta SET template_version = ?, last_updated = ?, update_history = ? WHERE id = 1",
        (version, today, json_dumps(history)),
    )
    conn.commit()


def update_project_config(version: str) -> None:
    """Update template_version in .claude/project-config.json if it exists."""
    config_path = PROJECT_ROOT / ".claude" / "project-config.json"
    if not config_path.exists():
        return
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["template_version"] = version
        config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    except (json.JSONDecodeError, OSError):
        pass  # non-fatal


# ---------------------------------------------------------------------------
# File action handlers
# ---------------------------------------------------------------------------


def action_overwrite(source_root: Path, target_root: Path, change: dict) -> dict | None:
    """Copy file from source, replacing target entirely."""
    rel = change["path"]
    src = source_root / rel
    dst = target_root / rel
    if not src.exists():
        return {"path": rel, "error": f"Source file not found: {src}"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    return None


def action_add(source_root: Path, target_root: Path, change: dict) -> dict | None:
    """Copy file from source only if target doesn't exist."""
    rel = change["path"]
    src = source_root / rel
    dst = target_root / rel
    if dst.exists():
        return None  # skip, not an error
    if not src.exists():
        return {"path": rel, "error": f"Source file not found: {src}"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    return None


def action_delete(_source_root: Path, target_root: Path, change: dict) -> dict | None:
    """Remove file from target if it exists. Cleans up empty parent dirs."""
    rel = change["path"]
    dst = target_root / rel
    if dst.exists():
        try:
            dst.unlink()
            # Remove empty parent directories up to project root
            parent = dst.parent
            while parent != target_root and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        except OSError as exc:
            return {"path": rel, "error": str(exc)}
    return None


def action_merge_append(source_root: Path, target_root: Path, change: dict, version: str) -> dict:
    """Append lines from source that are missing in target, under a marker comment."""
    rel = change["path"]
    src = source_root / rel
    dst = target_root / rel
    result = {"path": rel, "action": "merge_append", "added_lines": 0}

    if not src.exists():
        result["error"] = f"Source file not found: {src}"
        return result

    src_lines = src.read_text(encoding="utf-8").splitlines()
    if dst.exists():
        dst_text = dst.read_text(encoding="utf-8")
        dst_lines = dst_text.splitlines()
    else:
        dst_text = ""
        dst_lines = []

    existing = set(dst_lines)
    new_lines = [line for line in src_lines if line not in existing]

    if new_lines:
        marker = f"# Engine additions (v{version})"
        parts = [dst_text.rstrip()]
        if parts[0]:
            parts.append("")
        parts.append(marker)
        parts.extend(new_lines)
        parts.append("")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("\n".join(parts), encoding="utf-8", newline="\n")
        result["added_lines"] = len(new_lines)

    return result


def action_merge_section(source_root: Path, target_root: Path, change: dict) -> dict | None:
    """Replace a specific ## section in a markdown file with the source version."""
    rel = change["path"]
    section_name = change.get("section", "")
    src = source_root / rel
    dst = target_root / rel

    if not src.exists():
        return {"path": rel, "error": f"Source file not found: {src}"}
    if not section_name:
        return {"path": rel, "error": "merge_section requires a 'section' key"}

    src_text = src.read_text(encoding="utf-8")
    src_section = _extract_section(src_text, section_name)
    if src_section is None:
        bare = section_name.lstrip("#").strip()
        return {"path": rel, "error": f"Section '## {bare}' not found in source"}

    if not dst.exists():
        # Append the whole section
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src_section + "\n", encoding="utf-8", newline="\n")
        return None

    dst_text = dst.read_text(encoding="utf-8")
    new_text = _replace_section(dst_text, section_name, src_section)
    dst.write_text(new_text, encoding="utf-8", newline="\n")
    return None


def _extract_section(text: str, heading: str) -> str | None:
    """Extract content from ## heading to the next ## heading (or EOF)."""
    lines = text.splitlines(keepends=True)
    start = None
    end = None
    # Accept heading with or without ## prefix
    bare = heading.lstrip("#").strip()
    marker = f"## {bare}"
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped == marker:
            start = i
        elif start is not None and line.startswith("## "):
            end = i
            break
    if start is None:
        return None
    section_lines = lines[start:end]
    return "".join(section_lines).rstrip("\n")


def _replace_section(text: str, heading: str, replacement: str) -> str:
    """Replace an existing ## section in text, or append if missing."""
    lines = text.splitlines(keepends=True)
    # Accept heading with or without ## prefix
    bare = heading.lstrip("#").strip()
    marker = f"## {bare}"
    start = None
    end = None
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped == marker:
            start = i
        elif start is not None and line.startswith("## "):
            end = i
            break
    if start is None:
        # Append
        result = text.rstrip("\n") + "\n\n" + replacement + "\n"
        return result
    before = lines[:start]
    after = lines[end:] if end is not None else []
    result = "".join(before) + replacement + "\n" + ("" if not after else "\n" + "".join(after))
    return result


def _strip_jsonc_comments(text: str) -> str:
    """Strip // line comments and /* block comments */ from JSONC, respecting
    string literals so JSON string values that contain '/*' or '*/' (e.g. glob
    patterns like "**/*.pyc" or "**/bin/Debug") are left intact. A single
    string-aware pass — the previous blind `/\\*.*?\\*/` regex mangled such globs."""
    out = []
    i, n = 0, len(text)
    in_string = escape = in_line = in_block = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
                out.append(ch)
            i += 1
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
            else:
                i += 1
        elif in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
        elif ch == '"':
            in_string = True
            out.append(ch)
            i += 1
        elif ch == "/" and nxt == "/":
            in_line = True
            i += 2
        elif ch == "/" and nxt == "*":
            in_block = True
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def action_merge_json(source_root: Path, target_root: Path, change: dict) -> dict | None:
    """Merge JSON files using a named strategy. Supports JSONC (comments)."""
    rel = change["path"]
    strategy = change.get("strategy", "")
    src = source_root / rel
    dst = target_root / rel

    if not src.exists():
        return {"path": rel, "error": f"Source file not found: {src}"}

    src_data = json.loads(_strip_jsonc_comments(src.read_text(encoding="utf-8")))
    if dst.exists():
        dst_data = json.loads(_strip_jsonc_comments(dst.read_text(encoding="utf-8")))
    else:
        dst_data = {}

    if strategy == "deep_merge_hooks":
        merged = _deep_merge_hooks(src_data, dst_data)
    elif strategy == "deep_merge_rules":
        merged = _deep_merge_rules(src_data, dst_data)
    elif strategy == "add_missing":
        merged = _add_missing_keys(src_data, dst_data)
    elif strategy == "remove_keys":
        keys = change.get("keys", [])
        merged = _remove_keys(dst_data, keys)
    else:
        return {"path": rel, "error": f"Unknown merge strategy: {strategy}"}

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8", newline="\n")
    return None


def _deep_merge_hooks(source: dict, target: dict) -> dict:
    """Merge .claude/settings.json: union arrays, merge hooks by event, source wins scalars."""
    result = dict(target)

    # Top-level scalars: source wins
    for key, val in source.items():
        if key == "permissions":
            continue
        if key == "hooks":
            continue
        if not isinstance(val, (dict, list)):
            result[key] = val

    # Permissions: union arrays
    src_perms = source.get("permissions", {})
    dst_perms = result.get("permissions", {})
    for key in ("allow", "deny"):
        src_list = src_perms.get(key, [])
        dst_list = dst_perms.get(key, [])
        merged = list(dst_list)
        existing_set = set(json.dumps(x, sort_keys=True) if isinstance(x, dict) else str(x) for x in dst_list)
        for item in src_list:
            item_key = json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item)
            if item_key not in existing_set:
                merged.append(item)
        dst_perms[key] = merged
    result["permissions"] = dst_perms

    # Hooks: merge by event name, add new matchers
    src_hooks = source.get("hooks", {})
    dst_hooks = result.get("hooks", {})
    for event, src_matchers in src_hooks.items():
        if event not in dst_hooks:
            dst_hooks[event] = list(src_matchers)
        else:
            existing = set(
                json.dumps(m, sort_keys=True) for m in dst_hooks[event]
            )
            for matcher in src_matchers:
                if json.dumps(matcher, sort_keys=True) not in existing:
                    dst_hooks[event].append(matcher)
    result["hooks"] = dst_hooks

    return result


def _deep_merge_rules(source: dict, target: dict) -> dict:
    """Merge doc-enforcement.json: source wins rules/cleanup, target wins patterns."""
    result = dict(target)
    if "rules" in source:
        result["rules"] = source["rules"]
    if "cleanup" in source:
        result["cleanup"] = source["cleanup"]
    # target wins for doc_patterns and project-level source config
    return result


def _add_missing_keys(source: dict, target: dict) -> dict:
    """Add keys from source that don't exist in target. Target values always win."""
    result = dict(target)
    for key, val in source.items():
        if key not in result:
            result[key] = val
    return result


def _remove_keys(target: dict, keys: list[str]) -> dict:
    """Remove specific keys from target. For security patches and deprecations."""
    result = dict(target)
    for key in keys:
        result.pop(key, None)
    return result


def action_apply_constitution_scaffold(source_root: Path, target_root: Path, change: dict) -> dict:
    """Upsert template constitution articles from a scaffold JSON.

    Matching strategy:
    1. Match by source_id (canonical).
    2. If no source_id match AND a local article exists with the same
       normalized title but NULL source_id (pre-1.5.0 rows), adopt the
       scaffold's source_id into that row — prevents duplicate numbering
       on first upgrade.
    3. Otherwise INSERT a new row using the next available number.

    Local status of 'amended' or 'revoked' suppresses updates (the consumer
    has diverged on purpose); those rows are reported in `conflicts`.
    """
    rel = change["path"]
    src = source_root / rel
    result = {
        "path": rel,
        "action": "apply_constitution_scaffold",
        "inserted": 0,
        "updated": 0,
        "adopted": 0,
        "skipped_local_divergence": 0,
        "conflicts": [],
    }
    if not src.exists():
        result["error"] = f"Scaffold not found: {src}"
        return result

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["error"] = f"Scaffold JSON invalid: {exc}"
        return result

    articles = data.get("articles", [])
    if not articles:
        return result

    # Local import so the handler stays self-contained
    sys.path.insert(0, str(target_root / ".claude" / "scripts" / "shared"))
    from slugify import slugify  # noqa: E402

    conn = get_db(target_root)
    try:
        # Ensure source_id column exists (idempotent — migration runs via get_db)
        for article in articles:
            source_id = article["source_id"]
            title = article["title"]
            slug = slugify(title)

            # 1. Canonical match by source_id
            row = conn.execute(
                "SELECT * FROM constitution WHERE source_id = ?",
                (source_id,),
            ).fetchone()

            # 2. First-upgrade backfill — match by slug on NULL rows
            if row is None:
                row = conn.execute(
                    "SELECT * FROM constitution "
                    "WHERE source_id IS NULL AND LOWER(title) LIKE ?",
                    (title.lower(),),
                ).fetchone()
                # Fall back to slug match if title doesn't match exactly
                if row is None:
                    candidates = conn.execute(
                        "SELECT * FROM constitution WHERE source_id IS NULL"
                    ).fetchall()
                    for cand in candidates:
                        if slugify(cand["title"]) == slug:
                            row = cand
                            break
                if row is not None:
                    # Adopt this row — assign the template's source_id
                    conn.execute(
                        "UPDATE constitution SET source_id = ? WHERE id = ?",
                        (source_id, row["id"]),
                    )
                    result["adopted"] += 1

            if row is None:
                # 3. Insert fresh
                next_num_row = conn.execute(
                    "SELECT COALESCE(MAX(number), 0) + 1 AS n FROM constitution"
                ).fetchone()
                next_num = next_num_row["n"]
                conn.execute(
                    "INSERT INTO constitution ("
                    "number, title, status, category, context, rule_text, "
                    "consequences, enforcement, created_date, ratified_date, "
                    "source_id) VALUES (?, ?, 'ratified', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        next_num,
                        title,
                        article.get("category", "general"),
                        article.get("context", ""),
                        article["rule_text"],
                        article.get("consequences", ""),
                        article.get("enforcement", ""),
                        article.get("created_date", date.today().isoformat()),
                        article.get("ratified_date", date.today().isoformat()),
                        source_id,
                    ),
                )
                result["inserted"] += 1
                continue

            # Row exists (by canonical match or adoption). Decide whether to
            # update its content from the scaffold.
            if row["status"] in ("amended", "revoked"):
                result["skipped_local_divergence"] += 1
                result["conflicts"].append({
                    "source_id": source_id,
                    "number": row["number"],
                    "local_status": row["status"],
                    "reason": "local divergence preserved",
                })
                continue

            conn.execute(
                "UPDATE constitution SET "
                "title = ?, category = ?, context = ?, rule_text = ?, "
                "consequences = ?, enforcement = ?, ratified_date = ?, "
                "status = CASE WHEN status = 'proposed' THEN 'proposed' ELSE 'ratified' END "
                "WHERE source_id = ?",
                (
                    title,
                    article.get("category", "general"),
                    article.get("context", ""),
                    article["rule_text"],
                    article.get("consequences", ""),
                    article.get("enforcement", ""),
                    article.get("ratified_date", row["ratified_date"] or ""),
                    source_id,
                ),
            )
            result["updated"] += 1

        conn.commit()
    finally:
        conn.close()

    return result


# Action dispatch table
ACTION_HANDLERS = {
    "overwrite": action_overwrite,
    "add": action_add,
    "delete": action_delete,
}


def load_source_manifest(source_root: Path) -> tuple[list, dict]:
    """Load VERSIONS and MIGRATIONS from the source template's engine-update.py.

    The source has the authoritative manifest — the local copy may be outdated.
    """
    source_script = source_root / ".claude" / "scripts" / "engine-update.py"
    content = source_script.read_text(encoding="utf-8")

    versions = []
    migrations = {}

    # Extract VERSIONS list
    import re as _re
    v_match = _re.search(r"^VERSIONS\s*=\s*\[", content, _re.MULTILINE)
    if v_match:
        bracket_depth = 0
        for i in range(v_match.end(), len(content)):
            if content[i] == "[":
                bracket_depth += 1
            elif content[i] == "]":
                if bracket_depth == 0:
                    versions = eval(content[v_match.start() + len("VERSIONS = "):i + 1])
                    break
                bracket_depth -= 1

    # Extract MIGRATIONS dict
    m_match = _re.search(r"^MIGRATIONS\s*=\s*\{", content, _re.MULTILINE)
    if m_match:
        brace_depth = 0
        for i in range(m_match.end(), len(content)):
            if content[i] == "{":
                brace_depth += 1
            elif content[i] == "}":
                if brace_depth == 0:
                    migrations = eval(content[m_match.start() + len("MIGRATIONS = "):i + 1])
                    break
                brace_depth -= 1

    return versions, migrations


# ---------------------------------------------------------------------------
# Working tree guard
# ---------------------------------------------------------------------------


def check_clean_worktree() -> None:
    """Abort if there are uncommitted or unstaged source changes.

    Ignores claude.db (always dirty from MCP operations) and
    project-layer files that the update never touches.
    """
    import subprocess
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    # Files that are always dirty or irrelevant to update safety
    ignore = {".claude/claude.db", ".claude/claude.db-wal", ".claude/claude.db-shm"}
    dirty = []
    for line in result.stdout.strip().splitlines():
        # porcelain format: XY <path> or XY <path> -> <path>
        status = line[:2]
        path = line[3:].strip().split(" -> ")[-1]
        # Skip untracked files — git checkout doesn't touch them, no rollback concern
        if status == "??":
            continue
        if path not in ignore:
            dirty.append(path)
    if dirty:
        file_list = ", ".join(dirty[:5])
        if len(dirty) > 5:
            file_list += f" (+{len(dirty) - 5} more)"
        emit_error(
            f"Working tree has uncommitted changes: {file_list}. "
            "Commit or stash before applying updates, so you can "
            "`git checkout .` to rollback if needed."
        )


# ---------------------------------------------------------------------------
# Core commands
# ---------------------------------------------------------------------------


def cmd_status() -> None:
    """Print current template version info."""
    conn = get_db(PROJECT_ROOT)
    try:
        meta = read_meta(conn)
        emit(meta)
    finally:
        conn.close()


def cmd_dry_run(source: str) -> None:
    """Show what would be applied without making changes."""
    source_root = Path(source)
    if not source_root.exists():
        emit_error(f"Source path does not exist: {source}")
    if not (source_root / ".claude" / "scripts" / "engine-update.py").exists():
        emit_error(f"Source is not a valid template (missing .claude/scripts/engine-update.py): {source}")

    conn = get_db(PROJECT_ROOT)
    try:
        meta = read_meta(conn)
    finally:
        conn.close()

    current = meta["version"]

    # Load manifest from SOURCE, not self — source has the authoritative version list
    source_versions, _ = load_source_manifest(source_root)
    pending = [v for v in source_versions if version_gt(v["version"], current)]
    pending.sort(key=lambda v: parse_version(v["version"]))

    latest = pending[-1]["version"] if pending else current

    versions_out = []
    prev = current
    for v in pending:
        cats = {}
        has_hybrid = False
        for cat_name, changes in v.get("changes", {}).items():
            files = [c["path"] for c in changes]
            cats[cat_name] = {"count": len(files), "files": files}
            if cat_name == "hybrid":
                has_hybrid = True

        # Determine bump level from version number diff
        prev_parts = parse_version(prev)
        curr_parts = parse_version(v["version"])
        if curr_parts[0] > prev_parts[0]:
            bump = "major"
        elif curr_parts[1] > prev_parts[1]:
            bump = "minor"
        else:
            bump = "patch"

        versions_out.append({
            "version": v["version"],
            "description": v.get("description", ""),
            "bump_level": bump,
            "has_migrations": len(v.get("migrations", [])) > 0,
            "has_hybrid": has_hybrid,
            "categories": cats,
            "migrations": v.get("migrations", []),
        })
        prev = v["version"]

    emit({
        "current_version": current,
        "latest_version": latest,
        "versions_to_apply": versions_out,
    })


def cmd_apply(source: str, categories: list[str], yes: bool) -> None:
    """Apply pending versions from the source template."""
    if not yes:
        emit_error("--yes flag is required to apply updates")

    check_clean_worktree()

    source_root = Path(source)
    if not source_root.exists():
        emit_error(f"Source path does not exist: {source}")
    if not (source_root / ".claude" / "scripts" / "engine-update.py").exists():
        emit_error(f"Source is not a valid template (missing .claude/scripts/engine-update.py): {source}")

    conn = get_db(PROJECT_ROOT)
    try:
        meta = read_meta(conn)
    finally:
        conn.close()

    current = meta["version"]

    # Load manifest from SOURCE — it has the authoritative version list and migrations
    source_versions, source_migrations = load_source_manifest(source_root)
    pending = [v for v in source_versions if version_gt(v["version"], current)]
    pending.sort(key=lambda v: parse_version(v["version"]))

    if not pending:
        emit({"applied_version": current, "files_updated": 0, "migrations_run": [], "hybrid_diffs": [], "errors": []})
        return

    all_errors: list[dict] = []
    all_migrations: list[str] = []
    all_hybrid_diffs: list[dict] = []
    total_files = 0
    applied_version = current
    self_update_source: Path | None = None
    self_path = ".claude/scripts/engine-update.py"

    for ver in pending:
        version = ver["version"]

        # --- Run migrations ---
        conn = get_db(PROJECT_ROOT)
        try:
            ver_errors_fatal = False
            for mig_key in ver.get("migrations", []):
                sql = source_migrations.get(mig_key)
                if sql is None:
                    all_errors.append({"migration": mig_key, "error": "Migration key not found in MIGRATIONS dict"})
                    ver_errors_fatal = True
                    break
                try:
                    conn.executescript(sql)
                    conn.commit()
                    all_migrations.append(mig_key)
                except sqlite3.OperationalError as exc:
                    if "duplicate column" in str(exc).lower():
                        all_migrations.append(mig_key)  # idempotent success
                    else:
                        all_errors.append({"migration": mig_key, "error": str(exc)})
                        ver_errors_fatal = True
                        break
        finally:
            conn.close()

        if ver_errors_fatal:
            break  # stop processing further versions

        # --- Apply file changes ---
        for cat_name, changes in ver.get("changes", {}).items():
            # Empty `categories` means ALL categories (a bare `--yes` applies the
            # full update); a non-empty list filters to those categories.
            if categories and cat_name not in categories:
                continue
            for change in changes:
                action = change["action"]
                rel_path = change.get("path", "")

                # Defer self-update
                if rel_path == self_path and action == "overwrite":
                    self_update_source = source_root / rel_path
                    total_files += 1
                    continue

                try:
                    if action in ACTION_HANDLERS:
                        err = ACTION_HANDLERS[action](source_root, PROJECT_ROOT, change)
                        if err:
                            all_errors.append(err)
                        else:
                            total_files += 1
                    elif action == "merge_append":
                        diff = action_merge_append(source_root, PROJECT_ROOT, change, version)
                        all_hybrid_diffs.append(diff)
                        if "error" not in diff:
                            total_files += 1
                        else:
                            all_errors.append({"path": rel_path, "error": diff["error"]})
                    elif action == "merge_section":
                        err = action_merge_section(source_root, PROJECT_ROOT, change)
                        if err:
                            all_errors.append(err)
                        else:
                            total_files += 1
                    elif action == "merge_json":
                        err = action_merge_json(source_root, PROJECT_ROOT, change)
                        if err:
                            all_errors.append(err)
                        else:
                            total_files += 1
                    elif action == "apply_constitution_scaffold":
                        diff = action_apply_constitution_scaffold(source_root, PROJECT_ROOT, change)
                        all_hybrid_diffs.append(diff)
                        if "error" in diff:
                            all_errors.append({"path": rel_path, "error": diff["error"]})
                        else:
                            total_files += 1
                    else:
                        all_errors.append({"path": rel_path, "error": f"Unknown action: {action}"})
                except Exception as exc:
                    all_errors.append({"path": rel_path, "error": str(exc)})

        applied_version = version

    # --- Update DB and config ---
    conn = get_db(PROJECT_ROOT)
    try:
        history_entry = {
            "version": applied_version,
            "date": date.today().isoformat(),
            "categories": categories,
            "files_updated": total_files,
        }
        write_meta(conn, applied_version, history_entry)
    finally:
        conn.close()

    update_project_config(applied_version)

    # --- Self-update (must be last) ---
    if self_update_source and self_update_source.exists():
        try:
            dst = PROJECT_ROOT / self_path
            shutil.copy2(str(self_update_source), str(dst))
        except OSError as exc:
            all_errors.append({"path": self_path, "error": f"Self-update failed: {exc}"})

    emit({
        "applied_version": applied_version,
        "files_updated": total_files,
        "migrations_run": all_migrations,
        "hybrid_diffs": all_hybrid_diffs,
        "errors": all_errors,
    })


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Template engine update script. All output is JSON.",
    )
    parser.add_argument("--status", action="store_true", help="Show current template version")
    parser.add_argument("--dry-run", action="store_true", help="Preview pending updates without applying")
    parser.add_argument("--source", type=str, default="", help="Path to the template source directory")
    parser.add_argument("--categories", type=str, nargs="*", default=[], help="Categories to apply (comma or space separated, e.g. engine,engine_docs). Default: empty = ALL categories.")
    parser.add_argument("--yes", action="store_true", help="Confirm applying updates")

    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.dry_run:
        if not args.source:
            emit_error("--source is required with --dry-run")
        cmd_dry_run(args.source)
    elif args.source:
        # Flatten: handles both --categories engine,hybrid and --categories engine hybrid
        cats = []
        for item in args.categories:
            cats.extend(c.strip() for c in item.split(",") if c.strip())
        cmd_apply(args.source, cats, args.yes)
    else:
        emit_error("No command specified. Use --status, --dry-run --source <path>, or --source <path> --categories <cats> --yes")


if __name__ == "__main__":
    main()
