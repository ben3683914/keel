import { execFile } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, expect, it } from "vitest";

import { readEntity } from "../../../src/entity/index.js";
import { workspaceScope } from "../../../src/layout/index.js";
import { repair, validate } from "../../../src/validator/index.js";

const execFileAsync = promisify(execFile);

let root: string | undefined;

afterEach(async () => {
  if (root !== undefined) {
    await rm(root, { recursive: true, force: true });
    root = undefined;
  }
});

async function git(cwd: string, ...args: string[]): Promise<void> {
  await execFileAsync("git", args, { cwd });
}

async function initRepo(): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), "keel-int-"));
  root = dir;
  await git(dir, "init");
  await git(dir, "config", "user.email", "test@example.invalid");
  await git(dir, "config", "user.name", "Test");
  return dir;
}

function task(id: string, title: string, extra = ""): string {
  return `---\nid: ${id}\ntitle: ${title}\nstatus: todo\ncategory: task\npriority: P1\n${extra}created: 2026-07-01\n---\n`;
}

describe("V-4 with real git history (integration)", () => {
  it("archive-annotates refs to pruned entities; second pass is clean", async () => {
    const dir = await initRepo();
    const tasks = join(dir, "state/tasks");
    await mkdir(tasks, { recursive: true });
    await writeFile(
      join(tasks, "T-old01-legacy.md"),
      task("T-old01", "Legacy"),
    );
    await writeFile(
      join(tasks, "T-new01-current.md"),
      task("T-new01", "Current", "depends_on:\n  - T-old01\n"),
    );
    await git(dir, "add", ".");
    await git(dir, "commit", "-m", "both tasks");
    await git(dir, "rm", "state/tasks/T-old01-legacy.md");
    await git(dir, "commit", "-m", "prune legacy task to archive");

    const findings = await validate({ workspaceRoot: dir });
    const v4 = findings.filter((f) => f.rule === "V-4");
    expect(v4).toHaveLength(1);
    expect(v4[0]?.mode).toBe("silent"); // found in history → annotate, not remove

    const result = await repair(findings, "silent", { workspaceRoot: dir });
    expect(result.applied.map((f) => f.rule)).toContain("V-4");

    const read = await readEntity({
      scope: workspaceScope(dir),
      type: "task",
      id: "T-new01",
    });
    expect(read.entity?.data["ext"]).toEqual({
      keel: { resolved_by_archive: ["T-old01"] },
    });
    // The reference itself stays: history is the archive.
    expect(read.entity?.data["depends_on"]).toEqual(["T-old01"]);

    const again = await validate({ workspaceRoot: dir });
    expect(again).toEqual([]);
  });

  it("proposes removal when the ref never existed in history", async () => {
    const dir = await initRepo();
    const tasks = join(dir, "state/tasks");
    await mkdir(tasks, { recursive: true });
    await writeFile(
      join(tasks, "T-new01-current.md"),
      task("T-new01", "Current", "depends_on:\n  - T-ghost\n"),
    );
    await git(dir, "add", ".");
    await git(dir, "commit", "-m", "task with ghost dep");

    const findings = await validate({ workspaceRoot: dir });
    const v4 = findings.filter((f) => f.rule === "V-4");
    expect(v4).toHaveLength(1);
    expect(v4[0]?.mode).toBe("proposed");
  });
});

describe("V-13 with real git tracking (integration)", () => {
  it("flags tracked derived, ephemera, and binary state files — never removes them", async () => {
    const dir = await initRepo();
    await mkdir(join(dir, "state/tasks"), { recursive: true });
    await mkdir(join(dir, ".keel/derived"), { recursive: true });
    await writeFile(
      join(dir, "state/tasks/T-abc01-fine.md"),
      task("T-abc01", "Fine"),
    );
    await writeFile(join(dir, "board.md"), "# Board\n");
    await writeFile(join(dir, ".keel/derived/index.json"), "{}\n");
    await writeFile(
      join(dir, "state/tasks/evidence.bin"),
      Buffer.from([0x00, 0x01, 0x02]),
    );
    await git(dir, "add", "-f", ".");
    await git(dir, "commit", "-m", "track things that must not be tracked");

    const findings = await validate({ workspaceRoot: dir });
    const v13 = findings.filter((f) => f.rule === "V-13");
    expect(v13.map((f) => f.file).sort()).toEqual([
      ".keel/derived/index.json",
      "board.md",
      "state/tasks/evidence.bin",
    ]);
    expect(v13.every((f) => f.mode === "proposed")).toBe(true);

    // repair(silent) must not touch them: hard finding, never auto-git-rm.
    await repair(findings, "silent", { workspaceRoot: dir });
    await expect(readFile(join(dir, "board.md"), "utf8")).resolves.toBe(
      "# Board\n",
    );
  });
});
