"""
LangChain tools: thin adapters from an agent's tool call to a World operation.

Three things differ from the original tool layer:

* Tools carry no state.  They reach the world through ``ToolRuntime.context``.
* ``send_message`` is the only way to speak.  ``contact_atc``,
  ``relay_atc_message``, ``request_clearance`` and ``brief_crew`` were canned
  stubs in the original; they are all just messages now.
* Formal calls are coupled to the act they announce.  Authorising the drop,
  issuing a clearance, logging GO/NO-GO or calling an abort both changes the
  world and transmits the standard call, so the two cannot drift apart.

Every tool is ``async`` with no awaits inside, so when a model emits several
tool calls in one step they run in call order and replays are deterministic.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from langchain.tools import ToolRuntime, tool

from ..domain import data
from ..domain.comms import CommsDenied, make_message, resolve_recipients
from ..domain.world import World
from .context import TurnContext

Runtime = ToolRuntime[TurnContext]


def _world(runtime: Runtime) -> World:
    return runtime.context.world


def _actor(runtime: Runtime) -> str:
    return runtime.context.actor


def _out(result: Any) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


def _transmit(runtime: Runtime, to: list[str] | str, body: str, *, priority: str = "ROUTINE",
              kind: str = "voice", meta: dict | None = None) -> dict:
    """Queue a message on the right channel, or record why it was refused."""
    ctx = runtime.context
    try:
        channel, recipients = resolve_recipients(ctx.actor, to)
    except CommsDenied as exc:
        ctx.comms_events.append({
            "type": "comms_denied", "t": round(ctx.world.clock_min, 2), "actor": ctx.actor,
            "to": to if isinstance(to, list) else [to], "rule": exc.rule, "reason": exc.reason,
        })
        return {"sent": False, "denied": True, "rule": exc.rule, "reason": exc.reason}
    if not body or not body.strip():
        return {"sent": False, "error": "Message body is empty."}
    ctx.outbox.append(make_message(sender=ctx.actor, to=recipients, body=body, priority=priority,
                                   channel=channel, kind=kind, meta=meta))
    return {"sent": True, "channel": channel, "to": recipients, "priority": priority}


def _announce(runtime: Runtime, result: dict, to: list[str] | str, body: str, **kw: Any) -> str:
    """Transmit the standard call that goes with a successful act."""
    if result.get("ok"):
        sent = _transmit(runtime, to, body, **kw)
        result["transmitted"] = {"to": sent.get("to"), "body": body} if sent.get("sent") else sent
        result["note"] = (result.get("note", "") + " The standard call has been transmitted; do not repeat it.").strip()
    return _out(result)


# ---------------------------------------------------------------------------
# Every role
# ---------------------------------------------------------------------------

@tool
async def send_message(
    to: list[str],
    body: str,
    runtime: Runtime,
    priority: Literal["ROUTINE", "URGENT", "EMERGENCY"] = "ROUTINE",
) -> str:
    """Transmit a spoken message. This is the ONLY way anyone hears you.

    Crew talk to each other on the interphone; COPILOT and ATC talk on the radio.
    Use callsigns COMMANDER, COPILOT, NAVIGATOR, LOADMASTER, ATC, or "ALL" for
    every crew member on the interphone. Send one complete message rather than
    several fragments.

    Args:
        to: Recipient callsigns, e.g. ["COMMANDER"] or ["COMMANDER", "LOADMASTER"] or ["ALL"].
        body: What you say, in standard crew or ATC phraseology.
        priority: ROUTINE, URGENT (time-sensitive) or EMERGENCY (active emergency only).
    """
    return _out(_transmit(runtime, to, body, priority=priority))


@tool
async def read_sop(document_name: str, runtime: Runtime) -> str:
    """Load a reference document in full.

    Args:
        document_name: One of AC_SOP, CP_SOP, NAV_SOP, LM_SOP, ATC_SOP, ATC_PHRASEOLOGY,
            EMERGENCY_PROCEDURES, CHECKLISTS, MISSION_BRIEF, CARGO_MANIFEST.
    """
    key = document_name.strip().upper().replace(" ", "_").replace(".MD", "")
    filename = data.DOCUMENTS.get(key)
    if not filename:
        return _out({"error": f"Document {document_name!r} not found.", "available": list(data.DOCUMENTS)})
    try:
        content = (runtime.context.knowledge_dir / filename).read_text(encoding="utf-8")
    except OSError as exc:
        return _out({"error": f"Could not read {filename}: {exc}"})
    return _out({"document_name": key, "content": content})


@tool
async def get_aircraft_state(runtime: Runtime) -> str:
    """Read the instruments: phase, altitude, airspeed, heading, fuel, weight, CG, engines, door.

    On the drop run it also shows the distance to the CARP and whether the aircraft is inside the
    release window.
    """
    return _out(_world(runtime).aircraft_state())


@tool
async def get_fuel_state(runtime: Runtime) -> str:
    """Fuel remaining, burn rate, endurance, bingo and reserve status, and variance against the plan."""
    return _out(_world(runtime).fuel_state())


@tool
async def query_weather(location: str, runtime: Runtime) -> str:
    """Current weather at a location or waypoint.

    Args:
        location: KIRO, WPT ALPHA, WPT BRAVO, DZ-ALPHA, DELTA FIELD or KRDW.
    """
    return _out(_world(runtime).weather_at(location))


@tool
async def query_nav_data(waypoint: str, runtime: Runtime) -> str:
    """Navigation database entry for a waypoint (coordinates, elevation, notes).

    Args:
        waypoint: e.g. "WPT BRAVO" or "DZ-ALPHA".
    """
    return _out(_world(runtime).nav_data(waypoint))


# ---------------------------------------------------------------------------
# COMMANDER
# ---------------------------------------------------------------------------

@tool
async def review_mission_brief(runtime: Runtime) -> str:
    """Load the mission parameters: objective, route, DZ, cargo, fuel plan, abort criteria."""
    return _out(_world(runtime).mission_brief())


@tool
async def make_go_nogo(decision: Literal["GO", "NO-GO"], reason: str, runtime: Runtime) -> str:
    """Log the formal GO or NO-GO decision. The decision is announced to all crew for you.

    Args:
        decision: "GO" or "NO-GO".
        reason: The rationale in one or two sentences.
    """
    result = _world(runtime).make_go_nogo(_actor(runtime), decision, reason)
    return _announce(runtime, result, ["ALL"],
                     f"CREW, COMMANDER. GO/NO-GO check. My call is {result.get('decision')}. {reason}",
                     kind="decision", meta={"decision": result.get("decision")})


@tool
async def authorize_door_open(runtime: Runtime) -> str:
    """Authorize LOADMASTER to open the cargo door. The authorization call is transmitted for you.

    Give this only when the CARP is delivered, the pre-drop checks are reported complete and
    the ROMEO-4 clearance has been relayed.
    """
    result = _world(runtime).authorize_door_open(_actor(runtime))
    return _announce(runtime, result, ["LOADMASTER"], "LOADMASTER, COMMANDER. Door open authorized.",
                     kind="authorization", meta={"authorizes": "door_open"})


@tool
async def authorize_airdrop(runtime: Runtime) -> str:
    """Give the drop command. "Execute airdrop" is transmitted to LOADMASTER for you.

    Without this the Loadmaster cannot release any bundle.
    """
    result = _world(runtime).authorize_airdrop(_actor(runtime))
    return _announce(runtime, result, ["LOADMASTER"], "LOADMASTER, COMMANDER. Execute airdrop.",
                     kind="authorization", meta={"authorizes": "airdrop"})


@tool
async def revoke_authorizations(reason: str, runtime: Runtime) -> str:
    """Withdraw door-open and drop authorization. The hold call is transmitted to LOADMASTER for you.

    Args:
        reason: Why the drop is being held.
    """
    result = _world(runtime).revoke_authorizations(_actor(runtime), reason)
    return _announce(runtime, result, ["LOADMASTER"],
                     f"LOADMASTER, COMMANDER. Hold the drop. Authorization withdrawn. {reason}",
                     priority="URGENT", kind="authorization", meta={"authorizes": "none"})


@tool
async def declare_emergency(emergency_type: str, description: str, runtime: Runtime) -> str:
    """Declare an emergency (MAYDAY or PAN-PAN). All crew are alerted for you.

    Args:
        emergency_type: e.g. "MAYDAY - ENGINE FAILURE" or "PAN-PAN - CARGO SHIFT".
        description: What has happened and the immediate plan.
    """
    result = _world(runtime).declare_emergency(_actor(runtime), emergency_type, description)
    return _announce(runtime, result, ["ALL"],
                     f"CREW, COMMANDER. {emergency_type}. {description} "
                     "COPILOT, transmit to ATC and squawk seven-seven-zero-zero.",
                     priority="EMERGENCY", kind="emergency", meta={"emergency_type": emergency_type})


@tool
async def abort_mission(reason: str, runtime: Runtime) -> str:
    """Abort the airdrop mission and return to base. All crew are told for you.

    Args:
        reason: Which abort criterion was met.
    """
    result = _world(runtime).abort_mission(_actor(runtime), reason)
    return _announce(runtime, result, ["ALL"],
                     f"CREW, COMMANDER. Mission abort. {reason} We are returning to Iron Mountain.",
                     priority="URGENT", kind="decision", meta={"decision": "MISSION ABORT"})


@tool
async def get_performance_envelope(runtime: Runtime) -> str:
    """Stall speed, minimum safe speed, maximum speed and service ceiling at the current weight."""
    return _out(_world(runtime).performance_envelope())


@tool
async def get_engine_out_performance(runtime: Runtime) -> str:
    """Engine status with the resulting ceiling, fuel flow, control speed and recommended actions."""
    return _out(_world(runtime).engine_out_performance())


# ---------------------------------------------------------------------------
# COPILOT
# ---------------------------------------------------------------------------

@tool
async def file_flight_plan(route: str, alternate: str, runtime: Runtime) -> str:
    """File the IFR flight plan. Filing does not grant a clearance: request that from ATC by radio.

    Args:
        route: e.g. "KIRO WPT-ALPHA WPT-BRAVO DZ-ALPHA WPT-CHARLIE KIRO".
        alternate: Alternate airfield, e.g. "KRDW".
    """
    return _out(_world(runtime).file_flight_plan(_actor(runtime), route, alternate))


@tool
async def set_transponder(code: str, runtime: Runtime) -> str:
    """Set the transponder squawk code assigned by ATC.

    Args:
        code: Four digits, e.g. "4712".
    """
    return _out(_world(runtime).set_transponder(_actor(runtime), code))


@tool
async def execute_checklist(checklist_name: str, runtime: Runtime) -> str:
    """Run a checklist. Items are verified against the actual aircraft state.

    The result lists any open items. A checklist with open items is NOT complete.

    Args:
        checklist_name: PREFLIGHT, ENGINE START, BEFORE TAKEOFF, CLIMB/CRUISE, DZ APPROACH,
            POST-AIRDROP, BEFORE LANDING or SHUTDOWN.
    """
    return _out(_world(runtime).execute_checklist(_actor(runtime), checklist_name))


@tool
async def set_cruise_altitude(flight_level: int, runtime: Runtime) -> str:
    """Set a new cruise altitude. In flight this requires an ATC clearance for that level first.

    Args:
        flight_level: e.g. 140 for FL140.
    """
    return _out(_world(runtime).set_cruise_altitude(_actor(runtime), flight_level))


# ---------------------------------------------------------------------------
# NAVIGATOR
# ---------------------------------------------------------------------------

@tool
async def compute_route(runtime: Runtime) -> str:
    """The planned route: legs with heading, distance, time and planned fuel burn, plus totals."""
    return _out(_world(runtime).compute_route())


@tool
async def check_airspace(waypoint: str, runtime: Runtime, altitude: str = "") -> str:
    """Check whether a waypoint lies in restricted airspace and whether a clearance is on record.

    Args:
        waypoint: e.g. "DZ-ALPHA".
        altitude: Optional altitude, e.g. "FL180" or "1500 ft AGL".
    """
    return _out(_world(runtime).check_airspace(waypoint, altitude))


@tool
async def calculate_dz_offset(
    runtime: Runtime,
    wind_direction_deg: float | None = None,
    wind_speed_kts: float | None = None,
    drop_altitude_ft_agl: float = 1500,
) -> str:
    """Compute the CARP (Computed Air Release Point) for DZ-ALPHA and record it.

    Leave the wind arguments empty to use the wind currently observed at the DZ.

    Args:
        wind_direction_deg: Wind direction at drop altitude.
        wind_speed_kts: Wind speed at drop altitude.
        drop_altitude_ft_agl: Drop altitude above ground.
    """
    return _out(_world(runtime).calculate_carp(_actor(runtime), wind_direction_deg, wind_speed_kts,
                                               drop_altitude_ft_agl))


@tool
async def get_eta(waypoint: str, runtime: Runtime) -> str:
    """ETA to a waypoint in minutes from now, including any delay from holding.

    Args:
        waypoint: WPT ALPHA, WPT BRAVO, DZ-ALPHA, WPT CHARLIE or KIRO.
    """
    return _out(_world(runtime).eta(waypoint))


@tool
async def get_fuel_plan(runtime: Runtime) -> str:
    """Planned fuel at each waypoint, and current fuel against the plan."""
    return _out(_world(runtime).fuel_plan())


@tool
async def update_route(change_description: str, runtime: Runtime) -> str:
    """Record a route or altitude amendment that COMMANDER has directed.

    Args:
        change_description: e.g. "Cruise FL140 from present position to DZ-ALPHA due turbulence".
    """
    return _out(_world(runtime).update_route(_actor(runtime), change_description))


@tool
async def compute_performance_at(altitude_ft: float, runtime: Runtime) -> str:
    """What-if performance at another altitude: true airspeed, fuel flow change, ceiling. Changes nothing.

    Args:
        altitude_ft: e.g. 14000 for FL140.
    """
    return _out(_world(runtime).performance_at(altitude_ft))


# ---------------------------------------------------------------------------
# LOADMASTER
# ---------------------------------------------------------------------------

@tool
async def review_manifest(runtime: Runtime) -> str:
    """The cargo manifest: every bundle with weight, handling notes and release status."""
    return _out(_world(runtime).review_manifest())


@tool
async def calculate_weight_balance(runtime: Runtime) -> str:
    """Current gross weight and centre of gravity against limits, using actual fuel and cargo."""
    return _out(_world(runtime).weight_balance())


@tool
async def inspect_cargo(runtime: Runtime) -> str:
    """Walk the cargo bay: restraints, moisture seals, any cargo shift, and the door."""
    return _out(_world(runtime).inspect_cargo())


@tool
async def report_cargo_status(runtime: Runtime) -> str:
    """Bundles aboard and released, door state, abort state, the authorizations you hold, and where
    the aircraft is relative to the release point."""
    return _out(_world(runtime).cargo_status())


@tool
async def plan_drop_sequence(runtime: Runtime, sequence: list[str] | None = None) -> str:
    """Check a drop sequence for CG at every step and store it if it stays within limits.

    Args:
        sequence: Bundle IDs in release order. Omit to use the recommended sequence.
    """
    return _out(_world(runtime).plan_drop_sequence(_actor(runtime), sequence))


@tool
async def open_door(runtime: Runtime) -> str:
    """Open the cargo door. Requires COMMANDER's door-open authorization and 120-165 KIAS in flight."""
    return _out(_world(runtime).open_door(_actor(runtime)))


