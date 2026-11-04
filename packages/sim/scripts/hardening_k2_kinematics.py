"""Check all original G1 inputs against independent finite-difference contact motion.

The numerical limits are the same as the analytic contact unit test. This is
kinematics verification, not independent validation of K2's dynamic model.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from strandbeest_sim.backends.k2_backend import K2Backend
from strandbeest_sim.builder import resolve_spec
from strandbeest_sim.config import sim_config
from strandbeest_sim.linkage import solve_pose
from strandbeest_sim.registry import terrains


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rotate(a, v):
    c, s = math.cos(a), math.sin(a)
    return np.array([c*v[0]-s*v[1], s*v[0]+c*v[1]])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    assert not args.output.exists()
    plan_path=Path('experiments/hardening-k2-contract-plan-2026-11-04.json')
    plan=json.loads(plan_path.read_text())
    assert digest(plan['source_path'])==plan['source_sha256']
    corpus=json.loads(Path(plan['source_path']).read_text())
    assert corpus['n']==64 and corpus['seed']==1 and [r['case'] for r in corpus['rows']]==list(range(64))
    paths=list(Path('packages/sim/src').rglob('*.py'))+list(Path('packages/common/src').rglob('*.py'))+[Path(__file__)]
    sources={str(p):digest(p) for p in paths}
    h, rtol, atol = 1e-6, 3e-5, 2e-7
    result={'complete':False, 'scope':'kinematics_only_not_dynamics_validation',
            'plan_path':str(plan_path),'plan_sha256':digest(plan_path),'source_sha256':sources,
            'finite_difference_step_rad_or_m':h,'jacobian_rtol':rtol,'jacobian_atol':atol,
            'phases_per_case':96,'physical_evidence_upgraded':False,'rows':[]}
    for saved in corpus['rows']:
        row={'case':saved['case'],'checks':[]}
        try:
            sc=sim_config(saved['scenario'])
            be=K2Backend()
            info=be.build(sc,terrains.get(sc.terrain.kind)(sc))
            row.update(requested_timestep=sc.solver.timestep,actual_timestep=be.timestep,
                       timestep_matches=be.timestep==sc.solver.timestep,foot_owner=be._foot_owner_start,
                       initial_height_m=info.hip_height,terrain=sc.terrain.kind)
            spec=resolve_spec(sc)
            columns=[0,1,3] if sc.walker.pitch=='locked' else [0,1,2,3]
            base_phases=np.linspace(0,math.tau,32,endpoint=False)
            # Retain every original phase and add interior-of-cell probes.
            for phase in np.concatenate((base_phases,base_phases+.37*math.tau/1440,base_phases+.37*be._table_step)):
                q=np.array([.2,.3,0.,phase])
                be._q=q.copy()
                _,jn,jt=be._foot_contact_kinematics(0)

                def center_angle(state):
                    pose=solve_pose(spec,sc.walker.direction*state[3])
                    foot=np.array(pose[spec.foot])*sc.walker.unit
                    bar=np.array(pose[spec.foot])-pose[be._foot_owner_start]
                    return state[:2]+rotate(state[2],foot),state[2]+math.atan2(bar[1],bar[0])

                _,beta=center_angle(q)

                def material_point(state):
                    center,angle=center_angle(state)
                    return center+rotate(angle-beta,(0.,-sc.walker.foot_radius))

                numeric=np.column_stack([(material_point(q+h*np.eye(4)[k])-material_point(q-h*np.eye(4)[k]))/(2*h)
                                         for k in columns])
                observed=np.stack([jt,jn])[:,columns]
                error=np.abs(observed-numeric)
                bound=atol+rtol*np.abs(numeric)
                row['checks'].append({'phase_rad':float(phase),'passed':bool(np.all(error<=bound)),
                                      'max_abs_difference':float(error.max()),'max_tolerance_ratio':float((error/bound).max())})
            row['passed']=row['timestep_matches'] and all(r['passed'] for r in row['checks'])
        except (ValueError,KeyError,TypeError) as exc:
            row.update(passed=False,error=f'{type(exc).__name__}: {exc}')
        result['rows'].append(row)
    result['source_drift']=[p for p,hsh in sources.items() if digest(p)!=hsh]
    assert not result['source_drift']
    result['complete']=True
    result['cases_passed']=sum(r['passed'] for r in result['rows'])
    result['phases_failed']=sum(not s['passed'] for r in result['rows'] for s in r['checks'])
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['complete','cases_passed','phases_failed','source_drift']}))


if __name__=='__main__':main()
