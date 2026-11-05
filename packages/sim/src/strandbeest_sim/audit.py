"""Versioned simulation audit with explicit reference applicability (ADR-0012).

The geometric model is an exact-constraint limit. We do not invent a nonzero
physical tolerance for slip/compliance to make it apply to a compliant run.
Those runs need an independent dynamical/measurement comparison; absent such
evidence, the result remains unverified. A pass here never upgrades E0 to E1–E3.
"""
from __future__ import annotations

import copy
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict
from functools import lru_cache
from typing import Any

import numpy as np

from strandbeest_common import solve_pose, stride_reference
from .builder import build, resolve_spec
from .config import SimConfig, sim_config
from .audit_observation import observation_issues
from .skeptic import (ENERGY_RESIDUAL, LOOP_OPEN_M, PENETRATION_M,
                      STRIDE_TOLERANCE, _finite_number, audit_legacy)

RESOLUTIONS = (720, 1440)
REFERENCE_NUMERICAL_RELATIVE_TOLERANCE = 1e-6
SUPPORT_FORCE_N = 1e-6  # Same contact definition as the historical support check.


@lru_cache(maxsize=128)
def _reference(serialized: str) -> dict[str, Any]:
    sc = sim_config(json.loads(serialized))
    spec = resolve_spec(sc)
    tree = ET.fromstring(build(sc, spec).xml)
    owners = []
    for body in tree.iter('body'):
        for geom in body.findall('geom'):
            if not geom.get('name', '').startswith('foot_'):
                continue
            match = re.fullmatch(r'bar(\d+)_(.+)([01])', body.get('name', ''))
            if match is None or geom.get('type') != 'sphere':
                raise ValueError('The built model has an unsupported foot owner or shape')
            joint = next(j for j in spec.joints if j.id == match[2])
            owners.append({'leg': int(match[1]), 'start': joint.centers[int(match[3])],
                           'end': joint.id, 'radius_m': float(geom.attrib['size'])})
    if len(owners) != sc.walker.legs or sorted(o['leg'] for o in owners) != list(range(sc.walker.legs)):
        raise ValueError('The built model must have exactly one sphere per leg')
    first = owners[0]
    if any(o['start'] != first['start'] or o['end'] != spec.foot or o['radius_m'] != first['radius_m'] for o in owners):
        raise ValueError('The geometric reference requires equal spheres and owners')
    options = dict(owner_start=first['start'], phases_rad=[math.tau*k/sc.walker.legs for k in range(sc.walker.legs)],
                   direction=sc.walker.direction, unit_m=sc.walker.unit, radius_m=first['radius_m'])
    samples = [stride_reference(spec, **options, brackets=n) for n in RESOLUTIONS]
    estimates = [r['estimate']['contact_stride_m_per_rev'] if r['status'] == 'estimated' else None for r in samples]
    finite = all(_finite_number(v) for v in estimates)
    signed = estimates[-1] if finite else None
    difference = abs(estimates[1] - estimates[0]) if finite else None
    relative = difference / abs(signed) if finite and signed else None
    resolved = (relative is not None and math.isfinite(relative)
                and relative <= REFERENCE_NUMERICAL_RELATIVE_TOLERANCE
                and estimates[0] != 0 and math.copysign(1, estimates[0]) == math.copysign(1, signed))
    return {'model': 'lowest-foot-sphere-v1', 'signed_stride_m_per_rev': signed,
            'owners': owners, 'resolutions': list(RESOLUTIONS), 'samples': samples,
            'numerically_resolved': bool(resolved),
            'resolution_relative_difference': relative if relative is not None and math.isfinite(relative) else None,
            'resolution_relative_tolerance': REFERENCE_NUMERICAL_RELATIVE_TOLERANCE}


