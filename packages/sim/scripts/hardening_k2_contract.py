"""Locked diagnostic cases; never a replacement for the full H2 cohort."""
import argparse
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def trial(task):
    from strandbeest_sim.config import sim_config
    from strandbeest_sim.backends.k2_backend import K2Backend
    from strandbeest_sim.runner import run
    from strandbeest_sim.audit import audit_report
    case, scenario, variant, output_dir = task
    sc = sim_config(scenario)
    sc.run.max_time = 30.0
    if variant == 'fixed-dt500us':
        sc.solver.timestep = .0005
    be = K2Backend()
    started = time.perf_counter()
    result = run(sc, backend=be)
    path = Path(output_dir) / f'{variant}-case{case}.npz'
    assert not path.exists()
    arrays = {'t': result.t, 'psi': result.psi, 'x': result.x, 'z': result.z, 'torque': result.torque, **result.series}
    np.savez_compressed(path, **arrays)
    report = audit_report(sc, result.metrics, arrays, result.stalled, backend_name='k2')
    return {'case': case, 'variant': variant, 'scenario': sc.model_dump(mode='json'),
            'actual_timestep': be.timestep, 'wall_s': time.perf_counter()-started,
            'metrics': result.metrics, 'stalled': result.stalled, 'audit': report,
            'arrays_path': str(path), 'arrays_sha256': digest(path)}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--variant',required=True, choices=['before','fixed-dt500us','fixed-requested'])
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    assert not args.output.exists()
    plan_path=Path('experiments/hardening-k2-contract-plan-2026-11-04.json')
    plan=json.loads(plan_path.read_text())
    if args.variant == 'before':
        prior=json.loads(Path('experiments/hardening-audit-v2-validation-2026-11-04.json').read_text())
        backend_path='packages/sim/src/strandbeest_sim/backends/k2_backend.py'
        if digest(backend_path) != prior['source_sha256'][backend_path]:
            raise ValueError('The before variant requires the archived original K2 implementation in an isolated checkout')
    assert digest(plan['source_path'])==plan['source_sha256']
    old=json.loads(Path(plan['source_path']).read_text())
    source_paths=list(Path('packages/sim/src').rglob('*.py'))+list(Path('packages/common/src').rglob('*.py'))+[Path(__file__)]
    sources={str(p):digest(p) for p in source_paths}
    result={'complete':False,'variant':args.variant,'plan_path':str(plan_path),'plan_sha256':digest(plan_path),
            'source_sha256':sources,'full_h2_cohort':False,'rows':[]}
    tasks=[(case,old['rows'][case]['scenario'],args.variant,str(args.output.parent)) for case in plan['cases']]
    with ProcessPoolExecutor(max_workers=2) as pool:
        for row in pool.map(trial,tasks):
            result['rows'].append(row)
            print(json.dumps({'case':row['case'],'variant':row['variant'],'stride':row['metrics'].get('stride_per_rev'),
                              'stalled':row['stalled'],'actual_timestep':row['actual_timestep']}),flush=True)
    result['source_drift']=[p for p,h in sources.items() if digest(p)!=h]
    assert not result['source_drift']
    result['complete']=True
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
