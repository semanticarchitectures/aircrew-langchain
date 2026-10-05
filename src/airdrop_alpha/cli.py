"""
Command line for Operation AIRDROP ALPHA on LangGraph.

    airdrop run                          live crew (needs ANTHROPIC_API_KEY)
    airdrop run --crew scripted          offline scripted crew, no API key
    airdrop run --crew rogue             scripted crew with a Loadmaster who jumps the gun
    airdrop run --crew eager             scripted crew with a Commander who drops before the CARP
    airdrop run --interactive            pause whenever the crew goes quiet, to inject events
    airdrop run --dry-run                validate the scenario and print its timeline
    airdrop run --resume RUN_ID          continue a run that stopped
    airdrop history RUN_ID               list the checkpoints of a run
    airdrop fork RUN_ID --at-clock 60 --inject "!cargo_shift bundle=B-03"
    airdrop score RUN_ID                 print the scorecard of a saved run
    airdrop graph                        print the graph as Mermaid
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .domain.world import EFFECTS, ROLES
from .graph.scheduler import parse_inject
from .graph.state import new_run_id
from .observer import Observer, RunRecorder, fan_out
from .runner import fork_state, history, open_checkpointer, run_mission, state_at
from .scenario import ScenarioError, load_scenario, timeline_summary
from .scorecard import render, score

console = Console(highlight=False)

_HELP = f"""\
[bold]Evaluator console[/bold]: the crew is quiet and the clock is stopped.

  [bold]AGENT message[/bold]            inject a message      (agents: {', '.join(ROLES)}, ALL)
  [bold]AGENT:PRIORITY message[/bold]   with ROUTINE, URGENT or EMERGENCY
  [bold]!effect key=value[/bold]        change the world      (effects: {', '.join(EFFECTS)})
  [bold](empty line)[/bold]             continue to the next quiet point
  [bold]until 60[/bold]                 continue without pausing until T+60
  [bold]status[/bold]                   show aircraft and cargo state
  [bold]go[/bold]                       stop pausing and run to the end

Examples
  LOADMASTER:URGENT A strap on B-03 has failed. Inspect the cargo.
  !cargo_shift bundle=B-03 cg_shift_pct=4.9
  !weather location=DZ-ALPHA ceiling_ft_agl=300 visibility_sm=1
  !traffic_conflict active=true
  !engine_failure engine=2
"""


class EvaluatorConsole:
    """Interactive handler for the scheduler's interrupt."""

    def __init__(self) -> None:
        self.free_run = False
        self.skip_until = 0.0
        self.prompts = 0
        self.injects = 0

    async def __call__(self, payload: dict, state: dict) -> dict | None:
        if self.free_run or payload["next_at_min"] < self.skip_until:
            return None
        loop = asyncio.get_running_loop()
        self.prompts += 1
        coming = f"Next on the timeline: {payload['next']}, at T+{payload['next_at_min']:g}."
        console.print(Panel(f"{_HELP}\n{coming}" if self.prompts == 1
                            else f"{coming}  Inject, or press Enter to continue (help for commands).",
                            title=f"[bold magenta]EVALUATOR  T+{payload['clock_min']:g}  "
                                  f"{payload['mission_phase']}[/bold magenta]",
                            border_style="magenta", padding=(0, 1)))
        injects: list[dict] = []
        while True:
            try:
                line = (await loop.run_in_executor(None, input, "[EVALUATOR] > ")).strip()
            except (EOFError, KeyboardInterrupt):
                self.free_run = True
                break
            if not line:
                break
            if line.lower() in ("go", "quit", "q"):
                self.free_run = True
                break
            if line.lower() == "help":
                console.print(_HELP)
                continue
            if line.lower().startswith("until"):
                try:
                    self.skip_until = float(line.split()[1])
                except (IndexError, ValueError):
                    console.print("[red]usage: until <sim minute>, e.g. until 60[/red]")
                    continue
                break
            if line.lower() == "status":
                world = state["world"]
                console.print_json(json.dumps({"aircraft": world["aircraft"], "authority": world["authority"],
                                               "door": world["cargo"]["door"],
                                               "aborted": world["cargo"]["aborted"]}))
                continue
            try:
                injects.append(parse_inject(line))
                console.print(f"[magenta]queued: {line}[/magenta]")
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
        self.injects += len(injects)
        return {"injects": injects} if injects else None


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path.cwd() / ".env")


