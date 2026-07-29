# Keel Decisions — Distribution, Updates & Onboarding

**Version:** 1.0.0 | **Last Updated:** 2026-07-28 | **Status:** Approved
**Parent:** [Technical Decision Record hub](index.md)

## Keel Ships as an Artifact, Not a Clone (G2)

The template distribution is a built artifact delivered through the update channel — **not** a git clone of the maintainer's repo. Git belongs to the *user's* workspace, created or absorbed during onboarding. This single decision dissolves an entire legacy problem family:

**The `template_dev` flag dies.** Legacy developed the template inside itself while tracking state in git, so maintainer sessions could ship dirty state (completed onboarding, test tasks) to every downstream clone — patched by a flag guarding 17 MCP tools, a reactive-only escape hatch, and prayer. Keel's release pipeline **builds the artifact from a manifest** — seed state is constructed fresh, never "maintainer state, hopefully cleaned." Legacy's `/prep-release` (subtract dirt, exit code 4, hope) inverts into a build (add only what's declared). The maintainer's workspace can be as lived-in as it likes; a **pristine-boot smoke test** on the built artifact (onboarding not started, boards empty, no absolute paths) replaces the guard. The failure mode isn't guarded against — it's unrepresentable.

## The Update System (G8 + G10)

**Pristine baseline + true three-way merge.** The workspace keeps an untouched record of the shipped version (manifest + content hashes). An update computes *baseline→new* vs *baseline→current* per file:

| File state | Action |
|------------|--------|
| Untouched by user (hash proves it) | Silent upgrade |
| User-modified, framework-unchanged | Keep user's |
| Both changed | Real three-way merge; explicit prompt on overlap |
| User-namespace (own hooks, skills, articles) | Never a candidate — structurally out of scope |

This replaces legacy's 1453-line update script with its hand-maintained Python-literal `VERSIONS` manifest and per-file action lists (which conflicted with itself — CLAUDE.md was both wholesale-regenerated and section-merged). Baselines compute "what's safe to touch" *correctly for files the maintainer forgot to classify*. This is how OS package managers handle config files; it is idempotent by construction (re-running converges; "what did the user change" is always `diff baseline current`, never guessed).

**Namespaced extension points do the other half:** user additions live where the framework promises never to write (drop-in directories, provenance-tagged entities). When user-owned and framework-owned never share a namespace, most "merges" never happen at all — flexibility as structure, not heuristics. A user adding a hook participates in the same registry mechanism updates use: one system, no escape hatch.

**Channel format — deliberately dumb:** versioned tarballs + a signed JSON index (versions, hashes, minimum-upgradeable-from, changelog). Any static host works (S3, git releases, …). Detection is an HTTP GET of the index at session start behind a per-machine cooldown watermark — no service. Delta patches etc. are later optimizations behind the same index format.

**Update flow:** detect → prompt → automatic backup → dry-run preview → apply (interruptible-safe, resumable — Article 002) → declarative state migrations (versioned transform steps, testable in CI) → **smoke tests re-run** (an update that merges cleanly but breaks a capability must say so itself) → user reviews `git diff` like any PR, because it *is* text.

**Worked example:** v2.4.0 ships a new health rule. A team's workspace: 14 framework files changed upstream; they customized one skill; three user-namespace hooks exist. Result: 13 silent upgrades, one clean three-way merge on the skill (different sections), hooks untouched (not candidates), migrations replay idempotently, smoke tests pass, backup retained.

**Everything-as-content dividend:** model overlays (new prompting guidance), command-safety deny-lists (new footgun patterns), tutorial topics, and article packs all ship through this channel as data updates — improvements arrive without framework releases.

## Onboarding (kept, expanded, made declarative)

First-run setup is a **one-question-at-a-time interview** — each answer reshapes later questions (an interview teaches while configuring; a 30-key config file demands understanding upfront); **resumable** (first-run is when crashes and interruptions happen; a restartable-from-zero interview that already created folders is half-configured wreckage); answers stored only at completion so the interview needs no working machinery (it runs before setup completes).

**Rewrite refinements:**
- The flow is a **declarative branching question graph** the engine walks — not prose a model hopefully follows in order. Harness-portable (Codex walks the same graph), testable, extensible: features and article packs register their own questions (the AI-boundaries pack asks "does this project call LLMs?").
- Steps declare dependencies; the engine sequences them — legacy's load-bearing ordering bugs ("config+assemble must precede update_onboarding or the guard blocks it") die structurally.
- **Credential profiles (G9):** the interview asks whether to use current credentials or configure alternates (personal Claude vs Bedrock for work) and walks through setup. Profiles are per-machine ephemera, never tracked; setup re-prompts or restores on a new machine.
- **Presets:** workspace shape is a named toggle bundle (scratch/standard/team), extensible later to purpose-built profiles ("hardened-API") that are nothing but toggle states.
- **Tutorial** offered as an option (see below); post-onboarding **nudges** guide efficient early usage.

**Self-cleanup (G12):** onboarding dissolves itself — interview state, one-time scaffolding, and setup-only assets are **manifest-marked as setup-only** and removed at completion (declarative cleanup, not a hardcoded list). What remains is operational: update system, tutorial, runtime.

## Existing-Repo Ingestion (G1)

A user drops an existing codebase in; Keel offers to invert the structure so the workspace is the git root and their code lives at `./<project>/`. **Both history paths offered, keep-history recommended:** (a) preserve — their commits carried into the re-rooted repo, remote re-pointed/re-created with guidance; (b) fresh start — old `.git` archived aside, clean history begins. The ingestion ceremony handles moving/absorbing `.git`, re-rooting, and keeping their code working. A third answer exists for orgs that can't re-root (compliance, pipelines): manage-in-place via a coordinator workspace — see [collaboration.md](collaboration.md) multi-repo seams; documented as the escape hatch, not the recommendation (it forfeits state-travels-with-code and unified PR review).

`/document-project`-style analysis follows ingestion: detect projects by manifest markers, confirm with the user, fan out analysis, write baseline docs, **propose** (never impose) articles from observed conventions, open tasks for gaps.

## Setup, Doctor & Verification-by-Execution

**Principle (kept and promoted):** verify the capability, not its indicator. Legacy's setup executes each Python candidate (macOS ships a stub that passes `command -v` and fails on run) and smoke-tests by launching a real MCP server (the incompatible SDK imports fine and dies at runtime). Keel generalizes:

- **Smoke-test registry:** every feature and adapter registers its execution check (Article 003); setup runs all of them — e.g. actually starting an MCP server and making a tool call through each configured harness's real invocation path — reporting "verified: Claude Code ✓ Codex ✓" or naming the broken link precisely.
- **`doctor`:** the same checks as a standing command. G5's machine move is "clone → setup → doctor → go"; six weeks later, "it's being weird" is one command to re-verify every capability. Checks are idempotent and read-only where possible.
- **Updates re-run smoke tests** (above); the release pipeline runs the pristine-boot test on artifacts.

**Why this is existential for a public project:** setup is the highest-stakes, lowest-trust moment — a stranger, a fresh machine, zero investment. "Setup said success, first real use fails" reads as "this framework is broken." Execution checks convert "should work" into "did work" at the only moment cheap enough to fix it.
