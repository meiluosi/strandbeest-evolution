from .registry import drives, winds


class MotorDrive:
    """Crank driven at a prescribed speed by a stiff position servo whose target advances in time.

    While settling the target holds the initial angle (a velocity servo would let the load creep the crank).
    The servo force is the crank torque."""

    def __init__(self, sim) -> None:
        self.actuator = sim.info.actuator
        self.target = sim.q0
        self.t_drive = 0.0

    def control(self, sim, t: float, driving: bool) -> None:
        sc = sim.scenario
        dt = sim.backend.timestep
        if driving:
            ramp = sc.drive.ramp
            f = 1.0 if ramp <= 0 else min(t / ramp, 1.0)
            f = f * f * (3 - 2 * f)  # smooth start-up
            # hinge angle q rises with psi when direction == -1, falls when +1
            self.target += -sc.walker.direction * f * sc.drive.omega * dt
        sim.backend.set_actuator_target(self.actuator, self.target)

    def torque(self, sim) -> float:
        # force on the hinge coordinate q; flip the sign so positive means driving psi forward
        return float(-sim.scenario.walker.direction * sim.backend.actuator_force(self.actuator))


class SailDrive:
    """A drag sail turning the crank through a gear, in the scenario's wind. The walker starts (or does not) by itself.

    Sail torque at the crank, as in packages/core:  tau = gear * 0.5 * rho * Cd * A * r * (wind - omega*gear*r)^2  (0 if the
    bracket is negative). Rotor inertia, viscous damping and Coulomb friction act at the crank. While settling the crank is
    held by the position servo; at the start of driving the servo is switched off. Wind acts only on the sail, not on the body.
    """

    def __init__(self, sim) -> None:
        sc = sim.scenario
        self.actuator = sim.info.actuator
        self.joint = sim.info.crank_joint
        self.target = sim.q0
        self.released = False
        sim.backend.configure_joint(self.joint, armature=sc.drive.rotor_inertia, damping=sc.drive.crank_damping, frictionloss=sc.drive.crank_friction)
        self.wind = winds.get(sc.wind.kind)(sc.wind)
        self.tau = 0.0

    def control(self, sim, t: float, driving: bool) -> None:
        b = sim.backend
        if not driving:
            b.set_actuator_target(self.actuator, self.target)
            return
        if not self.released:
            b.release_actuator(self.actuator)
            self.released = True
        sc = sim.scenario
        d = sc.drive
        omega = -sc.walker.direction * b.joint_velocity(self.joint)  # crank speed in the walking direction
        rel = self.wind(t) - max(omega, 0.0) * d.sail_gear * d.sail_radius
        self.tau = d.sail_gear * 0.5 * sc.environment.air_density * d.sail_drag_coeff * d.sail_area * d.sail_radius * rel * rel if rel > 0 else 0.0
        b.apply_joint_torque(self.joint, -sc.walker.direction * self.tau)

    def torque(self, sim) -> float:
        return self.tau


@drives.register("motor")
def motor(sim) -> MotorDrive:
    return MotorDrive(sim)


@drives.register("sail")
def sail(sim) -> SailDrive:
    return SailDrive(sim)