def _check_live_credentials(crew: str) -> None:
    if crew != "live":
        return
    model = os.environ.get("AIRDROP_MODEL", "anthropic:")
    if model.startswith("anthropic:") and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]A live crew needs ANTHROPIC_API_KEY (in the environment or in .env).[/red]\n"
                      "Use [bold]--crew scripted[/bold] to run offline.")
        raise SystemExit(2)


def _print_timeline(scenario: dict) -> None:
    table = Table(title=f"{scenario['name']}  ({scenario['source']})", show_lines=False)
    for column in ("T+", "kind", "what", "requires"):
        table.add_column(column)
    for row in timeline_summary(scenario):
        table.add_row(f"{row['t']:g}", row["kind"], row["what"], row["requires"])
    console.print(table)
    console.print(f"Planned fuel at landing: {scenario['fuel_curve'][-1][1]:,.0f} lbs. "
                  f"Settings: {scenario['settings']}")


async def _cmd_run(args: argparse.Namespace) -> int:
    overrides = {}
    if args.interactive:
        overrides["interactive"] = True
    if args.party_line:
        overrides["party_line"] = True
    if args.max_turns:
        overrides["max_turns"] = args.max_turns
    scenario = None
    if not args.resume:
        try:
            scenario = load_scenario(args.scenario, **overrides)
        except ScenarioError as exc:
            console.print(f"[red]Scenario error: {exc}[/red]")
            return 2
        if args.dry_run:
            _print_timeline(scenario)
            return 0
    _check_live_credentials(args.crew)

    run_id = args.resume or args.run_id or new_run_id()
    observer = Observer(silent=args.quiet or args.json, verbose=args.verbose, pace=args.pace)
    recorder = None if args.no_logs else RunRecorder(args.logs, run_id)
    result = None
    try:
        async with open_checkpointer(None if args.no_db else args.db) as saver:
            if not (args.quiet or args.json):
                console.print(f"[dim]run {run_id} | crew {args.crew} | checkpoints "
                              f"{'in memory' if args.no_db else args.db}[/dim]")
            result = await run_mission(
                scenario, crew=args.crew, run_id=run_id, checkpointer=saver, resume=bool(args.resume),
                on_update=fan_out(observer.on_update, recorder.on_update if recorder else None),
                on_interrupt=EvaluatorConsole() if (args.interactive or args.resume) and sys.stdin.isatty() else None,
            )
    finally:
        if recorder:
            recorder.close(result.scorecard if result else None)

    if args.json:
        print(json.dumps(result.scorecard, indent=2))
    else:
        console.print()
        console.print(render(result.scorecard))
        if recorder:
            console.print(f"[dim]transcript: {recorder.transcript_path}[/dim]")
        if result.interrupted:
            console.print(f"[yellow]Paused at an evaluator prompt. Continue with: "
                          f"airdrop run --resume {run_id}[/yellow]")
    return 0 if result.state.get("status") == "complete" else 1


async def _cmd_history(args: argparse.Namespace) -> int:
    async with open_checkpointer(args.db) as saver:
        rows = await history(args.run_id, saver)
    if not rows:
        console.print(f"[red]No checkpoints for run {args.run_id!r} in {args.db}[/red]")
        return 1
    table = Table(title=f"run {args.run_id}: {len(rows)} checkpoints")
    for column in ("checkpoint", "step", "T+", "next", "turns", "msgs", "last event", "phase"):
        table.add_column(column, no_wrap=column != "phase")
    for row in rows:
        table.add_row(row["checkpoint_id"], str(row["step"]), f"{row['clock_min']:g}",
                      ",".join(row["next"]) or "(end)", str(row["turns"]), str(row["messages"]),
                      str(row["last_event"]), row["mission_phase"])
    console.print(table)
    return 0


