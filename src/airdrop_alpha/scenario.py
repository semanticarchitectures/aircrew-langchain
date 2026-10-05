"""
Scenario loading: YAML -> one validated, JSON-serialisable dict.

The loaded scenario is stored in graph state, so a checkpoint is
self-contained: a run can be resumed, replayed or forked without the file.

All timed things (mission phases, flight-profile segments, waypoint passages,
injected events, the end of the run) are normalised into one ``timeline`` list
that the scheduler walks in order.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .domain import performance as perf
from .domain.comms import PRIORITIES
from .domain.world import CONDITIONS, EFFECTS, ROLES, canonical_checklist, nominal_fuel_curve
from .domain import data

DEFAULT_SETTINGS: dict[str, Any] = {
    "hold_step_min": 2.0,
    "max_holds": 5,
    "max_turns": 400,
    "max_turns_per_burst": 40,
    "max_model_calls_per_turn": 20,
    "party_line": False,
    "memory_max_entries": 60,
    "interactive": False,
}

# Order of items that share a time.
_ORDER = {"mission_phase": 0, "flight": 1, "waypoint": 2, "event": 3, "end": 9}


class ScenarioError(ValueError):
    """The scenario file is malformed."""


def default_scenario_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "scenarios" / "airdrop_alpha.yaml"
        if candidate.is_file():
            return candidate
    return Path.cwd() / "scenarios" / "airdrop_alpha.yaml"


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if "extends" in raw:
        base = _read((path.parent / raw["extends"]).resolve())
        overlay = raw.get("scenario", {})
        merged = dict(base["scenario"])
        merged["settings"] = {**base["scenario"].get("settings", {}), **overlay.get("settings", {})}
        merged["extra_events"] = list(base["scenario"].get("extra_events", [])) + list(overlay.get("extra_events", []))
        for key, value in overlay.items():
            if key not in ("settings", "extra_events"):
                merged[key] = value
        return {"scenario": merged}
    return raw


def _check_requires(requires: list[str], where: str) -> list[str]:
    out = []
    for cond in requires or []:
        if cond.startswith("checklist:"):
            name = canonical_checklist(cond.split(":", 1)[1])
            if name not in data.CHECKLISTS:
                raise ScenarioError(f"{where}: unknown checklist in {cond!r}")
            out.append(f"checklist:{name}")
        elif cond in CONDITIONS:
            out.append(cond)
        else:
            raise ScenarioError(f"{where}: unknown condition {cond!r}. Known: {sorted(CONDITIONS)}")
    return out


def _recipients(value: Any, where: str) -> list[str]:
    names = [value] if isinstance(value, str) else list(value or [])
    out: list[str] = []
    for name in names:
        key = str(name).strip().upper()
        if key == "ALL":
            out.extend(ROLES)
        elif key in ROLES:
            out.append(key)
        else:
            raise ScenarioError(f"{where}: unknown callsign {name!r}")
    return list(dict.fromkeys(out))


def _event_item(raw: dict, phase_id: str, phase_name: str, index: int, start_agent: str) -> dict:
    where = f"event {phase_id}[{index}]"
    effects = []
    for eff in raw.get("effects", []) or []:
        eff = dict(eff)
        name = eff.pop("name", None)
        if name not in EFFECTS:
            raise ScenarioError(f"{where}: unknown effect {name!r}. Known: {sorted(EFFECTS)}")
        effects.append({"name": name, "args": eff})
    priority = str(raw.get("priority", "ROUTINE")).upper()
    if priority not in PRIORITIES:
        raise ScenarioError(f"{where}: unknown priority {priority!r}")
    message = " ".join(str(raw.get("message", "")).split())
    if not message and not effects:
        raise ScenarioError(f"{where}: needs a message or an effect")
    return {
        "id": f"event:{phase_id}:{float(raw.get('at_time', 0)):g}:{index}",
        "kind": "event", "at": float(raw.get("at_time", 0)),
        "phase_id": phase_id, "phase_name": phase_name,
        "inject_to": _recipients(raw.get("inject_to", start_agent), where) if message else [],
        "message": message, "priority": priority, "effects": effects,
        "requires": _check_requires(raw.get("requires", []), where),
        "label": (f"scenario event for {raw.get('inject_to', start_agent)}" if message
                  else "scenario effect"),
    }


def build_scenario(raw: dict, source: str = "<dict>") -> dict:
    """Validate a raw scenario mapping and normalise it."""
    sc = raw.get("scenario")
    if not isinstance(sc, dict):
        raise ScenarioError(f"{source}: missing top-level 'scenario' mapping")
    settings = {**DEFAULT_SETTINGS, **(sc.get("settings") or {})}
    unknown = set(settings) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ScenarioError(f"{source}: unknown settings {sorted(unknown)}")
    start_agent = str(sc.get("start_agent", "COMMANDER")).upper()
    if start_agent not in ROLES:
        raise ScenarioError(f"{source}: unknown start_agent {start_agent!r}")

    timeline: list[dict] = []

    profile = sorted(sc.get("flight_profile") or [], key=lambda s: float(s["at"]))
    if not profile or profile[0]["flight_phase"] != "ground":
        raise ScenarioError(f"{source}: flight_profile must start on the ground")
    for index, seg in enumerate(profile):
        phase = seg["flight_phase"]
        if phase not in perf.FLIGHT_PHASES:
            raise ScenarioError(f"{source}: unknown flight_phase {phase!r}")
        if index == 0:
            continue  # the starting state, not a transition
        where = f"flight_profile[{index}]"
        timeline.append({
            "id": f"flight:{index}:{phase}", "kind": "flight", "at": float(seg["at"]),
            "flight_phase": phase, "heading": seg.get("heading"),
            "requires": _check_requires(seg.get("requires", []), where),
            "notify": _recipients(seg.get("notify", []), where),
            "message": " ".join(str(seg.get("message", "")).split()),
            "label": f"aircraft enters {phase.replace('_', ' ')}",
        })

    waypoint_times: dict[str, float] = {}
    for wp in sc.get("waypoints") or []:
        name = str(wp["name"]).upper()
        waypoint_times[name] = float(wp["at"])
        timeline.append({
            "id": f"waypoint:{name}", "kind": "waypoint", "at": float(wp["at"]), "name": name,
            "silent": bool(wp.get("silent", False)), "requires": [],
            "label": f"passing {name}",
        })

    phases = []
    events_by_phase: dict[str, list[dict]] = {}
    for phase in sc.get("phases") or []:
        pid = str(phase.get("id") or phase.get("name"))
        pname = str(phase.get("name", pid))
        events = sorted(phase.get("events") or [], key=lambda e: float(e.get("at_time", 0)))
        at = float(phase["at"]) if "at" in phase else (float(events[0]["at_time"]) if events else 0.0)
        phases.append({"id": pid, "name": pname, "at": at})
        timeline.append({"id": f"mission_phase:{pid}", "kind": "mission_phase", "at": at,
                         "phase_id": pid, "phase_name": pname, "requires": [],
                         "label": pname})
        events_by_phase[pid] = list(events)
    for extra in sc.get("extra_events") or []:
        extra = dict(extra)
        pid = str(extra.pop("phase", phases[-1]["id"] if phases else "extra"))
        if pid not in events_by_phase:
            raise ScenarioError(f"{source}: extra_events refers to unknown phase {pid!r}")
        events_by_phase[pid].append(extra)
    names = {p["id"]: p["name"] for p in phases}
    for pid, events in events_by_phase.items():
        for index, ev in enumerate(events):
            timeline.append(_event_item(ev, pid, names[pid], index, start_agent))

    trigger = " ".join(str(sc.get("initial_trigger", "")).split())
    if trigger:
        timeline.append({
            "id": "event:initial_trigger", "kind": "event", "at": 0.0,
            "phase_id": phases[0]["id"] if phases else "start",
            "phase_name": phases[0]["name"] if phases else "Start",
            "inject_to": [start_agent], "message": trigger, "priority": "ROUTINE",
            "effects": [], "requires": [], "label": "initial trigger",
        })

    last = max((item["at"] for item in timeline), default=0.0)
    end_at = float(sc.get("end_at", last + 2))
    if end_at < last:
        raise ScenarioError(f"{source}: end_at {end_at:g} is before the last timeline item at {last:g}")
    timeline.append({"id": "end", "kind": "end", "at": end_at, "requires": [], "label": "end of scenario"})

    ids = [item["id"] for item in timeline]
    if len(ids) != len(set(ids)):
        raise ScenarioError(f"{source}: duplicate timeline ids")
    for position, item in enumerate(timeline):
        item["order"] = _ORDER[item["kind"]]
        item["position"] = position
    timeline.sort(key=lambda i: (i["at"], i["order"], i["position"]))

    departure_fuel = float(sc.get("departure_fuel_lbs", data.DEPARTURE_FUEL_LBS))
    hazards = []
    for hz in sc.get("hazards") or []:
        if hz.get("type") != "turbulence":
            raise ScenarioError(f"{source}: unknown hazard type {hz.get('type')!r}")
        hazards.append({"type": "turbulence", "near": hz.get("near"), "from": float(hz["from"]),
                        "to": float(hz["to"]), "band_fl": [float(hz["band_fl"][0]), float(hz["band_fl"][1])]})

    window = sc.get("drop_window")
    if window is not None:
        drop_window = [float(window["opens"]), float(window["closes"])]
    elif "DZ-ALPHA" in waypoint_times:
        drop_window = [waypoint_times["DZ-ALPHA"], waypoint_times["DZ-ALPHA"] + 1.0]
    else:
        drop_window = []
    if drop_window and not drop_window[0] < drop_window[1] <= end_at:
        raise ScenarioError(f"{source}: drop_window must open before it closes, inside the scenario")

    return {
        "name": str(sc.get("name", "unnamed")),
        "description": " ".join(str(sc.get("description", "")).split()),
        "aircraft_callsign": str(sc.get("aircraft_callsign", data.AIRCRAFT_CALLSIGN)),
        "source": source,
        "start_agent": start_agent,
        "settings": settings,
        "phases": phases,
        "timeline": timeline,
        "flight_profile": [{"at": float(s["at"]), "flight_phase": s["flight_phase"]} for s in profile],
        "waypoint_times": waypoint_times,
        "hazards": hazards,
        "drop_window": drop_window,
        "departure_fuel_lbs": departure_fuel,
        "fuel_curve": nominal_fuel_curve(profile, departure_fuel, end_at),
        "end_at": end_at,
    }


def load_scenario(path: str | Path | None = None, **setting_overrides: Any) -> dict:
    """Load and validate a scenario file.  Keyword arguments override settings."""
    p = Path(path) if path else default_scenario_path()
    if not p.is_file():
        raise ScenarioError(f"scenario file not found: {p}")
    raw = _read(p.resolve())
    if setting_overrides:
        raw["scenario"]["settings"] = {**(raw["scenario"].get("settings") or {}), **setting_overrides}
    return build_scenario(raw, source=str(p))


def timeline_summary(scenario: dict) -> list[dict]:
    """Human-readable rows for ``airdrop run --dry-run``."""
    rows = []
    for item in scenario["timeline"]:
        if item["kind"] == "event":
            what = (f"inject -> {', '.join(item['inject_to']) or '(effects only)'}: {item['message'][:70]}"
                    + ("..." if len(item["message"]) > 70 else ""))
            if item["effects"]:
                what += f"  [effects: {', '.join(e['name'] for e in item['effects'])}]"
        elif item["kind"] == "flight":
            what = f"flight phase -> {item['flight_phase']}"
        elif item["kind"] == "waypoint":
            what = f"passing {item['name']}"
        elif item["kind"] == "mission_phase":
            what = f"== {item['phase_name']} =="
        else:
            what = "end of scenario"
        rows.append({"t": item["at"], "kind": item["kind"], "what": what,
                     "requires": ", ".join(item.get("requires", []))})
    return rows
