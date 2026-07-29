# Keel Decisions — Teams, Reconciliation & Multi-Repo

**Version:** 1.0.0 | **Last Updated:** 2026-07-28 | **Status:** Approved
**Parent:** [Technical Decision Record hub](index.md)

## The Team Requirement (G3)

Multiple people work in parallel, each producing docs, routing changes, articles, tasks — and all of it must survive git conflict resolution the way code does. This requirement *validated* the text-as-truth state model (see [state-model.md](state-model.md)) and killed sequential IDs. The mechanisms: per-entity files (disjoint work never conflicts), small readable conflicts when the same entity is touched, and a **post-merge validate/repair pass** for what git can't see (dangling references, duplicate numbers) with proposed or safely-auto-applied fixes.

## Four Worked Scenarios (as discussed, verbatim decisions)

### A — Solo, two machines
Desktop Friday: task `T-k7f3m` left `working`, commit, push. Laptop Sunday: pull; the reconciler sees the watermark moved, rebuilds index entries for changed files, re-renders `board.md`, and session start offers "T-k7f3m in progress, last touched Friday — resume?" Ephemera (pointer, gate evidence) correctly did *not* travel — Sunday's machine re-runs reviews before committing because Friday's evidence attests to Friday's machine. **Fully solved by decided architecture; zero ceremony.**

### B — Small team, feature branches + PRs (the optimized shape)
Two people branch Monday; each session mutates state on its own branch. A PR diff shows code *plus readable state changes* (task closed, doc added) — **state review rides code review for free**. Disjoint entities auto-merge; the reconciler summarizes the merge at next session start ("since you last looked: T-p2n8x completed (Dana), billing doc added"). Same-entity collisions surface as small conflicts or validator findings with proposed repairs.

### C — Shared long-lived main
Same machinery, merges just happen smaller and more often; conflicts surface at pull, repaired at session start; CI validates post-push instead of pre-merge (findings become tasks rather than blocking); claim visibility is actually *faster* (pushes propagate in minutes). Cost: no review checkpoint before state lands. **Supported; nothing extra to build.**

### D — Mixed team with a non-AI developer
Marcus edits code in his IDE and pushes; never touches `state/`, needs zero training. The reconciler diffs the watermark: refreshes the code index for his files, flags docs whose **source-path mappings** cover his changes ("possibly stale — review?" as proposed tasks), re-indexes his hand-edited doc's headings automatically. CI confirms state coherence (and if he *had* mangled a task file, CI names the file and fix). **The system metabolizes his work automatically — non-AI developers get a dignified place with no obligations. This scenario is why G15 exists.**

## External-Change Reconciliation (G15)

Keel keeps a **per-(machine, repo) watermark** — the last reconciled commit. At session start it diffs `watermark..HEAD`: anything that arrived outside a Keel session (direct pushes, merged PRs, hotfixes) is discovered automatically; routing refreshes; mapped docs get staleness flags; new files get indexed; material changes propose follow-up work ("`payments/` changed significantly with no doc update — create a doc-review task?"). **Discovery is automatic; resolution arrives pre-proposed; applying is the user's one-tap choice.** One reconciler serves both non-framework contributors and post-merge sync for framework users — "what changed since I last looked" is the same question in both cases. The reconciler is also where an LLM optionally re-enters the otherwise-mechanical index pipeline: proposing curation for an uncurated new doc (pre-approved, optional).

## PR-First Optimization (decided)

All four shapes are supported; **PR-first is the taught default** — onboarding recommends it, docs teach it first, edge-case polish prioritizes it, and the shipped CI template assumes it. Two decisions attached:

**CI state validation ships with Keel** (GitHub Actions first): schema validation, ID/reference integrity, article-number collisions, pipeline-evidence plausibility — on every PR. Near-mandatory for teams: CI is the only enforcement point no harness variance can weaken, and the backstop for scenario D. Hooks enforce on the author's machine; CI guarantees the merged result.

**Task claiming is visibility, not locking.** Git state is eventually consistent; a claim on an unpushed branch is invisible. Keel does *not* pretend to solve distributed locking (no lock servers, no claim arbitration — non-goal 4): `start_task` sets the assignee (visible in `board.md` once pushed); session summaries surface "assigned elsewhere" as soon as known; the residual race belongs where it lives on every team — standup, chat, the PR. Claims made *visible fast*, not *atomic*: enormous machinery for tiny value refused.

## PM Bridges (extension class, not core)

Keel is not a PM suite (no sprints, points, burndowns, dashboards, time tracking — the legacy Gantt with invented durations died for this). But **arcs** (structural grouping — see [workflow.md](workflow.md)) are core because they serve AI context, and **bridges to external PM systems are a supported extension class**: feature-registry modules (off by default), e.g. an Azure DevOps connector with commands to push selected items outward, reflect closures back, map arcs to epics. Text-as-truth makes connectors nearly trivial for third parties to write — the designed extensibility dividend.

## Multi-Repo: Deferred, Designed-For (G18)

**Clarification recorded:** the workspace with N projects in one git repo **is a monorepo and is the core supported shape** — that's projects-first, not an extension. What's deferred is **multi-repo federation**: one workspace spanning projects that live in separate repositories with separate histories/permissions (the motivating case: ~20 enterprise-service-bus repos in microservice architecture, some calling others — separate by org policy, painful to work across, hugely served by a common interface with shared AI-referenceable documentation).

**Ben's coordinator sketch (adopted as the deferred design):** a coordinator workspace repo holds the state spine (boards, arcs, articles, docs, routing); projects *reference* external repos rather than owning folders — barely a new concept, since a project is already "a registered path with config"; Keel performs git operations against the referenced repo's root; shared docs live in the coordinator. Side benefit: "manage in place through a coordinator" becomes a third ingestion answer for orgs that can't re-root repos (not recommended — forfeits state-travels-with-code and unified PR review — but a legitimate escape hatch).

**V1 forward-compatibility commitments (cheap seams held open now):**
1. **Project paths are declared data with no structural internal-only assumption** — v1 *validates* paths are inside the workspace, but as a liftable validation rule (data), not an architectural wall.
2. **Watermarks key by (machine, repo-root)** even with exactly one root today — "one is a count, not a shape."
3. **Git operations take an explicit repo-root parameter** through one thin layer — the engine never assumes `cwd` is *the* repo (also better hygiene: the legacy stray-DB bug was a cwd assumption).

Not built, not promised for v1 — but no v1 decision may foreclose it.
