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

    # Mid-stroke compression resists a positive crank rotation.
    tau_mid = pump.reaction_torque(math.pi / 2, p_cyl=200_000.0, p_atm=P_ATM)
    assert tau_mid < 0.0
    expected_tau = -(200_000.0 - P_ATM) * pump.piston_area * pump.crank_radius
    assert math.isclose(tau_mid, expected_tau, rel_tol=1e-9)


# ==============================================================================
# 7. Multi-Cycle Crank Pump Charging & Energy Conservation Test
# ==============================================================================


def test_multi_cycle_crank_pump_charging() -> None:
    """Verify multi-cycle pump charging:

    1. Bottle pressure rises monotonically cycle-by-cycle.
    2. Dual check valves open and close during appropriate stroke phases.
    3. Mechanical crank work matches gauge-pressure p-V work (kinematic identity).
    4. Negative reaction torque integrates to positive input work.
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

    # 3. Kinematic work identity; the gas first law is checked separately.
    # Mechanical work done on pump shaft integral(-tau_pump * dpsi) > 0
    assert res.total_crank_work > 0.0
    # Must match gas p-V indicator work integral(-p_cyl * dV) with zero/negligible error
    assert math.isclose(res.total_crank_work, res.total_pv_work, rel_tol=1e-4)
    assert res.work_conservation_error < 1e-4

    # 4. Internal energy gain in the bottle storage
    delta_u_bottle = (res.final_bottle_pressure - res.initial_bottle_pressure) * bank.total_volume / (GAMMA_AIR - 1.0)
    assert delta_u_bottle > 0.0


def test_empirical_polytropic_compression_pv_n_constant() -> None:
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


def test_extreme_pressure_burst_limit_charging() -> None:
    """Stress test crank pump charging near PET burst pressure limit (750 - 800 kPa)."""
    bank = PETBottleBank(num_bottles=4, volume_per_bottle=0.002, precharge_pressure=750_000.0)
    pump = CrankReciprocatingPump()

    res = pump.simulate_charging(
        bottle_bank=bank,
        crank_speed_rpm=60.0,
        num_cycles=2,
        dt=1e-4,
    )

    # Verification: simulation remains numerically stable, no NaN, work matches indicator p-V work
    assert not np.any(np.isnan(res.p_cyl))
    assert not np.any(np.isnan(res.p_bottle))
    assert res.work_conservation_error < 1e-4
    assert res.final_bottle_pressure > res.initial_bottle_pressure
    assert not bank.is_burst(res.final_bottle_pressure)
    assert bank.safety_factor(res.final_bottle_pressure) > 1.0


def test_high_speed_crank_pumping_stability() -> None:
    """Stress test crank pump at 300 RPM (5 Hz) and 600 RPM (10 Hz)."""
    bank = PETBottleBank(num_bottles=2, volume_per_bottle=0.002)
    pump = CrankReciprocatingPump()

    for rpm in [300.0, 600.0]:
        res = pump.simulate_charging(
            bottle_bank=bank,
            crank_speed_rpm=rpm,
            num_cycles=2,
            dt=5e-5,
        )
        assert not np.any(np.isnan(res.p_cyl))
        assert res.work_conservation_error < 1e-4
        assert res.pressure_rise > 0.0
        assert res.is_monotonically_increasing_bottle_pressure


def test_extreme_pressure_gradient_mass_conservation() -> None:
    """Stress test mass conservation with 800 kPa chamber expanding into 50 kPa chamber."""
    net = FluidNetwork(track_mass=True)
    net.add_node(FluidNode("burst_tank", pressure=800_000.0, volume=0.005, n=1.25))
    net.add_node(FluidNode("vacuum_tank", pressure=50_000.0, volume=0.015, n=1.25))
    net.add_element(Orifice("orifice", "burst_tank", "vacuum_tank", conductance=1e-7))

    res = net.simulate(t_span=(0.0, 1.0), dt=1e-4)

    assert res.mass_conservation_relative_error < 1e-7
    assert not np.any(np.isnan(res.total_mass))


# ==============================================================================
# 8. Thermodynamic Wall Temperature ODE Coupling Tests (H3-02)
# ==============================================================================


def test_thermodynamic_wall_temperature_ode_rates() -> None:
    """Verify instantaneous rate equations for gas-wall-ambient heat exchange:

    Q_int = h_int * A * (T_air - T_wall)
    Q_ext = h_ext * A * (T_wall - T_amb)
    C_wall * d(T_wall)/dt = Q_int - Q_ext
    m_air * c_v * d(T_air)/dt = -Q_int
    """
    T_air_0 = 360.0
    T_wall_0 = 310.0
    T_amb = 295.0
    A = 0.44
    h_int = 15.0
    h_ext = 10.0
    C_wall = 250.0  # J/K
    V = 0.008  # 8 L
    p = 200_000.0

    node = FluidNode(
        name="bottle",
        pressure=p,
        volume=V,
        temperature=T_air_0,
        n=GAMMA_AIR,
        heat_transfer_area=A,
        ambient_temperature=T_amb,
        wall_thermal_capacitance=C_wall,
        T_wall=T_wall_0,
        h_int=h_int,
        h_ext=h_ext,
    )
    net = FluidNetwork(track_mass=True)
    net.add_node(node)

    # 1. Verify analytical heat exchange fluxes
    Q_int_expected = h_int * A * (T_air_0 - T_wall_0)  # 15 * 0.44 * (360 - 310) = 330 W
    Q_ext_expected = h_ext * A * (T_wall_0 - T_amb)    # 10 * 0.44 * (310 - 295) = 66 W
    assert math.isclose(node.compute_heat_transfer_int(), Q_int_expected, rel_tol=1e-12)
    assert math.isclose(node.compute_heat_transfer_ext(), Q_ext_expected, rel_tol=1e-12)

    # 2. Verify wall rate of temperature change: d(T_wall)/dt = (Q_int - Q_ext) / C_wall
    dT_wall_dt_expected = (Q_int_expected - Q_ext_expected) / C_wall
    assert math.isclose(dT_wall_dt_expected, (330.0 - 66.0) / 250.0, rel_tol=1e-12)

    # 3. Verify gas internal energy rate: dU_gas/dt = -Q_int
    # dp/dt = (gamma - 1) * (-Q_int) / V
    dp_dt_expected = (GAMMA_AIR - 1.0) * (-Q_int_expected) / V

    # Extract state vector and derivatives from network
    y = net.get_state()
    # y layout: [p, V, m, T_wall]
    assert len(y) == 4
    assert math.isclose(y[0], p, rel_tol=1e-12)
    assert math.isclose(y[1], V, rel_tol=1e-12)
    assert math.isclose(y[3], T_wall_0, rel_tol=1e-12)

    dy, balance = net._derivatives_and_balance(0.0, y)
    dp_dt_actual = dy[0]
    dv_dt_actual = dy[1]
    dm_dt_actual = dy[2]
    dT_wall_dt_actual = dy[3]

    assert dv_dt_actual == 0.0
    assert dm_dt_actual == 0.0
    assert math.isclose(dp_dt_actual, dp_dt_expected, rel_tol=1e-12)
    assert math.isclose(dT_wall_dt_actual, dT_wall_dt_expected, rel_tol=1e-12)


def test_wall_thermal_capacitance_insulated_equilibrium() -> None:
    """Verify that an insulated container (h_ext = 0) reaches the exact analytical equilibrium temperature:

    T_eq = (m_air * c_v * T_air_0 + C_wall * T_wall_0) / (m_air * c_v + C_wall)
    with zero energy loss (E_in - E_loss - Delta U = 0).
    """
    T_air_0 = 380.0
    T_wall_0 = 290.0
    V = 0.005
    p_0 = 300_000.0
    m_air = (p_0 * V) / (R_AIR * T_air_0)
    C_wall = 180.0  # J/K

    # Analytical mixture equilibrium temperature
    T_eq_expected = (m_air * CV_AIR * T_air_0 + C_wall * T_wall_0) / (m_air * CV_AIR + C_wall)

    node = FluidNode(
        name="insulated_bottle",
        pressure=p_0,
        volume=V,
        temperature=T_air_0,
        n=GAMMA_AIR,
        heat_transfer_area=0.3,
        wall_thermal_capacitance=C_wall,
        T_wall=T_wall_0,
        h_int=20.0,
        h_ext=0.0,  # Perfectly insulated exterior
        ambient_temperature=T_wall_0,
    )
    net = FluidNetwork(track_mass=True)
    net.add_node(node)

    res = net.simulate(t_span=(0.0, 150.0), dt=0.01)

    # 1. Equilibrium temperatures must match analytical prediction
    T_air_final = res.temperatures["insulated_bottle"][-1]
    T_wall_final = res.wall_temperatures["insulated_bottle"][-1]
    assert math.isclose(T_air_final, T_eq_expected, rel_tol=1e-4)
    assert math.isclose(T_wall_final, T_eq_expected, rel_tol=1e-4)
    assert math.isclose(T_air_final, T_wall_final, rel_tol=1e-4)

    # 2. Strict energy conservation: residual must be zero within ODE tolerances
    assert np.max(np.abs(res.balance["energy_residual_j"])) < 1e-7
    assert res.mass_conservation_relative_error < 1e-12


def test_wall_temperature_coupling_ambient_heat_loss_energy_ledger() -> None:
    """Verify coupled wall dynamics with heat loss to ambient:

    1. Wall temperature initially heats up (absorbing heat from hot air).
    2. Air and wall both cool down toward ambient.
    3. Energy balance ledger satisfies E_in - E_loss - Delta U = 0.
    """
    bank = PETBottleBank(
        num_bottles=4,
        volume_per_bottle=0.002,
        precharge_pressure=400_000.0,
        ambient_temperature=293.15,
        heat_transfer_coeff=10.0,
    )
    # Start enclosed air hot at 360 K, wall at ambient 293.15 K
    node = bank.to_node(
        name="bottle",
        initial_pressure=400_000.0,
        initial_temperature=360.0,
        initial_wall_temperature=293.15,
    )
    net = FluidNetwork(track_mass=True)
    net.add_node(node)

    res = net.simulate(t_span=(0.0, 20.0), dt=0.005)

    wall_temps = res.wall_temperatures["bottle"]
    air_temps = res.temperatures["bottle"]

    # 1. Wall temperature initially increases because T_air > T_wall
    assert wall_temps[50] > wall_temps[0]

    # 2. Air temperature decreases monotonically
    assert air_temps[-1] < air_temps[0]

    # 3. Energy conservation in ledger: Delta U + Q_loss = 0
    assert np.max(np.abs(res.balance["energy_residual_j"])) < 1e-7
    assert res.balance["convective_heat_j"][-1] < 0.0  # Heat lost to ambient



