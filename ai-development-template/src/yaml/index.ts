import {
  Document,
  isMap,
  parseDocument,
  visit,
  type Pair,
  type ParsedNode,
} from "yaml";

import { isRecord } from "../shared/index.js";

/** Stringify options producing the canonical serialization (Article 002). */
const CANONICAL_STRINGIFY = { indent: 2, lineWidth: 0 } as const;

/** A YAML parse error with best-effort position info. */
export interface YamlParseError {
  message: string;
  line?: number;
  col?: number;
}

/** Result of parsing a YAML source text. */
export type ParseYamlResult =
  | { ok: true; doc: Document.Parsed; data: Record<string, unknown> }
  | { ok: false; errors: YamlParseError[] };

/** Result of canonicalizing a YAML source text. */
export type CanonicalYamlResult =
  | { ok: true; text: string }
  | { ok: false; reason: "parse-error"; errors: YamlParseError[] }
  | { ok: false; reason: "comment-anchor"; lostComments: string[] };

/**
 * Parses YAML text into a comment-preserving document plus plain data.
 * Unparseable input returns structured errors with line/column, never throws
 * (the quarantine backstop: hand-edited files become findings, not crashes).
 */
export function parseYaml(text: string): ParseYamlResult {
  const doc = parseDocument(text);
  if (doc.errors.length > 0) {
    return {
      ok: false,
      errors: doc.errors.map((e) => ({
        message: e.message,
        line: e.linePos?.[0]?.line,
        col: e.linePos?.[0]?.col,
      })),
    };
  }
  // Materialization can throw even when parsing reported no errors (e.g.
  // alias-expansion bombs); cap alias expansion and quarantine on failure.
  let data: unknown;
  try {
    data = (doc.toJS({ maxAliasCount: 100 }) as unknown) ?? {};
  } catch (error) {
    return {
      ok: false,
      errors: [
        {
          message:
            error instanceof Error
              ? error.message
              : "Failed to materialize YAML document",
          line: 1,
        },
      ],
    };
  }
  if (!isRecord(data)) {
    return {
      ok: false,
      errors: [{ message: "Top-level YAML value must be a mapping", line: 1 }],
    };
  }
  return { ok: true, doc, data };
}

/**
 * Collects every comment string reachable in a document (document-level and
 * node-attached). Used to verify no hand-added comment is lost by a rewrite.
 */
export function collectCommentTexts(doc: Document): string[] {
  const comments: string[] = [];
  const push = (c: string | null | undefined): void => {
    if (typeof c === "string") {
      for (const line of c.split("\n")) comments.push(line.trim());
    }
  };
  push(doc.commentBefore);
  push(doc.comment);
  visit(doc, {
    Node(_, node) {
      push(node.commentBefore);
      push(node.comment);
    },
  });
  return comments;
}

/**
 * Returns comments present in `before` but missing from `after`. Non-empty
 * means a rewrite could not safely re-anchor every comment (V-12's skip case).
 */
export function findLostComments(before: Document, after: Document): string[] {
  const remaining = collectCommentTexts(after);
  const lost: string[] = [];
  for (const comment of collectCommentTexts(before)) {
    const idx = remaining.indexOf(comment);
    if (idx === -1) lost.push(comment);
    else remaining.splice(idx, 1);
  }
  return lost;
}

/**
 * Reorders a document's top-level keys into canonical order and forces block
 * style throughout. Known keys follow `keyOrder`; unknown keys keep their
 * original relative order after the known ones; `ext` always sorts last.
 * Comments stay attached to the node they precede, so they travel with keys.
 */
export function canonicalizeDocument(
  doc: Document,
  keyOrder: readonly string[],
): void {
  const contents = doc.contents;
  if (isMap(contents)) {
    const items = contents.items as Pair<ParsedNode, ParsedNode | null>[];
    const rank = new Map<Pair<ParsedNode, ParsedNode | null>, number>();
    items.forEach((pair, originalIndex) => {
      const key = String(pair.key);
      const known = keyOrder.indexOf(key);
      if (key === "ext") {
        rank.set(pair, Number.MAX_SAFE_INTEGER);
      } else if (known !== -1) {
        rank.set(pair, known * items.length);
      } else {
        rank.set(pair, keyOrder.length * items.length + originalIndex);
      }
    });
    items.sort((a, b) => (rank.get(a) ?? 0) - (rank.get(b) ?? 0));
  }
  // Block style throughout; empty collections have no block form, so they
  // stay flow (`[]` / `{}`) — inline, on the key's own line.
  visit(doc, {
    Map(_, node) {
      node.flow = node.items.length === 0;
    },
    Seq(_, node) {
      node.flow = node.items.length === 0;
    },
  });
  // Canonical form has no explicit document-end marker.
  if (doc.directives) doc.directives.docEnd = false;
}

