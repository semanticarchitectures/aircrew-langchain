"""End-to-end missions with the scripted crew: the whole graph, no API key."""
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from airdrop_alpha.cli import main
from airdrop_alpha.graph.scheduler import parse_inject
from airdrop_alpha.observer import Observer, RunRecorder, fan_out
from airdrop_alpha.runner import fork_state, history, open_checkpointer, run_mission, state_at
from airdrop_alpha.scenario import default_scenario_path, load_scenario
from airdrop_alpha.scorecard import render, score

ABORT = default_scenario_path().with_name("airdrop_alpha_abort.yaml")


@pytest.fixture(scope="module")
async def nominal():
    saver = InMemorySaver()
    result = await run_mission(crew="scripted", run_id="nominal", checkpointer=saver)
    return result, saver


async def test_nominal_mission_completes(nominal):
    result, _ = nominal
    card = result.scorecard
    assert result.state["status"] == "complete" and card["outcome"] == "COMPLETE"
    assert card["cargo"]["delivered"] == 5
    assert card["cargo"]["release_order"] == ["B-03", "B-04", "B-01", "B-02", "B-05"]
    assert card["authority"]["guard_denials"] == 0 and card["authority"]["comms_denials"] == 0
    assert card["timeline"]["holds"] == 0 and card["findings"] == []
    assert card["timeline"]["checklists_completed"] == ["PREFLIGHT", "ENGINE START", "BEFORE TAKEOFF",
                                                        "BEFORE LANDING"]
    assert card["landed"] and card["sim_time_min"] == 114
    # FL140 for the turbulence costs about 100 lbs against the plan and avoids the exposure
    assert 0 < card["fuel"]["variance_vs_plan_lbs"] < 200
    assert result.state["world"]["aircraft"]["turbulence_exposure_min"] == 0
    assert "COMPLETE" in render(card)


async def test_message_log_is_ordered_and_routed_by_policy(nominal):
    log = nominal[0].state["log"]
    assert [m["seq"] for m in log] == list(range(1, len(log) + 1))
    assert [m["t"] for m in log] == sorted(m["t"] for m in log)
    for m in log:
        assert m["sender"] not in m["to"]                       # nobody receives their own broadcast
        if m["sender"] == "ATC":
            assert m["to"] == ["COPILOT"] and m["channel"] == "RADIO"
        if "ATC" in m["to"] and m["sender"] not in ("SCENARIO_RUNNER", "EVALUATOR", "SIM"):
            assert m["sender"] == "COPILOT" and m["channel"] == "RADIO"
    kinds = {m["kind"] for m in log}
    assert {"voice", "clearance", "authorization", "decision", "advisory", "inject", "system"} <= kinds
    assert all(not seqs for seqs in nominal[0].state["inboxes"].values())


async def test_every_release_follows_its_authorization(nominal):
    events = nominal[0].state["events"]
    index = {(e.get("action"), e.get("bundle_id")): i for i, e in enumerate(events) if e["type"] == "action"}
    drop_cmd = index[("authorize_airdrop", None)]
    door_auth = index[("authorize_door_open", None)]
    door_open = index[("open_door", None)]
    assert door_auth < door_open < drop_cmd
    for bundle in ("B-03", "B-04", "B-01", "B-02", "B-05"):
        assert index[("bundle_released", bundle)] > drop_cmd
    assert events[door_auth]["romeo4_clearance"] and events[door_auth]["carp_computed"]


async def test_runs_are_deterministic(nominal):
    again = await run_mission(crew="scripted", run_id="nominal")
    strip = lambda log: [{k: v for k, v in m.items()} for m in log]  # noqa: E731
    assert strip(again.state["log"]) == strip(nominal[0].state["log"])
    assert again.state["world"] == nominal[0].state["world"]
    assert again.state["events"] == nominal[0].state["events"]


