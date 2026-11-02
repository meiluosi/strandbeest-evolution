"""Unit and physics tests for Strandbeest fluidic logic, morphological computing, and reflexes.

Tests covering:
1. Bistable mechanical detent slide valve (valves.py):
   - Hysteresis and deadband latching
   - Threshold snap switching (|p_A - p_B| > delta_p_switch)
   - Supply routing to forward/reverse channels
2. 4-bit pneumatic binary ripple step counter (counter.py):
   - T-flip-flop pulse edge detection
   - 16-step counting cycle (0 -> 1 -> ... -> 15 -> 0)
   - Overflow detection and automatic reversal pulse to directional valve
3. Theo Jansen water feeler reflex (feeler.py):
   - Hagen-Poiseuille viscous resistance (air vs water ~55x)
   - Atmospheric breathing vacuum < 1 kPa (< 500 Pa)
   - Immersion vacuum collapse (< -25 kPa within 50 ms)
   - Reflex reverse command tripping bistable valve
4. Storm ground-anchor reflex (anchor.py):
   - Tilt sensor arccos threshold (theta_crit = 18 deg)
   - Overturning moment stability limit
   - Pneumatic spike firing velocity and embedment stroke (0.15 m)
   - Mohr-Coulomb / Rankine soil mechanics holding force > 1500 N
"""

import math
import pytest

from strandbeest_sim.fluids.valves import BistableValve, BistableValveConfig
from strandbeest_sim.fluids.counter import (
    FluidicTFlipFlop,
    FlipFlopConfig,
    PneumaticStepCounter,
    StepCounterConfig,
)
from strandbeest_sim.fluids.feeler import WaterFeeler, WaterFeelerConfig
from strandbeest_sim.fluids.anchor import StormAnchor, StormAnchorConfig


# =============================================================================
# 1. Bistable Mechanical Detent Valve Tests
# =============================================================================


class TestBistableValve:
    def test_initial_state_and_routing(self):
        """Verify default forward state and channel pressure assignments."""
        cfg = BistableValveConfig(delta_p_switch=15000.0, p_supply=300000.0, p_exhaust=101325.0)
        valve = BistableValve(config=cfg, initial_state=1)

        assert valve.state == 1
        assert valve.is_forward is True
        assert valve.is_reverse is False
        assert valve.p_forward == pytest.approx(300000.0)
        assert valve.p_reverse == pytest.approx(101325.0)

        # Reverse initial state
        rev_valve = BistableValve(config=cfg, initial_state=-1)
        assert rev_valve.state == -1
        assert rev_valve.is_forward is False
        assert rev_valve.is_reverse is True
        assert rev_valve.p_forward == pytest.approx(101325.0)
        assert rev_valve.p_reverse == pytest.approx(300000.0)

    def test_hysteresis_deadband_retention(self):
        """Verify valve does NOT switch when control pressure difference is within deadband."""
        cfg = BistableValveConfig(delta_p_switch=15000.0)  # 15 kPa threshold
        valve = BistableValve(config=cfg, initial_state=1)
        p_atm = 101325.0

        # Pressures within deadband: dp = p_A - p_B in [-14 kPa, +14 kPa]
        test_pressures = [
            (p_atm, p_atm),  # dp = 0
            (p_atm + 5000.0, p_atm),  # dp = +5 kPa (favors current state 1)
            (p_atm, p_atm + 10000.0),  # dp = -10 kPa (opposes, but < 15 kPa threshold)
            (p_atm, p_atm + 14900.0),  # dp = -14.9 kPa (just below threshold)
        ]

        for p_A, p_B in test_pressures:
            switched = valve.evaluate_switching(p_A, p_B)
            assert switched == 0
            assert valve.state == 1, f"Flipped prematurely at dp = {p_A - p_B}"

    def test_snap_switching_above_threshold(self):
        """Verify instantaneous snap above switching threshold."""
        cfg = BistableValveConfig(delta_p_switch=15000.0)
        valve = BistableValve(config=cfg, initial_state=1)
        p_atm = 101325.0

        # Apply differential pressure exceeding 15 kPa in reverse direction:
        # p_B - p_A = 16000 Pa > 15000 Pa -> snaps to -1
        switched = valve.evaluate_switching(p_A=p_atm, p_B=p_atm + 16000.0)
        assert switched == -1
        assert valve.state == -1
        assert valve.p_reverse == pytest.approx(cfg.p_supply)
        assert valve.p_forward == pytest.approx(cfg.p_exhaust)

        # Now in reverse state: apply small forward pressure (10 kPa), should remain -1
        assert valve.evaluate_switching(p_A=p_atm + 10000.0, p_B=p_atm) == 0
        assert valve.state == -1

        # Now apply forward pressure exceeding threshold: p_A - p_B = 18 kPa -> snaps back to +1
        switched_back = valve.evaluate_switching(p_A=p_atm + 18000.0, p_B=p_atm)
        assert switched_back == 1
        assert valve.state == 1
        assert valve.p_forward == pytest.approx(cfg.p_supply)

    def test_continuous_spool_dynamics(self):
        """Verify dynamic ODE integration of spool motion with detent double-well potential."""
        cfg = BistableValveConfig(delta_p_switch=15000.0, spool_mass=0.02, c_viscous=2.0)
        valve = BistableValve(config=cfg, initial_state=1)
        p_atm = 101325.0

        # Step with zero differential pressure for 50 ms: spool stays latched at +half_stroke
        for _ in range(50):
            valve.step(dt=0.001, p_A=p_atm, p_B=p_atm)
        assert valve.state == 1
        assert valve.spool_position == pytest.approx(cfg.spool_stroke / 2.0)

        # Apply strong reversal pressure (p_B - p_A = 25 kPa)
        for _ in range(50):
            valve.step(dt=0.001, p_A=p_atm, p_B=p_atm + 25000.0)
        assert valve.state == -1
        assert valve.spool_position == pytest.approx(-cfg.spool_stroke / 2.0)

    def test_detent_peak_force_physics(self):
        """Verify maximum detent spring resistance matches delta_p_switch * A_spool."""
        cfg = BistableValveConfig(delta_p_switch=15000.0, spool_area=1.0e-4)
        valve = BistableValve(config=cfg)
        expected_f_peak = cfg.delta_p_switch * cfg.spool_area  # 15000 * 1e-4 = 1.5 N

        # Peak force in double-well occurs at x = half_stroke / sqrt(3)
        x_peak = (cfg.spool_stroke / 2.0) / math.sqrt(3.0)
        f_det = valve.detent_force(x_peak)
        assert f_det == pytest.approx(expected_f_peak, rel=1e-3)


