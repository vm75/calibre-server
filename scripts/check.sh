#!/usr/bin/env bash
set -euo pipefail
project_root=$(builtin cd -- "$(dirname -- "$0")/.." >/dev/null && builtin pwd)
builtin cd -- "$project_root" >/dev/null
for script in scripts/*.sh; do bash -n "$script"; done
python3 - <<'PY'
import ast
from pathlib import Path
for path in [*Path('patches').glob('*.py'), *Path('tests').rglob('*.py')]:
    ast.parse(path.read_text(), filename=str(path))
PY
node --check patches/remember-client.js
python3 -m unittest discover -s tests -p 'test_release.py' -v
