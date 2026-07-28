"""assemble validation: assemble.py mode derivation + template_dev flip.

This is the config/assemble layer the handler tests can't reach. The critical
case: the template_dev flip must key on `enforcement`, not `projects[]` — a
scaffold-only maintainer can write enforcement with an empty projects[], and the
flip must still fire (else downstream users stay locked in template-dev forever).

    .claude/venv/bin/python .claude/scripts/tests/test_assemble.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ASSEMBLE = REPO / ".claude" / "scripts" / "assemble.py"
SCAFFOLDS = REPO / ".claude" / "scaffolds"
PYTHON = REPO / ".claude" / "venv" / "bin" / "python"

_checks = 0
_failures = []


def check(label, cond):
    global _checks
    _checks += 1
    print(f"  {'ok:  ' if cond else 'FAIL:'} {label}")
    if not cond:
        _failures.append(label)


def assemble(tmp: Path, config: dict, mode_override: str | None = None):
    claude = tmp / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SCAFFOLDS, claude / "scaffolds", dirs_exist_ok=True)
    (claude / "project-config.json").write_text(json.dumps(config), encoding="utf-8")
    cmd = [str(PYTHON), str(ASSEMBLE), "--project-root", str(tmp)]
    if mode_override:
        cmd += ["--mode", mode_override]
    r = subprocess.run(cmd, capture_output=True, text=True)
    final_cfg = json.loads((claude / "project-config.json").read_text(encoding="utf-8"))
    claude_md = (tmp / "CLAUDE.md").read_text(encoding="utf-8") if (tmp / "CLAUDE.md").exists() else ""
    return r.stdout + r.stderr, final_cfg, claude_md


def case(config, mode_override=None):
    with tempfile.TemporaryDirectory() as tmp:
        return assemble(Path(tmp), config, mode_override)


def main():
    base = {"template_dev": True, "projects": []}

    # 1. enforcement full + EMPTY projects[] -> flip true->false (keys on enforcement).
    out, cfg, md = case({**base, "enforcement": "full"})
    check("enforcement full: assembles as 'project' mode", "mode: project" in out)
    check("enforcement full: template_dev FLIPS to false", cfg.get("template_dev") is False)
    check("enforcement full: CLAUDE.md is project flavor", "## Mode: Project" in md)

    # 2. pristine template (enforcement "", empty projects[]) -> STAYS true.
    out, cfg, md = case({**base, "enforcement": ""})
    check("pristine template: template_dev STAYS true", cfg.get("template_dev") is True)
    check("pristine template: still assembles (project default)", "mode: project" in out)

    # 3. scratch workspace (enforcement minimal) -> flip + scratchpad flavor.
    out, cfg, md = case({**base, "enforcement": "minimal"})
    check("scratch: assembles as 'scratchpad' mode", "mode: scratchpad" in out)
    check("scratch: template_dev flips to false", cfg.get("template_dev") is False)

    # 4. multi-project (enforcement full, populated projects[]) -> flip.
    out, cfg, md = case({**base, "enforcement": "full",
                         "projects": [{"slug": "web", "name": "Web", "path": "apps/web"}]})
    check("multi-project: template_dev flips to false", cfg.get("template_dev") is False)

    # 5. --mode override on pristine config must NOT flip template_dev.
    out, cfg, md = case({**base, "enforcement": ""}, mode_override="project")
    check("--mode override: does NOT flip template_dev", cfg.get("template_dev") is True)

    print()
    if _failures:
        print(f"ASSEMBLE: {len(_failures)}/{_checks} FAILED -> {_failures}")
        sys.exit(1)
    print(f"ASSEMBLE: all {_checks} checks passed")


if __name__ == "__main__":
    main()