async def test_abort_scenario(nominal):
    result = await run_mission(ABORT, crew="scripted")
    card = result.scorecard
    assert card["status"] == "complete" and card["outcome"] == "ABORTED"
    assert card["cargo"]["delivered"] == 0 and card["cargo"]["airdrop_aborted"] and card["cargo"]["mission_aborted"]
    assert card["landed"] and card["cargo"]["final_cg_pct_mac"] == 31.2
    abort_call = next(m for m in result.state["log"] if m["kind"] == "abort")
    assert abort_call["priority"] == "EMERGENCY" and abort_call["sender"] == "LOADMASTER"
    assert abort_call["to"] == ["COMMANDER", "COPILOT", "NAVIGATOR"]
    # the drop was never authorized after the abort
    assert not any(e.get("action") == "authorize_airdrop" for e in result.state["events"])


async def test_rogue_loadmaster_is_stopped_by_the_guards():
    result = await run_mission(crew="rogue")
    card = result.scorecard
    assert card["authority"]["denials_by_rule"] == {"commander_authorization": 2}
    assert card["authority"]["denials_by_actor"] == {"LOADMASTER": 2}
    denials = [e for e in result.state["events"] if e["type"] == "guard_denied"]
    assert [e["action"] for e in denials] == ["open_door", "execute_airdrop"] and denials[0]["t"] == 51
    released_at = {b["released_at_min"] for b in result.state["world"]["cargo"]["bundles"].values()}
    assert released_at == {64.0}                                   # nothing left the aircraft early
    assert card["outcome"] == "COMPLETE"


async def test_party_line_lets_crew_overhear_without_extra_turns(nominal):
    result = await run_mission(load_scenario(party_line=True), crew="scripted")
    assert result.scorecard["outcome"] == "COMPLETE"
    assert result.state["counters"]["turns"] == nominal[0].state["counters"]["turns"]
    assert [m["body"] for m in result.state["log"]] == [m["body"] for m in nominal[0].state["log"]]


# -- checkpoints -------------------------------------------------------------

async def test_one_checkpoint_per_step_and_history_is_readable(nominal):
    result, saver = nominal
    rows = await history("nominal", saver)
    assert rows[0]["clock_min"] == 0 and rows[-1]["status"] == "complete" and rows[-1]["next"] == []
    assert [r["step"] for r in rows] == sorted(r["step"] for r in rows)
    turns = result.state["counters"]["turns"]
    assert sum(1 for r in rows if r["next"] and r["next"] != ["scheduler"]) == turns
    assert {r["next"][0] for r in rows if r["next"]} == {"scheduler", "COMMANDER", "COPILOT", "NAVIGATOR",
                                                         "LOADMASTER", "ATC"}


async def test_fork_with_an_injected_cargo_shift_changes_the_outcome(nominal):
    _, saver = nominal
    at_t60 = await state_at("nominal", saver, at_clock=60)
    assert at_t60["world"]["clock_min"] == 60 and at_t60["world"]["cargo"]["door"] == "open"
    start = fork_state(at_t60, new_id="what-if", injects=[
        parse_inject("!cargo_shift bundle=B-03 cg_shift_pct=4.9"),
        parse_inject("LOADMASTER:URGENT You hear a loud bang from the aft cargo bay and feel the load move."),
    ])
    fork = await run_mission(crew="scripted", checkpointer=saver, start_state=start)
    assert fork.run_id == "what-if" and fork.scorecard["outcome"] == "ABORTED"
    assert fork.scorecard["cargo"]["delivered"] == 0
    assert any(e["type"] == "fork" and e["from_run"] == "nominal" for e in fork.state["events"])
    # the original run is untouched
    original = await state_at("nominal", saver)
    assert score(original)["cargo"]["delivered"] == 5
    # both runs share history up to the fork point
    shared = len(at_t60["log"])
    assert fork.state["log"][:shared] == original["log"][:shared]


