import { execFile } from "node:child_process";
import {
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, expect, it } from "vitest";

import { readEntity } from "../../../src/entity/index.js";
import { workspaceScope } from "../../../src/layout/index.js";
import { repair, validate } from "../../../src/validator/index.js";

const execFileAsync = promisify(execFile);

/** Deterministic repair seams, matching the validator fixture corpus. */
const RNG = (): number => 0.5;
const CLOCK = (): Date => new Date("2026-07-29T12:00:00Z");

const cleanups: string[] = [];

afterEach(async () => {
  while (cleanups.length > 0) {
    const dir = cleanups.pop();
    if (dir !== undefined) await rm(dir, { recursive: true, force: true });
  }
});

async function git(cwd: string, ...args: string[]): Promise<string> {
  const { stdout } = await execFileAsync("git", args, { cwd });
  return stdout;
}

async function initRepo(): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), "keel-merge-"));
  cleanups.push(dir);
  await git(dir, "init", "--initial-branch=main");
  await git(dir, "config", "user.email", "test@example.invalid");
  await git(dir, "config", "user.name", "Test");
  return dir;
}

async function commitAll(dir: string, message: string): Promise<void> {
  await git(dir, "add", ".");
  await git(dir, "commit", "-m", message);
}

/** Canonical task file (schema key order), optional body. */
function task(
  id: string,
  title: string,
  fields: { status?: string; priority?: string; created?: string } = {},
  body = "",
): string {
  const front = [
    `id: ${id}`,
    `title: ${title}`,
    `status: ${fields.status ?? "todo"}`,
    "category: task",
    `priority: ${fields.priority ?? "P1"}`,
    `created: ${fields.created ?? "2026-07-01"}`,
  ].join("\n");
  return body === "" ? `---\n${front}\n---\n` : `---\n${front}\n---\n\n${body}`;
}

async function writeTask(
  dir: string,
  filename: string,
  content: string,
): Promise<void> {
  await writeFile(join(dir, "state/tasks", filename), content);
}

/** Byte-level snapshot of a repo's state/ tree, keyed by relative path. */
async function stateTreeOf(dir: string): Promise<Map<string, string>> {
  const root = join(dir, "state");
  const files = new Map<string, string>();
  async function walk(cur: string): Promise<void> {
    for (const entry of await readdir(cur, { withFileTypes: true })) {
      const full = join(cur, entry.name);
      if (entry.isDirectory()) await walk(full);
      else files.set(relative(root, full), await readFile(full, "utf8"));
    }
  }
  await walk(root);
  return files;
}

