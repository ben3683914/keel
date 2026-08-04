import { readdirSync } from "node:fs";
import { cp, mkdtemp, readFile, readdir, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import type { ExecFileFn } from "../../../src/git/index.js";
import type { Finding } from "../../../src/schema/index.js";
import { repair, validate } from "../../../src/validator/index.js";
import { VALIDATION_RULES } from "../../../src/registry/index.js";
import {
  canonicalYaml,
  parseYaml,
  splitFrontmatter,
} from "../../../src/yaml/index.js";
import { ENTITY_SCHEMAS, keyOrderOf } from "../../../src/registry/index.js";

const FIXTURES = join(import.meta.dirname, "../../fixtures/validator");
const fixtureNames = readdirSync(FIXTURES).filter((n) => n.startsWith("v"));

/** Unit fixtures run without git: the seam reports not-a-repo (benign). */
const noGit: ExecFileFn = () =>
  Promise.reject(new Error("fatal: not a git repository"));

/** Deterministic repair seams — fixtures encode the resulting bytes. */
const RNG = (): number => 0.5;
const CLOCK = (): Date => new Date("2026-07-29T12:00:00Z");

const cleanups: string[] = [];
afterEach(async () => {
  while (cleanups.length > 0) {
    const dir = cleanups.pop();
    if (dir !== undefined) await rm(dir, { recursive: true, force: true });
  }
});

async function materialize(fixture: string): Promise<string> {
  const work = await mkdtemp(join(tmpdir(), "keel-vfix-"));
  cleanups.push(work);
  await cp(join(FIXTURES, fixture, "input"), work, { recursive: true });
  return work;
}

function normalize(findings: Finding[]): Record<string, unknown>[] {
  return findings.map((f) => ({
    rule: f.rule,
    ruleId: f.ruleId,
    mode: f.mode,
    severity: f.severity,
    file: f.file,
    message: f.message,
  }));
}

async function treeOf(root: string): Promise<Map<string, string>> {
  const files = new Map<string, string>();
  async function walk(dir: string): Promise<void> {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else files.set(relative(root, full), await readFile(full, "utf8"));
    }
  }
  await walk(root);
  return files;
}

async function expectedFindings(
  fixture: string,
): Promise<Record<string, unknown>[]> {
  const raw = await readFile(join(FIXTURES, fixture, "findings.json"), "utf8");
  return JSON.parse(raw) as Record<string, unknown>[];
}

async function hasRepairedTree(fixture: string): Promise<boolean> {
  try {
    await readdir(join(FIXTURES, fixture, "repaired"));
    return true;
  } catch {
    return false;
  }
}

describe.each(fixtureNames)("fixture %s", (fixture) => {
  it("produces the expected findings, repairs, and is idempotent", async () => {
    const work = await materialize(fixture);

    // 1. Broken input → expected findings.
    const findings = await validate({ workspaceRoot: work, exec: noGit });
    expect(normalize(findings)).toEqual(await expectedFindings(fixture));

    // 2. Silent repair → expected post-repair state.
    const result = await repair(findings, "silent", {
      workspaceRoot: work,
      rng: RNG,
      clock: CLOCK,
    });
    expect(result.skipped).toEqual([]);
    const expectedDir = (await hasRepairedTree(fixture)) ? "repaired" : "input";
    expect(await treeOf(work)).toEqual(
      await treeOf(join(FIXTURES, fixture, expectedDir)),
    );
    if (expectedDir === "input") {
      expect(result.applied).toEqual([]);
    } else {
      expect(result.applied.length).toBeGreaterThan(0);
    }

    // 3. Idempotence: a second pass over repaired state finds no silent work.
    // Residual proposals default to pass 1's proposed set; fixtures where the
    // residue differs (e.g. V-1 companions vanish with the duplicate) declare
    // it in findings-second-pass.json.
    const again = await validate({ workspaceRoot: work, exec: noGit });
    expect(again.filter((f) => f.mode === "silent")).toEqual([]);
    let expectedSecond: Record<string, unknown>[];
    try {
      expectedSecond = JSON.parse(
        await readFile(
          join(FIXTURES, fixture, "findings-second-pass.json"),
          "utf8",
        ),
      ) as Record<string, unknown>[];
    } catch {
      expectedSecond = normalize(findings.filter((f) => f.mode === "proposed"));
    }
    expect(normalize(again)).toEqual(expectedSecond);
  });
});

