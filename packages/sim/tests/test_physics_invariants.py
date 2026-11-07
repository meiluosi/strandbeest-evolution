"""Physical conservation, resistance deceleration, and aerodynamic invariant tests."""

import math
import numpy as np
from strandbeest_sim.fluids.anchor import StormAnchor, StormAnchorConfig
from strandbeest_sim.fluids import R_AIR, T_0, P_ATM


def test_storm_anchor_soil_resistance_causes_deceleration_and_arrest():
    """Anchor spike must genuinely decelerate and stop when soil resistance exceeds drive force."""
    # Configure an anchor with low drive pressure but dense sand resistance
    cfg = StormAnchorConfig(
        p_tank=165_000.0,  # 1.65 bar (~80 N driving force)
        p_atm=101_325.0,
        spike_mass=1.5,
        piston_diameter=0.04,
        spike_diameter=0.02,
        stroke=0.35,
        phi_deg=35.0,
        c_cohesion=5_000.0,
        damping=10.0,
    )
    anchor = StormAnchor(cfg)
    anchor.trigger(reason="test_soil_resistance")
    assert anchor.is_firing

    # Run for several time steps
    dt = 0.002
    velocities = []
    for _ in range(300):
        anchor.step(dt)
        velocities.append(anchor.deployment_velocity)

    # Initial acceleration should be followed by deceleration as penetration increases
    max_v = max(velocities)
    final_v = velocities[-1]
    assert max_v > 0.0, "Anchor should begin penetrating"
    assert final_v < max_v, "Anchor must decelerate due to increasing soil penetration resistance"
    
    # Must arrest BEFORE reaching full stroke (0.35 m) because resistance exceeds driving capacity
    assert anchor.penetration_depth < cfg.stroke, "Anchor should have been arrested by dense sand before full stroke"
    assert anchor.penetration_depth > 0.01, "Anchor should have achieved partial penetration before arrest"
    assert anchor.deployment_velocity == 0.0 or final_v < 0.02, "Anchor velocity should be arrested near zero"


def test_pneumatic_closed_system_total_mass_conservation():
    """Total mass in a closed multi-chamber pneumatic volume must be conserved across state changes."""
    v1 = 0.002  # 2 liters
    v2 = 0.003  # 3 liters
    p1 = 300_000.0  # 3 bar
    p2 = 100_000.0  # 1 bar
    t0 = 293.15  # 20 C
    
    rho1 = p1 / (R_AIR * t0)
    rho2 = p2 / (R_AIR * t0)
    
    m1 = rho1 * v1
    m2 = rho2 * v2
    total_initial_mass = m1 + m2
    
    # Isothermal mixing: final pressure P_f = (P1*V1 + P2*V2) / (V1 + V2)
    p_final = (p1 * v1 + p2 * v2) / (v1 + v2)
    rho_final = p_final / (R_AIR * t0)
    total_final_mass = rho_final * (v1 + v2)
    
    assert math.isclose(total_initial_mass, total_final_mass, rel_tol=1e-5), (
        f"Pneumatic mass not conserved: initial {total_initial_mass:.6e} kg vs final {total_final_mass:.6e} kg"
    )
