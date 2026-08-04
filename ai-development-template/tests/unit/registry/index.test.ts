import { describe, expect, it } from "vitest";

import {
  ARTICLE_CATEGORIES,
  ENTITY_SCHEMAS,
  ID_PREFIXES,
  ID_SLUG_ALPHABET,
  ID_SLUG_LENGTH,
  TASK_STATUSES,
  VALIDATION_RULES,
  WORKSPACE_ARTICLE_BAND,
  keyOrderOf,
  prefixSpec,
  ruleSpec,
  type IdPrefixSpec,
  type ValidationRuleSpec,
} from "../../../src/registry/index.js";
import {
  STATE_KIND_RULES,
  type StateKindRule,
} from "../../../src/layout/index.js";

describe("entity schema registry", () => {
  it("declares all seven entity types from the design doc", () => {
    expect(Object.keys(ENTITY_SCHEMAS).sort()).toEqual([
      "arc",
      "article",
      "curation",
      "doc",
      "project-config",
      "task",
      "workspace-config",
    ]);
  });

  it("declares the task field table exactly", () => {
    expect(ENTITY_SCHEMAS.task.fields.map((f) => f.name)).toEqual([
      "id",
      "title",
      "status",
      "category",
      "priority",
      "arc",
      "assignee",
      "depends_on",
      "provenance",
      "created",
      "ext",
    ]);
    const status = ENTITY_SCHEMAS.task.fields.find((f) => f.name === "status");
    expect(status?.default).toBe("todo");
    expect(status?.enumValues).toContain("awaiting-validation");
    const category = ENTITY_SCHEMAS.task.fields.find(
      (f) => f.name === "category",
    );
    expect(category?.required).toBe(true);
    expect(category?.default).toBeUndefined();
  });

  it("gives every markdown work item id-or-slug identity and ext last", () => {
    expect(ENTITY_SCHEMAS.task.identity).toBe("id");
    expect(ENTITY_SCHEMAS.arc.identity).toBe("id");
    expect(ENTITY_SCHEMAS.article.identity).toBe("slug");
    for (const schema of Object.values(ENTITY_SCHEMAS)) {
      expect(keyOrderOf(schema).at(-1)).toBe("ext");
    }
  });

  it("requires all four article body sections at ratification only", () => {
    expect(ENTITY_SCHEMAS.article.body).toEqual({
      requiredSections: ["Context", "Rule", "Consequences", "Enforcement"],
      when: { field: "status", equals: "ratified" },
    });
  });

  it("keeps docs the only entity with an updated field", () => {
    for (const [type, schema] of Object.entries(ENTITY_SCHEMAS)) {
      const hasUpdated = schema.fields.some((f) => f.name === "updated");
      expect(hasUpdated, type).toBe(type === "doc");
    }
  });
});

