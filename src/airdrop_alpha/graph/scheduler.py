"""
The scheduler node: the only place where time passes and turns are assigned.

Each time control returns here it does exactly one of:

1. give the next waiting agent a turn (highest-priority traffic first);
2. pause for the evaluator, in interactive mode, when the crew has gone quiet;
3. advance the clock to the next timeline item and either fire it or, if its
   conditions are not met, hold the timeline and tell the responsible crew;
4. end the run.

The original had no such place: a message handler called the next agent's
handler recursively, scenario events fired on wall-clock time whether or not
the crew was ready, and chains deeper than 25 calls were dropped silently.
"""
from __future__ import annotations

import copy
import os
from typing import Any

from langgraph.graph import END
from langgraph.types import Command, interrupt

from ..domain.comms import (
    EVALUATOR_SENDER, SCENARIO_SENDER, SIM, SYSTEM_SENDER, make_message, PRIORITIES,
)
from ..domain.world import EFFECTS, ROLES, World, condition_description, condition_owners
from ..scenario import load_scenario
from .state import MissionState, initial_state, pick_next, post_messages

SCHEDULER = "scheduler"


def _hold_place(world: World) -> str:
    phase = world.aircraft.flight_phase
    if phase == "ground":
        return "holding on the ground"
    if phase == "dz_approach":
        return "orbiting at drop altitude and drop speed"
    return "in a holding pattern"


def parse_inject(line: str) -> dict:
    """
    Parse one evaluator line.

    ``AGENT[:PRIORITY] message``    a message, as in the original console
    ``!effect key=value ...``       change the world (see World.apply_effect)
    """
    line = line.strip()
    if not line:
        raise ValueError("empty inject")
    if line.startswith("!"):
        parts = line[1:].split()
        name, args = parts[0], {}
        if name not in EFFECTS:
            raise ValueError(f"unknown effect {name!r}. Known: {', '.join(EFFECTS)}")
        for part in parts[1:]:
            if "=" not in part:
                raise ValueError(f"effect arguments are key=value pairs, got {part!r}")
            key, value = part.split("=", 1)
            try:
                args[key] = float(value) if "." in value else int(value)
            except ValueError:
                args[key] = value
        return {"effect": {"name": name, "args": args}}
    head, _, body = line.partition(" ")
    target, _, priority = head.partition(":")
    target, priority = target.upper(), (priority or "ROUTINE").upper()
    if target != "ALL" and target not in ROLES:
        raise ValueError(f"unknown agent {target!r}. Valid: {', '.join(ROLES)}, ALL")
    if priority not in PRIORITIES:
        raise ValueError(f"unknown priority {priority!r}. Valid: {', '.join(PRIORITIES)}")
    if not body.strip():
        raise ValueError("message body is empty")
    return {"message": {"to": list(ROLES) if target == "ALL" else [target],
                        "priority": priority, "body": body.strip()}}


def apply_injects(state: MissionState, injects: list[dict], sender: str = EVALUATOR_SENDER) -> dict:
    """Turn evaluator injects into a state update (messages, world effects, events)."""
    world = World.model_validate(state["world"])
    messages, events = [], []
    for inject in injects:
        if "effect" in inject:
            eff = inject["effect"]
            world.apply_effect(eff["name"], **dict(eff.get("args", {})))
        if "message" in inject:
            msg = inject["message"]
            messages.append(make_message(sender=sender, to=msg["to"], body=msg["body"],
                                         priority=msg.get("priority", "ROUTINE"), channel=SIM, kind="inject"))
    events.append({"type": "evaluator_inject", "t": round(world.clock_min, 2), "count": len(injects)})
    events.extend(world.drain_journal())
    stamped, inboxes = post_messages(messages, log_length=len(state.get("log", [])),
                                     inboxes=state["inboxes"], clock_min=world.clock_min)
    return {"world": world.model_dump(), "log": stamped, "inboxes": inboxes, "events": events}


def _next_item(state: MissionState) -> tuple[dict, float] | None:
    """The next unfired timeline item and the sim minute it is due."""
    fired = set(state["timeline"]["fired"])
    for item in state["scenario"]["timeline"]:
        if item["id"] not in fired:
            return item, item["at"] + state["world"]["nav"]["timeline_offset_min"]
    return None


