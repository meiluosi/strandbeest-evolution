"""Preregistered K2 work diagnostics and the unchanged original 64-case cohort."""
import argparse
import hashlib
import json
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def trial(task):
    from strandbeest_sim.audit import audit_report
    from strandbeest_sim.backends.k2_backend import K2Backend
    from strandbeest_sim.config import sim_config
    from strandbeest_sim.runner import run

    case, scenario, settings, output = task
    started = time.perf_counter()
    sc = sim_config(scenario)
    sc.solver.timestep = settings['timestep_s']
    sc.run.max_time = settings['max_time_s']
    try:
        be = K2Backend()
        result = run(sc, backend=be)
        path = Path(output) / f'case{case}.npz'
        assert not path.exists()
        arrays = {'t': result.t, 'psi': result.psi, 'x': result.x, 'z': result.z,
                  'torque': result.torque, **result.series}
        np.savez_compressed(path, **arrays)
        report = audit_report(sc, result.metrics, arrays, result.stalled, backend_name='k2')
        return {'case': case, 'completed': True, 'scenario': sc.model_dump(mode='json'),
                'actual_timestep': be.timestep, 'wall_s': time.perf_counter()-started,
                'metrics': result.metrics, 'stalled': result.stalled, 'audit': report,
                'simulated_s': float(result.t[-1]),
                'arrays_path': str(path), 'arrays_sha256': digest(path)}
    except Exception:
        # Preserve failed cases instead of replacing or silently dropping them.
        return {'case': case, 'completed': False, 'scenario': sc.model_dump(mode='json'),
                'wall_s': time.perf_counter()-started, 'error': traceback.format_exc()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True, choices=['diagnostic', 'coarse', 'cohort'])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--plan', type=Path, default=Path('experiments/hardening-k2-energy-plan-2026-11-04.json'))
    args = parser.parse_args()
    assert not args.output.exists()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plan_path = args.plan
    plan = json.loads(plan_path.read_text())
    assert digest(plan['source_path']) == plan['source_sha256']
    original = json.loads(Path(plan['source_path']).read_text())
    assert original['seed'] == plan['seed'] == 1 and len(original['rows']) == 64
    cases = plan['original_cases'] if args.stage == 'cohort' else plan['diagnostic_cases']
    source_paths = (list(Path('packages/sim/src').rglob('*.py'))
                    + list(Path('packages/common/src').rglob('*.py'))
                    + list(Path('schemas').glob('*.schema.json')) + [Path(__file__)])
    sources = {str(p): digest(p) for p in sorted(source_paths)}
    result = {'complete': False, 'stage': args.stage, 'plan_path': str(plan_path),
              'plan_sha256': digest(plan_path), 'source_sha256': sources,
              'full_64_k2_cohort': args.stage == 'cohort', 'h2_01_accepted': False,
              'independent_validation_accepted': False, 'rows': []}

    def save():
        result['rows'].sort(key=lambda row: row['case'])
        temporary = args.output.with_suffix('.partial')
        temporary.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
        temporary.replace(args.output)

    save()
    tasks = [(case, original['rows'][case]['scenario'], plan['stages'][args.stage],
              str(args.output.parent)) for case in cases]
    with ProcessPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(trial, task) for task in tasks]):
            row = future.result()
            result['rows'].append(row)
            save()
            metrics = row.get('metrics', {})
            print(json.dumps({'case': row['case'], 'completed': row['completed'],
                              'energy_residual': metrics.get('energy_residual_share'),
                              'audit': row.get('audit', {}).get('status'),
                              'stalled': row.get('stalled')}), flush=True)
    result['source_drift'] = [p for p, h in sources.items() if digest(p) != h]
    assert not result['source_drift']
    result['complete'] = len(result['rows']) == len(cases)
    result['execution_errors'] = sum(not row['completed'] for row in result['rows'])
    save()


if __name__ == '__main__':
    main()
