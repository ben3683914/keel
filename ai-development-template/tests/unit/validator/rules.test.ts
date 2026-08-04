import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import type { Entity } from "../../../src/entity/index.js";
import type { ExecFileFn } from "../../../src/git/index.js";
import { projectScope, workspaceScope } from "../../../src/layout/index.js";
import { ENTITY_SCHEMAS } from "../../../src/registry/index.js";
import {
  articleBand,
  canonicalContentOf,
  checkArticleNumbers,
  checkDanglingRefs,
  checkDuplicateIds,
  checkTrackedState,
  isRepairAction,
  type ScopeEntities,
} from "../../../src/validator/rules.js";

function entity(
  type: Entity["type"],
  path: string,
  data: Record<string, unknown>,
): Entity {
  return { type, path, data, body: "" };
}

function wsScope(root = "/ws"): ScopeEntities {
  return {
    scope: workspaceScope(root),
    scopeRef: { kind: "workspace" },
    tasks: [],
    arcs: [],
    articles: [],
  };
}

describe("checkDuplicateIds", () => {
  it("breaks created-date ties by path (elder = lexically first)", () => {
    const scopeE = wsScope();
    scopeE.tasks = [
      entity("task", "/ws/state/tasks/T-tie00-b.md", {
        id: "T-tie00",
        created: "2026-07-01",
      }),
      entity("task", "/ws/state/tasks/T-tie00-a.md", {
        id: "T-tie00",
        created: "2026-07-01",
      }),
    ];
    const findings = checkDuplicateIds(scopeE);
    expect(findings).toHaveLength(1);
    expect(findings[0]?.file).toBe("state/tasks/T-tie00-b.md");
  });

  it("ignores entities without a string id (V-8's job)", () => {
    const scopeE = wsScope();
    scopeE.tasks = [entity("task", "/ws/state/tasks/x.md", {})];
    expect(checkDuplicateIds(scopeE)).toEqual([]);
  });

  it("emits proposed companions for arc-field references to a duplicated id", () => {
    const scopeE = wsScope();
    scopeE.arcs = [
      entity("arc", "/ws/state/arcs/A-dup01-a.md", {
        id: "A-dup01",
        created: "2026-07-01",
      }),
      entity("arc", "/ws/state/arcs/A-dup01-b.md", {
        id: "A-dup01",
        created: "2026-07-02",
      }),
    ];
    scopeE.tasks = [
      entity("task", "/ws/state/tasks/T-in001-in.md", {
        id: "T-in001",
        arc: "A-dup01",
        created: "2026-07-01",
      }),
    ];
    const findings = checkDuplicateIds(scopeE);
    expect(findings.map((f) => [f.rule, f.mode])).toEqual([
      ["V-1", "silent"],
      ["V-1", "proposed"],
    ]);
    expect(findings[1]?.file).toBe("state/tasks/T-in001-in.md");
    expect(findings[1]?.message).toContain("`arc` is ambiguous");
  });
});

