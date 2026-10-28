#!/usr/bin/env bash
# Create .venv and install the Python packages in dependency order (editable), plus test tools.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
	for cand in /opt/miniconda3/bin/python3.13 python3.13 python3.12 python3.11 python3; do
		if command -v "$cand" >/dev/null 2>&1 && "$cand" -m ensurepip --version >/dev/null 2>&1; then
			PY="$cand"
			break
		fi
	done
fi
"${PY:-python3}" -m venv .venv
.venv/bin/pip install -q --upgrade pip
for p in packages/common packages/sim packages/fab packages/calib packages/rig packages/opt apps/api packages/agent; do
	.venv/bin/pip install -q -e "$p"
done
.venv/bin/pip install -q pytest httpx opencv-python-headless pyserial
echo "Python environment ready: source .venv/bin/activate"
