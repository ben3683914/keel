# ai-development-template

A template for AI-assisted development within existing agent frameworks like Claude Code and Codex, focused on extensibility, flexibility, and portability.

This folder holds the **Keel engine** (`keel-engine`) — the TypeScript/Node rewrite of the template's engine. The legacy Python engine still lives in the workspace's `.claude/scripts/`.

## Quick Reference

- **Install:** `npm install` (Node >= 20)
- **Build:** `npm run build` (tsc → `dist/`)
- **Test:** `npm test` (Vitest + v8 coverage)
- **Full local CI gate:** `npm run ci` (typecheck + lint + format:check + test)
