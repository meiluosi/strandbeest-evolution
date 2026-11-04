"""Predeclared contact/numerical/time-window sensitivity, not an acceptance sweep.

The original full-cohort gate is unchanged. All named trials (including failures)
are saved. Complete per-step decomposition is retained; detailed contacts are
recorded at the original telemetry cadence to bound disk use. The observer never
calls mj_forward and checks the integration state before/after every observation.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import time
import traceback
from array import array
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import mujoco
import numpy as np
from strandbeest_common import Design
from strandbeest_sim import load_scenario, run, scenario_from_design
from strandbeest_sim.skeptic import audit_legacy as audit

import hardening_g1_contact_diagnostic as diagnostic

ROOT = Path(__file__).resolve().parents[3]


class SampledContactTrace:
    """Every-step numeric arrays remain full; only the verbose contact JSON is decimated."""
    def __init__(self, stream, every):
        self.stream, self.every, self.count = stream, every, 0

    def write(self, value):
        if self.count % self.every == 0:
            self.stream.write(value)
        self.count += 1

    def close(self):
        self.stream.close()


class SensitivityBackend(diagnostic.ContactDiagnosticBackend):
    def __init__(self, trace_path, every, saturation_ratio):
        super().__init__(trace_path)
        self.trace = SampledContactTrace(self.trace, every)
        self.saturation_ratio = saturation_ratio
        self.solver_rows = array('d')

    def capture(self, view, index):
        super().capture(view, index)
        m, d = view.model, view.data
        normal_total = saturated_load = weighted_ratio = 0.0
        max_ratio = 0.0
        for i in range(d.ncon):
            contact = d.contact[i]
            if int(contact.geom1) not in self.geom_meta and int(contact.geom2) not in self.geom_meta:
                continue
            force = np.zeros(6)
            mujoco.mj_contactForce(m, d, i, force)
            normal = float(force[0])
            if normal <= diagnostic.FORCE_CUTOFF_N:
                continue
            coefficients = np.asarray(contact.friction[:2], dtype=float)
            if np.any(coefficients <= 0):
                raise ValueError('This declared diagnostic requires positive tangential friction')
            normalized = np.abs(force[1:3]) / coefficients
            # MuJoCo's condim=3 pyramidal cross-section is L1, elliptic is L2.
            demand = np.linalg.norm(normalized) if int(m.opt.cone) == int(mujoco.mjtCone.mjCONE_ELLIPTIC) else normalized.sum()
            ratio = float(demand / normal)
            normal_total += normal
            weighted_ratio += normal * ratio
            max_ratio = max(max_ratio, ratio)
            if ratio >= self.saturation_ratio:
                saturated_load += normal
        self.solver_rows.extend([index, int(np.max(d.solver_niter)),
            weighted_ratio / normal_total if normal_total else 0.0,
            saturated_load / normal_total if normal_total else 0.0,
            max_ratio, normal_total])


SOLVER_COLUMNS = ['step', 'max_solver_iterations', 'load_weighted_cone_utilization',
                  'saturated_normal_load_share', 'max_cone_utilization', 'normal_total_N']


def merge(base, overlay):
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def cycles(result):
    """Same sampled endpoint convention, reported separately per complete turn.

    No stationarity claim: a later cycle is not silently substituted for the
    prescribed original audit window. Short final pieces are reported as absent.
    """
    rows = []
    for k in range(int(math.floor(float(result.psi[-1]) / math.tau))):
        indices = np.flatnonzero((result.psi >= k * math.tau) & (result.psi <= (k + 1) * math.tau))
        if len(indices) < 2:
            rows.append({'cycle': k, 'available': False})
            continue
        a, b = int(indices[0]), int(indices[-1])
        revs = float((result.psi[b] - result.psi[a]) / math.tau)
        if revs <= 0:
            rows.append({'cycle': k, 'available': False})
            continue
        s = result.series
        work = float(s['e_in'][b] - s['e_in'][a])
        dissipated = sum(float(s[key][b] - s[key][a]) for key in ['e_contact', 'e_loops', 'e_friction'])
        mechanical = float(s['kinetic'][b] + s['potential'][b] - s['kinetic'][a] - s['potential'][a])
        rows.append(dict(cycle=k, available=True, actual_revolutions=revs,
            stride_m_per_rev=float((result.x[b] - result.x[a]) / revs),
            energy_in_J_per_rev=work / revs, mechanical_change_J_per_rev=mechanical / revs,
            residual_share=(work - dissipated - mechanical) / work if abs(work) > 1e-12 else None))
    return rows


def one(job):
    trial, source, directory, saturation_ratio = job
    name = f"case{source['case']}-{trial['name']}"
    trace = directory / f'{name}-contacts.jsonl.gz'
    scenario = scenario_from_design(Design(source['design']), merge(source['overrides'], trial['overrides']))
    saved = scenario.model_dump(mode='json', exclude_unset=True)
    assert load_scenario(saved) == scenario
    if trial['name'] == 'baseline':
        assert saved == source['scenario']
    from strandbeest_sim.config import sim_config
    cfg = sim_config(scenario)
    backend = SensitivityBackend(trace, cfg.run.record_every, saturation_ratio)
    start = time.monotonic()
    row = dict(case=source['case'], trial=trial, scenario=saved, completed=False)
    try:
        result = run(scenario, backend=backend)
        decomposition, steps = diagnostic.summarize_window(result, backend)
        solver_rows = np.frombuffer(backend.solver_rows, dtype=np.float64).reshape(-1, len(SOLVER_COLUMNS))
        assert len(solver_rows) == len(steps) == backend.observation_state_checks
        window = diagnostic.audit_window(result.psi)
        summary = None
        if window is not None:
            a, b = (i * cfg.run.record_every for i in window)
            selected = solver_rows[a:b]
            summary = dict(max_iterations=int(selected[:, 1].max()), mean_iterations=float(selected[:, 1].mean()),
                mean_cone_utilization=float(selected[:, 2].mean()), mean_saturated_load_share=float(selected[:, 3].mean()),
                max_cone_utilization=float(selected[:, 4].max()))
        arrays = directory / f'{name}-steps.npz'
        np.savez_compressed(arrays, steps=steps, columns=np.asarray(diagnostic.COLUMNS),
            solver_steps=solver_rows, solver_columns=np.asarray(SOLVER_COLUMNS),
            t=result.t, psi=result.psi, x=result.x, torque=result.torque,
            **{'series_' + k: v for k, v in result.series.items()})
        row.update(completed=True, metrics=diagnostic.safe_json(result.metrics), stalled=result.stalled,
            findings=[asdict(f) for f in audit(result.scenario, result.metrics, result.series, result.stalled)],
            diagnostic=decomposition, solver_diagnostic=summary, cycles=cycles(result),
            sphere_owners=backend.ownership, observation_state_checks=backend.observation_state_checks,
            actual_solver={'timestep': backend.model.opt.timestep, 'iterations': backend.model.opt.iterations,
                'tolerance': backend.model.opt.tolerance, 'cone': int(backend.model.opt.cone),
                'impratio': backend.model.opt.impratio, 'noslip_iterations': backend.model.opt.noslip_iterations,
                'noslip_tolerance': backend.model.opt.noslip_tolerance},
            arrays_file=arrays.name, arrays_sha256=diagnostic.digest(arrays))
        if trial['name'] == 'baseline':
            row['metrics_exactly_equal_previous'] = result.metrics == source['metrics']
            row['metric_differences'] = {k: {'before': source['metrics'].get(k), 'after': v}
                for k, v in result.metrics.items() if source['metrics'].get(k) != v}
    except Exception as exc:
        partial = directory / f'{name}-partial.npz'
        np.savez_compressed(partial, steps=np.frombuffer(backend.rows, dtype=np.float64),
                            solver_steps=np.frombuffer(backend.solver_rows, dtype=np.float64))
        row.update(error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc(),
                   partial_arrays_file=partial.name, partial_arrays_sha256=diagnostic.digest(partial))
    finally:
        backend.close()
    row.update(wall_s=time.monotonic() - start, contacts_file=trace.name, contacts_sha256=diagnostic.digest(trace))
    return diagnostic.safe_json(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    assert plan['case_ids'] == [53, 61] and len(plan['trials']) == 8
    source_path = ROOT / plan['input_path']
    assert diagnostic.digest(source_path) == plan['input_sha256']
    sources = json.loads(source_path.read_text())
    assert sources['complete'] and sources['n'] == 64 and sources['seed'] == 1
    directory = diagnostic.output_dir(args.output)
    (directory / 'plan.json').write_bytes(args.plan.read_bytes())
    initial = diagnostic.source_hashes()
    initial[str(Path(__file__).relative_to(ROOT))] = diagnostic.digest(__file__)
    jobs = [(trial, sources['rows'][case], directory, plan['saturation_ratio'])
            for case in plan['case_ids'] for trial in plan['trials']]
    document = dict(complete=False, full_cohort_pass=False, changes_live_audit=False,
        plan_path=str(args.plan), plan_sha256=diagnostic.digest(args.plan), plan=plan,
        source_sha256=initial, raw_directory=str(directory), rows=[])
    diagnostic.write_json(directory / 'manifest.json', document)
    start = time.monotonic()
    with ProcessPoolExecutor(max_workers=plan['workers']) as executor:
        futures = [executor.submit(one, job) for job in jobs]
        for future in as_completed(futures):
            row = future.result()
            document['rows'].append(row)
            document['rows'].sort(key=lambda r: (r['case'], r['trial']['name']))
            diagnostic.write_json(directory / 'manifest.json', document)
            print(json.dumps(dict(done=len(document['rows']), case=row['case'], trial=row['trial']['name'],
                completed=row['completed'], error=row.get('error'), stride=row.get('metrics', {}).get('stride_per_rev'))), flush=True)
    final = diagnostic.source_hashes()
    final[str(Path(__file__).relative_to(ROOT))] = diagnostic.digest(__file__)
    document.update(complete=True, all_trials_completed=all(r['completed'] for r in document['rows']),
        source_drift=diagnostic.changed_sources(initial, final), wall_s=time.monotonic() - start)
    diagnostic.write_json(directory / 'manifest.json', document)


if __name__ == '__main__':
    main()
