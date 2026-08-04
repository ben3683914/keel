import { describe, expect, it } from "vitest";

import {
  derivedPaths,
  entityDir,
  isContainedInWorkspace,
  projectScope,
  stateKindOf,
  workspaceRelative,
  workspaceScope,
} from "../../../src/layout/index.js";

const ROOT = "/ws";

describe("workspaceScope", () => {
  it("encodes the design doc's workspace layout", () => {
    const ws = workspaceScope(ROOT);
    expect(ws.kind).toBe("workspace");
    expect(ws.slug).toBe("workspace");
    expect(ws.tasksDir).toBe("/ws/state/tasks");
    expect(ws.arcsDir).toBe("/ws/state/arcs");
    expect(ws.articlesDir).toBe("/ws/state/articles");
    expect(ws.configPath).toBe("/ws/state/config/workspace.yaml");
    expect(ws.curationPath).toBe("/ws/state/routing/curation.yaml");
    expect(ws.docsDir).toBe("/ws/docs");
  });
});

describe("projectScope", () => {
  it("encodes the per-project layout with its own state tree", () => {
    const p = projectScope(ROOT, "web", "apps/web");
    expect(p.kind).toBe("project");
    expect(p.slug).toBe("web");
    expect(p.scopeRoot).toBe("/ws/apps/web");
    expect(p.tasksDir).toBe("/ws/apps/web/state/tasks");
    expect(p.configPath).toBe("/ws/apps/web/state/config.yaml");
    expect(p.curationPath).toBe("/ws/apps/web/state/routing/curation.yaml");
    expect(p.docsDir).toBe("/ws/apps/web/docs");
  });
});

describe("derivedPaths", () => {
  it("places derived and ephemera under .keel and board.md at root", () => {
    const d = derivedPaths(ROOT);
    expect(d.indexPath).toBe("/ws/.keel/derived/index.json");
    expect(d.headPath).toBe("/ws/.keel/derived/head.json");
    expect(d.localDir).toBe("/ws/.keel/local");
    expect(d.boardPath).toBe("/ws/board.md");
  });
});

describe("entityDir", () => {
  it("maps entity types to their directories and fixed paths", () => {
    const ws = workspaceScope(ROOT);
    expect(entityDir(ws, "task")).toBe(ws.tasksDir);
    expect(entityDir(ws, "arc")).toBe(ws.arcsDir);
    expect(entityDir(ws, "article")).toBe(ws.articlesDir);
    expect(entityDir(ws, "doc")).toBe(ws.docsDir);
    expect(entityDir(ws, "workspace-config")).toBe(ws.configPath);
    expect(entityDir(ws, "curation")).toBe(ws.curationPath);
    const p = projectScope(ROOT, "web", "web");
    expect(entityDir(p, "project-config")).toBe(p.configPath);
  });
});

describe("stateKindOf", () => {
  it("classifies the design doc's path table", () => {
    expect(stateKindOf("state/tasks/T-abc12-fix.md")).toBe("truth");
    expect(stateKindOf("docs/guides/setup.md")).toBe("truth");
    expect(stateKindOf("board.md")).toBe("derived");
    expect(stateKindOf(".keel/derived/index.json")).toBe("derived");
    expect(stateKindOf(".keel/local/scope.yaml")).toBe("ephemera");
    expect(stateKindOf(".keel/local/evidence/T-abc12.json")).toBe("ephemera");
  });

  it("classifies project state and docs as truth via declared paths", () => {
    const projects = ["web", "apps/api"];
    expect(stateKindOf("web/state/tasks/T-abc12-x.md", projects)).toBe("truth");
    expect(stateKindOf("apps/api/docs/readme.md", projects)).toBe("truth");
    expect(stateKindOf("web/src/main.ts", projects)).toBeUndefined();
  });

  it("does not own product code or unrelated paths", () => {
    expect(stateKindOf("src/index.ts")).toBeUndefined();
    expect(stateKindOf("README.md")).toBeUndefined();
  });
});

describe("isContainedInWorkspace", () => {
  it("accepts relative paths inside the root", () => {
    expect(isContainedInWorkspace(ROOT, "web")).toBe(true);
    expect(isContainedInWorkspace(ROOT, "apps/web")).toBe(true);
  });

  it("rejects escapes: .., absolute paths outside, and the root itself", () => {
    expect(isContainedInWorkspace(ROOT, "../elsewhere")).toBe(false);
    expect(isContainedInWorkspace(ROOT, "web/../../etc")).toBe(false);
    expect(isContainedInWorkspace(ROOT, "/etc/passwd")).toBe(false);
    expect(isContainedInWorkspace(ROOT, ".")).toBe(false);
  });

  it("canonicalizes before checking (dot segments collapse)", () => {
    expect(isContainedInWorkspace(ROOT, "./web/./x/..")).toBe(true);
  });
});

describe("workspaceRelative", () => {
  it("converts absolute paths to /-separated workspace-relative", () => {
    expect(workspaceRelative(ROOT, "/ws/state/tasks/T-a.md")).toBe(
      "state/tasks/T-a.md",
    );
  });
});
