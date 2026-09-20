"""Regression tests for the v0.2.1 audit fixes.

Each test names the concrete defect it locks down.
"""

from __future__ import annotations

import dataclasses
import threading

import pytest

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.features import features_of
from npc_memory_project.core.models import (
    ActionScore,
    BeliefStatus,
    DecisionTrace,
    GameEvent,
    MemoryRecord,
    MemoryTier,
    NPCState,
    WorldState,
)
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.decision.valid_actions import guard_may_arrest, valid_actions
from npc_memory_project.evaluation.harness import (
    FlatMemoryRetrieval,
    build_scenarios,
    evaluate,
)
from npc_memory_project.explainability.counterfactual import (
    CounterfactualExplanationVerifier,
    lineage_closure,
)
from npc_memory_project.explainability.dialogue import (
    FaithfulDialogueSynthesizer,
    LLMDialogueHook,
    PERSONA_REGISTRY,
    verify_dialogue_grounding,
)
from npc_memory_project.memory.manager import HierarchicalMemoryManager
from npc_memory_project.persistence.sqlite_store import SQLiteMemoryStore
from npc_memory_project.simulation.town_simulation import TownSimulation


# --------------------------------------------------------------- web traversal
def test_web_server_blocks_directory_traversal():
    """v0.2 served /etc/passwd via /static/../../../../../etc/passwd."""
    from npc_memory_project.web.server import create_server

    server = create_server("127.0.0.1", 0, TownSimulation())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        import urllib.error
        import urllib.request

        for escape in ("../../../../../etc/passwd", "../../../../../../etc/hostname"):
            url = f"http://127.0.0.1:{port}/static/{escape}"
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(url, timeout=5)
            assert err.value.code in (403, 404), f"{url} returned {err.value.code}"

        # the legit document still works
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert resp.status == 200
            assert b"canvas" in resp.read().lower()
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------ sqlite threading
def test_in_memory_store_is_thread_safe():
    """v0.2 raised sqlite3.ProgrammingError on any second-thread access."""
    store = SQLiteMemoryStore(":memory:")
    errors: list = []

    def worker(n: int) -> None:
        try:
            store.upsert(MemoryRecord(
                f"m{n}", "mira", f"fact {n}", "greeting", 1, MemoryTier.WORKING, 0.2, 1.0
            ))
            store.list_for_npc("mira")
            store.record_trace(
                DecisionTrace("mira", "trade", [ActionScore("trade", 1.0, {})], []), game_day=1
            )
        except Exception as exc:  # noqa: BLE001 - the point is to catch anything
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], errors
    assert len(store.list_for_npc("mira")) == 8


