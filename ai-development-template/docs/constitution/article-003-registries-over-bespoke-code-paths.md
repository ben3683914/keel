> **This file is auto-generated from SQLite. Do not edit directly.**
> Use `amend_article` or `revoke_article` to make changes.

# Article 003: Registries Over Bespoke Code Paths

**Category:** design

## Status

Ratified (2026-07-28)

## Context

Adopted from the oval game's Article 018 (generic entities over hardcoded singletons), generalized during T-001. The rewrite's walkthrough repeatedly converged on registries as the extension mechanism: features, health rules, finding types, smoke tests, routing scorers, onboarding questions, tutorial topics, harness adapters. User extensions (G10) and feature toggles (G4) only work if framework-shipped and user-added capabilities flow through the same mechanism.

## Rule

New framework capabilities plug into generic registries: features, hooks, health rules, finding types, smoke tests, scorers, onboarding questions, tutorial topics, and harness adapters are registry entries with declared metadata, discovered and composed by the engine. Adding a capability — whether framework-shipped or user-authored — must be a registry entry plus data/drop-in files, never a new hardcoded code path, special case, or singleton. Framework and user entries share mechanisms, separated by namespace and provenance.

## Consequences

Extension becomes patching; user additions break on every update; toggles miss surfaces that were special-cased outside the registry; the framework grows a bespoke code path per capability until it is unmaintainable — the legacy template's fate.

## Enforcement

During design review: any new capability must name which registry it enters, or justify creating a new registry (with its own schema) rather than a one-off. During code review: reject switch/if chains dispatching on capability identity where a registry lookup belongs; verify user-namespace entries are honored by the same code path as framework entries.
