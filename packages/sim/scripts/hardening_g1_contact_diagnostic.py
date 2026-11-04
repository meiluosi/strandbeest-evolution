"""Finite-foot / multi-contact diagnostic. Draft: no production acceptance gate.

Default is self-test only. --run-six performs the six fixed native diagnostics.
Six fixed inputs, one sequential worker, no physical overrides, no corpus changes.
All output is restricted to a fresh /tmp directory. No repository writes.
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
from array import array
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import time
import traceback
from types import SimpleNamespace
import numpy as np
import mujoco
import beest_kernel
from strandbeest_common import solve_pose
from strandbeest_sim.backends.mujoco_backend import MujocoBackend
from strandbeest_sim.builder import resolve_spec
from strandbeest_sim.config import sim_config
from strandbeest_sim.runner import run
from strandbeest_sim.skeptic import audit_legacy as audit, ENERGY_RESIDUAL, LOOP_OPEN_M, PENETRATION_M, STRIDE_TOLERANCE

ROOT = Path(__file__).resolve().parents[3]
SOURCES = {
    'default': 'experiments/hardening-g1-energy-v2-default-2026-11-03.json',
    'strong': 'experiments/hardening-g1-energy-v2-solref05-frozen-repeat-2026-11-03.json',
    'half': 'experiments/hardening-g1-energy-v2-solref05-dt005-frozen-repeat-2026-11-03.json',
}
FORCE_CUTOFF_N = 1e-6  # Existing skeptic support definition, applied to total force per foot.
DERIVATIVE_STEP_RAD = 1e-5  # Geometry diagnostic differentiation, not a physics parameter.
COMPONENTS = ['point', 'rolling', 'support_schedule', 'angular_compliance', 'contact_lever',
              'centre_kinematics', 'signed_slip', 'airborne', 'integration_update']
COLUMNS = ['step', 'time_s', 'psi_rad', 'x_m', 'vx_pre_m_s', 'vx_post_m_s', 'supports',
           'normal_total_N', 'identity_error_m_s', 'slip_weighted_abs_m_s',
           'ideal_support_spread_m_s', 'ideal_support_rms_m_s', *[key + '_m_s' for key in COMPONENTS]]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def source_hashes():
    paths = {Path(__file__).resolve()}
    for directory, pattern in [('packages/sim/src', '*.py'), ('packages/common/src', '*.py'),
                               ('crates', '*.rs'), ('schemas', '*.json')]:
        paths.update((ROOT / directory).rglob(pattern))
    # Include the loaded extension binary, not merely Python source or an installed version label.
    paths.update(Path(beest_kernel.__file__).resolve().parent.glob('*.so'))
    paths.add(Path(beest_kernel.__file__).resolve())
    return {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): digest(p) for p in sorted(paths)}

def changed_sources(initial, final):
    return [key for key in sorted(initial.keys() | final.keys()) if initial.get(key) != final.get(key)]

def output_dir(path):
    path = path.expanduser().resolve()
    if not path.is_relative_to(Path('/tmp').resolve()):
        raise ValueError('Draft output must stay under /tmp')
    path.mkdir(parents=True, exist_ok=False)
    return path

def write_json(path, doc):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(doc, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)

def safe_json(value):
    if isinstance(value, dict):
        return {key: safe_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [safe_json(item) for item in value]
    if isinstance(value, (float, np.floating)) and not math.isfinite(value):
        return {'nonfinite': str(value)}
    if isinstance(value, np.generic):
        return value.item()
    return value

def fixed_jobs():
    jobs = []
    for label, name in SOURCES.items():
        path = ROOT / name
        evidence = json.loads(path.read_text())
        for case in [53, 61]:
            rows = [row for row in evidence['rows'] if row['case'] == case]
            if len(rows) != 1 or not rows[0]['completed']:
                raise ValueError(f'Missing or incomplete fixed input: {label}/{case}')
            row = rows[0]
            cfg = sim_config(row['scenario'])
            assert cfg.terrain.kind == 'flat' and cfg.drive.kind == 'motor' and cfg.walker.pitch == 'locked'
            jobs.append({'label': label, 'case': case, 'source': name, 'source_sha256': digest(path),
                         'scenario': row['scenario'], 'scenario_sha256': canonical(row['scenario']),
                         'previous_metrics': row['metrics'], 'previous_findings': row['findings'],
                         'previous_wall_s': row['wall_s']})
    return jobs

def audit_window(psi):
    """Exact gait/energy endpoint selection; no interpolation or monotonicity assumption."""
    if len(psi) < 2:
        return None
    rev = 2 * math.pi
    total = (psi[-1] - psi[0]) / rev
    if total >= 1.98:
        n = max(1, math.floor(total + 0.02) - 1)
        lo, hi = rev, min(rev * (1 + n), psi[-1])
    else:
        lo, hi = 0.0, psi[-1]
    idx = np.flatnonzero((psi >= lo) & (psi <= hi))
    if len(idx) < 2 or psi[idx[-1]] <= psi[idx[0]]:
        return None
    return int(idx[0]), int(idx[-1])

def decompose(v_body, point, rolling, contacts, v_post):
    """All arguments/terms except weights and radius are SI velocities (m/s).

    u_actual = world foot CENTRE vx minus world torso vx; excludes omega x r.
    Contacts already selected by per-foot total normal load > existing cutoff.
    Normal-load weighting is a declared diagnostic convention, not a no-slip law.
    """
    terms = dict.fromkeys(COMPONENTS, 0.0)
    terms.update(point=point, rolling=rolling, integration_update=v_post-v_body)
    if contacts:
        forces = np.asarray([c['normal_N'] for c in contacts], float)
        weights = forces / forces.sum()
        avg = lambda key: sum(w * c[key] for w, c in zip(weights, contacts))
        ideal = [(-c['u_ideal_m_s'] + c['radius_m'] * c['omega_ideal_rad_s']) for c in contacts]
        terms['support_schedule'] = sum(w * value for w, value in zip(weights, ideal)) - point - rolling
        terms['angular_compliance'] = sum(w*c['radius_m']*(c['omega_actual_rad_s']-c['omega_ideal_rad_s']) for w,c in zip(weights,contacts))
        terms['contact_lever'] = sum(w*(-c['rotation_x_m_s']-c['radius_m']*c['omega_actual_rad_s']) for w,c in zip(weights,contacts))
        terms['centre_kinematics'] = -sum(w*(c['u_actual_m_s']-c['u_ideal_m_s']) for w,c in zip(weights,contacts))
        terms['signed_slip'] = avg('contact_vx_m_s')
        stats = {'normal_total_N': float(forces.sum()),
                 'slip_weighted_abs_m_s': sum(w*abs(c['contact_vx_m_s']) for w,c in zip(weights,contacts)),
                 'ideal_support_spread_m_s': max(ideal)-min(ideal),
                 'ideal_support_rms_m_s': math.sqrt(sum(w*(value-sum(ww*vv for ww,vv in zip(weights,ideal)))**2 for w,value in zip(weights,ideal)))}
    else:
        terms['airborne'] = v_body - point - rolling
        stats = dict(normal_total_N=0.0, slip_weighted_abs_m_s=0.0, ideal_support_spread_m_s=0.0, ideal_support_rms_m_s=0.0)
    # Without the explicit integration update, this is an identity at t_n.
    stats['identity_error_m_s'] = sum(terms.values()) - v_post
    return terms, stats

def rotation_x(omega, lever):
    return float(omega[1] * lever[2] - omega[2] * lever[1])

def angle_diff(a, b):
    return math.atan2(math.sin(a-b), math.cos(a-b))

def derivative_from_poses(poses, start, end, foot, unit, theta_dot, h):
    before, current, after = poses
    beta = lambda pose: math.atan2(pose[end][1]-pose[start][1], pose[end][0]-pose[start][0])
    u = unit * (after[foot][0]-before[foot][0]) / (2*h) * theta_dot
    omega = -angle_diff(beta(after), beta(before)) / (2*h) * theta_dot
    return {'centre_hip_m': [unit*current[foot][0], unit*current[foot][1]],
            'u_ideal_m_s': u, 'omega_ideal_rad_s': omega}

def geometry_reference(cfg, spec, ownership, brackets):
    """Predictive lowest-sphere reference from geometry only; actual dynamics never enters.

    Event intervals integrate endpoint x and unwrapped owner angle rather than a
    derivative quadrature. It is still an ideal single-support, rigid-closure,
    fixed-radius, no-slip model; matching it is not a universal physical invariant.
    """
    n=cfg.walker.legs
    owner=ownership[0]
    phases=[2*math.pi*j/n for j in range(n)]
    radius=owner['radius_m']
    def pose(a):
        value=solve_pose(spec,a)
        if value is None:
            raise ValueError('Ideal reference cannot assemble')
        return value
    def foot(a):
        return pose(a)[spec.foot]
    def beta(a):
        points=pose(a);start,end=points[owner['start']],points[owner['end']]
        return math.atan2(end[1]-start[1],end[0]-start[0])
    def support(a):
        return min(range(n),key=lambda leg:foot(a+phases[leg])[1])
    edges=[0.0]; previous=support(0.)
    for i in range(1,brackets+1):
        a,b=2*math.pi*(i-1)/brackets,2*math.pi*i/brackets
        following=support(b)
        if following!=previous:
            for _ in range(48):
                middle=(a+b)*.5
                if support(middle)==previous:
                    a=middle
                else:
                    b=middle
            edges.append((a+b)*.5)
        previous=following
    edges.append(2*math.pi)
    point=rolling=variation=0.0
    for a,b in zip(edges,edges[1:]):
        phase=phases[support((a+b)*.5)]
        angles=np.linspace(a,b,33)+phase
        owner_angles=np.unwrap([beta(theta) for theta in angles])
        xs=np.array([foot(theta)[0] for theta in angles])*cfg.walker.unit
        point-=cfg.walker.direction*(xs[-1]-xs[0])
        rolling-=cfg.walker.direction*radius*(owner_angles[-1]-owner_angles[0])
        variation+=float(np.abs(np.diff(xs+radius*owner_angles)).sum())
    return {'brackets':brackets,'point_stride_m_per_rev':float(point),
            'rolling_m_per_rev':float(rolling),'contact_stride_m_per_rev':float(point+rolling),
            'absolute_contact_travel_m_per_rev':variation,
            'cancellation_condition':variation/abs(point+rolling) if point+rolling else None,
            'support_intervals':len(edges)-1,'radius_m':radius,
            'inference_limit':'Geometry-only prediction with explicit ideal assumptions; not an automatic replacement audit gate.'}

class ContactDiagnosticBackend(MujocoBackend):
    """Read-only observer. Never calls mj_forward on any live or scratch state."""
    def __init__(self, trace_path):
        super().__init__()
        self.rows = array('d')
        self.trace = gzip.open(trace_path, 'xt', encoding='utf-8')
        self.completed_steps = 0
        self.observation_state_checks = 0
        self.ownership = []
        self.psi_start = None

    def build(self, cfg, plan):
        info = super().build(cfg, plan)
        self.cfg, self.spec = cfg, resolve_spec(cfg)
        self.settle_steps = int(round(cfg.run.settle / self.timestep))
        self.torso_id = self._id(mujoco.mjtObj.mjOBJ_BODY, 'torso')
        self.geom_meta = {}
        for geom in self._foot_geoms:
            owner = self._name(mujoco.mjtObj.mjOBJ_BODY, int(self.model.geom_bodyid[geom]))
            match = re.fullmatch(r'bar(\d+)_(.+)([01])', owner)
            if not match:
                raise ValueError(f'Unrecognized sphere owner {owner}')
            leg, end, branch = int(match[1]), match[2], int(match[3])
            joint = next(j for j in self.spec.joints if j.id == end)
            meta = {'geom': geom, 'name': self._name(mujoco.mjtObj.mjOBJ_GEOM, geom), 'owner': owner,
                    'leg': leg, 'start': joint.centers[branch], 'end': end,
                    'phase_rad': 2*math.pi*leg/cfg.walker.legs,
                    'radius_m': float(self.model.geom_size[geom, 0]), 'condim': int(self.model.geom_condim[geom])}
            self.geom_meta[geom] = meta
            self.ownership.append(meta)
        if len(self.ownership) != cfg.walker.legs:
            raise ValueError('Expected exactly one sphere per leg')
        return info

    def step(self, n=1):
        for _ in range(n):
            super().step()
            index = self.completed_steps - self.settle_steps
            self.completed_steps += 1
            if index < 0:
                continue
            before = self.snapshot().payload
            view = self.step_observation()
            self.capture(view, index)
            after = self.snapshot().payload
            if not np.array_equal(before, after):
                raise AssertionError('Observer modified mjSTATE_INTEGRATION (including warmstart)')
            self.observation_state_checks += 1

    def capture(self, view, index):
        m, d = view.model, view.data
        q = view.joint_position(self._info.crank_joint)
        theta0 = -(q-self._info.crank_q0)
        theta_dot = -view.joint_velocity(self._info.crank_joint)
        psi_absolute = self.cfg.walker.direction * theta0
        if self.psi_start is None:
            self.psi_start = psi_absolute
        vx = view.joint_velocity('tx')
        vx_post = self.joint_velocity('tx')
        ideal = {}
        for geom, meta in self.geom_meta.items():
            theta = theta0 + meta['phase_rad']
            poses = [solve_pose(self.spec, theta+delta) for delta in [-DERIVATIVE_STEP_RAD, 0.0, DERIVATIVE_STEP_RAD]]
            if any(p is None for p in poses):
                raise ValueError('Ideal geometry fails to assemble at observed phase')
            ideal[geom] = derivative_from_poses(poses, meta['start'], meta['end'], self.spec.foot,
                                               self.cfg.walker.unit, theta_dot, DERIVATIVE_STEP_RAD)
        low = min(ideal, key=lambda g: ideal[g]['centre_hip_m'][1]-self.geom_meta[g]['radius_m'])
        point = -ideal[low]['u_ideal_m_s']
        rolling = self.geom_meta[low]['radius_m'] * ideal[low]['omega_ideal_rad_s']
        contacts, normal_by_geom = [], dict.fromkeys(self._foot_geoms, 0.0)
        for i in range(d.ncon):
            c = d.contact[i]
            g1, g2 = int(c.geom1), int(c.geom2)
            foot, sign = (g2, 1.0) if g2 in self.geom_meta else (g1, -1.0) if g1 in self.geom_meta else (None, 0.0)
            if foot is None:
                continue
            if g1 in self.geom_meta and g2 in self.geom_meta:
                raise AssertionError('Unexpected foot-foot contact violates intended model')
            f6, vel = np.zeros(6), np.zeros(6)
            mujoco.mj_contactForce(m, d, i, f6)
            mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_GEOM, foot, vel, 0)
            centre = d.geom_xpos[foot].copy()
            lever = np.asarray(c.pos)-centre
            rot = rotation_x(vel[:3], lever)
            normal = max(float(f6[0]), 0.0)
            normal_by_geom[foot] += normal
            frame = np.asarray(c.frame).reshape(3, 3)
            rec = {'contact': i, 'geom': foot, 'other_geom': g1 if foot==g2 else g2,
                   'normal_N': normal, 'force_contact_N': f6[:3].tolist(),
                   'force_world_on_foot_N': (sign*frame.T@f6[:3]).tolist(),
                   'normal_world_toward_foot': (sign*frame[0]).tolist(),
                   'contact_pos_m': np.asarray(c.pos).tolist(), 'centre_pos_m': centre.tolist(),
                   'lever_m': lever.tolist(), 'omega_world_rad_s': vel[:3].tolist(),
                   'centre_velocity_world_m_s': vel[3:].tolist(),
                   'radius_m': self.geom_meta[foot]['radius_m'],
                   'omega_actual_rad_s': float(vel[1]), 'rotation_x_m_s': rot,
                   'u_actual_m_s': float(vel[3]-vx), 'contact_vx_m_s': float(vel[3]+rot),
                   **ideal[foot]}
            contacts.append(rec)
        active = {g for g, force in normal_by_geom.items() if force > FORCE_CUTOFF_N}
        weighted = [c for c in contacts if c['geom'] in active and c['normal_N'] > 0]
        terms, stats = decompose(vx, point, rolling, weighted, vx_post)
        self.rows.extend([index, index*self.timestep, psi_absolute-self.psi_start,
                          float(d.xpos[self.torso_id, 0]), vx, vx_post, len(active),
                          stats['normal_total_N'], stats['identity_error_m_s'],
                          stats['slip_weighted_abs_m_s'], stats['ideal_support_spread_m_s'], stats['ideal_support_rms_m_s'],
                          *[terms[key] for key in COMPONENTS]])
        self.trace.write(json.dumps({'step': index, 'time_s': index*self.timestep,
                                     'lowest_geom': low, 'contacts': contacts,
                                     'active_geoms': sorted(active)}, separators=(',', ':'), allow_nan=False)+'\n')

    def close(self):
        self.trace.close()


def summarize_window(result, backend):
    rows = np.frombuffer(backend.rows, dtype=np.float64).reshape(-1, len(COLUMNS))
    rec, dt = result.scenario.run.record_every, backend.timestep
    sampled = rows[::rec]
    if len(sampled) != len(result.t):
        raise AssertionError('Observer sample count differs from runner')
    for column, expected in [('psi_rad', result.psi), ('x_m', result.x)]:
        if not np.array_equal(sampled[:, COLUMNS.index(column)], expected):
            raise AssertionError(f'Observer/runner boundary mismatch: {column}')
    # Runner accumulates t; integer step multiplication differs by floating roundoff only.
    time_error = float(np.max(np.abs(sampled[:, 1]-result.t))) if len(sampled) else 0.0
    window = audit_window(result.psi)
    if window is None:
        return {'window': None, 'reason': 'Same invalid/short endpoint condition as existing gait audit'}, rows
    i0, i1 = window
    k0, k1 = i0*rec, i1*rec
    segment = rows[k0:k1]
    dpsi = result.psi[i1]-result.psi[i0]
    components = {key: float(segment[:, COLUMNS.index(key+'_m_s')].sum()*dt) for key in COMPONENTS}
    displacement = float(result.x[i1]-result.x[i0])
    stride = displacement/dpsi*(2*math.pi)
    if stride != result.metrics['stride_per_rev']:
        raise AssertionError('Window does not reproduce original stride metric exactly')
    balance = sum(components.values())-displacement
    return {'window': {'record_i0': i0, 'record_i1': i1, 'step_k0_inclusive': k0,
                       'step_k1_exclusive': k1, 'psi_rad': [float(result.psi[i0]), float(result.psi[i1])],
                       'time_s': [float(result.t[i0]), float(result.t[i1])], 'duration_s': (k1-k0)*dt},
            'sample_time_roundoff_max_s': time_error,
            'observed_displacement_m': displacement, 'original_stride_m_per_rev': stride,
            'components_m': components,
            'components_m_per_rev': {key: value/dpsi*(2*math.pi) for key,value in components.items()},
            'identity_displacement_error_m': balance,
            'identity_velocity_error_max_m_s': float(np.max(np.abs(segment[:, COLUMNS.index('identity_error_m_s')]))),
            'supports_count_histogram': {str(n): int(np.sum(segment[:,6]==n)) for n in sorted(set(segment[:,6].astype(int)))},
            'slip_weighted_abs_mean_m_s': float(np.mean(segment[:, COLUMNS.index('slip_weighted_abs_m_s')])),
            'ideal_support_spread_p95_m_s': float(np.quantile(segment[:, COLUMNS.index('ideal_support_spread_m_s')], .95)),
            'ideal_support_rms_mean_m_s': float(np.mean(segment[:, COLUMNS.index('ideal_support_rms_m_s')])),
            'interpretation': 'Algebraic/kinematic decomposition conditional on actual contact schedule; reconstruction is not independent physical validation.'}, rows


def self_tests():
    tests = []
    def record(name, details):
        tests.append({'name': name, 'passed': True, **details})
    # Independent closed-form translation/rotation; both velocity signs and zero start.
    for direction in [-1, 0, 1]:
        v = direction*.0038
        omega = direction*2.0
        lever = [0, 0, -.0019]
        cp = v + rotation_x([0,omega,0], lever)
        assert abs(cp) < 1e-16
        record(f'analytic_sphere_sign_{direction}', {'contact_vx_m_s': cp, 'radius_m': .002, 'penetration_m': .0002})
    for v in [-.4, 0.0, .4]:
        contacts = []
        for u, w, weight, lever_z in [(-.3,2.0,1.,-.0019), (.2,-1.,3.,-.002)]:
            contacts.append({'normal_N':weight, 'radius_m':.002, 'u_ideal_m_s':u*.8,
                             'u_actual_m_s':u, 'omega_ideal_rad_s':w*.9, 'omega_actual_rad_s':w,
                             'rotation_x_m_s':w*lever_z, 'contact_vx_m_s':v+u+w*lever_z})
        terms, stats = decompose(v,.1,.003,contacts,v+.01)
        assert abs(sum(terms.values())-(v+.01)) < 1e-15
        assert stats['ideal_support_spread_m_s'] > 0
        record(f'multicontact_identity_{v}', {'error_m_s': stats['identity_error_m_s'], 'not_independent_validation': True})
    terms, stats = decompose(.27,.1,.003,[],.28)
    assert abs(sum(terms.values())-.28) < 1e-15 and terms['airborne']==.27-.1-.003
    record('empty_support_defined_airborne', {'airborne_m_s': terms['airborne']})
    # Compatible versus opposing ideal supports: no false exact-sticking oracle.
    for velocities, spread in [([-.2,-.2],0.0), ([-.2,.2],.4)]:
        contacts=[{'normal_N':1.,'radius_m':0.,'u_ideal_m_s':u,'u_actual_m_s':u,
                   'omega_ideal_rad_s':0.,'omega_actual_rad_s':0.,'rotation_x_m_s':0.,'contact_vx_m_s':u} for u in velocities]
        _, stats=decompose(0.,0.,0.,contacts,0.)
        assert stats['ideal_support_spread_m_s']==spread
        record(f'ideal_support_spread_{spread}', {'spread_m_s':spread})
    # Analytic ellipse + rotating owner tests derivative sign, length-unit conversion, reverse/zero angular speed.
    h=DERIVATIVE_STEP_RAD
    for speed in [-3., 0., 3.]:
        theta=.7
        def pose(a):
            return {'N':(2*math.cos(a)-math.cos(2*a), -math.sin(a)-math.sin(2*a)),
                    'F':(2*math.cos(a),-math.sin(a))}
        got=derivative_from_poses([pose(theta-h),pose(theta),pose(theta+h)],'N','F','F',.001,speed,h)
        assert abs(got['u_ideal_m_s']-(-.002*math.sin(theta)*speed)) < 1e-12
        assert abs(got['omega_ideal_rad_s']-(-2*speed)) < 1e-9
        record(f'geometry_derivative_sign_{speed}',got)
    # Independent closed-form full-cycle ideal reference: 2 elliptic feet, rotating owners.
    native_solve=globals()['solve_pose']
    def ellipse_pose(spec, angle):
        foot=(2*math.cos(angle),math.sin(angle))
        return {'F':foot,'N':(foot[0]-math.cos(angle),foot[1]-math.sin(angle))}
    globals()['solve_pose']=ellipse_pose
    try:
        for direction in [-1,1]:
            for radius in [0.0,.002]:
                cfg=SimpleNamespace(walker=SimpleNamespace(legs=2,unit=.001,direction=direction))
                got=geometry_reference(cfg,SimpleNamespace(foot='F'),[{'start':'N','end':'F','radius_m':radius}],72)
                expected_point=-direction*.008
                expected_roll=-direction*2*math.pi*radius
                assert abs(got['point_stride_m_per_rev']-expected_point)<1e-14
                assert abs(got['rolling_m_per_rev']-expected_roll)<1e-14
                record(f'full_cycle_ellipse_direction_{direction}_radius_{radius}',got)
    finally:
        globals()['solve_pose']=native_solve
    # Exact existing window includes non-monotone psi; units dx/dpsi*2pi = m/rev.
    psi=np.array([0.,5.,6.3,7.,6.2,8.,12.4,12.5])
    assert audit_window(psi)==(2,7)
    record('nonmonotone_original_audit_window',{'indices':[2,7]})
    # Semiimplicit x increment is v_next*dt; explicit correction restores it over a strict subwindow.
    for a in [-2.,0.,2.]:
        dt=.001; pre=np.arange(100)*dt*a; post=pre+a*dt
        x=np.r_[0.,np.cumsum(post*dt)]
        k0,k1=17,83
        left=pre[k0:k1].sum()*dt
        update=(post[k0:k1]-pre[k0:k1]).sum()*dt
        assert abs(left+update-(x[k1]-x[k0])) < 1e-15
        record(f'semiimplicit_window_acceleration_{a}',{'left_m':float(left),'update_m':float(update),'observed_m':float(x[k1]-x[k0])})
    # Independent MuJoCo contact Jacobian: no walker and no time integration.
    xml='''<mujoco><option cone="elliptic"/><worldbody><geom type="plane" size="1 1 .1"/><body pos="0 0 .0018"><freejoint/><geom name="sphere" type="sphere" size=".002" mass="1" condim="3"/></body></worldbody></mujoco>'''
    m=mujoco.MjModel.from_xml_string(xml)
    for sign in [-1,1]:
        d=mujoco.MjData(m); d.qvel[0]=sign*.0038;d.qvel[4]=sign*2.
        # Initial forward on a tiny independent analytic fixture is allowed; never on observed live walker data.
        mujoco.mj_forward(m,d)
        assert d.ncon==1
        g=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,'sphere')
        vel=np.zeros(6);mujoco.mj_objectVelocity(m,d,mujoco.mjtObj.mjOBJ_GEOM,g,vel,0)
        lever=d.contact[0].pos-d.geom_xpos[g]
        cp=float(vel[3]+rotation_x(vel[:3],lever))
        assert abs(cp)<1e-15 and np.max(np.abs(d.efc_vel))<1e-15
        record(f'mujoco_contact_jacobian_{sign}',{'contact_vx_m_s':cp,'efc_velocity_max_m_s':float(np.max(np.abs(d.efc_vel))),'lever_z_m':float(lever[2])})
    # Existing coherent observation path must leave every integration-state bit unchanged.
    a,b=MujocoBackend(),MujocoBackend()
    for backend in (a,b):
        backend.build_reference('pendulum', angle=.3, timestep=.001)
    original_forward=mujoco.mj_forward
    def forbidden_forward(*args,**kwargs):
        raise AssertionError('Observation tried to call mj_forward')
    mujoco.mj_forward=forbidden_forward
    try:
        for _ in range(100):
            a.step(); b.step()
            before=b.snapshot().payload.copy();view=b.step_observation()
            _=view.body_position('bob');_=view.energies()
            assert np.array_equal(before,b.snapshot().payload)
            assert np.array_equal(a.snapshot().payload,b.snapshot().payload)
    finally:
        mujoco.mj_forward=original_forward
    record('preintegration_observer_noninterference_100_pendulum_steps',{'exact_state_equal':True,'warmstart_included':True,'mj_forward_forbidden_during_steps':True})
    assert changed_sources({'a':'1','deleted':'2'},{'a':'1','new':'3'})==['deleted','new']
    record('source_snapshot_union_detects_additions_deletions',{})
    jobs=fixed_jobs()
    record('six_fixed_inputs_no_simulation',{'jobs':[{'label':j['label'],'case':j['case'],'scenario_sha256':j['scenario_sha256']} for j in jobs]})
    return {'mode':'self-test only; zero walker steps or builds','tests':tests,'passed':len(tests),'failed':0,
            'previous_six_run_simulation_only_wall_s':sum(j['previous_wall_s'] for j in jobs),
            'six_run_runtime_warning':'Observer computes ideal poses and streams every contact every step; wall time is not measured yet and may greatly exceed old baseline durations.'}


def run_six(directory):
    jobs=fixed_jobs(); initial=source_hashes()
    document={'status':'running','independent_acceptance':False,'started_utc':datetime.now(timezone.utc).isoformat(),
              'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'python':platform.python_version(),'mujoco':importlib.metadata.version('mujoco'),'numpy':np.__version__,
              'source_hashes':initial,'source_scope':'sim/common Python, Rust sources, schema JSON, loaded native extension and diagnostic script',
              'units':{'velocity_components':'m/s','integrated_components':'m','normalized_components':'m/revolution','angle':'rad','angular_velocity':'rad/s','force':'N'},
              'thresholds_unchanged':{'energy_residual_share':ENERGY_RESIDUAL,'loop_open_m':LOOP_OPEN_M,'penetration_m':PENETRATION_M,'stride_relative_error':STRIDE_TOLERANCE},
              'diagnostic_definitions':{'weighting':'normal force normalized over contacts of feet with total normal force > 1e-6 N','derivative_step_rad':DERIVATIVE_STEP_RAD,
                 'boundary':'preintegration step_observation; no mj_forward during observation','integration':'Each t_n term times dt; separate v_next-v_n term matches semiimplicit translation',
                 'window':'Exact current gait/energy endpoint selection; integrate all steps in [i0*record_every,i1*record_every)',
                 'inference_limit':'Identity reconstruction is not an independent validation or replacement of existing stride gate; actual schedule/slip/compliance are observed inputs'},
              'rows':[]}
    write_json(directory/'manifest.json',document)
    for job in jobs:
        name=f"{job['label']}-case{job['case']}"; trace=directory/(name+'-contacts.jsonl.gz')
        backend=ContactDiagnosticBackend(trace); start=time.monotonic()
        row={**job,'completed':False}
        try:
            result=run(job['scenario'],backend=backend)
            summary,rows=summarize_window(result,backend)
            reference=[geometry_reference(result.scenario,backend.spec,backend.ownership,n) for n in [720,1440]]
            arrays=directory/(name+'-steps.npz')
            np.savez_compressed(arrays,steps=rows,columns=np.asarray(COLUMNS),t=result.t,psi=result.psi,x=result.x,
                                **{'series_'+key:value for key,value in result.series.items()})
            findings=[asdict(f) for f in audit(result.scenario,result.metrics,result.series,result.stalled)]
            row.update(completed=True,metrics=safe_json(result.metrics),stalled=result.stalled,findings=safe_json(findings),
                       metrics_exactly_equal_previous=result.metrics==job['previous_metrics'],
                       metric_differences={key:{'before':job['previous_metrics'].get(key),'after':value} for key,value in result.metrics.items() if job['previous_metrics'].get(key)!=value},
                       diagnostic=summary,geometry_only_reference=reference,sphere_ownership=backend.ownership,observation_state_checks=backend.observation_state_checks,
                       arrays_file=arrays.name,arrays_sha256=digest(arrays))
        except Exception as exc:
            partial=directory/(name+'-partial-steps.npz')
            np.savez_compressed(partial,steps=np.frombuffer(backend.rows,dtype=np.float64).reshape(-1,len(COLUMNS)),columns=np.asarray(COLUMNS))
            row.update(partial_arrays_file=partial.name,partial_arrays_sha256=digest(partial))
            row.update(error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc(),observation_state_checks=backend.observation_state_checks)
        finally:
            backend.close()
        row.update(wall_s=time.monotonic()-start,contacts_file=trace.name,contacts_sha256=digest(trace))
        document['rows'].append(safe_json(row));write_json(directory/'manifest.json',document)
        print(json.dumps({'done':len(document['rows']),'name':name,'completed':row['completed'],'wall_s':row['wall_s']}),flush=True)
    final=source_hashes();document.update(status='complete',all_six_completed=all(row['completed'] for row in document['rows']),
                                         sources_changed_during_run=changed_sources(initial,final),final_source_hashes=final)
    write_json(directory/'manifest.json',document)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-six',action='store_true',help='Run the six fixed native diagnostics instead of self-tests')
    parser.add_argument('--output',type=Path,required=True,help='Fresh directory under /tmp')
    args=parser.parse_args();directory=output_dir(args.output)
    if args.run_six:
        run_six(directory)
    else:
        start=time.monotonic();before=source_hashes();report=self_tests();after=source_hashes()
        report.update(wall_s=time.monotonic()-start,script_sha256=digest(__file__),source_hashes=before,
                      sources_changed_during_self_tests=changed_sources(before,after))
        write_json(directory/'self-test.json',report)
        print(json.dumps({key:report[key] for key in ['mode','passed','failed','wall_s','script_sha256','previous_six_run_simulation_only_wall_s']}),flush=True)

if __name__=='__main__':
    main()
