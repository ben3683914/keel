---
name: constitution
description: Manage the project constitution — propose a new article, amend or revoke an existing one, or review/ratify pending articles. Use for any constitution governance.
disable-model-invocation: true
---

The constitution is the project's set of binding rules (its **articles**). Changes are deliberate. Start by asking the user what they want to do (or infer it from their request):

> What would you like to do with the constitution?
> 1. **Propose a new article** — establish a new rule
> 2. **Amend an existing article** — revise a rule, then re-affirm it
> 3. **Revoke an article** — retire a rule
> 4. **Review pending articles** — ratify or revoke articles awaiting confirmation

Then follow the matching flow. Run `list_articles` anytime to show the current constitution.

## 1. Propose a new article

1. Ask what rule they want to establish.
2. Draft the article with context, rule, consequences, and enforcement.
3. Present it for review using `AskUserQuestion`.
4. If approved, call `propose_article` (docs-manager MCP) to create it (status `proposed`).
5. Ask if they want to ratify immediately — if yes, call `ratify_article`.

## 2. Amend an existing article

Editing a ratified rule is intentional friction: the change lands as `amended`
and must be **re-affirmed** (re-ratified) to become canonical again. In the
template, an un-re-affirmed article will not export to the scaffold and blocks a
release.

1. **Pick the article.** Run `list_articles` and confirm which number they mean.
2. **Identify the fields to change.** Any of `title`, `context`, `rule_text`,
   `consequences`, `enforcement`, `category` can be amended independently — you do
   not have to restate the whole article. (Changing `title` does NOT change the
   article's `source_id`, so cross-repo identity is preserved.)
3. **Show a before/after.** Display the current value and the proposed value for
   each field being changed, and confirm with `AskUserQuestion`.
4. **Amend.** Call `amend_article` with `number` plus only the changed fields.
   Status becomes `amended`.
5. **Re-affirm in the same step.** Immediately call `ratify_article` on the same
   number so the change is canonical. Treat amend + ratify as one user-visible
   "re-affirm" — do not leave the article sitting at `amended` unless the user
   explicitly wants to hold it for more edits.
6. If working in the template, remind the user that the constitution scaffold
   should be re-exported (`/prep-release` step 1, or the export script) so the
   change ships.

**Downstream caveat:** in a project created from the template (`template_dev` is
not set), an `amended` article means an intentional *local divergence* from the
inherited rule and is preserved across template updates. There, do NOT re-affirm
unless the user wants to forfeit that divergence protection.

## 3. Revoke an article

Retiring a rule is deliberate too — the constitution should reflect what the
project actually enforces.

1. **Pick the article.** Run `list_articles` and confirm the number.
2. **Confirm intent.** Show the article and confirm with `AskUserQuestion` that
   they want to retire it (and why).
3. **Revoke.** Call `revoke_article` with the number.
4. If working in the template, remind the user to re-export the constitution
   scaffold (`/prep-release` step 1, or the export script) so the removal ships.

## 4. Review pending articles

A proposed or amended article is **pending** until ratified.

1. Run `list_articles` and identify any in `proposed` or `amended` status.
2. For each, show it and ask via `AskUserQuestion` whether to **ratify** (make
   canonical, via `ratify_article`) or **revoke** (discard, via `revoke_article`).
