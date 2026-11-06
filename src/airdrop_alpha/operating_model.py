"""
The operating model a mission order is checked against.

Two layers, read from ``operating_model/`` at the repository root:

* a pinned snapshot of ENSIM's records (roles, interactions, systems,
  organizations), copied unchanged by ``scripts/snapshot_ensim.py``;
* ``local.yaml``: roles and communication links this simulation needs that
  ENSIM does not have.  Every local entry is marked representative, so a
  check that passes only because of it says so.

Only what order validation needs is modelled: which roles exist, who a role
reports to, and which communication systems a role is linked to.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

#: The ENSIM commit this project reads.  ENCAP's harness pins the same one.
ENSIM_SNAPSHOT = "ensim@aa7b714"
LOCAL_SUPPLEMENT = "local"
REPRESENTATIVE = "representative"


class OperatingModelError(ValueError):
    """The operating model files are missing or malformed."""


def operating_model_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "operating_model"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "operating_model"


@dataclass(frozen=True)
class Role:
    id: str
    name: str
    reports_to: str | None
    source: str                      # "ensim@aa7b714" or "representative"
    note: str = ""


@dataclass(frozen=True)
class Link:
    """A role is linked to a communication system."""
    role: str
    system: str
    source: str                      # the ENSIM record id, or "representative"
    note: str = ""


@dataclass
class OperatingModel:
    layers: list[str]
    roles: dict[str, Role] = field(default_factory=dict)
    systems: dict[str, dict] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def role(self, role_id: str) -> Role | None:
        return self.roles.get(role_id)

    def links_for(self, role_id: str, system: str) -> list[Link]:
        return [link for link in self.links if link.role == role_id and link.system == system]

    def summary(self) -> dict:
        """What a run records about the model it was checked against."""
        return {"layers": list(self.layers), "provenance": dict(self.provenance)}


def _records(path: Path, key: str) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OperatingModelError(f"cannot read {path}: {exc}") from exc
    return raw if isinstance(raw, list) else list(raw.get(key, []))


def _load_ensim(model: OperatingModel, folder: Path, layer: str) -> None:
    if not folder.is_dir():
        raise OperatingModelError(f"ENSIM snapshot {folder} not found; run scripts/snapshot_ensim.py")
    for record in _records(folder / "roles.json", "roles"):
        model.roles[record["id"]] = Role(id=record["id"], name=record.get("name", record["id"]),
                                         reports_to=record.get("reportsToRoleId"), source=layer)
    for record in _records(folder / "systems.json", "systems"):
        model.systems[record["id"]] = {"name": record.get("name", record["id"]), "type": record.get("type"),
                                       "source": layer}
    for record in _records(folder / "interactions.json", "interactions"):
        ends = [record.get("from") or {}, record.get("to") or {}]
        roles = [end["id"] for end in ends if end.get("kind") == "role"]
        systems = [end["id"] for end in ends if end.get("kind") == "system"]
        via = record.get("viaSystem") or {}
        if via.get("kind") == "system":
            systems.append(via["id"])
        if record.get("interactionType") in ("CommunicatesVia", "Informs", "CoordinatesWith", "Commands") \
                or via:
            for role_id in roles:
                for system in systems:
                    if model.systems.get(system, {}).get("type") == "Communications":
                        model.links.append(Link(role=role_id, system=system, source=f"{layer}:{record['id']}"))
    prov = folder / "provenance.json"
    if prov.is_file():
        model.provenance[layer] = json.loads(prov.read_text(encoding="utf-8"))


def _load_local(model: OperatingModel, path: Path) -> None:
    if not path.is_file():
        raise OperatingModelError(f"local supplement {path} not found")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for record in raw.get("roles") or []:
        if record["id"] in model.roles:
            raise OperatingModelError(f"{path}: role {record['id']!r} already exists in ENSIM; do not redefine it")
        model.roles[record["id"]] = Role(id=record["id"], name=record.get("name", record["id"]),
                                         reports_to=record.get("reports_to"), source=REPRESENTATIVE,
                                         note=" ".join(str(record.get("note", "")).split()))
    for record in raw.get("links") or []:
        model.links.append(Link(role=record["role"], system=record["system"], source=REPRESENTATIVE,
                                note=" ".join(str(record.get("note", "")).split())))
    model.provenance[LOCAL_SUPPLEMENT] = {"file": f"operating_model/{path.name}", "status": REPRESENTATIVE}


@lru_cache(maxsize=8)
def load_operating_model(layers: tuple[str, ...] = (ENSIM_SNAPSHOT, LOCAL_SUPPLEMENT),
                         root: str | None = None) -> OperatingModel:
    base = Path(root) if root else operating_model_dir()
    model = OperatingModel(layers=list(layers))
    for layer in layers:
        if layer.startswith("ensim@"):
            _load_ensim(model, base / layer, layer)
        elif layer == LOCAL_SUPPLEMENT:
            _load_local(model, base / "local.yaml")
        else:
            raise OperatingModelError(f"unknown operating-model layer {layer!r}")
    for link in model.links:
        if link.role not in model.roles:
            raise OperatingModelError(f"link for unknown role {link.role!r}")
        if link.system not in model.systems:
            raise OperatingModelError(f"link to unknown system {link.system!r}")
    return model


__all__ = ["ENSIM_SNAPSHOT", "Link", "OperatingModel", "OperatingModelError", "REPRESENTATIVE", "Role",
           "load_operating_model", "operating_model_dir"]
