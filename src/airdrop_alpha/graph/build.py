"""
Assemble the mission graph.

    START -> scheduler -> {COMMANDER | COPILOT | NAVIGATOR | LOADMASTER | ATC} -> scheduler -> ... -> END

The scheduler routes with ``Command(goto=...)``; every crew node returns to it.
One node runs per step, so there is exactly one checkpoint per agent turn and
per clock advance, and a run can be paused, resumed, replayed or forked at any
of them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from ..domain.data import knowledge_dir as default_knowledge_dir
from ..domain.world import ROLES
from .crew import make_crew_node
from .scheduler import SCHEDULER, scheduler
from .state import MissionState


def build_graph(crew: dict[str, Any], *, checkpointer: Any = None, knowledge_dir: Path | None = None):
    """
    Compile the mission graph.

    Args:
        crew: callsign -> compiled agent (see agents.factory.build_crew).
        checkpointer: a LangGraph checkpointer, or None for no persistence.
        knowledge_dir: where read_sop finds the SOP documents.
    """
    missing = [role for role in ROLES if role not in crew]
    if missing:
        raise ValueError(f"crew is missing agents for: {', '.join(missing)}")
    kdir = knowledge_dir or default_knowledge_dir()

    graph = StateGraph(MissionState)
    graph.add_node(SCHEDULER, scheduler, destinations=(*ROLES, SCHEDULER, END))
    for role in ROLES:
        graph.add_node(role, make_crew_node(role, crew[role], kdir),
                       retry_policy=RetryPolicy(max_attempts=3))
        graph.add_edge(role, SCHEDULER)
    graph.add_edge(START, SCHEDULER)
    return graph.compile(checkpointer=checkpointer)
