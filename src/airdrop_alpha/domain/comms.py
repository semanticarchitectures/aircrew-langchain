"""
Crew communications: message shape, channels and the routing policy.

The original parsed FROM/TO/PRIORITY headers out of free text and defaulted
anything unparseable to COMMANDER.  Here a message only exists if an agent
called a tool to send it, and who may talk to whom is checked in code against
the nets in the mission order (:class:`~.roster.Roster`):

* An interphone net joins the stations aboard the aircraft.  "ALL" (or
  "CREW") means every other member of the sender's interphone.
* A radio net joins an aircraft station to an outside station.  A station
  with no interphone (ATC) can address only the stations on its radio nets.
  A crew member addresses an outside station only if they share a radio net;
  otherwise the call goes through whoever is on the radio.

With the standard crew this is exactly the original policy: the four crew
members on the interphone, and COPILOT and ATC on the radio.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from .roster import Roster, standard_roster

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
    sender: str              # callsign, or a non-agent sender such as SIM
    sender_id: str           # agent id of the sender, when the sender is an agent
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


def resolve_recipients(sender: str, to: list[str] | str,
                       roster: Roster | None = None) -> tuple[str, list[str]]:
    """
    Apply the comms policy for a sender callsign.  Returns (channel,
    recipient callsigns) or raises :class:`CommsDenied`.
    """
    roster = roster or _STANDARD
    callsigns = roster.callsigns
    raw = [to] if isinstance(to, str) else list(to)
    names: list[str] = []
    for item in raw:
        names.extend(part for part in str(item).split(",") if part.strip())
    names = [normalise_callsign(n) for n in names]
    if not names:
        raise CommsDenied("no_recipient", "No recipient given.")

    interphone = roster.interphone_of(sender)
    if interphone is None:
        # An outside station: it talks only to the stations on its radio nets.
        peers = roster.radio_peers(sender)
        if not peers or any(n in BROADCAST_ALIASES for n in names) or not set(names) <= set(peers):
            listed = ", ".join(peers) or "nobody"
            raise CommsDenied(
                "atc_radio_only",
                f"{sender} talks to {roster.aircraft_callsign} on the radio, and only {listed} "
                f"{'is' if len(peers) == 1 else 'are'} on the radio. Address {' or '.join(peers) or 'nobody'}.",
            )
        return RADIO, list(dict.fromkeys(names))

    recipients: list[str] = []
    for name in names:
        if name in BROADCAST_ALIASES:
            recipients.extend(c for c in interphone.members if c != sender)
        elif name in callsigns:
            recipients.append(name)
        else:
            raise CommsDenied("unknown_callsign", f"Unknown callsign {name!r}. Valid: {', '.join(callsigns)}, ALL.")
    recipients = [r for r in dict.fromkeys(recipients) if r != sender]
    if not recipients:
        raise CommsDenied("no_recipient", "A message addressed only to yourself is not sent.")

    outside = [r for r in recipients if r not in interphone.members]
    if outside:
        peers = roster.radio_peers(sender)
        if not set(outside) <= set(peers):
            target = [r for r in outside if r not in peers][0]
            operators = roster.radio_operators_for(target) or ["nobody aboard"]
            raise CommsDenied(
                "atc_via_copilot",
                f"{sender} is not on the radio. All {target} communication goes through "
                f"{' or '.join(operators)}: ask {operators[0]} to make the call.",
            )
        if len(recipients) > len(outside):
            raise CommsDenied(
                "mixed_channels",
                f"{', '.join(outside)} {'is' if len(outside) == 1 else 'are'} on the radio and the crew "
                "are on the interphone. Send two separate messages.",
            )
        return RADIO, outside
    return INTERPHONE, recipients


_STANDARD = standard_roster()


def make_message(
    *, sender: str, to: list[str], body: str, priority: str = "ROUTINE",
    channel: str = INTERPHONE, kind: str = "voice", meta: dict | None = None,
    sender_id: str | None = None,
) -> CrewMessage:
    priority = str(priority).strip().upper()
    if priority not in PRIORITIES:
        priority = "ROUTINE"
    message = CrewMessage(sender=sender, to=list(to), body=body.strip(), priority=priority,
                          channel=channel, kind=kind, meta=dict(meta or {}))
    if sender_id:
        message["sender_id"] = sender_id
    return message
