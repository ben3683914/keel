import {
  mkdtemp,
  readFile,
  readdir,
  rm,
  symlink,
  writeFile,
  mkdir,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, relative, sep } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  kebabTitle,
  listEntities,
  readEntity,
  readEntityByPath,
  rewriteEntityFile,
  writeEntity,
  type WriteEvent,
} from "../../../src/entity/index.js";
import { workspaceScope, type ScopePaths } from "../../../src/layout/index.js";

let root: string;
let scope: ScopePaths;

beforeEach(async () => {
  root = await mkdtemp(join(tmpdir(), "keel-entity-"));
  scope = workspaceScope(root);
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

const validTask = {
  id: "T-abc12",
  title: "Fix the widget",
  category: "task",
  priority: "P1",
  created: "2026-07-29",
};

describe("kebabTitle", () => {
  it("kebab-cases titles for the filename courtesy suffix", () => {
    expect(kebabTitle("Fix the Widget!")).toBe("fix-the-widget");
    expect(kebabTitle("  ---  ")).toBe("");
    expect(kebabTitle("a".repeat(100))).toHaveLength(60);
  });
});

describe("writeEntity", () => {
  it("applies defaults at write time and lands the canonical file", async () => {
    const result = await writeEntity({
      scope,
      type: "task",
      data: { ...validTask },
      body: "Some context.",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.path).toBe(join(scope.tasksDir, "T-abc12-fix-the-widget.md"));
    const raw = await readFile(result.path, "utf8");
    expect(raw).toBe(
      [
        "---",
        "id: T-abc12",
        "title: Fix the widget",
        "status: todo",
        "category: task",
        "priority: P1",
        "depends_on: []",
        "provenance:",
        "  source: user",
        "created: 2026-07-29",
        "---",
        "",
        "Some context.",
        "",
      ].join("\n"),
    );
  });

  it("is byte-identical across repeated writes of identical input", async () => {
    const input = { scope, type: "task" as const, data: { ...validTask } };
    const first = await writeEntity(input);
    if (!first.ok) throw new Error("write failed");
    const bytes1 = await readFile(first.path, "utf8");
    const second = await writeEntity(input);
    if (!second.ok) throw new Error("write failed");
    const bytes2 = await readFile(second.path, "utf8");
    expect(bytes2).toBe(bytes1);
  });

  it("REJECTS invalid engine writes with the finding list, writing nothing", async () => {
    const result = await writeEntity({
      scope,
      type: "task",
      data: { id: "T-abc12", title: "No category", created: "2026-07-29" },
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.findings.some((f) => f.mode === "reject")).toBe(true);
    await expect(readdir(scope.tasksDir)).rejects.toThrow(); // dir never created
  });

  it("rejects article writes missing required body sections at ratification", async () => {
    const result = await writeEntity({
      scope,
      type: "article",
      data: {
        slug: "keel/test-rule",
        number: 7,
        title: "Test rule",
        status: "ratified",
        category: "design",
        triggers: ["commit"],
        provenance: { source: "local" },
        created: "2026-07-29",
      },
      body: "## Context\nx\n",
    });
    expect(result.ok).toBe(false);
  });

  it("renames the file on retitle — id stays the identity", async () => {
    await writeEntity({ scope, type: "task", data: { ...validTask } });
    const result = await writeEntity({
      scope,
      type: "task",
      data: { ...validTask, title: "Renamed entirely" },
    });
    expect(result.ok).toBe(true);
    const names = await readdir(scope.tasksDir);
    expect(names).toEqual(["T-abc12-renamed-entirely.md"]);
  });

  it("preserves hand-added YAML comments across engine rewrites", async () => {
    await writeEntity({ scope, type: "task", data: { ...validTask } });
    const path = join(scope.tasksDir, "T-abc12-fix-the-widget.md");
    const raw = await readFile(path, "utf8");
    await writeFile(
      path,
      raw.replace("priority: P1", "# escalated by ops\npriority: P1"),
    );
    const result = await writeEntity({
      scope,
      type: "task",
      data: { ...validTask, status: "working" },
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const rewritten = await readFile(result.path, "utf8");
    expect(rewritten).toContain("# escalated by ops\npriority: P1");
    expect(rewritten).toContain("status: working");
  });

  it("preserves ext: content untouched across rewrites", async () => {
    const ext = { "azure-devops": { work_item: 4412 } };
    await writeEntity({ scope, type: "task", data: { ...validTask, ext } });
    const result = await writeEntity({
      scope,
      type: "task",
      data: { ...validTask, ext, status: "done" },
    });
    if (!result.ok) throw new Error("write failed");
    const read = await readEntity({ scope, type: "task", id: "T-abc12" });
    expect(read.entity?.data["ext"]).toEqual(ext);
  });

  it("fires the onWrite side-effect seam (T-010/T-011 attach here)", async () => {
    const events: WriteEvent[] = [];
    const result = await writeEntity(
      { scope, type: "task", data: { ...validTask } },
      { onWrite: (e) => void events.push(e) },
    );
    expect(result.ok).toBe(true);
    expect(events).toHaveLength(1);
    expect(events[0]?.path).toBe(result.ok ? result.path : "");
    expect(events[0]?.entity.data["id"]).toBe("T-abc12");
  });

  it("REJECTS the confirmed id-traversal exploit, writing nothing outside", async () => {
    // Confirmed exploit: id `../../../../tmp/keel-pwned` wrote /tmp/keel-pwned-hi.md.
    const victimDir = await mkdtemp(join(tmpdir(), "keel-victim-"));
    try {
      const hops = relative(scope.tasksDir, victimDir).split(sep).join("/");
      const result = await writeEntity({
        scope,
        type: "task",
        data: { ...validTask, id: `${hops}/keel-pwned` },
        body: "hi",
      });
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.findings.some((f) => f.mode === "reject")).toBe(true);
        expect(result.findings[0]?.message).toMatch(/Invalid id/);
      }
      await expect(readdir(victimDir)).resolves.toEqual([]);
    } finally {
      await rm(victimDir, { recursive: true, force: true });
    }
  });

  it("rejects ids that do not match the declared prefix/slug format", async () => {
    for (const bad of [
      "T-abc1", // too short
      "T-abcdef", // too long
      "T-abciu", // excluded letters
      "X-abc12", // undeclared prefix
      "T_abc12", // wrong separator
      "../T-abc12",
    ]) {
      const result = await writeEntity({
        scope,
        type: "task",
        data: { ...validTask, id: bad },
      });
      expect(result.ok, bad).toBe(false);
    }
  });

  it("REJECTS the confirmed absolute-path doc write outside the workspace", async () => {
    const victimDir = await mkdtemp(join(tmpdir(), "keel-victim-"));
    try {
      const target = join(victimDir, "pwned.md");
      const result = await writeEntity({
        scope,
        type: "doc",
        data: { version: "1.0.0", updated: "2026-07-29", status: "Draft" },
        body: "# Pwned",
        path: target,
      });
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.findings[0]?.mode).toBe("reject");
        expect(result.findings[0]?.message).toMatch(/outside the workspace/);
      }
      await expect(readdir(victimDir)).resolves.toEqual([]);
    } finally {
      await rm(victimDir, { recursive: true, force: true });
    }
  });

  it("rejects doc writes escaping via .. inside a workspace-relative path", async () => {
    const result = await writeEntity({
      scope,
      type: "doc",
      data: { version: "1.0.0", updated: "2026-07-29", status: "Draft" },
      path: join(scope.docsDir, "../../../escaped.md"),
    });
    expect(result.ok).toBe(false);
  });

  it("returns V-7 findings alongside success for unknown keys", async () => {
    const result = await writeEntity({
      scope,
      type: "task",
      data: { ...validTask, statuss: "todo" },
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.findings.map((f) => f.rule)).toEqual(["V-7"]);
    }
  });

  it("writes nested article slugs inside the articles tree only", async () => {
    const result = await writeEntity({
      scope,
      type: "article",
      data: {
        slug: "keel/engine-data-separation",
        number: 1,
        title: "Engine/Data Separation",
        status: "proposed",
        category: "design",
        triggers: ["code-review"],
        provenance: { source: "framework" },
        created: "2026-07-29",
      },
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.path).toBe(
        join(scope.articlesDir, "keel/engine-data-separation.md"),
      );
    }
    await expect(
      writeEntity({
        scope,
        type: "article",
        data: {
          slug: "../../escape",
          number: 2,
          title: "Nope",
          status: "proposed",
          category: "design",
          triggers: ["commit"],
          provenance: { source: "local" },
          created: "2026-07-29",
        },
      }),
    ).rejects.toThrow(/escapes/);
  });

  it("writes configs and curation to their fixed yaml paths", async () => {
    const result = await writeEntity({
      scope,
      type: "workspace-config",
      data: {
        schema_version: 1,
        name: "Demo",
        projects: { web: { path: "web" } },
      },
    });
    expect(result.ok).toBe(true);
    const raw = await readFile(scope.configPath, "utf8");
    expect(raw).toContain("schema_version: 1");
    expect(raw).not.toContain("---");
  });

  it("requires an explicit path for doc writes", async () => {
    await expect(
      writeEntity({
        scope,
        type: "doc",
        data: { version: "1.0.0", updated: "2026-07-29", status: "Draft" },
      }),
    ).rejects.toThrow(/path/);
    const target = join(scope.docsDir, "guides/setup.md");
    const result = await writeEntity({
      scope,
      type: "doc",
      data: { version: "1.0.0", updated: "2026-07-29", status: "Draft" },
      body: "# Setup",
      path: target,
    });
    expect(result.ok).toBe(true);
  });
});

describe("readEntity / readEntityByPath", () => {
  it("reads back what was written (round trip)", async () => {
    await writeEntity({
      scope,
      type: "task",
      data: { ...validTask },
      body: "Context.",
    });
    const read = await readEntity({ scope, type: "task", id: "T-abc12" });
    expect(read.findings).toEqual([]);
    expect(read.entity?.data["title"]).toBe("Fix the widget");
    expect(read.entity?.body).toBe("Context.\n");
  });

  it("resolves by id even when the kebab-title differs (id is identity)", async () => {
    await mkdir(scope.tasksDir, { recursive: true });
    await writeFile(
      join(scope.tasksDir, "T-abc12-totally-different-name.md"),
      "---\nid: T-abc12\ntitle: X\nstatus: todo\ncategory: task\npriority: P2\ncreated: 2026-07-29\n---\n",
    );
    const read = await readEntity({ scope, type: "task", id: "T-abc12" });
    expect(read.entity?.data["id"]).toBe("T-abc12");
  });

  it("resolves a fully misnamed file via frontmatter id", async () => {
    await mkdir(scope.tasksDir, { recursive: true });
    await writeFile(
      join(scope.tasksDir, "B-zzzzz-wrong-prefix-name.md"),
      "---\nid: T-abc12\ntitle: X\nstatus: todo\ncategory: task\npriority: P2\ncreated: 2026-07-29\n---\n",
    );
    const read = await readEntity({ scope, type: "task", id: "T-abc12" });
    expect(read.entity?.data["id"]).toBe("T-abc12");
  });

  it("returns no entity and no findings for a missing id", async () => {
    const read = await readEntity({ scope, type: "task", id: "T-nope0" });
    expect(read.entity).toBeUndefined();
    expect(read.findings).toEqual([]);
  });

  it("rejects article reads whose slug escapes the articles directory", async () => {
    await expect(
      readEntity({ scope, type: "article", id: "../../escape" }),
    ).rejects.toThrow(/escapes/);
  });

  it("quarantines unparseable YAML as a finding with file and line", async () => {
    await mkdir(scope.tasksDir, { recursive: true });
    const path = join(scope.tasksDir, "T-bad00-broken.md");
    await writeFile(path, "---\nid: [broken\ntitle: :\n---\n");
    const read = await readEntityByPath(path, "task", root);
    expect(read.entity).toBeUndefined();
    expect(read.findings[0]).toMatchObject({
      ruleId: "unparseable-yaml",
      file: "state/tasks/T-bad00-broken.md",
    });
    expect(read.findings[0]?.line).toBeTypeOf("number");
  });

  it("reports on-disk schema problems as proposed findings, never defaults", async () => {
    await mkdir(scope.tasksDir, { recursive: true });
    const path = join(scope.tasksDir, "T-mis00-missing.md");
    await writeFile(
      path,
      "---\nid: T-mis00\ntitle: No status\ncategory: task\npriority: P1\ncreated: 2026-07-29\n---\n",
    );
    const read = await readEntityByPath(path, "task", root);
    expect(read.entity?.data["status"]).toBeUndefined();
    expect(
      read.findings.some((f) => f.rule === "V-8" && f.mode === "proposed"),
    ).toBe(true);
  });

  it("accepts docs without frontmatter (adapt, don't enforce)", async () => {
    await mkdir(scope.docsDir, { recursive: true });
    const path = join(scope.docsDir, "legacy.md");
    await writeFile(path, "# Legacy doc\nNo frontmatter here.\n");
    const read = await readEntityByPath(path, "doc", root);
    expect(read.findings).toEqual([]);
    expect(read.entity?.data).toEqual({});
  });

  it("flags state entities without frontmatter as missing required fields", async () => {
    await mkdir(scope.tasksDir, { recursive: true });
    const path = join(scope.tasksDir, "T-raw00-raw.md");
    await writeFile(path, "just prose\n");
    const read = await readEntityByPath(path, "task", root);
    expect(read.findings.some((f) => f.rule === "V-8")).toBe(true);
  });
});

describe("listEntities", () => {
  it("lists a scope's entities with filters, surfacing findings", async () => {
    await writeEntity({ scope, type: "task", data: { ...validTask } });
    await writeEntity({
      scope,
      type: "task",
      data: { ...validTask, id: "T-def34", title: "Another", status: "done" },
    });
    await mkdir(scope.tasksDir, { recursive: true });
    await writeFile(
      join(scope.tasksDir, "T-bad00-broken.md"),
      "---\nid: [\n---\n",
    );

    const all = await listEntities(scope, "task");
    expect(all.entities).toHaveLength(2);
    expect(all.findings.map((f) => f.ruleId)).toEqual(["unparseable-yaml"]);

    const done = await listEntities(scope, "task", { status: "done" });
    expect(done.entities.map((e) => e.data["id"])).toEqual(["T-def34"]);

    const byPredicate = await listEntities(
      scope,
      "task",
      (e) => e.data["id"] === "T-abc12",
    );
    expect(byPredicate.entities).toHaveLength(1);
  });

  it("does not follow symlinked entity files, and reports them", async () => {
    const outside = await mkdtemp(join(tmpdir(), "keel-outside-"));
    try {
      await writeFile(
        join(outside, "secret.md"),
        "---\nid: T-secr1\ntitle: Secret\nstatus: todo\ncategory: task\npriority: P1\ncreated: 2026-07-29\n---\n",
      );
      await mkdir(scope.tasksDir, { recursive: true });
      await symlink(
        join(outside, "secret.md"),
        join(scope.tasksDir, "T-link1-linked.md"),
      );
      const result = await listEntities(scope, "task");
      expect(result.entities).toEqual([]); // never read through the link
      expect(result.findings.map((f) => f.ruleId)).toEqual([
        "symlinked-state-file",
      ]);
      expect(result.findings[0]?.file).toBe("state/tasks/T-link1-linked.md");
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it("returns empty for an absent directory", async () => {
    const result = await listEntities(scope, "arc");
    expect(result.entities).toEqual([]);
    expect(result.findings).toEqual([]);
  });
});

describe("rewriteEntityFile", () => {
  it("mutates data, preserves comments, and can rename atomically", async () => {
    await mkdir(scope.tasksDir, { recursive: true });
    const path = join(scope.tasksDir, "T-abc12-old.md");
    await writeFile(
      path,
      "---\n# keep me\nid: T-abc12\ntitle: Old\nstatus: todo\ncategory: task\npriority: P1\ncreated: 2026-07-29\n---\n\nBody.\n",
    );
    const renamed = join(scope.tasksDir, "T-new99-old.md");
    await rewriteEntityFile(
      root,
      path,
      "task",
      (data) => ({ ...data, id: "T-new99" }),
      renamed,
    );
    const names = await readdir(scope.tasksDir);
    expect(names).toEqual(["T-new99-old.md"]);
    const raw = await readFile(renamed, "utf8");
    expect(raw).toContain("# keep me");
    expect(raw).toContain("id: T-new99");
    expect(raw).toContain("Body.");
  });

  it("refuses files without frontmatter or with broken YAML", async () => {
    await mkdir(scope.tasksDir, { recursive: true });
    const bare = join(scope.tasksDir, "bare.md");
    await writeFile(bare, "prose only\n");
    await expect(
      rewriteEntityFile(root, bare, "task", (d) => d),
    ).rejects.toThrow(/no frontmatter/);
    const broken = join(scope.tasksDir, "broken.md");
    await writeFile(broken, "---\na: [\n---\n");
    await expect(
      rewriteEntityFile(root, broken, "task", (d) => d),
    ).rejects.toThrow(/unparseable/i);
  });
});