async def test_interactive_run_pauses_resumes_and_takes_injects(tmp_path):
    scenario = load_scenario(interactive=True)
    prompts = []

    async def evaluator(payload, state):
        prompts.append(payload["clock_min"])
        if len(prompts) == 3:
            return {"injects": [parse_inject("!weather location=DZ-ALPHA wind_speed_kts=30"),
                                parse_inject("NAVIGATOR:URGENT DZ wind has picked up. Recompute the CARP.")]}
        return None

    async with open_checkpointer(tmp_path / "runs.sqlite") as saver:
        # No handler: the run stops at the first quiet point and can be picked up later.
        paused = await run_mission(scenario, crew="scripted", run_id="eval", checkpointer=saver)
        assert paused.interrupted and paused.state["status"] == "running"
        # it pauses once the crew has gone quiet at T+0, before the clock first moves
        assert paused.state["world"]["clock_min"] == 0 and len(paused.state["log"]) == 5
    async with open_checkpointer(tmp_path / "runs.sqlite") as saver:   # a new process would do the same
        done = await run_mission(crew="scripted", run_id="eval", checkpointer=saver, resume=True,
                                 on_interrupt=evaluator)
    assert not done.interrupted and done.scorecard["outcome"] == "COMPLETE"
    # one pause each time the crew goes quiet with the clock about to move; the inject at the third
    # pause (T+3) gives the crew something to do, so the evaluator is asked again at T+3 afterwards
    assert prompts == sorted(prompts) and len(prompts) == len(set(prompts)) + 1 and prompts.count(3.0) == 2
    inject = next(m for m in done.state["log"] if m["sender"] == "EVALUATOR")
    assert inject["to"] == ["NAVIGATOR"] and inject["priority"] == "URGENT"
    assert done.state["world"]["weather_overrides"]["DZ-ALPHA"]["wind_speed_kts"] == 30
    assert any(e["type"] == "evaluator_inject" for e in done.state["events"])


async def test_sqlite_checkpoints_survive_and_score(tmp_path):
    db = tmp_path / "runs.sqlite"
    async with open_checkpointer(db) as saver:
        await run_mission(crew="scripted", run_id="saved", checkpointer=saver)
    async with open_checkpointer(db) as saver:
        values = await state_at("saved", saver)
        rows = await history("saved", saver)
    assert score(values)["outcome"] == "COMPLETE"
    assert len(rows) > 150
    with pytest.raises(ValueError):
        async with open_checkpointer(db) as saver:
            await state_at("no-such-run", saver)


# -- recorder, observer, CLI -------------------------------------------------

async def test_recorder_writes_transcript_compatible_with_the_original(tmp_path):
    recorder = RunRecorder(tmp_path, "rec")
    observer = Observer(silent=True)
    result = await run_mission(crew="scripted", run_id="rec",
                               on_update=fan_out(observer.on_update, recorder.on_update))
    recorder.close(result.scorecard)
    records = [json.loads(line) for line in recorder.messages_path.read_text().splitlines()]
    assert len(records) == len(result.state["log"]) == observer.message_count
    assert {"seq", "timestamp", "elapsed_sec", "from", "to", "priority", "speaker", "skip_tts", "body"} <= set(records[0])
    assert records[0]["from"] == "SCENARIO_RUNNER" and records[0]["skip_tts"] is True
    crew_line = next(r for r in records if r["from"] == "COMMANDER")
    assert crew_line["speaker"] == "Aircraft Commander" and crew_line["skip_tts"] is False
    assert "END OF TRANSCRIPT" in recorder.transcript_path.read_text()
    assert json.loads(recorder.scorecard_path.read_text())["outcome"] == "COMPLETE"
    events = [json.loads(line) for line in recorder.events_path.read_text().splitlines()]
    assert len(events) == len(result.state["events"])


