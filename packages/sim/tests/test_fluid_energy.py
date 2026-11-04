"""Independent control-volume first-law checks; not real-world validation."""

from __future__ import annotations

import math

import numpy as np
import pytest

from strandbeest_sim.fluids import CP_AIR, CV_AIR, GAMMA_AIR, R_AIR
from strandbeest_sim.fluids import FluidNetwork, FluidNode, Orifice, CrankReciprocatingPump, PETBottleBank, P_ATM


@pytest.mark.parametrize("pressures", [(200_000.0, 100_000.0), (100_000.0, 200_000.0)])
@pytest.mark.parametrize("temperatures", [(400.0, 300.0), (280.0, 360.0)])
def test_rigid_adiabatic_exchange_conserves_energy_in_both_directions(pressures, temperatures):
    net = FluidNetwork()
    for name, p, temperature in zip(("a", "b"), pressures, temperatures):
        net.add_node(FluidNode(name, pressure=p, temperature=temperature, volume=0.001, n=GAMMA_AIR))
    net.add_element(Orifice("link", "a", "b", conductance=1e-8))
    flow = net.compute_mass_flows()["link"]
    rates = net.derivatives(0.0, net.get_state())
    energy_rates = rates[:2] * 0.001 / (GAMMA_AIR - 1.0)
    # An insulated rigid pair has no heat or mechanical work across its boundary.
    assert math.fsum(energy_rates) == pytest.approx(0.0, abs=1e-9)
    assert math.fsum(rates[4:]) == pytest.approx(0.0, abs=1e-15)
    donor, receiver = (0, 1) if flow > 0 else (1, 0)
    # Filling a tank brings upstream enthalpy, not the receiving tank's temperature.
    assert energy_rates[receiver] == pytest.approx(abs(flow) * CP_AIR * temperatures[donor], rel=1e-13)
    result = net.simulate((0.0, 0.05), dt=1e-4)
    total_energy = sum(result.pressures[name] * 0.001 / (GAMMA_AIR - 1.0) for name in ("a", "b"))
    np.testing.assert_allclose(total_energy, total_energy[0], rtol=1e-12, atol=1e-10)


@pytest.mark.parametrize("n", [1.0, 1.25, GAMMA_AIR])
def test_prescribed_heat_uses_physical_air_heat_capacity(n):
    node = FluidNode("tank", pressure=150_000.0, temperature=300.0, volume=0.002, n=n)
    supplied_watts = 7.0
    dp = node.compute_dp_dt(0.0, Q_dot=supplied_watts)
    # A sealed rigid tank has dU/dt = Q, independently of a compression exponent.
    assert node.volume * dp / (GAMMA_AIR - 1.0) == pytest.approx(supplied_watts, rel=1e-13)


