# Design decisions and development plan

**Status:** v0.1, 2026-10-04. Proposed. Section 2 records decisions Kevin made in
the design discussion of 2026-10-04. Section 3 records positions Claude proposed
that were not objected to but not explicitly confirmed. Section 6 lists what is
still open. Nothing in Sections 4 and 5 is built yet.

## 1. Where the project stands

The LangGraph rebuild works end to end: a governed envelope (the graph owns the
clock, turn order, timeline gates and authority checks) around five agents that
decide what to say and do. 88 tests pass. Two live runs exist on Claude Sonnet 4.6:

| Run | Result | Turns | Input tokens | Cost |
|---|---|---|---|---|
| live1 | Drop called 4 min early, 0 of 5 delivered (re-scored) | 102 | 1.79M | about $3 (estimate) |
| live2 | Drop on target, 5 of 5 delivered, no findings | 102 | 1.77M (78% cached) | $1.88 to $2.17 |

Three measured facts from live2 drive this plan:

- Every model call carries the full role prompt, tool set and the agent's whole
  mission log. Input per call roughly doubled over the flight (about 5-6k tokens
  early, 8-12k late).
- 37 of 102 turns ended with the agent silent and no action taken. Those turns
  cost 317k input tokens, about 18% of the run.
- A doctrine audit found nothing in either run traceable to published doctrine,
  and both runs contained assertions with no basis in recorded state (live2:
  "clear of Romeo-4" while inside it; "no terrain conflicts" with no terrain data).

## 2. Decisions made

### Mission and context

1. **First mission.** ENSIM Mission 1 (Hickam-Luzon humanitarian airdrop).
2. **What agent context is.** Information about the enterprise, the mission and
   the agent's role, plus role- and mission-specific material that includes the
   results of earlier simulations.
3. **Rehearsals.** Earlier simulation runs act as mission rehearsals. Agents use
   them as validated examples of what is expected, and for awareness of
   situations that can occur. They are a guide, not lines to recite.
4. **Shared examples.** For a team, the same examples are shared by all members.
5. **Context is scoped.** Context is managed by mission, phase and situation, and
   the aim is to optimize it for each. An agent does not hold the whole mission
   in context all the time.
6. **Procedures and sleep.** An agent reads the mission plan, takes part in a
   procedure, and sleeps until its next action in the plan or until conditions
   change. The initial comms check is the reference example: the station running
   the check validates comms with each node on the net and each node acknowledges.

### Identity

7. **Roster from the mission order.** The mission order defines the roster. Every
   agent has a unique id and a role defined there.
8. **The id names a configuration.** Ids persist across runs so that different
   configurations (model version, context management) can be compared across
   simulations.
9. **Id form.** `Type.VersionX.InstanceN`, for example `Loadmaster.v4.01`.
   Role-specific agent types have processing and context optimized for a role,
   and several instances of one version can run in a large simulation. A general
   capability set assigned to a role is also a valid type.

### Authorization

10. **Role-based grants.** Each agent has an identity and a set of authorizations
    granted by its role. Authorizations are meaningful as actions: the loadmaster
    operates the cargo equipment, so holds the grants needed to command it.
11. **Tools are visible to the crew.** Crew agents see the crew's tools; the
    authority checks decide what succeeds.
12. **The commander can reassign grants.** In some circumstances the commander may
    take authorizations from one crew member and give them to another, for
    example from the loadmaster to the copilot.
13. **Two-agent control stays in place.** No reassignment may leave one agent
    holding both the approval and the execution of a two-agent-controlled action
    (today: door opening and bundle release). Read strictly: no emergency
    exception. See open item 6.

### Deferred

14. **Fast pre-filter.** Each agent gets a fast pre-filter that listens to every
    message and event and classifies it for the agent's main model, on the model
    of fast and slow thinking. A classifier model such as Jev is the candidate.
    Discussion deferred; the design leaves a seam for it (Section 4.4).

## 3. Proposed, not yet confirmed

- **Validation is per phase segment, not per run.** A segment becomes an example
  only if the phase ended in the right state, every statement about the world
  matches recorded state, and it is signed off.
- **Instruments outrank examples.** A shared example never overrides a reading.
- **Held-out situations.** At least one situation appears in no example, so runs
  measure judgment and not recall.
- **Mission order and scenario are separate files.** Agents may read the order.
  Hazards and injected faults stay in the scenario, which agents never see.
- **Three checks on every action.** Standing grant, required approval, equipment
  state. A refusal names the check that failed.
