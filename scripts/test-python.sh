#!/usr/bin/env bash
# Fast Python tests for every package (slow simulator-heavy tests are marked and skipped).
set -euo pipefail
cd "$(dirname "$0")/.."
for p in packages/common packages/sim packages/fab packages/calib packages/rig apps/api; do
	echo "== $p"
	(cd "$p" && ../../.venv/bin/python -m pytest -q -m "not slow")
done
echo "== hardware/firmware (host tests of the rig logic)"
make -C hardware/firmware test