@tool
async def close_door(runtime: Runtime) -> str:
    """Close and secure the cargo door. No authorization is needed."""
    return _out(_world(runtime).close_door(_actor(runtime)))


@tool
async def execute_airdrop(bundle_id: str, runtime: Runtime) -> str:
    """Release one bundle. Requires COMMANDER's drop command, the door open and the aircraft on the drop run.

    The bundle leaves the aircraft wherever it is at that moment. A release before or after the
    release window at the CARP misses the drop zone; the result tells you where it went.

    Args:
        bundle_id: e.g. "B-03".
    """
    return _out(_world(runtime).execute_airdrop(_actor(runtime), bundle_id))


@tool
async def abort_airdrop(reason: str, runtime: Runtime) -> str:
    """Call ABORT AIRDROP. No authorization needed. The abort call is broadcast to all stations for you.

    Args:
        reason: The unsafe condition, stated plainly.
    """
    result = _world(runtime).abort_airdrop(_actor(runtime), reason)
    return _announce(runtime, result, ["ALL"],
                     f"ALL STATIONS, LOADMASTER. ABORT AIRDROP. ABORT AIRDROP. {reason}",
                     priority="EMERGENCY", kind="abort", meta={"reason": reason})


@tool
async def secure_cargo(bundle_id: str, runtime: Runtime) -> str:
    """Re-secure a bundle whose restraint failed or that has shifted. The cargo door must be closed.

    Args:
        bundle_id: e.g. "B-03".
    """
    return _out(_world(runtime).secure_cargo(_actor(runtime), bundle_id))


