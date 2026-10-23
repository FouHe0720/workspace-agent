#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
campus_demo_root=$(mktemp -d "${TMPDIR:-/tmp}/workspace-campus-demo.XXXXXXXX")
printf '%s\n' "Campus workspace: ${campus_demo_root}"
.venv/bin/agent init-demo --workspace "${campus_demo_root}" --scenario campus
.venv/bin/agent run '整理迎新选课和英语分级材料，生成交接索引' \
  --workspace "${campus_demo_root}" --scenario campus --dry-run
.venv/bin/agent run '整理迎新选课和英语分级材料，生成交接索引' \
  --workspace "${campus_demo_root}" --scenario campus --approve-writes
.venv/bin/python - "${campus_demo_root}" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
artifact = root / 'campus_desk.md'
content = artifact.read_text(encoding='utf-8')
assert '不含翻译学院' in content
assert '无需选择全校通选课程和通识核心课程' in content
for path in (root / 'materials').glob('*.md'):
    assert hashlib.sha256(path.read_bytes()).hexdigest() in content
print('Verified:', artifact)
print('sha256:', hashlib.sha256(artifact.read_bytes()).hexdigest())
PY
