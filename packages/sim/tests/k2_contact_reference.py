"""Independent enumeration of planar Coulomb modes for a frozen contact step.

This solves simultaneous equations, not the production sequential iteration.
Multiple feasible velocities or no feasible mode are reported, never hidden.
"""
from itertools import product

import numpy as np


def enumerate_contact_modes(system, atol=1e-9):
    normals = np.asarray(system['normal_jacobians'], dtype=float).reshape(-1, 4)
    tangents = np.asarray(system['tangent_jacobians'], dtype=float).reshape(-1, 4)
    n = len(normals)
    jacobian = np.empty((2*n+1, 4))
    jacobian[:-1:2], jacobian[1:-1:2] = normals, tangents
    jacobian[-1] = [0., 0., 0., 1.]
    response = np.asarray(system['effective_inverse']) @ jacobian.T
    free = np.asarray(system['free_velocity'])
    mu = system['mu']
    target = system['beta']*np.asarray(system['penetrations'])/system['dt']
    limit = system['motor_impulse_limit']
    motor_modes = ('released',) if system['motor_released'] else (
        ('linear',) if limit is None else ('linear', 'upper', 'lower'))
    solutions = []
    for modes in product(('off', 'stick', 'positive', 'negative'), repeat=n):
        for motor in motor_modes:
            a, rhs = np.zeros((2*n+1, 2*n+1)), np.zeros(2*n+1)
            for i, mode in enumerate(modes):
                if mode == 'off':
                    a[2*i, 2*i] = a[2*i+1, 2*i+1] = 1.
                else:
                    a[2*i] = normals[i] @ response
                    rhs[2*i] = target[i]-normals[i] @ free
                    if mode == 'stick':
                        a[2*i+1] = tangents[i] @ response
                        rhs[2*i+1] = -tangents[i] @ free
                    else:
                        a[2*i+1, 2*i+1] = 1.
                        a[2*i+1, 2*i] = mu if mode == 'positive' else -mu
            a[-1, -1] = 1.
            if motor == 'linear':
                a[-1] += system['motor_damping_dt']*response[3]
                rhs[-1] = system['motor_desired_impulse']-system['motor_damping_dt']*free[3]
            elif motor != 'released':
                rhs[-1] = limit if motor == 'upper' else -limit
            # Row scaling controls conditioning without changing equations.
            scale = np.maximum(np.max(np.abs(a), axis=1), np.finfo(float).tiny)
            impulse, _, rank, _ = np.linalg.lstsq(a/scale[:, None], rhs/scale, rcond=None)
            if np.max(np.abs(a @ impulse-rhs)) > atol:
                continue
            velocity = free+response @ impulse
            admissible = True
            for i, mode in enumerate(modes):
                pn, pt = impulse[2*i:2*i+2]
                vn = normals[i] @ velocity-target[i]
                vt = tangents[i] @ velocity
                admissible &= pn >= -atol and abs(pt) <= mu*max(0., pn)+atol
                if mode == 'off':
                    admissible &= vn >= -atol
                elif mode == 'positive':
                    admissible &= vt >= -atol
                elif mode == 'negative':
                    admissible &= vt <= atol
            demanded = system['motor_desired_impulse']-system['motor_damping_dt']*velocity[3]
            if motor == 'linear' and limit is not None:
                admissible &= abs(impulse[-1]) <= limit+atol
            elif motor == 'upper':
                admissible &= demanded >= limit-atol
            elif motor == 'lower':
                admissible &= demanded <= -limit+atol
            if admissible:
                solutions.append({'modes': list(modes), 'motor_mode': motor, 'rank': int(rank),
                                  'impulses': impulse.tolist(), 'velocity': velocity.tolist(),
                                  'linear_equation_max_error': float(np.max(np.abs(a @ impulse-rhs)))})
    return solutions
