"""The agent layer: tools, the scripted model, and what a turn commits."""
import json

from langchain_core.messages import HumanMessage

from airdrop_alpha.agents.factory import build_crew, render_prompt
from airdrop_alpha.agents.playbooks import scripted_models
from airdrop_alpha.agents.scripted import Rule, ScriptedChatModel, say, split_prompt
from airdrop_alpha.domain.data import knowledge_dir
from airdrop_alpha.domain.world import ROLES, World
from airdrop_alpha.graph.crew import make_crew_node, render_turn_prompt
from airdrop_alpha.graph.state import initial_state, post_messages
from airdrop_alpha.domain.comms import make_message
from airdrop_alpha.tools.toolsets import TOOLSETS


def _crew(scenario, role, rules):
    models = scripted_models()
    models[role] = ScriptedChatModel(role=role, playbook=rules)
    return build_crew(scenario, models)


def _state_with_traffic(scenario, to, body, sender="SCENARIO_RUNNER"):
    state = initial_state(scenario, "t")
    log, inboxes = post_messages([make_message(sender=sender, to=[to], body=body)], log_length=0,
                                 inboxes=state["inboxes"], clock_min=0)
    state["log"], state["inboxes"] = log, inboxes
    return state


def test_tools_are_scoped_by_role_and_hide_the_runtime():
    names = {role: {t.name for t in tools} for role, tools in TOOLSETS.items()}
    assert "execute_airdrop" in names["LOADMASTER"]
    assert all("execute_airdrop" not in names[r] for r in ROLES if r != "LOADMASTER")
    assert all("authorize_airdrop" not in names[r] for r in ROLES if r != "COMMANDER")
    assert all("issue_clearance" not in names[r] for r in ROLES if r != "ATC")
    assert all("send_message" in n for n in names.values())
    # the stubs that returned canned text in the original are gone
    gone = {"contact_atc", "relay_atc_message", "request_clearance", "brief_crew",
            "advance_flight_phase", "sync_cargo_weight", "simulate_engine_failure"}
    assert not gone & set().union(*names.values())
    for tools in TOOLSETS.values():
        for tool in tools:
            assert "runtime" not in tool.tool_call_schema.model_json_schema().get("properties", {})


def test_prompts_render_for_every_role(scenario):
    for role in ROLES:
        prompt = render_prompt(role, scenario)
        assert "{{" not in prompt and "HOW THIS SIMULATION WORKS" in prompt
        assert "FROM:" not in prompt                         # no header format to parse any more
    nav = render_prompt("NAVIGATOR", scenario)
    assert "Leg 2: WPT ALPHA > WPT BRAVO - 310 deg / 110 NM / 24 min" in nav
    assert "planned arrival 28,501 lbs" in nav


def test_split_prompt_separates_log_from_this_turn():
    prompt = render_turn_prompt(callsign="COPILOT", clock_min=3, mission_phase="P1", flight_phase="ground",
                                memory=["T+1\n  HEARD #6 from SCENARIO_RUNNER: old"], omitted=0,
                                incoming=[dict(make_message(sender="COMMANDER", to=["COPILOT"], body="new"),
                                               seq=9, t=3)], overheard=[])
    log, now = split_prompt(prompt)
    assert "old" in log and "old" not in now
    assert "new" in now and "COMMANDER -> you" in now


def test_scripted_model_is_stateless_and_steps_through_a_rule():
    model = ScriptedChatModel(role="COPILOT", playbook=[
        Rule(r"run it", [[("execute_checklist", {"checklist_name": "PREFLIGHT"})], [say("COMMANDER", "done")]]),
        Rule(r"never", [[say("COMMANDER", "no")]]),
        Rule(r"run it", [[say("ATC", "blocked")]], unless_logged=r"already"),
    ])
    human = HumanMessage("=== YOUR MISSION LOG ===\nalready\n=== NOW: T+1 ===\nplease run it")
    first = model.invoke([human])
    assert [c["name"] for c in first.tool_calls] == ["execute_checklist"]
    assert model.invoke([human]).tool_calls == first.tool_calls           # same input, same output
    second = model.invoke([human, first])
    assert second.tool_calls[0]["args"]["body"] == "done"
    assert model.invoke([human, first, second]).tool_calls == []
    assert model.invoke([HumanMessage("=== NOW: nothing relevant")]).tool_calls == []