describe("articleBand / checkArticleNumbers", () => {
  it("derives a project band from the declared article_block", () => {
    const scopeE: ScopeEntities = {
      scope: projectScope("/ws", "web", "web"),
      scopeRef: { kind: "project", slug: "web", relPath: "web" },
      tasks: [],
      arcs: [],
      articles: [],
      config: entity("project-config", "/ws/web/state/config.yaml", {
        article_block: 200,
      }),
    };
    expect(articleBand(scopeE)).toEqual({ start: 200, end: 299 });
  });

  it("skips project scopes without a valid article_block", () => {
    const scopeE: ScopeEntities = {
      scope: projectScope("/ws", "web", "web"),
      scopeRef: { kind: "project", slug: "web", relPath: "web" },
      tasks: [],
      arcs: [],
      articles: [
        entity("article", "/ws/web/state/articles/x.md", { number: 9999 }),
      ],
    };
    expect(articleBand(scopeE)).toBeUndefined();
    expect(checkArticleNumbers(scopeE)).toEqual([]);
  });

  it("emits a proposed band-full finding instead of writing out-of-band", () => {
    const scopeE = wsScope();
    // Saturate the workspace band (1–99), then add one duplicate.
    scopeE.articles = Array.from({ length: 99 }, (_, i) =>
      entity(
        "article",
        `/ws/state/articles/a${String(i + 1).padStart(2, "0")}.md`,
        {
          slug: `a${i + 1}`,
          number: i + 1,
          created: "2026-07-01",
        },
      ),
    );
    scopeE.articles.push(
      entity("article", "/ws/state/articles/zz-extra.md", {
        slug: "zz-extra",
        number: 42,
        created: "2026-07-02",
      }),
    );
    const first = checkArticleNumbers(scopeE);
    expect(first).toHaveLength(1);
    expect(first[0]).toMatchObject({ rule: "V-2", mode: "proposed" });
    expect(first[0]?.message).toContain("band 1–99 is full");
    expect(first[0]?.repair).toBeUndefined(); // nothing silent to apply
    // Idempotent: with nothing applied, a second pass is identical and
    // contains no silent work.
    const second = checkArticleNumbers(scopeE);
    expect(second).toEqual(first);
    expect(second.filter((f) => f.mode === "silent")).toEqual([]);
  });

  it("assigns distinct free numbers when several articles collide", () => {
    const scopeE = wsScope();
    scopeE.articles = [1, 2, 3].map((n) =>
      entity("article", `/ws/state/articles/a${n}.md`, {
        slug: `a${n}`,
        number: 7,
        created: `2026-07-0${n}`,
      }),
    );
    const findings = checkArticleNumbers(scopeE);
    expect(findings.map((f) => f.rule)).toEqual(["V-2", "V-2"]);
    const assigned = findings.map(
      (f) => (f.repair as { fields: { number: number } }).fields.number,
    );
    expect(assigned).toEqual([1, 2]);
  });
});

describe("checkDanglingRefs (archive-annotated silent path)", () => {
  it("emits a silent annotate repair when the ref exists in git history", async () => {
    const history = () =>
      Promise.resolve(["state/tasks/T-gone1-old.md"] as const as string[]);
    const scopeE = wsScope();
    scopeE.tasks = [
      entity("task", "/ws/state/tasks/T-ref01-r.md", {
        id: "T-ref01",
        depends_on: ["T-gone1"],
      }),
    ];
    const findings = await checkDanglingRefs(scopeE, history);
    expect(findings[0]).toMatchObject({
      rule: "V-4",
      mode: "silent",
      repair: { action: "annotate-archived-ref", ref: "T-gone1" },
    });
  });

  it("skips refs already annotated resolved-by-archive (idempotence)", async () => {
    const scopeE = wsScope();
    scopeE.tasks = [
      entity("task", "/ws/state/tasks/T-ref01-r.md", {
        id: "T-ref01",
        depends_on: ["T-gone1"],
        ext: { keel: { resolved_by_archive: ["T-gone1"] } },
      }),
    ];
    const findings = await checkDanglingRefs(scopeE, () =>
      Promise.reject(new Error("must not be called")),
    );
    expect(findings).toEqual([]);
  });

  it("flags dangling arc members too", async () => {
    const scopeE = wsScope();
    scopeE.arcs = [
      entity("arc", "/ws/state/arcs/A-arc01-a.md", {
        id: "A-arc01",
        members: ["T-nope0"],
      }),
    ];
    const findings = await checkDanglingRefs(scopeE, () => Promise.resolve([]));
    expect(findings[0]).toMatchObject({ rule: "V-4", mode: "proposed" });
    expect(findings[0]?.message).toContain("members");
  });
});

describe("canonicalContentOf", () => {
  it("reports no-frontmatter for bare markdown", () => {
    const result = canonicalContentOf("plain prose\n", ENTITY_SCHEMAS.task);
    expect(result).toEqual({ ok: false, reason: "no-frontmatter" });
  });

  it("reports parse errors for broken frontmatter", () => {
    const result = canonicalContentOf("---\na: [\n---\n", ENTITY_SCHEMAS.task);
    expect(result).toEqual({ ok: false, reason: "parse-error" });
  });

  it("canonicalizes yaml-format entities without a frontmatter fence", () => {
    const result = canonicalContentOf(
      "name: X\nschema_version: 1\nprojects: {}\n",
      ENTITY_SCHEMAS["workspace-config"],
    );
    expect(result).toEqual({
      ok: true,
      content: "schema_version: 1\nname: X\nprojects: {}\n",
    });
  });
});