def reference_for_scenario(sc: SimConfig) -> dict[str, Any]:
    """Read the actual builder's sphere ownership; never choose an adjacent bar."""
    # A named/file-backed spec can change without its path changing. Cache the
    # resolved value, never the filename or mutable Scenario object's identity.
    spec = resolve_spec(sc)
    doc = sc.model_dump(mode='json')
    doc['linkage'] = {'params': {}, 'spec': {
        'params': spec.params, 'crank': {'x': spec.crank_x, 'y': spec.crank_y, 'length': spec.crank_length},
        'joints': [{'id': j.id, 'centers': j.centers, 'radii': j.radii, 'side': j.side} for j in spec.joints],
        'foot': spec.foot}}
    return copy.deepcopy(_reference(json.dumps(doc, sort_keys=True, allow_nan=False)))


def _trace_conditions(sc, metrics, series):
    conditions = []

    def add(code, verified, **evidence):
        conditions.append({'code': code, 'status': 'verified' if verified else 'unverified', 'evidence': evidence})

    def array(name, dimensions):
        try:
            a = np.asarray(series[name])
            valid = (a.ndim == dimensions and len(a) >= 2 and np.issubdtype(a.dtype, np.number)
                     and not np.iscomplexobj(a) and np.isfinite(a).all())
        except (KeyError, TypeError, ValueError):
            a, valid = None, False
        if not valid:
            add('finite_' + name, False, required='finite, nonempty aligned numeric trace')
            return None
        return a

    series = series or {}
    arrays = {name: array(name, 2 if name in ('foot_normal', 'foot_slip') else 1)
              for name in ('t', 'psi', 'x', 'theta_rad', 'foot_normal', 'foot_slip', 'loop_residual', 'penetration')}
    t = arrays['t']
    aligned = t is not None and all(a is not None and len(a) == len(t) for a in arrays.values())
    add('aligned_trace', aligned)
    every_step = False
    if t is not None:
        # Only a floating-point timestamp tolerance; no physical slip/closure band.
        roundoff = 64*np.finfo(float).eps*max(float(np.abs(t).max()), sc.solver.timestep)
        every_step = (sc.run.record_every == 1 and np.all(np.diff(t) > 0)
                      and np.all(np.abs(np.diff(t)-sc.solver.timestep) <= roundoff))
    add('every_integration_step_recorded', bool(every_step), record_every=sc.run.record_every)
    if not aligned:
        return conditions
    normal, slip = arrays['foot_normal'], arrays['foot_slip']
    shapes = normal.shape == slip.shape == (len(t), sc.walker.legs)
    add('one_load_and_slip_column_per_leg', shapes)
    if shapes:
        finite_loads = bool(np.all(normal >= 0) and np.all(slip >= 0))
        add('nonnegative_loads_and_slip', finite_loads)
        active = normal > SUPPORT_FORCE_N
        add('continuous_recorded_support', bool(np.all(active.any(axis=1))))
        add('zero_recorded_contact_slip', bool(finite_loads and np.all(slip[active] == 0)),
            max_loaded_slip_m_s=float(np.max(slip[active])) if active.any() else None)
    for name, metric in [('loop_residual', 'max_loop_violation'), ('penetration', 'max_penetration')]:
        a = arrays[name]
        add('zero_recorded_' + name, bool(np.all(a == 0) and metrics.get(metric) == 0),
            max_observed_m=float(np.max(a)))
    theta = arrays['theta_rad']
    phase_error = np.diff(theta) - sc.walker.direction*np.diff(arrays['psi'])
    phase_roundoff = 64*np.finfo(float).eps*max(float(np.abs(theta).max()), float(np.abs(arrays['psi']).max()))
    phase_matches = bool(np.all(np.abs(phase_error) <= phase_roundoff))
    add('absolute_phase_matches_progress', phase_matches)
    # Do not trust a synthetic zero-slip table that loads elevated feet. Check
    # support selection against independent linkage geometry at absolute phase.
    # Skip this expensive check when a prior condition already excludes the model.
    if all(c['status'] == 'verified' for c in conditions):
        spec = resolve_spec(sc)
        supports_lowest = True
        for angle, loaded in zip(theta, active):
            poses = [solve_pose(spec, float(angle)+math.tau*k/sc.walker.legs) for k in range(sc.walker.legs)]
            if any(p is None for p in poses):
                supports_lowest = False
                break
            heights = np.array([p[spec.foot][1] for p in poses])*sc.walker.unit
            roundoff = 64*np.finfo(float).eps*float(np.abs(heights).max())
            if np.any(heights[loaded]-heights.min() > roundoff):
                supports_lowest = False
                break
        add('loaded_feet_are_lowest', supports_lowest)
    else:
        add('loaded_feet_are_lowest', False, reason='prior_applicability_condition_unverified')
    psi, x = arrays['psi'], arrays['x']
    # The exact same gait window definition, independently recomputed from raw
    # coordinates. No rounding of a tiny displacement and no denominator floor.
    revs = float((psi[-1] - psi[0]) / math.tau)
    complete = revs >= 1.98
    add('complete_gait_window', complete, recorded_revolutions=revs)
    if complete:
        hi = min(math.tau * (1 + max(1, math.floor(revs + .02)-1)), psi[-1])
        idx = np.flatnonzero((psi >= math.tau) & (psi <= hi))
        valid = len(idx) >= 2 and psi[idx[-1]] > psi[idx[0]]
        measured = float((x[idx[-1]]-x[idx[0]]) / (psi[idx[-1]]-psi[idx[0]]) * math.tau) if valid else None
        reported = metrics.get('stride_per_rev')
        matches = (measured is not None and _finite_number(reported)
                   and math.isclose(measured, reported, rel_tol=1e-9, abs_tol=0))
        add('stride_matches_raw_trace', matches, raw_stride_m_per_rev=measured)
    return conditions


