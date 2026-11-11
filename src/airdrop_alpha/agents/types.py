"""
Agent types: named, versioned configurations that fill seats.

An agent id is ``<Type>V<version>.Instance<n>``.  The type and version name a
configuration that does not change once runs have been recorded against it:
model, prompts, tool set, context policy.  Changing any of those means a new
version, so that results from different runs stay comparable.

``GeneralistV1`` is the configuration flown in the live runs of 3 October
2026 (live1, live2): one ``create_agent`` per seat on Claude Sonnet 4.6, the
role prompts in ``agents/prompts``, the role tool sets, and the mission log as
memory.  Its fingerprint (prompt templates, tool schemas, model, middleware)
is pinned below and checked by a test, so an edit to any of them fails until a
new version is added.

The scripted types are test fixtures: deterministic playbooks, no model.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

from ..domain.roster import (
    AIR_TRAFFIC_CONTROLLER, AIRCRAFT_COMMANDER, COPILOT, LOADMASTER, NAVIGATOR, make_agent_id, parse_agent_id,
)

AIRDROP_ROLES = (AIRCRAFT_COMMANDER, COPILOT, NAVIGATOR, LOADMASTER, AIR_TRAFFIC_CONTROLLER)

#: Prompt template per role for the version-1 prompt set.
PROMPTS_V1 = {
    AIRCRAFT_COMMANDER: "commander.md",
    COPILOT: "copilot.md",
    NAVIGATOR: "navigator.md",
    LOADMASTER: "loadmaster.md",
    AIR_TRAFFIC_CONTROLLER: "atc.md",
}


@dataclass(frozen=True)
class AgentType:
    name: str
    version: int
    harness: str                                  # create_agent | scripted
    description: str
    qualified_roles: tuple[str, ...]
    model: str | None = None
    max_tokens: int | None = None
    playbook: str | None = None
    prompts: dict[str, str] = field(default_factory=dict)
    context: str = ""
    middleware: tuple[str, ...] = ()
    fingerprint: str | None = None                # pinned; checked by tests/test_types.py

    @property
    def key(self) -> str:
        return f"{self.name}V{self.version}"

    def manifest(self) -> dict:
        out: dict[str, Any] = {
            "type": self.key, "harness": self.harness, "description": self.description,
            "qualified_roles": list(self.qualified_roles),
        }
        for name in ("model", "max_tokens", "playbook", "context"):
            if getattr(self, name):
                out[name] = getattr(self, name)
        if self.prompts:
            out["prompts"] = dict(self.prompts)
        if self.middleware:
            out["middleware"] = list(self.middleware)
        if self.fingerprint:
            out["fingerprint"] = self.fingerprint
        return out


GENERALIST_V1 = AgentType(
    name="Generalist", version=1, harness="create_agent",
    description="The configuration flown in live1 and live2 (3 October 2026): one LangChain create_agent "
                "per seat, role prompt plus the shared protocol, the role's tool set.",
    qualified_roles=AIRDROP_ROLES,
    model="anthropic:claude-sonnet-4-6", max_tokens=4096,
    prompts=PROMPTS_V1,
    context="Full role prompt and tool set every call; memory is the agent's own mission log, "
            "last memory_max_entries turns (60 in the scenario).",
    middleware=("ModelCallLimitMiddleware(run_limit=max_model_calls_per_turn, exit_behavior=end)",
                "AnthropicPromptCachingMiddleware(unsupported_model_behavior=ignore)"),
    fingerprint="f843ac3729ced7445b26a2c86f085c5272c467799d1a302a78bbeadc1921179f",
)


def _scripted(name: str, playbook: str, description: str) -> AgentType:
    return AgentType(name=name, version=1, harness="scripted", description=description,
                     qualified_roles=AIRDROP_ROLES, playbook=playbook)


AGENT_TYPES: dict[str, AgentType] = {t.key: t for t in (
    GENERALIST_V1,
    _scripted("ScriptedNominal", "scripted", "Deterministic playbook: flies the nominal mission, handles the "
              "cargo-shift abort."),
    _scripted("ScriptedRogue", "rogue", "Nominal playbook with a loadmaster who tries the door and a release "
              "before being authorized."),
    _scripted("ScriptedEager", "eager", "Nominal playbook with a commander who calls the drop four minutes "
              "before the CARP."),
)}

#: ``--crew`` names that replace the ordered agent type in every seat.
CREW_TYPES = {"scripted": "ScriptedNominalV1", "nominal": "ScriptedNominalV1",
              "rogue": "ScriptedRogueV1", "eager": "ScriptedEagerV1"}


class AgentTypeError(ValueError):
    """An agent id names a type or version that is not registered."""


def agent_type(agent_id_or_key: str) -> AgentType:
    key = agent_id_or_key
    if ".Instance" in key:
        name, version, _ = parse_agent_id(key)
        key = f"{name}V{version}"
    found = AGENT_TYPES.get(key)
    if found is None:
        raise AgentTypeError(f"unknown agent type {key!r}. Registered: {', '.join(AGENT_TYPES)}")
    return found


def bind_roster(order_roster: list[dict], crew: Any = "live",
                environ: dict | None = None) -> list[dict]:
    """
    The run's roster: the ordered seats with the agents that will actually fly
    them.  A scripted ``crew`` replaces every seat's type (the id says what ran);
    a model passed in, or a model set in the environment, is recorded as an
    override of the ordered type's model.
    """
    env = os.environ if environ is None else environ
    replacement = CREW_TYPES.get(crew) if isinstance(crew, str) else None
    seats = []
    for seat in order_roster:
        ordered = seat["agent_id"]
        type_name, version, instance = parse_agent_id(ordered)
        if replacement:
            kind = AGENT_TYPES[replacement]
            agent_id = make_agent_id(kind.name, kind.version, instance)
        else:
            kind = agent_type(ordered)
            agent_id = ordered
        overrides: dict[str, Any] = {}
        if not replacement and kind.harness == "create_agent":
            if crew == "live":
                model = env.get(f"AIRDROP_MODEL_{seat['callsign'].replace(' ', '_')}") or env.get("AIRDROP_MODEL")
                if model and model != kind.model:
                    overrides["model"] = model
            elif crew is not None:
                overrides["model"] = crew if isinstance(crew, str) else type(crew).__name__ \
                    if not isinstance(crew, dict) else "per-seat models"
        entry = {**seat, "agent_id": agent_id, "type": kind.key, "instance": instance,
                 "manifest": kind.manifest()}
        if agent_id != ordered:
            entry["ordered_as"] = ordered
        if overrides:
            entry["overrides"] = overrides
        seats.append(entry)
    return seats


def fingerprint_generalist_v1() -> str:
    """Hash of what a GeneralistV1 model sees before the first turn: prompt templates and tool schemas."""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    from ..tools.toolsets import TOOLSETS
    from .factory import PROMPT_DIR

    parts: dict[str, Any] = {
        "protocol": (PROMPT_DIR / "_protocol.md").read_text(encoding="utf-8"),
        "model": GENERALIST_V1.model, "max_tokens": GENERALIST_V1.max_tokens,
        "middleware": list(GENERALIST_V1.middleware),
    }
    for role, filename in sorted(GENERALIST_V1.prompts.items()):
        parts[f"prompt:{role}"] = (PROMPT_DIR / filename).read_text(encoding="utf-8")
        parts[f"tools:{role}"] = [convert_to_openai_tool(t) for t in TOOLSETS[role]]
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


__all__ = ["AGENT_TYPES", "AgentType", "AgentTypeError", "CREW_TYPES", "GENERALIST_V1", "agent_type",
           "bind_roster", "fingerprint_generalist_v1"]