describe("merge shapes over real git repos (integration)", () => {
  it("(a) branches touching different entities merge cleanly and validate clean", async () => {
    const dir = await initRepo();
    await mkdir(join(dir, "state/tasks"), { recursive: true });
    await writeTask(dir, "T-one01-first.md", task("T-one01", "First"));
    await writeTask(dir, "T-two01-second.md", task("T-two01", "Second"));
    await commitAll(dir, "base: two tasks");

    await git(dir, "checkout", "-b", "feat-a");
    await writeTask(
      dir,
      "T-one01-first.md",
      task("T-one01", "First", { status: "working" }),
    );
    await commitAll(dir, "feat-a: start first task");

    await git(dir, "checkout", "main");
    await git(dir, "checkout", "-b", "feat-b");
    await writeTask(
      dir,
      "T-two01-second.md",
      task("T-two01", "Second", { priority: "P0" }),
    );
    await commitAll(dir, "feat-b: escalate second task");

    // Clean merge: different entity files never conflict. A conflicting
    // merge exits non-zero, which makes this call reject and fail the test.
    await git(dir, "checkout", "feat-a");
    await git(dir, "merge", "feat-b", "--no-edit");
    expect(await git(dir, "status", "--porcelain")).toBe("");

    // Both branches' changes landed.
    const scope = workspaceScope(dir);
    const first = await readEntity({ scope, type: "task", id: "T-one01" });
    expect(first.entity?.data["status"]).toBe("working");
    const second = await readEntity({ scope, type: "task", id: "T-two01" });
    expect(second.entity?.data["priority"]).toBe("P0");

    // The merged state needs no validator attention at all.
    expect(await validate({ workspaceRoot: dir })).toEqual([]);
  });

  it("(b) same entity, frontmatter edit vs body edit, auto-merges without conflict", async () => {
    const dir = await initRepo();
    await mkdir(join(dir, "state/tasks"), { recursive: true });
    const body =
      "Opening prose that anchors the context on-ramp for this task.\n" +
      "\n" +
      "## Notes\n" +
      "\n" +
      "Original note recorded at mint time.\n";
    await writeTask(
      dir,
      "T-mrg01-shared.md",
      task("T-mrg01", "Shared", {}, body),
    );
    await commitAll(dir, "base: shared task");

    await git(dir, "checkout", "-b", "feat-front");
    await writeTask(
      dir,
      "T-mrg01-shared.md",
      task("T-mrg01", "Shared", { status: "working" }, body),
    );
    await commitAll(dir, "feat-front: status to working");

    await git(dir, "checkout", "main");
    await git(dir, "checkout", "-b", "feat-body");
    const editedBody = body.replace(
      "Original note recorded at mint time.",
      "Original note recorded at mint time.\n\nFollow-up added on a branch.",
    );
    await writeTask(
      dir,
      "T-mrg01-shared.md",
      task("T-mrg01", "Shared", {}, editedBody),
    );
    await commitAll(dir, "feat-body: append follow-up note");

    // Frontmatter and body are distinct hunks: git auto-merges, no conflict
    // (a conflicting merge exits non-zero and rejects this call).
    await git(dir, "checkout", "feat-front");
    await git(dir, "merge", "feat-body", "--no-edit");
    expect(await git(dir, "status", "--porcelain")).toBe("");

    const merged = await readFile(
      join(dir, "state/tasks/T-mrg01-shared.md"),
      "utf8",
    );
    expect(merged).toContain("status: working");
    expect(merged).toContain("Follow-up added on a branch.");
    expect(merged).not.toContain("<<<<<<<");

    // The auto-merged file is still a valid, canonical entity.
    const read = await readEntity({
      scope: workspaceScope(dir),
      type: "task",
      id: "T-mrg01",
    });
    expect(read.entity?.data["status"]).toBe("working");
    expect(read.entity?.body).toContain("Follow-up added on a branch.");
    expect(await validate({ workspaceRoot: dir })).toEqual([]);
  });

  it("(c) colliding ids across branches: V-1 repairs to a stable, idempotent result", async () => {
    const dir = await initRepo();
    await mkdir(join(dir, "state/tasks"), { recursive: true });
    await writeTask(dir, "T-bse01-base.md", task("T-bse01", "Base"));
    await commitAll(dir, "base");

    // Each branch mints the same id for a different task (cross-branch collision).
    await git(dir, "checkout", "-b", "feat-a");
    await writeTask(
      dir,
      "T-dup01-alpha.md",
      task("T-dup01", "Alpha", { created: "2026-07-01" }),
    );
    await commitAll(dir, "feat-a: alpha");

    await git(dir, "checkout", "main");
    await git(dir, "checkout", "-b", "feat-b");
    await writeTask(
      dir,
      "T-dup01-beta.md",
      task("T-dup01", "Beta", { created: "2026-07-02" }),
    );
    await commitAll(dir, "feat-b: beta");

    // Different paths merge cleanly — the collision only exists post-merge.
    await git(dir, "checkout", "feat-a");
    await git(dir, "merge", "feat-b", "--no-edit");

    const findings = await validate({ workspaceRoot: dir });
    const v1 = findings.filter((f) => f.rule === "V-1");
    expect(v1).toHaveLength(1);
    expect(v1[0]).toMatchObject({
      mode: "silent",
      file: "state/tasks/T-dup01-beta.md", // younger by `created`
    });

    const result = await repair(findings, "silent", {
      workspaceRoot: dir,
      rng: RNG,
      clock: CLOCK,
    });
    expect(result.applied.map((f) => f.rule)).toContain("V-1");
    expect(result.skipped).toEqual([]);

    // The younger entity is re-minted (rng 0.5 → ggggg) and its file renamed;
    // the elder keeps its identity.
    const scope = workspaceScope(dir);
    const survivor = await readEntity({ scope, type: "task", id: "T-dup01" });
    expect(survivor.entity?.data["title"]).toBe("Alpha");
    const reminted = await readEntity({ scope, type: "task", id: "T-ggggg" });
    expect(reminted.entity?.data["title"]).toBe("Beta");
    expect(reminted.entity?.data["created"]).toBe("2026-07-02");

    // Idempotence: a second pass over the repaired merge finds nothing.
    expect(await validate({ workspaceRoot: dir })).toEqual([]);
  });

  it("(c) repair result is byte-identical regardless of merge direction or repo path", async () => {
    // Two independent repos at different filesystem paths perform the same
    // merge in opposite directions; after repair, their state trees must be
    // byte-identical (Article 002 — stable, reproducible outcome).
    async function build(mergeAlphaIntoBeta: boolean): Promise<string> {
      const dir = await initRepo();
      await mkdir(join(dir, "state/tasks"), { recursive: true });
      await writeTask(dir, "T-bse01-base.md", task("T-bse01", "Base"));
      await commitAll(dir, "base");

      await git(dir, "checkout", "-b", "feat-a");
      await writeTask(
        dir,
        "T-dup01-alpha.md",
        task("T-dup01", "Alpha", { created: "2026-07-01" }),
      );
      await commitAll(dir, "feat-a: alpha");

      await git(dir, "checkout", "main");
      await git(dir, "checkout", "-b", "feat-b");
      await writeTask(
        dir,
        "T-dup01-beta.md",
        task("T-dup01", "Beta", { created: "2026-07-02" }),
      );
      await commitAll(dir, "feat-b: beta");

      await git(dir, "checkout", mergeAlphaIntoBeta ? "feat-b" : "feat-a");
      await git(
        dir,
        "merge",
        mergeAlphaIntoBeta ? "feat-a" : "feat-b",
        "--no-edit",
      );

      const findings = await validate({ workspaceRoot: dir });
      await repair(findings, "silent", {
        workspaceRoot: dir,
        rng: RNG,
        clock: CLOCK,
      });
      return dir;
    }

    const forward = await build(false);
    const backward = await build(true);
    expect(await stateTreeOf(forward)).toEqual(await stateTreeOf(backward));
  });
});
