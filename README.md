# Aircrew-LangChain

A multi-agent aircrew mission simulation on LangChain and LangGraph. The first mission is Operation AIRDROP ALPHA: a five-agent C-130 airdrop.

The domain is the one in [`semanticarchitectures/airdrop-alpha`](https://github.com/semanticarchitectures/airdrop-alpha): the same crew (Commander, Co-Pilot, Navigator, Loadmaster) plus ATC, the same mission, SOP documents and cargo. What changed is everything around the agents: where state lives, who decides whose turn it is, how messages are sent, and how authority is enforced.

The design rule is **structure the envelope, not the conversation**. The graph owns state, time, turn order and authority. The agents still decide what to say and do, in natural language.

The Python package is `airdrop_alpha` and the command is `airdrop`, after the first mission.

## Part of the Acquisition Knowledge System

Aircrew-LangChain is a component of the [Acquisition Knowledge System (AKS)](https://github.com/semanticarchitectures/acquisition-knowledge-system),
a demonstration of AI architecting and simulating Air Force enterprise operations, at scale and
realistically, and then being used in that enterprise, safely and under human authority.

Its role in AKS: LangGraph agents operating in the simulated enterprise under
role-based authority, and the first place AKS captures agent decisions as traces. It carries AKS
milestones D1 (mission order and authorization) and D2 (ENSIM Mission 1). Cross-component specs, the shared ontology and decisions live in the
umbrella repo.

## Status

| | |
|---|---|
| Built | The governed envelope, five agents, scripted and live crews, checkpoints with resume and fork, a deterministic scorecard, 88 offline tests. |
| Flown | Two live runs on Claude Sonnet 4.6 (see [Not verified, not modelled](#not-verified-not-modelled)). |
| Planned | A mission order that defines the roster, role-based authorization that the commander can reassign, context scoped to procedures, validated examples from earlier runs, and ENSIM Mission 1. See [`docs/PLAN.md`](docs/PLAN.md). |

Everything in `knowledge/` is fictional demonstration material. Nothing in the simulation is yet traceable to published Air Force or Joint doctrine; `docs/PLAN.md` describes how that is meant to change.

## Quick start

```bash
git clone https://github.com/semanticarchitectures/Aircrew-LangChain
cd Aircrew-LangChain
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

airdrop run --crew scripted          # full mission, offline, no API key
pytest                               # 88 tests, about 25 seconds, offline
```

For a live crew, copy `.env.example` to `.env`, set `ANTHROPIC_API_KEY`, then:

```bash
airdrop run                          # live crew
airdrop run --interactive            # pause when the crew goes quiet, to inject events
```

Python 3.11 or later.

## How it is put together

```
START -> scheduler -> { COMMANDER | COPILOT | NAVIGATOR | LOADMASTER | ATC } -> scheduler -> ... -> END
```

| Layer | Where | What it does |
|---|---|---|
| World | `domain/world.py` | One serialisable state object (aircraft, cargo, authority, ATC, nav, checklists) and every operation on it. No framework imports. Every state-changing operation checks the acting callsign and its own preconditions. |
| Comms | `domain/comms.py` | Message shape and the policy for who may address whom. |
| Tools | `tools/toolsets.py` | LangChain `@tool` adapters from a tool call to a world operation, grouped by role. They reach the world through `ToolRuntime.context`. |
| Agents | `agents/factory.py`, `agents/prompts/` | One `create_agent` per role: prompt, role toolset, model. |
| Graph | `graph/` | The LangGraph `StateGraph`. `scheduler` owns the clock and the turn order. Each crew node runs one agent turn as a transaction. |
| Scenario | `scenarios/*.yaml`, `scenario.py` | The timeline: flight profile, waypoints, injected events, and the conditions each one waits for. |
| Scorecard | `scorecard.py` | A deterministic read-out of a run, computed from checkpointed state. |

### The scheduler

Each time control returns to the scheduler it does one of four things:

1. gives the next waiting agent a turn. The agent holding the highest-priority traffic goes first; ties go to whoever has waited longest;
2. pauses for the evaluator (interactive mode only), when the crew has gone quiet and the clock is about to move;
3. advances the clock to the next timeline item and fires it, or, if its `requires` conditions are not met, holds the timeline and tells the crew members who can fix it;
4. ends the run.

Time passes only in step 3. A crew that has not obtained takeoff clearance does not take off: the aircraft waits, burns fuel, every later item slips, and after `max_holds` the run ends as `stalled`.

### A crew turn

A turn loads the world from graph state, lets the agent act on a private copy through its tools, and commits world, messages and audit events together when the agent finishes. If a model call fails mid-turn nothing is committed, and the checkpoint before the turn is still good.

What an agent remembers is its own mission log: for each earlier turn, what it heard, what it did, what it said. Raw tool output from earlier turns is not replayed into the prompt.

### Messages

`send_message` is the only way to speak. Text an agent writes outside a tool call is a private note. Two channels:

- **Interphone**: the four crew members. `ALL` means the crew except the sender.
- **Radio**: Co-Pilot and ATC only. Anyone else addressing ATC is refused and told to go through the Co-Pilot.

Formal calls are coupled to the act they announce. `authorize_airdrop` both sets the authorization and transmits "LOADMASTER, COMMANDER. Execute airdrop." `issue_clearance` both records the clearance and transmits it. The same goes for GO/NO-GO, door authorization, abort and emergency.

### Authority

Enforced in `World`, not in prompts. `execute_airdrop` succeeds only when all of these hold: the caller is the Loadmaster, the Commander has given the drop command, the door is open, a ROMEO-4 clearance is on record, the aircraft is on the drop run at 120-165 KIAS, the bundle's restraint is intact, CG stays within limits, and no abort is in effect. A refused action returns `denied: true` with the rule, changes nothing, and is counted in the scorecard.

Checklists are verified against the world. `PREFLIGHT` reports the flight plan item open until a plan is filed and approved.

### Drop accuracy

Authority is refused; physics is scored. A bundle leaves the aircraft wherever it is when `execute_airdrop` succeeds, and the scenario's `drop_window` says when that is over the release point (T+64 to T+65, at the CARP). A release outside the window is not refused, because an early or late drop is physically possible and is a crew error worth observing. The bundle is marked off target, the tool result says where it went, and the scorecard does not count it as delivered: five early bundles score `MISSED DROP ZONE`, not `COMPLETE`.

On the drop run, `get_aircraft_state` and `report_cargo_status` show the distance to the CARP, so the information is there for a crew that looks.

## Commands

```bash
airdrop run [--crew live|scripted|rogue|eager] [--scenario FILE] [--interactive] [--party-line]
            [--pace SECONDS] [--run-id NAME] [--resume RUN_ID] [--dry-run] [--json]
airdrop history RUN_ID                 # every checkpoint of a run
airdrop fork RUN_ID --at-clock 60 --inject "!cargo_shift bundle=B-03 cg_shift_pct=4.9" \
                    --inject "LOADMASTER:URGENT You hear a loud bang from the cargo bay."
airdrop score RUN_ID [--json]
airdrop graph                          # Mermaid diagram of the graph
```

Runs are checkpointed to `runs/airdrop.sqlite` after every agent turn and every clock advance. Both `runs/` and `logs/` are local output and are not kept in the repository. Transcripts go to `logs/`:

- `messages_<run>.jsonl` keeps the original field names (`seq`, `from`, `to`, `priority`, `speaker`, `skip_tts`, `body`) and adds `sim_time_min`, `channel`, `kind`.
- `transcript_<run>.txt`, `events_<run>.jsonl`, `scorecard_<run>.json`.

### Crews

| `--crew` | What plays the roles |
|---|---|
| `live` | Chat models. `AIRDROP_MODEL` sets the model for every role; `AIRDROP_MODEL_<ROLE>` overrides one. The default is `anthropic:claude-sonnet-4-6`, the model the original used, so runs are comparable. Any `init_chat_model` string works. |
| `scripted` | A deterministic playbook (`agents/playbooks.py`). Flies the nominal mission and handles the cargo-shift abort. |
| `rogue` | The scripted crew with a Loadmaster who tries the door and a release before being authorized. |
| `eager` | The scripted crew with a Commander who calls the drop as soon as the door is open, four minutes before the CARP. |

The scripted crews are test fixtures. They exist so the graph, guards, scheduler, checkpoints and scorecard can be exercised end to end without a model.

### Evaluator injects

In `--interactive` mode, and with `airdrop fork --inject`:

```
AGENT[:PRIORITY] message          COMMANDER Weather at the DZ is deteriorating.
!effect key=value ...             !cargo_shift bundle=B-03 cg_shift_pct=4.9
                                  !weather location=DZ-ALPHA ceiling_ft_agl=300 visibility_sm=1
                                  !traffic_conflict active=true
                                  !engine_failure engine=2
                                  !door_jam   !seal_failure bundle=B-05   !fuel_leak lbs=3000
```

A message tells an agent something. An effect changes the world, so the instruments and the guards reflect it.

## Scenario files

`scenarios/airdrop_alpha.yaml` is commented. The parts:

- `flight_profile`: what the aircraft does and when, with `requires` conditions.
- `waypoints`: passages announced to the Navigator.
- `hazards`: the turbulence band near BRAVO. Staying at FL180 accrues exposure; FL140 does not.
- `drop_window`: when a release lands on the DZ. It slips with the timeline.
- `phases[].events`: injected messages, optionally with `requires` and `effects`.
- `settings`: hold length, hold limit, turn budgets, party line, memory size.

`airdrop_alpha_abort.yaml` shows `extends` plus `extra_events`. `airdrop run --dry-run` prints the resolved timeline. Conditions usable in `requires` are in `CONDITIONS` in `domain/world.py`, plus `checklist:<NAME>`.

## What changed from the original

| Original | Here |
|---|---|
| A message handler calls the next agent's handler recursively. No turn order. Chains deeper than 25 are dropped silently. | The scheduler assigns turns. A burst limit forces the clock on and records it; nothing is dropped. |
| Messages parsed from `FROM:/TO:/PRIORITY:` text. Unparseable text goes to COMMANDER. `ALL` echoes back to the sender. | `send_message` tool with a routing policy. Untagged text goes nowhere, and the scorecard flags turns that end with unsent speech. |
| Authority only in prompts. `execute_airdrop` checks neither authorization nor the door. | Guards in the world model, by role and by precondition. |
| State in module globals across `tools/`. Two fuel states. | One `World`, serialised into graph state. |
| `contact_atc`, `brief_crew`, `relay_atc_message`, `request_clearance` return canned text. | Removed. They are messages. |
| Scenario events fire on wall-clock time. | Events fire on sim time, in order, and wait for their conditions. |
| The abort scenario is narrative only: the tools still report a healthy CG. | Scenario events can carry effects that change the world. |
| No persistence. | A checkpoint per step: resume, replay, fork. |

Removed tools and why: `advance_flight_phase` (the scheduler owns flight phase), `sync_cargo_weight` (single state), `simulate_engine_failure` (now an effect, with `get_engine_out_performance` to read the result). Added: `close_door` and `inspect_cargo` (the SOP calls for both), `secure_cargo`, `clear_abort`, `set_transponder`, `set_cruise_altitude`, `get_fuel_plan`, `authorize_door_open`, `authorize_airdrop`, `revoke_authorizations`, `abort_mission`, `cancel_clearance`, `check_sector_traffic`.

## What was reconciled

The original's numbers disagreed with each other. A single world model needs one answer, so:

- **Fuel.** The flight model started at 62,000 lbs and the commander's fuel tool at a fixed 45,000. Now 45,000 lbs per the mission brief, one source.
- **Fuel burn.** The flight model's rates burn about 19,000 lbs over the mission; the brief plans 16,500. One calibration factor (`FUEL_CALIBRATION` in `domain/performance.py`) makes the nominal profile burn 16,500 and land with 28,500. A test checks it.
- **Weights.** The flight model used a real C-130J operating weight; the manifest says 108,000 lbs empty plus 2,400 lbs crew. The manifest wins, so departure weight is 159,600 lbs as documented.
- **Stall speed.** At drop weight the original reported 130 KIAS as outside the safe envelope. The reference is adjusted so the documented drop speed is inside it.
- **Legs and times.** Three different leg tables existed. The Navigator's (85/110/45/90/100 NM, 18/24/10/20/22 min) is used, and scenario times are re-based on it: takeoff T+12, ALPHA T+30, BRAVO T+54, DZ T+64, CHARLIE T+88, KIRO T+110. The Navigator's prompt gets its leg and fuel table from the same data.
- **Order of pre-departure steps.** The Preflight checklist needs the flight plan, squawk and GO decision, so the commander's workflow now files and gets the IFR clearance before running it.

## LangSmith and Studio

**Tracing is off by default.** LangSmith is a hosted service; turning tracing on sends prompts, tool calls and model output to it. To turn it on, set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in `.env`. Each agent turn is traced as `<CALLSIGN> turn <n>` with the callsign, sim time and run id as metadata. A test asserts that a scripted run opens no network connection.

`evals/langsmith_eval.py` scores scenario variants. Without `--upload` it does not call LangSmith at all. With `--upload` it runs them as a LangSmith experiment.

`langgraph.json` exposes the graph to LangGraph Studio:

```bash
pip install -e ".[studio]"
AIRDROP_CREW=scripted langgraph dev      # start a run with an empty input: {}
```

## Tests

```bash
pytest
```

| File | Covers |
|---|---|
| `test_domain.py` | One fuel state, every guard, role authority for all 26 actions, checklists against the world, effects, drop accuracy, serialisation. |
| `test_comms.py` | The routing policy. |
| `test_scenario.py` | Loading, validation, and that the plan matches the mission brief. |
| `test_scheduler.py` | Turn order, gates, holds, slip, stall, budgets, injects. |
| `test_agents.py` | Tool scoping, the scripted model, what a turn commits, denied actions and transmissions. |
| `test_mission.py` | Full missions (nominal, abort, rogue, eager), determinism, checkpoints, fork, interactive pause and resume, re-scoring older runs, the CLI, no network in scripted runs. |
| `test_live_path.py` | The real `ChatAnthropic` client against a local stand-in for the API: tool schemas, system prompt, cache markers, tool-result round trip, token counts. |

## Not verified, not modelled

- **Two live runs have been made**, both on 3 October 2026 with Sonnet 4.6. The prompts have had those two runs only, so expect to tune them.
  - `live1`: 102 agent turns, 230 model calls, 1.79M input and 20k output tokens, about 8 minutes. The crew met every gate with no holds and landed on plan, but the Commander called the drop at T+60, four minutes before the CARP, and the debrief claimed the bundles were on target. At the time nothing scored release position, so the run was reported as complete; re-scored, it is `MISSED DROP ZONE`.
  - `live2`, flown after drop accuracy was scored: 102 agent turns, 228 model calls, 1.77M input tokens (78% read from cache) and 20k output tokens. The drop was called at T+64, on target; the scorecard reads `COMPLETE`, five of five delivered, no findings. One run each cannot show that the change caused the improvement.
  - A clean scorecard is not a clean run. In `live2` the crew reported "clear of Romeo-4" while still inside it, and "no terrain conflicts" with no terrain data. Nothing yet checks what the crew says against recorded state.
- **`evals/langsmith_eval.py --upload` has not been run** against LangSmith. The local mode has.
- Diverting to KRDW or DELTA FIELD is not modelled. `abort_mission` revokes the drop authorizations; the aircraft still flies the planned recovery.
- Altitude changes affect fuel flow and turbulence exposure, not timing.
- One agent acts at a time. That is deliberate (deterministic order, one checkpoint per turn) but it means no two crew members act in parallel.
- A live run makes one model turn for every message an agent receives, including ones it answers with silence. In the scripted mission 32 of 84 turns are silent; in `live2`, 37 of 102.
