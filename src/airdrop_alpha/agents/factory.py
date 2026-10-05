"""
Build the five agents with LangChain's ``create_agent``.

Each agent is a role prompt, the tools that role is allowed to hold, and a
model.  The per-turn context (the world copy, the outbox) arrives through
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

from ..domain.world import ROLES, World
from ..tools.context import TurnContext
from ..tools.toolsets import TOOLSETS

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


def render_prompt(role: str, scenario: dict) -> str:
    """The system prompt for a role: role text plus the shared simulation protocol."""
    text = (PROMPT_DIR / f"{role.lower()}.md").read_text(encoding="utf-8")
    text = text.replace("{{ROUTE_TABLE}}", _route_table(scenario))
    return text.rstrip() + "\n" + (PROMPT_DIR / "_protocol.md").read_text(encoding="utf-8")


def resolve_models(models: Any = None) -> dict[str, BaseChatModel]:
    """
    Turn a model spec into one chat model per role.

    ``models`` may be None (read AIRDROP_MODEL / AIRDROP_MODEL_<ROLE> from the
    environment), a model string, a chat model, or a dict of role -> either.
    """
    def one(spec: Any) -> BaseChatModel:
        if isinstance(spec, BaseChatModel):
            return spec
        return init_chat_model(str(spec), max_tokens=4096)

    if isinstance(models, dict):
        default = models.get("default")
        return {role: one(models.get(role) or default or os.environ.get("AIRDROP_MODEL", DEFAULT_MODEL))
                for role in ROLES}
    if models is not None:
        shared = one(models)
        return {role: shared for role in ROLES}
    base = os.environ.get("AIRDROP_MODEL", DEFAULT_MODEL)
    cache: dict[str, BaseChatModel] = {}
    out = {}
    for role in ROLES:
        spec = os.environ.get(f"AIRDROP_MODEL_{role}", base)
        out[role] = cache.setdefault(spec, one(spec))
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


def build_crew(scenario: dict, models: Any = None) -> dict[str, Any]:
    """Build callsign -> agent for a scenario."""
    resolved = resolve_models(models)
    limit = int(scenario["settings"].get("max_model_calls_per_turn", 20))
    crew = {}
    for role in ROLES:
        crew[role] = create_agent(
            resolved[role],
            tools=TOOLSETS[role],
            system_prompt=render_prompt(role, scenario),
            context_schema=TurnContext,
            middleware=_middleware(resolved[role], limit),
            checkpointer=False,  # the mission graph checkpoints whole turns
            name=role.lower(),
        )
    return crew


__all__ = ["build_crew", "render_prompt", "resolve_models", "DEFAULT_MODEL"]