/**
 * Produces the canonical serialization of YAML text: fixed key order, 2-space
 * indent, no flow collections. Idempotent — canonical text is a fixed point.
 * If any hand-added comment cannot be re-anchored, reports that instead of
 * rewriting (consumed by V-12).
 */
export function canonicalYaml(
  text: string,
  keyOrder: readonly string[],
): CanonicalYamlResult {
  const parsed = parseYaml(text);
  if (!parsed.ok) {
    return { ok: false, reason: "parse-error", errors: parsed.errors };
  }
  canonicalizeDocument(parsed.doc, keyOrder);
  const out = parsed.doc.toString(CANONICAL_STRINGIFY);
  const reparsed = parseDocument(out);
  const lostComments = findLostComments(parsed.doc, reparsed);
  if (lostComments.length > 0) {
    return { ok: false, reason: "comment-anchor", lostComments };
  }
  return { ok: true, text: out };
}

/**
 * Serializes a document with the canonical stringify settings (after
 * `canonicalizeDocument` has been applied).
 */
export function stringifyCanonical(doc: Document): string {
  return doc.toString(CANONICAL_STRINGIFY);
}

/**
 * Sets a top-level key on a comment-preserving document, keeping any comments
 * attached to the existing key and value nodes.
 */
export function setPreservingComments(
  doc: Document,
  key: string,
  value: unknown,
): void {
  const contents = doc.contents;
  const existing = isMap(contents)
    ? (contents.items as Pair<ParsedNode, ParsedNode | null>[]).find(
        (p) => String(p.key) === key,
      )
    : undefined;
  const oldValue = existing?.value;
  doc.set(key, value);
  const updated = isMap(doc.contents)
    ? (doc.contents.items as Pair<ParsedNode, ParsedNode | null>[]).find(
        (p) => String(p.key) === key,
      )
    : undefined;
  if (updated?.value && oldValue && updated.value !== oldValue) {
    updated.value.commentBefore = oldValue.commentBefore;
    updated.value.comment = oldValue.comment;
  }
}

/** A markdown file split into frontmatter YAML text and prose body. */
export interface SplitMarkdown {
  yamlText: string;
  body: string;
}

/**
 * Splits a markdown file into its YAML frontmatter and body. Returns
 * `undefined` when the file has no frontmatter block (legal for docs —
 * adapt, don't enforce). Tolerates CRLF fences from Windows-checkout hand
 * edits; canonical rewrites normalize to LF.
 */
export function splitFrontmatter(text: string): SplitMarkdown | undefined {
  const open = /^---\r?\n/.exec(text);
  if (open === null && text !== "---") return undefined;
  const rest = text.slice(open?.[0].length ?? text.length);
  const close = rest.search(/^---\r?(\n|$)/m);
  if (close === -1) return undefined;
  const yamlText = rest.slice(0, close);
  const body = rest.slice(close).replace(/^---\r?\n?/, "");
  return { yamlText, body: body.replace(/^(\r?\n)+/, "") };
}

/**
 * Assembles the canonical on-disk markdown form: frontmatter fenced by `---`,
 * one blank line, trimmed body, single trailing newline. Byte-stable under
 * repeated assembly (Article 002).
 */
export function buildMarkdown(yamlText: string, body: string): string {
  const fence = `---\n${yamlText.endsWith("\n") ? yamlText : yamlText + "\n"}---\n`;
  const trimmed = body.trim();
  return trimmed.length === 0 ? fence : `${fence}\n${trimmed}\n`;
}

/**
 * Extracts the level-2 markdown section headings (`## Title`) present in a
 * body. Deeper levels (`###`…) are sub-structure, not sections — body-section
 * contracts (e.g. article ratification requirements) match `##` only.
 */
export function bodySectionHeadings(body: string): string[] {
  const headings: string[] = [];
  for (const line of body.split("\n")) {
    const m = /^##\s+(.*)$/.exec(line.trim());
    if (m) headings.push(m[1]?.trim() ?? "");
  }
  return headings;
}
