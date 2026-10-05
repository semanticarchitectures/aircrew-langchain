"""
Static scenario data for Operation AIRDROP ALPHA (fictional, unclassified).

Everything here is reference data lifted from the knowledge documents.  Mutable
simulation state lives in :mod:`airdrop_alpha.domain.world`.
"""
from __future__ import annotations

from pathlib import Path

AIRCRAFT_CALLSIGN = "CONDOR 71"
ATC_FACILITY = "Alpha Approach"
ATC_FREQUENCY = "124.35 MHz"
SCENARIO_SQUAWK = "4712"

DEPARTURE_FUEL_LBS = 45_000.0
BINGO_FUEL_LBS = 32_000.0
MINIMUM_RESERVE_LBS = 8_000.0
PLANNED_BURN_LBS = 16_500.0
ALTERNATE_FIELD = "KRDW"
ALTERNATE_EXTRA_BURN_LBS = 1_800.0

FWD_CG_LIMIT = 25.0
AFT_CG_LIMIT = 35.0
DEPARTURE_CG = 31.2
#: Simplified CG model from the original: CG moves 0.6% MAC forward per
#: 1,000 lbs of cargo released.
CG_SHIFT_PER_1000_LBS = 0.6

DROP_MIN_CEILING_FT = 800
DROP_MIN_VIS_SM = 3
PLANNED_DZ_WIND = (270, 18.0)
PLANNED_CARP_NM = 4.2

# CARGO_MANIFEST_ALPHA section 1
MANIFEST: dict[str, dict] = {
    "B-01": {
        "description": "Medical Supply Kit A", "weight_lbs": 980,
        "category": "Medical / Priority",
        "special_handling": "Handle with care - fragile contents",
        "bay_position": "Bay Position 2 (forward center)",
    },
    "B-02": {
        "description": "Medical Supply Kit B", "weight_lbs": 980,
        "category": "Medical / Priority",
        "special_handling": "Handle with care - fragile contents",
        "bay_position": "Bay Position 3 (aft center)",
    },
    "B-03": {
        "description": "Field Ration Pack 1", "weight_lbs": 720,
        "category": "Consumables", "special_handling": "None",
        "bay_position": "Bay Position 4 (aft)",
    },
    "B-04": {
        "description": "Field Ration Pack 2", "weight_lbs": 720,
        "category": "Consumables", "special_handling": "None",
        "bay_position": "Bay Position 5 (aft)",
    },
    "B-05": {
        "description": "Communications Equipment", "weight_lbs": 800,
        "category": "Equipment",
        "special_handling": "Moisture-sensitive - inspect seal before drop",
        "bay_position": "Bay Position 1 (forward)",
    },
}
RECOMMENDED_DROP_SEQUENCE = ["B-03", "B-04", "B-01", "B-02", "B-05"]
PRIORITY_BUNDLES = ["B-01", "B-02"]

# MISSION_BRIEF_ALPHA section 3
WAYPOINTS: dict[str, dict] = {
    "KIRO": {"name": "KIRO (Iron Mountain AB)", "lat": 42.1, "lon": -94.2,
             "elevation_ft_msl": 910, "notes": "Departure and destination airfield."},
    "WPT ALPHA": {"name": "Waypoint ALPHA", "lat": 42.5, "lon": -95.1,
                  "planned_altitude_fl": 180, "notes": "Cruise entry waypoint."},
    "WPT BRAVO": {"name": "Waypoint BRAVO", "lat": 43.1, "lon": -95.8,
                  "planned_altitude_fl": 180,
                  "notes": "Weather watch point. FL140 alternate if turbulence reported."},
    "DZ-ALPHA": {"name": "Drop Zone ALPHA", "lat": 42.8, "lon": -95.4,
                 "elevation_ft_msl": 850, "drop_altitude_ft_agl": 1500,
                 "notes": "Primary drop zone. Within Restricted Area ROMEO-4."},
    "WPT CHARLIE": {"name": "Waypoint CHARLIE", "lat": 42.3, "lon": -94.8,
                    "planned_altitude_fl": 180, "notes": "Post-drop climb waypoint."},
    "DELTA FIELD": {"name": "Alternate DZ - Delta Field", "lat": 42.3, "lon": -94.0,
                    "elevation_ft_msl": 780, "notes": "Alternate DZ. 22 NM northeast of KIRO."},
    "KRDW": {"name": "KRDW (Divert field)", "lat": 41.8, "lon": -93.5,
             "elevation_ft_msl": 750, "notes": "Bingo fuel divert field."},
}