describe("round-trip fixed point (every fixture file)", () => {
  it("parse → canonical serialize → parse is a fixed point incl. ext and comments", async () => {
    for (const fixture of fixtureNames) {
      const tree = await treeOf(join(FIXTURES, fixture, "input"));
      for (const [path, raw] of tree) {
        const yamlText = path.endsWith(".yaml")
          ? raw
          : splitFrontmatter(raw)?.yamlText;
        if (yamlText === undefined) continue;
        const before = parseYaml(yamlText);
        if (!before.ok) continue; // quarantine fixtures
        const keyOrder = keyOrderOf(
          path.endsWith(".yaml")
            ? ENTITY_SCHEMAS["workspace-config"]
            : ENTITY_SCHEMAS.task,
        );
        const first = canonicalYaml(yamlText, keyOrder);
        expect(first.ok, `${fixture}/${path}`).toBe(true);
        if (!first.ok) continue;
        const second = canonicalYaml(first.text, keyOrder);
        expect(second.ok && second.text, `${fixture}/${path}`).toBe(first.text);
        const after = parseYaml(first.text);
        expect(after.ok && after.data, `${fixture}/${path}`).toEqual(
          before.data,
        );
      }
    }
  });
});

describe("repair modes", () => {
  it("proposed mode materializes proposals without touching disk", async () => {
    const work = await materialize("v05-arc-membership");
    const before = await treeOf(work);
    const findings = await validate({ workspaceRoot: work, exec: noGit });
    const result = await repair(findings, "proposed", { workspaceRoot: work });
    expect(result.applied).toEqual([]);
    expect(result.proposals.map((f) => f.mode)).toEqual(["proposed"]);
    expect(result.skipped).toHaveLength(2); // the silent class, untouched
    expect(await treeOf(work)).toEqual(before);
  });

  it("skips silent findings without a usable repair payload", async () => {
    const work = await materialize("v05-arc-membership");
    const bogus: Finding = {
      rule: "V-5",
      ruleId: "arc-membership-disagreement",
      mode: "silent",
      severity: "warning",
      file: "state/tasks/T-mem02-two.md",
      message: "no payload",
    };
    const result = await repair([bogus], "silent", { workspaceRoot: work });
    expect(result.applied).toEqual([]);
    expect(result.skipped).toEqual([bogus]);
  });

  it("skips repairs whose application fails (missing file)", async () => {
    const work = await materialize("v05-arc-membership");
    const doomed: Finding = {
      rule: "V-5",
      ruleId: "arc-membership-disagreement",
      mode: "silent",
      severity: "warning",
      file: "state/tasks/T-nope0-gone.md",
      message: "target missing",
      repair: { action: "set-fields", type: "task", fields: { arc: "A-x" } },
    };
    const result = await repair([doomed], "silent", { workspaceRoot: work });
    expect(result.skipped).toEqual([doomed]);
  });
});

