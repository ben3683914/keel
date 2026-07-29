#!/usr/bin/env bash
# Bootstrap script for the AI agent to call during first-run setup.
# Creates the Python venv and installs MCP dependencies.
# Exit code 0 = success, 1 = failure.
#
# Invoke as:  bash setup.sh
set -u
cd "$(dirname "$0")"

log() { echo "[setup] $*"; }

# The mcp package requires Python >= 3.10.
MIN_MINOR=10

# Find a usable python3. On macOS, /usr/bin/python3 is an Xcode Command Line
# Tools stub that passes `command -v` but fails when run if the CLT are not
# installed, and older CLT pythons are 3.9 (too old for mcp) — so we must
# actually run each candidate and check its version, newest first.
log "Looking for Python >= 3.$MIN_MINOR ..."
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    version=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || continue
    major=${version%%.*}
    minor=${version##*.}
    if [ "$major" -eq 3 ] && [ "$minor" -ge "$MIN_MINOR" ]; then
        PYTHON=$candidate
        break
    fi
    log "Skipping $candidate (Python $version is older than 3.$MIN_MINOR)."
done

if [ -z "$PYTHON" ]; then
    if command -v python3 >/dev/null 2>&1; then
        echo "SETUP_ERROR: No Python >= 3.$MIN_MINOR found. On macOS, install one with 'brew install python@3.12' (or, if python3 failed to run at all, install the Xcode Command Line Tools with 'xcode-select --install')."
    else
        echo "SETUP_ERROR: python3 not found in PATH"
    fi
    exit 1
fi
log "Using $PYTHON ($("$PYTHON" --version 2>&1))."

# A leftover venv built with an older/removed interpreter can't install mcp —
# detect that and rebuild rather than failing later at the install step.
if [ -x ".claude/venv/bin/python" ]; then
    venv_version=$(.claude/venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || venv_version=""
    venv_minor=${venv_version##*.}
    if [ -z "$venv_version" ] || [ "${venv_version%%.*}" -ne 3 ] || [ "$venv_minor" -lt "$MIN_MINOR" ]; then
        log "Existing venv uses Python ${venv_version:-<broken>} — recreating with $PYTHON."
        rm -rf .claude/venv
    fi
fi

# Create venv if missing
if [ ! -x ".claude/venv/bin/python" ]; then
    log "Creating virtual environment at .claude/venv ..."
    if ! "$PYTHON" -m venv .claude/venv; then
        echo "SETUP_ERROR: Failed to create virtual environment (on Debian/Ubuntu, is the python3-venv package installed?)"
        exit 1
    fi
else
    log "Reusing existing virtual environment at .claude/venv."
fi

VENV_PY=".claude/venv/bin/python"

# Make sure pip inside the venv is current enough to resolve modern wheels
# (the pip bundled with macOS system pythons can be quite old).
log "Upgrading pip inside the venv..."
if ! "$VENV_PY" -m pip install --quiet --upgrade pip; then
    echo "SETUP_ERROR: Failed to upgrade pip inside the venv"
    exit 1
fi

# Install/upgrade the MCP package. This is the slow step: it downloads mcp plus
# its dependencies. Output is left visible (no --quiet) so progress is obvious
# instead of the script looking hung.
#
# The version is capped below 2.0 deliberately. Our four servers are built on
# the decorator API (@server.list_tools() / @server.call_tool()), which mcp 2.0
# removed outright -- it is gone from mcp.server.Server AND from
# mcp.server.lowlevel.Server, so there is no drop-in import to switch to.
# An unpinned `pip install --upgrade mcp` therefore silently breaks every MCP
# server at import time. Do not relax this cap without porting the servers in
# .claude/scripts/mcp/ to the 2.x API first.
log "Installing the 'mcp' package and its dependencies (downloading — can take 30-90s on first run)..."
if ! "$VENV_PY" -m pip install --upgrade "mcp>=1.9,<2"; then
    echo "SETUP_ERROR: Failed to install MCP package"
    exit 1
fi

# Verify the servers actually load. Importing `Server` alone is NOT enough --
# it still succeeds on mcp 2.0, where the decorators the servers use at module
# scope are missing, so a shallow check reports success on a broken install.
# Exercising a real server module is what catches an incompatible SDK.
log "Verifying the MCP servers load..."
# (this script cd's to the repo root at the top, so relative paths are correct)
if ! "$VENV_PY" -c "
import importlib.util, sys
from pathlib import Path
root = Path.cwd()
sys.path.insert(0, str(root / '.claude' / 'scripts' / 'shared'))
sys.path.insert(0, str(root / '.claude' / 'scripts' / 'mcp'))
target = root / '.claude' / 'scripts' / 'mcp' / 'task_manager.py'
spec = importlib.util.spec_from_file_location('_smoke', target)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
" 2>/dev/null; then
    echo "SETUP_ERROR: MCP server verification failed (incompatible 'mcp' package?)"
    exit 1
fi

log "Setup complete."
echo "SETUP_COMPLETE"
