"""Web-layer tests.

v0.2 shipped a 247-line HTTP server with zero tests -- which is why the
directory-traversal hole and the threading crash went unnoticed. These tests
cover the API surface plus the two defects.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from npc_memory_project.simulation.town_simulation import TownSimulation
from npc_memory_project.web.server import create_server


@pytest.fixture(scope="module")
def server():
    srv = create_server("127.0.0.1", 0, TownSimulation(), threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture(scope="module")
def base_url(server):
    return f"http://127.0.0.1:{server.server_address[1]}"


def get(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def post(url: str, payload: dict | None = None):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def test_index_and_static_assets_serve(base_url):
    for path in ("/", "/static/game.js", "/static/inspector.js", "/static/style.css"):
        with urllib.request.urlopen(f"{base_url}{path}", timeout=10) as resp:
            assert resp.status == 200
            assert resp.read()


def test_traversal_attempts_are_refused(base_url):
    for escape in ("../../../../../etc/passwd", "../../../../../../etc/hostname"):
        request = urllib.request.Request(f"{base_url}/static/{escape}")
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(request, timeout=10)
        assert err.value.code in (403, 404)


def test_state_endpoint_reports_every_npc(base_url):
    _, payload = get(f"{base_url}/api/state")
    assert payload["game_day"] == 1
    assert set(payload["npcs"]) == {"mira", "arun", "kael", "rohan"}
    assert payload["npcs"]["mira"]["trust"] == pytest.approx(-30.0)


def test_brain_endpoint_exposes_tiers_and_trace(base_url):
    _, brain = get(f"{base_url}/api/npc/mira/brain")
    assert set(brain["tiers"]) == {"working", "episodic", "semantic", "archive"}
    assert brain["current_action"]
    assert brain["action_scores"]
    assert "causal_evidence" in brain and "retrieved_ids" in brain


def test_interact_reports_dialogue_source_and_evidence(base_url):
    status, payload = post(f"{base_url}/api/interact", {"npc_id": "mira"})
    assert status == 200
    assert payload["selected_action"] in {"refuse_trade", "warn_player", "call_guard"}
    assert payload["dialogue"]
    assert payload["dialogue_source"] == "deterministic"
    assert payload["faithful"] is True
    assert payload["grounded_factor"]


def test_day_advance_then_exoneration_flips_behaviour(base_url):
    for _ in range(3):
        status, _ = post(f"{base_url}/api/day/advance")
        assert status == 200

    _, payload = post(f"{base_url}/api/interact", {"npc_id": "mira"})
    assert payload["selected_action"] == "apologise"
    assert payload["grounded_factor"].startswith("The guard proved")


def test_counterfactual_endpoint_ablates_descendants(base_url):
    post(f"{base_url}/api/scenario/reset")
    for _ in range(3):
        post(f"{base_url}/api/day/advance")

    _, brain = get(f"{base_url}/api/npc/mira/brain")
    guard_proof = next(
        m["event_id"] for m in brain["tiers"]["episodic"]
        if m["summary"].startswith("The guard proved")
    )

    status, payload = post(
        f"{base_url}/api/counterfactual/simulate",
        {"npc_id": "mira", "disabled_event_ids": [guard_proof]},
    )
    assert status == 200
    # the guard proof plus the summary derived from it
    assert payload["ablated_count"] >= 2
    assert guard_proof in payload["ablated_ids"]
    assert payload["selected_action"] != "apologise"


def test_rumour_and_evidence_and_reset_endpoints(base_url):
    status, payload = post(f"{base_url}/api/rumour/share", {"speaker": "arun", "listener": "mira"})
    assert status == 200 and payload["status"] == "shared"

    status, payload = post(f"{base_url}/api/action/evidence", {"target": "kael"})
    assert status == 200 and payload["status"] == "evidence_presented"

    status, payload = post(f"{base_url}/api/action/persuade_rohan")
    assert status == 200 and payload["status"] == "confessed"

    status, payload = post(f"{base_url}/api/scenario/reset")
    assert status == 200 and payload["game_day"] == 1

    _, state = get(f"{base_url}/api/state")
    assert state["game_day"] == 1


def test_unknown_routes_return_json_404(base_url):
    request = urllib.request.Request(f"{base_url}/api/nope")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(request, timeout=10)
    assert err.value.code == 404
    assert json.loads(err.value.read())["error"] == "not found"


def test_dialogue_config_reports_offline_mode(base_url):
    _, payload = get(f"{base_url}/api/dialogue/config")
    assert payload["llm_configured"] is False
    assert "Deterministic" in payload["mode"]


def test_cors_headers_are_opt_out_by_default(base_url):
    request = urllib.request.Request(f"{base_url}/api/state")
    with urllib.request.urlopen(request, timeout=10) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") is None
