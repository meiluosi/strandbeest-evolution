"""All-64 inertia/bias projection check; no physical validation is implied."""
import argparse
import hashlib
import json
import math
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(task):
    from strandbeest_sim.backends.k2_inertia import WalkerInertia
    from strandbeest_sim.builder import build, resolve_spec
    from strandbeest_sim.config import sim_config
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
    from k2_inertia_reference import NativeReducedOracle

    saved, settings, output = task
    row = {'case': saved['case'], 'checks': []}
    try:
        cfg = sim_config(saved['scenario'])
        cfg.walker.pitch = 'free'
        spec = resolve_spec(cfg)
        inertia = WalkerInertia(spec, cfg, build(cfg, spec).xml)
        oracle = NativeReducedOracle(cfg)
        phases = np.arange(32)*math.tau/32
        phases = np.r_[phases, phases+.37*math.tau/1440]
        arrays = {'phase_rad': phases}
        observed = {key: [] for key in settings['bounds']}
        references = {key: [] for key in settings['bounds']}
        velocity = np.array(settings['velocity'])
        gravity = settings['gravity']
        for phase in phases:
            q = np.array([*settings['position'], phase])
            sample = inertia.sample(q, settings['armature'])
            expected = oracle.evaluate(q, velocity, gravity, settings['armature'])
            actual = {'mass': sample.matrix, 'bias_minus_gravity': sample.bias(velocity)-sample.gravity(gravity),
                      'potential': sample.potential(q, gravity),
                      'body_positions': sample.body_positions,
                      'com': np.array([q[0]+sample.moment[0]/sample.mass, 0., q[1]+sample.moment[1]/sample.mass])}
            check = {'phase_rad': float(phase), 'min_eigenvalue': float(np.linalg.eigvalsh(sample.matrix).min()), 'fields': {}}
            for key, bound in settings['bounds'].items():
                observed[key].append(actual[key])
                references[key].append(expected[key])
                error = np.abs(np.asarray(actual[key])-expected[key])
                tolerance = bound['atol']+bound['rtol']*np.abs(expected[key])
                check['fields'][key] = {'passed': bool(np.all(error <= tolerance)),
                                        'max_abs_error': float(np.max(error)),
                                        'max_bound_ratio': float(np.max(error/tolerance))}
            check['passed'] = check['min_eigenvalue'] > 0 and all(v['passed'] for v in check['fields'].values())
            row['checks'].append(check)
        for key in observed:
            arrays['actual_'+key] = np.asarray(observed[key])
            arrays['reference_'+key] = np.asarray(references[key])
        path = Path(output) / f'inertia-case{saved["case"]}.npz'
        assert not path.exists()
        np.savez_compressed(path, **arrays)
        row.update(passed=all(c['passed'] for c in row['checks']), arrays_path=str(path), arrays_sha256=digest(path))
    except Exception:
        row.update(passed=False, error=traceback.format_exc())
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plan_path = Path('experiments/hardening-k2-inertia-plan-2026-11-04.json')
    plan = json.loads(plan_path.read_text())
    assert digest(plan['source_path']) == plan['source_sha256']
    corpus = json.loads(Path(plan['source_path']).read_text())
    assert corpus['seed'] == 1 and len(corpus['rows']) == 64
    paths = list(Path('packages/sim/src').rglob('*.py'))+list(Path('packages/common/src').rglob('*.py'))
    paths += [Path(__file__), Path('packages/sim/tests/k2_inertia_reference.py')]
    sources = {str(p): digest(p) for p in paths}
    result = {'complete': False, 'scope': 'independent_inertia_assembly_not_dynamic_or_physical_acceptance',
              'plan_path': str(plan_path), 'plan_sha256': digest(plan_path),
              'source_sha256': sources, 'rows': [], 'physical_evidence_upgraded': False}

    def save():
        result['rows'].sort(key=lambda row: row['case'])
        temporary = args.output.with_suffix('.partial')
        temporary.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
        temporary.replace(args.output)

    save()
    with ProcessPoolExecutor(max_workers=2) as pool:
        tasks = [(row, plan['static_probe'], str(args.output.parent)) for row in corpus['rows']]
        for future in as_completed([pool.submit(probe, task) for task in tasks]):
            row = future.result()
            result['rows'].append(row)
            save()
            print(json.dumps({'case': row['case'], 'passed': row['passed'],
                              'failed_phases': sum(not c['passed'] for c in row['checks']),
                              'execution_error': 'error' in row}), flush=True)
    result['source_drift'] = [p for p, h in sources.items() if digest(p) != h]
    assert not result['source_drift']
    result['complete'] = len(result['rows']) == 64
    result['cases_passed'] = sum(r['passed'] for r in result['rows'])
    result['phases_failed'] = sum(not c['passed'] for r in result['rows'] for c in r['checks'])
    save()


if __name__ == '__main__':
    main()
