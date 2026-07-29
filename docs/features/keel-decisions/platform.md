# Keel Decisions — Platform, Harnesses & Models

**Version:** 1.0.0 | **Last Updated:** 2026-07-28 | **Status:** Approved
**Parent:** [Technical Decision Record hub](index.md)

## Neutral Core + Harness Adapters (G6)

Keel targets Claude Code and Codex as peers, switchable at will, with future harnesses addable as adapters. The core declares **what must hold** (rules, pipeline graphs, gates) as data; each adapter enforces **as much as it can**; a **capability matrix** makes the difference explicit rather than silent.

| Capability | Claude Code | Codex |
|------------|-------------|-------|
| MCP tools | ✓ | ✓ |
| Pre-tool hooks (blocking gates) | ✓ | ✗ |
| Stop/session hooks | ✓ | ✗ |
| Entry instruction file | CLAUDE.md | AGENTS.md |
| Enforcement mode | Block + inject | Inject (compensation — stronger assertions) |

MCP is the common denominator: every harness that speaks it receives tool responses, which is why in-band injection is the baseline enforcement layer (see [governance.md](governance.md)) and hooks are a Claude-adapter bonus. Enforcement *degrades from blocking to asserting, never to nothing*.

## Instruction Architecture: Thin Shims, Three-Layer Assembly (changed)

Legacy generated CLAUDE.md wholesale from scaffold partials (discarding user edits) while the update system simultaneously treated it as hand-merged — two mechanisms, opposite assumptions, same file. Keel:

- **Entry shims** (`CLAUDE.md`, `AGENTS.md`, …): thin, nearly-static, generated; they point to the shared docs, carry only genuinely harness-specific notes, and are safe to regenerate because nobody has a reason to edit a pointer file.
- **Shared instruction docs**: all real content — workflow, session protocol, design gate, roles — written once, harness-neutral, maintained like any docs (size limits, health checks, mergeable).
- **Assembly layers**: (1) core instructions → (2) harness overlay (what the capability matrix implies: "you have no commit hook; injection carries gate reminders — heed them") → (3) model overlay (G7). Shims are the only generated artifact — tiny, deterministic, rebuildable.

User edits belong in shared docs or user overlay files, which updates respect via provenance. Adding harness #3 is a data change (Article 001 requires this).

## Model Overlays (G7)

One **default directive set** for every model; **named models** get sparse overlay files — deltas only (prompting-style adjustments, feature directives, agent model assignments). Unknown/new model → pure default; adaptation, not enforcement, and never an error. Overlays are registry data shipped through the update channel: when Anthropic publishes new guidance for a model (the motivating case: Opus 5 guidance differing sharply from what legacy was built on), the maintainer publishes a ~30-line overlay; every workspace picks it up at next update; no framework release; a Codex-on-GPT teammate sees zero diff noise. Agent **model assignments** (which model the code-reviewer spawns on) live in this same layer — a Bedrock workspace (G9) with different model availability just overlays different assignments.

## Engine: TypeScript/Node (decided)

**Decisive fact:** every machine running Keel already runs a harness, and the harnesses are npm-distributed — Node is the one runtime guaranteed present, including native Windows. The legacy venv chicken-and-egg (hooks invoked via a venv python that doesn't exist until setup runs; macOS shipping a stub `python3` that passes `command -v` and fails on execution) has no Node equivalent: the runtime that runs the harness runs the engine.

Supporting: one language for MCP servers (TS SDK is the reference implementation), hooks, setup tooling, validators, the reconciler, and eventually T-002; mature shell-parsing libraries for the commit gate; the largest contributor pool for a public project; artifact ships source + lockfile — no per-platform binaries in the update channel.

Rejected: **Go/Rust** (single static binary is genuinely nice, but per-platform binaries complicate the channel, raise the contribution bar, and user extensions land back in script-land anyway — reintroducing the polyglot problem exactly at the extension boundary where flexibility matters most); **Python** (the devil just exorcised); **Bun/Deno** (attractive, but betting long-term public support on the smaller ecosystem is an avoidable risk; a later port stays feasible).

Platforms: WSL/Linux/macOS required; native Windows nice-to-have; end user runs exactly one setup script, ever (G5).

## AI Provider Registry (G16)

Beyond the harness's model, Keel can call other providers directly — Bedrock-hosted models, OpenAI via AWS, Kimi K3, etc. — declared as registry entries (endpoint, models, auth-profile reference) with credentials in per-machine profiles (G9), never tracked. Primary use: **cross-model adversarial review** (see [workflow.md](workflow.md) — stages declare executors). The engine makes provider calls directly (mechanical, outside the harness). Degradation: no credentials on this machine → fall back to harness-subagent execution with a visible note, or gate, per config. Framing: the harness stops being *the* AI and becomes *the primary* AI among several the workspace can orchestrate.

## Command Safety (changed from legacy's hardcoded deny-list — reclassified from kill to change by Ben)

A feature module, **ON by default**, whose default posture **prevents pushes** (explicit user confirmation required) and enforces a curated deny-list of dangerous commands — git footguns (`push --force`, `reset --hard`, `clean -f`) *and* general AI-agent footguns (`rm -rf` at dangerous paths, piped-to-shell downloads, credential-file reads). Rationale (Ben's): the default posture protects against *the agent*, not the human — an AI with shell access is precisely the actor that should hit guardrails by default; a public framework's stranger-first experience must be the safe one.

- **Tiers:** `strict` (legacy posture: full deny-list + push-via-confirmation flow) / `standard` (default, as above) / `off` (explicit, logged opt-out for teams whose forge protections are stronger).
- **The deny-list is declared data shipped via the update channel** — new agent-footgun patterns publish as list updates; every workspace's guardrails improve without a release. Threat intelligence as content.
- **Universal conversational law at every tier:** the agent never pushes without in-session user go-ahead — a collaboration norm, not config.
- Enforced as blocks on harnesses with permission hooks; as injected assertions elsewhere (capability matrix).

## Command Namespaces (G14)

Three visually and structurally distinct namespaces: **harness built-ins** (`/init`, `/review` — frontier names Keel must not collide with; legacy's `/review`, `/health` were live collision risks), **Keel-shipped** (`/keel-health`, `/keel-board`, `/keel-features`), and **user-created** (own prefix; final word [Pending]). A shipped **skill-builder skill** walks users through creating skills the approved way — right structure, metadata, provenance-tagged user-owned, auto-prefixed — so user skills survive updates structurally and the three origins are never confusable.

## Naming: Keel

Chosen from a shortlist (Charter, Accord, Tenet, Keel + second round: Rudder, Ballast, Cairn, Truss, Chassis, Plinth, Lintel, Canon, Axiom, Precept). Rationale: short, concrete, structural — the keel is the first thing laid down, everything is built on it, and it's the last thing to fail; says "the thing everything rests on" without saying "governance." Excluded for collisions: Helm (Kubernetes), Codex (OpenAI), Bedrock (AWS), Keystone (OpenStack), Loom, Anchor, Trellis.