describe("checkTrackedState", () => {
  let dir: string | undefined;

  afterEach(async () => {
    if (dir !== undefined) {
      await rm(dir, { recursive: true, force: true });
      dir = undefined;
    }
  });

  it("flags tracked derived/ephemera and binary truth files", async () => {
    dir = await mkdtemp(join(tmpdir(), "keel-v13-"));
    await mkdir(join(dir, "state/tasks"), { recursive: true });
    await writeFile(
      join(dir, "state/tasks/blob.md"),
      Buffer.from([0x68, 0x00, 0x69]),
    );
    const tracked = [
      "board.md",
      ".keel/derived/index.json",
      ".keel/local/scope.yaml",
      "state/tasks/blob.md",
      "state/tasks/deleted-from-worktree.md",
      "src/main.ts",
    ];
    const exec: ExecFileFn = () =>
      Promise.resolve({ stdout: tracked.join("\0") + "\0" });
    const findings = await checkTrackedState(dir, [], exec);
    expect(findings.map((f) => f.file).sort()).toEqual([
      ".keel/derived/index.json",
      ".keel/local/scope.yaml",
      "board.md",
      "state/tasks/blob.md",
    ]);
    expect(findings.every((f) => f.severity === "critical")).toBe(true);
    expect(findings.every((f) => f.mode === "proposed")).toBe(true); // never auto-rm
  });
});

describe("isRepairAction", () => {
  it("accepts each well-formed variant", () => {
    expect(
      isRepairAction({
        action: "remint-id",
        type: "task",
        scope: { kind: "workspace" },
        oldId: "T-abc12",
      }),
    ).toBe(true);
    expect(
      isRepairAction({
        action: "remint-id",
        type: "arc",
        scope: { kind: "project", slug: "web", relPath: "web" },
        oldId: "A-abc12",
      }),
    ).toBe(true);
    expect(
      isRepairAction({ action: "set-fields", type: "task", fields: {} }),
    ).toBe(true);
    expect(
      isRepairAction({
        action: "annotate-archived-ref",
        type: "task",
        ref: "T-gone1",
      }),
    ).toBe(true);
    expect(
      isRepairAction({ action: "rewrite-canonical", type: "article" }),
    ).toBe(true);
  });

  it("rejects the confirmed under-checked payloads", () => {
    // Each of these was accepted by the old "object with string action" guard.
    expect(isRepairAction({ action: "totally-bogus" })).toBe(false);
    expect(isRepairAction({ action: "set-fields" })).toBe(false);
    expect(
      isRepairAction({
        action: "remint-id",
        type: 99,
        scope: null,
        oldId: [],
      }),
    ).toBe(false);
    expect(isRepairAction({})).toBe(false);
    expect(isRepairAction(null)).toBe(false);
    expect(isRepairAction("remint")).toBe(false);
  });

  it("rejects per-variant field defects", () => {
    expect(
      isRepairAction({ action: "set-fields", type: "nope", fields: {} }),
    ).toBe(false);
    expect(
      isRepairAction({ action: "set-fields", type: "task", fields: [] }),
    ).toBe(false);
    expect(
      isRepairAction({ action: "annotate-archived-ref", type: "task" }),
    ).toBe(false);
    expect(isRepairAction({ action: "rewrite-canonical" })).toBe(false);
    // remint-id with a malformed ScopeRef
    expect(
      isRepairAction({
        action: "remint-id",
        type: "task",
        scope: { kind: "project", slug: "web" }, // relPath missing
        oldId: "T-abc12",
      }),
    ).toBe(false);
    expect(
      isRepairAction({
        action: "remint-id",
        type: "doc", // not a task/arc
        scope: { kind: "workspace" },
        oldId: "T-abc12",
      }),
    ).toBe(false);
  });
});
