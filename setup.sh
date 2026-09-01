#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Jarvis V1 requires Python 3.11+")
print(f"Using Python {sys.version.split()[0]}")
PY

if [ ! -d .venv ]; then
    "$PYTHON_BIN" -m venv .venv
fi

if [ -x .venv/bin/python ]; then
    VENV_PY=.venv/bin/python
else
    echo "Could not find .venv/bin/python" >&2
    exit 1
fi

"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -e '.[voice,dev]'

if [ ! -f config/jarvis.toml ]; then
    cp config/jarvis.example.toml config/jarvis.toml
fi

cat <<'TXT'

Jarvis V1 Python environment is ready.
Next:
  1. export OPENAI_API_KEY='...'
  2. .venv/bin/python scripts/bootstrap_third_party.py   # one-time, needs Internet
  3. .venv/bin/python -m jarvis health
  4. .venv/bin/python scripts/dev_start.py

For voice-only use without the optional UI components:
  .venv/bin/python scripts/dev_start.py --no-board --no-visualizer
TXT
