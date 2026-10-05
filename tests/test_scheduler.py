"""The scheduler: turn order, gates, holds, budgets."""
import copy

import pytest
from langgraph.graph import END

from airdrop_alpha.domain.comms import make_message
from airdrop_alpha.graph.scheduler import SCHEDULER, _advance, apply_injects, parse_inject, scheduler
from airdrop_alpha.graph.state import initial_state, pick_next, post_messages


def _merge(state, command):
    """Apply a scheduler Command to a state the way the graph's reducers would."""
    new = dict(state)
    for key, value in (command.update or {}).items():
        new[key] = state.get(key, []) + value if key in ("log", "events") else value
    return new


def _run_until(state, predicate, limit=200):
    for _ in range(limit):
        command = _advance(state)
        state = _merge(state, command)
        if predicate(state, command):
            return state, command
    raise AssertionError("predicate never became true")


def test_turn_order_is_priority_then_longest_waiting_then_crew_order(scenario):
    state = initial_state(scenario, "t")
    msgs = [
        make_message(sender="SIM", to=["NAVIGATOR"], body="routine, oldest"),
        make_message(sender="SIM", to=["COPILOT"], body="routine, newer"),
        make_message(sender="SIM", to=["LOADMASTER"], body="urgent", priority="URGENT"),
        make_message(sender="SIM", to=["ATC", "COMMANDER"], body="routine, shared"),
    ]
    log, inboxes = post_messages(msgs, log_length=0, inboxes=state["inboxes"], clock_min=0)
    order = []
    while (nxt := pick_next(inboxes, log)):
        order.append(nxt)
        inboxes[nxt] = []
    assert order == ["LOADMASTER", "NAVIGATOR", "COPILOT", "COMMANDER", "ATC"]
    assert [m["seq"] for m in log] == [1, 2, 3, 4]


async def test_scheduler_routes_waiting_agents_before_advancing_time(scenario):
    state = _merge(initial_state(scenario, "t"), _advance(initial_state(scenario, "t")))   # mission phase
    state = _merge(state, _advance(state))                                                 # initial trigger
    assert state["inboxes"]["COMMANDER"] == [1]
    command = await scheduler(state)
    assert command.goto == "COMMANDER" and not command.update
    assert state["world"]["clock_min"] == 0


def test_unmet_gate_holds_the_timeline_and_tells_the_owners(scenario):
    """The T+3 inject needs a logged GO.  Without one, nothing is injected and time slips."""
    state = initial_state(scenario, "t")
    state, command = _run_until(state, lambda s, c: any(e["type"] == "gate_hold" for e in c.update["events"]))
    hold = next(e for e in state["events"] if e["type"] == "gate_hold")
    assert hold["unmet"] == ["go_decision"] and hold["t"] == 3
    assert state["world"]["nav"]["timeline_offset_min"] == 2
    assert state["world"]["aircraft"]["holding"] is True
    notice = state["log"][-1]
    assert notice["sender"] == "SIM" and notice["to"] == ["COMMANDER"] and notice["priority"] == "URGENT"
    assert "GO decision" in notice["body"] and "holding on the ground" in notice["body"]
    assert command.goto == SCHEDULER
    # the gated inject has not been delivered
    assert not any("File the flight plan" in m["body"] for m in state["log"])


def test_gate_clears_when_the_condition_becomes_true(scenario):
    state = initial_state(scenario, "t")
    state, _ = _run_until(state, lambda s, c: any(e["type"] == "gate_hold" for e in c.update["events"]))
    state["inboxes"] = {k: [] for k in state["inboxes"]}
    state["world"]["authority"]["go_nogo"].append({"log_id": 1, "decision": "GO", "reason": "", "t": 3})
    state, _ = _run_until(state, lambda s, c: any(e["type"] == "hold_released" for e in c.update["events"]))
    assert state["world"]["clock_min"] == 5                       # 3 + one 2-minute hold
    assert state["world"]["aircraft"]["holding"] is False
    assert "File the flight plan" in state["log"][-1]["body"]
    # everything later has slipped by the same two minutes
    state["inboxes"] = {k: [] for k in state["inboxes"]}
    state, _ = _run_until(state, lambda s, c: any(e["type"] == "mission_phase" for e in c.update["events"]))
    assert state["world"]["clock_min"] == 8                       # phase 2 was planned for T+6


def test_run_stalls_after_max_holds(scenario):
    state = initial_state(scenario, "t")
    state, command = _run_until(state, lambda s, c: s["status"] != "running")
    assert state["status"] == "stalled" and command.goto == END
    assert sum(1 for e in state["events"] if e["type"] == "gate_hold") == scenario["settings"]["max_holds"]
    assert state["world"]["clock_min"] == 3 + 2 * scenario["settings"]["max_holds"]
    stalled = next(e for e in state["events"] if e["type"] == "stalled")
    assert stalled["unmet"] == ["go_decision"]


async def test_turn_budget_ends_the_run(scenario):
    state = initial_state(scenario, "t")
    state["inboxes"]["COPILOT"] = [1]
    state["log"] = [dict(make_message(sender="SIM", to=["COPILOT"], body="x"), seq=1, t=0)]
    state["counters"]["turns"] = scenario["settings"]["max_turns"]
    command = await scheduler(state)
    assert command.goto == END and command.update["status"] == "turn_budget_exhausted"


async def test_burst_limit_forces_the_clock_on_and_keeps_the_traffic(scenario):
    state = initial_state(scenario, "t")
    state["inboxes"]["COPILOT"] = [1]
    state["log"] = [dict(make_message(sender="SIM", to=["COPILOT"], body="x"), seq=1, t=0)]
    state["counters"]["burst_turns"] = scenario["settings"]["max_turns_per_burst"]
    command = await scheduler(state)
    assert command.goto == SCHEDULER
    assert command.update["events"][0]["type"] == "burst_limit"
    assert command.update["counters"]["burst_turns"] == 0
    assert command.update["inboxes"]["COPILOT"] == [1]             # not dropped, unlike the original


def test_parse_inject():
    assert parse_inject("loadmaster:urgent Strap failed.") == {
        "message": {"to": ["LOADMASTER"], "priority": "URGENT", "body": "Strap failed."}}
    assert len(parse_inject("ALL:EMERGENCY Fire.")["message"]["to"]) == 5
    assert parse_inject("!cargo_shift bundle=B-03 cg_shift_pct=4.9") == {
        "effect": {"name": "cargo_shift", "args": {"bundle": "B-03", "cg_shift_pct": 4.9}}}
    for bad in ("", "PURSER hello", "COMMANDER:LOUD hello", "COMMANDER", "!meteor", "!door_jam now"):
        with pytest.raises(ValueError):
            parse_inject(bad)


def test_injects_change_the_world_and_are_delivered(scenario):
    state = initial_state(scenario, "t")
    before = copy.deepcopy(state)
    update = apply_injects(state, [parse_inject("!engine_failure engine=3"),
                                   parse_inject("COMMANDER:EMERGENCY Number three engine fire light.")])
    assert state == before                                         # pure: returns an update
    assert update["world"]["aircraft"]["inoperative_engines"] == [3]
    assert update["inboxes"]["COMMANDER"] == [1]
    assert update["log"][0]["sender"] == "EVALUATOR" and update["log"][0]["priority"] == "EMERGENCY"
    assert [e["type"] for e in update["events"]] == ["evaluator_inject", "effect"]
