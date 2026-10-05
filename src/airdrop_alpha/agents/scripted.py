"""
A deterministic stand-in for a chat model.

``ScriptedChatModel`` plays a role from a playbook of rules instead of calling
an LLM.  It is what makes the whole system testable offline: the graph, the
scheduler, the guards, checkpointing and the scorecard all run for real, with
only the reasoning replaced.

A rule fires when its pattern matches the new traffic of the turn.  The model
is stateless: it works out where it is in a turn from the messages it is
given, so it behaves identically when a run is replayed from a checkpoint.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from ..graph.crew import LOG_MARKER, NOW_MARKER

Call = tuple[str, dict[str, Any]]


def say(to: str | list[str], body: str, priority: str = "ROUTINE") -> Call:
    """A send_message call."""
    return ("send_message", {"to": [to] if isinstance(to, str) else to, "body": body, "priority": priority})


@dataclass
class Rule:
    """When ``when`` matches this turn's traffic, emit ``steps`` (one model step each)."""
    when: str
    steps: list[list[Call]]
    requires: str | None = None        # must also match somewhere in the log or this turn
    unless_logged: str | None = None   # skip if this matches the agent's mission log
    unless_now: str | None = None      # skip if this also matches this turn's traffic
    note: str = ""
    _pattern: re.Pattern = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._pattern = re.compile(self.when, re.IGNORECASE | re.DOTALL)

    def matches(self, now: str, log: str) -> bool:
        if not self._pattern.search(now):
            return False
        if self.requires and not re.search(self.requires, log + now, re.IGNORECASE | re.DOTALL):
            return False
        if self.unless_now and re.search(self.unless_now, now, re.IGNORECASE | re.DOTALL):
            return False
        if self.unless_logged and re.search(self.unless_logged, log, re.IGNORECASE | re.DOTALL):
            return False
        return True


def split_prompt(text: str) -> tuple[str, str]:
    """Split a turn prompt into (mission log, this turn's traffic)."""
    if NOW_MARKER in text:
        log, now = text.split(NOW_MARKER, 1)
        now = now.split("OVERHEARD ON THE INTERPHONE", 1)[0]
        return log.replace(LOG_MARKER, ""), now
    return "", text


class ScriptedChatModel(BaseChatModel):
    """Chat model that follows a playbook.  See module docstring."""

    role: str
    playbook: list[Rule]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _plan(self, prompt: str) -> tuple[list[list[Call]], str]:
        log, now = split_prompt(prompt)
        steps: list[list[Call]] = []
        notes: list[str] = []
        for rule in self.playbook:
            if rule.matches(now, log):
                steps.extend(rule.steps)
                if rule.note:
                    notes.append(rule.note)
        return steps, " ".join(notes)

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        human_index = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
        prompt = str(messages[human_index].content) if human_index >= 0 else ""
        taken = sum(1 for m in messages[human_index + 1:] if isinstance(m, AIMessage))
        steps, note = self._plan(prompt)
        if taken < len(steps):
            digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:10]
            calls = [{"name": name, "args": dict(args), "id": f"{self.role.lower()}-{digest}-{taken}-{i}",
                      "type": "tool_call"} for i, (name, args) in enumerate(steps[taken])]
            message = AIMessage(content="", tool_calls=calls)
        else:
            message = AIMessage(content=note)
        return ChatResult(generations=[ChatGeneration(message=message)])
