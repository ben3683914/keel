import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  assertContained,
  atomicWrite,
  isContained,
  isRecord,
  isStringArray,
} from "../../../src/shared/index.js";

describe("isRecord", () => {
  it("accepts plain records and rejects null, arrays, and scalars", () => {
    expect(isRecord({})).toBe(true);
    expect(isRecord({ a: 1 })).toBe(true);
    expect(isRecord(null)).toBe(false);
    expect(isRecord([])).toBe(false);
    expect(isRecord("x")).toBe(false);
  });
});

describe("isStringArray", () => {
  it("accepts string arrays (incl. empty) and rejects mixed content", () => {
    expect(isStringArray([])).toBe(true);
    expect(isStringArray(["a", "b"])).toBe(true);
    expect(isStringArray(["a", 1])).toBe(false);
    expect(isStringArray("a")).toBe(false);
  });
});

describe("isContained / assertContained", () => {
  it("accepts strict descendants only", () => {
    expect(isContained("/ws", "/ws/state/tasks/x.md")).toBe(true);
    expect(isContained("/ws", "/ws")).toBe(false);
    expect(isContained("/ws", "/ws/../etc/passwd")).toBe(false);
    expect(isContained("/ws", "/etc/passwd")).toBe(false);
    expect(isContained("/ws", "/wsibling/x")).toBe(false);
  });

  it("assertContained throws with a clear message on escape", () => {
    expect(() => assertContained("/ws", "/tmp/evil")).toThrow(
      /outside the workspace root/,
    );
    expect(() => assertContained("/ws", "/ws/fine.md")).not.toThrow();
  });
});

describe("atomicWrite", () => {
  it("REFUSES to write outside the passed root (traversal chokepoint)", async () => {
    const dir = await mkdtemp(join(tmpdir(), "keel-shared-"));
    try {
      const outside = join(dir, "..", "keel-escape.md");
      await expect(atomicWrite(dir, outside, "pwned")).rejects.toThrow(
        /outside the workspace root/,
      );
      await expect(readFile(outside, "utf8")).rejects.toThrow();
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  it("does not follow a symlink planted at a predictable temp name", async () => {
    // Regression for the confirmed exploit: a repo-committed symlink at the
    // old deterministic `.<name>.tmp` path redirected the write outside the
    // tree. Random temp suffix + `wx` close both halves.
    const dir = await mkdtemp(join(tmpdir(), "keel-shared-"));
    const outside = await mkdtemp(join(tmpdir(), "keel-victim-"));
    try {
      const victim = join(outside, "victim.txt");
      await writeFile(victim, "original");
      await symlink(victim, join(dir, ".file.md.tmp")); // old temp name
      await atomicWrite(dir, join(dir, "file.md"), "new content\n");
      await expect(readFile(victim, "utf8")).resolves.toBe("original");
      await expect(readFile(join(dir, "file.md"), "utf8")).resolves.toBe(
        "new content\n",
      );
    } finally {
      await rm(dir, { recursive: true, force: true });
      await rm(outside, { recursive: true, force: true });
    }
  });

  it("unlinks the temp file when the write fails", async () => {
    const dir = await mkdtemp(join(tmpdir(), "keel-shared-"));
    try {
      const locked = join(dir, "locked");
      await mkdir(locked);
      await chmod(locked, 0o555); // deny create → writeFile fails
      await expect(
        atomicWrite(dir, join(locked, "x.md"), "y"),
      ).rejects.toThrow();
      await chmod(locked, 0o755);
      await expect(readdir(locked)).resolves.toEqual([]);
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  let dir: string | undefined;

  afterEach(async () => {
    if (dir !== undefined) {
      await rm(dir, { recursive: true, force: true });
      dir = undefined;
    }
  });

  it("creates parent directories and leaves no temp file behind", async () => {
    dir = await mkdtemp(join(tmpdir(), "keel-shared-"));
    const target = join(dir, "nested/deep/file.md");
    await atomicWrite(dir, target, "content\n");
    await expect(readFile(target, "utf8")).resolves.toBe("content\n");
    const names = await readdir(join(dir, "nested/deep"));
    expect(names).toEqual(["file.md"]);
  });

  it("replaces existing content atomically (rename, not truncate+write)", async () => {
    dir = await mkdtemp(join(tmpdir(), "keel-shared-"));
    const target = join(dir, "file.md");
    await atomicWrite(dir, target, "first\n");
    await atomicWrite(dir, target, "second\n");
    await expect(readFile(target, "utf8")).resolves.toBe("second\n");
  });
});
