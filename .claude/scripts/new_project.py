#!/usr/bin/env python3
"""Create a project: scaffold its folder + docs and register it in project-config.json.

This is the SINGLE code path for adding a project to the workspace. Onboarding
(single / scratch / multi) and `/add-project` all call it, so every project —
regardless of workspace shape — is a real `projects[]` entry living in its own
`./<slug>/` subfolder. The `workspace` row is never a working project; it is the
umbrella only (constitution tier + cross-cutting board + resolution fallback).

Idempotent and non-destructive: it creates the folder and doc scaffold only when
missing, and NEVER overwrites an existing README or doc (so code dropped into the
folder before `/document-project` is left untouched).

Usage:
    python .claude/scripts/new_project.py \
        --slug my-app --name "My App" \
        [--path my-app] [--description "..."] \
        [--source-roots src] [--source-extensions .py .pyi] \
        [--test-command "pytest"] [--enforcement full] \
        [--no-scaffold]

`--path` defaults to the slug. Without `--no-scaffold`, the folder,
`<path>/docs/index.md`, and a stub `<path>/README.md` are created if absent.
On success the new `projects[]` list is printed as JSON.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SHARED = Path(__file__).resolve().parent / "shared"
sys.path.insert(0, str(SHARED))

from routing import get_project_root, load_project_config  # noqa: E402
from slugify import slugify  # noqa: E402


def _config_path(root: Path) -> Path:
    return root / ".claude" / "project-config.json"


def _save_config(root: Path, config: dict) -> None:
    # LF-only, trailing newline — matches every other generated file in the engine.
    _config_path(root).write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def _doc_index_stub(name: str) -> str:
    today = date.today().isoformat()
    return (
        f"# {name}\n\n"
        f"> **Version:** 0.1.0 | **Last Updated:** {today} | **Status:** Draft\n\n"
        f"Documentation root for **{name}**. Run `/document-project {{path}}` to "
        f"generate baseline architecture and conventions docs once code is in place.\n"
    )


def _readme_stub(name: str, description: str) -> str:
    desc = description.strip() or "(project description)"
    return (
        f"# {name}\n\n"
        f"{desc}\n\n"
        f"## Quick Reference\n\n"
        f"- **Build:** TBD\n"
        f"- **Run:** TBD\n"
        f"- **Test:** TBD\n"
    )


def add_project(
    slug: str,
    name: str,
    path: str | None = None,
    description: str = "",
    source_roots: list[str] | None = None,
    source_extensions: list[str] | None = None,
    test_command: str = "",
    enforcement: str | None = None,
    scaffold: bool = True,
    refresh: bool = True,
) -> dict:
    """Register a project and (optionally) scaffold its folder. Returns the new entry.

    Raises ValueError on a bad/duplicate slug or path.
    """
    root = get_project_root()
    config = load_project_config()

    slug = slugify(slug)
    if not slug or slug == "untitled":
        raise ValueError("A valid --slug is required (letters/numbers/hyphens).")

    rel_path = (path or slug).replace("\\", "/").strip("/")
    if not rel_path or rel_path == "." or rel_path.startswith(".."):
        raise ValueError(
            f"Project path must be a real subfolder, not the repo root (got {path!r}). "
            f"Every project lives in its own ./<slug>/ folder."
        )

    projects = config.get("projects") or []
    for entry in projects:
        if entry.get("slug") == slug:
            raise ValueError(f"A project with slug '{slug}' already exists.")
        existing_path = (entry.get("path") or "").replace("\\", "/").strip("/")
        if existing_path and existing_path == rel_path:
            raise ValueError(f"A project already uses path '{rel_path}'.")

    entry = {
        "slug": slug,
        "name": name or slug,
        "path": rel_path,
        "description": description or "",
        "source_roots": source_roots or ["src"],
        "source_extensions": source_extensions or [],
        "test_command": test_command or "",
    }
    if enforcement:
        entry["enforcement"] = enforcement

    if scaffold:
        proj_dir = root / rel_path
        (proj_dir / "docs").mkdir(parents=True, exist_ok=True)
        index = proj_dir / "docs" / "index.md"
        if not index.exists():
            index.write_text(_doc_index_stub(entry["name"]), encoding="utf-8", newline="\n")
        readme = proj_dir / "README.md"
        if not readme.exists():
            readme.write_text(
                _readme_stub(entry["name"], entry["description"]),
                encoding="utf-8",
                newline="\n",
            )

    projects.append(entry)
    config["projects"] = projects
    _save_config(root, config)

    if refresh:
        # Sync the new folder into the routing DB so docs/code are indexed.
        import routing

        routing.refresh_doc_routing()
        routing.refresh_code_routing()

    return entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Create and register a project.")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--path", default=None, help="Subfolder (defaults to slug).")
    ap.add_argument("--description", default="")
    ap.add_argument("--source-roots", nargs="*", default=None)
    ap.add_argument("--source-extensions", nargs="*", default=None)
    ap.add_argument("--test-command", default="")
    ap.add_argument("--enforcement", default=None, choices=["full", "minimal", None])
    ap.add_argument(
        "--no-scaffold",
        action="store_true",
        help="Register only; do not create the folder / doc / README.",
    )
    ap.add_argument(
        "--no-refresh",
        action="store_true",
        help="Skip routing refresh (caller will refresh).",
    )
    args = ap.parse_args(argv)

    try:
        entry = add_project(
            slug=args.slug,
            name=args.name,
            path=args.path,
            description=args.description,
            source_roots=args.source_roots,
            source_extensions=args.source_extensions,
            test_command=args.test_command,
            enforcement=args.enforcement,
            scaffold=not args.no_scaffold,
            refresh=not args.no_refresh,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    config = load_project_config()
    print(json.dumps({"added": entry, "projects": config.get("projects", [])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