@tool
async def clear_abort(resolution: str, runtime: Runtime) -> str:
    """Clear an airdrop abort once the unsafe condition is resolved. COMMANDER must then re-authorize.

    Args:
        resolution: What was done to resolve the condition.
    """
    return _out(_world(runtime).clear_abort(_actor(runtime), resolution))


# ---------------------------------------------------------------------------
# ATC
# ---------------------------------------------------------------------------

@tool
async def approve_flight_plan(runtime: Runtime) -> str:
    """Approve CONDOR 71's filed flight plan and assign the squawk code. Do this before the IFR clearance."""
    return _out(_world(runtime).approve_flight_plan(_actor(runtime)))


@tool
async def issue_clearance(
    clearance_type: Literal["IFR", "TAXI", "TAKEOFF", "ALTITUDE", "ROMEO4_TRANSIT", "DIRECT", "APPROACH", "LANDING", "OTHER"],
    text: str,
    runtime: Runtime,
    altitude_fl: int | None = None,
) -> str:
    """Issue a clearance to CONDOR 71. It is recorded and transmitted to COPILOT on the radio for you.

    Args:
        clearance_type: The kind of clearance.
        text: The full clearance exactly as spoken, e.g. "CONDOR 71, Tower. Runway two-seven-left, cleared for takeoff."
        altitude_fl: The cleared flight level when the clearance assigns one, e.g. 140.
    """
    result = _world(runtime).issue_clearance(_actor(runtime), clearance_type, text, altitude_fl)
    return _announce(runtime, result, ["COPILOT"], text, kind="clearance",
                     meta={"clearance_type": result.get("type"), "altitude_fl": result.get("altitude_fl")})