async def _cmd_fork(args: argparse.Namespace) -> int:
    try:
        injects = [parse_inject(line) for line in args.inject or []]
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    _check_live_credentials(args.crew)
    new_id = args.new_run_id or f"{args.run_id}-fork-{new_run_id()[-6:]}"
    observer = Observer(silent=args.quiet, verbose=args.verbose)
    recorder = None if args.no_logs else RunRecorder(args.logs, new_id)
    async with open_checkpointer(args.db) as saver:
        try:
            values = await state_at(args.run_id, saver, checkpoint_id=args.checkpoint, at_clock=args.at_clock)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        start = fork_state(values, new_id=new_id, injects=injects)
        console.print(f"[dim]fork of {args.run_id} at T+{values['world']['clock_min']:g} -> run {new_id} "
                      f"({len(injects)} inject(s), crew {args.crew})[/dim]")
        result = await run_mission(crew=args.crew, run_id=new_id, checkpointer=saver, start_state=start,
                                   on_update=fan_out(observer.on_update,
                                                     recorder.on_update if recorder else None))
    if recorder:
        recorder.close(result.scorecard)
    console.print()
    console.print(render(result.scorecard))
    return 0


async def _cmd_score(args: argparse.Namespace) -> int:
    async with open_checkpointer(args.db) as saver:
        try:
            values = await state_at(args.run_id, saver)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
    card = score(values)
    print(json.dumps(card, indent=2)) if args.json else console.print(render(card))
    return 0


def _cmd_graph(args: argparse.Namespace) -> int:
    from .graph.build import build_graph
    from .runner import make_crew

    graph = build_graph(make_crew(load_scenario(), "scripted"))
    print(graph.get_graph().draw_mermaid())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="airdrop", description="Operation AIRDROP ALPHA on LangGraph")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--db", default="runs/airdrop.sqlite", help="SQLite checkpoint database")
        p.add_argument("--logs", default="logs", help="directory for transcripts and event logs")
        p.add_argument("--no-logs", action="store_true", help="do not write transcript files")
        p.add_argument("--quiet", action="store_true", help="no live rendering, scorecard only")
        p.add_argument("--verbose", action="store_true", help="show every action and silent turn")

    run = sub.add_parser("run", help="run a mission")
    run.add_argument("--scenario", help="scenario YAML (default scenarios/airdrop_alpha.yaml)")
    run.add_argument("--crew", default="live", choices=["live", "scripted", "rogue", "eager"])
    run.add_argument("--interactive", action="store_true", help="pause for evaluator injects when the crew is quiet")
    run.add_argument("--party-line", action="store_true", help="crew overhear interphone traffic not addressed to them")
    run.add_argument("--pace", type=float, default=0.0, help="real seconds to wait per sim minute")
    run.add_argument("--max-turns", type=int, help="override the scenario's agent turn budget")
    run.add_argument("--run-id", help="name for this run (default: timestamp)")
    run.add_argument("--resume", metavar="RUN_ID", help="continue a saved run from its last checkpoint")
    run.add_argument("--dry-run", action="store_true", help="validate the scenario and print its timeline")
    run.add_argument("--no-db", action="store_true", help="keep checkpoints in memory only")
    run.add_argument("--json", action="store_true", help="print only the scorecard as JSON")
    common(run)

    hist = sub.add_parser("history", help="list the checkpoints of a run")
    hist.add_argument("run_id")
    hist.add_argument("--db", default="runs/airdrop.sqlite")

    fork = sub.add_parser("fork", help="branch a saved run, optionally injecting events")
    fork.add_argument("run_id")
    where = fork.add_mutually_exclusive_group()
    where.add_argument("--at-clock", type=float, help="fork from the last checkpoint at or before this sim minute")
    where.add_argument("--checkpoint", help="fork from this checkpoint id (see: airdrop history)")
    fork.add_argument("--inject", action="append", help="evaluator inject line; repeatable")
    fork.add_argument("--crew", default="live", choices=["live", "scripted", "rogue", "eager"])
    fork.add_argument("--new-run-id")
    common(fork)

    sc = sub.add_parser("score", help="print the scorecard of a saved run")
    sc.add_argument("run_id")
    sc.add_argument("--db", default="runs/airdrop.sqlite")
    sc.add_argument("--json", action="store_true")

    sub.add_parser("graph", help="print the graph as Mermaid")
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_env()
    args = build_parser().parse_args(argv)
    if args.command == "graph":
        return _cmd_graph(args)
    handler = {"run": _cmd_run, "history": _cmd_history, "fork": _cmd_fork, "score": _cmd_score}[args.command]
    try:
        return asyncio.run(handler(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. The last checkpoint is saved; use --resume to continue.[/yellow]")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
