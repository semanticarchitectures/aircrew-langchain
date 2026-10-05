"""
CONDOR 71 flight performance model (pure functions, no state).

Ported from airdrop-alpha ``tools/flight_model.py``.  The ISA atmosphere and
the per-phase performance tables are unchanged; three things were reconciled
so the simulation has one consistent set of numbers (see README, "What was
reconciled"):

* Weights follow CARGO_MANIFEST_ALPHA (108,000 lbs empty + 2,400 lbs crew),
  not the real C-130J operating weight the original flight model used.
* Fuel flows carry one calibration factor so the nominal mission profile burns
  the 16,500 lbs that MISSION_BRIEF_ALPHA plans for.
* The stall-speed reference is set so the 130 KIAS drop speed is inside the
  safe envelope at drop weight (the original reported it as outside).
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# ISA Standard Atmosphere (ICAO Doc 7488)
# ---------------------------------------------------------------------------

_T0 = 288.15      # K, sea-level temperature
_P0 = 101_325.0   # Pa, sea-level pressure
_L = 0.0065       # K/m, tropospheric lapse rate
_R = 287.058      # J/kg/K
_G = 9.80665      # m/s^2
_FT = 0.3048      # m per foot


def isa(altitude_ft: float) -> tuple[float, float, float]:
    """Return (temperature K, pressure Pa, density kg/m^3) at pressure altitude."""
    h = max(0.0, altitude_ft) * _FT
    if h <= 11_000.0:
        t = _T0 - _L * h
        p = _P0 * (t / _T0) ** (_G / (_L * _R))
    else:
        t = 216.65
        p = _P0 * (216.65 / _T0) ** (_G / (_L * _R)) * math.exp(
            -_G * (h - 11_000.0) / (_R * t)
        )
    return t, p, p / (_R * t)


def cas_to_tas(cas_kts: float, altitude_ft: float) -> float:
    _, _, rho = isa(altitude_ft)
    _, _, rho0 = isa(0.0)
    return round(cas_kts * math.sqrt(rho0 / rho), 1)


def density_altitude(pressure_alt_ft: float, oat_c: float | None = None) -> float:
    t_isa, _, _ = isa(pressure_alt_ft)
    t_actual = (oat_c + 273.15) if oat_c is not None else t_isa
    return round(pressure_alt_ft + 118.8 * (t_actual - t_isa))


# ---------------------------------------------------------------------------
# Performance tables
# ---------------------------------------------------------------------------

FLIGHT_PHASES = (
    "ground", "takeoff", "climb", "cruise", "descent",
    "holding", "dz_approach", "landing",
)

#: All-engine fuel flow (lbs/hr) by phase, before calibration.
_FUEL_FLOW_PPH = {
    "ground": 2_400,
    "takeoff": 18_000,
    "climb": 14_500,
    "cruise": 11_600,
    "descent": 6_000,
    "holding": 10_000,
    "dz_approach": 13_500,
    "landing": 8_000,
}

#: Scales every phase so the nominal AIRDROP ALPHA profile burns 16,500 lbs
#: (MISSION_BRIEF_ALPHA section 6).  Checked by tests/test_scenario.py.
FUEL_CALIBRATION = 0.8652

PHASE_KIAS = {
    "ground": 0.0,
    "takeoff": 140.0,
    "climb": 250.0,
    "cruise": 211.0,
    "descent": 250.0,
    "holding": 200.0,
    "dz_approach": 130.0,
    "landing": 120.0,
}

#: Representative altitude (ft MSL) by phase.  Cruise uses the cleared cruise
#: altitude instead; DZ approach is 1,500 ft AGL over an 850 ft DZ.
PHASE_ALT_FT = {
    "ground": 0.0,
    "takeoff": 0.0,
    "climb": 5_000.0,
    "descent": 10_000.0,
    "holding": 10_000.0,
    "dz_approach": 2_350.0,
    "landing": 500.0,
}

VERT_RATE_FPM = {"climb": 1_800.0, "descent": -1_500.0}

ENGINE_FACTOR = {4: 1.00, 3: 0.82, 2: 0.60, 1: 0.34, 0: 0.0}
VMC_KIAS = {4: 0.0, 3: 85.0, 2: 95.0, 1: 0.0, 0: 0.0}
CEILING_DA_FT = {4: 28_000.0, 3: 20_000.0, 2: 12_000.0, 1: 3_000.0, 0: 0.0}

VREF_WEIGHT_LBS = 160_000.0
VS1_REF_KIAS = 98.0
VMO_KIAS = 315.0

EMPTY_WEIGHT_LBS = 108_000.0
CREW_WEIGHT_LBS = 2_400.0
MAX_GROSS_WEIGHT_LBS = 175_000.0

DOOR_OPEN_MIN_KIAS = 120.0
DOOR_OPEN_MAX_KIAS = 165.0

PLANNED_CRUISE_FT = 18_000.0


def stall_speed(gross_weight_lbs: float) -> float:
    """Stall speed (KIAS) at a given gross weight."""
    return round(VS1_REF_KIAS * math.sqrt(gross_weight_lbs / VREF_WEIGHT_LBS), 1)


def min_safe_speed(gross_weight_lbs: float, engines: int) -> float:
    """Minimum safe operating speed: the higher of 1.3 x stall and VMC."""
    return round(max(1.3 * stall_speed(gross_weight_lbs), VMC_KIAS.get(engines, 0.0)), 1)


def fuel_flow_pph(phase: str, engines: int = 4, cruise_altitude_ft: float = PLANNED_CRUISE_FT) -> float:
    """
    Fuel flow (lbs/hr) for a phase.

    Cruise below the planned FL180 burns slightly more: +0.75% per 1,000 ft.
    """
    base = _FUEL_FLOW_PPH.get(phase, _FUEL_FLOW_PPH["cruise"]) * FUEL_CALIBRATION
    if phase == "cruise":
        below = max(0.0, PLANNED_CRUISE_FT - cruise_altitude_ft) / 1_000.0
        base *= 1.0 + 0.0075 * below
    return base * ENGINE_FACTOR.get(engines, 1.0)


def phase_altitude(phase: str, cruise_altitude_ft: float) -> float:
    if phase == "cruise":
        return cruise_altitude_ft
    return PHASE_ALT_FT.get(phase, 0.0)