@tool
async def cancel_clearance(clearance_type: str, reason: str, runtime: Runtime) -> str:
    """Cancel a clearance already issued. The cancellation is transmitted to COPILOT for you.

    Args:
        clearance_type: e.g. "ROMEO4_TRANSIT".
        reason: Why it is cancelled.
    """
    result = _world(runtime).cancel_clearance(_actor(runtime), clearance_type, reason)
    return _announce(runtime, result, ["COPILOT"],
                     f"CONDOR 71, Alpha Approach. {clearance_type.replace('_', ' ').title()} clearance cancelled. {reason}",
                     priority="URGENT", kind="clearance",
                     meta={"clearance_type": clearance_type.upper(), "cancelled": True})


@tool
async def issue_hold(fix: str, direction: str, leg_time: str, runtime: Runtime) -> str:
    """Issue a holding instruction. It is transmitted to COPILOT for you.

    Args:
        fix: Holding fix, e.g. "WPT ALPHA".
        direction: "left" or "right" turns.
        leg_time: e.g. "2 minutes".
    """
    text = (f"CONDOR 71, Alpha Approach. Hold at {fix}, {direction} turns, {leg_time} legs. "
            "Expect further clearance in one-five minutes.")
    result = _world(runtime).record_advisory(_actor(runtime), "issue_hold", fix=fix, text=text)
    return _announce(runtime, result, ["COPILOT"], text, kind="clearance", meta={"clearance_type": "HOLD"})


