// Keel engine — public API surface, in three tiers.
//
// Tier 1 (flat named exports): the state-layer operations from the design's
//   interface table, the scope constructors and `resolveRepoRoot` needed to
//   call them, every type reachable from one of those signatures, and the
//   guard that narrows an `unknown` payload one of them returns. A new name
//   belongs here only if a consumer calls it or needs it to write a typed
//   call site without an unchecked cast.
// Tier 2 (`export * as <subsystem>`): whole modules a named future consumer
//   must reach into. Add a namespace when a subsystem gains such a consumer;
//   widen a subsystem's own index.ts to add members to an existing one.
// Tier 3 (absent from this file): internal helpers with no named consumer.
//   They stay deep-importable — promote only when a real consumer appears.
//
// Derived-state builders are NOT part of this layer: index rebuild (T-010),
// board render (T-011), and archive lookup (T-032) attach to writes via the
// `onWrite` side-effect seam on `writeEntity` (see WriteOptions).

// --- Tier 1: operations, scope constructors, and their signature types ------

export { resolveRepoRoot, type ExecFileFn } from "./git/index.js";

export {
  projectScope,
  workspaceScope,
  type ScopePaths,
} from "./layout/index.js";

export {
  mintId,
  type ClockFn,
  type MintOptions,
  type MintedId,
  type RandomFn,
} from "./id/index.js";

// Registry types reachable from a tier-1 signature: `EntityType` appears in
// every entity signature, `IdPrefixSpec` in `MintOptions.prefixes`,
// `ValidationRuleSpec` in `ValidateOptions.rules`, and `FindingMode` /
// `FindingSeverity` are required fields of `Finding`. The rest of the
// registry stays in the tier-2 namespace.
export {
  type EntityType,
  type FindingMode,
  type FindingSeverity,
  type IdPrefixSpec,
  type ValidationRuleSpec,
} from "./registry/index.js";

export { type Finding } from "./schema/index.js";

export {
  listEntities,
  readEntity,
  readEntityByPath,
  writeEntity,
  type Entity,
  type EntityFilter,
  type EntityRef,
  type ListResult,
  type ReadResult,
  type WriteEntityInput,
  type WriteEvent,
  type WriteOptions,
  type WriteResult,
} from "./entity/index.js";

export {
  repair,
  validate,
  type RepairMode,
  type RepairOptions,
  type RepairResult,
  type ValidateOptions,
} from "./validator/index.js";

// Payload carried on `Finding.repair` and consumed by `repair()`. The field
// stays `unknown` on purpose — registry-declared rules (Article 003) may carry
// their own payloads — so `isRepairAction` is the checked way in; these types
// are reachable through that guard, not through any signature.
export {
  isRepairAction,
  type RepairAction,
  type ScopeRef,
} from "./validator/rules.js";

// --- Tier 2: subsystems with named future consumers ------------------------

// Declared data other subsystems must read (Article 003 — feature registry;
// T-014/T-015 read the schema, prefix, and rule tables).
export * as registry from "./registry/index.js";
// Path resolution and state-kind rules for the index build (T-010) and the
// board render (T-011).
export * as layout from "./layout/index.js";
// Git seams used by the reconciler (T-030).
export * as git from "./git/index.js";
// Canonical serialization used by the index build (T-010) and board render
// (T-011).
export * as yaml from "./yaml/index.js";
// Field/body validation helpers for authors of new validation rules.
export * as schema from "./schema/index.js";

// Tier 3 (deliberately not exported): `kebabTitle`, `drawSlug`,
// `formatMintDate`, and the remaining `entity`/`validator` internals.
