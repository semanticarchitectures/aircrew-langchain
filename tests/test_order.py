"""Phase 1: mission orders, the operating model, identity, and the Phase 1 gate."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from airdrop_alpha.agents.types import (
    AGENT_TYPES, GENERALIST_V1, bind_roster, fingerprint_generalist_v1,
)
from airdrop_alpha.domain.comms import CommsDenied, INTERPHONE, RADIO, resolve_recipients
from airdrop_alpha.domain.roster import LOADMASTER, Roster, make_agent_id, parse_agent_id
from airdrop_alpha.domain.world import World
from airdrop_alpha.graph.scheduler import parse_inject
from airdrop_alpha.operating_model import ENSIM_SNAPSHOT, load_operating_model, operating_model_dir
from airdrop_alpha.order import OrderError, default_order_path, load_order, roster_model, validate_order
from airdrop_alpha.runner import fork_state, history, run_mission, state_at
from airdrop_alpha.scenario import ScenarioError, build_scenario, default_scenario_path, load_scenario
from airdrop_alpha.scorecard import score

from .conftest import ready_for_drop

ROOT = Path(__file__).resolve().parents[1]
TWO_LOADMASTERS = ROOT / "scenarios" / "airdrop_alpha_two_loadmasters.order.yaml"
PHASE0 = Path(__file__).parent / "fixtures" / "phase0"


def _raw_order() -> dict:
    return yaml.safe_load(default_order_path().read_text())


# --- identity ----------------------------------------------------------------

def test_agent_ids_name_a_type_version_and_instance():
    assert parse_agent_id("LoadMasterV4.Instance2") == ("LoadMaster", 4, 2)
    assert make_agent_id("Generalist", 1, 5) == "GeneralistV1.Instance5"
    for bad in ("Generalist.v1.01", "GeneralistV1", "generalistV1.Instance1", "GeneralistV1.Instance"):
        with pytest.raises(ValueError):
            parse_agent_id(bad)


def test_generalist_v1_is_pinned_to_what_live2_flew():
    # If this fails, a prompt, tool schema, model or middleware setting changed.  Do not
    # update the pin: add GeneralistV2 and leave V1 describing the recorded runs.
    assert fingerprint_generalist_v1() == GENERALIST_V1.fingerprint
    baseline = json.loads((ROOT / "baselines" / "GeneralistV1" / "live2" / "baseline.json").read_text())
    assert baseline["fingerprint"] == GENERALIST_V1.fingerprint


def test_a_scripted_crew_is_recorded_as_the_type_that_flew():
    order = load_order()
    seats = bind_roster(order["roster"], "rogue", environ={})
    assert [s["agent_id"] for s in seats] == [f"ScriptedRogueV1.Instance{n}" for n in range(1, 6)]
    assert seats[3]["ordered_as"] == "GeneralistV1.Instance4" and seats[3]["callsign"] == "LOADMASTER"
    live = bind_roster(order["roster"], "live", environ={"AIRDROP_MODEL_ATC": "anthropic:claude-haiku-4-5"})
    assert [s["agent_id"] for s in live] == [s["agent_id"] for s in order["roster"]]
    assert live[4]["overrides"] == {"model": "anthropic:claude-haiku-4-5"} and "overrides" not in live[0]
    assert set(AGENT_TYPES) >= {"GeneralistV1", "ScriptedNominalV1", "ScriptedRogueV1", "ScriptedEagerV1"}


# --- the operating model -----------------------------------------------------

def test_the_ensim_snapshot_is_unedited():
    folder = operating_model_dir() / ENSIM_SNAPSHOT
    provenance = json.loads((folder / "provenance.json").read_text())
    assert provenance["commit"].startswith(ENSIM_SNAPSHOT.split("@")[1])
    for entry in provenance["files"]:
        data = (folder / Path(entry["path"]).name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
    assert (folder / "LICENSE").is_file() and (folder / "NOTICE").is_file()


def test_the_local_supplement_only_adds():
    model = load_operating_model()
    assert model.role("navigator").source == "representative"
    assert model.role("loadmaster").source == ENSIM_SNAPSHOT
    assert any(link.source.startswith(ENSIM_SNAPSHOT) for link in model.links_for("loadmaster",
                                                                                   "aircraft-intercom-system"))


# --- validating orders -------------------------------------------------------

def test_the_standard_order_validates_and_says_what_is_representative():
    order = load_order()
    assert [s["callsign"] for s in order["roster"]] == ["COMMANDER", "COPILOT", "NAVIGATOR", "LOADMASTER", "ATC"]
    text = " ".join(order["representative"])
    assert "role navigator" in text
    assert "copilot on tactical-communications-system" in text
    assert not any(item.startswith("loadmaster on") for item in order["representative"])  # ENSIM has it


def test_an_invalid_order_is_rejected_with_every_reason():
    raw = _raw_order()
    od = raw["order"]
    od["roster"][0]["id"] = "Generalist.v1.01"                       # malformed id
    od["roster"][1]["callsign"] = "LOADMASTER"                        # duplicate callsign
    od["roster"][2]["role"] = "flight-engineer"                       # not in the operating model
    od["roster"][4]["id"] = "OracleV9.Instance5"                      # unknown agent type
    od["nets"][0]["members"].append("TOWER")                          # not in the roster
    od["nets"].append({"id": "dz", "kind": "radio", "system": "dz-safety-of-flight-radio-net",
                       "members": ["LOADMASTER", "ATC"]})              # no such link for either role
    od["cargo"] = ["B-01"]
    with pytest.raises(OrderError) as caught:
        validate_order(raw, "bad.yaml")
    problems = "\n".join(caught.value.problems)
    for expected in ("not of the form", "already held by", "'flight-engineer' is not in the operating model",
                     "unknown agent type 'OracleV9'", "TOWER is not a callsign in the roster",
                     "has no link to dz-safety-of-flight-radio-net", "does not match the manifest"):
        assert expected in problems, expected
    assert len(caught.value.problems) >= 7


def test_a_seat_on_no_net_is_rejected():
    raw = _raw_order()
    raw["order"]["roster"].append({"id": "GeneralistV1.Instance6", "role": "loadmaster", "callsign": "LOAD 2"})
    with pytest.raises(OrderError, match="LOAD 2 is on no net"):
        validate_order(raw)


def test_scenario_and_order_must_describe_the_same_mission():
    raw = yaml.safe_load(default_scenario_path().read_text())
    order = load_order()
    late = copy.deepcopy(order)
    late["timeline"]["takeoff"] = 15
    with pytest.raises(ScenarioError, match="plans takeoff at T\\+15"):
        build_scenario(copy.deepcopy(raw), order=late)
    no_atc = validate_order(_strip_atc(_raw_order()))
    quiet = copy.deepcopy(raw)                     # nothing in it addresses ATC, but its gates need ATC
    for phase in quiet["scenario"]["phases"]:
        phase["events"] = [e for e in phase.get("events") or [] if e.get("inject_to") != "ATC"]
    with pytest.raises(ScenarioError, match="takeoff_clearance, which involves copilot, air-traffic-controller; "
                                            "no seat in the order holds air-traffic-controller"):
        build_scenario(quiet, order=no_atc)
    bad = copy.deepcopy(raw)
    bad["scenario"]["phases"][0]["events"][0]["inject_to"] = "LOAD 2"
    with pytest.raises(ScenarioError, match="unknown callsign 'LOAD 2'"):
        build_scenario(bad, order=order)


def _strip_atc(raw: dict) -> dict:
    od = raw["order"]
    od["roster"] = [s for s in od["roster"] if s["callsign"] != "ATC"]
    od["nets"] = [n for n in od["nets"] if n["kind"] != "radio"]
    return raw


# --- the roster in the domain --------------------------------------------------

def test_authority_comes_from_the_role_the_order_gives():
    order = load_order(TWO_LOADMASTERS)
    world = ready_for_drop(World.new(roster=roster_model(order), drop_window=[64, 65]))
    world.authority.drop_authorized = True
    assert world.execute_airdrop("GeneralistV1.Instance6", "B-03")["ok"]       # LOAD 2, a loadmaster
    denied = world.execute_airdrop("GeneralistV1.Instance3", "B-04")           # the navigator
    assert denied["rule"] == "role_authority"
    assert denied["reason"] == ("execute_airdrop is reserved for LOADMASTER, LOAD 2; "
                                "NAVIGATOR has no authority to do it.")
    action = next(e for e in world.journal if e["type"] == "action")
    assert (action["actor"], action["agent_id"], action["role"]) == ("LOAD 2", "GeneralistV1.Instance6", LOADMASTER)


def test_comms_follow_the_nets_in_the_order():
    roster = Roster.model_validate(roster_model(load_order(TWO_LOADMASTERS)))
    assert resolve_recipients("COMMANDER", ["ALL"], roster) == (
        INTERPHONE, ["COPILOT", "NAVIGATOR", "LOADMASTER", "LOAD 2"])
    assert resolve_recipients("LOAD 2", ["LOADMASTER"], roster) == (INTERPHONE, ["LOADMASTER"])
    assert resolve_recipients("COPILOT", ["ATC"], roster) == (RADIO, ["ATC"])
    with pytest.raises(CommsDenied) as caught:
        resolve_recipients("LOAD 2", ["ATC"], roster)
    assert caught.value.rule == "atc_via_copilot" and "ask COPILOT" in caught.value.reason
    with pytest.raises(CommsDenied, match="only COPILOT is on the radio"):
        resolve_recipients("ATC", ["LOAD 2"], roster)


def test_injects_can_address_any_seat_including_callsigns_with_spaces():
    callsigns = ["COMMANDER", "LOADMASTER", "LOAD 2"]
    assert parse_inject("LOAD 2:URGENT Check the B-03 strap.", callsigns)["message"] == {
        "to": ["LOAD 2"], "priority": "URGENT", "body": "Check the B-03 strap."}
    assert parse_inject("LOAD 2 Report.", callsigns)["message"]["to"] == ["LOAD 2"]
    assert parse_inject("ALL Stand by.", callsigns)["message"]["to"] == callsigns
    with pytest.raises(ValueError, match="unknown agent"):
        parse_inject("NAVIGATOR hello", callsigns)


# --- the Phase 1 gate -----------------------------------------------------------

def _without_roster(card: dict) -> dict:
    return {k: v for k, v in card.items() if k != "roster"}


@pytest.mark.parametrize("case, scenario_file, crew, settings", [
    ("nominal", "airdrop_alpha.yaml", "scripted", {}),
    ("abort", "airdrop_alpha_abort.yaml", "scripted", {}),
    ("rogue", "airdrop_alpha.yaml", "rogue", {}),
    ("eager", "airdrop_alpha.yaml", "eager", {}),
    ("partyline", "airdrop_alpha.yaml", "scripted", {"party_line": True}),
])
async def test_scripted_scorecards_are_unchanged_from_phase_0(case, scenario_file, crew, settings):
    """Gate: the existing mission, now run from a mission order, scores exactly as before."""
    scenario = load_scenario(default_scenario_path().parent / scenario_file, **settings)
    result = await run_mission(scenario, crew=crew, run_id=case)
    expected = json.loads((PHASE0 / f"{case}.scorecard.json").read_text())
    assert json.loads(json.dumps(_without_roster(result.scorecard), default=str)) == expected


async def test_two_loadmasters_fly_the_mission():
    """Gate: a run with two instances of one role."""
    result = await run_mission(load_scenario(order=TWO_LOADMASTERS), crew="scripted", run_id="two")
    card = result.scorecard
    assert card["outcome"] == "COMPLETE" and card["cargo"]["delivered"] == 5
    seats = {s["callsign"]: s for s in card["roster"]["seats"]}
    assert seats["LOAD 2"]["agent_id"] == "ScriptedNominalV1.Instance6" and seats["LOAD 2"]["role"] == LOADMASTER
    assert card["effort"]["turns_by_agent"]["LOAD 2"] > 0                  # hears what is sent to ALL
    log = result.state["log"]
    assert all(m["to"] == ["LOADMASTER"] for m in log if m.get("kind") == "authorization")
    assert any("LOAD 2" in m["to"] for m in log if m["sender"] == "COMMANDER")
    sent = [m for m in log if m["sender"] == "LOADMASTER"]
    assert sent and all(m["sender_id"] == "ScriptedNominalV1.Instance4" for m in sent)


async def test_saved_runs_of_any_order_can_be_listed_forked_and_rebound():
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    await run_mission(load_scenario(order=TWO_LOADMASTERS), crew="scripted", run_id="two", checkpointer=saver)
    rows = await history("two", saver)
    assert rows and {"LOAD 2"} & {n for r in rows for n in r["next"]}
    values = await state_at("two", saver, at_clock=60)
    start = fork_state(values, new_id="two-rogue",
                       injects=[parse_inject("LOAD 2 Check the straps.", list(values["inboxes"]))])
    fork = await run_mission(crew="rogue", run_id="two-rogue", checkpointer=saver, start_state=start)
    bound = next(e for e in fork.state["events"] if e["type"] == "crew_bound")
    assert bound["seats"]["LOAD 2"] == {"from": "ScriptedNominalV1.Instance6", "to": "ScriptedRogueV1.Instance6"}
    assert fork.scorecard["roster"]["configurations"] == ["ScriptedRogueV1"]
    with pytest.raises(ValueError, match="continue it with the same crew"):
        await run_mission(crew="eager", run_id="two-rogue", checkpointer=saver, resume=True)


def test_runs_saved_before_rosters_score_without_one(scenario):
    result = score({"world": World.new().model_dump(), "scenario": {k: v for k, v in scenario.items()
                                                                     if k != "order"}})
    assert result["roster"] == {"recorded": False, "note": "run made before rosters were recorded",
                                "seats": [], "representative": []}
