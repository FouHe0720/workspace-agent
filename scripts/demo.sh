#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
# Each run gets a new dedicated directory; existing user artifacts are never removed.
mkdir -p .local
demo_root=$(mktemp -d "${TMPDIR:-/tmp}/workspace-agent-demo.XXXXXXXX")
printf '%s\n' "Demo workspace: ${demo_root}"
.venv/bin/agent init-demo --workspace "${demo_root}"
.venv/bin/agent run '查找 RAG 笔记、整理差异并生成 study_plan.md' --workspace "${demo_root}" --dry-run
.venv/bin/agent run '查找 RAG 笔记、整理差异并生成 study_plan.md' --workspace "${demo_root}" --approve-writes
.venv/bin/python - "${demo_root}" <<'PY'
import hashlib
import sys
from pathlib import Path

artifact = Path(sys.argv[1]) / 'study_plan.md'
assert artifact.is_file()
content = artifact.read_text(encoding='utf-8')
assert all(name in content for name in ['notes/rag.md', 'notes/fastapi.md', 'notes/agent.md'])
print('Verified artifact:', artifact.name, 'sha256:', hashlib.sha256(artifact.read_bytes()).hexdigest())
PY
.venv/bin/agent mcp-demo --workspace "${demo_root}"
.venv/bin/agent tui