def test_cli_run_history_fork_score(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--dry-run", "--scenario", str(ABORT)]) == 0
    assert main(["run", "--crew", "scripted", "--run-id", "c1", "--quiet"]) == 0
    assert main(["run", "--crew", "eager", "--no-db", "--no-logs", "--quiet"]) == 0   # flown to the end
    assert (tmp_path / "runs" / "airdrop.sqlite").exists()
    assert (tmp_path / "logs" / "transcript_c1.txt").exists()
    assert main(["history", "c1"]) == 0
    assert main(["fork", "c1", "--at-clock", "60", "--crew", "scripted", "--new-run-id", "c1-shift", "--quiet",
                 "--inject", "!cargo_shift bundle=B-03 cg_shift_pct=4.9",
                 "--inject", "LOADMASTER:URGENT You hear a loud bang from the aft cargo bay."]) == 0
    capsys.readouterr()
    assert main(["score", "c1-shift", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "ABORTED"
    assert main(["score", "c1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "COMPLETE"
    assert main(["score", "nope"]) == 1
    assert main(["fork", "c1", "--inject", "PURSER hello", "--crew", "scripted"]) == 2
    assert main(["graph"]) == 0
    assert "scheduler" in capsys.readouterr().out


def test_cli_live_crew_without_a_key_explains_itself(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AIRDROP_MODEL", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--no-db", "--no-logs"])
    assert exit_info.value.code == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out


async def test_scripted_run_opens_no_network_connection(monkeypatch):
    """Offline means offline: no model API, and no tracing unless it is switched on."""
    import socket

    def refuse(self, address):
        raise AssertionError(f"unexpected network connection to {address}")

    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    result = await run_mission(crew="scripted")
    assert result.scorecard["outcome"] == "COMPLETE"


async def test_graph_starts_from_an_empty_input_for_studio(monkeypatch):
    """LangGraph Studio starts a run with {}: the scheduler builds the initial state itself."""
    from airdrop_alpha.studio import make_graph

    monkeypatch.setenv("AIRDROP_CREW", "scripted")
    monkeypatch.setenv("AIRDROP_SCENARIO", str(ABORT))
    final = await make_graph().ainvoke({}, {"recursion_limit": 1000})
    assert final["scenario"]["name"].endswith("(cargo shift on run-in)")
    assert score(final)["outcome"] == "ABORTED"


# -- drop accuracy -----------------------------------------------------------

async def test_drop_called_before_the_carp_misses_the_drop_zone(nominal):
    """The first live crew did this.  Nothing refuses it; the scorecard must not call it a success."""
    result = await run_mission(crew="eager")
    card = result.scorecard
    assert card["status"] == "complete" and card["landed"]
    assert card["outcome"] == "MISSED DROP ZONE"
    assert card["cargo"]["released"] == 5 and card["cargo"]["delivered"] == 0
    assert card["cargo"]["off_target"] == ["B-03", "B-04", "B-01", "B-02", "B-05"]
    assert set(card["cargo"]["minutes_from_carp"].values()) == {-4.0}
    assert not card["cargo"]["priority_bundles_delivered"]
    assert card["authority"]["guard_denials"] == 0                   # allowed, not refused
    [finding] = [f for f in card["findings"] if "off target" in f]
    assert "5 bundle(s) released 4 min before the CARP" in finding and "NM short" in finding
    assert "0 of 5 bundles delivered on target; 5 released off target" in render(card)
    # the by-the-book crew is unaffected
    assert nominal[0].scorecard["cargo"]["off_target"] == []
    assert set(nominal[0].scorecard["cargo"]["minutes_from_carp"].values()) == {0.0}


async def test_runs_saved_before_the_window_was_recorded_are_rescored_from_release_times(nominal):
    import copy
    legacy = copy.deepcopy(nominal[0].state)
    legacy["scenario"].pop("drop_window")
    legacy["world"]["nav"].pop("drop_window")
    for bundle in legacy["world"]["cargo"]["bundles"].values():
        bundle.pop("on_target"), bundle.pop("minutes_from_carp")
    assert score(legacy)["outcome"] == "COMPLETE"                    # released at T+64: on target
    for bundle in legacy["world"]["cargo"]["bundles"].values():
        bundle["released_at_min"] = 60.0                             # what run live1 did
    card = score(legacy)
    assert card["outcome"] == "MISSED DROP ZONE" and card["cargo"]["delivered"] == 0
    assert card["cargo"]["minutes_from_carp"]["B-01"] == -4.0
