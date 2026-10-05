#!/usr/bin/env bash
# Fast Python tests for every package (slow simulator-heavy tests are marked and skipped).
set -euo pipefail
cd "$(dirname "$0")/.."
for p in packages/common packages/sim packages/fab packages/calib packages/rig apps/api; do
	echo "== $p"
	(cd "$p" && ../../.venv/bin/python -m pytest -q -m "not slow")
done
echo "== repository checks (i18n literals, schema annotations, generated models up to date, duplicated-module trigger)"
.venv/bin/python scripts/check_no_hardcoded_cjk.py
.venv/bin/python scripts/check_schema_annotations.py
.venv/bin/python scripts/check_schema_annotations.py --strict schemas/design.schema.json schemas/scenario.schema.json
.venv/bin/python scripts/gen_models.py --check
.venv/bin/python scripts/check_duplication_trigger.py
echo "== hardware/firmware (host tests of the rig logic)"
make -C hardware/firmware test