def test_fixed_temperature_overrides_empirical_compression_exponent():
    net = FluidNetwork()
    net.add_node(FluidNode("boundary", pressure=300_000.0, temperature=400.0, is_fixed_pressure=True))
    tank = FluidNode("tank", pressure=100_000.0, temperature=300.0, volume=0.002,
                     is_fixed_temperature=True, heat_transfer_coeff=4.0, heat_transfer_area=0.2,
                     ambient_temperature=350.0)
    net.add_node(tank)
    net.add_element(Orifice("fill", "boundary", "tank", conductance=1e-8))
    initial_mass = tank.mass
    result = net.simulate((0.0, 0.02), dt=1e-4)
    assert result.masses["tank"][-1] > initial_mass
    np.testing.assert_allclose(result.temperatures["tank"], 300.0, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(result.pressures["tank"] * result.volumes["tank"],
                               result.masses["tank"] * R_AIR * 300.0, rtol=1e-12, atol=1e-10)
    balance = result.balance
    gained_u = CV_AIR * 300.0 * (result.masses["tank"] - initial_mass)
    np.testing.assert_allclose(balance["external_enthalpy_j"],
                               CP_AIR * 400.0 * (result.masses["tank"] - initial_mass), atol=1e-10)
    np.testing.assert_allclose(balance["convective_heat_j"], 40.0 * result.t, atol=1e-12)
    np.testing.assert_allclose(balance["thermostat_heat_j"],
                               gained_u - balance["external_enthalpy_j"] - 40.0 * result.t, atol=1e-10)
    assert balance["thermostat_heat_j"][-1] < 0.0
    assert np.max(np.abs(balance["energy_residual_j"])) < 1e-10


@pytest.mark.parametrize("filling", [True, False])
def test_open_adiabatic_tank_matches_analytic_fill_or_blowdown(filling):
    net = FluidNetwork()
    net.add_node(FluidNode("reservoir", pressure=300_000.0 if filling else 100_000.0,
                          temperature=400.0 if filling else 300.0, is_fixed_pressure=True))
    tank = FluidNode("tank", pressure=100_000.0 if filling else 300_000.0,
                     temperature=280.0 if filling else 400.0, volume=0.002, n=GAMMA_AIR)
    net.add_node(tank)
    net.add_element(Orifice("port", "reservoir", "tank", conductance=1e-8))
    initial_p, initial_t, initial_m = tank.pressure, tank.temperature, tank.mass
    result = net.simulate((0.0, 0.1), dt=1e-4)
    mass_ratio = result.masses["tank"] / initial_m
    if filling:
        expected_u = initial_p * tank.volume / (GAMMA_AIR - 1.0) + CP_AIR * 400.0 * (result.masses["tank"] - initial_m)
        np.testing.assert_allclose(result.balance["internal_energy_j"], expected_u, rtol=1e-12, atol=1e-10)
        assert result.balance["external_enthalpy_j"][-1] > 0.0
    else:
        np.testing.assert_allclose(result.temperatures["tank"], initial_t * mass_ratio ** (GAMMA_AIR - 1.0), rtol=1e-11)
        np.testing.assert_allclose(result.pressures["tank"], initial_p * mass_ratio ** GAMMA_AIR, rtol=1e-11)
        assert result.balance["external_enthalpy_j"][-1] < 0.0
    np.testing.assert_allclose(result.balance["boundary_mass_kg"], result.masses["tank"] - initial_m, atol=1e-14)
    assert result.mass_conservation_relative_error < 1e-12
    assert np.max(np.abs(result.balance["energy_residual_j"])) < 1e-9
    assert np.max(np.abs(result.balance["polytropic_heat_j"])) == 0.0


@pytest.mark.parametrize("n", [1.0, 1.25, GAMMA_AIR])
def test_closed_compression_matches_analytic_work_and_heat(n):
    p0, v0 = 100_000.0, 0.001
    net = FluidNetwork()
    net.add_node(FluidNode("piston", pressure=p0, volume=v0, n=n,
                          volume_func=lambda t: (v0 * (1.0 - 0.5 * t), -0.5 * v0)))
    result = net.simulate((0.0, 0.5), dt=0.0025)
    volumes = v0 * (1.0 - 0.5 * result.t)
    pressures = p0 * (v0 / volumes) ** n
    np.testing.assert_allclose(result.pressures["piston"], pressures, rtol=2e-11)
    work = (p0 * v0 * np.log(v0 / volumes) if n == 1.0
            else (pressures * volumes - p0 * v0) / (n - 1.0))
    delta_u = (pressures * volumes - p0 * v0) / (GAMMA_AIR - 1.0)
    np.testing.assert_allclose(result.balance["compression_work_j"], work, rtol=2e-9, atol=1e-8)
    np.testing.assert_allclose(result.balance["polytropic_heat_j"], delta_u - work, rtol=2e-9, atol=1e-8)
    assert np.max(np.abs(result.balance["energy_residual_j"])) < 1e-8
    if n < GAMMA_AIR:
        assert result.balance["polytropic_heat_j"][-1] < 0.0
    else:
        assert result.balance["polytropic_heat_j"][-1] == 0.0


def test_rigid_cooling_matches_lumped_heat_capacity_solution():
    node = FluidNode("hot", pressure=200_000.0, temperature=400.0, volume=0.002,
                     n=1.25, heat_transfer_coeff=2.0, heat_transfer_area=0.1,
                     ambient_temperature=300.0)
    mass = node.mass
    net = FluidNetwork()
    net.add_node(node)
    result = net.simulate((0.0, 5.0), dt=0.01)
    expected_temperature = 300.0 + 100.0 * np.exp(-0.2 * result.t / (mass * CV_AIR))
    np.testing.assert_allclose(result.temperatures["hot"], expected_temperature, rtol=1e-12)
    np.testing.assert_allclose(result.balance["convective_heat_j"],
                               mass * CV_AIR * (expected_temperature - 400.0), atol=1e-9)
    assert np.max(np.abs(result.balance["energy_residual_j"])) < 1e-9


def test_different_polytropic_closures_report_nonzero_external_heat():
    net = FluidNetwork()
    net.add_node(FluidNode("a", pressure=200_000.0, temperature=400.0, volume=0.001, n=1.25))
    net.add_node(FluidNode("b", pressure=100_000.0, temperature=300.0, volume=0.001, n=GAMMA_AIR))
    net.add_element(Orifice("link", "a", "b", conductance=1e-8))
    result = net.simulate((0.0, 0.02), dt=1e-4)
    delta_u = result.balance["internal_energy_j"] - result.balance["internal_energy_j"][0]
    assert delta_u[-1] > 1.0  # The empirical closure supplies heat; this is not adiabatic.
    np.testing.assert_allclose(delta_u, result.balance["polytropic_heat_j"], atol=1e-9)
    np.testing.assert_allclose(result.balance["external_enthalpy_j"], 0.0, atol=1e-12)
    assert np.max(np.abs(result.balance["energy_residual_j"])) < 1e-9


def test_curved_prescribed_volume_has_convergent_energy_error():
    errors = []
    for dt in (0.05, 0.025):
        v0, p0 = 0.001, 100_000.0
        net = FluidNetwork()
        net.add_node(FluidNode("cyl", pressure=p0, volume=v0, n=GAMMA_AIR,
                              volume_func=lambda t: (v0 * math.exp(-2.0 * t), -2.0 * v0 * math.exp(-2.0 * t))))
        result = net.simulate((0.0, 0.5), dt=dt)
        np.testing.assert_allclose(result.volumes["cyl"], v0 * np.exp(-2.0 * result.t), rtol=1e-15)
        errors.append(abs(result.balance["energy_residual_j"][-1]))
    # RK4 quadrature/integration error is exposed, never forced to zero by the ledger.
    assert errors[0] > 1e-5
    assert errors[1] < errors[0] / 8.0


def test_partial_state_cannot_silently_reuse_old_mass():
    net = FluidNetwork()
    net.add_node(FluidNode("tank"))
    with pytest.raises(ValueError, match="requires pressure, volume and mass"):
        net.derivatives(0.0, net.get_state()[:2])
    with pytest.raises(ValueError, match="track_mass=True"):
        FluidNetwork(track_mass=False).add_node(FluidNode("tank"))


def test_rejected_step_preserves_previous_valid_state():
    net = FluidNetwork()
    net.add_node(FluidNode("a", pressure=200_000.0, n=GAMMA_AIR))
    net.add_node(FluidNode("b", pressure=100_000.0, n=GAMMA_AIR))
    net.add_element(Orifice("link", "a", "b", conductance=1e-6))
    initial = net.get_state().copy()
    with pytest.raises(ValueError, match="Non-positive thermodynamic state"):
        net.step(1.0)
    np.testing.assert_array_equal(net.get_state(), initial)
    assert net.last_step_balance == {}


@pytest.mark.parametrize("dt,method", [(0.0, "rk4"), (-0.01, "rk4"), (float("nan"), "rk4"), (0.01, "rkk4")])
def test_invalid_integrator_input_fails_explicitly(dt, method):
    net = FluidNetwork()
    net.add_node(FluidNode("tank"))
    with pytest.raises(ValueError):
        net.step(dt, method=method)


@pytest.mark.parametrize("angle,omega", [(0.7, 3.0), (0.7, -3.0), (4.0, 3.0), (4.0, -3.0)])
def test_gas_reaction_on_crank_matches_independent_virtual_work(angle, omega):
    pump = CrankReciprocatingPump()
    pressure_difference = 150_000.0
    epsilon = 1e-6
    # Finite work from an independent displacement, rather than the analytic derivative.
    delta_volume = pump.cylinder_volume(angle + epsilon) - pump.cylinder_volume(angle - epsilon)
    expected_torque = pressure_difference * delta_volume / (2.0 * epsilon)
    actual_torque = pump.reaction_torque(angle, P_ATM + pressure_difference)
    assert actual_torque == pytest.approx(expected_torque, rel=1e-9)
    power_into_gas = pump.mechanical_power(angle, omega, P_ATM + pressure_difference)
    assert power_into_gas == pytest.approx(-expected_torque * omega, rel=1e-9)


def test_charging_network_accounts_for_heat_and_inlet_enthalpy():
    pump = CrankReciprocatingPump()
    bank = PETBottleBank()
    coarse = pump.create_network(bank, crank_speed_rpm=60.0).simulate((0.0, 1.0), dt=1e-4)
    net = pump.create_network(bank, crank_speed_rpm=60.0)
    result = net.simulate((0.0, 1.0), dt=5e-5)
    balance = result.balance
    assert result.pressures["bottle"][-1] > result.pressures["bottle"][0]
    assert balance["boundary_mass_kg"][-1] > 0.0
    assert balance["external_enthalpy_j"][-1] > 0.0
    assert balance["polytropic_heat_j"][-1] < 0.0
    assert result.mass_conservation_relative_error < 1e-11
    # The boundary enthalpy must not be counted as shaft work or ignored.
    np.testing.assert_allclose(balance["external_enthalpy_j"],
                               CP_AIR * net.nodes["atm"].temperature * balance["boundary_mass_kg"], atol=1e-9)
    assert np.max(np.abs(balance["energy_residual_j"])) < 1e-7
    # Valve switching is nonsmooth; verify refinement without asserting RK4's
    # smooth-ODE convergence order or treating the coarse error as zero.
    assert np.max(np.abs(balance["energy_residual_j"])) < np.max(np.abs(coarse.balance["energy_residual_j"])) / 2.0
