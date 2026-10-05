"""
Entry point for LangGraph Studio and ``langgraph dev`` (see langgraph.json).

    AIRDROP_CREW      live (default), scripted or rogue
    AIRDROP_SCENARIO  path to a scenario file (default scenarios/airdrop_alpha.yaml)

Start a run with an empty input ({}): the scheduler loads the scenario and
builds the initial state itself.  The server supplies the checkpointer.

Imports are absolute because the server loads this file by path.
"""
from __future__ import annotations

import os

from airdrop_alpha.graph.build import build_graph
from airdrop_alpha.runner import make_crew
from airdrop_alpha.scenario import load_scenario


def make_graph():
    scenario = load_scenario(os.environ.get("AIRDROP_SCENARIO") or None)
    return build_graph(make_crew(scenario, os.environ.get("AIRDROP_CREW", "live")))
