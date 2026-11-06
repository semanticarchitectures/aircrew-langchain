# Mission order format

**Status:** v1, 2026-11-06. This project's own format, offered as input to the
AKS simulation-interface decision (due 2027-01-31). ENSIM does not emit mission
orders yet.

A mission order is the part of a mission the agents may know: who flies it, how
they talk, and the plan. The scenario file names its order and holds everything
the agents must not see: hazards, injected faults and the simulator's settings.

Examples: [`scenarios/airdrop_alpha.order.yaml`](../scenarios/airdrop_alpha.order.yaml)
and [`scenarios/airdrop_alpha_two_loadmasters.order.yaml`](../scenarios/airdrop_alpha_two_loadmasters.order.yaml).
Loader and validator: [`src/airdrop_alpha/order.py`](../src/airdrop_alpha/order.py).

## Fields

```yaml
order:
  id: airdrop-alpha
  name: Operation AIRDROP ALPHA
  classification: UNCLASSIFIED - FICTIONAL DEMONSTRATION
  aircraft: {callsign: CONDOR 71, type: C-130J (representative)}
  operating_model: [ensim@aa7b714, local]
  roster:
    - {id: GeneralistV1.Instance1, role: aircraft-commander, callsign: COMMANDER, position: Aircraft commander}
    ...
  nets:
    - {id: interphone, kind: interphone, system: aircraft-intercom-system, control: COMMANDER,
       members: [COMMANDER, COPILOT, NAVIGATOR, LOADMASTER]}
    - {id: approach, kind: radio, system: tactical-communications-system, frequency: 124.35 MHz,
       members: [COPILOT, ATC]}
  route: [KIRO, WPT ALPHA, WPT BRAVO, DZ-ALPHA, WPT CHARLIE, KIRO]
  drop_zone: DZ-ALPHA
  cargo: [B-01, B-02, B-03, B-04, B-05]
  timeline: {takeoff: 12, time_over_target: 64, landing: 110}
```

| Field | Meaning |
|---|---|
| `roster[].id` | The agent in the seat: `<Type>V<version>.Instance<n>`. Type and version name a fixed configuration (see `agents/types.py`); the instance tells copies apart. Unique in the order. |
| `roster[].role` | An operating-model role id. Authority is granted to roles. |
| `roster[].callsign` | How the seat is addressed on a net. Unique in the order. Messages are routed by callsign, and the graph has one node per seat. |
| `roster[].position` | Duty position, free text. Recorded; not yet used to route calls. |
| `nets[]` | Voice nets. `kind` is `interphone` (aboard the aircraft; at most one) or `radio` (to an outside station). `system` is an operating-model communication system. `members` are callsigns; `control` is the net control station. |
| `operating_model` | The layers the order is checked against, in order. Default: the pinned ENSIM snapshot, then the local supplement. |
| `route`, `drop_zone`, `cargo` | Must match what the simulation models (`domain/data.py`). |
| `timeline` | Planned minutes from mission start: `takeoff`, `time_over_target`, `landing`. Must match the scenario's flight profile and drop window. |

## Who may talk to whom

The comms policy reads the nets. `ALL` means every other member of the sender's
interphone. A station with no interphone (ATC) can address only the stations on
its radio nets. A crew member can address an outside station only if they share
a radio net; otherwise the transmission is refused and the reason names who is
on the radio. With the standard order this is exactly the original policy.

## Validation

An order is rejected, with every problem listed at once, when:

- a field is missing or malformed, or an id is not of the agent-id form;
- two seats share an id or a callsign;
- a role is not in the operating model, or an agent type is unknown or not
  qualified for the role it is seated in;
- a net names a callsign not in the roster or a system not in the operating
  model, or a member's role has no link to the net's system;
- a seat is on no net, or there is more than one interphone net;
- the route, drop zone or cargo do not match the domain data.

A scenario is rejected when it disagrees with its order: a callsign it addresses
is not in the roster, the aircraft callsign or planned times differ, or a
timeline gate depends on a role no seat holds (a takeoff clearance needs both a
copilot and ATC).

## Operating model

`operating_model/ensim@aa7b714/` is a byte-for-byte copy of ENSIM's roles,
interactions, systems and organizations at commit `aa7b714`, with ENSIM's
LICENSE and NOTICE and a provenance record of file hashes. A test checks the
hashes. `scripts/snapshot_ensim.py` makes a new snapshot from an ENSIM checkout.

A role is linked to a communication system when an ENSIM interaction connects
them: `CommunicatesVia`, or any interaction whose `viaSystem` is that system.

`operating_model/local.yaml` adds what this simulation needs and ENSIM lacks.
It may add, never redefine. Every entry is representative, and a check that
passes only because of one is listed under `representative` in the validated
order, in `airdrop run --dry-run`, and in every scorecard. For the standard
order that is the navigator role and three links: copilot on the intercom,
copilot on the radio, navigator on the intercom.

## Runs

The run's roster is the order's seats bound to the agents that fly them
(`agents.types.bind_roster`). A scripted crew replaces the type in every seat
and keeps the instance numbers (`GeneralistV1.Instance4` becomes
`ScriptedNominalV1.Instance4`, recorded as `ordered_as`); a model set on the
command line or in the environment is recorded as an override. The bound
roster, with each configuration's manifest, is checkpointed with the run and
written to the scorecard.
