# Project Guide

Project overview, purpose, and the build / run / test commands live in **[README.md](README.md)**. This file (CLAUDE.md) is the working agreement for Claude: architecture, mode, workflow, and rules.

## Architecture Snapshot

    project/
      board-snapshot.md   (auto-generated at session end)
    .claude/
      claude.db           (all mutable state -- SQLite)
      scripts/shared/     (DB, project resolver, routing)
      scripts/mcp/        (4 MCP servers)
      scripts/hooks/      (enforcement + tracking hooks)
      scripts/tests/      (engine regression tests)
      agents/             (4 review agents)
      skills/             (custom skills)
      scaffolds/          (CLAUDE.md + settings.json partials)

**Note:** `claude.db` is tracked in git intentionally -- project state travels with the repo.

## Self-Cleaning

This file must stay under ~100 lines. Move details to linked docs.
