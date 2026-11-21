#!/usr/bin/env bash
# One-command local setup: virtualenv, dependencies, first admin user, tests (optional).
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements-dev.txt
export SHIELDCAD_DATA_DIR="${SHIELDCAD_DATA_DIR:-./data}"
if [ ! -f "$SHIELDCAD_DATA_DIR/users.json" ]; then
  echo "Creating first admin user 'admin' (key is shown once):"
  python -m shieldcad.admin add-user admin admin --days 90
fi
[ "${1:-}" = "--test" ] && python -m pytest -q
echo
echo "Start the server:  . .venv/bin/activate && python -m shieldcad.server   ->  http://127.0.0.1:8000"