ROUTE = ["KIRO", "WPT ALPHA", "WPT BRAVO", "DZ-ALPHA", "WPT CHARLIE", "KIRO"]

#: Planned legs (heading, distance, time) from the Navigator's route data.
#: Planned fuel per leg is computed from the flight profile, not stored here.
LEGS: list[dict] = [
    {"from": "KIRO", "to": "WPT ALPHA", "heading_deg": 285, "distance_nm": 85, "time_min": 18},
    {"from": "WPT ALPHA", "to": "WPT BRAVO", "heading_deg": 310, "distance_nm": 110, "time_min": 24},
    {"from": "WPT BRAVO", "to": "DZ-ALPHA", "heading_deg": 295, "distance_nm": 45, "time_min": 10},
    {"from": "DZ-ALPHA", "to": "WPT CHARLIE", "heading_deg": 120, "distance_nm": 90, "time_min": 20},
    {"from": "WPT CHARLIE", "to": "KIRO", "heading_deg": 95, "distance_nm": 100, "time_min": 22},
]

# MISSION_BRIEF_ALPHA section 7
WEATHER: dict[str, dict] = {
    "KIRO": {"location": "KIRO (Iron Mountain AB)", "conditions": "Clear",
             "visibility_sm": 10, "ceiling_ft_agl": None, "wind_direction": 250,
             "wind_speed_kts": 12, "temperature_c": 8,
             "remarks": "VFR. Departure and arrival conditions well above minimums."},
    "WPT ALPHA": {"location": "Waypoint ALPHA", "conditions": "Clear",
                  "visibility_sm": 10, "ceiling_ft_agl": None, "wind_direction": 260,
                  "wind_speed_kts": 15, "temperature_c": -12,
                  "remarks": "No significant weather. Normal cruise conditions."},
    "WPT BRAVO": {"location": "Waypoint BRAVO", "conditions": "Moderate turbulence",
                  "visibility_sm": 10, "ceiling_ft_agl": None, "wind_direction": 270,
                  "wind_speed_kts": 22, "temperature_c": -15,
                  "turbulence": "Moderate at FL160-FL200. Improvement reported at FL140.",
                  "turbulence_band_fl": [160, 200],
                  "remarks": "PIREP: MOD TURB FL160-FL200. Recommend FL140 if comfort required."},
    "DZ-ALPHA": {"location": "Drop Zone ALPHA", "conditions": "Partly cloudy",
                 "visibility_sm": 8, "ceiling_ft_agl": 3500, "wind_direction": 270,
                 "wind_speed_kts": 18, "temperature_c": 5,
                 "drop_weather_mins_ceiling_ft": DROP_MIN_CEILING_FT,
                 "drop_weather_mins_vis_sm": DROP_MIN_VIS_SM,
                 "remarks": "DZ conditions above minimums."},
    "DELTA FIELD": {"location": "Alternate DZ - Delta Field", "conditions": "Clear",
                    "visibility_sm": 10, "ceiling_ft_agl": None, "wind_direction": 255,
                    "wind_speed_kts": 10, "temperature_c": 6,
                    "remarks": "Alternate DZ clear. No weather concerns."},
    "KRDW": {"location": "KRDW (Divert field)", "conditions": "Clear",
             "visibility_sm": 10, "ceiling_ft_agl": None, "wind_direction": 245,
             "wind_speed_kts": 8, "temperature_c": 7, "remarks": "Divert field clear."},
}
DEFAULT_WEATHER = {"conditions": "Clear", "visibility_sm": 10, "ceiling_ft_agl": None,
                   "wind_direction": 270, "wind_speed_kts": 15,
                   "remarks": "No specific data - scenario default returned."}

