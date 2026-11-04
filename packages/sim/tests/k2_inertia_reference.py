"""Independent test oracle: native maximal-coordinate inertia projected by finite differences.

This helper does not import the K2 mass assembler or its interpolation table.
It positions the native rigid bodies on the exact linkage manifold and obtains
its velocity map by differences of independently reconstructed joint angles.
"""
import math
import re
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

from strandbeest_sim.builder import build, resolve_spec
from strandbeest_sim.linkage import solve_pose


class NativeReducedOracle:
    def __init__(self, cfg):
        self.cfg = cfg
        self.spec = resolve_spec(cfg)
        built = build(cfg, self.spec)
        self.model = mujoco.MjModel.from_xml_string(built.xml)
        self.data = mujoco.MjData(self.model)
        self.tree = ET.fromstring(built.xml)
        self.parents = {child.get('name'): body.get('name') for body in self.tree.iter('body') for child in body.findall('body')}
        self.names = [mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(1, self.model.nbody)]
        self.initial_angles = self.angles(0.)
        self.height = built.hip_height

    def angles(self, psi):
        phases = [math.tau*k/self.cfg.walker.legs for k in range(self.cfg.walker.legs)]
        poses = [solve_pose(self.spec, phase+self.cfg.walker.direction*psi) for phase in phases]
        angles = {'torso': 0.}
        for name in self.names[1:]:
            crank = re.fullmatch(r'crank(\d+)', name)
            if crank:
                leg = int(crank[1])
                angles[name] = phases[leg]+self.cfg.walker.direction*psi
            else:
                match = re.fullmatch(r'bar(\d+)_(.+)([01])', name)
                leg = int(match[1])
                joint = next(j for j in self.spec.joints if j.id == match[2])
                a = poses[leg][joint.centers[int(match[3])]]
                b = poses[leg][joint.id]
                angles[name] = math.atan2(b[1]-a[1], b[0]-a[0])
        return angles

    def position(self, q):
        angles = self.angles(q[3])
        position = self.model.qpos0.copy()
        for j in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, j)
            if name == 'tx': value = q[0]
            elif name == 'tz': value = q[1]-self.height
            elif name == 'tp': value = -q[2]
            else:
                parent = self.parents[name]
                value = position[self.model.jnt_qposadr[j]] - (
                    angles[name]-self.initial_angles[name] - angles[parent]+self.initial_angles[parent])
            position[self.model.jnt_qposadr[j]] = value
        return position

    def tangent(self, q, h=1e-5):
        columns = []
        for axis in np.eye(4):
            left, right = self.position(q-h*axis), self.position(q+h*axis)
            delta = right-left
            for j in range(self.model.njnt):
                if self.model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE:
                    address = self.model.jnt_qposadr[j]
                    delta[address] = math.atan2(math.sin(delta[address]), math.cos(delta[address]))
            columns.append(delta/(2*h))
        return np.column_stack(columns)

    def evaluate(self, q, velocity, gravity=(0., 0., -9.81), armature=0.):
        model, data = self.model, self.data
        joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, 'crank0')
        model.dof_armature[model.jnt_dofadr[joint]] = armature
        model.opt.gravity[:] = gravity
        tangent = self.tangent(q)
        data.qpos[:] = self.position(q)
        data.qvel[:] = tangent @ velocity
        mujoco.mj_forward(model, data)
        full = np.zeros((model.nv, model.nv))
        mujoco.mj_fullM(model, data, full)
        # q_native'' = T q_reduced'' + dT/dt q_reduced'.
        h = 3e-5
        mapping_acceleration = (self.tangent(q+h*velocity)-self.tangent(q-h*velocity)) @ velocity/(2*h)
        bias_and_gravity = tangent.T @ (data.qfrc_bias + full @ mapping_acceleration)
        potential = float(-np.sum(model.body_mass[:, None]*data.xipos*model.opt.gravity))
        center = np.sum(model.body_mass[:, None]*data.xipos, axis=0)/model.body_mass.sum()
        return {'mass': tangent.T@full@tangent, 'bias_minus_gravity': bias_and_gravity,
                'potential': potential, 'com': center, 'body_positions': data.xpos[1:].copy(),
                'body_rotations': data.xmat[1:].reshape((-1, 3, 3)).copy()}
