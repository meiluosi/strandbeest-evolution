"""Native phase-at-observation fixtures; no change to the historical run corpora."""
import hashlib
import json
import subprocess
from pathlib import Path

import mujoco
from strandbeest_common import Design
from strandbeest_common.schemas import schema_dir
from strandbeest_sim import run, scenario_from_design

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / 'contracts/audit-reference/phase.json'
if target.exists():
    raise FileExistsError(target)
target.parent.mkdir(exist_ok=True)
design_path = schema_dir() / 'examples/design-jansen-small-6leg.json'
design = Design(json.loads(design_path.read_text()))
rows = []
for direction in [-1, 1]:
    overrides = {'walker': {'direction': direction},
                 'run': {'settle': .05, 'revolutions': .15, 'max_time': 2, 'frame_rate': 0},
                 'drive': {'ramp': .1}}
    result = run(scenario_from_design(design, overrides))
    rows.append({'direction': direction, 'overrides': overrides,
                 'theta_rad': result.series['theta_rad'].tolist(), 'psi_rad': result.psi.tolist(),
                 't_s': result.t.tolist(), 'stalled': bool(result.stalled)})
doc = {'scope': 'absolute phase and left-endpoint observation; not a physical-validation fixture',
       'mujoco': mujoco.mj_versionString(), 'design': str(design_path.relative_to(ROOT)),
       'design_sha256': hashlib.sha256(design_path.read_bytes()).hexdigest(), 'cases': rows}
target.write_text(json.dumps(doc, indent=2, allow_nan=False)+'\n')
subprocess.run(['pnpm', 'exec', 'biome', 'format', '--write', str(target)], cwd=ROOT, check=True)
print(json.dumps({'cases': len(rows), 'samples': [len(r['theta_rad']) for r in rows]}))
