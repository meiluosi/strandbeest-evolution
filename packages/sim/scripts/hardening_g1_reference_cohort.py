"""Read-only, geometry-only comparison of the original 64 G1 inputs."""
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'packages/sim/scripts'))
import hardening_g1_contact_diagnostic as diagnostic
from strandbeest_sim.builder import build, resolve_spec
from strandbeest_sim.config import sim_config
from strandbeest_sim.events import nominal_stride_m
from strandbeest_sim.skeptic import STRIDE_TOLERANCE

paths = {label: ROOT / f'experiments/hardening-g1-contact-v3-{suffix}-2026-11-04.json'
         for label, suffix in [('default', 'default'), ('strong', 'solref05'), ('half', 'solref05-dt005')]}
cohorts = {label: json.loads(path.read_text()) for label, path in paths.items()}
target = Path(sys.argv[1])
if target.exists():
    raise FileExistsError(target)
assert all(d['complete'] and d['n'] == 64 and d['seed'] == 1 and len(d['rows']) == 64 for d in cohorts.values())
initial = diagnostic.source_hashes()
start = time.monotonic()
rows = []
for original in cohorts['half']['rows']:
    sc = sim_config(original['scenario'])
    spec = resolve_spec(sc)
    tree = ET.fromstring(build(sc, spec).xml)
    spheres = [(body, geom) for body in tree.iter('body') for geom in body.findall('geom')
               if geom.get('name', '').startswith('foot_')]
    body, sphere = spheres[0]
    match = re.fullmatch(r'bar(\d+)_(.+)([01])', body.get('name'))
    joint = next(j for j in spec.joints if j.id == match[2])
    owner = {'start': joint.centers[int(match[3])], 'end': match[2],
             'radius_m': float(sphere.attrib['size']), 'body': body.get('name')}
    references = [diagnostic.geometry_reference(sc, spec, [owner], count) for count in [720, 1440]]
    nominal = nominal_stride_m(sc)
    comparisons = {}
    for label, cohort in cohorts.items():
        row = next(r for r in cohort['rows'] if r['case'] == original['case'])
        assert row['design'] == original['design']
        stride = row['metrics']['stride_per_rev']
        comparisons[label] = {'actual_m_per_rev': stride, 'stalled': row['stalled'],
             'original_findings': row['findings'],
             'relative_errors': {key: abs(stride / ref - 1) if ref else None for key, ref in
                [('legacy', nominal), ('point', references[-1]['point_stride_m_per_rev']),
                 ('sphere', references[-1]['contact_stride_m_per_rev'])]}}
    rows.append({'case': original['case'], 'terrain': sc.terrain.kind,
                 'legs': sc.walker.legs, 'direction': sc.walker.direction,
                 'legacy_nominal_m_per_rev': nominal, 'sphere_owner': owner,
                 'references': references, 'comparisons': comparisons})
    print('geometry', original['case'], 'of 64', flush=True)

summary = {}
for label in cohorts:
    flat = [r for r in rows if r['terrain'] == 'flat' and not r['comparisons'][label]['stalled']]
    summary[label] = {'flat_nonstalled': len(flat), **{key + '_exceeds_original_15pct':
        [r['case'] for r in flat if r['comparisons'][label]['relative_errors'][key] is None or
         r['comparisons'][label]['relative_errors'][key] > STRIDE_TOLERANCE]
        for key in ['legacy', 'point', 'sphere']}}
out = {'complete': True, 'full_cohort_pass': False, 'changes_live_audit': False,
       'inference_limit': 'Point and sphere references are alternative ideal models, not replacements for the current acceptance gate. They do not predict compliant-contact loads or slip.',
       'source_sha256': initial, 'source_drift': diagnostic.changed_sources(initial, diagnostic.source_hashes()),
       'script_sha256': diagnostic.digest(__file__),
       'input_sha256': {label: diagnostic.digest(path) for label, path in paths.items()},
       'threshold': STRIDE_TOLERANCE, 'rows': rows, 'summary': summary,
       'wall_s': time.monotonic() - start}
with target.open('x') as f:
    json.dump(out, f, indent=2, allow_nan=False)
    f.write('\n')
print(json.dumps(summary, indent=2), flush=True)
