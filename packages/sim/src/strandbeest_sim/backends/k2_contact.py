"""Coupled planar contact impulses with active-mode corrections.

Projected sweeps identify a local Coulomb mode. A simultaneous linear solve
corrects that mode when it improves the projection residual. The iteration
budget is explicit; an unconverged result must not be silently integrated.
"""
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ContactSolution:
    velocity: np.ndarray
    normal: np.ndarray
    tangent: np.ndarray
    motor: float
    iterations: int
    converged: bool
    normal_error: float
    tangent_error: float
    motor_error: float


class ContactConvergenceError(RuntimeError):
    def __init__(self, solution, system):
        self.solution, self.system = solution, system
        super().__init__(f'K2 contact solve exhausted {solution.iterations} iterations: '
                         f'normal residual {solution.normal_error:.6g} m/s, '
                         f'tangent residual {solution.tangent_error:.6g} m/s, '
                         f'motor residual {solution.motor_error:.6g} N m s')


def solve_contacts(*, free_velocity, inverse_mass, normals, tangents, targets,
                   normal_compliance, friction, motor_enabled, motor_desired,
                   motor_damping_dt, motor_limit, iterations):
    normals = np.asarray(normals, dtype=float).reshape(-1, 4)
    tangents = np.asarray(tangents, dtype=float).reshape(-1, 4)
    targets, compliance = np.asarray(targets), np.asarray(normal_compliance)
    count = len(normals)
    jacobian = np.empty((2*count+1, 4))
    jacobian[:-1:2], jacobian[1:-1:2] = normals, tangents
    jacobian[-1] = [0., 0., 0., 1.]
    response = inverse_mass @ jacobian.T
    contact_matrix = jacobian @ response
    diagonal = np.diag(contact_matrix).copy()
    diagonal[:-1:2] += compliance
    if np.any(diagonal <= 0) or not np.isfinite(diagonal).all():
        raise ValueError('K2 contact response must have a finite positive diagonal')
    p = np.zeros(2*count+1)
    velocity = np.asarray(free_velocity).copy()
    visited, pending = set(), set()
    frontier = deque()
    # Small dense products/solves use a relative roundoff-scale check, with
    # each row scaled in its own physical unit. This is not an m/s tolerance
    # or a way to relax the public energy/penetration/stride audit thresholds.
    roundoff = 128*np.finfo(float).eps

    def evaluate(impulse, v):
        speed = jacobian @ v
        n = impulse[:-1:2]
        t = impulse[1:-1:2]
        normal_trial = n-(speed[:-1:2]-targets+compliance*n)/diagonal[:-1:2]
        tangent_trial = t-speed[1:-1:2]/diagonal[1:-1:2]
        bound = friction*np.maximum(0., n)
        demand = motor_desired-motor_damping_dt*v[3] if motor_enabled else 0.
        clipped = np.clip(demand, -motor_limit, motor_limit) if motor_enabled and motor_limit is not None else demand
        delta = np.empty_like(impulse)
        delta[:-1:2] = n-np.maximum(0., normal_trial)
        delta[1:-1:2] = t-np.clip(tangent_trial, -bound, bound)
        motor_error = abs(impulse[-1]-clipped)
        delta[-1] = (impulse[-1]-clipped)/(1+motor_damping_dt*diagonal[-1]) if motor_enabled else impulse[-1]
        normal_error = diagonal[:-1:2]*np.abs(delta[:-1:2])
        tangent_error = diagonal[1:-1:2]*np.abs(delta[1:-1:2])
        magnitude = np.abs(free_velocity)+np.abs(response) @ np.abs(impulse)
        scales = np.abs(jacobian) @ magnitude
        normal_bound = roundoff*(scales[:-1:2]+np.abs(targets)+compliance*np.abs(n)+diagonal[:-1:2]*np.abs(n))
        tangent_bound = roundoff*(scales[1:-1:2]+diagonal[1:-1:2]*(np.abs(t)+bound))
        motor_bound = roundoff*(abs(impulse[-1])+abs(motor_desired)+motor_damping_dt*magnitude[3])
        good = (np.all(normal_error <= normal_bound) and np.all(tangent_error <= tangent_bound)
                and motor_error <= motor_bound)
        merit = float(np.sum(diagonal*delta**2))
        return bool(good), merit, normal_trial, tangent_trial, demand, (
            float(np.max(normal_error, initial=0.)), float(np.max(tangent_error, initial=0.)), float(motor_error))

    def result(done, used, errors):
        return ContactSolution(velocity.copy(), p[:-1:2].copy(), p[1:-1:2].copy(), float(p[-1]),
                               used, done, *errors)

    def mode_for(impulse, evaluated):
        normal_trial, tangent_trial, demand = evaluated[2:5]
        mode = []
        for i in range(count):
            bound = friction*max(0., impulse[2*i])
            mode.append(0 if normal_trial[i] <= 0 else 2 if tangent_trial[i] < -bound
                        else 3 if tangent_trial[i] > bound else 1)
        mode.append(0 if not motor_enabled or motor_limit is None or abs(demand) <= motor_limit
                    else 1 if demand > 0 else 2)
        return tuple(mode)

    def enqueue(mode, first=False):
        if mode in visited:
            return
        if mode in pending:
            if not first:
                return
            frontier.remove(mode)
        pending.add(mode)
        (frontier.appendleft if first else frontier.append)(mode)

    for iteration in range(iterations if count else 1):
        # Feasible projected sweep, including the actual bounded motor law.
        for i in range(count):
            k = 2*i
            normal = max(0., p[k]+(targets[i]-normals[i] @ velocity-compliance[i]*p[k])/diagonal[k])
            velocity += response[:, k]*(normal-p[k])
            p[k] = normal
            bound = friction*normal
            tangent = np.clip(p[k+1]-tangents[i] @ velocity/diagonal[k+1], -bound, bound)
            velocity += response[:, k+1]*(tangent-p[k+1])
            p[k+1] = tangent
        if motor_enabled:
            motor = p[-1]+(motor_desired-p[-1]-motor_damping_dt*velocity[3])/(1+motor_damping_dt*diagonal[-1])
            if motor_limit is not None:
                motor = np.clip(motor, -motor_limit, motor_limit)
            velocity += response[:, -1]*(motor-p[-1])
            p[-1] = motor
        state = evaluate(p, velocity)
        if state[0]:
            return result(True, iteration+1, state[-1])

        # Correct the inferred mode, then pivot to neighboring modes if local
        # mode inference cycles. At most one dense correction per iteration.
        # Preserve the current null-space impulse in redundant contact systems.
        _, merit, normal_trial, tangent_trial, demand, _ = state
        inferred = mode_for(p, state)
        if inferred not in visited:
            selected = inferred
            if selected in pending:
                frontier.remove(selected)
                pending.remove(selected)
        elif frontier:
            selected = frontier.popleft()
            pending.remove(selected)
        else:
            selected = inferred
        visited.add(selected)
        a, rhs = np.zeros_like(contact_matrix), np.zeros_like(p)
        for i in range(count):
            k = 2*i
            if selected[i] == 0:
                a[k, k] = a[k+1, k+1] = 1.
                continue
            a[k] = contact_matrix[k]
            a[k, k] += compliance[i]
            rhs[k] = targets[i]-normals[i] @ free_velocity
            if selected[i] == 1:
                a[k+1] = contact_matrix[k+1]
                rhs[k+1] = -tangents[i] @ free_velocity
            else:
                a[k+1, k+1] = 1.
                a[k+1, k] = friction if selected[i] == 2 else -friction
        a[-1, -1] = 1.
        if motor_enabled:
            if selected[-1] != 0:
                rhs[-1] = motor_limit if selected[-1] == 1 else -motor_limit
            else:
                a[-1] += motor_damping_dt*contact_matrix[-1]
                rhs[-1] = motor_desired-motor_damping_dt*free_velocity[3]
        scale = np.maximum(np.max(np.abs(a), axis=1), np.finfo(float).tiny)
        correction = np.linalg.lstsq(a/scale[:, None], (rhs-a @ p)/scale, rcond=None)[0]
        candidate = p+correction
        unprojected = evaluate(candidate, free_velocity+response @ candidate)
        enqueue(mode_for(candidate, unprojected), first=True)
        for index in range(count+1):
            choices = range(4) if index < count else range(3 if motor_enabled and motor_limit is not None else 1)
            for choice in choices:
                adjacent = list(selected)
                adjacent[index] = choice
                enqueue(tuple(adjacent))
        candidate[:-1:2] = np.maximum(0., candidate[:-1:2])
        bounds = friction*candidate[:-1:2]
        candidate[1:-1:2] = np.clip(candidate[1:-1:2], -bounds, bounds)
        if not motor_enabled:
            candidate[-1] = 0.
        elif motor_limit is not None:
            candidate[-1] = np.clip(candidate[-1], -motor_limit, motor_limit)
        candidate_velocity = free_velocity+response @ candidate
        checked = evaluate(candidate, candidate_velocity)
        if checked[0] or checked[1] < merit:
            p, velocity = candidate, candidate_velocity
            state = checked
            if state[0]:
                return result(True, iteration+1, state[-1])
    return result(False, iterations, state[-1])
