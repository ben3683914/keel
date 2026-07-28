"""Shared routing utilities for doc and code routing.

Callable from MCP servers (docs_manager, code_manager) and hooks
without importing MCP server dependencies.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import get_db, json_dumps, json_loads
from db import get_project_root as _resolve_root
from projects import sync_projects_from_config, get_project_by_slug, WORKSPACE_ID


def get_project_root() -> Path:
    # Resolve UP from the current directory rather than trusting it raw: a hook
    # subprocess (e.g. track_modifications -> refresh_doc_routing) inherits the
    # drifted shell cwd, so a bare Path.cwd() would scan a sub-directory and
    # register subdir-relative routing rows into the real workspace DB. Passing
    # cwd as an explicit root uses db.py's loop-1-only resolution: it climbs to
    # the nearest ancestor that already has a claude.db, else honors cwd exactly
    # (never the .claude/.git heuristic, which would collapse a fresh cwd onto a
    # bare ~/.claude). At the workspace root this is a no-op.
    return _resolve_root(Path.cwd())


def load_project_config() -> dict:
    path = get_project_root() / ".claude" / "project-config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def routing_projects(conn) -> list[tuple[int, dict | None]]:
    """Routing targets as (project_id, config_entry). The workspace project
    (id=1, entry=None) is first, then each declared project in config.projects[].
    Ensures a DB project row exists for every config project (sync by slug)."""
    config = load_project_config()
    sync_projects_from_config(conn, config)
    targets: list[tuple[int, dict | None]] = [(WORKSPACE_ID, None)]
    for entry in config.get("projects", []) or []:
        slug = entry.get("slug")
        if not slug:
            continue
        row = get_project_by_slug(conn, slug)
        if row:
            targets.append((row["id"], entry))
    return targets


def registered_project_paths() -> list[str]:
    """Relative paths of declared projects (used to keep the workspace scan from
    double-claiming files that belong to a sub-project)."""
    config = load_project_config()
    out = []
    for entry in config.get("projects", []) or []:
        p = (entry.get("path") or "").replace("\\", "/").strip("/")
        if p:
            out.append(p)
    return out


def count_lines(file_path: Path) -> int:
    try:
        return len(file_path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


# --- Doc Routing ---


def get_doc_patterns() -> list[str]:
    config = load_project_config()
    return config.get("doc_patterns", ["docs/**/*.md"])


def get_all_doc_dirs(conn) -> list[tuple[int, Path]]:
    """(project_id, docs_dir) per project. The workspace project owns root
    `docs/`; each declared project owns `<path>/docs/`. A single-project
    workspace is just the workspace target plus that one project."""
    root = get_project_root()
    out = []
    for pid, entry in routing_projects(conn):
        if entry is None:
            out.append((pid, root / "docs"))
        else:
            p = (entry.get("path") or "").replace("\\", "/").strip("/")
            out.append((pid, root / p / "docs"))
    return out


STOPWORDS = {
    "about", "above", "after", "again", "also", "always", "area",
    "based", "been", "before", "being", "both", "case", "changes",
    "complete", "configuration", "contents", "could", "current",
    "data", "default", "deferred", "design", "detail", "details",
    "diagram", "does", "done", "during", "each", "effect", "else",
    "enabled", "every", "example", "examples", "expected", "field",
    "fields", "first", "flow", "following", "format", "from", "full",
    "future", "general", "given", "handling", "have", "here",
    "high", "implementation", "important", "included", "into", "item",
    "items", "just", "keep", "last", "levels", "like", "line", "list",
    "long", "made", "main", "make", "many", "mode", "more", "most",
    "must", "name", "needed", "never", "next", "none", "normal",
    "notes", "number", "object", "once", "only", "open", "optional",
    "order", "other", "over", "overview", "path", "play", "process",
    "properties", "record", "reference", "required", "resolved",
    "rest", "result", "same", "section", "send", "sequence", "should",
    "show", "side", "since", "size", "some", "specific", "state",
    "status", "step", "steps", "still", "stop", "storage", "string",
    "structure", "style", "summary", "system", "table", "take",
    "text", "that", "their", "them", "then", "there", "these",
    "they", "this", "through", "time", "token", "total", "turn",
    "type", "types", "under", "until", "used", "using", "value",
    "very", "want", "well", "were", "what", "when", "where",
    "which", "while", "will", "with", "within", "work", "works",
    "would", "your",
}

SKIP_HEADINGS = {
    "overview", "contents", "example", "examples", "notes",
    "summary", "table", "appendix", "details", "reference",
}


def extract_heading_keywords(file_path: Path) -> list[str]:
    keywords = set()
    try:
        content = file_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            match = re.match(r"^#{2,3}\s+(?:\d+(?:\.\d+)*\.?\s+)?(.+)", line)
            if not match:
                continue
            heading = match.group(1).strip()
            heading = re.sub(r"[`*_\[\]()]", "", heading)
            heading_lower = heading.lower().strip()
            if heading_lower in SKIP_HEADINGS:
                continue
            words = heading_lower.split()
            if 2 <= len(words) <= 4:
                phrase = " ".join(w.strip(".-:,;") for w in words)
                keywords.add(phrase)
            for word in words:
                word = word.strip(".-()[]{}:,;")
                if len(word) >= 4 and word not in STOPWORDS and not re.match(r"^\d", word):
                    keywords.add(word)
    except OSError:
        pass
    return sorted(keywords)


def _all_source_base_dirs() -> list[str]:
    """Source-root prefixes across the workspace and every declared project
    (project roots are prefixed by the project path), for doc->source ref boosts."""
    config = load_project_config()
    base_dirs = set()
    for r in (config.get("source_roots") or ["src"]):
        rc = r.replace("\\", "/").strip("/")
        if rc and rc != ".":
            base_dirs.add(rc)
    for entry in config.get("projects", []) or []:
        p = (entry.get("path") or "").replace("\\", "/").strip("/")
        roots = entry.get("source_roots") or config.get("source_roots") or ["src"]
        for r in roots:
            rc = r.replace("\\", "/").strip("/")
            if not rc or rc == ".":
                if p:
                    base_dirs.add(p)
            else:
                base_dirs.add(f"{p}/{rc}" if p else rc)
    return sorted(base_dirs)


def extract_source_refs(file_path: Path) -> list[str]:
    base_dirs = _all_source_base_dirs()
    refs = set()
    try:
        content = file_path.read_text(encoding="utf-8")
        for base_dir in base_dirs:
            for match in re.finditer(rf"(?:{re.escape(base_dir)}/[\w/.-]+)", content):
                path = match.group(0)
                if "." in path.split("/")[-1]:
                    path = "/".join(path.split("/")[:-1]) + "/"
                refs.add(path)
    except OSError:
        pass
    return sorted(refs)


def refresh_doc_routing() -> list[str]:
    """Scan docs per project, update doc_routing. Rows are keyed (project_id, path).
    Returns list of changes."""
    root = get_project_root()
    conn = get_db()
    changes = []

    try:
        existing = {
            (row["project_id"], row["path"]): row
            for row in conn.execute("SELECT * FROM doc_routing").fetchall()
        }
        actual = {}  # (project_id, rel_path) -> full Path
        for pid, docs_dir in get_all_doc_dirs(conn):
            if not docs_dir.exists():
                continue
            for md_file in docs_dir.rglob("*.md"):
                rel_path = str(md_file.relative_to(root)).replace("\\", "/")
                actual[(pid, rel_path)] = md_file

        for key in sorted(actual.keys() - existing.keys()):
            pid, doc_path = key
            full_path = actual[key]
            auto_kw = extract_heading_keywords(full_path)
            source_refs = extract_source_refs(full_path)
            conn.execute(
                "INSERT INTO doc_routing (project_id, path, keywords, auto_keywords, source_paths) "
                "VALUES (?, ?, ?, ?, ?)",
                (pid, doc_path, "[]", json_dumps(auto_kw), json_dumps(source_refs)),
            )
            changes.append(f"ADDED: {doc_path} ({len(auto_kw)} auto keywords)")

        for key in sorted(existing.keys() - actual.keys()):
            pid, doc_path = key
            conn.execute(
                "DELETE FROM doc_routing WHERE project_id = ? AND path = ?", (pid, doc_path)
            )
            changes.append(f"REMOVED: {doc_path}")

        for key in actual.keys() & existing.keys():
            pid, doc_path = key
            full_path = actual[key]
            if not full_path.exists():
                continue

            heading_kw = extract_heading_keywords(full_path)
            old_auto = set(json_loads(existing[key]["auto_keywords"]))

            if set(heading_kw) != old_auto:
                added = set(heading_kw) - old_auto
                removed = old_auto - set(heading_kw)
                delta_parts = []
                if added:
                    delta_parts.append(f"+{len(added)}")
                if removed:
                    delta_parts.append(f"-{len(removed)}")
                conn.execute(
                    "UPDATE doc_routing SET auto_keywords = ? WHERE project_id = ? AND path = ?",
                    (json_dumps(heading_kw), pid, doc_path),
                )
                changes.append(f"AUTO_KEYWORDS: {doc_path} {', '.join(delta_parts)} (total: {len(heading_kw)})")

            content_refs = extract_source_refs(full_path)
            existing_refs = set(json_loads(existing[key]["source_paths"]))
            new_refs = set(content_refs) - existing_refs
            if new_refs:
                all_refs = sorted(existing_refs | new_refs)
                conn.execute(
                    "UPDATE doc_routing SET source_paths = ? WHERE project_id = ? AND path = ?",
                    (json_dumps(all_refs), pid, doc_path),
                )
                changes.append(f"PATHS: {doc_path} +{len(new_refs)}")

        if changes:
            conn.commit()
    finally:
        conn.close()

    return changes


# --- Code Routing ---


DEFINITION_PATTERNS = re.compile(
    r"\b(?:def|fn|func|function|class|interface|struct|enum|trait|impl|module|package)\s+(\w+)",
    re.MULTILINE,
)


DEFAULT_EXCLUDE_DIRS = [
    "node_modules", ".venv", "venv", "build", "dist", ".git", ".claude",
    "__pycache__", "target", "out", ".next", "coverage", "docs", "tests",
]


def get_source_config(entry: dict | None = None) -> tuple[list[str], list[str], list[str]]:
    """(source_roots, source_extensions, exclude_dirs) for a project entry.
    entry=None uses top-level/workspace config. Per-project keys fall back to the
    top-level value when absent so a project need only override what differs."""
    config = load_project_config()

    def pick(key, default):
        if entry is not None and entry.get(key):
            return entry.get(key)
        return config.get(key) or default

    roots = pick("source_roots", ["src"])
    exts = pick("source_extensions", [])
    if entry is not None and entry.get("exclude_dirs") is not None:
        excludes = entry.get("exclude_dirs")
    else:
        excludes = config.get("exclude_dirs")
    if excludes is None:
        excludes = list(DEFAULT_EXCLUDE_DIRS)
    return roots, exts, excludes


def get_all_source_dirs(conn) -> list[tuple[int, dict | None, Path]]:
    """(project_id, config_entry, scan_root) per project. Workspace first
    (entry=None, scans repo root); each declared project scans its own path."""
    root = get_project_root()
    out = []
    for pid, entry in routing_projects(conn):
        if entry is None:
            out.append((pid, None, root))
        else:
            p = (entry.get("path") or "").replace("\\", "/").strip("/")
            out.append((pid, entry, root / p))
    return out


def extract_auto_keywords(file_path: Path) -> list[str]:
    keywords = set()
    root = get_project_root()
    try:
        rel = str(file_path.relative_to(root)).replace("\\", "/")
    except ValueError:
        rel = str(file_path).replace("\\", "/")

    path_no_ext = re.sub(r"\.[^.]+$", "", rel)
    parts = path_no_ext.split("/")
    for part in parts:
        if part in ("src", "lib", "index", "mod", "main", "app", "tests", "test"):
            continue
        words = re.split(r"[-_]", part)
        if len(words) > 1:
            keywords.add(part)
        for word in words:
            if len(word) >= 4:
                keywords.add(word.lower())

    try:
        content = file_path.read_text(encoding="utf-8")
        for match in DEFINITION_PATTERNS.finditer(content):
            name = match.group(1)
            words = re.sub(r"([A-Z])", r" \1", name).strip().split()
            for word in words:
                lower = word.lower()
                if len(lower) >= 4:
                    keywords.add(lower)
    except OSError:
        pass

    return sorted(keywords)


def _scan_source_files(
    scan_root: Path,
    roots: list[str],
    exts: list[str],
    excludes: list[str],
    exclude_paths: list[str] | None = None,
) -> set[str]:
    root = get_project_root()
    exclude_set = set(excludes)
    ext_set = set(exts)
    exclude_paths = exclude_paths or []
    files = set()

    if roots == ["."] or not roots:
        start_dirs = [scan_root]
    else:
        start_dirs = []
        for r in roots:
            r_clean = r.replace("\\", "/").strip("/")
            if not r_clean or r_clean == ".":
                start_dirs.append(scan_root)
                continue
            candidate = scan_root / r_clean
            if candidate.exists() and candidate.is_dir():
                start_dirs.append(candidate)

    for start in start_dirs:
        for path in start.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel_parts = path.relative_to(scan_root).parts
            except ValueError:
                continue
            if any(part in exclude_set for part in rel_parts):
                continue
            if ext_set and path.suffix not in ext_set:
                continue
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            # Workspace scan must not claim files that belong to a declared project.
            if any(rel == ep or rel.startswith(ep + "/") for ep in exclude_paths):
                continue
            files.add(rel)
    return files


def refresh_code_routing() -> list[str]:
    """Scan source files and update code_routing table."""
    root = get_project_root()
    conn = get_db()
    changes = []

    try:
        existing = {
            (row["project_id"], row["path"]): row
            for row in conn.execute("SELECT * FROM code_routing").fetchall()
        }

        actual = {}  # (project_id, rel_path) -> full Path
        project_paths = registered_project_paths()
        for pid, entry, scan_root in get_all_source_dirs(conn):
            roots, exts, excludes = get_source_config(entry)
            exclude_paths = project_paths if entry is None else []
            for rel in _scan_source_files(scan_root, roots, exts, excludes, exclude_paths):
                actual[(pid, rel)] = root / rel

        for key in sorted(actual.keys() - existing.keys()):
            pid, file_path = key
            full_path = actual[key]
            auto_kw = extract_auto_keywords(full_path)
            line_count = count_lines(full_path)
            conn.execute(
                "INSERT INTO code_routing (project_id, path, description, line_count, exports, dependencies, keywords, auto_keywords) "
                "VALUES (?, ?, '', ?, '[]', '[]', '[]', ?)",
                (pid, file_path, line_count, json_dumps(auto_kw)),
            )
            changes.append(f"ADDED: {file_path} ({line_count} lines)")

        for key in sorted(existing.keys() - actual.keys()):
            pid, file_path = key
            conn.execute(
                "DELETE FROM code_routing WHERE project_id = ? AND path = ?", (pid, file_path)
            )
            changes.append(f"REMOVED: {file_path}")

        for key in actual.keys() & existing.keys():
            pid, file_path = key
            full_path = actual[key]
            if not full_path.exists():
                continue

            new_auto_kw = extract_auto_keywords(full_path)
            old_auto_kw = set(json_loads(existing[key]["auto_keywords"]))

            updates = {}
            if set(new_auto_kw) != old_auto_kw:
                updates["auto_keywords"] = json_dumps(new_auto_kw)
                added = set(new_auto_kw) - old_auto_kw
                removed = old_auto_kw - set(new_auto_kw)
                delta = []
                if added:
                    delta.append(f"+{len(added)}")
                if removed:
                    delta.append(f"-{len(removed)}")
                changes.append(f"AUTO_KEYWORDS: {file_path} {', '.join(delta)} (total: {len(new_auto_kw)})")

            new_count = count_lines(full_path)
            if new_count != existing[key]["line_count"]:
                updates["line_count"] = new_count

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE code_routing SET {set_clause} WHERE project_id = ? AND path = ?",
                    (*updates.values(), pid, file_path),
                )

        if changes:
            conn.commit()
    finally:
        conn.close()

    return changes


# --- Hook Utility ---


def _matches_source(rel: str, roots: list[str], exts: list[str], excludes: list[str]) -> bool:
    parts = rel.split("/")
    if any(part in excludes for part in parts):
        return False
    last = parts[-1] if parts else ""
    ext = Path(last).suffix
    if exts and ext not in exts:
        return False
    if not roots or roots == ["."]:
        return True
    for r in roots:
        r_norm = r.replace("\\", "/").strip("/")
        if not r_norm or r_norm == ".":
            return True
        if rel == r_norm or rel.startswith(r_norm + "/"):
            return True
    return False


def is_source_file(file_path: str) -> bool:
    """True if the path qualifies as a source file under ANY project's
    (source_roots, source_extensions, exclude_dirs) triad. The hook only needs
    to know whether an edit is source-y enough to gate; project attribution is
    resolved separately via projects.project_for_path."""
    normalized = file_path.replace("\\", "/")
    root_str = str(get_project_root()).replace("\\", "/").rstrip("/")
    rel = normalized
    if root_str and normalized.startswith(root_str + "/"):
        rel = normalized[len(root_str) + 1:]
    rel = rel.lstrip("/")

    config = load_project_config()
    # Workspace candidate (prefix '') then each declared project (its path prefix).
    candidates = [("", get_source_config(None))]
    for entry in config.get("projects", []) or []:
        p = (entry.get("path") or "").replace("\\", "/").strip("/")
        candidates.append((p, get_source_config(entry)))

    for prefix, (roots, exts, excludes) in candidates:
        sub = rel
        if prefix:
            if rel == prefix:
                sub = ""
            elif rel.startswith(prefix + "/"):
                sub = rel[len(prefix) + 1:]
            else:
                continue  # file not under this project's subtree
        if _matches_source(sub, roots, exts, excludes):
            return True
    return False
