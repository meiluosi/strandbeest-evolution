import mujoco

from .registry import drives


class MotorDrive:
    """Crank driven at a prescribed speed by a stiff position servo whose target advances in time.

    While settling the target holds the initial angle (a velocity servo would let the load creep the crank).
    The servo force is the crank torque."""

    def __init__(self, sim) -> None:
        self.aid = mujoco.mj_name2id(sim.model, mujoco.mjtObj.mjOBJ_ACTUATOR, sim.built.actuator)
        self.target = sim.q0
        self.t_drive = 0.0

    def control(self, sim, t: float, driving: bool) -> None:
        sc = sim.scenario
        dt = sim.model.opt.timestep
        if driving:
            ramp = sc.drive.ramp
            f = 1.0 if ramp <= 0 else min(t / ramp, 1.0)
            f = f * f * (3 - 2 * f)  # smooth start-up
            # hinge angle q rises with psi when direction == -1, falls when +1
            self.target += -sc.walker.direction * f * sc.drive.omega * dt
        sim.data.ctrl[self.aid] = self.target

    def torque(self, sim) -> float:
        # force on the hinge coordinate q; flip the sign so positive means driving psi forward
        return float(-sim.scenario.walker.direction * sim.data.actuator_force[self.aid])


@drives.register("motor")
def motor(sim) -> MotorDrive:
    return MotorDrive(sim)