def _advance(state: MissionState) -> Command:
    """Move the clock to the next timeline item and fire it or hold on it."""
    scenario, settings = state["scenario"], state["scenario"]["settings"]
    world = World.model_validate(state["world"])
    timeline = copy.deepcopy(state["timeline"])
    counters = dict(state["counters"])
    fired = set(timeline["fired"])
    remaining = [item for item in scenario["timeline"] if item["id"] not in fired]
    messages: list = []
    events: list[dict] = []
    status = "running"

    if not remaining:
        status = "complete"
    else:
        item = remaining[0]
        due = item["at"] + world.nav.timeline_offset_min
        if due > world.clock_min:
            world.advance_time(due - world.clock_min)

        unmet = [cond for cond in item["requires"] if not world.check(cond)]
        if unmet:
            count = timeline["holds"].get(item["id"], 0) + 1
            timeline["holds"][item["id"]] = count
            descriptions = [condition_description(c) for c in unmet]
            if count > settings["max_holds"]:
                status = "stalled"
                events.append({"type": "stalled", "t": round(world.clock_min, 2), "item": item["label"],
                               "unmet": unmet, "detail": "; ".join(descriptions)})
            else:
                step = float(settings["hold_step_min"])
                world.nav.timeline_offset_min += step
                world.aircraft.holding = True
                owners = ["COMMANDER"]
                for cond in unmet:
                    owners.extend(condition_owners(cond))
                body = (
                    f"The mission timeline is holding. Next step ({item['label']}) cannot happen until: "
                    f"{'; '.join(descriptions)}. CONDOR 71 is {_hold_place(world)}. "
                    f"This is hold {count} of {settings['max_holds']}; each hold costs {step:g} minutes and fuel."
                )
                messages.append(make_message(sender=SYSTEM_SENDER, to=list(dict.fromkeys(owners)), body=body,
                                             priority="URGENT", channel=SIM, kind="system",
                                             meta={"hold": item["id"], "unmet": unmet}))
                events.append({"type": "gate_hold", "t": round(world.clock_min, 2), "item": item["label"],
                               "item_id": item["id"], "unmet": unmet, "hold_number": count, "slip_min": step})
        else:
            if world.aircraft.holding:
                world.aircraft.holding = False
                events.append({"type": "hold_released", "t": round(world.clock_min, 2), "item": item["label"]})
            fired.add(item["id"])
            timeline["fired"] = [i["id"] for i in scenario["timeline"] if i["id"] in fired]
            kind = item["kind"]
            if kind == "mission_phase":
                timeline["mission_phase"] = item["phase_id"]
                timeline["mission_phase_name"] = item["phase_name"]
                events.append({"type": "mission_phase", "t": round(world.clock_min, 2),
                               "phase_id": item["phase_id"], "name": item["phase_name"]})
            elif kind == "flight":
                world.set_flight_phase(item["flight_phase"], item.get("heading"))
                if item.get("notify") and item.get("message"):
                    messages.append(make_message(sender=SYSTEM_SENDER, to=item["notify"], body=item["message"],
                                                 channel=SIM, kind="system",
                                                 meta={"flight_phase": item["flight_phase"]}))
            elif kind == "waypoint":
                world.nav.passed.append(item["name"])
                events.append({"type": "waypoint", "t": round(world.clock_min, 2), "name": item["name"]})
                if not item.get("silent"):
                    messages.append(make_message(
                        sender=SYSTEM_SENDER, to=["NAVIGATOR"], channel=SIM, kind="system",
                        body=f"CONDOR 71 is passing {item['name']} at T+{world.clock_min:g} min. "
                             "Make your waypoint report to COMMANDER.",
                        meta={"waypoint": item["name"]}))
            elif kind == "event":
                for effect in item["effects"]:
                    world.apply_effect(effect["name"], **dict(effect["args"]))
                if item["message"] and item["inject_to"]:
                    messages.append(make_message(sender=SCENARIO_SENDER, to=item["inject_to"],
                                                 body=item["message"], priority=item["priority"],
                                                 channel=SIM, kind="inject", meta={"event": item["id"]}))
                events.append({"type": "scenario_event", "t": round(world.clock_min, 2), "item_id": item["id"],
                               "to": item["inject_to"], "effects": [e["name"] for e in item["effects"]]})
            elif kind == "end":
                status = "complete"

    counters["burst_turns"] = 0
    events.extend(world.drain_journal())
    stamped, inboxes = post_messages(messages, log_length=len(state.get("log", [])),
                                     inboxes=state["inboxes"], clock_min=world.clock_min)
    if status != "running":
        events.append({"type": "run_end", "t": round(world.clock_min, 2), "status": status})
    update: dict[str, Any] = {"world": world.model_dump(), "timeline": timeline, "counters": counters,
                              "log": stamped, "inboxes": inboxes, "events": events, "status": status}
    return Command(goto=END if status != "running" else SCHEDULER, update=update)


async def scheduler(state: MissionState) -> Command:
    if "world" not in state:
        # Started with an empty input (for example from LangGraph Studio).
        scenario = load_scenario(os.environ.get("AIRDROP_SCENARIO") or None)
        return Command(goto=SCHEDULER, update=initial_state(scenario, state.get("run_id")))
    if state.get("status", "running") != "running":
        return Command(goto=END)

    settings = state["scenario"]["settings"]
    counters = state["counters"]
    waiting = [role for role in ROLES if state["inboxes"].get(role)]

    if waiting:
        clock = state["world"]["clock_min"]
        if counters["turns"] >= settings["max_turns"]:
            return Command(goto=END, update={
                "status": "turn_budget_exhausted",
                "events": [{"type": "run_end", "t": clock, "status": "turn_budget_exhausted",
                            "detail": f"{counters['turns']} agent turns used"}]})
        if counters["burst_turns"] < settings["max_turns_per_burst"]:
            return Command(goto=pick_next(state["inboxes"], state["log"]))
        # The crew has talked for a full burst without going quiet.  The
        # original dropped the message silently; here the clock is forced on
        # and the event is recorded.  Waiting traffic stays in the inboxes.
        forced = _advance(state)
        forced.update["events"] = [{"type": "burst_limit", "t": clock,
                                    "turns": counters["burst_turns"], "waiting": waiting},
                                   *forced.update["events"]]
        return forced

    upcoming = _next_item(state)
    clock = state["world"]["clock_min"]
    if settings.get("interactive") and upcoming is not None and upcoming[1] > clock:
        # Pause only when the clock is about to move, not between items that
        # share a time.
        decision = interrupt({
            "type": "quiescent",
            "clock_min": clock,
            "mission_phase": state["timeline"]["mission_phase_name"],
            "next_at_min": upcoming[1],
            "next": upcoming[0]["label"],
            "prompt": "Crew is quiet. Inject an event, or continue.",
        })
        injects = (decision or {}).get("injects") if isinstance(decision, dict) else None
        if injects:
            return Command(goto=SCHEDULER, update=apply_injects(state, injects))

    return _advance(state)
