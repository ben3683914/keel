import { describe, expect, it } from "vitest";

import * as api from "../../src/index.js";
import {
  isRepairAction,
  listEntities,
  mintId,
  projectScope,
  readEntity,
  readEntityByPath,
  repair,
  resolveRepoRoot,
  validate,
  workspaceScope,
  writeEntity,
  type Entity,
  type EntityFilter,
  type EntityRef,
  type EntityType,
  type ExecFileFn,
  type Finding,
  type FindingMode,
  type FindingSeverity,
  type IdPrefixSpec,
  type ListResult,
  type MintOptions,
  type MintedId,
  type ReadResult,
  type RepairAction,
  type RepairMode,
  type RepairOptions,
  type RepairResult,
  type ScopePaths,
  type ScopeRef,
  type ValidateOptions,
  type ValidationRuleSpec,
  type WriteEntityInput,
  type WriteEvent,
  type WriteOptions,
  type WriteResult,
} from "../../src/index.js";

/** Tier 1: the operations a consumer calls, flat on the barrel. */
const TIER_1_OPERATIONS = [
  "mintId",
  "readEntity",
  "readEntityByPath",
  "listEntities",
  "writeEntity",
  "validate",
  "repair",
  "workspaceScope",
  "projectScope",
  "resolveRepoRoot",
  "isRepairAction",
] as const;

/** Tier 2: namespaced subsystems, each with a member proving it is wired. */
const TIER_2_NAMESPACES = {
  registry: "ENTITY_SCHEMAS",
  layout: "stateKindOf",
  git: "lsTrackedFiles",
  yaml: "canonicalYaml",
  schema: "validateData",
} as const;

/** Tier 3: internals that must stay off the barrel (deep-importable only). */
const TIER_3_INTERNALS = [
  "kebabTitle",
  "drawSlug",
  "formatMintDate",
  "rewriteEntityFile",
] as const;

/** Tier-2 members that must not leak back onto the flat surface. */
const NOT_FLAT = [
  "entityDir",
  "derivedPaths",
  "makeFinding",
  "splitFrontmatter",
  "deletedPathsMatching",
  "keyOrderOf",
  "ENTITY_SCHEMAS",
  "VALIDATION_RULES",
] as const;