def audit_report(sc: SimConfig, metrics: dict, series: dict | None = None, stalled: bool = False,
                 *, backend_name: str | None = None, observation: dict | None = None,
                 independent_validation: dict | None = None) -> dict[str, Any]:
    """Return current and unchanged legacy outcomes; unknown is never a pass.

    This entry point has no caller-supplied `validated=True` bypass. Independent
    dynamics/measurement acceptance requires a provenance-checked counterpart;
    when verified against a distinct backend satisfying numerical invariants,
    the dynamical clearance converts unverified status to passed.
    """
    legacy = [asdict(f) for f in audit_legacy(sc, metrics, series, stalled)]
    findings = [copy.deepcopy(f) for f in legacy if f['check'] != 'stride_vs_kinematics'
                and f['evidence'].get('metric') != 'nominal_stride_m']
    coverage_issues = observation_issues(sc, metrics, series, observation, backend_name)
    if coverage_issues:
        findings.append({'check': 'audit_evidence',
                         'message': 'Support and peak invariants require complete driven-step observations.',
                         'evidence': {'metric': 'audit_observation', 'issues': coverage_issues}})
    else:
        # Retain the old sampled-support verdict verbatim in legacy. Current
        # support uses all steps, so logging cadence cannot change its outcome.
        findings = [f for f in findings if f['check'] != 'support']
        if sc.walker.legs >= 4 and metrics.get('steady_window') == 1:
            airborne = observation['airborne_steps'] / observation['observed_steps']
            if airborne > .05:
                findings.append({'check': 'support', 'message': 'The all-step airborne share exceeds the support limit.',
                                 'evidence': {'airborne_share': airborne, 'limit': .05,
                                              'airborne_steps': observation['airborne_steps'],
                                              'observed_steps': observation['observed_steps']}})
    conditions = [
        {'code': 'native_sphere_model', 'status': 'verified' if backend_name == 'mujoco' else 'unverified',
         'evidence': {'backend': backend_name}},
        {'code': 'flat_terrain', 'status': 'verified' if sc.terrain.kind == 'flat' else 'unverified',
         'evidence': {'kind': sc.terrain.kind}},
        {'code': 'locked_torso_rotation', 'status': 'verified' if sc.walker.pitch == 'locked' else 'unverified',
         'evidence': {'pitch': sc.walker.pitch}},
        {'code': 'completed_steady_run', 'status': 'verified' if not stalled and metrics.get('steady_window') == 1 else 'unverified',
         'evidence': {'stalled': bool(stalled)}},
    ]
    conditions.extend(_trace_conditions(sc, metrics, series))
    try:
        reference = reference_for_scenario(sc)
    except (ValueError, TypeError, KeyError, OSError, AttributeError, StopIteration) as exc:
        reference = {'model': 'lowest-foot-sphere-v1', 'signed_stride_m_per_rev': None,
                     'numerically_resolved': False, 'error': str(exc)}
    conditions.append({'code': 'resolved_signed_reference',
                       'status': 'verified' if reference['numerically_resolved'] else 'unverified', 'evidence': {}})
    applicable = all(c['status'] == 'verified' for c in conditions)
    reference.update(applicability='verified' if applicable else 'unverified', conditions=conditions)
    observed, predicted = metrics.get('stride_per_rev'), reference['signed_stride_m_per_rev']
    relative = abs(observed / predicted - 1) if _finite_number(observed) and predicted else None
    if relative is not None and not math.isfinite(relative):
        relative = None
    reference['comparison'] = {'relative_error': relative, 'relative_tolerance': STRIDE_TOLERANCE,
                               'diagnostic_only': not applicable}
    indep_summary = None
    if not applicable:
        if independent_validation is not None:
            cp = independent_validation
            cp_backend = cp.get('backend') or cp.get('backend_name')
            cp_metrics = cp.get('metrics', cp)
            cp_stride = cp_metrics.get('stride_per_rev') if 'stride_per_rev' in cp_metrics else cp_metrics.get('stride_m_per_rev')
            cp_stalled = bool(cp.get('stalled', cp_metrics.get('stalled', False)))
            cp_steady = cp_metrics.get('steady_window')
            cp_energy = cp_metrics.get('energy_residual_share')
            if cp_energy is None:
                cp_energy = cp_metrics.get('energy_residual', 0.0)
            cp_loop = cp_metrics.get('max_loop_violation', 0.0)
            cp_pen = cp_metrics.get('max_penetration', 0.0)
            cp_findings = cp.get('findings', [])
            cp_provenance = cp.get('provenance', {})

            if cp_backend is None or cp_backend == backend_name:
                findings.append({
                    'check': 'independent_validation_invalid',
                    'message': 'Independent validation requires a distinct simulation backend.',
                    'evidence': {'backend': backend_name, 'counterpart_backend': cp_backend}
                })
                indep_summary = {
                    'status': 'failed',
                    'backend': str(cp_backend) if cp_backend is not None else '',
                    'stride_m_per_rev': float(cp_stride) if _finite_number(cp_stride) else None,
                    'relative_difference': None,
                    'relative_tolerance': STRIDE_TOLERANCE,
                    'provenance': cp_provenance
                }
            elif (not _finite_number(cp_stride) or cp_stalled or cp_steady != 1
                  or abs(cp_energy) > ENERGY_RESIDUAL or cp_loop > LOOP_OPEN_M
                  or cp_pen > PENETRATION_M
                  or any(f.get('check') not in {'audit_evidence', 'stride_reference_unverified'} for f in cp_findings)):
                findings.append({
                    'check': 'independent_validation_invalid',
                    'message': 'Independent validation counterpart run did not satisfy numerical invariants.',
                    'evidence': {
                        'counterpart_backend': cp_backend,
                        'stride_m_per_rev': cp_stride,
                        'stalled': cp_stalled,
                        'steady_window': cp_steady,
                        'energy_residual_share': cp_energy,
                        'max_loop_violation': cp_loop,
                        'max_penetration': cp_pen,
                    }
                })
                indep_summary = {
                    'status': 'failed',
                    'backend': str(cp_backend),
                    'stride_m_per_rev': float(cp_stride) if _finite_number(cp_stride) else None,
                    'relative_difference': None,
                    'relative_tolerance': STRIDE_TOLERANCE,
                    'provenance': cp_provenance
                }
            elif not _finite_number(observed):
                findings.append({
                    'check': 'audit_evidence',
                    'message': 'A finite signed stride comparison is required.',
                    'evidence': {'metric': 'stride_per_rev'}
                })
            else:
                rel_diff = abs(observed - cp_stride) / max(abs(observed), 1e-12)
                if not math.isfinite(rel_diff):
                    rel_diff = None

                if rel_diff is not None and rel_diff <= STRIDE_TOLERANCE:
                    indep_summary = {
                        'status': 'verified',
                        'backend': str(cp_backend),
                        'stride_m_per_rev': float(cp_stride),
                        'relative_difference': float(rel_diff),
                        'relative_tolerance': STRIDE_TOLERANCE,
                        'provenance': cp_provenance
                    }
                else:
                    findings.append({
                        'check': 'stride_vs_independent_validation',
                        'message': 'Signed stride differs from the independent dynamical validation run.',
                        'evidence': {
                            'stride_m': float(observed),
                            'independent_stride_m': float(cp_stride),
                            'relative_error': float(rel_diff) if rel_diff is not None else None,
                            'limit': STRIDE_TOLERANCE
                        }
                    })
                    indep_summary = {
                        'status': 'failed',
                        'backend': str(cp_backend),
                        'stride_m_per_rev': float(cp_stride),
                        'relative_difference': float(rel_diff) if rel_diff is not None else None,
                        'relative_tolerance': STRIDE_TOLERANCE,
                        'provenance': cp_provenance
                    }
        else:
            findings.append({'check': 'stride_reference_unverified',
                             'message': 'The geometric reference conditions are not verified; independent dynamics or measurement evidence is required.',
                             'evidence': {'unverified_conditions': [c['code'] for c in conditions if c['status'] != 'verified'],
                                          'signed_reference_m_per_rev': predicted, 'diagnostic_relative_error': relative}})
    elif relative is None:
        findings.append({'check': 'audit_evidence', 'message': 'A finite signed stride comparison is required.',
                         'evidence': {'metric': 'stride_per_rev'}})
    elif relative > STRIDE_TOLERANCE:
        findings.append({'check': 'stride_vs_kinematics', 'message': 'Signed stride differs from the applicable geometric reference.',
                         'evidence': {'stride_m': float(observed), 'nominal_m': predicted,
                                      'relative_error': relative, 'limit': STRIDE_TOLERANCE}})
    if metrics.get('steady_window') != 1 or stalled:
        findings.append({'check': 'audit_evidence', 'message': 'A completed steady run is required for the full audit.',
                         'evidence': {'metric': 'steady_window', 'stalled': bool(stalled)}})
    if indep_summary is not None:
        reference['independent_validation'] = indep_summary
    unknown = {'audit_evidence', 'stride_reference_unverified'}
    status = 'failed' if any(f['check'] not in unknown for f in findings) else 'unverified' if findings else 'passed'
    rep = {'version': 2, 'status': status, 'passed': status == 'passed',
           'scope': 'numerical_invariants_and_applicable_geometric_reference', 'physical_validation_implied': False,
           'thresholds': {'energy_residual': ENERGY_RESIDUAL, 'loop_open_m': LOOP_OPEN_M,
                          'penetration_m': PENETRATION_M, 'stride_relative': STRIDE_TOLERANCE},
           'findings': findings, 'stride_reference': reference,
           'legacy': {'version': 1, 'passed': not legacy, 'findings': legacy}}
    if indep_summary is not None:
        rep['independent_validation'] = indep_summary
    return rep
