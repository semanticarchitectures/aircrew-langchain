"""
Who is in the mission: seats, the agents in them, and the nets that join them.

Three names are kept apart:

* the **agent id** names a configuration and one copy of it, in the form
  ``<Type>V<version>.Instance<n>`` (for example ``GeneralistV1.Instance4``).
  It is what an action or a decision is attributed to.
* the **role** is the operating-model role the mission order seats the agent
  in (for example ``loadmaster``).  Authority is granted to roles.
* the **callsign** is how the seat is addressed on a net (``LOADMASTER``).
  Messages are routed by callsign, and the graph has one node per seat.

The mission order defines the seats and nets (see ``order.py``).  This module
holds only the data types and the standard five-seat crew that the domain
model falls back to when it is used without an order, as in unit tests.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

# Role ids.  The first four exist in ENSIM's operating model; ``navigator`` is
# added by this project's local supplement (see operating_model/local.yaml).
AIRCRAFT_COMMANDER = "aircraft-commander"
COPILOT = "copilot"
NAVIGATOR = "navigator"
LOADMASTER = "loadmaster"
AIR_TRAFFIC_CONTROLLER = "air-traffic-controller"

AGENT_ID = re.compile(r"^(?P<type>[A-Z][A-Za-z0-9]*?)V(?P<version>[0-9]+)\.Instance(?P<instance>[0-9]+)$")

NetKind = Literal["interphone", "radio"]


def parse_agent_id(agent_id: str) -> tuple[str, int, int]:
    """``GeneralistV1.Instance4`` -> ("Generalist", 1, 4).  Raises ValueError."""
    match = AGENT_ID.match(str(agent_id))
    if not match:
        raise ValueError(f"agent id {agent_id!r} is not of the form <Type>V<version>.Instance<n>, "
                         "for example GeneralistV1.Instance1")
    return match["type"], int(match["version"]), int(match["instance"])


def make_agent_id(type_name: str, version: int, instance: int) -> str:
    agent_id = f"{type_name}V{int(version)}.Instance{int(instance)}"
    parse_agent_id(agent_id)
    return agent_id


class Seat(BaseModel):
    """One seat in the mission and the agent sitting in it."""
    agent_id: str
    role: str
    callsign: str
    position: str | None = None


class Net(BaseModel):
    """A voice net.  Members are callsigns."""
    id: str
    kind: NetKind
    system: str
    members: list[str]
    control: str | None = None
    frequency: str | None = None


class Roster(BaseModel):
    aircraft_callsign: str = "CONDOR 71"
    seats: list[Seat] = Field(default_factory=list)
    nets: list[Net] = Field(default_factory=list)

    # ------------------------------------------------------------------ lookup

    @property
    def callsigns(self) -> list[str]:
        return [seat.callsign for seat in self.seats]

    def seat(self, key: str | None) -> Seat | None:
        """The seat held by an agent id, or addressed by a callsign."""
        if key is None:
            return None
        for seat in self.seats:
            if seat.agent_id == key:
                return seat
        upper = str(key).upper()
        for seat in self.seats:
            if seat.callsign.upper() == upper:
                return seat
        return None

    def holders(self, role: str) -> list[Seat]:
        return [seat for seat in self.seats if seat.role == role]

    def callsigns_for(self, roles: list[str] | tuple[str, ...]) -> list[str]:
        """Callsigns of every seat holding one of ``roles``, in roster order."""
        wanted = set(roles)
        return [seat.callsign for seat in self.seats if seat.role in wanted]

    # -------------------------------------------------------------------- nets

    def interphone_of(self, callsign: str) -> Net | None:
        for net in self.nets:
            if net.kind == "interphone" and callsign in net.members:
                return net
        return None

    def radio_peers(self, callsign: str) -> list[str]:
        peers: list[str] = []
        for net in self.nets:
            if net.kind == "radio" and callsign in net.members:
                peers.extend(m for m in net.members if m != callsign)
        return list(dict.fromkeys(peers))

    def radio_operators_for(self, callsign: str) -> list[str]:
        """Members of the sender's interphone who share a radio net with ``callsign``."""
        operators = []
        for net in self.nets:
            if net.kind == "radio" and callsign in net.members:
                operators.extend(m for m in net.members if m != callsign and self.interphone_of(m))
        return list(dict.fromkeys(operators))


#: Callsign, role and position of the standard Operation AIRDROP ALPHA crew.
STANDARD_SEATS: list[tuple[str, str, str]] = [
    ("COMMANDER", AIRCRAFT_COMMANDER, "Aircraft commander"),
    ("COPILOT", COPILOT, "Copilot; works the radio"),
    ("NAVIGATOR", NAVIGATOR, "Navigator"),
    ("LOADMASTER", LOADMASTER, "Loadmaster"),
    ("ATC", AIR_TRAFFIC_CONTROLLER, "Alpha Approach controller"),
]


def standard_roster(type_name: str = "Generalist", version: int = 1) -> Roster:
    """The five-seat crew of the original scenario, with every seat of one agent type."""
    seats = [Seat(agent_id=make_agent_id(type_name, version, n), role=role, callsign=callsign, position=pos)
             for n, (callsign, role, pos) in enumerate(STANDARD_SEATS, start=1)]
    nets = [
        Net(id="interphone", kind="interphone", system="aircraft-intercom-system", control="COMMANDER",
            members=["COMMANDER", "COPILOT", "NAVIGATOR", "LOADMASTER"]),
        Net(id="approach", kind="radio", system="tactical-communications-system", frequency="124.35 MHz",
            members=["COPILOT", "ATC"]),
    ]
    return Roster(seats=seats, nets=nets)


__all__ = [
    "AIRCRAFT_COMMANDER", "COPILOT", "NAVIGATOR", "LOADMASTER", "AIR_TRAFFIC_CONTROLLER",
    "Net", "Roster", "Seat", "STANDARD_SEATS", "make_agent_id", "parse_agent_id", "standard_roster",
]
