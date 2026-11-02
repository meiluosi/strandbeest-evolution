"""Thermodynamic and fluid mechanics constants in SI units."""

# Specific gas constant for dry air [J/(kg*K)]
R_AIR: float = 287.05

# Ratio of specific heats for air (diatomic ideal gas) [-]
GAMMA_AIR: float = 1.4

# Specific heat capacity at constant pressure [J/(kg*K)]
CP_AIR: float = R_AIR * GAMMA_AIR / (GAMMA_AIR - 1.0)  # ~1004.675

# Specific heat capacity at constant volume [J/(kg*K)]
CV_AIR: float = R_AIR / (GAMMA_AIR - 1.0)  # ~717.625

# Standard reference conditions for ISO 6358 pneumatic standards
# Reference temperature (20 °C) [K]
T_0: float = 293.15

# Reference pressure (1 bar / 100 kPa) [Pa]
P_0: float = 100_000.0

# Reference air density at 20 °C, 100 kPa [kg/m^3]
RHO_0: float = 1.204

# Standard atmospheric pressure [Pa]
P_ATM: float = 101_325.0

# Critical pressure ratio for sonic choked flow (ISO 6358 b-factor) [-]
DEFAULT_CRITICAL_PRESSURE_RATIO: float = 0.528

# Default polytropic exponent for air compression in reciprocating pumps [-]
DEFAULT_POLYTROPIC_EXPONENT: float = 1.25
