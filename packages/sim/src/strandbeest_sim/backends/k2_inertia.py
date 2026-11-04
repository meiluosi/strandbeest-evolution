"""Reduced rigid-body inertia from the declared walker geometry, without a physics engine.

Coordinates are X, Z, counterclockwise torso angle, forward crank angle.
Every capsule and sphere contributes its own translational and rotational
energy. Derivatives come from the same periodic C2 position interpolant.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np

from ..linkage import solve_pose


class PeriodicQuintic:
    def __init__(self, values: np.ndarray):
        self.count = len(values)
        self.step = math.tau / self.count
        shifted = {k: np.roll(values, -k, axis=0) for k in range(-3, 4)}
        h = self.step
        first = sum(w*shifted[k] for k, w in zip(range(-3, 4), [-1, 9, -45, 0, 45, -9, 1])) / (60*h)
        second = sum(w*shifted[k] for k, w in zip(range(-3, 4), [2, -27, 270, -490, 270, -27, 2])) / (180*h*h)
        a, b = values, shifted[1]
        va, vb = h*first, h*np.roll(first, -1, axis=0)
        aa, ab = h*h*second, h*h*np.roll(second, -1, axis=0)
        delta = b-a
        self.coefficients = np.stack([
            a, va, aa/2,
            10*delta-6*va-4*vb-1.5*aa+.5*ab,
            -15*delta+8*va+7*vb+1.5*aa-ab,
            6*delta-3*(va+vb)+.5*(ab-aa),
        ], axis=1)

    def sample(self, angles):
        angles = np.atleast_1d(angles)
        index = (angles % math.tau) / self.step
        i = index.astype(int)
        c = self.coefficients[i % self.count]
        s = (index-i).reshape((-1,)+(1,)*(c.ndim-2))
        value = c[:, 0]+s*(c[:, 1]+s*(c[:, 2]+s*(c[:, 3]+s*(c[:, 4]+s*c[:, 5]))))
        first = (c[:, 1]+s*(2*c[:, 2]+s*(3*c[:, 3]+s*(4*c[:, 4]+s*5*c[:, 5]))))/self.step
        second = (2*c[:, 2]+s*(6*c[:, 3]+s*(12*c[:, 4]+s*20*c[:, 5])))/(self.step*self.step)
        return value, first, second


def capsule_inertia(mass: float, length: float, radius: float) -> float:
    """Uniform solid capsule's transverse central inertia, kg m^2.

    Split its mass by cylinder/hemisphere volume. Each hemisphere centroid is
    3r/8 beyond the cap plane; parallel-axis transfer supplies the cap term.
    This is the shape convention declared by the shared MJCF, not a new
    material-density or hollow-tube assumption.
    """
    caps = mass*(4*radius/3)/(length+4*radius/3)
    cylinder = mass-caps
    return cylinder*(length*length/12+radius*radius/4) + caps*(
        2*radius*radius/5+length*length/4+3*length*radius/8)


def cross(a, b):
    return a[..., 0]*b[..., 1]-a[..., 1]*b[..., 0]


def quarter_turn(a):
    return np.stack((-a[..., 1], a[..., 0]), axis=-1)


@dataclass
class MassSample:
    matrix: np.ndarray
    mass: float
    moment: np.ndarray
    moment_first: np.ndarray
    moment_second: np.ndarray
    pitch_first: float
    cross_first: float
    drive_first: float
    joint_ratios: np.ndarray
    body_positions: np.ndarray
    body_angles: np.ndarray

    def bias(self, velocity):
        phi, psi = velocity[2:]
        linear = -self.moment*phi*phi + 2*quarter_turn(self.moment_first)*phi*psi + self.moment_second*psi*psi
        return np.array([*linear, self.pitch_first*phi*psi+self.cross_first*psi*psi,
                         -.5*self.pitch_first*phi*phi+.5*self.drive_first*psi*psi])

    def gravity(self, acceleration):
        g = np.asarray(acceleration)[[0, 2]]
        return np.array([*(self.mass*g), quarter_turn(self.moment)@g, self.moment_first@g])

    def potential(self, q, acceleration):
        return float(-np.asarray(acceleration)[[0, 2]] @ (self.mass*q[:2]+self.moment))


class WalkerInertia:
    """All declared box/capsule/sphere inertias projected into four coordinates."""
    def __init__(self, spec, cfg, xml: str, poses=None):
        self.direction = cfg.walker.direction
        self.phases = math.tau*np.arange(cfg.walker.legs)/cfg.walker.legs
        self.unit = cfg.walker.unit
        self.spec = spec
        self.point_names = ['G', 'C', *(j.id for j in spec.joints), '__pivot__']
        self.point_index = {name: i for i, name in enumerate(self.point_names)}
        if poses is None:
            poses = [solve_pose(spec, theta) for theta in np.linspace(0, math.tau, 2880, endpoint=False)]
        if any(p is None for p in poses):
            raise ValueError('linkage cannot assemble over the inertia table')
        points = np.array([[*(p[name] for name in self.point_names[:-1]), spec.pivot] for p in poses])*self.unit
        self.points = PeriodicQuintic(points)

        tree = ET.fromstring(xml)
        torso = tree.find(".//body[@name='torso']")
        torso_geom = torso.find("geom[@type='box']")
        self.torso_mass = float(torso_geom.attrib['mass'])
        half = np.fromstring(torso_geom.attrib['size'], sep=' ')
        self.torso_inertia = self.torso_mass*(half[0]**2+half[2]**2)/3
        bodies = list(torso.iter('body'))
        self.body_names = tuple(b.attrib['name'] for b in bodies)
        parent = {child.attrib['name']: body.attrib['name'] for body in bodies for child in body.findall('body')}
        self.parent_indices = np.array([self.body_names.index(parent[b.attrib['name']]) for b in bodies[1:]])
        self.legs, self.starts, self.ends, self.reference_angles, self.lateral = [], [], [], [], []
        geom_body, masses, inertias, offsets = [], [], [], []
        joint_friction, joint_damping = [], []
        for index, body in enumerate(bodies[1:]):
            name = body.attrib['name']
            crank = re.fullmatch(r'crank(\d+)', name)
            bar = re.fullmatch(r'bar(\d+)_(.+)([01])', name)
            if crank:
                leg, start, end = int(crank[1]), '__pivot__', 'C'
            elif bar:
                leg = int(bar[1])
                joint = next(j for j in spec.joints if j.id == bar[2])
                start, end = joint.centers[int(bar[3])], joint.id
            else:
                raise ValueError(f'unsupported K2 moving body {name}')
            pose = solve_pose(spec, self.phases[leg])
            p_start = np.asarray(spec.pivot if start == '__pivot__' else pose[start])
            vector = np.asarray(pose[end])-p_start
            beta = math.atan2(vector[1], vector[0])
            rotation_back = np.array([[math.cos(beta), math.sin(beta)], [-math.sin(beta), math.cos(beta)]])
            self.legs.append(leg)
            self.starts.append(self.point_index[start])
            self.ends.append(self.point_index[end])
            self.reference_angles.append(beta)
            self.lateral.append((leg-(cfg.walker.legs-1)/2)*cfg.walker.lateral_spacing)
            joint = body.find('joint')
            joint_friction.append(float(joint.get('frictionloss', '0')))
            joint_damping.append(float(joint.get('damping', '0')))
            for geom in body.findall('geom'):
                mass = float(geom.attrib['mass'])
                radius = float(geom.attrib['size'])
                if geom.attrib['type'] == 'capsule':
                    endpoints = np.fromstring(geom.attrib['fromto'], sep=' ').reshape(2, 3)
                    length = float(np.linalg.norm(endpoints[1]-endpoints[0]))
                    center = endpoints.mean(axis=0)[[0, 2]]
                    inertia = capsule_inertia(mass, length, radius)
                elif geom.attrib['type'] == 'sphere':
                    center = np.fromstring(geom.attrib['pos'], sep=' ')[[0, 2]]
                    inertia = .4*mass*radius*radius
                else:
                    raise ValueError('K2 inertia requires the declared capsules and spheres')
                geom_body.append(index)
                masses.append(mass)
                inertias.append(inertia)
                offsets.append(rotation_back @ center)
        self.legs = np.asarray(self.legs)
        self.starts, self.ends = np.asarray(self.starts), np.asarray(self.ends)
        self.reference_angles = np.asarray(self.reference_angles)
        self.lateral = np.asarray(self.lateral)
        self.geom_body = np.asarray(geom_body)
        self.masses, self.inertias = np.asarray(masses), np.asarray(inertias)
        self.offsets = np.asarray(offsets)
        self.joint_friction, self.joint_damping = np.asarray(joint_friction), np.asarray(joint_damping)
        self.mass = self.torso_mass+float(self.masses.sum())

    def sample(self, q, armature=0.) -> MassSample:
        value, first, second = self.points.sample(self.phases+self.direction*q[3])
        first *= self.direction
        start = value[self.legs, self.starts]
        start_first = first[self.legs, self.starts]
        start_second = second[self.legs, self.starts]
        vector = value[self.legs, self.ends]-start
        v1 = first[self.legs, self.ends]-start_first
        v2 = second[self.legs, self.ends]-start_second
        length = np.sqrt(np.sum(vector*vector, axis=1))
        unit = vector/length[:, None]
        length_first = np.sum(unit*v1, axis=1)
        unit_first = (v1-unit*length_first[:, None])/length[:, None]
        length_second = np.sum(unit_first*v1+unit*v2, axis=1)
        unit_second = (v2-unit*length_second[:, None]-2*unit_first*length_first[:, None])/length[:, None]
        beta_first = cross(vector, v1)/(length*length)
        beta_second = (cross(vector, v2)-2*beta_first*np.sum(vector*v1, axis=1))/(length*length)

        centers = []
        for origin, axis in ((start, unit), (start_first, unit_first), (start_second, unit_second)):
            selected = axis[self.geom_body]
            centers.append(origin[self.geom_body]+selected*self.offsets[:, :1]+quarter_turn(selected)*self.offsets[:, 1:])
        u, u1, u2 = centers
        b1, b2 = beta_first[self.geom_body], beta_second[self.geom_body]
        mass = self.masses[:, None]
        moment = np.sum(mass*u, axis=0)
        moment1 = np.sum(mass*u1, axis=0)
        moment2 = np.sum(mass*u2, axis=0)
        pitch = self.torso_inertia+float(np.sum(mass*u*u)+self.inertias.sum())
        mixed = float(np.sum(self.masses*cross(u, u1)+self.inertias*b1))
        drive = float(np.sum(mass*u1*u1)+np.sum(self.inertias*b1*b1))+armature
        pitch1 = float(2*np.sum(mass*u*u1))
        mixed1 = float(np.sum(self.masses*cross(u, u2)+self.inertias*b2))
        drive1 = float(2*np.sum(mass*u1*u2)+2*np.sum(self.inertias*b1*b2))

        c, s = math.cos(q[2]), math.sin(q[2])
        rotation = np.array([[c, -s], [s, c]])
        moment, moment1, moment2 = rotation@moment, rotation@moment1, rotation@moment2
        matrix = np.zeros((4, 4))
        matrix[0, 0] = matrix[1, 1] = self.mass
        matrix[:2, 2] = matrix[2, :2] = quarter_turn(moment)
        matrix[:2, 3] = matrix[3, :2] = moment1
        matrix[2, 2], matrix[2, 3], matrix[3, 2], matrix[3, 3] = pitch, mixed, mixed, drive
        body_positions = np.zeros((len(self.body_names), 3))
        body_positions[:, [0, 2]] = q[:2]
        body_positions[1:, [0, 2]] += start @ rotation.T
        body_positions[1:, 1] = self.lateral
        body_angles = np.r_[0., np.arctan2(vector[:, 1], vector[:, 0])-self.reference_angles]+q[2]
        angular = np.r_[0., beta_first]
        ratios = beta_first-angular[self.parent_indices]
        return MassSample(matrix, self.mass, moment, moment1, moment2, pitch1, mixed1, drive1,
                          ratios, body_positions, body_angles)
