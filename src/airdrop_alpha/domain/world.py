"""
The simulated world: one serialisable state object and every operation on it.

This module is framework-free.  It replaces the module-level globals scattered
across the original ``tools/`` package (two fuel states, cargo manifest, door
state, clearance log, ...) with a single :class:`World` that the graph
checkpoints as plain JSON.

Authority is enforced here, not in prompts.  Every state-changing operation
takes the acting callsign, checks it against :data:`PERMISSIONS`, then checks
the operation's own preconditions.  A refused operation returns a dict with
``denied: True`` plus the rule that fired, and is written to the journal so the
scorecard can count it.
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from . import data, performance as perf

CREW = ("COMMANDER", "COPILOT", "NAVIGATOR", "LOADMASTER")

#: A timeline hold puts the aircraft in a holding pattern only from these
#: phases.  On the ground it simply waits; on the drop run it orbits at drop
#: altitude and speed, so the door limits still hold.
_HOLDABLE_PHASES = ("takeoff", "climb", "cruise", "descent")
ROLES = CREW + ("ATC",)

#: Which callsigns may perform each state-changing action.
PERMISSIONS: dict[str, tuple[str, ...]] = {
    "make_go_nogo": ("COMMANDER",),
    "authorize_door_open": ("COMMANDER",),
    "authorize_airdrop": ("COMMANDER",),
    "revoke_authorizations": ("COMMANDER",),
    "declare_emergency": ("COMMANDER",),
    "abort_mission": ("COMMANDER",),
    "file_flight_plan": ("COPILOT",),
    "set_transponder": ("COPILOT",),
    "execute_checklist": ("COPILOT",),
    "set_cruise_altitude": ("COPILOT",),
    "calculate_carp": ("NAVIGATOR",),
    "update_route": ("NAVIGATOR",),
    "plan_drop_sequence": ("LOADMASTER",),
    "open_door": ("LOADMASTER",),
    "close_door": ("LOADMASTER",),
    "execute_airdrop": ("LOADMASTER",),
    "abort_airdrop": ("LOADMASTER",),
    "clear_abort": ("LOADMASTER",),
    "secure_cargo": ("LOADMASTER",),
    "approve_flight_plan": ("ATC",),
    "issue_clearance": ("ATC",),
    "cancel_clearance": ("ATC",),
    "issue_hold": ("ATC",),
    "provide_weather_advisory": ("ATC",),
    "issue_traffic_advisory": ("ATC",),
    "coordinate_emergency": ("ATC",),
}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class Bundle(BaseModel):
    description: str
    weight_lbs: float
    category: str
    special_handling: str
    bay_position: str
    released: bool = False
    released_at_min: float | None = None
    release_order: int | None = None
    #: Minutes from the start of the release window at the moment of release
    #: (negative: before the CARP).  None until released.
    minutes_from_carp: float | None = None
    #: Whether the release fell inside the window.  An early or late release is
    #: physically possible, so it is allowed and scored, not refused.
    on_target: bool | None = None
    strap_ok: bool = True
    seal_ok: bool = True


class Aircraft(BaseModel):
    flight_phase: str = "ground"
    holding: bool = False
    landed: bool = False
    cruise_altitude_ft: float = perf.PLANNED_CRUISE_FT
    heading_deg: float = 285.0
    fuel_lbs: float = data.DEPARTURE_FUEL_LBS
    engines_running: bool = False
    inoperative_engines: list[int] = Field(default_factory=list)
    squawk: str | None = None
    hold_minutes: float = 0.0
    turbulence_exposure_min: float = 0.0
    bingo_reported: bool = False


class Cargo(BaseModel):
    bundles: dict[str, Bundle] = Field(default_factory=dict)
    door: str = "closed"  # open | closed | jammed
    aborted: bool = False
    abort_reason: str | None = None
    cg_offset_pct: float = 0.0
    planned_sequence: list[str] = Field(default_factory=lambda: list(data.RECOMMENDED_DROP_SEQUENCE))


class Authority(BaseModel):
    go_nogo: list[dict] = Field(default_factory=list)
    door_open_authorized: bool = False
    drop_authorized: bool = False
    emergencies: list[dict] = Field(default_factory=list)
    mission_aborted: bool = False
    mission_abort_reason: str | None = None


class AtcState(BaseModel):
    flight_plan: dict | None = None
    clearances: list[dict] = Field(default_factory=list)
    advisories: list[dict] = Field(default_factory=list)
    traffic_conflict_romeo4: bool = False


class NavState(BaseModel):
    route: list[str] = Field(default_factory=lambda: list(data.ROUTE))
    carp: dict | None = None
    amendments: list[dict] = Field(default_factory=list)
    passed: list[str] = Field(default_factory=list)
    #: Nominal scenario minute at which each waypoint is passed.
    waypoint_times: dict[str, float] = Field(default_factory=dict)
    #: Nominal fuel curve as [minute, fuel_lbs] breakpoints.
    fuel_curve: list[list[float]] = Field(default_factory=list)
    #: Nominal [opens, closes] sim minutes of the release window at the CARP.
    drop_window: list[float] = Field(default_factory=list)
    #: Minutes the whole timeline has slipped because of holds.
    timeline_offset_min: float = 0.0


class World(BaseModel):
    clock_min: float = 0.0
    aircraft: Aircraft = Field(default_factory=Aircraft)
    cargo: Cargo = Field(default_factory=Cargo)
    authority: Authority = Field(default_factory=Authority)
    atc: AtcState = Field(default_factory=AtcState)
    nav: NavState = Field(default_factory=NavState)
    checklists: dict[str, float] = Field(default_factory=dict)
    weather_overrides: dict[str, dict] = Field(default_factory=dict)
    hazards: list[dict] = Field(default_factory=list)
    #: Audit entries produced since the world was loaded.  Not part of the
    #: persisted state: the graph drains it into its ``events`` channel.
    journal: list[dict] = Field(default_factory=list, exclude=True)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def new(
        cls,
        *,
        departure_fuel_lbs: float = data.DEPARTURE_FUEL_LBS,
        waypoint_times: dict[str, float] | None = None,
        fuel_curve: list[list[float]] | None = None,
        hazards: list[dict] | None = None,
        drop_window: list[float] | None = None,
    ) -> "World":
        world = cls()
        world.aircraft.fuel_lbs = departure_fuel_lbs
        world.cargo.bundles = {bid: Bundle(**spec) for bid, spec in data.MANIFEST.items()}
        world.nav.waypoint_times = dict(waypoint_times or {})
        world.nav.fuel_curve = [list(p) for p in (fuel_curve or [])]
        world.hazards = list(hazards or [])
        world.nav.drop_window = [float(t) for t in (drop_window or [])]
        return world

    # ------------------------------------------------------------------
    # Journal and guards
    # ------------------------------------------------------------------

    def _log(self, type_: str, **fields: Any) -> None:
        self.journal.append({"type": type_, "t": round(self.clock_min, 2), **fields})

    def _deny(self, actor: str, action: str, rule: str, reason: str, **extra: Any) -> dict:
        self._log("guard_denied", actor=actor, action=action, rule=rule, reason=reason)
        return {"ok": False, "denied": True, "rule": rule, "reason": reason, **extra}

    def _role(self, actor: str, action: str) -> dict | None:
        allowed = PERMISSIONS[action]
        if actor not in allowed:
            return self._deny(
                actor, action, "role_authority",
                f"{action} is reserved for {', '.join(allowed)}; {actor} has no authority to do it.",
            )
        return None

    def _did(self, actor: str, action: str, **detail: Any) -> None:
        self._log("action", actor=actor, action=action, **detail)

    def drain_journal(self) -> list[dict]:
        entries, self.journal = self.journal, []
        return entries

    # ------------------------------------------------------------------
    # Derived quantities
    # ------------------------------------------------------------------

    @property
    def airborne(self) -> bool:
        return self.aircraft.flight_phase != "ground"

    @property
    def effective_phase(self) -> str:
        """The phase the aircraft is physically flying (holds override the plan)."""
        if self.aircraft.holding and self.aircraft.flight_phase in _HOLDABLE_PHASES:
            return "holding"
        return self.aircraft.flight_phase

    @property
    def engines_operative(self) -> int:
        return 4 - len(self.aircraft.inoperative_engines)

    @property
    def altitude_ft(self) -> float:
        phase = self.effective_phase
        if phase == "holding":
            return min(self.aircraft.cruise_altitude_ft, perf.PHASE_ALT_FT["holding"])
        return perf.phase_altitude(phase, self.aircraft.cruise_altitude_ft)

    @property
    def airspeed_kias(self) -> float:
        return perf.PHASE_KIAS.get(self.effective_phase, 0.0)

    @property
    def cargo_aboard_lbs(self) -> float:
        return sum(b.weight_lbs for b in self.cargo.bundles.values() if not b.released)

    @property
    def cargo_released_lbs(self) -> float:
        return sum(b.weight_lbs for b in self.cargo.bundles.values() if b.released)

    @property
    def gross_weight_lbs(self) -> float:
        return perf.EMPTY_WEIGHT_LBS + perf.CREW_WEIGHT_LBS + self.aircraft.fuel_lbs + self.cargo_aboard_lbs

    def _cg(self, released_lbs: float | None = None) -> float:
        released = self.cargo_released_lbs if released_lbs is None else released_lbs
        return round(
            data.DEPARTURE_CG - released / 1000.0 * data.CG_SHIFT_PER_1000_LBS + self.cargo.cg_offset_pct, 1
        )

    @property
    def cg_pct_mac(self) -> float:
        return self._cg()

    @staticmethod
    def _cg_ok(cg: float) -> bool:
        return data.FWD_CG_LIMIT <= cg <= data.AFT_CG_LIMIT

    @property
    def fuel_flow_pph(self) -> float:
        if self.aircraft.landed:
            return 0.0
        return perf.fuel_flow_pph(self.effective_phase, self.engines_operative, self.aircraft.cruise_altitude_ft)

    def has_clearance(self, clearance_type: str) -> bool:
        return any(
            c["type"] == clearance_type and not c.get("cancelled") for c in self.atc.clearances
        )

    def weather_at(self, location: str) -> dict:
        key = location.strip().upper()
        base = dict(data.WEATHER.get(key, data.DEFAULT_WEATHER))
        base.update(self.weather_overrides.get(key, {}))
        base.setdefault("location", location)
        return base

    # ------------------------------------------------------------------
    # Time (called only by the scheduler)
    # ------------------------------------------------------------------

    def advance_time(self, minutes: float) -> None:
        """Move the clock forward, burning fuel and accruing hazard exposure."""
        if minutes <= 0:
            return
        start, end = self.clock_min, self.clock_min + minutes
        burned = self.fuel_flow_pph * minutes / 60.0
        self.aircraft.fuel_lbs = max(0.0, self.aircraft.fuel_lbs - burned)
        if self.aircraft.holding:
            self.aircraft.hold_minutes += minutes

        if self.effective_phase == "cruise":
            fl = self.aircraft.cruise_altitude_ft / 100.0
            offset = self.nav.timeline_offset_min
            for hazard in self.hazards:
                if hazard.get("type") != "turbulence":
                    continue
                lo, hi = hazard["band_fl"]
                overlap = min(end, hazard["to"] + offset) - max(start, hazard["from"] + offset)
                if overlap > 0 and lo <= fl <= hi:
                    self.aircraft.turbulence_exposure_min += overlap

        self.clock_min = end
        if (
            not self.aircraft.bingo_reported
            and self.airborne
            and self.aircraft.fuel_lbs <= data.BINGO_FUEL_LBS
            and "DZ-ALPHA" not in self.nav.passed
        ):
            self.aircraft.bingo_reported = True
            self._log("bingo_fuel", fuel_lbs=round(self.aircraft.fuel_lbs))
        if self.aircraft.fuel_lbs <= 0 and self.airborne:
            self._log("fuel_exhausted")

    def set_flight_phase(self, phase: str, heading_deg: float | None = None) -> None:
        if phase not in perf.FLIGHT_PHASES:
            raise ValueError(f"unknown flight phase {phase!r}")
        previous = self.aircraft.flight_phase
        self.aircraft.flight_phase = phase
        self.aircraft.holding = False
        if heading_deg is not None:
            self.aircraft.heading_deg = float(heading_deg) % 360
        if phase == "ground" and previous != "ground":
            self.aircraft.landed = True
        if phase != "ground" and self.cargo.door == "open" and self.airspeed_kias > perf.DOOR_OPEN_MAX_KIAS:
            self._log("limit_exceeded", limit="door_open_airspeed",
                      detail=f"Cargo door open at {self.airspeed_kias:.0f} KIAS (limit {perf.DOOR_OPEN_MAX_KIAS:.0f}).")
        self._log("flight_phase", previous=previous, phase=phase)

    # ------------------------------------------------------------------
    # Conditions (used by checklists, timeline gates and the scorecard)
    # ------------------------------------------------------------------

    def check(self, condition: str) -> bool:
        if condition.startswith("checklist:"):
            return canonical_checklist(condition.split(":", 1)[1]) in self.checklists
        try:
            return bool(CONDITIONS[condition][2](self))
        except KeyError:
            raise KeyError(f"unknown condition {condition!r}") from None

    # ------------------------------------------------------------------
    # Shared instrument reads
    # ------------------------------------------------------------------

    def aircraft_state(self) -> dict:
        alt = self.altitude_ft
        kias = self.airspeed_kias
        return {
            "sim_time_min": round(self.clock_min, 1),
            "phase": self.effective_phase,
            "planned_phase": self.aircraft.flight_phase,
            "holding": self.aircraft.holding,
            "altitude_ft": round(alt),
            "altitude_fl": f"FL{int(alt / 100):03d}" if alt >= 5000 else f"{round(alt)} ft MSL",
            "cleared_cruise_altitude": f"FL{int(self.aircraft.cruise_altitude_ft / 100):03d}",
            "density_altitude_ft": perf.density_altitude(alt),
            "airspeed_kias": round(kias),
            "airspeed_ktas": round(perf.cas_to_tas(kias, alt)),
            "heading_deg": round(self.aircraft.heading_deg),
            "fuel_lbs": round(self.aircraft.fuel_lbs),
            "fuel_flow_pph": round(self.fuel_flow_pph),
            "cargo_lbs": round(self.cargo_aboard_lbs),
            "gross_weight_lbs": round(self.gross_weight_lbs),
            "cg_pct_mac": self.cg_pct_mac,
            "engines_running": self.aircraft.engines_running,
            "engines_operative": self.engines_operative,
            "inoperative_engines": list(self.aircraft.inoperative_engines),
            "climb_rate_fpm": perf.VERT_RATE_FPM.get(self.effective_phase, 0.0),
            "squawk": self.aircraft.squawk,
            "cargo_door": self.cargo.door,
            **({"drop_run": self.release_timing()} if self.effective_phase == "dz_approach"
               and self.release_timing() else {}),
        }

    def release_timing(self) -> dict | None:
        """Where the aircraft is relative to the release window at the CARP."""
        if len(self.nav.drop_window) != 2:
            return None
        opens = self.nav.drop_window[0] + self.nav.timeline_offset_min
        closes = self.nav.drop_window[1] + self.nav.timeline_offset_min
        clock = self.clock_min
        in_window = opens <= clock <= closes
        nm_per_min = perf.cas_to_tas(perf.PHASE_KIAS["dz_approach"], perf.PHASE_ALT_FT["dz_approach"]) / 60.0
        miss_min = 0.0 if in_window else (opens - clock if clock < opens else clock - closes)
        if in_window:
            position = "at the CARP, inside the release window"
        elif clock < opens:
            position = f"{opens - clock:g} min before the CARP (about {miss_min * nm_per_min:.1f} NM short)"
        else:
            position = f"{clock - closes:g} min past the release window (about {miss_min * nm_per_min:.1f} NM long)"
        return {
            "minutes_to_carp": round(max(0.0, opens - clock), 2),
            "minutes_from_carp": round(clock - opens, 2),
            "in_release_window": in_window,
            "miss_distance_nm": round(miss_min * nm_per_min, 1),
            "position": position,
        }

    def performance_envelope(self) -> dict:
        gw, eng = self.gross_weight_lbs, self.engines_operative
        vs1, v_min = perf.stall_speed(gw), perf.min_safe_speed(gw, eng)
        cas, da = self.airspeed_kias, perf.density_altitude(self.altitude_ft)
        ceiling = perf.CEILING_DA_FT[eng]
        return {
            "gross_weight_lbs": round(gw),
            "stall_speed_kias": vs1,
            "min_safe_speed_kias": v_min,
            "max_speed_kias": perf.VMO_KIAS,
            "service_ceiling_da_ft": ceiling,
            "current_density_alt_ft": da,
            "within_ceiling": da < ceiling,
            "engines_operative": eng,
            "airspeed_within_envelope": cas == 0.0 or v_min <= cas <= perf.VMO_KIAS,
            "margin_to_stall_kias": round(cas - vs1, 1) if cas > 0 else None,
            "door_open_speed_limits_kias": [perf.DOOR_OPEN_MIN_KIAS, perf.DOOR_OPEN_MAX_KIAS],
        }

    def fuel_state(self) -> dict:
        """Single fuel source of truth (the original kept two that disagreed)."""
        fuel, ff = self.aircraft.fuel_lbs, self.fuel_flow_pph
        planned = self.planned_fuel_now()
        status = "NORMAL"
        if fuel <= data.MINIMUM_RESERVE_LBS:
            status = "BELOW MINIMUM RESERVE - EMERGENCY"
        elif fuel <= data.BINGO_FUEL_LBS and "DZ-ALPHA" not in self.nav.passed:
            status = "BINGO - DIVERT TO KRDW"
        out = {
            "current_fuel_lbs": round(fuel),
            "departure_fuel_lbs": round(data.DEPARTURE_FUEL_LBS),
            "bingo_fuel_lbs": round(data.BINGO_FUEL_LBS),
            "bingo_applies": "DZ-ALPHA" not in self.nav.passed,
            "minimum_reserve_lbs": round(data.MINIMUM_RESERVE_LBS),
            "planned_fuel_now_lbs": round(planned) if planned is not None else None,
            "variance_vs_plan_lbs": round(planned - fuel) if planned is not None else None,
            "variance_note": "positive means more fuel burned than planned",
            "planned_arrival_fuel_lbs": round(self.nav.fuel_curve[-1][1]) if self.nav.fuel_curve else None,
            "fuel_flow_pph": round(ff),
            "status": status,
            "alternate_field": data.ALTERNATE_FIELD,
            "alternate_extra_burn_lbs": round(data.ALTERNATE_EXTRA_BURN_LBS),
        }
        if ff > 0:
            hours = fuel / ff
            tas = perf.cas_to_tas(self.airspeed_kias, self.altitude_ft)
            usable = max(0.0, fuel - data.MINIMUM_RESERVE_LBS) / ff
            out.update({
                "endurance_minutes": round(hours * 60, 1),
                "endurance_range_nm": round(hours * tas),
                "usable_endurance_minutes": round(usable * 60, 1),
                "usable_range_nm": round(usable * tas),
            })
        return out

    def performance_at(self, altitude_ft: float, weight_lbs: float | None = None, oat_c: float | None = None) -> dict:
        gw = float(weight_lbs) if weight_lbs is not None else self.gross_weight_lbs
        eng = self.engines_operative
        da = perf.density_altitude(altitude_ft, oat_c)
        ceiling = perf.CEILING_DA_FT[eng]
        ff_there = perf.fuel_flow_pph("cruise", eng, altitude_ft)
        ff_plan = perf.fuel_flow_pph("cruise", eng, perf.PLANNED_CRUISE_FT)
        climb = max(0.0, perf.VERT_RATE_FPM["climb"] - (gw - perf.VREF_WEIGHT_LBS) / 1000.0 * 5.0)
        return {
            "query_altitude_ft": round(altitude_ft),
            "density_altitude_ft": da,
            "gross_weight_lbs": round(gw),
            "cruise_cas_kias": round(perf.PHASE_KIAS["cruise"]),
            "cruise_tas_ktas": round(perf.cas_to_tas(perf.PHASE_KIAS["cruise"], altitude_ft)),
            "cruise_fuel_flow_pph": round(ff_there),
            "fuel_flow_change_vs_fl180_pph": round(ff_there - ff_plan),
            "time_impact": "Negligible (under 1 minute); scheduled waypoint times are unchanged.",
            "estimated_climb_rate_fpm": round(climb),
            "stall_speed_kias": perf.stall_speed(gw),
            "min_safe_speed_kias": perf.min_safe_speed(gw, eng),
            "service_ceiling_da_ft": ceiling,
            "above_service_ceiling": da >= ceiling,
        }

    def engine_out_performance(self) -> dict:
        eng = self.engines_operative
        da = perf.density_altitude(self.altitude_ft)
        actions = {
            4: ["All engines operative. No action required."],
            3: ["Identify and confirm the failed engine; feather the propeller.",
                f"Maintain airspeed above {perf.VMC_KIAS[3]:.0f} KIAS (VMC).",
                "Advise ATC (PAN-PAN) through COPILOT."],
            2: ["Two engines inoperative: declare MAYDAY.",
                "Begin descent if above the reduced service ceiling.",
                "Divert to the nearest suitable airfield."],
        }.get(eng, ["Aircraft cannot maintain altitude: declare MAYDAY and prepare for a forced landing."])
        return {
            "engines_operative": eng,
            "inoperative_engines": list(self.aircraft.inoperative_engines),
            "fuel_flow_pph": round(self.fuel_flow_pph),
            "service_ceiling_da_ft": perf.CEILING_DA_FT[eng],
            "current_density_alt_ft": da,
            "can_maintain_current_altitude": da < perf.CEILING_DA_FT[eng],
            "min_control_speed_kias": perf.VMC_KIAS.get(eng, 0.0),
            "recommended_actions": actions,
        }

    def mission_brief(self) -> dict:
        return {
            "mission_name": "Operation AIRDROP ALPHA",
            "aircraft_callsign": data.AIRCRAFT_CALLSIGN,
            "objective": "Deliver five bundles of humanitarian supplies to Drop Zone ALPHA "
                         "via low-altitude airdrop. Return to Iron Mountain Air Base (KIRO).",
            "route": " > ".join(self.nav.route),
            "cruise_altitude": "FL180 (FL140 alternate if turbulence at BRAVO)",
            "drop_altitude_ft_agl": 1500,
            "dz_coords": "42.8N / 95.4W",
            "drop_run_heading_deg": 90,
            "total_bundles": len(self.cargo.bundles),
            "total_cargo_lbs": round(sum(b.weight_lbs for b in self.cargo.bundles.values())),
            "priority_cargo": "B-01, B-02 (medical)",
            "departure_fuel_lbs": round(data.DEPARTURE_FUEL_LBS),
            "bingo_fuel_lbs": round(data.BINGO_FUEL_LBS),
            "planned_burn_lbs": round(data.PLANNED_BURN_LBS),
            "success_criteria": "All 5 bundles released within 0.5 NM of DZ-ALPHA center. "
                                "Aircraft and crew return safely to KIRO.",
            "abort_criteria_summary": "Fuel below bingo before DZ; DZ weather below minimums; "
                                      "ATC denies Romeo-4 transit; cargo W&B unresolvable; "
                                      "Loadmaster calls airdrop abort.",
            "atc": f"{data.ATC_FACILITY} on {data.ATC_FREQUENCY}; all ATC traffic through COPILOT.",
        }

    # ------------------------------------------------------------------
    # COMMANDER
    # ------------------------------------------------------------------

    def make_go_nogo(self, actor: str, decision: str, reason: str) -> dict:
        if (denied := self._role(actor, "make_go_nogo")):
            return denied
        value = decision.strip().upper().replace("NOGO", "NO-GO").replace("NO GO", "NO-GO")
        if value not in ("GO", "NO-GO"):
            return {"ok": False, "error": f"Invalid decision {decision!r}. Must be 'GO' or 'NO-GO'."}
        entry = {"log_id": len(self.authority.go_nogo) + 1, "decision": value,
                 "reason": reason, "t": round(self.clock_min, 2)}
        self.authority.go_nogo.append(entry)
        if value == "NO-GO":
            self.authority.door_open_authorized = False
            self.authority.drop_authorized = False
        self._did(actor, "make_go_nogo", decision=value, reason=reason)
        return {"ok": True, "logged": True, **entry}

    def authorize_door_open(self, actor: str) -> dict:
        if (denied := self._role(actor, "authorize_door_open")):
            return denied
        if self.authority.mission_aborted:
            return self._deny(actor, "authorize_door_open", "mission_aborted", "The mission has been aborted.")
        self.authority.door_open_authorized = True
        self._did(actor, "authorize_door_open", romeo4_clearance=self.has_clearance("ROMEO4_TRANSIT"),
                  carp_computed=self.nav.carp is not None)
        return {"ok": True, "door_open_authorized": True}

    def authorize_airdrop(self, actor: str) -> dict:
        if (denied := self._role(actor, "authorize_airdrop")):
            return denied
        if self.authority.mission_aborted:
            return self._deny(actor, "authorize_airdrop", "mission_aborted", "The mission has been aborted.")
        if self.cargo.aborted:
            return self._deny(
                actor, "authorize_airdrop", "abort_in_effect",
                "A Loadmaster airdrop abort is in effect. LOADMASTER must resolve the condition "
                "and clear the abort before the drop can be re-authorized.",
            )
        self.authority.drop_authorized = True
        self._did(actor, "authorize_airdrop", door=self.cargo.door,
                  romeo4_clearance=self.has_clearance("ROMEO4_TRANSIT"))
        return {"ok": True, "drop_authorized": True}

    def revoke_authorizations(self, actor: str, reason: str) -> dict:
        if (denied := self._role(actor, "revoke_authorizations")):
            return denied
        self.authority.door_open_authorized = False
        self.authority.drop_authorized = False
        self._did(actor, "revoke_authorizations", reason=reason)
        return {"ok": True, "door_open_authorized": False, "drop_authorized": False, "reason": reason}

    def declare_emergency(self, actor: str, emergency_type: str, description: str) -> dict:
        if (denied := self._role(actor, "declare_emergency")):
            return denied
        entry = {"emergency_id": len(self.authority.emergencies) + 1, "type": emergency_type,
                 "description": description, "t": round(self.clock_min, 2)}
        self.authority.emergencies.append(entry)
        self._did(actor, "declare_emergency", emergency_type=emergency_type)
        return {
            "ok": True, **entry, "squawk": "7700", "guard_frequency": "121.5 MHz",
            "action_items": [
                "COPILOT transmits MAYDAY or PAN-PAN on 124.35 MHz and sets squawk 7700.",
                "NAVIGATOR computes the nearest suitable airfield and fuel state.",
                "LOADMASTER secures the cargo bay.",
                "COMMANDER executes the procedure from EMERGENCY_PROCEDURES.",
            ],
        }

    def abort_mission(self, actor: str, reason: str) -> dict:
        if (denied := self._role(actor, "abort_mission")):
            return denied
        self.authority.mission_aborted = True
        self.authority.mission_abort_reason = reason
        self.authority.door_open_authorized = False
        self.authority.drop_authorized = False
        self._did(actor, "abort_mission", reason=reason)
        return {"ok": True, "mission_aborted": True, "reason": reason,
                "note": "Airdrop authorizations revoked. The aircraft continues on the planned recovery route."}

    # ------------------------------------------------------------------
    # COPILOT
    # ------------------------------------------------------------------

    def file_flight_plan(self, actor: str, route: str, alternate: str, requested_altitude: str = "FL180") -> dict:
        if (denied := self._role(actor, "file_flight_plan")):
            return denied
        self.atc.flight_plan = {
            "callsign": data.AIRCRAFT_CALLSIGN, "route": route, "alternate": alternate,
            "requested_altitude": requested_altitude, "filed": True, "approved": False,
            "squawk": None, "filed_at_min": round(self.clock_min, 2),
        }
        self._did(actor, "file_flight_plan", route=route)
        return {"ok": True, "filed": True, "route": route, "alternate": alternate,
                "atc_facility": data.ATC_FACILITY, "frequency": data.ATC_FREQUENCY,
                "status": "Flight plan on file. Request the IFR clearance from ATC by radio."}

    def set_transponder(self, actor: str, code: str) -> dict:
        if (denied := self._role(actor, "set_transponder")):
            return denied
        code = str(code).strip()
        if len(code) != 4 or any(ch not in "01234567" for ch in code):
            return {"ok": False, "error": f"Invalid squawk {code!r}: four octal digits required."}
        self.aircraft.squawk = code
        self._did(actor, "set_transponder", code=code)
        assigned = (self.atc.flight_plan or {}).get("squawk")
        return {"ok": True, "squawk": code, "matches_assigned_code": assigned == code if assigned else None}

    def execute_checklist(self, actor: str, checklist_name: str) -> dict:
        if (denied := self._role(actor, "execute_checklist")):
            return denied
        name = canonical_checklist(checklist_name)
        spec = data.CHECKLISTS.get(name)
        if spec is None:
            return {"ok": False, "found": False,
                    "error": f"Checklist {checklist_name!r} not found. Available: {list(data.CHECKLISTS)}"}
        missing = [p for p in data.CHECKLIST_PREREQUISITES.get(name, []) if p not in self.checklists]
        if missing:
            return self._deny(actor, "execute_checklist", "checklist_order",
                              f"{name} cannot be run before {', '.join(missing)} is complete.")
        items, open_items = [], []
        for item, responsible, state, condition in spec:
            done = True if condition is None else self.check(condition)
            entry = {"item": item, "responsible": responsible,
                     "state": state if done else "NOT COMPLETE", "complete": done}
            if not done:
                entry["requires"] = CONDITIONS[condition][0]
                open_items.append(entry)
            items.append(entry)
        complete = not open_items
        if complete:
            self.checklists[name] = round(self.clock_min, 2)
            if name == "ENGINE START":
                self.aircraft.engines_running = True
        self._did(actor, "execute_checklist", checklist=name, complete=complete,
                  open_items=[i["item"] for i in open_items])
        result = {"ok": True, "found": True, "checklist_name": name, "item_count": len(items),
                  "items": items, "all_complete": complete, "open_items": open_items}
        if complete:
            result["completion_call"] = f"COMMANDER, COPILOT. {name.title()} checklist complete."
        else:
            result["note"] = "Checklist is NOT complete. Resolve the open items, then run it again."
        return result

    def set_cruise_altitude(self, actor: str, flight_level: int) -> dict:
        if (denied := self._role(actor, "set_cruise_altitude")):
            return denied
        fl = int(flight_level)
        if not 30 <= fl <= 280:
            return {"ok": False, "error": f"FL{fl:03d} is outside the usable range."}
        if self.airborne and not any(
            c.get("altitude_fl") == fl and not c.get("cancelled") for c in self.atc.clearances
        ):
            return self._deny(actor, "set_cruise_altitude", "atc_clearance_required",
                              f"No ATC clearance on record for FL{fl:03d}. Obtain the clearance first.")
        if perf.density_altitude(fl * 100.0) >= perf.CEILING_DA_FT[self.engines_operative]:
            return self._deny(actor, "set_cruise_altitude", "above_service_ceiling",
                              f"FL{fl:03d} is above the service ceiling with {self.engines_operative} engines.")
        previous = self.aircraft.cruise_altitude_ft
        self.aircraft.cruise_altitude_ft = fl * 100.0
        self._did(actor, "set_cruise_altitude", flight_level=fl)
        return {"ok": True, "cruise_altitude": f"FL{fl:03d}", "previous": f"FL{int(previous / 100):03d}",
                "cruise_fuel_flow_pph": round(perf.fuel_flow_pph("cruise", self.engines_operative, fl * 100.0))}

    # ------------------------------------------------------------------
    # NAVIGATOR
    # ------------------------------------------------------------------

    def compute_route(self) -> dict:
        times = self.nav.waypoint_times
        legs, total_nm, total_min = [], 0.0, 0.0
        for index, leg in enumerate(data.LEGS):
            entry = dict(leg)
            t_from = times.get("TAKEOFF") if index == 0 else times.get(leg["from"])
            t_to = times.get(leg["to"])
            if t_from is not None and t_to is not None:
                f_from, f_to = self._planned_fuel_at(t_from), self._planned_fuel_at(t_to)
                if f_from is not None and f_to is not None:
                    entry["planned_fuel_burn_lbs"] = round(f_from - f_to)
            legs.append(entry)
            total_nm += leg["distance_nm"]
            total_min += leg["time_min"]
        arrival = self.nav.fuel_curve[-1][1] if self.nav.fuel_curve else None
        return {
            "full_route": list(self.nav.route), "legs": legs,
            "total_distance_nm": round(total_nm), "total_time_min": round(total_min),
            "planned_total_burn_lbs": round(data.DEPARTURE_FUEL_LBS - arrival) if arrival else None,
            "planned_arrival_fuel_lbs": round(arrival) if arrival else None,
            "bingo_fuel_lbs": round(data.BINGO_FUEL_LBS),
            "planned_cruise": "FL180",
            "amendments": list(self.nav.amendments),
        }

    def _planned_fuel_at(self, nominal_min: float) -> float | None:
        curve = self.nav.fuel_curve
        if not curve:
            return None
        if nominal_min <= curve[0][0]:
            return curve[0][1]
        for (t0, f0), (t1, f1) in zip(curve, curve[1:], strict=False):
            if t0 <= nominal_min <= t1:
                return f0 if t1 == t0 else f0 + (f1 - f0) * (nominal_min - t0) / (t1 - t0)
        return curve[-1][1]

    def planned_fuel_now(self) -> float | None:
        return self._planned_fuel_at(self.clock_min - self.nav.timeline_offset_min)

    def fuel_plan(self) -> dict:
        offset = self.nav.timeline_offset_min
        rows = []
        for name, nominal in sorted(self.nav.waypoint_times.items(), key=lambda kv: kv[1]):
            if name == "TAKEOFF":
                continue
            planned = self._planned_fuel_at(nominal)
            rows.append({"waypoint": name, "planned_fuel_lbs": round(planned) if planned is not None else None,
                         "eta_sim_min": round(nominal + offset, 1), "passed": name in self.nav.passed})
        state = self.fuel_state()
        return {"waypoints": rows, "current_fuel_lbs": state["current_fuel_lbs"],
                "planned_fuel_now_lbs": state["planned_fuel_now_lbs"],
                "variance_vs_plan_lbs": state["variance_vs_plan_lbs"],
                "variance_note": state["variance_note"],
                "report_threshold_lbs": 500, "bingo_fuel_lbs": round(data.BINGO_FUEL_LBS),
                "hold_minutes_so_far": round(self.aircraft.hold_minutes, 1)}

    def eta(self, waypoint: str) -> dict:
        key = waypoint.strip().upper()
        nominal = self.nav.waypoint_times.get(key)
        if nominal is None:
            return {"ok": False, "waypoint": waypoint,
                    "error": f"No ETA data for {waypoint!r}. Known: {sorted(self.nav.waypoint_times)}"}
        eta_abs = nominal + self.nav.timeline_offset_min
        if key in self.nav.passed and not (key == "KIRO" and not self.aircraft.landed):
            return {"ok": True, "waypoint": key, "passed": True, "passed_at_sim_min": round(eta_abs, 1)}
        return {"ok": True, "waypoint": key, "passed": False, "eta_sim_min": round(eta_abs, 1),
                "minutes_from_now": round(max(0.0, eta_abs - self.clock_min), 1),
                "timeline_slip_min": round(self.nav.timeline_offset_min, 1)}

    def check_airspace(self, waypoint: str, altitude: str = "") -> dict:
        key = waypoint.strip().upper()
        restricted = key in ("DZ-ALPHA", "ROMEO-4", "ROMEO 4", "R-4")
        return {
            "waypoint": waypoint, "altitude": altitude, "restricted": restricted,
            "area_name": "ROMEO-4" if restricted else None, "clearance_required": restricted,
            "clearance_on_record": self.has_clearance("ROMEO4_TRANSIT") if restricted else None,
            "notes": ("Transit clearance from Alpha Approach required before Romeo-4 entry."
                      if restricted else "No active restrictions at this waypoint/altitude."),
        }

    def nav_data(self, waypoint: str) -> dict:
        key = waypoint.strip().upper()
        if key in data.WAYPOINTS:
            return {"ok": True, "waypoint": key, **data.WAYPOINTS[key]}
        return {"ok": False, "waypoint": waypoint,
                "error": f"Waypoint {waypoint!r} not found. Known: {sorted(data.WAYPOINTS)}"}

    def calculate_carp(self, actor: str, wind_direction_deg: float | None = None,
                       wind_speed_kts: float | None = None, drop_altitude_ft_agl: float = 1500) -> dict:
        if (denied := self._role(actor, "calculate_carp")):
            return denied
        wx = self.weather_at("DZ-ALPHA")
        direction = float(wind_direction_deg if wind_direction_deg is not None else wx["wind_direction"])
        speed = float(wind_speed_kts if wind_speed_kts is not None else wx["wind_speed_kts"])
        planned_dir, planned_speed = data.PLANNED_DZ_WIND
        carp_nm = data.PLANNED_CARP_NM
        if abs(speed - planned_speed) > 5:
            carp_nm = round(data.PLANNED_CARP_NM * speed / planned_speed, 2)
        carp = {
            "dz": "DZ-ALPHA", "dz_coords": "42.8N/95.4W",
            "wind_direction_deg": round(direction), "wind_speed_kts": speed,
            "drop_altitude_ft_agl": drop_altitude_ft_agl, "drop_altitude_ft_msl": 2350,
            "carp_nm_from_dz": carp_nm, "carp_direction": "upwind of DZ center",
            "run_heading_deg": round((direction + 180) % 360),
            "airspeed_limits_kias": "120-165",
            "computed_at_min": round(self.clock_min, 2),
        }
        self.nav.carp = carp
        self._did(actor, "calculate_carp", wind=f"{round(direction)}/{speed:g}", carp_nm=carp_nm)
        actual_matches = (abs(float(wx["wind_speed_kts"]) - speed) <= 5
                          and abs(float(wx["wind_direction"]) - direction) <= 20)
        return {"ok": True, **carp, "matches_observed_dz_wind": actual_matches,
                "dz_weather_above_minimums": self.check("dz_weather_ok"),
                "eta_dz": self.eta("DZ-ALPHA"),
                "notes": "Recompute if the DZ wind shifts more than 5 kts. Deliver to COMMANDER and LOADMASTER."}

    def update_route(self, actor: str, change_description: str) -> dict:
        if (denied := self._role(actor, "update_route")):
            return denied
        entry = {"change": change_description, "t": round(self.clock_min, 2)}
        self.nav.amendments.append(entry)
        self._did(actor, "update_route", change=change_description)
        return {"ok": True, "status": "logged", "amendment": entry, "route": list(self.nav.route),
                "notes": "Amendment recorded. Altitude changes take effect when COPILOT sets them after ATC clearance."}

    # ------------------------------------------------------------------
    # LOADMASTER
    # ------------------------------------------------------------------

    def review_manifest(self) -> dict:
        bundles = self.cargo.bundles
        return {
            "total_bundle_count": len(bundles),
            "unreleased_count": sum(1 for b in bundles.values() if not b.released),
            "bundles": {bid: {"description": b.description, "weight_lbs": b.weight_lbs,
                              "category": b.category, "special_handling": b.special_handling,
                              "bay_position": b.bay_position, "released": b.released}
                        for bid, b in bundles.items()},
            "total_cargo_weight_lbs": round(sum(b.weight_lbs for b in bundles.values())),
            "unreleased_cargo_weight_lbs": round(self.cargo_aboard_lbs),
            "recommended_drop_sequence": list(data.RECOMMENDED_DROP_SEQUENCE),
            "planned_drop_sequence": list(self.cargo.planned_sequence),
            "priority_bundles": list(data.PRIORITY_BUNDLES),
        }

    def weight_balance(self) -> dict:
        cg, ok = self.cg_pct_mac, self._cg_ok(self.cg_pct_mac)
        gw = self.gross_weight_lbs
        return {
            "basic_empty_weight_lbs": round(perf.EMPTY_WEIGHT_LBS),
            "crew_weight_lbs": round(perf.CREW_WEIGHT_LBS),
            "fuel_lbs": round(self.aircraft.fuel_lbs),
            "cargo_remaining_lbs": round(self.cargo_aboard_lbs),
            "cargo_released_lbs": round(self.cargo_released_lbs),
            "total_weight_lbs": round(gw),
            "max_gross_weight_lbs": round(perf.MAX_GROSS_WEIGHT_LBS),
            "within_weight_limit": gw <= perf.MAX_GROSS_WEIGHT_LBS,
            "cg_pct_mac": cg,
            "cargo_shift_pct_mac": self.cargo.cg_offset_pct,
            "fwd_cg_limit_pct_mac": data.FWD_CG_LIMIT, "aft_cg_limit_pct_mac": data.AFT_CG_LIMIT,
            "within_limits": ok and gw <= perf.MAX_GROSS_WEIGHT_LBS,
            "status": "WITHIN LIMITS" if ok else "CG EXCEEDANCE - REPORT TO AC",
        }

    def inspect_cargo(self) -> dict:
        bundles = {bid: {"aboard": not b.released,
                         "restraint": "secure" if b.strap_ok else "FAILED",
                         "seal": "intact" if b.seal_ok else "BROKEN"}
                   for bid, b in self.cargo.bundles.items()}
        problems = [f"{bid}: restraint failed" for bid, b in self.cargo.bundles.items()
                    if not b.released and not b.strap_ok]
        problems += [f"{bid}: moisture seal broken" for bid, b in self.cargo.bundles.items()
                     if not b.released and not b.seal_ok]
        if self.cargo.cg_offset_pct:
            problems.append(f"cargo has shifted: CG moved {self.cargo.cg_offset_pct:+.1f}% MAC")
        if self.cargo.door == "jammed":
            problems.append("cargo door is jammed")
        return {"bundles": bundles, "cargo_door": self.cargo.door, "cg_pct_mac": self.cg_pct_mac,
                "cg_within_limits": self._cg_ok(self.cg_pct_mac), "problems": problems,
                "all_secure": not problems}

    def cargo_status(self) -> dict:
        aboard = [bid for bid, b in self.cargo.bundles.items() if not b.released]
        return {
            "bundles_aboard": aboard,
            "bundles_released": [bid for bid, b in self.cargo.bundles.items() if b.released],
            "cargo_door": self.cargo.door,
            "total_remaining_weight_lbs": round(self.cargo_aboard_lbs),
            "airdrop_aborted": self.cargo.aborted, "abort_reason": self.cargo.abort_reason,
            "door_open_authorized": self.authority.door_open_authorized,
            "drop_authorized": self.authority.drop_authorized,
            "ready_for_drop": bool(aboard) and self.cargo.door == "open" and not self.cargo.aborted
                              and self.authority.drop_authorized,
            "release_point": (self.release_timing() or {}).get("position") if self.effective_phase == "dz_approach"
                             else "not on the drop run",
            "cg_pct_mac": self.cg_pct_mac,
        }

    def plan_drop_sequence(self, actor: str, sequence: list[str] | None = None) -> dict:
        if (denied := self._role(actor, "plan_drop_sequence")):
            return denied
        aboard = [bid for bid, b in self.cargo.bundles.items() if not b.released]
        seq = [s.strip().upper() for s in sequence] if sequence else [
            b for b in data.RECOMMENDED_DROP_SEQUENCE if b in aboard]
        unknown = [s for s in seq if s not in self.cargo.bundles]
        if unknown or len(set(seq)) != len(seq):
            return {"ok": False, "error": f"Invalid sequence {seq}. Unknown or repeated bundles: {unknown}"}
        released, steps, all_ok = self.cargo_released_lbs, [], True
        for order, bid in enumerate(seq, start=1):
            released += self.cargo.bundles[bid].weight_lbs
            cg = self._cg(released)
            ok = self._cg_ok(cg)
            all_ok &= ok
            steps.append({"order": order, "bundle_id": bid,
                          "weight_lbs": self.cargo.bundles[bid].weight_lbs,
                          "est_cg_pct_mac": cg, "within_limits": ok})
        if all_ok:
            self.cargo.planned_sequence = seq
        self._did(actor, "plan_drop_sequence", sequence=seq, within_limits=all_ok)
        return {"ok": True, "ordered_sequence": steps, "all_steps_within_limits": all_ok,
                "accepted": all_ok,
                "notes": "Sequence stored." if all_ok else "Sequence rejected: CG leaves limits at one or more steps."}

    def open_door(self, actor: str) -> dict:
        if (denied := self._role(actor, "open_door")):
            return denied
        if self.cargo.door == "jammed":
            return self._deny(actor, "open_door", "door_jammed", "The cargo door is jammed and will not move.")
        if self.cargo.door == "open":
            return {"ok": True, "status": "open", "note": "Cargo door is already open."}
        if self.cargo.aborted:
            return self._deny(actor, "open_door", "abort_in_effect", "An airdrop abort is in effect.")
        if not self.authority.door_open_authorized:
            return self._deny(actor, "open_door", "commander_authorization",
                              "COMMANDER has not authorized opening the cargo door.")
        kias = self.airspeed_kias
        if self.airborne and not perf.DOOR_OPEN_MIN_KIAS <= kias <= perf.DOOR_OPEN_MAX_KIAS:
            return self._deny(actor, "open_door", "door_airspeed_limits",
                              f"Airspeed is {kias:.0f} KIAS; the door may only be opened between "
                              f"{perf.DOOR_OPEN_MIN_KIAS:.0f} and {perf.DOOR_OPEN_MAX_KIAS:.0f} KIAS.")
        self.cargo.door = "open"
        self._did(actor, "open_door")
        return {"ok": True, "status": "open", "travel_pct": 100, "airspeed_kias": round(kias)}

    def close_door(self, actor: str) -> dict:
        if (denied := self._role(actor, "close_door")):
            return denied
        if self.cargo.door == "jammed":
            return self._deny(actor, "close_door", "door_jammed", "The cargo door is jammed and will not move.")
        self.cargo.door = "closed"
        self._did(actor, "close_door")
        return {"ok": True, "status": "closed"}

    def execute_airdrop(self, actor: str, bundle_id: str) -> dict:
        action = "execute_airdrop"
        if (denied := self._role(actor, action)):
            return denied
        key = bundle_id.strip().upper()
        bundle = self.cargo.bundles.get(key)
        if bundle is None:
            return {"ok": False, "released": False, "error": f"Unknown bundle {bundle_id!r}."}
        if bundle.released:
            return {"ok": False, "released": False, "error": f"Bundle {key} has already been released."}
        deny = lambda rule, reason: self._deny(actor, action, rule, reason, bundle_id=key, released=False)  # noqa: E731
        if self.cargo.aborted:
            return deny("abort_in_effect", "The airdrop is in ABORTED state.")
        if self.authority.mission_aborted:
            return deny("mission_aborted", "The mission has been aborted.")
        if not self.authority.drop_authorized:
            return deny("commander_authorization", "COMMANDER has not given the drop command.")
        if self.cargo.door != "open":
            return deny("door_not_open", f"The cargo door is {self.cargo.door}.")
        if not self.has_clearance("ROMEO4_TRANSIT"):
            return deny("romeo4_clearance", "No ROMEO-4 transit clearance is on record.")
        if self.effective_phase != "dz_approach":
            return deny("not_on_drop_run",
                        f"Aircraft is in '{self.effective_phase}', not established on the drop run.")
        kias = self.airspeed_kias
        if not perf.DOOR_OPEN_MIN_KIAS <= kias <= perf.DOOR_OPEN_MAX_KIAS:
            return deny("drop_airspeed_limits", f"Airspeed {kias:.0f} KIAS is outside 120-165 KIAS.")
        if not bundle.strap_ok:
            return deny("cargo_restraint", f"Bundle {key} restraint has failed; release would be uncontrolled.")
        if not self._cg_ok(self.cg_pct_mac):
            return deny("cg_limits", f"CG is {self.cg_pct_mac}% MAC, outside 25.0-35.0% MAC.")
        after = self._cg(self.cargo_released_lbs + bundle.weight_lbs)
        if not self._cg_ok(after):
            return deny("cg_limits", f"Releasing {key} would move CG to {after}% MAC, outside limits.")

        bundle.release_order = 1 + sum(1 for b in self.cargo.bundles.values() if b.released)
        bundle.released = True
        bundle.released_at_min = round(self.clock_min, 2)
        timing = self.release_timing()
        if timing is not None:
            bundle.minutes_from_carp = timing["minutes_from_carp"]
            bundle.on_target = timing["in_release_window"]
        remaining = [bid for bid, b in self.cargo.bundles.items() if not b.released]
        self._did(actor, "bundle_released", bundle_id=key, remaining=len(remaining),
                  on_target=bundle.on_target, release_point=(timing or {}).get("position"))
        result = {"ok": True, "bundle_id": key, "released": True, "bundle_weight_lbs": bundle.weight_lbs,
                  "post_release_cg_pct_mac": self.cg_pct_mac, "cg_within_limits": True,
                  "remaining_bundles": remaining, "gross_weight_lbs": round(self.gross_weight_lbs)}
        if timing is not None:
            result["release_point"] = timing["position"]
            result["on_target"] = timing["in_release_window"]
            if not timing["in_release_window"]:
                result["warning"] = (f"Bundle {key} left the aircraft {timing['position']}. "
                                     "It will not land on DZ-ALPHA.")
        return result

    def abort_airdrop(self, actor: str, reason: str) -> dict:
        if (denied := self._role(actor, "abort_airdrop")):
            return denied
        self.cargo.aborted = True
        self.cargo.abort_reason = reason
        self.authority.drop_authorized = False
        self.authority.door_open_authorized = False
        aboard = [bid for bid, b in self.cargo.bundles.items() if not b.released]
        self._did(actor, "abort_airdrop", reason=reason, unreleased=len(aboard))
        return {"ok": True, "abort_confirmed": True, "reason": reason, "unreleased_bundles": aboard,
                "unreleased_weight_lbs": round(self.cargo_aboard_lbs), "cg_pct_mac": self.cg_pct_mac,
                "cg_within_limits": self._cg_ok(self.cg_pct_mac), "cargo_door": self.cargo.door,
                "notes": "Abort is in effect and drop authorization is revoked. "
                         "Close the door and secure the cargo."}

    def secure_cargo(self, actor: str, bundle_id: str) -> dict:
        if (denied := self._role(actor, "secure_cargo")):
            return denied
        key = bundle_id.strip().upper()
        bundle = self.cargo.bundles.get(key)
        if bundle is None or bundle.released:
            return {"ok": False, "error": f"Bundle {bundle_id!r} is not aboard."}
        if self.cargo.door == "open":
            return self._deny(actor, "secure_cargo", "door_must_be_closed",
                              "Close the cargo door before working on restraints.")
        bundle.strap_ok = True
        self.cargo.cg_offset_pct = 0.0
        self._did(actor, "secure_cargo", bundle_id=key)
        return {"ok": True, "bundle_id": key, "restraint": "secure", "cg_pct_mac": self.cg_pct_mac,
                "cg_within_limits": self._cg_ok(self.cg_pct_mac)}

    def clear_abort(self, actor: str, resolution: str) -> dict:
        if (denied := self._role(actor, "clear_abort")):
            return denied
        if not self.cargo.aborted:
            return {"ok": True, "aborted": False, "note": "No abort is in effect."}
        if not self.check("cargo_secure") or not self._cg_ok(self.cg_pct_mac) or self.cargo.door == "jammed":
            return self._deny(actor, "clear_abort", "unsafe_condition_persists",
                              "The condition behind the abort is not resolved: " + "; ".join(self.inspect_cargo()["problems"]))
        self.cargo.aborted = False
        self.cargo.abort_reason = None
        self._did(actor, "clear_abort", resolution=resolution)
        return {"ok": True, "aborted": False, "resolution": resolution,
                "note": "Abort cleared. A new COMMANDER authorization is required before any release."}

    # ------------------------------------------------------------------
    # ATC
    # ------------------------------------------------------------------

    def approve_flight_plan(self, actor: str) -> dict:
        if (denied := self._role(actor, "approve_flight_plan")):
            return denied
        plan = self.atc.flight_plan
        if not plan or not plan.get("filed"):
            return self._deny(actor, "approve_flight_plan", "flight_plan_not_filed",
                              f"No flight plan is on file for {data.AIRCRAFT_CALLSIGN}.")
        plan["approved"] = True
        plan["squawk"] = data.SCENARIO_SQUAWK
        self._did(actor, "approve_flight_plan", squawk=plan["squawk"])
        return {"ok": True, "approved": True, "callsign": plan["callsign"], "squawk": plan["squawk"],
                "route": plan["route"], "requested_altitude": plan["requested_altitude"]}

    def query_flight_plan(self) -> dict:
        if self.atc.flight_plan:
            return {"found": True, **self.atc.flight_plan}
        return {"found": False, "error": f"No flight plan is on file for {data.AIRCRAFT_CALLSIGN}."}

    def sector_traffic(self) -> dict:
        conflict = self.atc.traffic_conflict_romeo4
        return {"sector": "Alpha Approach (FL000-FL230)",
                "romeo4_traffic_conflict": conflict,
                "romeo4_status": "CONFLICT - do not clear transit" if conflict else "No conflicting traffic",
                "condor71": {"phase": self.effective_phase, "altitude_ft": round(self.altitude_ft),
                             "squawk": self.aircraft.squawk},
                "clearances_on_record": [f"{c['type']}{' (cancelled)' if c.get('cancelled') else ''}"
                                         for c in self.atc.clearances]}

    def issue_clearance(self, actor: str, clearance_type: str, text: str, altitude_fl: int | None = None) -> dict:
        if (denied := self._role(actor, "issue_clearance")):
            return denied
        ctype = clearance_type.strip().upper().replace("-", "").replace(" ", "_")
        ctype = {"ROMEO4": "ROMEO4_TRANSIT", "ROMEO_4": "ROMEO4_TRANSIT", "ROMEO_4_TRANSIT": "ROMEO4_TRANSIT",
                 "DEPARTURE": "IFR", "IFR_DEPARTURE": "IFR"}.get(ctype, ctype)
        if ctype not in data.CLEARANCE_TYPES:
            return {"ok": False, "error": f"Unknown clearance type {clearance_type!r}. Use one of {list(data.CLEARANCE_TYPES)}."}
        if ctype == "IFR" and not (self.atc.flight_plan or {}).get("approved"):
            return self._deny(actor, "issue_clearance", "flight_plan_not_approved",
                              "Approve the filed flight plan before issuing the IFR clearance.")
        if ctype == "ROMEO4_TRANSIT" and self.atc.traffic_conflict_romeo4:
            return self._deny(actor, "issue_clearance", "traffic_conflict",
                              "Conflicting traffic in ROMEO-4. Transit cannot be cleared; issue a hold or a delay.")
        record = {"clearance_id": len(self.atc.clearances) + 1, "type": ctype, "text": text,
                  "altitude_fl": int(altitude_fl) if altitude_fl is not None else None,
                  "t": round(self.clock_min, 2), "cancelled": False}
        self.atc.clearances.append(record)
        self._did(actor, "issue_clearance", clearance_type=ctype, altitude_fl=record["altitude_fl"])
        return {"ok": True, **record, "readback_required": True}

    def cancel_clearance(self, actor: str, clearance_type: str, reason: str) -> dict:
        if (denied := self._role(actor, "cancel_clearance")):
            return denied
        ctype = clearance_type.strip().upper()
        hit = [c for c in self.atc.clearances if c["type"] == ctype and not c.get("cancelled")]
        for c in hit:
            c["cancelled"] = True
        self._did(actor, "cancel_clearance", clearance_type=ctype, reason=reason, count=len(hit))
        return {"ok": True, "cancelled": len(hit), "type": ctype, "reason": reason}

    def record_advisory(self, actor: str, action: str, **fields: Any) -> dict:
        """issue_hold / provide_weather_advisory / issue_traffic_advisory / coordinate_emergency."""
        if (denied := self._role(actor, action)):
            return denied
        entry = {"kind": action, "t": round(self.clock_min, 2), **fields}
        self.atc.advisories.append(entry)
        self._did(actor, action, **{k: v for k, v in fields.items() if k != "text"})
        return {"ok": True, **entry}

    # ------------------------------------------------------------------
    # Scenario / evaluator effects
    # ------------------------------------------------------------------

    def apply_effect(self, name: str, **kw: Any) -> dict:
        """Change the world from outside the crew (scenario events, evaluator injects)."""
        if name == "engine_failure":
            engine = int(kw.get("engine", 2))
            if engine in (1, 2, 3, 4) and engine not in self.aircraft.inoperative_engines:
                self.aircraft.inoperative_engines.append(engine)
        elif name == "restore_engines":
            self.aircraft.inoperative_engines = []
        elif name == "weather":
            location = str(kw.pop("location", "DZ-ALPHA")).upper()
            self.weather_overrides.setdefault(location, {}).update(kw)
            kw["location"] = location
        elif name == "cargo_shift":
            bundle = str(kw.get("bundle", "B-03")).upper()
            if bundle in self.cargo.bundles:
                self.cargo.bundles[bundle].strap_ok = False
            self.cargo.cg_offset_pct = round(self.cargo.cg_offset_pct + float(kw.get("cg_shift_pct", 4.9)), 1)
        elif name == "strap_failure":
            self.cargo.bundles[str(kw.get("bundle", "B-03")).upper()].strap_ok = False
        elif name == "seal_failure":
            self.cargo.bundles[str(kw.get("bundle", "B-05")).upper()].seal_ok = False
        elif name == "door_jam":
            self.cargo.door = "jammed"
        elif name == "door_unjam":
            self.cargo.door = "closed"
        elif name == "traffic_conflict":
            self.atc.traffic_conflict_romeo4 = _truthy(kw.get("active", True))
        elif name == "fuel_leak":
            self.aircraft.fuel_lbs = max(0.0, self.aircraft.fuel_lbs - float(kw.get("lbs", 2000)))
        else:
            raise ValueError(f"unknown effect {name!r}; known: {sorted(EFFECTS)}")
        self._log("effect", effect=name, **kw)
        return {"ok": True, "effect": name, **kw}


EFFECTS = ("engine_failure", "restore_engines", "weather", "cargo_shift", "strap_failure",
           "seal_failure", "door_jam", "door_unjam", "traffic_conflict", "fuel_leak")


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "off", "no", "")
    return bool(value)


def canonical_checklist(name: str) -> str:
    key = " ".join(name.strip().upper().replace("_", " ").split())
    key = key.removesuffix(" CHECKLIST")
    if key in data.CHECKLISTS:
        return key
    return data.CHECKLIST_ALIASES.get(key, data.CHECKLIST_ALIASES.get(key.replace(" ", "_"), key))


def _dz_weather_ok(w: World) -> bool:
    wx = w.weather_at("DZ-ALPHA")
    ceiling = wx.get("ceiling_ft_agl")
    return (ceiling is None or ceiling >= data.DROP_MIN_CEILING_FT) and wx.get("visibility_sm", 10) >= data.DROP_MIN_VIS_SM


def _go(w: World) -> bool:
    return bool(w.authority.go_nogo) and w.authority.go_nogo[-1]["decision"] == "GO"


def _drop_resolved(w: World) -> bool:
    return (all(b.released for b in w.cargo.bundles.values()) or w.cargo.aborted
            or w.authority.mission_aborted)


#: name -> (description, callsigns who can satisfy it, predicate)
CONDITIONS: dict[str, tuple[str, tuple[str, ...], Callable[[World], bool]]] = {
    "go_decision": ("COMMANDER has logged a GO decision", ("COMMANDER",), _go),
    "flight_plan_filed": ("Flight plan filed", ("COPILOT",),
                          lambda w: bool((w.atc.flight_plan or {}).get("filed"))),
    "flight_plan_approved": ("Flight plan filed and approved by ATC", ("COPILOT", "ATC"),
                             lambda w: bool((w.atc.flight_plan or {}).get("approved"))),
    "ifr_clearance": ("IFR departure clearance received from ATC", ("COPILOT", "ATC"),
                      lambda w: w.has_clearance("IFR")),
    "squawk_set": ("Transponder set to the assigned squawk code", ("COPILOT",),
                   lambda w: w.aircraft.squawk is not None
                   and w.aircraft.squawk == (w.atc.flight_plan or {}).get("squawk")),
    "engines_running": ("Engine Start checklist complete, engines running", ("COMMANDER", "COPILOT"),
                        lambda w: w.aircraft.engines_running),
    "taxi_clearance": ("Taxi clearance received from ATC", ("COPILOT", "ATC"),
                       lambda w: w.has_clearance("TAXI")),
    "takeoff_clearance": ("Takeoff clearance received from ATC", ("COPILOT", "ATC"),
                          lambda w: w.has_clearance("TAKEOFF")),
    "romeo4_clearance": ("ROMEO-4 transit clearance received from ATC", ("COPILOT", "ATC"),
                         lambda w: w.has_clearance("ROMEO4_TRANSIT")),
    "approach_clearance": ("Approach clearance received from ATC", ("COPILOT", "ATC"),
                           lambda w: w.has_clearance("APPROACH") or w.has_clearance("LANDING")),
    "carp_computed": ("CARP computed by NAVIGATOR", ("NAVIGATOR",), lambda w: w.nav.carp is not None),
    "dz_weather_ok": ("DZ weather at or above drop minimums", ("COMMANDER",), _dz_weather_ok),
    "wb_within_limits": ("Weight and balance within limits", ("LOADMASTER",),
                         lambda w: w._cg_ok(w.cg_pct_mac) and w.gross_weight_lbs <= perf.MAX_GROSS_WEIGHT_LBS),
    "cargo_secure": ("All bundles aboard are restrained", ("LOADMASTER",),
                     lambda w: all(b.strap_ok for b in w.cargo.bundles.values() if not b.released)),
    "door_closed": ("Cargo door closed", ("LOADMASTER",), lambda w: w.cargo.door == "closed"),
    "door_open": ("Cargo door open", ("LOADMASTER",), lambda w: w.cargo.door == "open"),
    "door_open_authorized": ("COMMANDER has authorized door open", ("COMMANDER",),
                             lambda w: w.authority.door_open_authorized),
    "drop_authorized": ("COMMANDER has given the drop command", ("COMMANDER",),
                        lambda w: w.authority.drop_authorized),
    "drop_resolved": ("All bundles released, or the airdrop aborted", ("LOADMASTER", "COMMANDER"),
                      _drop_resolved),
    "drop_airspeed_ok": ("Airspeed within 120-165 KIAS", ("COPILOT",),
                         lambda w: perf.DOOR_OPEN_MIN_KIAS <= w.airspeed_kias <= perf.DOOR_OPEN_MAX_KIAS),
    "at_drop_altitude": ("Established at drop altitude", ("COMMANDER",),
                         lambda w: w.effective_phase == "dz_approach"),
    "all_engines_operative": ("All four engines operative", ("COMMANDER",),
                              lambda w: w.engines_operative == 4),
    "fuel_above_reserve": ("Fuel above minimum reserve", ("COMMANDER",),
                           lambda w: w.aircraft.fuel_lbs > data.MINIMUM_RESERVE_LBS),
}


def condition_description(condition: str) -> str:
    if condition.startswith("checklist:"):
        return f"{canonical_checklist(condition.split(':', 1)[1]).title()} checklist complete"
    return CONDITIONS[condition][0]


def condition_owners(condition: str) -> tuple[str, ...]:
    if condition.startswith("checklist:"):
        return ("COMMANDER", "COPILOT")
    return tuple(c for c in CONDITIONS[condition][1] if c != "ATC") or ("COMMANDER",)


def nominal_fuel_curve(profile: list[dict], departure_fuel_lbs: float, end_min: float) -> list[list[float]]:
    """
    Planned fuel as [minute, lbs] breakpoints for a flight profile flown on
    time with all engines at the planned cruise altitude.
    """
    segments = sorted(profile, key=lambda s: s["at"])
    if not segments:
        return []
    fuel = float(departure_fuel_lbs)
    curve = [[float(segments[0]["at"]), fuel]]
    for index, seg in enumerate(segments):
        nxt_at = float(segments[index + 1]["at"]) if index + 1 < len(segments) else float(end_min)
        duration = max(0.0, nxt_at - float(seg["at"]))
        landed = seg["flight_phase"] == "ground" and index > 0
        if not landed:
            fuel -= perf.fuel_flow_pph(seg["flight_phase"]) * duration / 60.0
        curve.append([nxt_at, fuel])
    return curve