# =============================================================================
# 2. 4-bit Pneumatic Binary Ripple Step Counter Tests
# =============================================================================


class TestStepCounter:
    def test_fluidic_t_flip_flop_pulse_edge_detection(self):
        """Verify single T-FF primes on high pressure pulse and toggles on falling edge."""
        ff_cfg = FlipFlopConfig(p_high=20000.0, p_low=5000.0)
        ff = FluidicTFlipFlop(config=ff_cfg, initial_q=0)

        # Pressure rising towards p_high
        ff.step(15000.0, is_gauge=True)
        assert ff.q == 0  # not yet primed

        # Reach high threshold
        ff.step(22000.0, is_gauge=True)
        assert ff.q == 0  # primed, but waiting for falling edge

        # Pressure dropping between high and low
        ff.step(10000.0, is_gauge=True)
        assert ff.q == 0

        # Falling edge below p_low -> toggle completes!
        carry = ff.step(4000.0, is_gauge=True)
        assert ff.q == 1
        assert carry is False  # 0 -> 1 does not emit carry

        # Second pulse: 0 -> 25 kPa -> 2 kPa
        ff.step(25000.0, is_gauge=True)
        carry2 = ff.step(2000.0, is_gauge=True)
        assert ff.q == 0
        assert carry2 is True  # 1 -> 0 emits carry!

    def test_16_step_ripple_counting_cycle(self):
        """Verify full binary count sequence 0 -> 1 -> ... -> 15 -> 0."""
        counter = PneumaticStepCounter()
        assert counter.count == 0
        assert counter.bits == (0, 0, 0, 0)

        # Step through 1 to 15
        for step in range(1, 16):
            overflow = counter.tick()
            assert counter.count == step
            assert overflow is False, f"Premature overflow at step {step}"

            # Verify binary bits match integer
            expected_bits = (
                (step >> 0) & 1,
                (step >> 1) & 1,
                (step >> 2) & 1,
                (step >> 3) & 1,
            )
            assert counter.bits == expected_bits

        # 16th step: rollover from 15 -> 0 triggers overflow!
        overflow16 = counter.tick()
        assert counter.count == 0
        assert counter.bits == (0, 0, 0, 0)
        assert overflow16 is True
        assert counter.overflow_active is True

    def test_counter_automatic_reversal_trigger(self):
        """Verify counter triggers direction reversal on connected bistable valve upon overflow."""
        valve = BistableValve(initial_state=1)
        counter = PneumaticStepCounter(valve=valve)

        assert valve.is_forward is True

        # Perform 15 steps: valve should stay forward
        for _ in range(15):
            counter.tick()
        assert valve.is_forward is True

        # 16th step triggers overflow and flips valve to reverse
        counter.tick()
        assert counter.count == 0
        assert counter.overflow_active is True
        assert valve.is_reverse is True
        assert valve.state == -1

    def test_counter_with_continuous_pump_pulses(self):
        """Verify counter operation with simulated continuous reciprocating pump pressure pulses."""
        counter = PneumaticStepCounter()
        p_atm = 101325.0

        # Simulate 3 pump stroke cycles (each cycle: rise to 25 kPa gauge, fall to 0)
        for expected_count in (1, 2, 3):
            # Pump compression stroke
            for _ in range(10):
                counter.step(dt=0.01, p_pulse=p_atm + 25000.0)
            # Pump exhaust stroke
            for _ in range(10):
                counter.step(dt=0.01, p_pulse=p_atm + 1000.0)

            assert counter.count == expected_count