describe("shipped tables are immutable at runtime", () => {
  // `readonly` erases at compile time; these tables are security controls
  // (a mutated VALIDATION_RULES silently disables a rule for every later
  // validate() call). Freezing is asserted so a future table edit that drops
  // deepFreeze fails here instead of shipping soft.
  it("freezes every shipped table and its nested members", () => {
    for (const table of [
      ARTICLE_CATEGORIES,
      TASK_STATUSES,
      ID_PREFIXES,
      VALIDATION_RULES,
      STATE_KIND_RULES,
    ]) {
      expect(Object.isFrozen(table)).toBe(true);
      for (const entry of table) expect(Object.isFrozen(entry)).toBe(true);
    }
    expect(Object.isFrozen(ENTITY_SCHEMAS)).toBe(true);
    for (const schema of Object.values(ENTITY_SCHEMAS)) {
      expect(Object.isFrozen(schema)).toBe(true);
      expect(Object.isFrozen(schema.fields)).toBe(true);
      for (const field of schema.fields)
        expect(Object.isFrozen(field)).toBe(true);
      if (schema.body) {
        expect(Object.isFrozen(schema.body)).toBe(true);
        expect(Object.isFrozen(schema.body.requiredSections)).toBe(true);
      }
    }
  });

  it("rejects the confirmed tampering PoCs", () => {
    // Each of these silently disabled a control before freezing.
    expect(() =>
      (VALIDATION_RULES as ValidationRuleSpec[]).splice(0, 20),
    ).toThrow();
    expect(() => (STATE_KIND_RULES as StateKindRule[]).splice(0)).toThrow();
    expect(() =>
      (ID_PREFIXES as IdPrefixSpec[]).push({
        prefix: "../../evil",
        entityType: "task",
        category: "task",
      }),
    ).toThrow();
    expect(() => {
      const field = ENTITY_SCHEMAS.task.fields.find((f) => f.name === "id");
      (field as { required: boolean }).required = false;
    }).toThrow();
    // …and the tables still hold their shipped contents.
    expect(VALIDATION_RULES.length).toBeGreaterThanOrEqual(14);
    expect(ID_PREFIXES.map((p) => p.prefix)).toEqual(["T", "B", "S", "A"]);
    expect(
      ENTITY_SCHEMAS.task.fields.find((f) => f.name === "id")?.required,
    ).toBe(true);
  });

  it("still honors caller-supplied override tables (Article 003 seam)", () => {
    // Freezing the shipped defaults must not freeze the override path.
    const custom = [...VALIDATION_RULES.filter((r) => r.rule !== "V-11")];
    custom.push({
      rule: "V-99",
      id: "custom-rule",
      modes: ["proposed"],
      severity: "info",
      description: "user-authored",
    });
    expect(Object.isFrozen(custom)).toBe(false);
    expect(ruleSpec("V-99", custom)?.id).toBe("custom-rule");
    expect(ruleSpec("V-11", custom)).toBeUndefined();

    const prefixes = [
      ...ID_PREFIXES,
      { prefix: "E", entityType: "task", category: "task" } as const,
    ];
    expect(prefixSpec("E", prefixes)?.prefix).toBe("E");
  });
});

describe("id prefix table", () => {
  it("declares T/B/S for tasks and A for arcs", () => {
    expect(ID_PREFIXES.map((p) => p.prefix)).toEqual(["T", "B", "S", "A"]);
    expect(prefixSpec("S")?.category).toBe("security");
    expect(prefixSpec("A")?.entityType).toBe("arc");
    expect(prefixSpec("X")).toBeUndefined();
  });

  it("is extensible by passing a wider table (Article 003)", () => {
    const extended = [
      ...ID_PREFIXES,
      { prefix: "E", entityType: "task", category: "task" } as const,
    ];
    expect(prefixSpec("E", extended)?.prefix).toBe("E");
  });
});

describe("id slug alphabet", () => {
  it("is 32 lowercase Crockford-style symbols excluding i l o u", () => {
    expect(ID_SLUG_ALPHABET).toHaveLength(32);
    expect(new Set(ID_SLUG_ALPHABET).size).toBe(32);
    for (const banned of ["i", "l", "o", "u"]) {
      expect(ID_SLUG_ALPHABET).not.toContain(banned);
    }
    expect(ID_SLUG_ALPHABET).toBe(ID_SLUG_ALPHABET.toLowerCase());
    expect(ID_SLUG_LENGTH).toBe(5);
  });
});

describe("validation rule config", () => {
  it("declares the full V-1..V-13 table plus the quarantine backstop", () => {
    const rules = VALIDATION_RULES.map((r) => r.rule);
    expect(rules).toContain("quarantine");
    for (let i = 1; i <= 13; i++) expect(rules).toContain(`V-${i}`);
  });

  it("marks workspace-internal-paths as the liftable declared rule", () => {
    const v11 = ruleSpec("V-11");
    expect(v11?.id).toBe("workspace-internal-paths");
    expect(v11?.liftable).toBe(true);
  });

  it("modes match the design table", () => {
    expect(ruleSpec("V-1")?.modes).toEqual(["silent", "proposed"]);
    expect(ruleSpec("V-6")?.modes).toEqual(["proposed"]);
    expect(ruleSpec("V-8")?.modes).toEqual(["reject", "proposed"]);
    expect(ruleSpec("V-13")?.severity).toBe("critical");
  });

  it("lifting a rule is a data change: ruleSpec on a filtered copy", () => {
    const lifted = VALIDATION_RULES.filter((r) => r.rule !== "V-11");
    expect(ruleSpec("V-11", lifted)).toBeUndefined();
    expect(ruleSpec("V-12", lifted)).toBeDefined();
  });

  it("workspace article band is 1-99", () => {
    expect(WORKSPACE_ARTICLE_BAND).toEqual({ start: 1, end: 99 });
  });
});