# ---------------------------------------------------------------------------
# Checklists (CHECKLISTS.md).  Each item: (item, responsible, state, condition)
# ``condition`` names a world condition (see World.check) that must hold for
# the item to be complete; None means the crew member attests to it.
# ---------------------------------------------------------------------------

CHECKLISTS: dict[str, list[tuple[str, str, str, str | None]]] = {
    "PREFLIGHT": [
        ("Cargo manifest", "LOADMASTER", "Reviewed and certified", None),
        ("Weight and balance", "LOADMASTER", "Within limits", "wb_within_limits"),
        ("Fuel quantity", "COMMANDER", "Confirmed", None),
        ("Flight plan", "COPILOT", "Filed and acknowledged by ATC", "flight_plan_approved"),
        ("Weather - departure", "COMMANDER", "Reviewed", None),
        ("Weather - enroute", "NAVIGATOR", "Reviewed", None),
        ("Weather - DZ", "COMMANDER", "Reviewed", "dz_weather_ok"),
        ("Route brief", "NAVIGATOR", "Delivered to AC", None),
        ("ATC squawk code", "COPILOT", "Set", "squawk_set"),
        ("Emergency equipment", "LOADMASTER", "Checked and stowed", None),
        ("Cargo door (closed)", "LOADMASTER", "Closed and sealed", "door_closed"),
        ("GO/NO-GO decision", "COMMANDER", "GO", "go_decision"),
    ],
    "ENGINE START": [
        ("Parking brake", "COMMANDER", "Set", None),
        ("Fuel shutoffs", "COMMANDER", "Open", None),
        ("Ignition - all engines", "COMMANDER", "Start - running", None),
        ("Oil pressure", "COMMANDER", "In the green", None),
        ("Engine temperatures", "COMMANDER", "Within limits", None),
        ("Hydraulics", "COMMANDER", "Pressure normal", None),
        ("Electrical", "COMMANDER", "All buses normal", None),
        ("Interphone check", "ALL CREW", "All stations check", None),
    ],
    "BEFORE TAKEOFF": [
        ("Departure clearance", "COPILOT", "Received", "ifr_clearance"),
        ("Transponder", "COPILOT", "Code set - ALT mode", "squawk_set"),
        ("Flight controls", "COMMANDER", "Free and correct", None),
        ("Flaps", "COMMANDER", "Takeoff setting", None),
        ("Trim", "COMMANDER", "Set for takeoff", None),
        ("Cargo door", "LOADMASTER", "Closed and locked", "door_closed"),
        ("Cargo secured", "LOADMASTER", "All bundles secure", "cargo_secure"),
        ("Crew ready", "ALL CREW", "Ready", None),
        ("Abort criteria reviewed", "COMMANDER", "Reviewed", None),
    ],
    "CLIMB/CRUISE": [
        ("Cruise altitude", "COMMANDER", "Established", None),
        ("Engine instruments", "COMMANDER", "All in normal range", "all_engines_operative"),
        ("Fuel state", "COMMANDER", "On plan", None),
        ("Navigation check", "NAVIGATOR", "On track", None),
        ("ATC position report", "COPILOT", "Reported", None),
        ("Cargo check", "LOADMASTER", "All bundles secure", "cargo_secure"),
    ],
    "DZ APPROACH": [
        ("CARP computation", "NAVIGATOR", "Complete - briefed to AC and LM", "carp_computed"),
        ("DZ weather check", "NAVIGATOR", "Above drop minimums", "dz_weather_ok"),
        ("Romeo-4 clearance", "COPILOT", "Confirmed from ATC", "romeo4_clearance"),
        ("Airspeed - drop limits", "COPILOT", "120-165 KIAS", "drop_airspeed_ok"),
        ("Drop altitude", "COMMANDER", "2,350 ft MSL", "at_drop_altitude"),
        ("Cargo manifest - final", "LOADMASTER", "Drop sequence confirmed", None),
        ("Bundle attachments", "LOADMASTER", "All straps checked", "cargo_secure"),
        ("Cargo door seal", "LOADMASTER", "Inspected", None),
        ("Cargo bay - personnel", "LOADMASTER", "Bay clear", None),
        ("Interphone", "ALL CREW", "All stations check", None),
        ("Door open authorization", "COMMANDER", "Authorized", "door_open_authorized"),
        ("Cargo door", "LOADMASTER", "Open", "door_open"),
    ],
    "POST-AIRDROP": [
        ("All bundles released / accounted", "LOADMASTER", "Confirmed", "drop_resolved"),
        ("Cargo door", "LOADMASTER", "Closed and locked", "door_closed"),
        ("Cargo bay - clear", "LOADMASTER", "Inspected", None),
        ("Post-drop W&B", "LOADMASTER", "Within limits", "wb_within_limits"),
        ("Post-drop fuel state", "COMMANDER", "Checked", None),
        ("ATC - exit Romeo-4", "COPILOT", "Reported", None),
        ("Route to recovery", "NAVIGATOR", "Confirmed", None),
    ],
    "BEFORE LANDING": [
        ("Approach clearance", "COPILOT", "Received", "approach_clearance"),
        ("Cargo door", "LOADMASTER", "Closed and locked", "door_closed"),
        ("All cargo secured", "LOADMASTER", "Secured", "cargo_secure"),
        ("Landing gear", "COMMANDER", "Down and locked", None),
        ("Flaps", "COMMANDER", "Landing setting", None),
        ("Fuel state", "COMMANDER", "Sufficient", "fuel_above_reserve"),
        ("Crew seated and secured", "ALL CREW", "Secured", None),
    ],
    "SHUTDOWN": [
        ("Throttles", "COMMANDER", "Idle", None),
        ("Fuel shutoffs", "COMMANDER", "Closed", None),
        ("Ignition", "COMMANDER", "Off", None),
        ("Transponder", "COPILOT", "Standby", None),
        ("Cargo bay secure", "LOADMASTER", "Confirmed", None),
    ],
}

