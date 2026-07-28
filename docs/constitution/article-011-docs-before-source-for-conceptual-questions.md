> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 011: Docs Before Source for Conceptual Questions

**Category:** workflow

## Status

Ratified (2026-04-23)

## Context

The doc system is the intended first-line source for conceptual context. Skipping it and reading source directly bypasses the routing layer, misses current context captured in feature docs, and forgoes constitution-article injection that `get_relevant_docs` performs in the same call. Past sessions have fallen into the source-first reflex on ad-hoc questions because earlier framing positioned `get_relevant_docs` as a task-lifecycle step rather than a standing rule. Docs often carry architectural intent, decisions, and nuance that source doesn't surface — answering from source alone can produce explanations that are technically accurate but miss the "why."

## Rule

When answering a conceptual question about the codebase — how a system works, what something does, an architecture or API explanation — `get_relevant_docs` must be called before reading source files. This applies outside of formal task context, including ad-hoc conversational questions. Source files are for verification and mechanical lookups (specific lines, signatures, grep-style checks), not first-pass conceptual understanding.

## Consequences

Answers based solely on source reads may contradict current architectural decisions documented elsewhere, or miss constitution articles relevant to the topic. The docs-reviewer agent will flag explanatory responses that did not call `get_relevant_docs` first. The answering agent risks teaching users to trust source as the canonical reference when the doc layer was designed to be authoritative.

## Enforcement

During review, check whether conceptual-question responses were preceded by a `get_relevant_docs` call in the same conversation. One call per topic per session is sufficient — the rule targets the first-pass reflex, not redundant re-queries. Mechanical reads (specific line numbers, signature checks, verification after docs were consulted) are exempt.
