# ai-development-template

Workspace for **ai-development-template** — a template for AI-assisted development within existing agent frameworks like Claude Code and Codex, focused on extensibility, flexibility, and portability. The project itself lives in [`./ai-development-template/`](ai-development-template/).

## Quick Reference

    Bootstrap workspace:   bash setup.sh
    Keel engine (ai-development-template/):
      Install:             npm install
      Build:               npm run build
      Test:                npm test
      Full local CI gate:  npm run ci        (typecheck + lint + format:check + test)
    Legacy engine tests:   pytest            (.claude/scripts/tests/)

## Documentation

See [docs/index.md](docs/index.md) for full project documentation.

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Python 3.x
- Node.js >= 20 and npm (Keel engine)
- Git
