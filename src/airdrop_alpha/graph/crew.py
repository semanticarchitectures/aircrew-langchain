"""
Crew nodes: one agent turn as a transaction on the mission state.

A turn loads the world from graph state, lets the agent act on that private
copy through its tools, and commits world, messages and audit events together
when the agent finishes.  If the model call fails part-way, nothing is
committed and the checkpoint before the turn is still valid.

What an agent remembers is its own mission log: for each earlier turn, what it
heard, what it did and what it said.  Raw tool output from earlier turns is not
replayed into the prompt; the instruments are the source of truth and can be
read again.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from ..domain.comms import INTERPHONE, NON_AGENT_SENDERS, CrewMessage
from ..domain.world import CREW, World
from ..tools.context import TurnContext
from .state import MissionState, post_messages

#: Final text that reads like a radio call.  If a turn ends with this and nothing
#: was sent, the agent probably "spoke" without calling send_message.
_SPEECH = re.compile(
    r"^\W*(COMMANDER|COPILOT|NAVIGATOR|LOADMASTER|ATC|CREW|ALL STATIONS|CONDOR 71|ALPHA APPROACH)\b[,.:]",
    re.IGNORECASE)

NOW_MARKER = "=== NOW:"
LOG_MARKER = "=== YOUR MISSION LOG"
_BODY_LIMIT = 700


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _header(message: CrewMessage, viewer: str) -> str:
    to = ", ".join("you" if r == viewer else r for r in message["to"])
    tag = f" ({message['kind']})" if message.get("kind") not in (None, "voice") else ""
    return f"[#{message['seq']} {message['channel']} {message['priority']}{tag}] {message['sender']} -> {to}"


def render_turn_prompt(
    *, callsign: str, clock_min: float, mission_phase: str, flight_phase: str,
    memory: list[str], omitted: int, incoming: list[CrewMessage], overheard: list[CrewMessage],
) -> str:
    """The single human message an agent receives for a turn."""
    parts = [f"{LOG_MARKER} (your earlier turns, oldest first) ==="]
    if omitted:
        parts.append(f"({omitted} older entries omitted)")
    parts.append("\n".join(memory) if memory else "(no earlier turns)")
    parts.append("")
    parts.append(f"{NOW_MARKER} T+{clock_min:g} min | {mission_phase} | aircraft: {flight_phase} ===")
    parts.append("INCOMING TRAFFIC (addressed to you):")
    for message in incoming:
        parts.append(_header(message, callsign))
        parts.append(message["body"])
        parts.append("")
    if overheard:
        parts.append("OVERHEARD ON THE INTERPHONE (not addressed to you; no response required):")
        for message in overheard:
            parts.append(f"{_header(message, callsign)}: {_clip(message['body'], 300)}")
        parts.append("")
    parts.append("Act with your tools. Speak only through send_message. "
                 "If nothing needs saying, end your turn without sending anything.")
    return "\n".join(parts)


def _summarise_result(name: str, content: Any) -> str:
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return _clip(text, 200)
    if not isinstance(payload, dict):
        return _clip(text, 200)
    if payload.get("denied"):
        return f"DENIED ({payload.get('rule')}): {payload.get('reason')}"
    if payload.get("error"):
        return f"ERROR: {_clip(payload['error'], 200)}"
    if name == "read_sop":
        return f"loaded {payload.get('document_name')}"
    if name == "execute_checklist":
        if payload.get("all_complete"):
            return f"{payload.get('checklist_name')} complete"
        opens = ", ".join(i["item"] for i in payload.get("open_items", []))
        return f"{payload.get('checklist_name')} NOT complete; open: {opens}"
    payload.pop("note", None)
    payload.pop("notes", None)
    return _clip(json.dumps(payload, default=str), 220)


def summarise_turn(
    *, clock_min: float, incoming: list[CrewMessage], new_messages: list, sent: list[CrewMessage],
) -> tuple[str, dict[str, int]]:
    """Build the mission-log entry for a finished turn, and count its usage."""
    stats = {"model_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "cache_read_tokens": 0, "cache_write_tokens": 0}
    calls: dict[str, dict] = {}
    actions: list[str] = []
    note = ""
    for message in new_messages:
        if isinstance(message, AIMessage):
            stats["model_calls"] += 1
            usage = message.usage_metadata or {}
            stats["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            stats["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            details = usage.get("input_token_details") or {}
            stats["cache_read_tokens"] += int(details.get("cache_read", 0) or 0)
            # langchain-anthropic reports cache writes per TTL when the API gives the
            # breakdown, and zeroes "cache_creation" in that case.
            stats["cache_write_tokens"] += sum(int(details.get(key, 0) or 0) for key in (
                "cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"))
            for call in message.tool_calls:
                calls[call["id"]] = call
            if not message.tool_calls and message.text:
                note = message.text
        elif isinstance(message, ToolMessage):
            stats["tool_calls"] += 1
            call = calls.get(message.tool_call_id, {"name": message.name or "tool", "args": {}})
            if call["name"] == "send_message":
                result = _summarise_result("send_message", message.content)
                if result.startswith("DENIED"):
                    actions.append(f"send_message to {call['args'].get('to')} -> {result}")
                continue
            args = ", ".join(f"{k}={_clip(json.dumps(v, default=str), 60)}" for k, v in call["args"].items())
            actions.append(f"{call['name']}({args}) -> {_summarise_result(call['name'], message.content)}")

    lines = [f"T+{clock_min:g}"]
    for message in incoming:
        lines.append(f"  HEARD #{message['seq']} from {message['sender']}: {_clip(message['body'], _BODY_LIMIT)}")
    for action in actions:
        lines.append(f"  DID {action}")
    for message in sent:
        lines.append(f"  SAID #{message['seq']} to {', '.join(message['to'])}: {_clip(message['body'], _BODY_LIMIT)}")
    if not actions and not sent:
        lines.append("  (took no action and stayed silent)")
    if note:
        lines.append(f"  NOTE {_clip(note, 300)}")
    stats["unsent_speech"] = int(bool(note) and not sent and bool(_SPEECH.match(str(note))))
    return "\n".join(lines), stats


def make_crew_node(callsign: str, agent: Any, knowledge_dir: Path):
    """Build the graph node that gives ``callsign`` one turn."""

    async def crew_turn(state: MissionState, config: RunnableConfig) -> dict:
        settings = state["scenario"]["settings"]
        world = World.model_validate(state["world"])
        log = state["log"]
        incoming = [log[seq - 1] for seq in state["inboxes"].get(callsign, [])]
        last_seen = state["last_seen"].get(callsign, 0)

        overheard: list[CrewMessage] = []
        if settings.get("party_line") and callsign in CREW:
            mine = {m["seq"] for m in incoming}
            overheard = [m for m in log[last_seen:]
                         if m["channel"] == INTERPHONE and m["seq"] not in mine
                         and m["sender"] != callsign and callsign not in m["to"]]

        entries = state["memory"].get(callsign, [])
        keep = int(settings.get("memory_max_entries", 60))
        prompt = render_turn_prompt(
            callsign=callsign, clock_min=world.clock_min,
            mission_phase=state["timeline"]["mission_phase_name"],
            flight_phase=world.effective_phase,
            memory=entries[-keep:], omitted=max(0, len(entries) - keep),
            incoming=incoming, overheard=overheard,
        )

        ctx = TurnContext(world=world, actor=callsign, knowledge_dir=knowledge_dir)
        turn_number = state["counters"]["turns"] + 1
        result = await agent.ainvoke(
            {"messages": [HumanMessage(prompt)]},
            context=ctx,
            config={
                "recursion_limit": 4 * int(settings.get("max_model_calls_per_turn", 20)) + 10,
                "run_name": f"{callsign} turn {turn_number}",
                "tags": [f"role:{callsign}"],
                "metadata": {"callsign": callsign, "sim_time_min": world.clock_min,
                             "run_id": state.get("run_id"), "turn": turn_number},
            },
        )

        stamped, inboxes = post_messages(ctx.outbox, log_length=len(log),
                                         inboxes={**state["inboxes"], callsign: []},
                                         clock_min=world.clock_min)
        entry, stats = summarise_turn(clock_min=world.clock_min, incoming=incoming,
                                      new_messages=result["messages"][1:], sent=stamped)

        counters = dict(state["counters"])
        counters["turns"] = turn_number
        counters["burst_turns"] = counters.get("burst_turns", 0) + 1
        for key in ("model_calls", "tool_calls", "input_tokens", "output_tokens",
                    "cache_read_tokens", "cache_write_tokens"):
            counters[key] = counters.get(key, 0) + stats[key]
        by_agent = dict(counters.get("turns_by_agent", {}))
        by_agent[callsign] = by_agent.get(callsign, 0) + 1
        counters["turns_by_agent"] = by_agent

        events = world.drain_journal() + ctx.comms_events
        events.append({
            "type": "turn", "t": round(world.clock_min, 2), "actor": callsign, "turn": turn_number,
            "heard": [m["seq"] for m in incoming], "sent": [m["seq"] for m in stamped],
            "silent": not stamped, "from_sim_only": all(m["sender"] in NON_AGENT_SENDERS for m in incoming),
            **stats,
        })

        return {
            "world": world.model_dump(),
            "log": stamped,
            "events": events,
            "inboxes": inboxes,
            "memory": {**state["memory"], callsign: entries + [entry]},
            "last_seen": {**state["last_seen"], callsign: len(log)},
            "counters": counters,
        }

    crew_turn.__name__ = f"{callsign.lower()}_turn"
    return crew_turn
