"""
The mission state: everything the graph checkpoints.

All values are plain JSON types, so a checkpoint can be inspected, replayed or
forked without importing any class from this package.
"""
from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Any, TypedDict

from ..domain.comms import CrewMessage, PRIORITY_RANK
from ..domain.world import World
from ..order import roster_model


class MissionState(TypedDict, total=False):
    run_id: str
    #: The validated scenario (see scenario.build_scenario), including its mission order.
    scenario: dict
    #: The run's roster: each seat with the agent that flies it (agents.types.bind_roster).
    roster: list[dict]
    #: World.model_dump(): aircraft, cargo, authority, ATC, nav, checklists.
    world: dict
    #: Scheduler bookkeeping: fired item ids, hold counts, current mission phase.
    timeline: dict
    #: Every message, in order.  ``seq`` is the 1-based position in this list.
    log: Annotated[list[CrewMessage], operator.add]
    #: Audit trail: actions, guard denials, gate holds, phase changes, turns.
    events: Annotated[list[dict], operator.add]
    #: callsign (one per seat) -> message seqs waiting to be handled.
    inboxes: dict[str, list[int]]
    #: callsign -> that agent's own mission log, one entry per turn.
    memory: dict[str, list[str]]
    #: callsign -> highest message seq that agent has seen (for party line).
    last_seen: dict[str, int]
    counters: dict[str, Any]
    #: running | complete | stalled | turn_budget_exhausted
    status: str


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def initial_state(scenario: dict, run_id: str | None = None,
                  roster: list[dict] | None = None) -> MissionState:
    """
    The state a run starts from.  ``roster`` is the bound roster; by default
    the seats exactly as the mission order gives them.
    """
    seats = roster if roster is not None else [dict(s) for s in scenario["order"]["roster"]]
    callsigns = [seat["callsign"] for seat in seats]
    world = World.new(
        departure_fuel_lbs=scenario["departure_fuel_lbs"],
        waypoint_times=scenario["waypoint_times"],
        fuel_curve=scenario["fuel_curve"],
        hazards=scenario["hazards"],
        drop_window=scenario.get("drop_window"),
        roster=roster_model(scenario["order"], seats),
    )
    return MissionState(
        run_id=run_id or new_run_id(),
        scenario=scenario,
        roster=seats,
        world=world.model_dump(),
        timeline={"fired": [], "holds": {}, "mission_phase": None, "mission_phase_name": "Not started"},
        log=[],
        events=[],
        inboxes={c: [] for c in callsigns},
        memory={c: [] for c in callsigns},
        last_seen={c: 0 for c in callsigns},
        counters={
            "turns": 0, "burst_turns": 0, "model_calls": 0, "tool_calls": 0,
            "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
            "turns_by_agent": {c: 0 for c in callsigns},
        },
        status="running",
    )


def post_messages(
    messages: list[CrewMessage], *, log_length: int, inboxes: dict[str, list[int]], clock_min: float,
) -> tuple[list[CrewMessage], dict[str, list[int]]]:
    """Number messages, stamp them, and deliver them to the recipients' inboxes."""
    inboxes = {role: list(seqs) for role, seqs in inboxes.items()}
    stamped: list[CrewMessage] = []
    for offset, message in enumerate(messages, start=1):
        entry = dict(message)
        entry["seq"] = log_length + offset
        entry["t"] = round(clock_min, 2)
        for recipient in entry["to"]:
            if recipient in inboxes:
                inboxes[recipient].append(entry["seq"])
        stamped.append(entry)  # type: ignore[arg-type]
    return stamped, inboxes


def pick_next(inboxes: dict[str, list[int]], log: list[CrewMessage]) -> str | None:
    """
    Whose turn is it?  The seat holding the highest-priority waiting message
    goes first; ties go to whoever has been waiting longest, then roster order
    (the order of ``inboxes``).
    """
    best: tuple[int, int, int] | None = None
    chosen: str | None = None
    for index, role in enumerate(inboxes):
        seqs = inboxes.get(role) or []
        if not seqs:
            continue
        top = max(PRIORITY_RANK.get(log[s - 1]["priority"], 0) for s in seqs)
        key = (-top, min(seqs), index)
        if best is None or key < best:
            best, chosen = key, role
    return chosen
