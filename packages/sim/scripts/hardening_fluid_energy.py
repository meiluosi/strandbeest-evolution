"""Fixed control-volume/virtual-work probes; no measured-data or H3 acceptance claim.

Run once against the preserved original implementation and once after the fix.
The same scenarios, time steps and analytic identities are used in both runs.
Outputs are new files only, with the actual loaded source hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from strandbeest_sim.fluids import (
    CP_AIR, GAMMA_AIR, P_ATM, R_AIR, CrankReciprocatingPump,
    FluidNetwork, FluidNode, Orifice, PETBottleBank,
)
from strandbeest_sim.fluids import constants, network, pump, storage


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def energy_summary(result):
    balance = getattr(result, "balance", {})
    return {
        "ledger_available": bool(balance),
        "ledger_final": {key: float(values[-1]) for key, values in balance.items()},
        "max_abs_energy_residual_j": float(np.max(np.abs(balance["energy_residual_j"]))) if balance else None,
        "reported_mass_conservation_relative_error": result.mass_conservation_relative_error,
    }


def exchange():
    net = FluidNetwork()
    net.add_node(FluidNode("hot", pressure=200_000.0, temperature=400.0, volume=0.001, n=GAMMA_AIR))
    net.add_node(FluidNode("cold", pressure=100_000.0, temperature=300.0, volume=0.001, n=GAMMA_AIR))
    net.add_element(Orifice("link", "hot", "cold", conductance=1e-8))
    flow = net.compute_mass_flows()["link"]
    dy = net.derivatives(0.0, net.get_state())
    result = net.simulate((0.0, 0.05), dt=1e-4)
    total_u = sum(result.pressures[name] * result.volumes[name] / (GAMMA_AIR - 1.0)
                  for name in ("hot", "cold"))
    return {
        "input": {"pressures_pa": [200_000.0, 100_000.0], "temperatures_k": [400.0, 300.0],
                  "volumes_m3": [0.001, 0.001], "n": GAMMA_AIR, "conductance": 1e-8,
                  "duration_s": 0.05, "dt_s": 1e-4},
        "initial_mass_flow_kg_s": flow,
        "initial_total_mass_rate_kg_s": float(np.sum(dy[4:])),
        "initial_total_gas_energy_rate_w": float(np.sum(0.001 * dy[:2] / (GAMMA_AIR - 1.0))),
        "expected_total_energy_rate_w": 0.0,
        "expected_inflow_enthalpy_w": flow * CP_AIR * 400.0,
        "actual_receiver_energy_rate_w": float(0.001 * dy[1] / (GAMMA_AIR - 1.0)),
        "max_abs_total_energy_change_j": float(np.max(np.abs(total_u - total_u[0]))),
        **energy_summary(result),
    }


def fixed_temperature():
    net = FluidNetwork()
    net.add_node(FluidNode("boundary", pressure=300_000.0, temperature=400.0, is_fixed_pressure=True))
    net.add_node(FluidNode("tank", pressure=100_000.0, temperature=300.0, volume=0.002,
                          is_fixed_temperature=True, heat_transfer_coeff=4.0,
                          heat_transfer_area=0.2, ambient_temperature=350.0))
    net.add_element(Orifice("fill", "boundary", "tank", conductance=1e-8))
    result = net.simulate((0.0, 0.02), dt=1e-4)
    pv = result.pressures["tank"] * result.volumes["tank"]
    mrt = result.masses["tank"] * R_AIR * result.temperatures["tank"]
    return {"max_ideal_gas_relative_error": float(np.max(np.abs(pv - mrt) / np.abs(mrt))),
            "temperature_change_k": float(result.temperatures["tank"][-1] - result.temperatures["tank"][0]),
            **energy_summary(result)}


def charging():
    rows = []
    for dt in (1e-4, 5e-5, 2.5e-5):
        net = CrankReciprocatingPump().create_network(PETBottleBank(), crank_speed_rpm=60.0)
        result = net.simulate((0.0, 1.0), dt=dt)
        rows.append({"dt_s": dt, "duration_s": 1.0, "rpm": 60.0,
                     "bottle_final_pressure_pa": float(result.pressures["bottle"][-1]),
                     **energy_summary(result)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    sources = [Path(module.__file__).resolve() for module in (constants, network, pump, storage)]
    sources.append(Path(__file__).resolve())
    initial = {str(path): digest(path) for path in sources}
    mechanism = CrankReciprocatingPump()
    angle, epsilon, delta_p = 0.7, 1e-6, 150_000.0
    expected_tau = delta_p * (mechanism.cylinder_volume(angle + epsilon)
                              - mechanism.cylinder_volume(angle - epsilon)) / (2.0 * epsilon)
    result = {
        "complete": True, "h3_02_accepted": False, "physical_measurements_added": 0,
        "scope": "Gas-only standalone network and prescribed-motion pump, not the walker coupling.",
        "assumptions": ["Ideal gas with constant air cp/cv; quasi-steady orifice flow.",
                        "Empirical n defaults retained; its heat must be explicit.",
                        "Vessel-wall thermal capacity remains metadata, not a coupled thermal state."],
        "primary_source": "https://web.mit.edu/16.unified/OldFiles/www/SPRING/thermodynamics/notes/node18.html",
        "source_sha256": initial,
        "rigid_adiabatic_exchange": exchange(),
        "prescribed_heat": [{"n": n, "supplied_w": 7.0,
            "actual_internal_energy_rate_w": FluidNode("tank", pressure=150_000.0,
                temperature=300.0, volume=0.002, n=n).compute_dp_dt(0.0, Q_dot=7.0)
                * 0.002 / (GAMMA_AIR - 1.0)} for n in (1.0, 1.25, GAMMA_AIR)],
        "fixed_temperature": fixed_temperature(),
        "crank_virtual_work": {"angle_rad": angle, "pressure_difference_pa": delta_p,
            "finite_difference_rad": epsilon, "expected_gas_on_crank_torque_nm": expected_tau,
            "actual_reaction_torque_nm": mechanism.reaction_torque(angle, P_ATM + delta_p)},
        "charging_refinement": charging(),
        "source_drift": [str(path) for path in sources if digest(path) != initial[str(path)]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.output), "sha256": digest(args.output),
                      "initial_exchange_energy_rate_w": result["rigid_adiabatic_exchange"]["initial_total_gas_energy_rate_w"],
                      "source_drift": result["source_drift"]}))


if __name__ == "__main__":
    main()
