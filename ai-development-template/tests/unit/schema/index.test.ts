import { describe, expect, it } from "vitest";

import { ENTITY_SCHEMAS } from "../../../src/registry/index.js";
import {
  applyDefaults,
  makeFinding,
  validateBody,
  validateData,
} from "../../../src/schema/index.js";

const task = ENTITY_SCHEMAS.task;

const validTask = {
  id: "T-abc12",
  title: "Fix the widget",
  status: "todo",
  category: "task",
  priority: "P1",
  created: "2026-07-29",
};

describe("applyDefaults", () => {
  it("fills declared defaults for absent fields only", () => {
    const out = applyDefaults({ id: "T-abc12", status: "working" }, task);
    expect(out["status"]).toBe("working");
    expect(out["depends_on"]).toEqual([]);
    expect(out["provenance"]).toEqual({ source: "user" });
  });

  it("clones defaults so instances never share state", () => {
    const a = applyDefaults({}, task);
    const b = applyDefaults({}, task);
    (a["depends_on"] as string[]).push("T-zzzzz");
    expect(b["depends_on"]).toEqual([]);
  });

  it("never mutates its input", () => {
    const input = { id: "T-abc12" };
    applyDefaults(input, task);
    expect(input).toEqual({ id: "T-abc12" });
  });
});

describe("validateData", () => {
  it("accepts a fully valid task", () => {
    expect(validateData(validTask, task, "f.md", "on-disk")).toEqual([]);
  });

  it("flags unknown bare keys as V-7 proposed, suggesting ext:", () => {
    const findings = validateData(
      { ...validTask, statuss: "todo" },
      task,
      "f.md",
      "on-disk",
    );
    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({
      rule: "V-7",
      ruleId: "unknown-frontmatter-key",
      mode: "proposed",
    });
    expect(findings[0]?.proposedFix).toMatch(/ext:/);
  });

  it("V-8 missing required field: reject at engine-write, proposed on-disk", () => {
    const data = { ...validTask } as Record<string, unknown>;
    delete data["priority"];
    const write = validateData(data, task, "f.md", "engine-write");
    expect(write[0]).toMatchObject({ rule: "V-8", mode: "reject" });
    const disk = validateData(data, task, "f.md", "on-disk");
    expect(disk[0]).toMatchObject({ rule: "V-8", mode: "proposed" });
  });

  it("V-9 invalid enum value carries the allowed values", () => {
    const findings = validateData(
      { ...validTask, status: "doing" },
      task,
      "f.md",
      "engine-write",
    );
    expect(findings[0]).toMatchObject({ rule: "V-9", mode: "reject" });
    expect(findings[0]?.proposedFix).toContain("todo");
  });

  it("checks field shapes: date, int, arrays, mappings", () => {
    const bad = validateData(
      { ...validTask, created: "yesterday", depends_on: "T-x" },
      task,
      "f.md",
      "on-disk",
    );
    expect(bad.map((f) => f.rule).sort()).toEqual(["V-8", "V-8"]);
    const doc = validateData(
      { version: "1.0", updated: "2026-07-29", status: "Draft" },
      ENTITY_SCHEMAS.doc,
      "d.md",
      "on-disk",
    );
    expect(doc[0]?.message).toMatch(/version/);
    const article = validateData(
      { number: "one" },
      ENTITY_SCHEMAS.article,
      "a.md",
      "on-disk",
    );
    expect(article.some((f) => f.message.includes("must be an integer"))).toBe(
      true,
    );
  });

  it("bool and object-array shapes validate", () => {
    const doc = validateData(
      {
        version: "1.0.0",
        updated: "2026-07-29",
        status: "Draft",
        load_at_start: "yes",
      },
      ENTITY_SCHEMAS.doc,
      "d.md",
      "on-disk",
    );
    expect(doc[0]?.message).toMatch(/boolean/);
    const article = validateData(
      {
        slug: "keel/x",
        number: 1,
        title: "X",
        status: "proposed",
        category: "design",
        triggers: ["commit"],
        provenance: { source: "local" },
        created: "2026-07-29",
        amendments: ["not-an-object"],
      },
      ENTITY_SCHEMAS.article,
      "a.md",
      "on-disk",
    );
    expect(article[0]?.message).toMatch(/list of mappings/);
  });

  it("leaves undeclared ext: content untouched (no findings)", () => {
    const findings = validateData(
      { ...validTask, ext: { "azure-devops": { work_item: 4412 } } },
      task,
      "f.md",
      "on-disk",
    );
    expect(findings).toEqual([]);
  });

  it("validates declared ext block schemas (feature-registry seam)", () => {
    const extSchemas = {
      "azure-devops": [
        { name: "work_item", type: "int", required: true } as const,
      ],
    };
    const good = validateData(
      { ...validTask, ext: { "azure-devops": { work_item: 4412 } } },
      task,
      "f.md",
      "on-disk",
      { extSchemas },
    );
    expect(good).toEqual([]);
    const missing = validateData(
      { ...validTask, ext: { "azure-devops": {} } },
      task,
      "f.md",
      "on-disk",
      { extSchemas },
    );
    expect(missing[0]?.message).toContain("ext.azure-devops.work_item");
    const wrongShape = validateData(
      { ...validTask, ext: { "azure-devops": "nope" } },
      task,
      "f.md",
      "on-disk",
      { extSchemas },
    );
    expect(wrongShape[0]?.message).toMatch(/must be a mapping/);
    const wrongType = validateData(
      { ...validTask, ext: { "azure-devops": { work_item: "4412" } } },
      task,
      "f.md",
      "on-disk",
      { extSchemas },
    );
    expect(wrongType[0]?.message).toMatch(/integer/);
  });
});

describe("validateBody", () => {
  const article = ENTITY_SCHEMAS.article;

  it("requires all four sections at ratification", () => {
    const body = "## Context\nx\n\n## Rule\ny\n";
    const findings = validateBody(
      body,
      { status: "ratified" },
      article,
      "a.md",
      "engine-write",
    );
    expect(findings.map((f) => f.message)).toEqual([
      expect.stringContaining("Consequences"),
      expect.stringContaining("Enforcement"),
    ]);
    expect(findings[0]?.mode).toBe("reject");
  });

  it("does not apply the contract before ratification", () => {
    expect(
      validateBody("", { status: "proposed" }, article, "a.md", "on-disk"),
    ).toEqual([]);
  });

  it("passes with all sections present, and skips types without contracts", () => {
    const full =
      "## Context\na\n## Rule\nb\n## Consequences\nc\n## Enforcement\nd\n";
    expect(
      validateBody(full, { status: "ratified" }, article, "a.md", "on-disk"),
    ).toEqual([]);
    expect(
      validateBody("", {}, ENTITY_SCHEMAS.task, "t.md", "on-disk"),
    ).toEqual([]);
  });
});

describe("makeFinding", () => {
  it("resolves ruleId and severity from the declared table", () => {
    const finding = makeFinding("V-13", "proposed", "board.md", "tracked");
    expect(finding.ruleId).toBe("tracked-derived-or-binary");
    expect(finding.severity).toBe("critical");
  });

  it("falls back to the rule name for undeclared rules", () => {
    const finding = makeFinding("V-99", "proposed", "", "mystery", { line: 3 });
    expect(finding.ruleId).toBe("V-99");
    expect(finding.line).toBe(3);
  });
});