# =============================================================================
# 3. Theo Jansen Water Feeler ("watervoeler") Reflex Tests
# =============================================================================


class TestWaterFeeler:
    def test_hagen_poiseuille_resistances(self):
        """Verify analytical Hagen-Poiseuille resistance of air and water in 3 mm tube."""
        cfg = WaterFeelerConfig(
            tube_diameter=0.003,
            tube_length=0.5,
            mu_air=1.82e-5,
            mu_water=1.002e-3,
        )
        feeler = WaterFeeler(config=cfg)

        pi_d4 = math.pi * (0.003**4)
        expected_r_air = (128.0 * 1.82e-5 * 0.5) / pi_d4
        expected_r_water = (128.0 * 1.002e-3 * 0.5) / pi_d4

        assert feeler.r_air == pytest.approx(expected_r_air, rel=1e-5)
        assert feeler.r_water == pytest.approx(expected_r_water, rel=1e-5)
        # Ratio of water to air resistance is ~55x
        assert (feeler.r_water / feeler.r_air) == pytest.approx(55.05, rel=1e-2)

    def test_air_breathing_negligible_vacuum(self):
        """Verify that in air, aspiration creates negligible vacuum (|p_tube - p_atm| < 500 Pa < 1 kPa)."""
        feeler = WaterFeeler()
        # Tip is 0.05 m above water level (z_water = 0)
        feeler.set_water_level(0.0)

        # Step for 200 ms in air
        for _ in range(20):
            feeler.step(dt=0.01, override_tip_altitude=0.05)

        # Vacuum should be negligible (< 500 Pa, Hagen-Poiseuille delta_p ~ 229 Pa)
        assert abs(feeler.gauge_pressure) < 500.0
        assert abs(feeler.gauge_pressure) < 1000.0
        assert feeler.is_immersed is False
        assert feeler.trip_triggered is False

    def test_water_immersion_vacuum_spike_within_50ms(self):
        """Verify that water immersion causes vacuum collapse (< -25 kPa) within 50 ms."""
        valve = BistableValve(initial_state=1)
        feeler = WaterFeeler(valve=valve)
        feeler.set_water_level(0.0)

        # Immerse tip at z = -0.01 m (below water level 0.0)
        immersion_time = 0.0
        tripped_in_50ms = False

        dt = 0.001  # 1 ms steps
        for step_i in range(100):  # up to 100 ms
            fired = feeler.step(dt=dt, override_tip_altitude=-0.01)
            immersion_time = (step_i + 1) * dt

            if feeler.gauge_pressure <= -25000.0:  # < -25 kPa gauge
                tripped_in_50ms = immersion_time <= 0.050
                break

        assert feeler.is_immersed is True
        assert feeler.gauge_pressure < -25000.0
        assert tripped_in_50ms is True, f"Took {immersion_time*1000:.1f} ms to reach -25 kPa, expected <= 50 ms"
        assert feeler.trip_triggered is True
        # Valve should have reversed to escape tide
        assert valve.is_reverse is True
        assert valve.state == -1

    def test_oscillating_feeler_tide_detection(self):
        """Verify oscillating tip detects water as tide rises above trough of oscillation."""
        cfg = WaterFeelerConfig(oscillation_amplitude=0.03, oscillation_frequency=5.0)
        feeler = WaterFeeler(config=cfg, base_altitude=0.05)
        # Tip oscillates between 0.02 m and 0.08 m

        # Tide at 0.01 m -> tip never touches water
        for _ in range(50):
            feeler.step(dt=0.02, z_water=0.01)
        assert feeler.trip_triggered is False

        # Tide rises to 0.025 m -> tip touches water during trough
        trip_detected = False
        for _ in range(120):
            if feeler.step(dt=0.01, z_water=0.025):
                trip_detected = True
                break

        assert trip_detected is True
        assert feeler.trip_triggered is True


