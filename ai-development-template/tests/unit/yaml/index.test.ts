import { describe, expect, it } from "vitest";
import { parseDocument } from "yaml";

import {
  bodySectionHeadings,
  buildMarkdown,
  canonicalYaml,
  collectCommentTexts,
  findLostComments,
  parseYaml,
  setPreservingComments,
  splitFrontmatter,
  stringifyCanonical,
} from "../../../src/yaml/index.js";

const KEY_ORDER = ["id", "title", "status", "priority", "created", "ext"];

describe("parseYaml", () => {
  it("parses a mapping into data plus a comment-preserving document", () => {
    const result = parseYaml("id: T-abc12\ntitle: Fix it\n");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual({ id: "T-abc12", title: "Fix it" });
    }
  });

  it("returns structured errors with line info for broken YAML", () => {
    const result = parseYaml("a: [1,\nb: :\n");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.length).toBeGreaterThan(0);
      expect(result.errors[0]?.line).toBeTypeOf("number");
    }
  });

  it("rejects non-mapping top-level values", () => {
    const result = parseYaml("- just\n- a list\n");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors[0]?.message).toMatch(/must be a mapping/i);
    }
  });

  it("treats an empty document as an empty mapping", () => {
    const result = parseYaml("");
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.data).toEqual({});
  });

  it("quarantines an alias-expansion bomb instead of throwing", () => {
    // "billion laughs": parses cleanly, explodes on materialization.
    const bomb = [
      "a: &a [x, x, x, x, x, x, x, x, x, x]",
      "b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a, *a]",
      "c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b, *b]",
      "d: &d [*c, *c, *c, *c, *c, *c, *c, *c, *c, *c]",
      "e: [*d, *d, *d, *d, *d, *d, *d, *d, *d, *d]",
      "",
    ].join("\n");
    const result = parseYaml(bomb);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors[0]?.message).toBeTruthy();
    }
  });
});

describe("canonicalYaml", () => {
  it("orders known keys per schema, indents 2, and unrolls flow maps", () => {
    const input =
      "status: todo\nid: T-abc12\next: {azure: {work_item: 4}}\ntitle: X\n";
    const result = canonicalYaml(input, KEY_ORDER);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.text).toBe(
        "id: T-abc12\ntitle: X\nstatus: todo\next:\n  azure:\n    work_item: 4\n",
      );
    }
  });

  it("is a fixed point: canonicalizing canonical output is byte-identical", () => {
    const input =
      "# header\nstatus: todo\nid: T-abc12\n# about priority\npriority: P1\ntitle: 'Quoted: title'\n";
    const first = canonicalYaml(input, KEY_ORDER);
    expect(first.ok).toBe(true);
    if (!first.ok) return;
    const second = canonicalYaml(first.text, KEY_ORDER);
    expect(second.ok).toBe(true);
    if (second.ok) expect(second.text).toBe(first.text);
  });

  it("keeps hand-added comments attached to the key they precede", () => {
    const input =
      "status: todo\n# priority note\npriority: P1\nid: T-abc12\ntitle: X\n";
    const result = canonicalYaml(input, KEY_ORDER);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.text).toContain("# priority note\npriority: P1");
    }
  });

  it("places unknown keys after known keys but before ext", () => {
    const input =
      "zeta: 1\nid: T-abc12\next:\n  a: 1\ntitle: X\nstatus: todo\n";
    const result = canonicalYaml(input, KEY_ORDER);
    expect(result.ok).toBe(true);
    if (result.ok) {
      const lines = result.text.split("\n");
      expect(lines.indexOf("zeta: 1")).toBeGreaterThan(
        lines.indexOf("status: todo"),
      );
      expect(lines.indexOf("zeta: 1")).toBeLessThan(lines.indexOf("ext:"));
    }
  });

  it("reports parse errors instead of rewriting", () => {
    const result = canonicalYaml("a: [broken\n", KEY_ORDER);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("parse-error");
  });

  it("round-trips ext blocks and comments through parse → serialize → parse", () => {
    const input =
      "id: T-abc12\ntitle: X\nstatus: todo\next:\n  azure-devops:\n    # synced 2026\n    work_item: 4412\n";
    const result = canonicalYaml(input, KEY_ORDER);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    const reparsed = parseYaml(result.text);
    expect(reparsed.ok).toBe(true);
    if (reparsed.ok) {
      expect(reparsed.data).toEqual({
        id: "T-abc12",
        title: "X",
        status: "todo",
        ext: { "azure-devops": { work_item: 4412 } },
      });
    }
    expect(result.ok && result.text).toContain("# synced 2026");
  });
});