#: Names the original prompts and tools used for the same checklists.
CHECKLIST_ALIASES = {
    "TAKEOFF": "BEFORE TAKEOFF",
    "LANDING": "BEFORE LANDING",
    "CRUISE": "CLIMB/CRUISE",
    "CLIMB": "CLIMB/CRUISE",
    "POST AIRDROP": "POST-AIRDROP",
    "DZ": "DZ APPROACH",
    "ENGINE_START": "ENGINE START",
}

#: A checklist cannot be run until these are complete.
CHECKLIST_PREREQUISITES = {
    "ENGINE START": ["PREFLIGHT"],
    "BEFORE TAKEOFF": ["ENGINE START"],
}

CLEARANCE_TYPES = (
    "IFR", "TAXI", "TAKEOFF", "ALTITUDE", "ROMEO4_TRANSIT",
    "DIRECT", "APPROACH", "LANDING", "OTHER",
)

DOCUMENTS: dict[str, str] = {
    "AC_SOP": "AC_SOP.md",
    "CP_SOP": "CP_SOP.md",
    "NAV_SOP": "NAV_SOP.md",
    "LM_SOP": "LM_SOP.md",
    "ATC_SOP": "ATC_SOP.md",
    "ATC_PHRASEOLOGY": "ATC_PHRASEOLOGY.md",
    "EMERGENCY_PROCEDURES": "EMERGENCY_PROCEDURES.md",
    "CHECKLISTS": "CHECKLISTS.md",
    "MISSION_BRIEF": "MISSION_BRIEF_ALPHA.md",
    "CARGO_MANIFEST": "CARGO_MANIFEST_ALPHA.md",
}


def knowledge_dir() -> Path:
    """Locate the knowledge/ directory (repo root when run from a checkout)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "knowledge"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "knowledge"
