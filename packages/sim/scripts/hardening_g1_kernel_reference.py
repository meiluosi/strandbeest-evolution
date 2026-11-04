"""All 64 original G1 inputs through native + WASM shared geometric reference.

No dynamic simulation is rerun. Historical measured metrics/findings stay intact;
this is an ideal-model comparison and never a replacement acceptance protocol.
Run: .venv/bin/python packages/sim/scripts/hardening_g1_kernel_reference.py OUTPUT.json
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import beest_kernel
from strandbeest_common import stride_reference
from strandbeest_common.linkage import _kernel_spec
from strandbeest_sim.builder import build, resolve_spec
from strandbeest_sim.config import sim_config
from strandbeest_sim.skeptic import STRIDE_TOLERANCE

ROOT = Path(__file__).resolve().parents[3]
RESOLUTIONS = [720, 1440, 2880]
METRIC_KEYS = ['point_stride_m_per_rev', 'rolling_m_per_rev', 'contact_stride_m_per_rev']
NUMERICAL_PARITY_M = 1e-12  # Binding/numerical comparison, not the physical 15% gate.


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    paths = set((ROOT / 'crates/beest-kernel/src').glob('*.rs'))
    for directory in ['packages/core/src', 'packages/common/src', 'packages/sim/src']:
        paths.update(p for p in (ROOT / directory).rglob('*') if p.suffix in {'.ts', '.py'})
    paths.update((ROOT / 'crates/beest-kernel/generated').glob('*'))
    paths.update(Path(beest_kernel.__file__).resolve().parent.glob('*.so'))
    paths.update([Path(__file__).resolve(), ROOT / 'scripts/compare-stride-kernel.ts',
                  ROOT / 'contracts/stride-reference/cases.json', ROOT / 'Cargo.lock'])
    return {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): digest(p) for p in sorted(paths)}


def main():
    target = Path(sys.argv[1])
    if target.exists():
        raise FileExistsError(target)
    paths = {label: ROOT / f'experiments/hardening-g1-audit-energy-v3-{suffix}-2026-11-04.json'
             for label, suffix in [('default', 'default'), ('strong', 'solref05'), ('half', 'solref05-dt005')]}
    old_reference_path = ROOT / 'experiments/hardening-g1-reference-cohort-2026-11-04.json'
    old_reference = {r['case']: r for r in json.loads(old_reference_path.read_text())['rows']}
    cohorts = {label: json.loads(path.read_text()) for label, path in paths.items()}
    for cohort in cohorts.values():
        assert cohort['complete'] and cohort['n'] == 64 and cohort['seed'] == 1
        assert [r['case'] for r in cohort['rows']] == list(range(64))
    before = source_hashes()
    started = time.monotonic()
    requests, rows = [], []
    for original in cohorts['half']['rows']:
        case = original['case']
        sc = sim_config(original['scenario'])
        spec = resolve_spec(sc)
        tree = ET.fromstring(build(sc, spec).xml)
        owners = []
        for body in tree.iter('body'):
            for sphere in body.findall('geom'):
                if not sphere.get('name', '').startswith('foot_'):
                    continue
                match = re.fullmatch(r'bar(\d+)_(.+)([01])', body.attrib['name'])
                assert match is not None
                joint = next(j for j in spec.joints if j.id == match[2])
                owners.append(dict(leg=int(match[1]), body=body.attrib['name'],
                                   start=joint.centers[int(match[3])], end=joint.id,
                                   radius_m=float(sphere.attrib['size'])))
        assert len(owners) == sc.walker.legs
        assert sorted(o['leg'] for o in owners) == list(range(sc.walker.legs))
        owner = owners[0]
        assert all(o['start'] == owner['start'] and o['end'] == spec.foot and
                   o['radius_m'] == sc.walker.foot_radius for o in owners)
        options = dict(owner_start=owner['start'], phases_rad=[math.tau * k / sc.walker.legs for k in range(sc.walker.legs)],
                       direction=sc.walker.direction, unit_m=sc.walker.unit, radius_m=owner['radius_m'], brackets=720)
        native = [stride_reference(spec, **{**options, 'brackets': n}) for n in RESOLUTIONS]
        serialized_spec = _kernel_spec(spec)
        serialized_spec['crank'] = {k: serialized_spec.pop('crank_' + k) for k in ['x', 'y', 'length']}
        requests.append(dict(case=case, spec=serialized_spec, options=options, resolutions=RESOLUTIONS))
        comparisons = {}
        for label, cohort in cohorts.items():
            actual = cohort['rows'][case]
            assert actual['design'] == original['design']
            reference = native[-1]['estimate']
            stride = reference['contact_stride_m_per_rev'] if reference else None
            comparisons[label] = dict(actual_m_per_rev=actual['metrics']['stride_per_rev'],
                stalled=actual['stalled'], original_findings=actual['findings'],
                relative_error=abs(actual['metrics']['stride_per_rev'] / stride - 1) if stride else None)
        rows.append(dict(case=case, terrain=sc.terrain.kind, legs=sc.walker.legs,
                         options=options, sphere_owners=owners, native=native,
                         prior_geometry=old_reference[case]['references'][-1], comparisons=comparisons))
        print(f'Native geometry {case + 1}/64', flush=True)
    process = subprocess.run(['node', '--import', 'tsx', 'scripts/compare-stride-kernel.ts'],
                             cwd=ROOT, input=json.dumps(requests, allow_nan=False), text=True,
                             capture_output=True, check=True)
    wasm = json.loads(process.stdout)
    assert [r['case'] for r in wasm['rows']] == list(range(64))
    for row, web in zip(rows, wasm['rows'], strict=True):
        row['wasm'] = web['results']
        row['binding_max_error_m'] = 0.0
        row['prior_geometry_max_error_m'] = 0.0
        estimates = []
        for native, web_result in zip(row['native'], row['wasm'], strict=True):
            assert native['status'] == web_result['status']
            assert native['status'] == 'estimated', f"Unresolved geometry case {row['case']}: {native['status']}"
            estimate = native['estimate']
            estimates.append(estimate)
            row['binding_max_error_m'] = max(row['binding_max_error_m'],
                *(abs(estimate[key] - web_result['estimate'][key]) for key in METRIC_KEYS))
            row['prior_geometry_max_error_m'] = max(row['prior_geometry_max_error_m'],
                *(abs(estimate[key] - row['prior_geometry'][key]) for key in METRIC_KEYS))
        row['resolution_max_error_m'] = max(abs(e[key] - estimates[-1][key]) for e in estimates for key in METRIC_KEYS)
    after = source_hashes()
    drift = [p for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    summary = {}
    for label in cohorts:
        flat = [r for r in rows if r['terrain'] == 'flat' and not r['comparisons'][label]['stalled']]
        summary[label] = dict(
            original_failed_cases=[r['case'] for r in cohorts[label]['rows'] if r['findings']],
            flat_nonstalled=len(flat),
            ideal_sphere_exceeds_original_15pct=[r['case'] for r in flat if r['comparisons'][label]['relative_error'] is None or
                                               r['comparisons'][label]['relative_error'] > STRIDE_TOLERANCE])
    max_errors = {key: max(r[key] for r in rows) for key in ['binding_max_error_m', 'prior_geometry_max_error_m', 'resolution_max_error_m']}
    numerical_pass = all(v <= NUMERICAL_PARITY_M for v in max_errors.values()) and not drift
    document = dict(complete=True, shared_geometry_checks_pass=numerical_pass,
                    full_cohort_pass=False, changes_live_audit=False, dynamics_rerun=False,
                    inference_limit='Rigid flat no-slip geometric diagnostic only. Dynamic inputs/results and the original audit are unchanged. Finite-resolution agreement does not prove all support events were found.',
                    source_sha256=before, source_drift=drift,
                    input_sha256={str(p.relative_to(ROOT)): digest(p) for p in [*paths.values(), old_reference_path]},
                    resolutions=RESOLUTIONS, numerical_parity_tolerance_m=NUMERICAL_PARITY_M,
                    original_stride_threshold=STRIDE_TOLERANCE, node=wasm['node'], wasm_kernel=wasm['kernel'],
                    wall_s=time.monotonic() - started, wasm_wall_ms=wasm['wall_ms'],
                    max_errors=max_errors, summary=summary, requests=requests, rows=rows)
    with target.open('x') as f:
        json.dump(document, f, indent=2, allow_nan=False)
        f.write('\n')
    print(json.dumps(dict(numerical_pass=numerical_pass, max_errors=max_errors, summary=summary), indent=2), flush=True)
    if not numerical_pass:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
