#!/usr/bin/env bash
# Create .venv and install the Python packages in dependency order (editable), plus test tools.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
for p in packages/common packages/sim packages/fab packages/calib apps/api; do
	.venv/bin/pip install -q -e "$p"
done
.venv/bin/pip install -q pytest httpx
echo "Python environment ready: source .venv/bin/activate"
