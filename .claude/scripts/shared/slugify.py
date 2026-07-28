"""Deterministic title -> slug conversion for cross-repo article identity.

A slug is generated from an article title to form the suffix of `source_id`
(`template:<slug>` or `project:<slug>`). It must be stable: the same title
must produce the same slug across template/project repositories so upserts
can match on source_id.
"""

import re


def slugify(title: str) -> str:
    """Lowercase, ASCII-only, hyphen-separated slug. Empty input -> 'untitled'."""
    if title is None:
        return "untitled"
    slug = title.strip().lower()
    # Drop anything that isn't alnum, whitespace, or hyphen
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.ASCII)
    # Collapse whitespace/underscores/hyphens into single hyphens
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


def normalize_title(title: str) -> str:
    """Normalized form of a title, used for fuzzy pre-existing-row matching.

    Two titles with trivial punctuation/whitespace differences (e.g.
    'Docs Before Source' vs 'Docs Before Source!') should produce the same
    normalized form, so the first-upgrade backfill can match a locally
    authored article to the template's canonical version.
    """
    return slugify(title)