describe("path-escape defenses", () => {
  it("skips a project scope whose realpath escapes via a symlink", async () => {
    const work = await materialize("v10-project-slug-mismatch");
    const outside = await mkdtemp(join(tmpdir(), "keel-outside-"));
    cleanups.push(outside);
    // Move the real project folder outside, leave a symlink in its place.
    await cp(join(work, "web"), join(outside, "web"), { recursive: true });
    await rm(join(work, "web"), { recursive: true, force: true });
    await symlink(join(outside, "web"), join(work, "web"));

    const findings = await validate({ workspaceRoot: work, exec: noGit });
    // V-10 lived inside the escaped scope: it must not be collected at all.
    expect(findings.map((f) => f.rule)).toEqual(["V-11"]);
    expect(findings[0]?.message).toMatch(/symbolic link; scope skipped/);
  });

  it("skips a caller-supplied repair whose scope.relPath escapes the root", async () => {
    // Confirmed: this payload was APPLIED — projectScope built a root outside
    // the workspace and mintId readdir'd it (out-of-tree read). `repair()` is
    // public and takes caller-supplied findings, so this is reachable from an
    // MCP layer round-tripping findings through JSON.
    const work = await materialize("v01-duplicate-id");
    const target = join(work, "state/tasks/T-dup01-beta.md");
    const before = await readFile(target, "utf8");
    const hostile: Finding = {
      rule: "V-1",
      ruleId: "duplicate-entity-id",
      mode: "silent",
      severity: "error",
      file: "state/tasks/T-dup01-beta.md",
      message: "hand-built payload",
      repair: {
        action: "remint-id",
        type: "task",
        scope: {
          kind: "project",
          slug: "evil",
          relPath: "../../../../../../etc",
        },
        oldId: "T-dup01",
      },
    };
    const result = await repair([hostile], "silent", { workspaceRoot: work });
    expect(result.applied).toEqual([]);
    expect(result.skipped).toEqual([hostile]);
    // Nothing was renamed or rewritten: the repair never ran.
    expect(await readFile(target, "utf8")).toBe(before);
    expect(await readdir(join(work, "state/tasks"))).toContain(
      "T-dup01-beta.md",
    );
  });

  it("skips caller-supplied payloads that fail per-variant validation", async () => {
    const work = await materialize("v05-arc-membership");
    const bogus: Finding[] = [
      { action: "totally-bogus" },
      { action: "set-fields" },
      { action: "remint-id", type: 99, scope: null, oldId: [] },
    ].map((payload, i) => ({
      rule: "V-5",
      ruleId: "arc-membership-disagreement",
      mode: "silent" as const,
      severity: "warning" as const,
      file: "state/tasks/T-mem02-two.md",
      message: `payload ${i}`,
      repair: payload,
    }));
    const result = await repair(bogus, "silent", { workspaceRoot: work });
    expect(result.applied).toEqual([]);
    expect(result.skipped).toEqual(bogus);
  });

  it("skips repairs whose finding.file escapes the workspace root", async () => {
    const work = await materialize("v05-arc-membership");
    const escaping: Finding = {
      rule: "V-5",
      ruleId: "arc-membership-disagreement",
      mode: "silent",
      severity: "warning",
      file: "../../../../tmp/keel-escape.md",
      message: "escaping repair target",
      repair: { action: "set-fields", type: "task", fields: { arc: "A-x" } },
    };
    const result = await repair([escaping], "silent", {
      workspaceRoot: work,
    });
    expect(result.applied).toEqual([]);
    expect(result.skipped).toEqual([escaping]);
  });
});

describe("declared rule config (lifting)", () => {
  it("severity overrides in a custom rule config flow through as data", async () => {
    const work = await materialize("v07-unknown-key");
    const custom = VALIDATION_RULES.map((r) =>
      r.rule === "V-7" ? { ...r, severity: "error" as const } : r,
    );
    const findings = await validate({
      workspaceRoot: work,
      exec: noGit,
      rules: custom,
    });
    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatchObject({ rule: "V-7", severity: "error" });
  });

  it("lifting workspace-internal-paths by data change disables V-11", async () => {
    const work = await materialize("v11-workspace-internal-paths");
    const lifted = VALIDATION_RULES.filter((r) => r.rule !== "V-11");
    const findings = await validate({
      workspaceRoot: work,
      exec: noGit,
      rules: lifted,
    });
    expect(findings).toEqual([]);
  });
});

describe("scope filtering", () => {
  it("validating only the workspace scope skips project findings", async () => {
    const work = await materialize("v10-project-slug-mismatch");
    const all = await validate({ workspaceRoot: work, exec: noGit });
    expect(all.map((f) => f.rule)).toEqual(["V-10"]);
    const wsOnly = await validate({
      workspaceRoot: work,
      exec: noGit,
      scope: "workspace",
    });
    expect(wsOnly).toEqual([]);
    const projOnly = await validate({
      workspaceRoot: work,
      exec: noGit,
      scope: "web",
    });
    expect(projOnly.map((f) => f.rule)).toEqual(["V-10"]);
  });
});
