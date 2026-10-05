"""Per-turn context handed to every tool through LangChain's ToolRuntime."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain.comms import CrewMessage
from ..domain.world import World


@dataclass
class TurnContext:
    """
    What one agent turn works against.

    ``world`` is a private copy loaded from graph state.  Tools mutate it; the
    crew node commits it back to graph state only when the turn finishes, so a
    failed turn leaves the mission state untouched.
    """

    world: World
    actor: str
    knowledge_dir: Path
    outbox: list[CrewMessage] = field(default_factory=list)
    comms_events: list[dict] = field(default_factory=list)
