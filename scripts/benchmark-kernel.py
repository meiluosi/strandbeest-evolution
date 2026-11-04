"""Boundary-inclusive native/reference timings. Run with .venv/bin/python after setup-python.sh."""
import json
import platform
import sys
import timeit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/common/tests"))
import reference_kinematics as reference
from strandbeest_common import gait_metrics, load_spec, solve_pose
from strandbeest_common.gait import foot_path
from strandbeest_common.linkage import _kernel

results = []
for file in sorted((ROOT / "contracts/kinematics").glob("*.json")):
    spec = load_spec(json.loads(file.read_text())["spec"])
    row = {"file": file.name}
    _kernel(spec)
    row["native_value_key_and_cache_hit_ms"] = timeit.timeit(lambda: _kernel(spec), number=2000) * 1000 / 2000
    for name, pose, trace, gait in [("python-reference", reference.solve_pose, reference.foot_path, reference.gait_metrics), ("rust-python", solve_pose, foot_path, gait_metrics)]:
        measurements = {}
        for key, operation, count in [("pose_ms", lambda: pose(spec, 1.234), 2000), ("trace180_ms", lambda: trace(spec, 180), 200), ("trace_and_gait_ms", lambda: gait(spec, 180), 200)]:
            for _ in range(20): operation()
            measurements[key] = timeit.timeit(operation, number=count) * 1000 / count
        row[name] = measurements
    results.append(row)
print(json.dumps({"python": platform.python_version(), "platform": platform.platform(), "units": "milliseconds per operation, binding conversion included; local warm run", "results": results}, indent=2))
