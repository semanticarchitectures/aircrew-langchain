"""
Terminal observer and run recorder.

Both consume the graph's update stream: each step yields the new messages and
audit events that step produced.  Nothing here touches the simulation.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from .domain.comms import NON_AGENT_SENDERS

_PRIORITY_STYLE = {"ROUTINE": "cyan", "URGENT": "yellow", "EMERGENCY": "bold red"}
_PRIORITY_BORDER = {"ROUTINE": "cyan", "URGENT": "yellow", "EMERGENCY": "red"}

#: World actions worth a line in the terminal.
_SHOWN_ACTIONS = {
    "make_go_nogo", "authorize_door_open", "authorize_airdrop", "revoke_authorizations",
    "declare_emergency", "abort_mission", "file_flight_plan", "set_transponder", "execute_checklist",
    "set_cruise_altitude", "calculate_carp", "open_door", "close_door", "bundle_released",
    "abort_airdrop", "clear_abort", "secure_cargo", "approve_flight_plan", "issue_clearance",
    "cancel_clearance",
}


class Observer:
    """Renders messages as panels and audit events as one-line notes."""

    def __init__(self, *, silent: bool = False, verbose: bool = False, pace: float = 0.0,
                 console: Console | None = None) -> None:
        self.silent = silent
        self.verbose = verbose
        self.pace = pace  # real seconds per sim minute
        self.console = console or Console(highlight=False)
        self.message_count = 0
        self._clock = 0.0

    async def on_update(self, node: str, update: dict) -> None:
        events = update.get("events") or []
        clock = (update.get("world") or {}).get("clock_min", self._clock)
        if clock > self._clock:
            if self.pace > 0:
                await asyncio.sleep((clock - self._clock) * self.pace)
            self._clock = clock
        # Phase banners first, then speech, then what the speech did.
        for event in events:
            if event.get("type") == "mission_phase":
                self._event(event)
        for message in update.get("log") or []:
            self.message_count += 1
            self._message(message)
        for event in events:
            if event.get("type") != "mission_phase":
                self._event(event)

    def _message(self, message: dict) -> None:
        if self.silent:
            return
        priority = message.get("priority", "ROUTINE")
        injected = message["sender"] in NON_AGENT_SENDERS
        style = "magenta" if injected else _PRIORITY_STYLE.get(priority, "white")
        header = Text()
        header.append(f"#{message['seq']:03d} ", style="dim")
        header.append(f"T+{message['t']:g} ", style="dim")
        header.append(message["sender"], style=f"bold {style}")
        header.append(" -> ", style="dim")
        header.append(", ".join(message["to"]), style=f"bold {style}")
        header.append(f"  [{priority}]", style=style)
        header.append(f"  {message['channel'].lower()}", style="dim")
        if message.get("kind") not in (None, "voice", "inject", "system"):
            header.append(f"  {message['kind']}", style="bold green")
        self.console.print(Panel(Text(message["body"], overflow="fold"), title=header, title_align="left",
                                 border_style="magenta" if injected else _PRIORITY_BORDER.get(priority, "white"),
                                 padding=(0, 1)))

    def _event(self, event: dict) -> None:
        if self.silent:
            return
        kind, t = event.get("type"), event.get("t", 0)
        out = self.console.print
        if kind == "mission_phase":
            out(Rule(f"[bold white]{event['name']}[/bold white]  [dim]T+{t:g}[/dim]", style="white"))
        elif kind == "flight_phase":
            out(f"[dim]      T+{t:g}  aircraft: {event['previous']} -> [/dim][bold]{event['phase']}[/bold]")
        elif kind == "waypoint":
            out(f"[dim]      T+{t:g}  passing {event['name']}[/dim]")
        elif kind == "gate_hold":
            out(f"[yellow]      T+{t:g}  HOLD {event['hold_number']}: {event['item']} is waiting on "
                f"{', '.join(event['unmet'])} (+{event['slip_min']:g} min)[/yellow]")
        elif kind == "hold_released":
            out(f"[green]      T+{t:g}  hold released: {event['item']}[/green]")
        elif kind == "guard_denied":
            out(f"[bold red]      T+{t:g}  REFUSED {event['actor']} {event['action']}[/bold red] "
                f"[red]({event['rule']}) {event['reason']}[/red]")
        elif kind == "comms_denied":
            out(f"[bold red]      T+{t:g}  REFUSED {event['actor']} transmission[/bold red] "
                f"[red]({event['rule']}) {event['reason']}[/red]")
        elif kind == "action" and event.get("action") == "bundle_released" and event.get("on_target") is False:
            out(f"[bold red]      T+{t:g}  OFF TARGET {event['bundle_id']} released "
                f"{event.get('release_point')}[/bold red]")
        elif kind == "action" and (self.verbose or event.get("action") in _SHOWN_ACTIONS):
            detail = {k: v for k, v in event.items() if k not in ("type", "t", "actor", "action")}
            text = ", ".join(f"{k}={v}" for k, v in detail.items())
            out(f"[green]      T+{t:g}  {event['actor']} {event['action']}[/green][dim] {text}[/dim]")
        elif kind == "effect":
            detail = {k: v for k, v in event.items() if k not in ("type", "t", "effect")}
            out(f"[magenta]      T+{t:g}  world effect: {event['effect']} {detail or ''}[/magenta]")
        elif kind in ("bingo_fuel", "fuel_exhausted", "limit_exceeded", "burst_limit", "stalled"):
            out(f"[bold yellow]      T+{t:g}  {kind.replace('_', ' ').upper()} "
                f"{ {k: v for k, v in event.items() if k not in ('type', 't')} }[/bold yellow]")
        elif kind == "turn" and self.verbose and event.get("silent"):
            out(f"[dim]      T+{t:g}  {event['actor']} stayed silent[/dim]")
        elif kind == "run_end":
            out(Rule(f"[bold]run ended: {event['status']}[/bold]  [dim]T+{t:g}[/dim]"))


_SPEAKERS = {
    "COMMANDER": "Aircraft Commander", "COPILOT": "Co-Pilot", "NAVIGATOR": "Navigator",
    "LOADMASTER": "Loadmaster", "ATC": "Air Traffic Control", "EVALUATOR": "Evaluator",
}
_PRIORITY_LABEL = {"ROUTINE": "", "URGENT": " URGENT", "EMERGENCY": " EMERGENCY"}


class RunRecorder:
    """
    Writes a run to disk:

    * ``messages_<run>.jsonl``  one record per message.  Keeps the field names
      of the original MessageLogger (seq, from, to, priority, speaker,
      skip_tts, body) so existing TTS tooling still reads it, and adds
      sim_time_min, channel and kind.
    * ``transcript_<run>.txt``  the same, formatted for reading.
    * ``events_<run>.jsonl``    the audit trail.
    * ``scorecard_<run>.json``  written by :meth:`close`.
    """

    def __init__(self, log_dir: str | Path, run_id: str) -> None:
        self.log_dir = Path(log_dir)
        self.run_id = run_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.messages_path = self.log_dir / f"messages_{run_id}.jsonl"
        self.transcript_path = self.log_dir / f"transcript_{run_id}.txt"
        self.events_path = self.log_dir / f"events_{run_id}.jsonl"
        self.scorecard_path = self.log_dir / f"scorecard_{run_id}.json"
        self._start = time.monotonic()
        self._count = 0
        self._messages = open(self.messages_path, "a", encoding="utf-8")
        self._events = open(self.events_path, "a", encoding="utf-8")
        self._transcript = open(self.transcript_path, "a", encoding="utf-8")
        self._transcript.write(f"{'=' * 60}\n  OPERATION AIRDROP ALPHA - MISSION TRANSCRIPT\n"
                               f"  Run ID : {run_id}\n  Started: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                               f"{'=' * 60}\n\n")

    def on_update(self, node: str, update: dict) -> None:
        for message in update.get("log") or []:
            self._count += 1
            skip = message["sender"] in ("SCENARIO_RUNNER", "SIM")
            speaker = _SPEAKERS.get(message["sender"], message["sender"])
            record = {
                "seq": message["seq"],
                "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                "elapsed_sec": round(time.monotonic() - self._start, 1),
                "sim_time_min": message["t"],
                "from": message["sender"], "to": ",".join(message["to"]),
                "priority": message["priority"], "channel": message["channel"], "kind": message.get("kind"),
                "speaker": speaker, "skip_tts": skip, "body": message["body"],
            }
            self._messages.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._transcript.write(
                f"[#{message['seq']:04d} | T+{message['t']:g} min]{_PRIORITY_LABEL.get(message['priority'], '')}"
                f"{'  [SKIP - simulation direction]' if skip else ''}\n"
                f"{speaker} -> {', '.join(message['to'])}  ({message['channel'].lower()})\n\n"
                f"{message['body'].strip()}\n\n{'-' * 60}\n\n")
        for event in update.get("events") or []:
            self._events.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        self._messages.flush()
        self._events.flush()
        self._transcript.flush()

    def close(self, scorecard: dict | None = None) -> None:
        if self._transcript.closed:
            return
        self._transcript.write(f"\n{'=' * 60}\n  END OF TRANSCRIPT - {self._count} message(s) recorded\n"
                               f"  Closed: {datetime.now():%Y-%m-%d %H:%M:%S}\n{'=' * 60}\n")
        for handle in (self._messages, self._events, self._transcript):
            handle.close()
        if scorecard is not None:
            self.scorecard_path.write_text(json.dumps(scorecard, indent=2, default=str), encoding="utf-8")


def fan_out(*handlers: Any):
    """Combine several update handlers into one."""
    async def handler(node: str, update: dict) -> None:
        for h in handlers:
            if h is None:
                continue
            outcome = h(node, update)
            if asyncio.iscoroutine(outcome):
                await outcome
    return handler
