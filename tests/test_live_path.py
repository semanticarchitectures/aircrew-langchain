"""
The live-model path, exercised against a local stand-in for the Anthropic API.

No key and no internet are needed.  The real ChatAnthropic client builds real
requests; a small HTTP server on localhost answers them.  This checks the
plumbing a scripted model cannot: tool schemas as the API receives them, the
system prompt and cache markers, the tool-result round trip, and token counts.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from airdrop_alpha.agents.factory import build_crew
from airdrop_alpha.domain.comms import make_message
from airdrop_alpha.domain.data import knowledge_dir
from airdrop_alpha.domain.world import World
from airdrop_alpha.graph.crew import make_crew_node
from airdrop_alpha.graph.state import initial_state, post_messages
from airdrop_alpha.tools.toolsets import TOOLSETS


class FakeAnthropic(BaseHTTPRequestHandler):
    requests: list[dict] = []
    script: list[list[dict]] = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        type(self).requests.append(body)
        content = type(self).script[len(type(self).requests) - 1]
        payload = {
            "id": f"msg_{len(type(self).requests)}", "type": "message", "role": "assistant",
            "model": body["model"], "content": content,
            "stop_reason": "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn",
            "stop_sequence": None,
            # the shape the real API returns, including the per-TTL cache-write breakdown
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 800,
                      "cache_creation_input_tokens": 100, "output_tokens": 50,
                      "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 0}},
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_api(monkeypatch):
    FakeAnthropic.requests, FakeAnthropic.script = [], []
    server = HTTPServer(("127.0.0.1", 0), FakeAnthropic)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.delenv("AIRDROP_MODEL", raising=False)
    yield FakeAnthropic
    server.shutdown()


async def test_live_commander_turn_round_trip(scenario, fake_api):
    fake_api.script = [
        [{"type": "text", "text": "Checking the weather before I decide."},
         {"type": "tool_use", "id": "toolu_1", "name": "query_weather", "input": {"location": "DZ-ALPHA"}}],
        [{"type": "tool_use", "id": "toolu_2", "name": "make_go_nogo",
          "input": {"decision": "GO", "reason": "DZ weather above minimums."}},
         {"type": "tool_use", "id": "toolu_3", "name": "send_message",
          "input": {"to": ["ATC"], "body": "Alpha Approach, CONDOR 71, request taxi."}}],
        [{"type": "text", "text": "GO logged. I cannot reach ATC myself; COPILOT will make the call."}],
    ]
    crew = build_crew(scenario)                       # models from the environment, i.e. ChatAnthropic
    node = make_crew_node("COMMANDER", crew["COMMANDER"], knowledge_dir())
    state = initial_state(scenario, "live")
    state["log"], state["inboxes"] = post_messages(
        [make_message(sender="SCENARIO_RUNNER", to=["COMMANDER"], body="Decide GO or NO-GO.")],
        log_length=0, inboxes=state["inboxes"], clock_min=0)

    update = await node(state, {})

    # what the API was sent
    first = fake_api.requests[0]
    assert first["model"] == "claude-sonnet-4-6" and first["max_tokens"] == 4096
    system = first["system"] if isinstance(first["system"], str) else " ".join(b["text"] for b in first["system"])
    assert "Your callsign is COMMANDER." in system and "HOW THIS SIMULATION WORKS" in system
    assert {t["name"] for t in first["tools"]} == {t.name for t in TOOLSETS["COMMANDER"]}
    for tool in first["tools"]:
        assert "runtime" not in tool["input_schema"].get("properties", {})
        assert tool["description"]
    assert "cache_control" in json.dumps(first)                      # prompt caching is on
    [user] = first["messages"]
    text = user["content"] if isinstance(user["content"], str) else user["content"][0]["text"]
    assert "INCOMING TRAFFIC" in text and "Decide GO or NO-GO." in text
    # tool results went back in the follow-up requests
    assert len(fake_api.requests) == 3
    results = [b for b in fake_api.requests[1]["messages"][-1]["content"] if b["type"] == "tool_result"]
    assert results[0]["tool_use_id"] == "toolu_1" and "Drop Zone ALPHA" in json.dumps(results[0])

    # what the turn committed
    assert World.model_validate(update["world"]).check("go_decision")
    [announcement] = update["log"]                                   # the ATC call was refused
    assert announcement["kind"] == "decision" and "My call is GO" in announcement["body"]
    assert [e["rule"] for e in update["events"] if e["type"] == "comms_denied"] == ["atc_via_copilot"]
    assert update["counters"]["model_calls"] == 3 and update["counters"]["tool_calls"] == 3
    assert update["counters"]["input_tokens"] == 3000 and update["counters"]["output_tokens"] == 150
    # the cached share of the input is counted, so a run's cost can be worked out exactly
    assert update["counters"]["cache_read_tokens"] == 2400 and update["counters"]["cache_write_tokens"] == 300
    assert "NOTE GO logged." in update["memory"]["COMMANDER"][0]
