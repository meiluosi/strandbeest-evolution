"""Run a predeclared precision/compliance diagnostic without changing G1 gates.

Inputs are the exact saved scenarios, not regenerated random samples. The
read-only observer records solver iteration counts; standard runner telemetry
is retained for all outcomes. A diagnostic time bound is explicit in the plan.
Neither a short run nor a stalled run can be reported as an accepted repair.
"""
from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import platform
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import numpy as np
from strandbeest_sim import load_scenario, run
from strandbeest_sim.backends.mujoco_backend import MujocoBackend
from strandbeest_sim.skeptic import audit_legacy as audit

import hardening_g1_contact_diagnostic as evidence

ROOT = Path(__file__).resolve().parents[3]


class IterationObserver(MujocoBackend):
    def __init__(self):
        super().__init__()
        self.iterations = Counter()

    def step(self, n=1):
        for _ in range(n):
            super().step()
            # Read only the already-completed solve; never call mj_forward.
            self.iterations[int(np.max(self.data.solver_niter))] += 1


def one(job):
    trial, source, directory, time_bound = job
    saved = copy.deepcopy(source['scenario'])
    for section, fields in trial['overrides'].items():
        saved.setdefault(section, {}).update(fields)
    # This is a diagnostic cutoff, not a change to the original 600 s audit.
    saved.setdefault('run', {})['max_time'] = time_bound
    scenario = load_scenario(saved)
    assert load_scenario(json.loads(scenario.model_dump_json(exclude_unset=True))) == scenario
    row = dict(case=source['case'], trial=trial, scenario=saved, completed=False)
    backend = IterationObserver()
    started = time.monotonic()
    try:
        result = run(scenario, backend=backend)
        arrays = directory / f"case{source['case']}-{trial['name']}.npz"
        np.savez_compressed(arrays, t=result.t, psi=result.psi, x=result.x,
                            z=result.z, torque=result.torque,
                            **{'series_' + k: v for k, v in result.series.items()})
        full_turns = float(result.psi[-1] / (2 * np.pi))
        row.update(completed=True, stalled=bool(result.stalled),
            complete_gait_window=bool(not result.stalled and full_turns >= 2.0),
            recorded_revolutions=full_turns, simulated_s=float(result.t[-1]),
            metrics=evidence.safe_json(result.metrics),
            findings=[asdict(f) for f in audit(result.scenario, result.metrics, result.series, result.stalled)],
            arrays_path=str(arrays), arrays_sha256=evidence.digest(arrays))
        if trial['name'] == 'baseline':
            row['metrics_exactly_equal_previous'] = result.metrics == source['metrics']
            row['metric_differences'] = {k: {'before': source['metrics'].get(k), 'after': v}
                for k, v in result.metrics.items() if source['metrics'].get(k) != v}
        row['actual_solver'] = {key: getattr(backend.model.opt, key)
                               for key in ['timestep', 'iterations', 'tolerance', 'cone', 'impratio', 'noslip_iterations']}
        row['iteration_histogram_all_steps_including_settle'] = dict(sorted(backend.iterations.items()))
    except Exception as exc:
        row.update(error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
    row['wall_s'] = time.monotonic() - started
    return evidence.safe_json(row)


def hashes():
    found = evidence.source_hashes()
    found[str(Path(__file__).relative_to(ROOT))] = evidence.digest(__file__)
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    source_path = ROOT / plan['input_path']
    assert evidence.digest(source_path) == plan['input_sha256']
    source = json.loads(source_path.read_text())
    assert source['complete'] and source['n'] == 64 and source['seed'] == 1
    sources = {row['case']: row for row in source['rows']}
    directory = evidence.output_dir(args.output)
    (directory / 'plan.json').write_bytes(args.plan.read_bytes())
    initial = hashes()
    document = dict(complete=False, full_cohort_pass=False, changes_live_audit=False,
        plan_path=str(args.plan), plan_sha256=evidence.digest(args.plan), plan=plan,
        python=platform.python_version(), mujoco=importlib.metadata.version('mujoco'),
        source_sha256=initial, raw_directory=str(directory), rows=[])
    evidence.write_json(directory / 'manifest.json', document)
    jobs = [(trial, sources[case], directory, plan['diagnostic_max_time_s'])
            for case in plan['case_ids'] for trial in plan['trials']]
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=plan['workers']) as pool:
        futures = [pool.submit(one, job) for job in jobs]
        for future in as_completed(futures):
            row = future.result()
            document['rows'].append(row)
            document['rows'].sort(key=lambda r: (r['case'], r['trial']['name']))
            evidence.write_json(directory / 'manifest.json', document)
            print(json.dumps(dict(done=len(document['rows']), case=row['case'],
                trial=row['trial']['name'], completed=row['completed'], error=row.get('error'),
                stalled=row.get('stalled'), stride=row.get('metrics', {}).get('stride_per_rev'))), flush=True)
    final = hashes()
    document.update(complete=True, all_trials_completed=all(r['completed'] for r in document['rows']),
        source_drift=evidence.changed_sources(initial, final), wall_s=time.monotonic() - started)
    evidence.write_json(directory / 'manifest.json', document)


if __name__ == '__main__':
    main()
