"""
Run, resume, inspect and fork missions.  The CLI, the tests and the LangSmith
evaluation script all go through this module.
"""
from __future__ import annotations

import contextlib
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from .agents.factory import build_crew
from .agents.playbooks import PLAYBOOKS, scripted_models
from .graph.build import build_graph
from .graph.scheduler import SCHEDULER, apply_injects
from .graph.state import initial_state, new_run_id
from .scenario import load_scenario
from .scorecard import score

UpdateHandler = Callable[[str, dict], Awaitable[None] | None]
InterruptHandler = Callable[[dict, dict], Awaitable[dict | None]]


@dataclass
class RunResult:
    run_id: str
    state: dict
    scorecard: dict
    interrupted: bool = False


def make_crew(scenario: dict, crew: Any = "scripted") -> dict[str, Any]:
    """
    ``crew`` is "live" (models from the environment), the name of a scripted
    playbook ("scripted", "rogue"), or anything agents.factory.resolve_models
    accepts (a model string, a chat model, or a role -> model dict).
    """
    if crew == "live":
        return build_crew(scenario)
    if isinstance(crew, str) and crew in PLAYBOOKS:
        return build_crew(scenario, scripted_models(crew))
    return build_crew(scenario, crew)


@contextlib.asynccontextmanager
async def open_checkpointer(db_path: str | Path | None) -> AsyncIterator[Any]:
    """SQLite checkpointer for ``db_path``, or an in-memory one when it is None."""
    if db_path is None:
        yield InMemorySaver()
        return
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        yield saver


def run_config(run_id: str, scenario: dict | None = None) -> dict:
    settings = (scenario or {}).get("settings", {})
    steps = 2 * int(settings.get("max_turns", 400)) + 6 * len((scenario or {}).get("timeline", [])) + 200
    return {
        "configurable": {"thread_id": run_id},
        "recursion_limit": steps,
        "run_name": f"airdrop-alpha {run_id}",
        "tags": ["airdrop-alpha"],
        "metadata": {"run_id": run_id, "scenario": (scenario or {}).get("name")},
    }