- **Four kinds of grant.** Operate (command a system), decide (gate another
  agent's action), communicate (transmit on a net), read (see information).
- **Limits on reassignment.** Only among roles that report to the commander; the
  commander's own decisions and anything held off the aircraft do not transfer;
  the receiving station must have a control for the system; appropriateness is
  scored, not blocked.
- **The procedure card and monitoring duty move with a grant.**
- **A version is a manifest.** Model pin, context policy, card set, filter rules
  and tool set, changed one component at a time where possible.
- **No memory carries across runs on an id.**
- **A generalist baseline type runs in every seat** as the reference to beat.
- **Every grant and card carries a source** or is marked "representative".

## 4. Target design

### 4.1 Mission order

One file per mission, readable by agents: roster (id, role, callsign, duty
position), nets (control station, members), route, cargo, timeline. Validated
before a run against a pinned snapshot of ENSIM's operating model: every role
must exist, every net member's role must have a link to that system, every agent
type must be qualified for its role.

### 4.2 Authorization

Actions belong to systems; roles operate systems; the mission order seats agents
in roles. Grants are mission state: recorded, checkpointed and replayable. The
commander's reassignment action records grantor, grantee, scope, time and
reason, is announced on the interphone automatically, and wakes both agents.

ENSIM supplies four `Operates` relations (including loadmaster to the CDS release
mechanism) and the reports-to chain. Its `authorities` field is empty for 13 of
14 roles and its systems have no command sets, so most grants originate in this
project and are marked accordingly.

### 4.3 Procedures and context

The unit of work is a procedure with a card: who runs it, the sequence, expected
responses, completion condition, source. A turn's context is the agent's standing
layer, the card for the procedure in hand, and a handoff derived by the graph
from recorded state. The full mission log is no longer sent every turn.

### 4.4 Attention step

One step per agent between every message or event and that agent's turn. It
returns ignore, note, routine response, or wake the main model. Version 1 is
rules in code. Every classification is logged so that misses can be counted.
A classifier model can replace the rules later without other changes.

### 4.5 Examples and evaluation

Examples are extracted from scored runs by phase segment, checked, and stored in
a versioned library keyed by mission type, phase and role. The evaluation harness
adds configuration as a dimension, swaps one seat at a time, forks from a
checkpoint just before the phase under test, and repeats each cell.

## 5. Development plan

Each phase ends with a gate that must pass before the next begins. Phases 1 to 4
are built on the existing scenario, because that is where a baseline exists.
Mission 1 follows in Phase 5 (see open item 5).

**Phase 0. Baseline.** Done on 2026-10-05: the Mac copy is up to date
(cache-counter fix, live2 logs) and the project is under version control at
`semanticarchitectures/Aircrew-LangChain`. Remaining: record live2 as the
baseline configuration, `Generalist.v1` in every seat.
*Gate:* all tests pass on the Mac copy; the baseline record exists.

**Phase 1. Mission order and identity.** Mission-order schema and loader. Split
the current scenario into order and scenario. Build the graph from the roster.
Separate id, role and callsign throughout; key authority by role. Store the
roster and version manifests in every run record. Validate orders against the
ENSIM snapshot.
*Gate:* the existing mission runs from an order with unchanged scripted
scorecards; a run with two loadmaster instances works; an invalid order is
rejected with the reason.

**Phase 2. Authorization.** Grant model and the three checks. Action to system
to role. All crew tools visible to all crew agents; current grants shown each
turn. Reassignment action with its limits and the two-agent-control rule. A
loadmaster-incapacitated fault.
*Gate:* out-of-role attempts are refused and counted per agent; a reassignment
survives checkpoint replay; any reassignment that would give one agent both keys
is refused; the scripted incapacitation case completes with the copilot
releasing under the commander's approval.

**Phase 3. Procedures, cards and sleep: the comms check.** Procedure cards,
per-turn context assembly, graph-derived handoff, attention step (rules), wake
rules. Add the comms check to the mission.
*Gate:* each node acknowledges once, in order, with no extra traffic; over
repeated live runs, card-only context is compared with full context on turns,
tokens and extra transmissions; idle turns fall below the baseline's 37 of 102;
the attention log shows no missed required action.

**Phase 4. Validated examples and evaluation.** Segment extraction, claim check
against recorded state, sign-off flag, example library, shared phase cards.
Harness: configuration as a dimension, one-seat swaps, forked trials,
repetitions, per-agent measures, one held-out situation.
*Gate:* the claim check catches the known false calls in live1 and live2; the
drop-run experiment reports a baseline failure rate and a with-card rate over
repeated forked trials.

**Phase 5. ENSIM Mission 1.** Mission order for Mission 1 from the ENSIM record:
C-17, nine roles including those off the aircraft. Upstream steps from ENSIM's
run as the enterprise skeleton. Role cards generated from the operating-model
bundle with source ids and caveat notes carried across. Clock and scheduling
across the tasking chain.
*Gate:* Mission 1 runs end to end scripted, then live; every grant and card has
a source or is marked representative; the doctrine audit is repeated and reports
traced against untraced assertions.

**Later, not scheduled.** Classifier pre-filter in the attention step. Doctrine
retrieval at page level (depends on ENCAP's index, which is not built).
Role-specific agent types tuned and compared against the baseline.

**Model spend.** Scripted runs cost nothing. A full live run is about $2 on
Sonnet 4.6. Phases 3 and 4 need repeated live trials; forked trials cost a
fraction of a full run. Estimate: $40 to $60 through Phase 4. Phase 5 is not
estimated, since it has more agents and a longer timeline.

## 6. Open decisions

1. **Example sign-off.** A person approves each example, or machine checks alone.
   Proposed: a person, since live2 passed the scorecard with false calls in it.
2. **Optimization target.** Mission outcome, fidelity (fewer unsupported claims)
   and token cost pull in different directions. Proposed: fidelity first.
3. **Source of rehearsal content.** ENSIM's Mission 1 run output is the ten
   planned steps marked complete, with no decisions or failures. Proposed:
   scored runs of this simulator supply the examples; ENSIM supplies the
   upstream skeleton.
4. **Citation target for doctrine text.** Verbatim publication pages or ENCAP's
   synthesized bundles. Proposed: verbatim pages, with the bundles as the map.
5. **Order of work.** Proposed above: prove the mechanisms on the existing
   scenario, then move to Mission 1. The alternative is to start on Mission 1,
   which changes mission and mechanisms together and loses the baseline.
6. **Two-agent control in an emergency.** Recorded strictly in decision 13. An
   exception after a declared emergency is not included.
7. **Corpus for the cockpit.** The three publications on hand cover the AOC and
   mobility level. DAFMAN 13-217 and AFMAN 11-231 are not on hand, and the C-17
   flight manual is not public, so cockpit checklists stay representative.
8. **Classifier access.** Jev is in early access behind a waitlist.
