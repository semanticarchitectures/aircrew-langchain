"""
Mission scorecard: a deterministic read-out of a finished (or stopped) run.

Everything is computed from the checkpointed state, so the same function
scores a live run, a replay, a fork, or a state pulled from LangSmith.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .domain import data, performance as perf
from .domain.world import ROLES, World


def _first(events: list[dict], **match: Any) -> dict | None:
    for event in events:
        if all(event.get(k) == v for k, v in match.items()):
            return event
    return None


def _release_window(state: dict, world: World) -> list[float]:
    """The nominal release window, also for runs saved before it was recorded."""
    if len(world.nav.drop_window) == 2:
        return world.nav.drop_window
    scenario = state.get("scenario", {})
    if len(scenario.get("drop_window") or []) == 2:
        return scenario["drop_window"]
    carp = world.nav.waypoint_times.get("DZ-ALPHA")
    return [carp, carp + 1.0] if carp is not None else []


def score(state: dict) -> dict:
    """Score a mission state.  Returns a JSON-serialisable dict."""
    world = World.model_validate(state["world"])
    events: list[dict] = state.get("events", [])
    log: list[dict] = state.get("log", [])
    counters = state.get("counters", {})
    status = state.get("status", "running")

    bundles = world.cargo.bundles
    released = [bid for bid, b in bundles.items() if b.released]
    order = sorted(released, key=lambda bid: bundles[bid].release_order or 0)

    # A bundle counts as delivered only if it left the aircraft inside the
    # release window.  Runs saved before the world recorded this are judged
    # from the release time.
    window = _release_window(state, world)
    offset = world.nav.timeline_offset_min
    minutes_from_carp: dict[str, float] = {}
    delivered: list[str] = []
    for bid in order:
        bundle = bundles[bid]
        on_target, from_carp = bundle.on_target, bundle.minutes_from_carp
        if on_target is None and window:
            on_target = window[0] + offset <= bundle.released_at_min <= window[1] + offset
            from_carp = round(bundle.released_at_min - (window[0] + offset), 2)
        if from_carp is not None:
            minutes_from_carp[bid] = from_carp
        if on_target is not False:
            delivered.append(bid)
    off_target = [bid for bid in order if bid not in delivered]
    priority_delivered = all(b in delivered for b in data.PRIORITY_BUNDLES)

    if status == "running":
        outcome = "IN PROGRESS"
    elif status == "stalled":
        outcome = "STALLED"
    elif status == "turn_budget_exhausted":
        outcome = "TURN BUDGET EXHAUSTED"
    elif not world.aircraft.landed:
        outcome = "INCOMPLETE"
    elif len(delivered) == len(bundles):
        outcome = "COMPLETE"
    elif len(delivered) >= 3 or priority_delivered:
        outcome = "PARTIAL"
    elif off_target:
        outcome = "MISSED DROP ZONE"
    elif world.cargo.aborted or world.authority.mission_aborted:
        outcome = "ABORTED"
    else:
        outcome = "NOT DELIVERED"

    denials = [e for e in events if e.get("type") == "guard_denied"]
    comms_denials = [e for e in events if e.get("type") == "comms_denied"]
    holds = [e for e in events if e.get("type") == "gate_hold"]
    turns = [e for e in events if e.get("type") == "turn"]

    # Procedure findings: things that were allowed to happen but are worth a look.
    findings: list[str] = []
    door_auth = _first(events, type="action", action="authorize_door_open")
    if door_auth:
        if not door_auth.get("romeo4_clearance"):
            findings.append("Door open authorized before the ROMEO-4 clearance was on record.")
        if not door_auth.get("carp_computed"):
            findings.append("Door open authorized before the CARP was computed.")
    takeoff = _first(events, type="flight_phase", phase="takeoff")
    go = _first(events, type="action", action="make_go_nogo")
    if takeoff and (not go or go["t"] > takeoff["t"]):
        findings.append("Aircraft departed without a logged GO decision.")
    if off_target:
        nm_per_min = perf.cas_to_tas(perf.PHASE_KIAS["dz_approach"], perf.PHASE_ALT_FT["dz_approach"]) / 60.0
        by_timing: dict[float, list[str]] = {}
        for bid in off_target:
            by_timing.setdefault(minutes_from_carp.get(bid, 0.0), []).append(bid)
        for from_carp, bids in sorted(by_timing.items()):
            late = max(0.0, from_carp - (window[1] - window[0])) if window else 0.0
            miss = (-from_carp if from_carp < 0 else late) * nm_per_min
            when = f"{-from_carp:g} min before the CARP" if from_carp < 0 else f"{late:g} min after the release window"
            findings.append(f"{len(bids)} bundle(s) released {when}, about {miss:.1f} NM "
                            f"{'short of' if from_carp < 0 else 'beyond'} the release point: "
                            f"{', '.join(bids)}. Counted as off target, not delivered.")
    if released and world.nav.carp is None:
        findings.append("Bundles were released without a computed CARP.")
    if world.aircraft.turbulence_exposure_min > 0:
        findings.append(f"{world.aircraft.turbulence_exposure_min:.0f} min in forecast moderate turbulence "
                        "(no altitude amendment in effect).")
    if any(e.get("type") == "bingo_fuel" for e in events):
        findings.append("Fuel reached bingo before the DZ.")
    for event in events:
        if event.get("type") == "limit_exceeded":
            findings.append(event.get("detail", "An aircraft limit was exceeded."))
    if world.cargo.door != "closed" and world.aircraft.landed:
        findings.append(f"Landed with the cargo door {world.cargo.door}.")
    unsent = sum(1 for t in turns if t.get("unsent_speech"))
    if unsent:
        findings.append(f"{unsent} turn(s) ended with what reads like a radio call written as plain text "
                        "instead of sent with send_message; nobody heard it.")
    if any(e.get("type") == "burst_limit" for e in events):
        findings.append("The crew exceeded the per-burst turn limit; the clock was forced on.")

    planned_arrival = world.nav.fuel_curve[-1][1] if world.nav.fuel_curve else None
    by_sender = Counter(m["sender"] for m in log)

    return {
        "run_id": state.get("run_id"),
        "scenario": state.get("scenario", {}).get("name"),
        "status": status,
        "outcome": outcome,
        "sim_time_min": round(world.clock_min, 1),
        "landed": world.aircraft.landed,
        "cargo": {
            "delivered": len(delivered), "released": len(released), "total": len(bundles),
            "release_order": order, "off_target": off_target, "minutes_from_carp": minutes_from_carp,
            "priority_bundles_delivered": priority_delivered,
            "airdrop_aborted": world.cargo.aborted, "abort_reason": world.cargo.abort_reason,
            "mission_aborted": world.authority.mission_aborted,
            "final_cg_pct_mac": world.cg_pct_mac,
        },
        "fuel": {
            "final_lbs": round(world.aircraft.fuel_lbs),
            "planned_arrival_lbs": round(planned_arrival) if planned_arrival is not None else None,
            "variance_vs_plan_lbs": (round(planned_arrival - world.aircraft.fuel_lbs)
                                     if planned_arrival is not None and status == "complete" else None),
            "above_minimum_reserve": world.aircraft.fuel_lbs > data.MINIMUM_RESERVE_LBS,
        },
        "timeline": {
            "holds": len(holds), "slip_min": round(world.nav.timeline_offset_min, 1),
            "held_on": sorted({e["item"] for e in holds}),
            "checklists_completed": sorted(world.checklists, key=world.checklists.get),
        },
        "authority": {
            "guard_denials": len(denials),
            "denials_by_rule": dict(Counter(e["rule"] for e in denials)),
            "denials_by_actor": dict(Counter(e["actor"] for e in denials)),
            "comms_denials": len(comms_denials),
            "comms_denials_by_rule": dict(Counter(e["rule"] for e in comms_denials)),
            "go_nogo": [f"{g['decision']} at T+{g['t']:g}" for g in world.authority.go_nogo],
            "emergencies": [e["type"] for e in world.authority.emergencies],
        },
        "comms": {
            "messages": len(log),
            "by_sender": {k: by_sender[k] for k in sorted(by_sender)},
            "silent_turns": sum(1 for t in turns if t.get("silent")),
            "unsent_speech_turns": unsent,
        },
        "effort": {
            "agent_turns": counters.get("turns", 0),
            "turns_by_agent": {r: counters.get("turns_by_agent", {}).get(r, 0) for r in ROLES},
            "model_calls": counters.get("model_calls", 0),
            "tool_calls": counters.get("tool_calls", 0),
            "input_tokens": counters.get("input_tokens", 0),
            "output_tokens": counters.get("output_tokens", 0),
            # Parts of input_tokens.  Absent (None) for runs made before these were counted.
            "cache_read_tokens": counters.get("cache_read_tokens"),
            "cache_write_tokens": counters.get("cache_write_tokens"),
        },
        "findings": findings,
    }


def render(card: dict) -> str:
    """Plain-text scorecard."""
    cargo, fuel, tl, auth, comms, effort = (card[k] for k in
                                             ("cargo", "fuel", "timeline", "authority", "comms", "effort"))
    lines = [
        f"MISSION SCORECARD  {card['scenario']}  (run {card['run_id']})",
        f"  Outcome            {card['outcome']}  (status {card['status']}, T+{card['sim_time_min']:g} min, "
        f"{'landed' if card['landed'] else 'not landed'})",
        f"  Cargo              {cargo['delivered']} of {cargo['total']} bundles delivered on target"
        + (f"; {len(cargo['off_target'])} released off target" if cargo["off_target"] else "")
        + (f"; release order {' '.join(cargo['release_order'])}" if cargo["release_order"] else "")
        + (f"; airdrop aborted: {cargo['abort_reason']}" if cargo["airdrop_aborted"] else ""),
        f"  Fuel               {fuel['final_lbs']:,} lbs"
        + (f" (plan {fuel['planned_arrival_lbs']:,}" if fuel["planned_arrival_lbs"] is not None else "")
        + (f", {fuel['variance_vs_plan_lbs']:+,} burned vs plan)" if fuel["variance_vs_plan_lbs"] is not None
           else (")" if fuel["planned_arrival_lbs"] is not None else "")),
        f"  Timeline           {tl['holds']} hold(s), {tl['slip_min']:g} min slip"
        + (f" on: {'; '.join(tl['held_on'])}" if tl["held_on"] else ""),
        f"  Checklists         {', '.join(tl['checklists_completed']) or 'none'}",
        f"  Authority guards   {auth['guard_denials']} action(s) refused"
        + (f" {auth['denials_by_rule']} by {auth['denials_by_actor']}" if auth["guard_denials"] else ""),
        f"  Comms policy       {auth['comms_denials']} transmission(s) refused"
        + (f" {auth['comms_denials_by_rule']}" if auth["comms_denials"] else ""),
        f"  Decisions          {', '.join(auth['go_nogo']) or 'no GO/NO-GO logged'}"
        + (f"; emergencies: {', '.join(auth['emergencies'])}" if auth["emergencies"] else ""),
        f"  Messages           {comms['messages']}  {comms['by_sender']}",
        f"  Agent turns        {effort['agent_turns']} ({comms['silent_turns']} silent)  {effort['turns_by_agent']}",
        f"  Model / tool calls {effort['model_calls']} / {effort['tool_calls']}"
        + (f"   tokens in/out {effort['input_tokens']:,} / {effort['output_tokens']:,}"
           if effort["input_tokens"] or effort["output_tokens"] else "")
        + (f"   (input from cache {effort['cache_read_tokens']:,}, written to cache "
           f"{effort['cache_write_tokens']:,})" if effort.get("cache_read_tokens") is not None
           and effort["input_tokens"] else ""),
    ]
    if card["findings"]:
        lines.append("  Findings")
        lines.extend(f"    - {finding}" for finding in card["findings"])
    else:
        lines.append("  Findings           none")
    return "\n".join(lines)