async def _drive(graph: Any, first_input: Any, config: dict, on_update: UpdateHandler | None,
                 on_interrupt: InterruptHandler | None) -> bool:
    """Stream the graph to completion.  Returns True if it stopped at an interrupt."""
    next_input = first_input
    while True:
        async for chunk in graph.astream(next_input, config, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__" or not update or on_update is None:
                    continue
                outcome = on_update(node, update)
                if outcome is not None:
                    await outcome
        snapshot = await graph.aget_state(config)
        if not snapshot.interrupts:
            return False
        if on_interrupt is None:
            return True
        decision = await on_interrupt(snapshot.interrupts[0].value, snapshot.values)
        # Never resume with an empty dict: LangGraph reads a dict whose keys are
        # all interrupt ids as "no answer yet" and raises the same interrupt again.
        next_input = Command(resume=decision or {"injects": []})


async def run_mission(
    scenario: dict | str | Path | None = None,
    *,
    crew: Any = "scripted",
    run_id: str | None = None,
    checkpointer: Any = None,
    on_update: UpdateHandler | None = None,
    on_interrupt: InterruptHandler | None = None,
    resume: bool = False,
    start_state: dict | None = None,
) -> RunResult:
    """
    Run a mission to its end (or to an unanswered interrupt).

    Args:
        scenario: a loaded scenario dict, a path, or None for the default file.
        crew: see :func:`make_crew`.
        run_id: thread id for checkpoints; generated if omitted.
        checkpointer: LangGraph checkpointer.  Defaults to in-memory.
        on_update: called with (node, state update) after every step.
        on_interrupt: called with (payload, state) when the evaluator is asked
            for input; returns ``{"injects": [...]}`` or None to continue.
        resume: continue ``run_id`` from its last checkpoint instead of starting.
        start_state: start from this full state instead of a fresh one (forks).
    """
    checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
    if resume:
        if not run_id:
            raise ValueError("resume needs the run_id of the run to continue")
        probe = build_graph(make_crew(load_scenario(), "scripted"), checkpointer=checkpointer)
        saved = await probe.aget_state(run_config(run_id))
        if not saved.values:
            raise ValueError(f"no checkpoint found for run {run_id!r}")
        scenario_dict = saved.values["scenario"]
        first_input: Any = None
    else:
        if start_state is not None:
            scenario_dict = start_state["scenario"]
        else:
            scenario_dict = scenario if isinstance(scenario, dict) else load_scenario(scenario)
        run_id = run_id or (start_state or {}).get("run_id") or new_run_id()
        first_input = start_state if start_state is not None else initial_state(scenario_dict, run_id)
        first_input = {**first_input, "run_id": run_id}

    graph = build_graph(make_crew(scenario_dict, crew), checkpointer=checkpointer)
    config = run_config(run_id, scenario_dict)
    interrupted = await _drive(graph, first_input, config, on_update, on_interrupt)
    values = (await graph.aget_state(config)).values
    return RunResult(run_id=run_id, state=values, scorecard=score(values), interrupted=interrupted)


async def history(run_id: str, checkpointer: Any) -> list[dict]:
    """Checkpoints of a run, oldest first."""
    graph = build_graph(make_crew(load_scenario(), "scripted"), checkpointer=checkpointer)
    rows = []
    async for snap in graph.aget_state_history(run_config(run_id)):
        values = snap.values or {}
        if "world" not in values:
            continue
        events = values.get("events") or []
        rows.append({
            "checkpoint_id": snap.config["configurable"]["checkpoint_id"],
            "step": (snap.metadata or {}).get("step"),
            "next": list(snap.next),
            "clock_min": values["world"]["clock_min"],
            "mission_phase": values["timeline"]["mission_phase_name"],
            "turns": values["counters"]["turns"],
            "messages": len(values.get("log") or []),
            "status": values.get("status"),
            "last_event": events[-1]["type"] if events else None,
        })
    rows.reverse()
    return rows


async def state_at(run_id: str, checkpointer: Any, *, checkpoint_id: str | None = None,
                   at_clock: float | None = None) -> dict:
    """
    State of a run at a checkpoint where the scheduler is about to act.

    With ``at_clock``, the last such checkpoint at or before that sim time.
    With neither argument, the latest checkpoint.
    """
    graph = build_graph(make_crew(load_scenario(), "scripted"), checkpointer=checkpointer)
    best = None
    async for snap in graph.aget_state_history(run_config(run_id)):
        values = snap.values or {}
        if "world" not in values:
            continue
        cid = snap.config["configurable"]["checkpoint_id"]
        if checkpoint_id is not None:
            if cid == checkpoint_id:
                best = snap
                break
            continue
        if at_clock is None:
            best = snap
            break
        if tuple(snap.next) in ((SCHEDULER,), ()) and values["world"]["clock_min"] <= at_clock:
            best = snap
            break
    if best is None:
        raise ValueError(f"no matching checkpoint for run {run_id!r}")
    if checkpoint_id is not None and tuple(best.next) not in ((SCHEDULER,), ()):
        raise ValueError(f"checkpoint {checkpoint_id} is mid-turn (next: {best.next}); "
                         "pick one where the scheduler is next")
    return copy.deepcopy(dict(best.values))


def fork_state(values: dict, *, new_id: str, injects: list[dict] | None = None,
               settings: dict | None = None) -> dict:
    """
    A start state for a what-if branch: the saved state, optionally with
    evaluator injects applied and settings changed, under a new run id.
    """
    forked = copy.deepcopy(values)
    forked["run_id"] = new_id
    forked["status"] = "running"
    if settings:
        forked["scenario"]["settings"] = {**forked["scenario"]["settings"], **settings}
    if injects:
        update = apply_injects(forked, injects)
        forked["world"] = update["world"]
        forked["inboxes"] = update["inboxes"]
        forked["log"] = forked["log"] + update["log"]
        forked["events"] = forked["events"] + update["events"]
    forked["events"] = forked["events"] + [{
        "type": "fork", "t": forked["world"]["clock_min"], "from_run": values.get("run_id"),
        "injects": len(injects or [])}]
    return forked
