"""Comprehensive unit and physical tests for 1D compressible gas network,

PET bottle storage, and crank reciprocating pump models.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from strandbeest_sim.fluids import (
    CP_AIR,
    CV_AIR,
    DEFAULT_CRITICAL_PRESSURE_RATIO,
    DEFAULT_POLYTROPIC_EXPONENT,
    GAMMA_AIR,
    P_ATM,
    R_AIR,
    RHO_0,
    T_0,
    CheckValve,
    CrankReciprocatingPump,
    FluidNetwork,
    FluidNode,
    Orifice,
    PETBottleBank,
    iso6358_mass_flow,
    iso6358_mass_flow_derivative_p2,
    iso6358_mass_flow_derivative_ratio,
)


# ==============================================================================
# 1. Fundamental Constants and Properties
# ==============================================================================


def test_air_thermodynamic_relations() -> None:
    """Verify ideal gas relations between R, gamma, cp, and cv."""
    # R = cp - cv
    assert math.isclose(CP_AIR - CV_AIR, R_AIR, rel_tol=1e-6)
    # gamma = cp / cv
    assert math.isclose(CP_AIR / CV_AIR, GAMMA_AIR, rel_tol=1e-6)
    # R = 287.05 J/(kg*K)
    assert math.isclose(R_AIR, 287.05, abs_tol=1e-4)


# ==============================================================================
# 2. ISO 6358 Orifice Flow Model & Sonic Choke Continuity
# ==============================================================================


def test_iso6358_bidirectional_symmetry() -> None:
    """Verify ISO 6358 flow is antisymmetric with respect to port exchange."""
    p1 = 300_000.0
    p2 = 150_000.0
    c = 1e-7

    flow_12 = iso6358_mass_flow(p1, p2, conductance=c)
    flow_21 = iso6358_mass_flow(p2, p1, conductance=c)

    assert flow_12 > 0.0
    assert flow_21 < 0.0
    assert math.isclose(flow_12, -flow_21, rel_tol=1e-12)


def test_iso6358_zero_pressure_differential() -> None:
    """Verify flow is identically zero when port pressures are equal."""
    p = 250_000.0
    assert iso6358_mass_flow(p, p) == 0.0


def test_sonic_choke_transition_continuity() -> None:
    """Verify continuity of mass flow rate across sonic choke threshold r = b."""
    p1 = 400_000.0
    b = DEFAULT_CRITICAL_PRESSURE_RATIO
    c = 1e-7

    # Choked region (r <= b)
    p2_choked = (b - 0.01) * p1
    # Subsonic region (r > b)
    p2_subsonic = (b + 0.01) * p1

    flow_choked = iso6358_mass_flow(p1, p2_choked, conductance=c)
    flow_critical = iso6358_mass_flow(p1, b * p1, conductance=c)
    flow_subsonic = iso6358_mass_flow(p1, p2_subsonic, conductance=c)

    # In choked region, flow is independent of downstream pressure
    flow_deep_choked = iso6358_mass_flow(p1, 0.1 * p1, conductance=c)
    assert math.isclose(flow_deep_choked, flow_critical, rel_tol=1e-12)
    assert math.isclose(flow_choked, flow_critical, rel_tol=1e-12)

    # Continuity: as r -> b+, flow matches critical choked value
    eps = 1e-7
    flow_above = iso6358_mass_flow(p1, (b + eps) * p1, conductance=c)
    assert math.isclose(flow_above, flow_critical, rel_tol=1e-6)


def test_sonic_choke_derivative_continuity() -> None:
    """Verify that d(m_dot)/dr is continuous across the sonic choke threshold r = b.

    Left derivative: d(m_dot)/dr = 0 for r <= b.
    Right derivative limit: lim_{r -> b+} d(m_dot)/dr = 0.
    Both analytical and numerical derivatives must agree and be continuous across r = b.
    """
    p1 = 500_000.0
    b = DEFAULT_CRITICAL_PRESSURE_RATIO
    c = 1e-7

    # Analytical derivative at r < b is 0.0
    d_left = iso6358_mass_flow_derivative_ratio(b - 1e-5, p1, conductance=c, b=b)
    assert d_left == 0.0

    # Analytical derivative exactly at r = b is 0.0
    d_at_b = iso6358_mass_flow_derivative_ratio(b, p1, conductance=c, b=b)
    assert d_at_b == 0.0

    # Verify analytical derivative matches centered finite difference at b + eps
    for eps in [1e-3, 1e-4, 1e-5]:
        d_right = iso6358_mass_flow_derivative_ratio(b + eps, p1, conductance=c, b=b)
        delta = 1e-7
        m_plus = iso6358_mass_flow(p1, (b + eps + delta) * p1, conductance=c, b=b)
        m_minus = iso6358_mass_flow(p1, (b + eps - delta) * p1, conductance=c, b=b)
        num_centered = (m_plus - m_minus) / (2.0 * delta)
        assert math.isclose(d_right, num_centered, rel_tol=1e-3, abs_tol=1e-6)

    # Continuity of derivative: lim_{eps -> 0+} d_right(b + eps) = 0.0
    d_near_b = iso6358_mass_flow_derivative_ratio(b + 1e-8, p1, conductance=c, b=b)
    assert abs(d_near_b) < 1e-6

    # Forward difference from b also converges to 0 (matching left slope 0)
    for eps_test in [1e-4, 1e-5, 1e-6]:
        m_b = iso6358_mass_flow(p1, b * p1, conductance=c, b=b)
        m_b_plus = iso6358_mass_flow(p1, (b + eps_test) * p1, conductance=c, b=b)
        forward_slope = (m_b_plus - m_b) / eps_test
        assert abs(forward_slope) < 1e-3


def test_iso6358_flow_monotonicity() -> None:
    """Verify that flow rate decreases monotonically as downstream pressure rises."""
    p1 = 300_000.0
    c = 1e-7
    r_vals = np.linspace(0.1, 0.99, 100)
    flows = [iso6358_mass_flow(p1, r * p1, conductance=c) for r in r_vals]

    # Flow should be non-increasing everywhere
    for i in range(1, len(flows)):
        assert flows[i] <= flows[i - 1] + 1e-15


# ==============================================================================
# 3. Closed-System Mass Conservation Tests
# ==============================================================================


def test_closed_system_mass_conservation_two_chambers_isothermal() -> None:
    """Test closed-system mass conservation between two chambers with relative error < 10^-7."""
    net = FluidNetwork(track_mass=True)

    v1 = 0.015  # 15 L
    v2 = 0.035  # 35 L
    p1_0 = 600_000.0
    p2_0 = 100_000.0

    net.add_node(FluidNode("ch1", pressure=p1_0, volume=v1, n=1.0, is_fixed_temperature=True))
    net.add_node(FluidNode("ch2", pressure=p2_0, volume=v2, n=1.0, is_fixed_temperature=True))
    net.add_element(Orifice("orifice", "ch1", "ch2", conductance=2e-7))

    res = net.simulate(t_span=(0.0, 5.0), dt=1e-4)

    # 1. Verify mass conservation relative error is strictly < 10^-7
    assert res.mass_conservation_relative_error < 1e-7

    # 2. Verify theoretical analytical equilibrium pressure
    # For isothermal mixing: p_eq = (p1*V1 + p2*V2) / (V1 + V2)
    p_eq_expected = (p1_0 * v1 + p2_0 * v2) / (v1 + v2)
    assert math.isclose(res.pressures["ch1"][-1], p_eq_expected, rel_tol=1e-4)
    assert math.isclose(res.pressures["ch2"][-1], p_eq_expected, rel_tol=1e-4)


def test_closed_system_mass_conservation_polytropic_three_chambers() -> None:
    """Test mass conservation in a 3-chamber polytropic network (relative error < 10^-7)."""
    net = FluidNetwork(track_mass=True)

    net.add_node(FluidNode("tank_a", pressure=500_000.0, volume=0.01, n=1.25))
    net.add_node(FluidNode("tank_b", pressure=200_000.0, volume=0.02, n=1.25))
    net.add_node(FluidNode("tank_c", pressure=100_000.0, volume=0.03, n=1.25))

    net.add_element(Orifice("pipe_ab", "tank_a", "tank_b", conductance=1e-7))
    net.add_element(Orifice("pipe_bc", "tank_b", "tank_c", conductance=1e-7))

    res = net.simulate(t_span=(0.0, 4.0), dt=1e-4)

    # Relative mass error must be < 10^-7
    assert res.mass_conservation_relative_error < 1e-7

    # Final pressures must tend toward equalization
    assert abs(res.pressures["tank_a"][-1] - res.pressures["tank_c"][-1]) < 50_000.0


# ==============================================================================
# 4. Check Valve Behavior & Unidirectional Sealing
# ==============================================================================


def test_check_valve_sealing_and_cracking() -> None:
    """Verify check valve opens only when forward delta_p exceeds cracking pressure."""
    p_crack = 3000.0
    valve = CheckValve("chk", "inlet", "outlet", conductance=1e-7, cracking_pressure=p_crack)

    # 1. Reverse pressure: p_a < p_b -> strictly zero flow
    assert valve.compute_mass_flow(p_a=100_000.0, p_b=200_000.0, T_a=T_0, T_b=T_0) == 0.0

    # 2. Forward pressure below cracking: p_a - p_b < p_crack -> zero flow
    assert valve.compute_mass_flow(p_a=102_000.0, p_b=100_000.0, T_a=T_0, T_b=T_0) == 0.0
    assert not valve.is_open(p_a=102_000.0, p_b=100_000.0)

    # 3. Forward pressure exactly at cracking -> zero flow
    assert valve.compute_mass_flow(p_a=100_000.0 + p_crack, p_b=100_000.0, T_a=T_0, T_b=T_0) == 0.0

    # 4. Forward pressure above cracking -> positive forward flow
    flow = valve.compute_mass_flow(p_a=100_000.0 + p_crack + 10_000.0, p_b=100_000.0, T_a=T_0, T_b=T_0)
    assert flow > 0.0
    assert valve.is_open(p_a=100_000.0 + p_crack + 10_000.0, p_b=100_000.0)


# ==============================================================================
# 5. PET Bottle Storage Bank Properties & Safety
# ==============================================================================


def test_pet_bottle_bank_properties() -> None:
    """Verify PET bottle bank volume, safety limits, and stored exergy."""
    bank = PETBottleBank(num_bottles=4, volume_per_bottle=0.002)

    # Total volume: 4 * 2.0 L = 8.0 L = 0.008 m^3
    assert math.isclose(bank.total_volume, 0.008, rel_tol=1e-9)

    # Pressure limits
    assert not bank.is_overpressure(500_000.0)
    assert bank.is_overpressure(650_000.0)  # > 0.6 MPa
    assert not bank.is_burst(750_000.0)
    assert bank.is_burst(800_000.0)  # >= 0.8 MPa
    assert bank.is_burst(900_000.0)

    # Safety factor at 400 kPa: 800 / 400 = 2.0
    assert math.isclose(bank.safety_factor(400_000.0), 2.0, rel_tol=1e-6)

    # Stored exergy: 0 at atmospheric pressure, strictly positive at 5 bar
    assert bank.stored_exergy(P_ATM) == 0.0
    exergy_5bar = bank.stored_exergy(500_000.0)
    assert exergy_5bar > 1000.0  # Over 1 kJ stored pneumatic energy

    # Heat exchange with ambient
    assert bank.heat_exchange(T_0) == 0.0
    assert bank.heat_exchange(T_0 + 10.0) < 0.0  # Losing heat when hot
    assert bank.heat_exchange(T_0 - 10.0) > 0.0  # Absorbing heat when cold


# ==============================================================================
# 6. Reciprocating Piston Pump Kinematics & Reaction Torque
# ==============================================================================


def test_pump_kinematics_and_torque() -> None:
    """Verify displacement, volume variation, and reaction torque profile."""
    pump = CrankReciprocatingPump(crank_radius=0.025, piston_diameter=0.030)

    # Bottom Dead Center (psi = 0)
    assert math.isclose(pump.piston_displacement(0.0), 0.0, abs_tol=1e-12)
    assert math.isclose(pump.cylinder_volume(0.0), pump.max_volume, rel_tol=1e-9)
    assert math.isclose(pump.reaction_torque(0.0, p_cyl=200_000.0), 0.0, abs_tol=1e-12)

    # Top Dead Center (psi = pi)
    assert math.isclose(pump.piston_displacement(math.pi), 2 * pump.crank_radius, rel_tol=1e-9)
    assert math.isclose(pump.cylinder_volume(math.pi), pump.dead_volume, rel_tol=1e-9)
    assert math.isclose(pump.reaction_torque(math.pi, p_cyl=200_000.0), 0.0, abs_tol=1e-12)

    # Mid-stroke compression (psi = pi / 2): sin(psi) = 1 -> positive resisting torque
    tau_mid = pump.reaction_torque(math.pi / 2, p_cyl=200_000.0, p_atm=P_ATM)
    assert tau_mid > 0.0
    expected_tau = (200_000.0 - P_ATM) * pump.piston_area * pump.crank_radius
    assert math.isclose(tau_mid, expected_tau, rel_tol=1e-9)


# ==============================================================================
# 7. Multi-Cycle Crank Pump Charging & Energy Conservation Test
# ==============================================================================


def test_multi_cycle_crank_pump_charging() -> None:
    """Verify multi-cycle pump charging:

    1. Bottle pressure rises monotonically cycle-by-cycle.
    2. Dual check valves open and close during appropriate stroke phases.
    3. Mechanical crank work matches gas p-V work (energy conservation).
    4. Reaction torque integrates to strictly positive compression work.
    """
    bank = PETBottleBank(num_bottles=4, volume_per_bottle=0.002)
    pump = CrankReciprocatingPump(
        crank_radius=0.025,
        piston_diameter=0.030,
        cracking_pressure=2000.0,
        inlet_conductance=2e-8,
        outlet_conductance=2e-8,
    )

    num_cycles = 4
    res = pump.simulate_charging(
        bottle_bank=bank,
        crank_speed_rpm=60.0,
        num_cycles=num_cycles,
        dt=1e-4,
    )

    # 1. Monotonic bottle pressure rise across cycles
    assert res.is_monotonically_increasing_bottle_pressure
    assert res.pressure_rise > 1000.0  # Noticeable pressure increase
    assert res.mass_pumped > 0.0  # Mass added to storage

    # 2. Check valve operation
    # Inlet valve must have opened during suction
    assert np.any(res.inlet_valve_open)
    # Outlet valve must have opened during discharge
    assert np.any(res.outlet_valve_open)
    # Both valves must be closed during transition phases
    both_closed = (~res.inlet_valve_open) & (~res.outlet_valve_open)
    assert np.sum(both_closed) > 0.5 * len(res.t)

    # 3. Energy conservation:
    # Mechanical work done on pump shaft integral(tau * dpsi) > 0
    assert res.total_crank_work > 0.0
    # Must match gas p-V indicator work integral(-p_cyl * dV) with zero/negligible error
    assert math.isclose(res.total_crank_work, res.total_pv_work, rel_tol=1e-4)
    assert res.work_conservation_error < 1e-4

    # 4. Internal energy gain in the bottle storage
    delta_u_bottle = (res.final_bottle_pressure - res.initial_bottle_pressure) * bank.total_volume / (GAMMA_AIR - 1.0)
    assert delta_u_bottle > 0.0


def test_adiabatic_polytropic_compression_pv_n_constant() -> None:
    """Verify that an isolated cylinder volume undergoing kinematic compression satisfies p * V^n = const."""
    net = FluidNetwork(track_mass=True)

    n = 1.25
    v0 = 0.001
    p0 = 100_000.0

    # Linear volume reduction: V(t) = v0 * (1 - 0.5 * t), dV/dt = -0.5 * v0
    def volume_func(t: float) -> tuple[float, float]:
        v = v0 * (1.0 - 0.5 * t)
        dv_dt = -0.5 * v0
        return v, dv_dt

    node = FluidNode("cylinder", pressure=p0, volume=v0, n=n, volume_func=volume_func)
    net.add_node(node)

    # Simulate from t=0 to t=0.5 (volume drops to 0.75 * v0)
    res = net.simulate(t_span=(0.0, 0.5), dt=1e-4)

    c0 = p0 * (v0**n)
    for p, v in zip(res.pressures["cylinder"], res.volumes["cylinder"]):
        c_t = p * (v**n)
        assert math.isclose(c_t, c0, rel_tol=1e-5)

