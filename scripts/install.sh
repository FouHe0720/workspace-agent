#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if command -v uv >/dev/null 2>&1; then
  uv sync --frozen --extra dev
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -e '.[dev]'
fi
.venv/bin/agent --help >/dev/null