def test_threaded_http_server_handles_concurrent_requests():
    """End-to-end version of the threading fix: the simulator must serve 2+ threads."""
    from http.server import ThreadingHTTPServer
    from npc_memory_project.web.server import create_server

    server = create_server("127.0.0.1", 0, TownSimulation(), threaded=True)
    assert isinstance(server, ThreadingHTTPServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    results: list = []

    def hit() -> None:
        import json
        import urllib.request

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/interact",
            data=json.dumps({"npc_id": "mira"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            results.append(json.loads(resp.read())["selected_action"])

    try:
        threads = [threading.Thread(target=hit) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        server.shutdown()
        server.server_close()

    assert len(results) == 6
    assert all(action in {"refuse_trade", "warn_player", "call_guard"} for action in results)


# ---------------------------------------------------------------- arrest gate
def test_guard_cannot_arrest_without_warrant():
    """v0.2's arrest gate was a literal `pass`; the guard arrested at will."""
    guard = NPCState("kael", "guard", trust=0)
    lawful_world = WorldState(1, "square", player_has_money=True, player_wanted=False)

    assert guard_may_arrest(lawful_world) is False
    assert "arrest_player" not in valid_actions(guard, lawful_world)

    for world in (
        WorldState(1, "square", True, player_wanted=True),
        WorldState(1, "square", True, False, metadata={"suspect": "player"}),
        WorldState(1, "square", True, False, metadata={"permit_arrest": "true"}),
    ):
        assert "arrest_player" in valid_actions(guard, world)


def test_guard_with_prejudicial_memory_still_cannot_arrest():
    theft = MemoryRecord(
        "theft", "kael", "Player stole medicine", "theft", 1,
        MemoryTier.EPISODIC, 0.95, 0.99,
    )
    guard = NPCState("kael", "guard", trust=0, personality={"aggressive": 0.9})
    world = WorldState(1, "square", True, player_wanted=False)

    assert UtilityDecisionEngine().decide(guard, world, [theft]).selected_action != "arrest_player"


# -------------------------------------------------------------- disputed leak
def test_disputed_memories_are_excluded_from_retrieval():
    """v0.2's retrieval filtered only SUPERSEDED/EXPIRED, so disputes drove decisions."""
    manager = HierarchicalMemoryManager()
    disputed = MemoryRecord(
        "d", "kael", "Unverified rumour: player stole.", "rumour_theft", 1,
        MemoryTier.EPISODIC, 0.85, 0.85, status=BeliefStatus.DISPUTED,
    )
    assert manager.retrieve([disputed], npc_id="kael", current_day=1) == []
    assert len(manager.retrieve(
        [disputed], npc_id="kael", current_day=1, include_disputed=True
    )) == 1


def test_disputed_rumour_cannot_trigger_arrest():
    disputed = MemoryRecord(
        "d", "kael", "Unverified rumour: player stole.", "rumour_theft", 1,
        MemoryTier.EPISODIC, 0.85, 0.85, status=BeliefStatus.DISPUTED,
    )
    guard = NPCState("kael", "guard", trust=0)
    world = WorldState(1, "square", True, player_wanted=False)
    retrieved = HierarchicalMemoryManager().retrieve([disputed], npc_id="kael", current_day=1)
    assert UtilityDecisionEngine().decide(guard, world, retrieved).selected_action != "arrest_player"


# --------------------------------------------------------------- semantic tier
def test_semantic_belief_reaches_the_feature_vector():
    """v0.2: semantic beliefs matched no event_type keyword -> zero influence."""
    semantic = MemoryRecord(
        "s", "mira", "The player was falsely accused.", "belief_player_falsely_accused", 3,
        MemoryTier.SEMANTIC, 1.0, 0.95,
        source="belief_revision", metadata={"claim": "player_falsely_accused"},
    )
    assert "innocence" in features_of(semantic)
    assert UtilityDecisionEngine()._features([semantic])[1] == pytest.approx(0.95)


def test_consolidation_source_is_admitted_to_semantic_tier():
    """choose_tier gated on metadata['is_summary'], which nothing in v0.2 ever set."""
    manager = HierarchicalMemoryManager()
    consolidated = GameEvent(
        "semantic_consensus", "system", "mira", "Factual consensus established.", 4, "shop",
        0.9, 0.9, 0.9, 0.9, source="consolidation", confidence=0.95,
    )
    assert manager.choose_tier(consolidated) == MemoryTier.SEMANTIC

    # an ordinary high-impact event still lands in episodic memory
    ordinary = GameEvent(
        "theft", "player", "mira", "Player stole medicine.", 1, "shop",
        0.9, -1.0, 0.5, 0.9, confidence=1.0,
    )
    assert manager.choose_tier(ordinary) == MemoryTier.EPISODIC


def test_legacy_keyword_features_still_work():
    """Backwards compatibility: records without feature_key behave as in v0.2."""
    legacy = MemoryRecord("l", "mira", "Player stole.", "theft_accusation", 1,
                          MemoryTier.EPISODIC, 0.8, 0.9)
    assert features_of(legacy) == frozenset({"theft"})


# ------------------------------------------------------- lineage-aware ablation
def test_lineage_closure_includes_derived_records():
    source = MemoryRecord("src", "mira", "Guard proved Rohan stole.", "innocence_verified", 3,
                          MemoryTier.EPISODIC, 0.86, 0.95)
    summary = MemoryRecord("sum", "mira", "Player was falsely accused.",
                           "belief_player_falsely_accused", 3, MemoryTier.SEMANTIC, 1.0, 0.95,
                           metadata={"derived_from": "src"})
    derived_of_summary = MemoryRecord("sum2", "mira", "Consensus.", "semantic_consensus", 4,
                                      MemoryTier.SEMANTIC, 0.9, 0.9,
                                      metadata={"derived_from": "sum"})
    unrelated = MemoryRecord("other", "mira", "Weather was fine.", "weather", 4,
                             MemoryTier.WORKING, 0.1, 0.5)

    closure = lineage_closure([source, summary, derived_of_summary, unrelated], ["src"])
    assert closure == {"src", "sum", "sum2"}


def test_ablating_a_source_removes_its_summaries_and_flips_the_action():
    """Without lineage the summary survives and the true cause looks inert."""
    engine = UtilityDecisionEngine()
    verifier = CounterfactualExplanationVerifier(engine)
    npc = NPCState("mira", "shopkeeper", 10.0, {"fairness": 0.9, "cautious": 0.7},
                   {"medicine": 5})
    world = WorldState(4, "pharmacy", True, False)

    source = MemoryRecord("src", "mira",
                          "The guard proved that Rohan, not the player, stole the medicine.",
                          "innocence_verified", 3, MemoryTier.EPISODIC, 0.86, 0.95)
    # the summary carries the same signal as its source, one tier up
    summary = MemoryRecord("sum", "mira", "The player was falsely accused.",
                           "belief_player_falsely_accused", 3, MemoryTier.SEMANTIC, 1.0, 0.95,
                           source="belief_revision",
                           metadata={"derived_from": "src", "claim": "player_falsely_accused"})

    analysis = verifier.verify_memories(npc, world, [source, summary])
    top = analysis[0]
    assert engine.decide(npc, world, [source, summary]).selected_action == "apologise"
    assert top.changed_action is True
    assert top.action_without_factor in {"trade", "refuse_trade", "warn_player"}

    # Without lineage tracking the summary outlives its own source, keeps the
    # signal alive, and the verifier wrongly reports the source as inert.
    naive = CounterfactualExplanationVerifier(engine, follow_lineage=False)
    naive_top = naive.verify_memories(npc, world, [source, summary])[0]
    assert naive_top.changed_action is False
    assert naive_top.score_delta < top.score_delta


# ------------------------------------------------------------- corroboration
def test_independent_corroboration_raises_confidence():
    updater = ContradictionAwareBeliefUpdater(corroboration_gain=0.05)
    original = MemoryRecord("a", "mira", "Player stole.", "theft_accusation", 1,
                            MemoryTier.EPISODIC, 0.8, 0.6, source="arun",
                            metadata={"conflict_key": "k", "claim": "player_stole"})
    independent = MemoryRecord("b", "mira", "Player stole.", "theft_accusation", 2,
                               MemoryTier.EPISODIC, 0.8, 0.6, source="vendor_x",
                               metadata={"conflict_key": "k", "claim": "player_stole"})
    revised, _ = updater.revise([original], independent)

    assert revised[0].status == BeliefStatus.CORROBORATED
    assert revised[0].confidence > original.confidence


def test_hearsay_echo_does_not_raise_confidence():
    """Repeating a rumour back must not increase certainty."""
    updater = ContradictionAwareBeliefUpdater(corroboration_gain=0.05)
    original = MemoryRecord("a", "mira", "Player stole.", "theft_accusation", 1,
                            MemoryTier.EPISODIC, 0.8, 0.7, source="arun",
                            metadata={"conflict_key": "k", "claim": "player_stole"})
    echo = MemoryRecord("b", "mira", "Arun told me that: Player stole.", "rumour_theft", 2,
                        MemoryTier.WORKING, 0.8, 0.7, source="hearsay_arun",
                        metadata={"conflict_key": "k", "claim": "player_stole",
                                  "origin_event_id": "a"})
    revised, _ = updater.revise([original], echo)

    assert revised[0].status == BeliefStatus.CORROBORATED
    assert revised[0].confidence == original.confidence


def test_revise_does_not_mutate_the_incoming_record():
    updater = ContradictionAwareBeliefUpdater()
    existing = MemoryRecord("a", "mira", "Player stole.", "theft_accusation", 1,
                            MemoryTier.EPISODIC, 0.8, 0.9, source="guard",
                            metadata={"conflict_key": "k", "claim": "player_stole"})
    incoming = MemoryRecord("b", "mira", "Rohan stole.", "innocence_verified", 2,
                            MemoryTier.EPISODIC, 0.8, 0.4, source="arun",
                            metadata={"conflict_key": "k", "claim": "rohan_stole"})
    before = dataclasses.replace(incoming)

    _, returned = updater.revise([existing], incoming)

    assert incoming.status == before.status, "caller's object was mutated in place"
    assert returned.status == BeliefStatus.DISPUTED


# --------------------------------------------------------- llm faithfulness
class _HostileHook(LLMDialogueHook):
    """A backend that ignores the prompt -- the case v0.2 could not detect."""

    def __init__(self, text: str) -> None:
        super().__init__(api_key="test-key")
        self._text = text

    def _call_llm_api(self, system_prompt, user_prompt, fallback):  # noqa: D102
        return self._text


def test_hallucinated_dialogue_is_rejected_and_reported_unfaithful():
    synthesizer = FaithfulDialogueSynthesizer(
        llm_hook=_HostileHook("I saw you burn down the orphanage! And you owe me 500 gold!")
    )
    evidence = [
        dataclasses.replace(
            _evidence("Officer Kael proved Rohan was the thief"), memory_id="m1"
        )
    ]
    result = synthesizer.synthesize(
        NPCState("mira", "shopkeeper", 10.0, {"fairness": 0.9}), "apologise", evidence
    )

    assert "orphanage" not in result["dialogue"]
    assert result["dialogue_source"] == "llm_rejected"
    assert result["faithful"] is True          # the restored template is grounded
    assert result["grounded_factor"] == "Officer Kael proved Rohan was the thief"


def test_grounded_paraphrase_is_accepted():
    synthesizer = FaithfulDialogueSynthesizer(
        llm_hook=_HostileHook("Rohan was the thief -- Officer Kael proved it, so I apologise.")
    )
    evidence = [_evidence("Officer Kael proved Rohan was the thief")]
    result = synthesizer.synthesize(
        NPCState("mira", "shopkeeper", 10.0, {"fairness": 0.9}), "apologise", evidence
    )

    assert result["dialogue_source"] == "llm_verified"
    assert result["faithful"] is True
    assert "Rohan" in result["dialogue"]


def test_dropped_causal_factor_fails_grounding_check():
    grounded, missing = verify_dialogue_grounding(
        "Apologies, let us start over.", ["Officer Kael proved Rohan was the thief"]
    )
    assert grounded is False
    assert missing == ["Officer Kael proved Rohan was the thief"]


def test_offline_hook_never_calls_a_model():
    hook = LLMDialogueHook(api_key=None, endpoint=None)
    assert hook.is_configured is False
    base = "Halt in the name of the law!"
    text, source, faithful = hook.polish_verified(
        base, NPCState("kael", "guard"), PERSONA_REGISTRY["kael"], []
    )
    assert (text, source, faithful) == (base, "deterministic", True)


def _evidence(factor: str):
    from npc_memory_project.core.models import ExplanationEvidence

    return ExplanationEvidence(
        factor_name=factor,
        original_action="apologise",
        action_without_factor="trade",
        original_score=0.6,
        score_without_factor=0.4,
        changed_action=True,
        score_delta=0.2,
    )


# ------------------------------------------------------------------- rumours
def test_rumour_button_works_in_the_shipped_scenario():
    """v0.2: Arun owned no memory, so the UI's rumour action always failed."""
    sim = TownSimulation()
    shared = sim.share_rumour("arun", "mira")
    assert shared is not None
    assert shared["status"] == "shared"
    assert shared["speaker"] == "arun" and shared["listener"] == "mira"


def test_rumour_location_is_a_place_not_a_role():
    sim = TownSimulation()
    before = {m.event_id for m in sim.store.list_for_npc("mira")}
    sim.share_rumour("arun", "mira")
    new = [m for m in sim.store.list_for_npc("mira") if m.event_id not in before]

    assert new
    for record in new:
        assert record.metadata.get("source_chain")
        assert "shopkeeper" not in record.tags, record.tags


def test_disputed_rumour_does_not_corrupt_an_exonerated_npc():
    """Round-tripping hearsay after exoneration must not revive the accusation."""
    sim = TownSimulation()
    for _ in range(3):
        sim.advance_day()                       # exoneration lands on day 3
    assert sim.interact_with_npc("mira")["selected_action"] == "apologise"

    sim.share_rumour("arun", "mira")            # Arun repeats the stale accusation
    after = sim.interact_with_npc("mira")

    assert after["selected_action"] == "apologise"
    disputed = [m for m in sim.store.list_for_npc("mira")
                if m.status == BeliefStatus.DISPUTED]
    assert disputed, "expected the stale rumour to be recorded as DISPUTED"


# ------------------------------------------------------------------ evaluation
def test_invariant_suite_discriminates_selective_from_flat_memory():
    scenarios = build_scenarios(40)
    shm = evaluate(scenarios)
    flat = evaluate(scenarios, retrieval=FlatMemoryRetrieval(top_k=5))

    assert shm["checks"] > 0
    assert shm["pass_rate"] == pytest.approx(1.0), shm["failures"]
    assert shm["pass_rate"] > flat["pass_rate"], (
        "the invariant suite must distinguish status-aware retrieval from a "
        "status-blind stream, otherwise it measures nothing"
    )


def test_contract_checks_all_pass():
    from npc_memory_project.evaluation.benchmark import contract_checks

    for row in contract_checks():
        assert row["status"] == "PASS", row


def test_footprint_is_measured_not_assumed():
    from npc_memory_project.evaluation.benchmark import footprint_measurement

    measured = footprint_measurement(n_scenarios=20)
    per_decision = measured["per_decision"]

    assert per_decision["held_records"] > per_decision["retrieved_records"]
    assert 0 <= per_decision["char_reduction_pct"] <= 100
    assert per_decision["held_chars"] > 0 and per_decision["retrieved_chars"] > 0
