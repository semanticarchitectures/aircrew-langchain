"""
Mission orders: who flies the mission, how they talk, and what the plan is.

A mission order is the part of a mission the agents may know: the roster
(each agent's id, role, callsign and duty position), the nets, the route, the
drop zone, the cargo and the planned times.  Everything the agents must not
see (hazards, injected faults, the simulator's settings) stays in the
scenario file, which names its order.

The format is defined here and described in ``docs/mission-order.md``.  It is
this project's own format, offered as input to the AKS simulation-interface
decision; ENSIM does not yet emit mission orders.

Validation reports every problem at once.  An order is rejected when:

* a field is missing or malformed, or an agent id is not of the form
  ``<Type>V<version>.Instance<n>``;
* two seats share an agent id or a callsign;
* a role is not in the operating model, or an agent type is unknown or not
  qualified for the role it is seated in;
* a net names a callsign that is not in the roster, a system that is not in
  the operating model, or a member whose role has no link to that system;
* a seat is on no net, or more than one interphone net is given;
* the route, drop zone or cargo do not match the domain data.

Checks that pass only because of the local supplement are not errors; they
are listed under ``representative`` in the validated order, so a run records
which of its structure is not sourced from ENSIM.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .agents.types import AgentTypeError, agent_type
from .domain import data
from .domain.roster import parse_agent_id
from .operating_model import ENSIM_SNAPSHOT, LOCAL_SUPPLEMENT, REPRESENTATIVE, load_operating_model

NET_KINDS = ("interphone", "radio")
TIMELINE_KEYS = ("takeoff", "time_over_target", "landing")


class OrderError(ValueError):
    """A mission order that cannot be flown.  ``problems`` lists every reason."""

    def __init__(self, source: str, problems: list[str]) -> None:
        self.source = source
        self.problems = list(problems)
        lines = "\n".join(f"  - {p}" for p in self.problems)
        super().__init__(f"{source}: mission order rejected ({len(self.problems)} problem"
                         f"{'s' if len(self.problems) != 1 else ''}):\n{lines}")


def default_order_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "scenarios" / "airdrop_alpha.order.yaml"
        if candidate.is_file():
            return candidate
    return Path.cwd() / "scenarios" / "airdrop_alpha.order.yaml"


def _text(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def validate_order(raw: dict, source: str = "<dict>") -> dict:
    """Validate a raw ``{"order": {...}}`` mapping.  Returns the normalised order or raises OrderError."""
    problems: list[str] = []
    representative: list[str] = []
    od = raw.get("order") if isinstance(raw, dict) else None
    if not isinstance(od, dict):
        raise OrderError(source, ["missing top-level 'order' mapping"])

    for key in ("id", "name", "roster", "nets"):
        if key not in od:
            problems.append(f"missing '{key}'")
    layers = tuple(od.get("operating_model") or (ENSIM_SNAPSHOT, LOCAL_SUPPLEMENT))
    try:
        model = load_operating_model(layers)
    except ValueError as exc:
        raise OrderError(source, [str(exc)]) from exc

    aircraft = od.get("aircraft") or {}
    aircraft_callsign = _text(aircraft.get("callsign") or data.AIRCRAFT_CALLSIGN).upper()

    # --- roster ---------------------------------------------------------------
    seats: list[dict] = []
    ids: set[str] = set()
    callsigns: dict[str, str] = {}
    for index, entry in enumerate(od.get("roster") or []):
        where = f"roster[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: expected a mapping")
            continue
        agent_id = _text(entry.get("id"))
        role = _text(entry.get("role"))
        callsign = _text(entry.get("callsign")).upper()
        if not agent_id or not role or not callsign:
            problems.append(f"{where}: needs id, role and callsign")
            continue
        try:
            parse_agent_id(agent_id)
        except ValueError as exc:
            problems.append(f"{where}: {exc}")
            continue
        if agent_id in ids:
            problems.append(f"{where}: duplicate agent id {agent_id}")
        ids.add(agent_id)
        if callsign in callsigns:
            problems.append(f"{where}: callsign {callsign} is already held by {callsigns[callsign]}")
        callsigns[callsign] = agent_id
        found = model.role(role)
        if found is None:
            problems.append(f"{where}: role {role!r} is not in the operating model ({', '.join(model.layers)})")
        elif found.source == REPRESENTATIVE:
            representative.append(f"role {role}: not in {ENSIM_SNAPSHOT}; defined in operating_model/local.yaml. "
                                  f"{found.note}".strip())
        try:
            kind = agent_type(agent_id)
            if role not in kind.qualified_roles:
                problems.append(f"{where}: agent type {kind.key} is not qualified for role {role}")
        except AgentTypeError as exc:
            problems.append(f"{where}: {exc}")
        seats.append({"agent_id": agent_id, "role": role, "callsign": callsign,
                      "position": _text(entry.get("position")) or None})
    if not seats and "roster" in od:
        problems.append("roster is empty")

    # --- nets -----------------------------------------------------------------
    nets: list[dict] = []
    net_ids: set[str] = set()
    on_a_net: set[str] = set()
    role_of = {s["callsign"]: s["role"] for s in seats}
    for index, entry in enumerate(od.get("nets") or []):
        where = f"nets[{index}]"
        net_id = _text(entry.get("id"))
        kind = _text(entry.get("kind")).lower()
        system = _text(entry.get("system"))
        members = [_text(m).upper() for m in entry.get("members") or []]
        if not net_id or kind not in NET_KINDS or not system or not members:
            problems.append(f"{where}: needs id, kind ({' or '.join(NET_KINDS)}), system and members")
            continue
        if net_id in net_ids:
            problems.append(f"{where}: duplicate net id {net_id}")
        net_ids.add(net_id)
        if system not in model.systems:
            problems.append(f"{where}: system {system!r} is not in the operating model")
        for member in members:
            if member not in role_of:
                problems.append(f"{where}: member {member} is not a callsign in the roster")
                continue
            on_a_net.add(member)
            if system in model.systems:
                links = model.links_for(role_of[member], system)
                if not links:
                    problems.append(f"{where}: {member} ({role_of[member]}) has no link to {system} "
                                    "in the operating model")
                elif all(link.source == REPRESENTATIVE for link in links):
                    note = next((link.note for link in links if link.note), "")
                    representative.append(f"{role_of[member]} on {system}: not in {ENSIM_SNAPSHOT}; "
                                          f"linked in operating_model/local.yaml. {note}".strip())
        control = _text(entry.get("control")).upper() or None
        if control and control not in members:
            problems.append(f"{where}: control station {control} is not a member of the net")
        nets.append({"id": net_id, "kind": kind, "system": system, "members": members, "control": control,
                     "frequency": _text(entry.get("frequency")) or None})
    if sum(1 for n in nets if n["kind"] == "interphone") > 1:
        problems.append("more than one interphone net; this version supports one")
    for seat in seats:
        if seat["callsign"] not in on_a_net:
            problems.append(f"{seat['callsign']} is on no net and could not speak or be heard")

    # --- plan -----------------------------------------------------------------
    route = [_text(w).upper() for w in od.get("route") or data.ROUTE]
    if route != data.ROUTE:
        problems.append(f"route {route} does not match the route this simulation models: {data.ROUTE}")
    drop_zone = _text(od.get("drop_zone") or "DZ-ALPHA").upper()
    if drop_zone not in route:
        problems.append(f"drop zone {drop_zone} is not on the route")
    cargo = [_text(b).upper() for b in od.get("cargo") or list(data.MANIFEST)]
    if sorted(cargo) != sorted(data.MANIFEST):
        problems.append(f"cargo {cargo} does not match the manifest: {sorted(data.MANIFEST)}")
    timeline = {}
    for key, value in (od.get("timeline") or {}).items():
        if key not in TIMELINE_KEYS:
            problems.append(f"timeline: unknown entry {key!r}. Known: {', '.join(TIMELINE_KEYS)}")
            continue
        try:
            timeline[key] = float(value)
        except (TypeError, ValueError):
            problems.append(f"timeline.{key}: expected minutes, got {value!r}")

    if problems:
        raise OrderError(source, problems)
    return {
        "id": _text(od["id"]), "name": _text(od["name"]), "source": source,
        "classification": _text(od.get("classification")) or None,
        "aircraft": {"callsign": aircraft_callsign, "type": _text(aircraft.get("type")) or None},
        "operating_model": model.summary(),
        "roster": seats, "nets": nets,
        "route": route, "drop_zone": drop_zone, "cargo": cargo, "timeline": timeline,
        "representative": list(dict.fromkeys(representative)),
    }


def load_order(path: str | Path | None = None) -> dict:
    p = Path(path) if path else default_order_path()
    if not p.is_file():
        raise OrderError(str(p), ["mission order file not found"])
    with open(p, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return validate_order(raw, source=str(p))


def roster_model(order: dict, seats: list[dict] | None = None) -> dict:
    """
    Seats and nets in the shape of :class:`~.domain.roster.Roster`.  ``seats``
    is the run's bound roster (see agents.types.bind_roster); by default the
    seats as ordered.
    """
    chosen = seats if seats is not None else order["roster"]
    return {"aircraft_callsign": order["aircraft"]["callsign"],
            "seats": [{k: s.get(k) for k in ("agent_id", "role", "callsign", "position")} for s in chosen],
            "nets": order["nets"]}


__all__ = ["OrderError", "default_order_path", "load_order", "roster_model", "validate_order"]
