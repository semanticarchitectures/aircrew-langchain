"""
Crew communications: message shape, channels and the routing policy.

The original parsed FROM/TO/PRIORITY headers out of free text and defaulted
anything unparseable to COMMANDER.  Here a message only exists if an agent
called a tool to send it, and who may talk to whom is checked in code:

* INTERPHONE connects the four crew members.
* RADIO connects COPILOT and ATC.  Nobody else may address ATC, and ATC may
  address nobody else.
* "ALL" (or "CREW") means every crew member on the interphone except the
  sender.  It never includes ATC.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from .world import CREW, ROLES

Priority = Literal["ROUTINE", "URGENT", "EMERGENCY"]
PRIORITIES: tuple[str, ...] = ("ROUTINE", "URGENT", "EMERGENCY")
PRIORITY_RANK = {"ROUTINE": 0, "URGENT": 1, "EMERGENCY": 2}

INTERPHONE = "INTERPHONE"
RADIO = "RADIO"
SIM = "SIM"

#: Senders that are not agents.  Their messages are injections into the sim.
SCENARIO_SENDER = "SCENARIO_RUNNER"
EVALUATOR_SENDER = "EVALUATOR"
SYSTEM_SENDER = "SIM"
NON_AGENT_SENDERS = (SCENARIO_SENDER, EVALUATOR_SENDER, SYSTEM_SENDER)

BROADCAST_ALIASES = ("ALL", "CREW", "ALL CREW", "ALL STATIONS")


class CrewMessage(TypedDict, total=False):
    seq: int
    t: float                 # sim minutes
    sender: str
    to: list[str]
    channel: str             # INTERPHONE | RADIO | SIM
    priority: str
    kind: str                # voice | authorization | clearance | advisory | abort | emergency | decision | inject | system
    body: str
    meta: dict[str, Any]


class CommsDenied(Exception):
    """A transmission that the comms policy does not allow."""

    def __init__(self, rule: str, reason: str) -> None:
        super().__init__(reason)
        self.rule = rule
        self.reason = reason


def normalise_callsign(name: str) -> str:
    key = " ".join(str(name).strip().upper().split())
    aliases = {
        "AC": "COMMANDER", "AIRCRAFT COMMANDER": "COMMANDER", "PILOT": "COMMANDER",
        "CP": "COPILOT", "CO-PILOT": "COPILOT",
        "NAV": "NAVIGATOR", "LM": "LOADMASTER",
        "ALPHA APPROACH": "ATC", "TOWER": "ATC", "GROUND": "ATC", "CLEARANCE DELIVERY": "ATC",
    }
    return aliases.get(key, key)


def resolve_recipients(sender: str, to: list[str] | str) -> tuple[str, list[str]]:
    """
    Apply the comms policy.  Returns (channel, recipients) or raises
    :class:`CommsDenied`.
    """
    raw = [to] if isinstance(to, str) else list(to)
    names: list[str] = []
    for item in raw:
        names.extend(part for part in str(item).split(",") if part.strip())
    names = [normalise_callsign(n) for n in names]
    if not names:
        raise CommsDenied("no_recipient", "No recipient given.")

    if sender == "ATC":
        if any(n in BROADCAST_ALIASES for n in names) or set(names) != {"COPILOT"}:
            raise CommsDenied(
                "atc_radio_only",
                "ATC talks to CONDOR 71 on the radio, and only COPILOT is on the radio. Address COPILOT.",
            )
        return RADIO, ["COPILOT"]

    recipients: list[str] = []
    for name in names:
        if name in BROADCAST_ALIASES:
            recipients.extend(c for c in CREW if c != sender)
        elif name in ROLES:
            recipients.append(name)
        else:
            raise CommsDenied("unknown_callsign", f"Unknown callsign {name!r}. Valid: {', '.join(ROLES)}, ALL.")
    recipients = [r for r in dict.fromkeys(recipients) if r != sender]
    if not recipients:
        raise CommsDenied("no_recipient", "A message addressed only to yourself is not sent.")

    if "ATC" in recipients:
        if sender != "COPILOT":
            raise CommsDenied(
                "atc_via_copilot",
                f"{sender} is not on the radio. All ATC communication goes through COPILOT: "
                "ask COPILOT to make the call.",
            )
        if len(recipients) > 1:
            raise CommsDenied(
                "mixed_channels",
                "ATC is on the radio and the crew are on the interphone. Send two separate messages.",
            )
        return RADIO, ["ATC"]
    return INTERPHONE, recipients


def make_message(
    *, sender: str, to: list[str], body: str, priority: str = "ROUTINE",
    channel: str = INTERPHONE, kind: str = "voice", meta: dict | None = None,
) -> CrewMessage:
    priority = str(priority).strip().upper()
    if priority not in PRIORITIES:
        priority = "ROUTINE"
    return CrewMessage(sender=sender, to=list(to), body=body.strip(), priority=priority,
                       channel=channel, kind=kind, meta=dict(meta or {}))