@tool
async def provide_weather_advisory(pirep: str, runtime: Runtime) -> str:
    """Pass a pilot report or weather advisory to CONDOR 71. It is transmitted to COPILOT for you.

    Args:
        pirep: The advisory text.
    """
    text = f"CONDOR 71, Alpha Approach. Pilot report: {pirep}"
    result = _world(runtime).record_advisory(_actor(runtime), "provide_weather_advisory", text=text)
    return _announce(runtime, result, ["COPILOT"], text, kind="advisory", meta={"advisory": "weather"})


@tool
async def issue_traffic_advisory(traffic_info: str, runtime: Runtime) -> str:
    """Issue a traffic advisory. It is transmitted to COPILOT for you.

    Args:
        traffic_info: Bearing, distance, altitude, type and direction of the traffic.
    """
    text = f"CONDOR 71, Alpha Approach. Traffic advisory: {traffic_info}"
    result = _world(runtime).record_advisory(_actor(runtime), "issue_traffic_advisory", text=text)
    return _announce(runtime, result, ["COPILOT"], text, priority="URGENT", kind="advisory",
                     meta={"advisory": "traffic"})


@tool
async def coordinate_emergency(emergency_type: str, runtime: Runtime) -> str:
    """Start emergency coordination for CONDOR 71. Priority handling is transmitted to COPILOT for you.

    Args:
        emergency_type: "MAYDAY" or "PAN-PAN".
    """
    text = (f"CONDOR 71, Alpha Approach. {emergency_type} acknowledged. You have priority handling. "
            "Cleared direct Iron Mountain. Say souls on board and fuel remaining.")
    result = _world(runtime).record_advisory(_actor(runtime), "coordinate_emergency",
                                             emergency_type=emergency_type, text=text)
    return _announce(runtime, result, ["COPILOT"], text, priority="EMERGENCY", kind="emergency",
                     meta={"emergency_type": emergency_type})


