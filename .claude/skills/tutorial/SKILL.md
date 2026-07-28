---
name: tutorial
description: Interactive guided tour of this template — what it is, the session workflow, skills, and (most importantly) context management. Use when the user runs /tutorial or asks to learn how the template works.
disable-model-invocation: true
argument-hint: "[topic]"
---

You are giving a **guided, interactive tour** of this template. This is a friendly tour, NOT a documentation dump.

## Ground rules (read first)

- **Do NOT scan the repository.** Everything for the standard tour is curated below — use it as your script and paraphrase naturally. Only if the user asks something these notes don't cover should you read **one** specific file (e.g. a particular `SKILL.md` or doc), never the whole template.
- **Keep it short.** A few sentences per topic. Offer to go deeper; don't force it. Concrete beats exhaustive.
- **Let the user drive.** They can pick topics in any order, ask anything, jump around, or say "I'm done" at any point.
- If invoked with a `[topic]` argument (e.g. `/tutorial skills`), jump straight to that topic.

## Step 1 — Welcome + choose the path

Greet in ~2 lines, e.g.: *"Welcome! This template turns Claude Code into a structured, spec-driven dev partner — your docs and a project constitution are the source of truth, and all project state travels with the repo so you can stop and resume anytime."*

Then ask **one** question:

> Would you like a **guided tour** of the essentials, or would you rather **jump straight to the menu** and pick what interests you?

- **Guided tour** → walk the Core topics (1–4) in order, pausing after each: *"Questions, or move on?"* Then show the full menu for the extras.
- **Menu** → show the full menu now and follow their picks.

## Topic menu

Present as a numbered list:

**Core**
1. What this template is & why
2. A session, start to finish
3. Skills — what they are & when to use them
4. ⭐ Context management — the most important habit

**More**
5. The constitution & enforcement
6. MCP tools & where your state lives
7. Single vs multi-project workspaces
8. Agent teams & the review pipeline

Remind them they can also just ask a question, or say **"let's start"** to begin setting up their project.

## Curated content (your script — paraphrase, keep tight)

### 1. What this template is & why
It makes Claude Code work like a disciplined senior engineer instead of an eager intern. The core idea: **the spec is the source of truth.** Your design docs and a project **constitution** (a small set of rock-solid rules) govern the work, and Claude is held to them. All project state — tasks, reviews, the constitution — lives in `.claude/claude.db`, which is committed to git, so the project's "memory" travels with the repo and any teammate (or a fresh session) picks up exactly where things were.

### 2. A session, start to finish
A normal loop:
1. **Session start** — Claude auto-loads the constitution, current status, and health.
2. **Pick one piece of work** — start a task.
3. **Design first — the most important step.** Getting the *design* of a system right matters far more than the code that implements it: a flawed design is expensive to unwind, while solid code on a sound design is cheap. So for anything non-trivial, Claude asks design questions one at a time, writes a short design doc, and gets your explicit go-ahead *before* writing code. This isn't optional politeness — the constitution requires it (**Article 002, Design Before Implementation**).
4. **Build** — Claude orchestrates; specialized agents do the implementation.
5. **Review gates** — code → docs → security → tests, each acknowledged.
6. **Validate & commit** — you confirm it works, then it's committed (along with `claude.db`, so state travels).

The point: small, reviewed, well-documented steps.

### 3. Skills — what they are & when to use them
Skills are slash-commands for common workflows. The main ones:
- `/board` — see the task board at a glance.
- `/project-status` — current phase, blockers, progress.
- `/health` — code & doc health (file sizes, naming, stale docs).
- `/review` — run the review pipeline on the current changes.
- `/inspect` — peek into the project's state in `claude.db`.
- `/add-project` — grow a single project into a multi-project workspace.
- `/document-project` — generate or refresh docs for an existing codebase.
- `/constitution` — propose, amend, or revoke articles when the project needs a behavior *actively enforced*.
- `/tutorial` — this tour, anytime.

Rule of thumb: reach for a skill when you want a *consistent, repeatable* workflow instead of ad-hoc steps.

### 4. ⭐ Context management — the most important habit
This single habit determines whether Claude stays sharp.

- **Work on one thing per session.** Do a feature or fix, finish it, then **`/clear`** before starting the next.
- **Why:** the model pays the most attention to what's *early* in the context window. As context fills with old, half-relevant history, recall degrades and **hallucinations go up**. A long, sprawling session is a *worse* session — not a more informed one.
- **You lose nothing by clearing.** The template is built for this: your tasks, reviews, and progress live in `claude.db`, and a **board snapshot** is written at session end. A fresh session reloads exactly where you left off — so `/clear` early and often between units of work.
- **End sessions with `/exit`** — don't just force-close the terminal/window. `/exit` lets Claude run its session-end housekeeping (writing that board snapshot, finalizing state) so the next session resumes cleanly.

Mental model: **one unit of work → `/clear` (or `/exit` to close) → next unit, fresh context.**

### 5. The constitution & enforcement
The **constitution** (`docs/constitution/`) is a short list of binding rules for the project. The one to know first is **Article 002 — Design Before Implementation**: any new system, API, or significant change needs a reviewed design document *before* coding starts (quick fixes are exempt). That's the template's core conviction — **design is the most important part of building a system** — turned into an enforceable rule. It's reinforced by **Article 003 (Honest & Collaborative Partnership)** — Claude must design *with* you and push back rather than rubber-stamp — and **Article 001 (Architecture Doc as Source of Truth)**. The rest cover reviews, doc size, diagrams, and so on. These are **enforced**, not suggested: hooks block a commit until reviews are acknowledged, and the docs-reviewer flags a qualifying change that arrives with no design doc as a violation. It feels like guardrails because it *is* — that's what keeps quality from drifting. And the constitution is yours to grow: when your project needs a particular standard or behavior **actively enforced** — not just hoped for — propose it as a new article with `/constitution`. Once ratified it becomes a binding rule that the reviews and hooks hold every change to. That's the intended move whenever you catch yourself wishing "this should always happen here."

### 6. MCP tools & where your state lives
Four MCP servers run the project's brain: **task-manager** (tasks/board), **docs-manager** (docs + constitution), **code-manager** (code routing + reviews), **test-manager** (tests). They read and write `.claude/claude.db` — the single, git-tracked store of project state. You rarely touch these directly; Claude does, and you see the results.

### 7. Single vs multi-project workspaces
A workspace holds one project or many, and **every project lives in its own `./<slug>/` folder** — your code never sits at the repo root next to the engine. **Single** is the default: one project folder, everything scoped to it. Run **`/add-project`** and it becomes **multi-project**: each project gets its own board, status, health, routing, and constitution tier — all on top of a shared *workspace* umbrella (cross-cutting tasks + a workspace constitution tier). You never work on the workspace row itself; it's just the umbrella. Start single; grow when you need to.

### 8. Agent teams & the review pipeline
Claude acts as the **orchestrator** — it designs and delegates, but doesn't write source code itself. Specialized **sub-agents** do: implementers write code, then **code-reviewer**, **docs-reviewer**, **security-reviewer**, and **test-runner** each check the work before it can be committed. Independent work can run in parallel.

## Wrapping up

When the user is done — or says "let's start":
- If this tour was launched **during onboarding**, offer to begin the real onboarding interview with a chosen shape (single / multi / scratch), asking questions **one at a time**.
- If launched later via `/tutorial`, confirm they're set and point them at `/board` or starting a task.

Either way, leave them with the one habit that matters most: **one unit of work per session, then `/clear` — and `/exit` to close cleanly.**