# =============================================================================
# 4. Storm Sand-Anchor ("stormanker") Reflex Tests
# =============================================================================


class TestStormAnchor:
    def test_tilt_sensor_trigger_threshold(self):
        """Verify tilt trigger angle theta_crit = 18 degrees."""
        anchor = StormAnchor(StormAnchorConfig(theta_crit_deg=18.0))

        # 1. Normal upright walker: z_walker = [0, 0, 1] -> tilt = 0 deg
        assert anchor.compute_tilt_angle([0, 0, 1]) == pytest.approx(0.0)
        assert anchor.check_tilt_trigger([0, 0, 1]) is False

        # 2. Moderate tilt: 15 deg < 18 deg -> no trigger
        tilt_15 = math.radians(15.0)
        z_15 = [math.sin(tilt_15), 0.0, math.cos(tilt_15)]
        assert math.degrees(anchor.compute_tilt_angle(z_15)) == pytest.approx(15.0, abs=1e-3)
        assert anchor.check_tilt_trigger(z_15) is False

        # 3. Critical tilt: 19 deg > 18 deg -> triggers!
        tilt_19 = math.radians(19.0)
        z_19 = [math.sin(tilt_19), 0.0, math.cos(tilt_19)]
        assert math.degrees(anchor.compute_tilt_angle(z_19)) == pytest.approx(19.0, abs=1e-3)
        assert anchor.check_tilt_trigger(z_19) is True

    def test_wind_overturning_moment_trigger(self):
        """Verify storm wind drag trigger when overturning moment exceeds stability moment."""
        cfg = StormAnchorConfig(walker_mass=80.0, stance_width=1.6, sail_center_height=1.4)
        anchor = StormAnchor(config=cfg)

        # Righting moment M_restore = 80 kg * 9.81 * 0.8 m = 627.84 N*m
        # Critical drag force: F_crit = 627.84 / 1.4 = 448.46 N
        assert anchor.check_wind_overturn(wind_drag_force=300.0) is False
        assert anchor.check_wind_overturn(wind_drag_force=460.0) is True

    def test_pneumatic_firing_dynamics(self):
        """Verify pneumatic cylinder shoots spike into sand achieving high velocity and stroke."""
        cfg = StormAnchorConfig(
            stroke=0.15,  # 0.15 m embedment
            piston_diameter=0.04,  # 40 mm bore
            p_tank=500000.0,  # 500 kPa
            spike_mass=0.8,  # 0.8 kg
        )
        anchor = StormAnchor(config=cfg)

        # Trigger anchor via critical tilt
        tilt_25 = math.radians(25.0)
        z_tilt = [0.0, math.sin(tilt_25), math.cos(tilt_25)]

        peak_velocity = 0.0
        time_to_seat = 0.0

        dt = 0.002
        for step_i in range(100):  # up to 200 ms
            fully_deployed = anchor.step(dt=dt, z_walker=z_tilt)
            v = anchor.deployment_velocity
            if v > peak_velocity:
                peak_velocity = v
            if fully_deployed:
                time_to_seat = (step_i + 1) * dt
                break

        assert anchor.is_deployed is True
        assert anchor.penetration_depth == pytest.approx(0.15, rel=1e-3)
        # Deployment should be fast (< 100 ms) and achieve several m/s velocity
        assert time_to_seat < 0.100, f"Took {time_to_seat*1000:.1f} ms, expected < 100 ms"
        assert peak_velocity > 1.5, f"Peak velocity {peak_velocity:.2f} m/s too slow"

    def test_soil_mechanics_holding_force_exceeds_1500N(self):
        """Verify Mohr-Coulomb / Rankine passive earth pressure holding force > 1500 N."""
        cfg = StormAnchorConfig(
            phi_deg=35.0,  # 35 deg sand friction
            gamma_sand=17000.0,  # 17 kN/m^3
            c_cohesion=20000.0,  # 20 kPa damp sand apparent cohesion
            q_surcharge=15000.0,  # 15 kPa foot surcharge
            fluke_width=0.10,  # 10 cm effective width
            stroke=0.15,  # 15 cm embedment
        )
        anchor = StormAnchor(config=cfg)

        # Rankine passive earth pressure coefficient: K_p = tan^2(45 + 35/2) = 3.690
        expected_kp = math.tan(math.radians(45.0 + 35.0 / 2.0)) ** 2
        assert anchor.k_p == pytest.approx(expected_kp, rel=1e-4)
        assert anchor.k_p == pytest.approx(3.690, abs=0.01)

        # Calculate holding resistance force in sand
        f_holding = anchor.compute_holding_force()

        # Requirement: F_holding > 1500 N
        assert f_holding > 1500.0, f"Holding force {f_holding:.1f} N was below 1500 N"
        # Check realistic physical magnitude (around 1800 - 2500 N)
        assert 1600.0 <= f_holding <= 3000.0, f"Unrealistic holding force {f_holding:.1f} N"

    def test_soil_mechanics_parameter_sensitivity(self):
        """Verify holding force increases monotonically with friction angle and depth."""
        # 1. Friction angle sensitivity
        forces_phi = []
        for phi in (30.0, 35.0, 40.0):
            anc = StormAnchor(StormAnchorConfig(phi_deg=phi))
            forces_phi.append(anc.compute_holding_force())
        assert forces_phi[0] < forces_phi[1] < forces_phi[2]

        # 2. Embedment depth scaling
        anc = StormAnchor(StormAnchorConfig())
        f_shallow = anc.compute_holding_force(depth=0.05)
        f_mid = anc.compute_holding_force(depth=0.10)
        f_full = anc.compute_holding_force(depth=0.15)
        assert f_shallow < f_mid < f_full
        # Depth scaling is super-linear due to deepening passive wedge
        assert (f_full / f_shallow) > 3.0

    def test_3d_roll_and_pitch_compound_tilt(self):
        """Verify compound 3D roll and pitch tilt vector angles."""
        anc = StormAnchor(StormAnchorConfig(theta_crit_deg=18.0))
        # Pure pitch of 12 deg + pure roll of 15 deg
        pitch = math.radians(12.0)
        roll = math.radians(15.0)
        # Up-vector after pitch and roll: [sin(roll), sin(pitch), cos(roll)*cos(pitch)]
        z_compound = [math.sin(roll), math.sin(pitch), math.cos(roll) * math.cos(pitch)]
        theta = math.degrees(anc.compute_tilt_angle(z_compound))
        # Total 3D compound tilt angle ~ 19.36 deg
        assert theta == pytest.approx(19.36, abs=0.1)
        # Compound angle exceeds 18 deg -> triggers
        assert anc.check_tilt_trigger(z_compound) is True