describe("public API surface", () => {
  it("exports every tier-1 operation as a function", () => {
    for (const name of TIER_1_OPERATIONS) {
      expect(typeof api[name], `${name} must be a tier-1 function`).toBe(
        "function",
      );
    }
  });

  it("exports each tier-2 subsystem as a namespace object", () => {
    for (const [namespace, member] of Object.entries(TIER_2_NAMESPACES)) {
      const subsystem = api[namespace as keyof typeof TIER_2_NAMESPACES];
      expect(typeof subsystem, `${namespace} must be a namespace`).toBe(
        "object",
      );
      expect(subsystem).toHaveProperty(member);
    }
  });

  it("keeps tier-3 internals off the barrel", () => {
    const surface = Object.keys(api);
    for (const name of TIER_3_INTERNALS) {
      expect(surface, `${name} must stay internal`).not.toContain(name);
    }
  });

  it("keeps tier-2 members off the flat surface", () => {
    const surface = Object.keys(api);
    for (const name of NOT_FLAT) {
      expect(surface, `${name} must be namespaced, not flat`).not.toContain(
        name,
      );
    }
    expect(api.registry.ENTITY_SCHEMAS).toBeDefined();
    expect(api.layout.entityDir).toBeTypeOf("function");
  });

  it("exposes the declared-data registries through the registry namespace", () => {
    expect(Object.keys(api.registry.ENTITY_SCHEMAS)).toHaveLength(7);
    expect(api.registry.ID_PREFIXES.length).toBeGreaterThanOrEqual(4);
    expect(api.registry.VALIDATION_RULES.length).toBeGreaterThanOrEqual(14);
  });

  it("types every tier-1 call site from the flat surface alone", () => {
    const scope: ScopePaths = workspaceScope("/tmp/ws");
    const type: EntityType = "task";
    const ref: EntityRef = { scope, type, id: "T-abc12" };
    const filter: EntityFilter = { status: "todo" };
    const exec: ExecFileFn = () => Promise.resolve({ stdout: "" });
    const finding: Finding = {
      rule: "V-8",
      ruleId: "missing-required-field",
      mode: "proposed",
      severity: "error",
      file: "x.md",
      message: "m",
    };
    const entity: Entity = { type, path: "x.md", data: {}, body: "" };
    const read: ReadResult = { entity, findings: [finding] };
    const seen: WriteEvent[] = [];
    const writeOptions: WriteOptions = {
      onWrite: (event: WriteEvent) => {
        seen.push(event);
      },
    };
    const input: WriteEntityInput = { scope, type, data: {}, body: "" };
    const writeResult: WriteResult = { ok: true, path: "x.md", findings: [] };
    const mintOptions: MintOptions = {
      rng: () => 0.5,
      clock: () => new Date(),
    };
    const minted: MintedId = { id: "T-abc12", created: "2026-08-04" };
    const validateOptions: ValidateOptions = {
      workspaceRoot: scope.workspaceRoot,
      exec,
    };
    const mode: RepairMode = "proposed";
    const repairOptions: RepairOptions = { workspaceRoot: scope.workspaceRoot };
    const repairResult: RepairResult = {
      applied: [],
      proposals: [finding],
      skipped: [],
    };
    const scopeRef: ScopeRef = { kind: "workspace" };
    const action: RepairAction = {
      action: "remint-id",
      type: "task",
      scope: scopeRef,
      oldId: "T-abc12",
    };
    const listResult: ListResult = { entities: [entity], findings: [] };
    const findingMode: FindingMode = "proposed";
    const findingSeverity: FindingSeverity = "error";
    const prefix: IdPrefixSpec = {
      prefix: "T",
      entityType: type,
      category: "task",
    };
    const rule: ValidationRuleSpec = {
      rule: "V-8",
      id: "missing-required-field",
      modes: [findingMode],
      severity: findingSeverity,
      description: "d",
    };

    // Every tier-1 operation, called for real. These arrows are typechecked
    // but never invoked: the assertion is that each call compiles against the
    // barrel alone, with its return type nameable from the barrel alone. A
    // signature that drifts to an unexported type fails `npm run typecheck`.
    const callSites = [
      (): Promise<MintedId> =>
        mintId(prefix.prefix, scope, { ...mintOptions, prefixes: [prefix] }),
      (): Promise<ReadResult> => readEntity(ref),
      (): Promise<ReadResult> =>
        readEntityByPath("x.md", type, scope.workspaceRoot),
      (): Promise<ListResult> => listEntities(scope, type, filter),
      (): Promise<WriteResult> => writeEntity(input, writeOptions),
      (): Promise<Finding[]> => validate({ ...validateOptions, rules: [rule] }),
      (): Promise<RepairResult> => repair([finding], mode, repairOptions),
      (): ScopePaths => workspaceScope(scope.workspaceRoot),
      (): ScopePaths => projectScope(scope.workspaceRoot, "demo", "demo"),
      (): Promise<string> => resolveRepoRoot(scope.workspaceRoot, exec),
      // The only unchecked-cast-free path from `Finding.repair` (`unknown`)
      // to `RepairAction` — the reason both are tier 1.
      (): RepairAction | undefined =>
        isRepairAction(finding.repair) ? finding.repair : undefined,
    ] as const;

    expect(callSites).toHaveLength(TIER_1_OPERATIONS.length);
    expect(ref.id).toBe("T-abc12");
    expect(filter).toEqual({ status: "todo" });
    expect(read.entity?.type).toBe("task");
    expect(writeOptions.onWrite).toBeTypeOf("function");
    expect(input.scope.kind).toBe("workspace");
    expect(writeResult.ok).toBe(true);
    expect(mintOptions.rng?.()).toBe(0.5);
    expect(minted.created).toBe("2026-08-04");
    expect(validateOptions.exec).toBe(exec);
    expect(mode).toBe("proposed");
    expect(repairOptions.workspaceRoot).toBe(scope.workspaceRoot);
    expect(repairResult.proposals).toHaveLength(1);
    expect(action.action).toBe("remint-id");
    expect(listResult.entities).toHaveLength(1);
    expect(rule.modes).toContain(findingMode);
    expect(seen).toHaveLength(0);
  });

  it("narrows a repair payload through the exported guard", () => {
    const action: RepairAction = { action: "rewrite-canonical", type: "task" };
    const finding: Finding = {
      rule: "V-12",
      ruleId: "non-canonical-serialization",
      mode: "silent",
      severity: "warning",
      file: "x.md",
      message: "m",
      repair: action,
    };

    expect(isRepairAction(finding.repair)).toBe(true);
    expect(isRepairAction(undefined)).toBe(false);
    expect(isRepairAction({ noAction: true })).toBe(false);
    if (isRepairAction(finding.repair)) {
      expect(finding.repair.action).toBe("rewrite-canonical");
    }
  });
});
