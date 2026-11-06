"""
Assemble the mission graph.

    START -> scheduler -> {one node per seat in the mission order} -> scheduler -> ... -> END

Seat nodes are named by callsign (COMMANDER, ..., ATC for the standard order).
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
from .crew import make_crew_node
from .scheduler import SCHEDULER, scheduler
from .state import MissionState


def build_graph(crew: dict[str, Any], *, checkpointer: Any = None, knowledge_dir: Path | None = None):
    """
    Compile the mission graph.

    Args:
        crew: callsign -> compiled agent, one per seat, in roster order
            (see agents.factory.build_crew).
        checkpointer: a LangGraph checkpointer, or None for no persistence.
        knowledge_dir: where read_sop finds the SOP documents.
    """
    if not crew:
        raise ValueError("crew is empty: the mission order has no seats")
    if SCHEDULER in crew:
        raise ValueError(f"{SCHEDULER!r} cannot be a callsign")
    kdir = knowledge_dir or default_knowledge_dir()
    seats = list(crew)

    graph = StateGraph(MissionState)
    graph.add_node(SCHEDULER, scheduler, destinations=(*seats, SCHEDULER, END))
    for callsign in seats:
        graph.add_node(callsign, make_crew_node(callsign, crew[callsign], kdir),
                       retry_policy=RetryPolicy(max_attempts=3))
        graph.add_edge(callsign, SCHEDULER)
    graph.add_edge(START, SCHEDULER)
    return graph.compile(checkpointer=checkpointer)
