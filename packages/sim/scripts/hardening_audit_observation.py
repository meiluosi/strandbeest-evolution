"""H2-01: preserve prior trajectories while checking all-step audit coverage.

Run from the repository root with --kind native or k2 --output DIRECTORY.
The native run emits a separate companion fixture; old golden files are read-only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

from strandbeest_common import Design
from strandbeest_sim import run, scenario_from_design
from strandbeest_sim.audit import audit_report
from strandbeest_sim.audit_observation import observation_issues
from strandbeest_sim.config import sim_config
from strandbeest_sim.events import diagnose, detect_events

ROOT = Path(__file__).resolve().parents[3]
PLAN = ROOT/'experiments/hardening-audit-observation-plan-2026-11-04.json'


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    paths = [*sorted((ROOT/'packages/sim/src').rglob('*.py')),
             *sorted((ROOT/'packages/common/src').rglob('*.py')),
             *sorted((ROOT/'packages/sim-web/src').glob('*.ts')),
             *sorted((ROOT/'schemas').glob('*.json')), Path(__file__)]
    return {str(p.relative_to(ROOT)): digest(p) for p in paths}


def retain(res, output, name, backend):
    arrays = {'t': res.t, 'psi': res.psi, 'x': res.x, 'z': res.z, 'torque': res.torque, **res.series}
    path = output/(name+'.npz')
    np.savez_compressed(path, **arrays)
    issues = observation_issues(res.scenario, res.metrics, arrays, res.audit_observation, backend)
    assert not issues, issues
    report = audit_report(res.scenario, res.metrics, arrays, res.stalled,
                          backend_name=backend, observation=res.audit_observation)
    return dict(name=name, scenario=res.scenario.model_dump(mode='json'),
                arrays_path=str(path), arrays_sha256=digest(path), metrics=res.metrics,
                audit_observation=res.audit_observation, stalled=res.stalled, audit=report)


def native(output):
    path = ROOT/'contracts/sim-run/cases-contact-v3.json'
    original = read(path)
    spec = importlib.util.spec_from_file_location('original_run_generator', ROOT/'contracts/generate_sim_run.py')
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    last = []
    original_run = gen.run

    def observe_run(*args, **kwargs):
        res = original_run(*args, **kwargs)
        last[:] = [res]
        return res

    gen.run = observe_run
    rows, companion = [], []
    for c in original['cases']:
        started = time.monotonic()
        expected = c['expected']
        got = gen.one(copy.deepcopy(c['overrides']))
        # An observation-only repair must not change trajectories, events,
        # energy or any non-peak metric. Keep old peak/diagnosis values intact.
        for key in expected:
            if key not in ('metrics', 'diagnosis'):
                assert got[key] == expected[key], (c['name'], key)
        for key, value in expected['metrics'].items():
            if key not in ('max_loop_violation', 'max_penetration'):
                assert got['metrics'][key] == value, (c['name'], key)
        row = retain(last[0], output, c['name'], 'mujoco')
        row['raw_replay_and_nonpeak_metrics_unchanged'] = True
        row['before_peak_metrics'] = {k: expected['metrics'][k] for k in ('max_loop_violation', 'max_penetration')}
        row['before_diagnosis'] = expected['diagnosis']
        row['diagnosis'] = got['diagnosis']
        rows.append(row)
        companion.append({'name': c['name'], 'metrics': got['metrics'], 'diagnosis': got['diagnosis'],
                          'audit_observation': row['audit_observation']})
        print(json.dumps({'case': c['name'], 'wall_s': time.monotonic()-started,
                          'steps': row['audit_observation']['observed_steps']}), flush=True)
    signed_path = ROOT/'contracts/sim-run/signed-energy-v3.json'
    fixture = read(signed_path)
    res = run(scenario_from_design(Design(fixture['design']), copy.deepcopy(fixture['overrides'])))
    raw = {'t': res.t, 'psi': res.psi, 'x': res.x, 'z': res.z, 'torque': res.torque, **res.series}
    for key, value in fixture['raw_series'].items():
        np.testing.assert_array_equal(raw[key], value)
    for key, value in fixture['replay']['metrics'].items():
        if key not in ('max_loop_violation', 'max_penetration'):
            assert res.metrics[key] == value, key
    row = retain(res, output, 'signed-energy', 'mujoco')
    row['raw_replay_and_nonpeak_metrics_unchanged'] = True
    row['before_peak_metrics'] = {k: fixture['replay']['metrics'][k] for k in ('max_loop_violation', 'max_penetration')}
    row['before_diagnosis'] = fixture['replay']['diagnosis']
    row['diagnosis'] = diagnose(res, detect_events(res))
    rows.append(row)
    companion.append({'name': 'signed-energy', 'metrics': res.metrics, 'diagnosis': row['diagnosis'],
                      'audit_observation': row['audit_observation']})
    return rows, {'version': 1, 'source': str(path.relative_to(ROOT)), 'source_sha256': digest(path),
                  'signed_source': str(signed_path.relative_to(ROOT)), 'signed_source_sha256': digest(signed_path),
                  'physics_changed': False, 'cases': companion}


def k2(output):
    plan = read(PLAN)
    baseline_path = Path('/tmp/beest-k2-contact-2026-11-04/coupled/cohort/result.json')
    baseline = read(baseline_path)
    rows = []
    for case in plan['diagnostic_cases']:
        reference = baseline['rows'][case]
        full = None
        observation = None
        for rec in plan['record_every']:
            started = time.monotonic()
            sc = sim_config(reference['scenario'])
            sc.run.max_time = plan['diagnostic_max_time_s']
            sc.run.record_every = rec
            res = run(sc, backend='k2')
            row = retain(res, output, f'case{case}-rec{rec}', 'k2')
            row['case'], row['record_every'] = case, rec
            with np.load(row['arrays_path']) as a:
                if rec == 1:
                    full = {k: a[k] for k in a.files}
                    observation = row['audit_observation']
                else:
                    assert a.files == list(full)
                    assert all(np.array_equal(full[k][::rec], a[k]) for k in a.files)
                    assert observation == row['audit_observation']
                if rec == 20:
                    assert digest(reference['arrays_path']) == reference['arrays_sha256']
                    with np.load(reference['arrays_path']) as old:
                        assert a.files == old.files and all(np.array_equal(a[k], old[k]) for k in a.files)
                    row['prior_sparse_trace_bitwise_unchanged'] = True
                    row['prior_audit'] = reference['audit']
            row['all_step_observation_matches_dense_run'] = True
            rows.append(row)
            print(json.dumps({'case': case, 'record_every': rec, 'wall_s': time.monotonic()-started,
                              'audit': row['audit']['status'], 'observation': row['audit_observation']}), flush=True)
    return rows, {'prior_path': str(baseline_path), 'prior_sha256': digest(baseline_path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kind', choices=('native', 'k2'), required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = sources()
    result = {'complete': False, 'kind': args.kind, 'plan_path': str(PLAN.relative_to(ROOT)),
              'plan_sha256': digest(PLAN), 'source_sha256': before, 'h2_01_accepted': False,
              'physical_evidence_upgraded': False, 'rows': []}
    target = output/'result.json'
    target.write_text(json.dumps(result, indent=2)+'\n')
    rows, companion = (native if args.kind == 'native' else k2)(output)
    result.update(rows=rows, companion=companion)
    result['source_drift'] = [p for p, h in before.items() if digest(ROOT/p) != h]
    assert not result['source_drift'], result['source_drift']
    result['complete'] = True
    target.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    if args.kind == 'native':
        (output/'companion.json').write_text(json.dumps(companion, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'complete': True, 'runs': len(rows)}), flush=True)


if __name__ == '__main__':
    main()
