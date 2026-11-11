"""
Build one agent per seat with LangChain's ``create_agent``.

Each agent is the prompt for its seat's role, the tools that role holds, and a
model.  The seats come from the run's roster (agents.types.bind_roster); the
prompt set and the default model come from the seat's agent type.  The
per-turn context (the world copy, the outbox) arrives through
``context_schema``; the agents keep no state of their own between turns.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from ..domain.world import World
from ..tools.context import TurnContext
from ..tools.toolsets import TOOLSETS
from .types import PROMPTS_V1, agent_type

PROMPT_DIR = Path(__file__).parent / "prompts"

#: The original airdrop-alpha model, kept as the default so runs are comparable.
DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


def _route_table(scenario: dict) -> str:
    world = World.new(departure_fuel_lbs=scenario["departure_fuel_lbs"],
                      waypoint_times=scenario["waypoint_times"], fuel_curve=scenario["fuel_curve"])
    route = world.compute_route()
    lines = [f"Route: {' > '.join(route['full_route'])}", "", "Planned leg data:"]
    for index, leg in enumerate(route["legs"], start=1):
        burn = leg.get("planned_fuel_burn_lbs")
        lines.append(
            f"  Leg {index}: {leg['from']} > {leg['to']} - {leg['heading_deg']:03d} deg / "
            f"{leg['distance_nm']} NM / {leg['time_min']} min"
            + (f" / {burn:,} lbs fuel" if burn is not None else "")
        )
    lines.append(f"Total: {route['total_distance_nm']} NM / {route['total_time_min']} min airborne.")
    if route["planned_arrival_fuel_lbs"] is not None:
        lines.append(
            f"Fuel: start {scenario['departure_fuel_lbs']:,.0f} lbs, planned burn "
            f"{route['planned_total_burn_lbs']:,} lbs including ground operations, "
            f"planned arrival {route['planned_arrival_fuel_lbs']:,} lbs."
        )
    return "\n".join(lines)


def render_prompt(role: str, scenario: dict, prompts: dict[str, str] | None = None) -> str:
    """
    The system prompt for a role: role text plus the shared simulation protocol.
    ``role`` is a role id (``loadmaster``); a standard callsign (``LOADMASTER``)
    also works.
    """
    filename = (prompts or PROMPTS_V1).get(role) or f"{role.lower()}.md"
    text = (PROMPT_DIR / filename).read_text(encoding="utf-8")
    text = text.replace("{{ROUTE_TABLE}}", _route_table(scenario))
    return text.rstrip() + "\n" + (PROMPT_DIR / "_protocol.md").read_text(encoding="utf-8")


def _seats(scenario: dict, roster: list[dict] | None) -> list[dict]:
    return roster if roster is not None else list(scenario["order"]["roster"])


def resolve_models(models: Any = None, seats: list[dict] | None = None) -> dict[str, BaseChatModel]:
    """
    One chat model per seat, keyed by callsign.

    ``models`` may be None (environment: AIRDROP_MODEL_<CALLSIGN>, then
    AIRDROP_MODEL, then the agent type's model), a model string, a chat model,
    or a dict keyed by callsign (or "default").
    """
    seats = seats if seats is not None else [{"callsign": c, "agent_id": f"GeneralistV1.Instance{i}"}
                                             for i, c in enumerate(["COMMANDER", "COPILOT", "NAVIGATOR",
                                                                    "LOADMASTER", "ATC"], start=1)]

    def one(spec: Any) -> BaseChatModel:
        if isinstance(spec, BaseChatModel):
            return spec
        return init_chat_model(str(spec), max_tokens=4096)

    def type_model(seat: dict) -> str:
        try:
            return agent_type(seat["agent_id"]).model or DEFAULT_MODEL
        except ValueError:
            return DEFAULT_MODEL

    if isinstance(models, dict):
        default = models.get("default")
        return {seat["callsign"]: one(models.get(seat["callsign"]) or default
                                      or os.environ.get("AIRDROP_MODEL", type_model(seat)))
                for seat in seats}
    if models is not None:
        shared = one(models)
        return {seat["callsign"]: shared for seat in seats}
    cache: dict[str, BaseChatModel] = {}
    out = {}
    for seat in seats:
        key = seat["callsign"].replace(" ", "_")
        spec = os.environ.get(f"AIRDROP_MODEL_{key}") or os.environ.get("AIRDROP_MODEL") or type_model(seat)
        out[seat["callsign"]] = cache.setdefault(spec, one(spec))
    return out


def _middleware(model: BaseChatModel, max_model_calls: int) -> list:
    middleware: list = [ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="end")]
    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
    except ImportError:  # pragma: no cover - langchain-anthropic is a declared dependency
        return middleware
    if isinstance(model, ChatAnthropic):
        # The system prompt and tool definitions are identical on every turn.
        middleware.append(AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"))
    return middleware


def build_crew(scenario: dict, models: Any = None, roster: list[dict] | None = None) -> dict[str, Any]:
    """Build callsign -> agent, one per seat of ``roster`` (default: the seats as ordered)."""
    seats = _seats(scenario, roster)
    resolved = resolve_models(models, seats)
    limit = int(scenario["settings"].get("max_model_calls_per_turn", 20))
    crew = {}
    for seat in seats:
        callsign, role = seat["callsign"], seat["role"]
        if role not in TOOLSETS:
            raise ValueError(f"{callsign}: no tool set for role {role!r}; known: {', '.join(TOOLSETS)}")
        try:
            prompts = agent_type(seat["agent_id"]).prompts or PROMPTS_V1
        except ValueError:
            prompts = PROMPTS_V1
        crew[callsign] = create_agent(
            resolved[callsign],
            tools=TOOLSETS[role],
            system_prompt=render_prompt(role, scenario, prompts),
            context_schema=TurnContext,
            middleware=_middleware(resolved[callsign], limit),
            checkpointer=False,  # the mission graph checkpoints whole turns
            name=callsign.lower().replace(" ", "_"),
        )
    return crew


__all__ = ["build_crew", "render_prompt", "resolve_models", "DEFAULT_MODEL"]