describe("comment accounting", () => {
  it("collects document- and node-level comments", () => {
    const doc = parseDocument("# top\na: 1 # inline\n# before b\nb: 2\n");
    const comments = collectCommentTexts(doc);
    expect(comments).toContain("top");
    expect(comments).toContain("inline");
    expect(comments).toContain("before b");
  });

  it("findLostComments reports comments missing after a rewrite", () => {
    const before = parseDocument("# keep\na: 1\n# gone\nb: 2\n");
    const after = parseDocument("# keep\na: 1\nb: 2\n");
    expect(findLostComments(before, after)).toEqual(["gone"]);
  });

  it("findLostComments is empty when every comment survives", () => {
    const before = parseDocument("# one\na: 1\n");
    const after = parseDocument("b: 0\n# one\na: 1\n");
    expect(findLostComments(before, after)).toEqual([]);
  });
});

describe("setPreservingComments", () => {
  it("keeps comments on a key whose value is replaced", () => {
    const parsed = parseYaml("# about status\nstatus: todo\nid: T-abc12\n");
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    setPreservingComments(parsed.doc, "status", "working");
    const out = stringifyCanonical(parsed.doc);
    expect(out).toContain("# about status");
    expect(out).toContain("status: working");
  });

  it("adds a new key when none exists", () => {
    const parsed = parseYaml("id: T-abc12\n");
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    setPreservingComments(parsed.doc, "title", "New");
    expect(stringifyCanonical(parsed.doc)).toContain("title: New");
  });
});

describe("splitFrontmatter / buildMarkdown", () => {
  it("splits frontmatter and body", () => {
    const text = "---\nid: T-abc12\n---\n\nBody prose.\n";
    expect(splitFrontmatter(text)).toEqual({
      yamlText: "id: T-abc12\n",
      body: "Body prose.\n",
    });
  });

  it("returns undefined without a frontmatter block", () => {
    expect(splitFrontmatter("# Just a doc\n")).toBeUndefined();
    expect(splitFrontmatter("---\nnever closed\n")).toBeUndefined();
  });

  it("tolerates CRLF fences from Windows-checkout hand edits", () => {
    const text = "---\r\nid: T-abc12\r\ntitle: X\r\n---\r\n\r\nBody line.\r\n";
    const split = splitFrontmatter(text);
    expect(split).toBeDefined();
    expect(split?.yamlText).toBe("id: T-abc12\r\ntitle: X\r\n");
    expect(split?.body).toBe("Body line.\r\n");
    const parsed = parseYaml(split?.yamlText ?? "");
    expect(parsed.ok && parsed.data).toEqual({ id: "T-abc12", title: "X" });
  });

  it("round-trips: split(build(y, b)) is a fixed point", () => {
    const built = buildMarkdown("id: T-abc12\n", "Body text.");
    expect(built).toBe("---\nid: T-abc12\n---\n\nBody text.\n");
    const split = splitFrontmatter(built);
    expect(split).toEqual({ yamlText: "id: T-abc12\n", body: "Body text.\n" });
    expect(buildMarkdown(split?.yamlText ?? "", split?.body ?? "")).toBe(built);
  });

  it("builds a frontmatter-only file when the body is empty", () => {
    expect(buildMarkdown("a: 1", "")).toBe("---\na: 1\n---\n");
  });
});

describe("bodySectionHeadings", () => {
  it("extracts only level-2 headings, ignoring prose and deeper levels", () => {
    const body =
      "Intro prose.\n\n## Context\ntext\n\n### Sub\n\n#### Deeper\n\n## Rule\nmore\n";
    expect(bodySectionHeadings(body)).toEqual(["Context", "Rule"]);
  });
});