async def test_only_send_message_reaches_anyone(scenario):
    """Text outside a tool call is a private note.  The original dispatched it to COMMANDER."""
    crew = _crew(scenario, "NAVIGATOR", [Rule(r"report", [], note="COMMANDER, NAVIGATOR. Passing ALPHA.")])
    node = make_crew_node("NAVIGATOR", crew["NAVIGATOR"], knowledge_dir())
    update = await node(_state_with_traffic(scenario, "NAVIGATOR", "report please"), {})
    assert update["log"] == []
    assert all(not seqs for seqs in update["inboxes"].values())
    assert "NOTE COMMANDER, NAVIGATOR. Passing ALPHA." in update["memory"]["NAVIGATOR"][0]
    turn = update["events"][-1]
    assert turn["type"] == "turn" and turn["silent"] is True
    # ... and the scorecard flags it, so a live crew losing transmissions this way is visible
    assert turn["unsent_speech"] == 1
    state = {**_state_with_traffic(scenario, "NAVIGATOR", "report please"), "events": update["events"]}
    from airdrop_alpha.scorecard import score
    card = score(state)
    assert card["comms"]["unsent_speech_turns"] == 1 and "nobody heard it" in card["findings"][0]


async def test_turn_commits_world_messages_and_memory_together(scenario):
    crew = _crew(scenario, "COMMANDER", [Rule(r"decide", [[("make_go_nogo", {"decision": "GO", "reason": "ok"})]])])
    node = make_crew_node("COMMANDER", crew["COMMANDER"], knowledge_dir())
    state = _state_with_traffic(scenario, "COMMANDER", "decide now")
    update = await node(state, {})
    assert World.model_validate(update["world"]).check("go_decision")
    assert state["world"]["authority"]["go_nogo"] == []                 # input state untouched
    [announcement] = update["log"]
    assert announcement["kind"] == "decision" and announcement["seq"] == 2
    assert announcement["to"] == ["COPILOT", "NAVIGATOR", "LOADMASTER"]
    assert update["inboxes"]["COMMANDER"] == [] and update["inboxes"]["LOADMASTER"] == [2]
    assert update["inboxes"]["ATC"] == []
    assert {"action", "turn"} <= {e["type"] for e in update["events"]}
    entry = update["memory"]["COMMANDER"][0]
    assert "HEARD #1 from SCENARIO_RUNNER: decide now" in entry and "DID make_go_nogo" in entry
    assert "SAID #2 to COPILOT, NAVIGATOR, LOADMASTER" in entry
    assert update["counters"]["turns"] == 1 and update["counters"]["tool_calls"] == 1


async def test_denied_transmission_is_recorded_and_not_delivered(scenario):
    crew = _crew(scenario, "COMMANDER", [Rule(r"call", [[say("ATC", "Alpha Approach, CONDOR 71, request FL140.")]])])
    node = make_crew_node("COMMANDER", crew["COMMANDER"], knowledge_dir())
    update = await node(_state_with_traffic(scenario, "COMMANDER", "call ATC yourself"), {})
    assert update["log"] == [] and update["inboxes"]["ATC"] == []
    denied = [e for e in update["events"] if e["type"] == "comms_denied"]
    assert denied and denied[0]["rule"] == "atc_via_copilot"
    assert "DENIED (atc_via_copilot)" in update["memory"]["COMMANDER"][0]


async def test_denied_action_changes_nothing_and_is_remembered(scenario):
    crew = _crew(scenario, "LOADMASTER", [Rule(r"drop", [[("execute_airdrop", {"bundle_id": "B-03"})]])])
    node = make_crew_node("LOADMASTER", crew["LOADMASTER"], knowledge_dir())
    state = _state_with_traffic(scenario, "LOADMASTER", "drop it now")
    update = await node(state, {})
    assert update["world"]["cargo"] == state["world"]["cargo"]
    assert [e["rule"] for e in update["events"] if e["type"] == "guard_denied"] == ["commander_authorization"]
    assert "DENIED (commander_authorization)" in update["memory"]["LOADMASTER"][0]


async def test_model_call_limit_ends_a_runaway_turn(scenario):
    looping = [Rule(r"loop", [[("get_aircraft_state", {})]] * 50)]
    limited = dict(scenario, settings={**scenario["settings"], "max_model_calls_per_turn": 4})
    models = scripted_models()
    models["COPILOT"] = ScriptedChatModel(role="COPILOT", playbook=looping)
    node = make_crew_node("COPILOT", build_crew(limited, models)["COPILOT"], knowledge_dir())
    update = await node(_state_with_traffic(limited, "COPILOT", "loop forever"), {})
    assert update["counters"]["tool_calls"] == 4
    assert update["events"][-1]["type"] == "turn"


async def test_read_sop_returns_the_document(scenario):
    crew = _crew(scenario, "LOADMASTER", [Rule(r"read", [[("read_sop", {"document_name": "lm_sop"})]])])
    result = await crew["LOADMASTER"].ainvoke(
        {"messages": [HumanMessage("=== NOW: read")]},
        context=__import__("airdrop_alpha.tools.context", fromlist=["TurnContext"]).TurnContext(
            world=World.new(), actor="LOADMASTER", knowledge_dir=knowledge_dir()))
    payload = json.loads(result["messages"][2].content)
    assert payload["document_name"] == "LM_SOP" and "LOADMASTER" in payload["content"]
