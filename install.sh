#!/usr/bin/env bash
# Career Kit one-click install (macOS / Linux)
#
#   bash install.sh
#
# Does three things: create a venv (pinned to Python 3.12 when uv is available)
# -> install deps (including iv8, from the official PyPI) -> print the MCP
# registration command using an ABSOLUTE interpreter path (avoids the classic
# "bare `python` points at the wrong interpreter" trap).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV_PY="$ROOT/.venv/bin/python"
INDEX="https://pypi.org/simple"   # iv8 only exists on the official PyPI

echo ""
echo "== Career Kit install =="
echo "repo: $ROOT"
echo ""

if command -v uv >/dev/null 2>&1; then
    echo "[1/3] uv: install Python 3.12 and create venv ..."
    uv python install 3.12
    uv venv .venv --python 3.12 --clear
    echo "[2/3] installing dependencies (-e .) ..."
    uv pip install -e . --index-url "$INDEX"
else
    PY="$(command -v python3 || command -v python || true)"
    if [ -z "$PY" ]; then
        echo "Neither python3 nor uv found. Install uv (recommended): https://docs.astral.sh/uv/"
        exit 1
    fi
    echo "[1/3] python -m venv .venv ..."
    "$PY" -m venv .venv
    "$VENV_PY" -m pip install --upgrade pip
    echo "[2/3] installing dependencies (-e .) ..."
    "$VENV_PY" -m pip install -e . --index-url "$INDEX"
fi

if [ ! -x "$VENV_PY" ]; then
    echo "Install failed: interpreter not found at $VENV_PY"
    exit 1
fi

echo "[3/3] done."
echo ""
echo "Interpreter (use this ABSOLUTE path to register the MCP server):"
echo "  $VENV_PY"
echo ""
echo "Register with your AI agent (pick one; run from any directory):"
echo "  Claude Code :  claude mcp add career-kit -- \"$VENV_PY\" -m src.server"
echo "  Codex CLI   :  codex mcp add career-kit -- \"$VENV_PY\" -m src.server"
echo "  opencode    :  add to opencode.json:"
echo "    {\"mcp\":{\"career-kit\":{\"type\":\"local\",\"command\":[\"$VENV_PY\",\"-m\",\"src.server\"],\"enabled\":true}}}"
echo ""
echo "Scrapers need a browser engine (first time, optional):"
echo "  \"$VENV_PY\" -m playwright install chromium"
echo ""
echo "Verify: start a new session and type /career-kit; a welcome guide means success."
