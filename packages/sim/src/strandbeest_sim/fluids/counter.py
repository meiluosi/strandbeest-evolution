"""4-bit pneumatic binary ripple step counter.

Implements a cascade of 4 fluidic T-flip-flops clocked by reciprocating
pump stroke pressure pulses. Tracks walking steps from 0 to 15.
Upon reaching the step limit (16 steps), it generates an overflow pulse
and triggers an automatic reversal command to the main directional slide valve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .valves import BistableValve


@dataclass
class FlipFlopConfig:
    """Thresholds for pneumatic pulse edge detection."""

    p_high: float = 20000.0  # Pa gauge (20 kPa threshold to prime trigger)
    p_low: float = 5000.0  # Pa gauge (5 kPa threshold to complete falling-edge toggle)
    p_atm: float = 101325.0  # Pa absolute


class FluidicTFlipFlop:
    """Single fluidic toggle flip-flop (T-FF).

    Toggles state Q in {0, 1} on the falling edge of an input pressure pulse.
    When Q transitions from 1 -> 0, it emits a carry pulse to drive downstream stages.
    """

    def __init__(self, config: FlipFlopConfig | None = None, initial_q: Literal[0, 1] = 0) -> None:
        self.config = config or FlipFlopConfig()
        self._q: Literal[0, 1] = initial_q
        self._primed: bool = False  # Set when p exceeds p_high, waiting for drop below p_low
        self._emitted_carry: bool = False

    @property
    def q(self) -> Literal[0, 1]:
        """Current binary state (0 or 1)."""
        return self._q

    @property
    def q_bar(self) -> Literal[0, 1]:
        """Complementary state (1 - Q)."""
        return 1 if self._q == 0 else 0

    def reset(self, q: Literal[0, 1] = 0) -> None:
        """Reset flip-flop to designated state."""
        self._q = q
        self._primed = False
        self._emitted_carry = False

    def toggle(self) -> bool:
        """Directly toggle Q.

        Returns:
            True if state transitioned 1 -> 0 (generating a carry out pulse).
        """
        old_q = self._q
        self._q = 0 if old_q == 1 else 1
        return old_q == 1 and self._q == 0

    def step(self, p_input: float, is_gauge: bool = False) -> bool:
        """Process input pressure signal and return whether a carry out occurred.

        Args:
            p_input: Pressure at input port (Pa).
            is_gauge: If True, p_input is relative to atmospheric; otherwise absolute.

        Returns:
            True if a falling-edge toggle occurred and Q transitioned 1 -> 0.
        """
        p_gauge = p_input if is_gauge else (p_input - self.config.p_atm)

        carry = False
        if not self._primed:
            if p_gauge >= self.config.p_high:
                self._primed = True
        else:
            if p_gauge <= self.config.p_low:
                self._primed = False
                carry = self.toggle()

        return carry


@dataclass
class StepCounterConfig:
    """Configuration for 4-bit pneumatic ripple counter."""

    step_limit: int = 16  # Count overflow threshold (16 steps = 0..15)
    reversal_pulse_pressure: float = 50000.0  # Pa gauge (50 kPa pulse to reverse valve)
    pulse_hold_time: float = 0.2  # Reversal pulse active duration (seconds)
    p_atm: float = 101325.0  # Pa absolute


class PneumaticStepCounter:
    """4-bit binary ripple step counter cascade.

    Constructed from 4 cascaded fluidic T-flip-flops (bits 0, 1, 2, 3).
    Bit 0 is clocked by reciprocating pump pulses.
    Bit i is clocked by the carry-out (1 -> 0 transition) of Bit i - 1.
    Counts 0 -> 1 -> ... -> 15 -> 0.
    Reaching step_limit triggers an overflow signal and automatic reversal pulse.
    """

    def __init__(
        self,
        config: StepCounterConfig | None = None,
        ff_config: FlipFlopConfig | None = None,
        valve: BistableValve | None = None,
    ) -> None:
        self.config = config or StepCounterConfig()
        self._ff_config = ff_config or FlipFlopConfig(p_atm=self.config.p_atm)
        self.valve = valve

        # 4 bits: Q0 (LSB), Q1, Q2, Q3 (MSB)
        self.cells = [
            FluidicTFlipFlop(config=self._ff_config),
            FluidicTFlipFlop(config=self._ff_config),
            FluidicTFlipFlop(config=self._ff_config),
            FluidicTFlipFlop(config=self._ff_config),
        ]

        self._total_steps: int = 0
        self._overflow_active: bool = False
        self._pulse_timer: float = 0.0

    @property
    def count(self) -> int:
        """Current 4-bit binary count as integer in [0, 15]."""
        return (
            self.cells[0].q * 1
            + self.cells[1].q * 2
            + self.cells[2].q * 4
            + self.cells[3].q * 8
        )

    @property
    def bits(self) -> tuple[int, int, int, int]:
        """Current binary state (Q0, Q1, Q2, Q3)."""
        return (
            self.cells[0].q,
            self.cells[1].q,
            self.cells[2].q,
            self.cells[3].q,
        )

    @property
    def total_steps(self) -> int:
        """Total number of pump strokes / steps executed since last reset."""
        return self._total_steps

    @property
    def overflow_active(self) -> bool:
        """True while reversal pulse is asserted following an overflow."""
        return self._overflow_active

    @property
    def reversal_pulse_pressure(self) -> float:
        """Output pressure pulse for reversing the valve (Pa gauge)."""
        return self.config.reversal_pulse_pressure if self._overflow_active else 0.0

    def reset(self) -> None:
        """Reset counter to 0 and de-assert overflow pulse."""
        for cell in self.cells:
            cell.reset(0)
        self._total_steps = 0
        self._overflow_active = False
        self._pulse_timer = 0.0

    def tick(self) -> bool:
        """Advance the ripple counter by exactly one discrete step pulse.

        Returns:
            True if step caused overflow (transition from 15 -> 0 or reaching step_limit).
        """
        self._total_steps += 1

        # Ripple propagation through the 4 T-FF stages:
        # Bit 0 always toggles
        c0 = self.cells[0].toggle()
        c1 = self.cells[1].toggle() if c0 else False
        c2 = self.cells[2].toggle() if c1 else False
        c3 = self.cells[3].toggle() if c2 else False

        # Overflow occurs when MSB (bit 3) rolls over (c3 is True) or count matches limit
        overflow = c3 or (self._total_steps % self.config.step_limit == 0)
        if overflow:
            self._trigger_overflow()

        return overflow

    def step(self, dt: float, p_pulse: float, is_gauge: bool = False) -> bool:
        """Step counter with continuous pump pressure signal over duration dt.

        Args:
            dt: Timestep (seconds).
            p_pulse: Instantaneous pressure from reciprocating pump (Pa).
            is_gauge: Whether p_pulse is gauge or absolute.

        Returns:
            True if an overflow / reversal event was triggered during this step.
        """
        # Update pulse timer if overflow is currently active
        if self._overflow_active:
            self._pulse_timer -= dt
            if self._pulse_timer <= 0.0:
                self._overflow_active = False
                self._pulse_timer = 0.0

        # Feed pump pulse into bit 0
        c0 = self.cells[0].step(p_pulse, is_gauge=is_gauge)
        overflow = False

        if c0:
            # Carry from bit 0 drives bit 1
            c1 = self.cells[1].toggle()
            c2 = self.cells[2].toggle() if c1 else False
            c3 = self.cells[3].toggle() if c2 else False

            self._total_steps += 1
            overflow = c3 or (self._total_steps % self.config.step_limit == 0)
            if overflow:
                self._trigger_overflow()

        return overflow

    def _trigger_overflow(self) -> None:
        """Activate reversal pulse and reverse associated valve if linked."""
        self._overflow_active = True
        self._pulse_timer = self.config.pulse_hold_time

        # If a directional valve is connected, trigger reverse direction
        if self.valve is not None:
            # Reverse direction by pulsing Port B with high pressure
            p_B = self.config.p_atm + self.config.reversal_pulse_pressure
            p_A = self.config.p_atm
            self.valve.step(dt=0.01, p_A=p_A, p_B=p_B)
            # Also ensure valve state switches to reverse
            if self.valve.state != -1:
                self.valve.switch_to(-1)
