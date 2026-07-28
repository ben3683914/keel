# Setup Guide

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Python 3.x (for MCP servers, hooks, and enforcement scripts)
- Git

Optional:
- [GitHub CLI](https://cli.github.com/) (`gh`) for automated repo creation
- AWS CLI with SSO configured (for work/Bedrock projects)

## Getting Started

1. Copy the template to a new folder
2. Open in Claude Code — `setup.sh` runs automatically during onboarding to bootstrap the venv and MCP servers
3. Complete the onboarding interview (13 questions)
4. Install project dependencies: (project-specific command)
5. Run the project: (project-specific command)
6. Run tests: (project-specific command)

## Portable VSCode

Each project gets its own isolated VSCode instance at `.vscode-portable/`:

- Downloaded and extracted during setup
- Extensions are pre-installed into the portable instance's `data/` folder
- `start-workspace.bat` launches the portable instance (falls back to global `code` if missing)
- `.vscode/settings.json` workspace settings apply regardless of which instance is used
- Gitignored — each developer gets their own local copy

If the download fails during setup, the project works fine with global VSCode.

## Python Virtual Environment

MCP servers run via `.claude/venv/bin/python` (project venv, gitignored).
Bootstrapped automatically by `setup.sh` during first-run onboarding.
Each developer gets their own venv — it is not shared or committed.

## Development Workflow

1. Use `create_task` to create a task on the board
2. Use `start_task` to move it to in-progress
3. Write code + tests
4. Complete the review workflow (code → docs → security → tests)
5. Commit with conventional format: `type: description`
6. Use `move_to_testing` → `validate_task` to close the task
7. Update docs if behavior changed