class TestIntegratedFluidicReflexes:
    def test_feeler_rapid_recovery_on_water_exit(self):
        """Verify feeler tube recovers from vacuum back to ambient immediately when lifted from water."""
        feeler = WaterFeeler()
        # 1. Submerge to build vacuum
        for _ in range(50):
            feeler.step(dt=0.001, override_tip_altitude=-0.02)
        assert feeler.gauge_pressure < -25000.0

        # 2. Lift out of water into air
        for _ in range(10):  # 10 ms of air aspiration
            feeler.step(dt=0.001, override_tip_altitude=0.05)

        # Recovers back to low-resistance breathing (< 500 Pa)
        assert abs(feeler.gauge_pressure) < 500.0
        assert feeler.is_immersed is False

    def test_counter_noise_rejection(self):
        """Verify counter rejects sub-threshold pressure fluctuations without stepping."""
        counter = PneumaticStepCounter()
        p_atm = 101325.0

        # Small pressure ripple (e.g. 8 kPa gauge, below p_high of 20 kPa)
        for _ in range(50):
            counter.step(dt=0.01, p_pulse=p_atm + 8000.0)
            counter.step(dt=0.01, p_pulse=p_atm + 1000.0)

        assert counter.count == 0  # Rejects noise, no spurious steps

    def test_counter_multi_cycle_rollover(self):
        """Verify counter reliably counts 48 steps across 3 complete rollover cycles."""
        valve = BistableValve(initial_state=1)
        counter = PneumaticStepCounter(valve=valve)

        reversal_count = 0
        for step in range(48):
            valve.switch_to(1)  # reset valve to forward before potential flip
            overflow = counter.tick()
            if overflow:
                reversal_count += 1
                assert counter.count == 0
                assert valve.state == -1

        assert reversal_count == 3
        assert counter.total_steps == 48

