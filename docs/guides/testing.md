> **Version:** 0.2.0
> **Last Updated:** 2026-07-29
> **Status:** Active

# Testing Guide

## Keel Engine (`ai-development-template/`)

The engine test suite runs with [Vitest](https://vitest.dev/). All commands run from the
project folder:

    cd ai-development-template

| Command | Purpose |
|---------|---------|
| `npm test` | `vitest run --coverage` — full suite with v8 coverage |
| `npm run test:watch` | Vitest watch mode during development |
| `npm run ci` | typecheck + lint + format:check + test — the exact gate CI runs |

CI (`.github/workflows/ci.yml`) runs `npm run ci` on ubuntu/macos × Node 20/22 (required)
and windows × Node 22 (advisory). Coverage thresholds (80% lines / 75% branches in
`vitest.config.ts`) activate with the first real module (T-009).

### Organization

- **Unit tests** — `tests/unit/` mirrors `src/` one-to-one:
  `src/<module>/<file>.ts` ↔ `tests/unit/<module>/<file>.test.ts`. Pure logic in
  isolation; no real git, no network. Determinism seams (e.g. the git layer's injectable
  `ExecFileFn`) keep them hermetic.
- **Integration tests** — `tests/integration/` exercises cross-module flows against real
  temporary git repositories (per-test temp dirs, cleaned up in `afterEach`). Slower and
  fewer; still hermetic.
- **Fixtures** — `tests/fixtures/<area>/<case>/` with an `input/` tree plus expected
  outputs. Conventions: [tests/fixtures/README.md](../../ai-development-template/tests/fixtures/README.md).

Full test strategy: [engine-scaffold.md](../features/engine-scaffold.md#test-strategy-sdlc-d).

## Legacy Template Engine (`.claude/scripts/`)

Engine regression tests for the Python MCP/hook scripts live in `.claude/scripts/tests/`
and run with `pytest`.

## Test Conventions

- Use descriptive test names that explain the expected behavior
- Follow Arrange-Act-Assert pattern
- Keep tests independent — no shared mutable state
- Mock external dependencies via injected seams, not internal logic
