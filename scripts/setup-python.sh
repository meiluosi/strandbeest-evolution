#!/usr/bin/env bash
# Create .venv and install the Python packages in dependency order (editable), plus test tools.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v cargo >/dev/null 2>&1; then
	echo "Rust (cargo) is required to build the local beest-kernel Python extension. Install Rust, then rerun this script." >&2
	exit 1
fi
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
	for cand in /opt/miniconda3/bin/python3.13 python3.13 python3.12 python3.11 python3; do
		if command -v "$cand" >/dev/null 2>&1 && "$cand" -m ensurepip --version >/dev/null 2>&1; then
			PY="$cand"
			break
		fi
	done
fi
BEEST_VENV_DIR="${STRANDBEEST_VENV:-.venv}"
"${PY:-python3}" -m venv "$BEEST_VENV_DIR"
"$BEEST_VENV_DIR/bin/pip" install -q --upgrade pip
# The parity suite imports this extension: do not rely on a wheel left in a developer's environment.
"$BEEST_VENV_DIR/bin/pip" install -q -e crates/beest-kernel
for p in packages/common packages/sim packages/fab packages/calib packages/rig packages/opt apps/api packages/agent; do
	"$BEEST_VENV_DIR/bin/pip" install -q -e "$p"
done
"$BEEST_VENV_DIR/bin/pip" install -q pytest httpx opencv-python-headless pyserial
echo "Python environment ready: source $BEEST_VENV_DIR/bin/activate"