@tool
async def query_flight_plan(runtime: Runtime) -> str:
    """CONDOR 71's flight plan as filed, with approval status and squawk."""
    return _out(_world(runtime).query_flight_plan())


@tool
async def check_sector_traffic(runtime: Runtime) -> str:
    """Your scope: traffic conflicts in ROMEO-4, CONDOR 71's position, and the clearances on record."""
    return _out(_world(runtime).sector_traffic())


# ---------------------------------------------------------------------------
# Role toolsets
# ---------------------------------------------------------------------------

TOOLSETS: dict[str, list] = {
    "COMMANDER": [
        send_message, review_mission_brief, query_weather, make_go_nogo, authorize_door_open,
        authorize_airdrop, revoke_authorizations, declare_emergency, abort_mission,
        get_aircraft_state, get_fuel_state, get_performance_envelope, get_engine_out_performance,
        read_sop,
    ],
    "COPILOT": [
        send_message, file_flight_plan, set_transponder, execute_checklist, set_cruise_altitude,
        query_nav_data, get_aircraft_state, get_fuel_state, read_sop,
    ],
    "NAVIGATOR": [
        send_message, compute_route, check_airspace, calculate_dz_offset, get_eta, get_fuel_plan,
        update_route, query_weather, get_aircraft_state, compute_performance_at, read_sop,
    ],
    "LOADMASTER": [
        send_message, review_manifest, calculate_weight_balance, inspect_cargo, plan_drop_sequence,
        report_cargo_status, open_door, close_door, execute_airdrop, abort_airdrop, secure_cargo,
        clear_abort, read_sop,
    ],
    "ATC": [
        send_message, approve_flight_plan, issue_clearance, cancel_clearance, issue_hold,
        provide_weather_advisory, issue_traffic_advisory, coordinate_emergency, query_flight_plan,
        check_sector_traffic, read_sop,
    ],
}

__all__ = ["TOOLSETS", "TurnContext"]
