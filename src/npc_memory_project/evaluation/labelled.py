"""Author-labelled decision cases: the correctness regression suite.

Seventeen states with an expected action family, each written to isolate one
mechanism (status filtering, tiering, admissibility, contradiction handling,
rumour provenance). These ARE used as the accuracy benchmark in
``evaluation/report.py`` -- and they also ARE the weak part of it, because the
same person wrote the system and the labels.

Three things keep it useful and honest:

* ``label_source`` is carried on every case and surfaced in the report, so the
  reader is told the labels are ``author``, not human.
* Each case carries a ``rationale`` stating *why* the expectation holds, so a
  reader can disagree with an individual label rather than with a score.
* ``run_labelled_suite`` scores ANY retrieval policy, so the set functions as a
  discrimination test: a method that merely ranks by recency should score worse.

``docs/HUMAN_EVAL_PROTOCOL.md`` specifies how to replace this with independent
human annotation, and ``evaluation/report.py --export-labels`` emits the exact
instrument that protocol needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.models import (
    BeliefStatus, GameEvent, MemoryRecord, MemoryTier, NPCState, WorldState,
)
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.memory.manager import HierarchicalMemoryManager

#: action families -- confusing trade with offer_discount matters less than
#: confusing trade with arrest_player
FAMILY = {
    "trade": "warm", "offer_discount": "warm", "apologise": "warm", "help_player": "warm",
    "refuse_trade": "punitive", "warn_player": "punitive", "call_guard": "punitive",
    "arrest_player": "punitive",
    "talk": "neutral", "ignore": "neutral", "deny": "neutral", "flee": "neutral",
    "bribe": "neutral", "spread_rumour": "neutral", "confess": "neutral",
    "question_player": "informative", "report_findings": "informative",
}

CLAIM_FEATURE = {
    "player_stole": "theft",
    "player_falsely_accused": "innocence",
    "rohan_stole": "innocence",
}


@dataclass
class LabelCase:
    case_id: str
    npc: NPCState
    world: WorldState
    memories: List[MemoryRecord]
    expected_family: str
    rationale: str
    label_source: str = "author"          # never claim otherwise
    alternatives: Tuple[str, ...] = ()    # other defensible families, if any

    def is_correct(self, action: str) -> bool:
        chosen = FAMILY.get(action, "neutral")
        return chosen == self.expected_family or chosen in self.alternatives


def _memory(
    event_id: str,
    npc_id: str,
    summary: str,
    event_type: str,
    day: int,
    tier: MemoryTier,
    importance: float,
    confidence: float,
    status: BeliefStatus = BeliefStatus.ACTIVE,
    claim: Optional[str] = None,
    source: str = "direct",
    conflict_key: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
) -> MemoryRecord:
    meta = dict(metadata or {})
    if claim:
        meta["claim"] = claim
    if conflict_key:
        meta["conflict_key"] = conflict_key
    return MemoryRecord(
        event_id=event_id, npc_id=npc_id, summary=summary, event_type=event_type,
        game_day=day, tier=tier, importance=importance, confidence=confidence,
        status=status, source=source, tags=[event_type], metadata=meta,
    )


def _shopkeeper(trust: float = 0.0) -> NPCState:
    return NPCState("mira", "shopkeeper", trust,
                    {"fairness": 0.9, "cautious": 0.7}, {"medicine": 5, "bandage": 10})


def _guard(trust: float = 0.0, aggressive: float = 0.3) -> NPCState:
    return NPCState("kael", "guard", trust,
                    {"fairness": 0.9, "cautious": 0.8, "aggressive": aggressive},
                    {"sword": 1})


def _world(day: int = 4, **meta: str) -> WorldState:
    return WorldState(day, "pharmacy", player_has_money=True, player_wanted=False,
                      metadata=dict(meta))


def author_labelled_cases() -> List[LabelCase]:
    """The regression set. Each case isolates one mechanism."""
    cases: List[LabelCase] = []

    # ---- 1. no memory at all: nothing to go on ------------------------------
    cases.append(LabelCase(
        "fresh-npc-no-history",
        _shopkeeper(trust=0.0), _world(),
        [],
        "warm",
        "No history at all; a neutral shopkeeper serves a customer. Any punitive "
        "action here would be unmotivated.",
    ))

    # ---- 2. active accusation -> do not serve -------------------------------
    cases.append(LabelCase(
        "active-accusation-blocks-trade",
        _shopkeeper(trust=-30.0), _world(),
        [_memory("a1", "mira", "Arun accused the player of stealing medicine.",
                 "theft_accusation", 1, MemoryTier.EPISODIC, 0.86, 0.60,
                 claim="player_stole", conflict_key="theft")],
        "punitive",
        "A single active accusation she believes: refusing or warning is the "
        "believable response; serving would ignore her own belief.",
    ))

    # ---- 3. exoneration -> warm ---------------------------------------------
    cases.append(LabelCase(
        "exoneration-restores-warmth",
        _shopkeeper(trust=10.0), _world(),
        [
            _memory("a1", "mira", "Arun accused the player of stealing medicine.",
                    "theft_accusation", 1, MemoryTier.EPISODIC, 0.86, 0.60,
                    status=BeliefStatus.SUPERSEDED, claim="player_stole",
                    conflict_key="theft"),
            _memory("e1", "mira", "The guard proved that Rohan, not the player, stole the medicine.",
                    "innocence_verified", 3, MemoryTier.EPISODIC, 0.86, 0.95,
                    claim="rohan_stole", conflict_key="theft", source="guard"),
            _memory("s1", "mira", "The player was falsely accused of stealing medicine.",
                    "belief_player_falsely_accused", 3, MemoryTier.SEMANTIC, 1.0, 0.95,
                    claim="player_falsely_accused", source="belief_revision"),
        ],
        "warm",
        "Superseded accusation plus a certified exoneration: she should be "
        "friendly or apologetic, and must not punish.",
    ))

    # ---- 4. the disputed-rumour trap ----------------------------------------
    cases.append(LabelCase(
        "disputed-rumour-does-not-justify-hostility",
        _shopkeeper(trust=0.0), _world(),
        [
            _memory("s1", "mira", "The player was falsely accused of stealing medicine.",
                    "belief_player_falsely_accused", 3, MemoryTier.SEMANTIC, 1.0, 0.95,
                    claim="player_falsely_accused", source="belief_revision"),
            _memory("d1", "mira", "A drunkard claimed the player was seen near the shelf.",
                    "rumour_theft_accusation", 3, MemoryTier.WORKING, 0.5, 0.30,
                    status=BeliefStatus.DISPUTED, claim="player_stole",
                    conflict_key="theft", source="hearsay_drunkard"),
        ],
        "warm",
        "A low-confidence contested claim the updater explicitly marked DISPUTED "
        "must not outweigh established exoneration. Punishing here is the "
        "documented v0.2 bug.",
    ))

    # ---- 5. corroboration raises confidence ---------------------------------
    cases.append(LabelCase(
        "corroborated-accusation-hardens-refusal",
        _shopkeeper(trust=-10.0), _world(),
        [
            _memory("a1", "mira", "Arun accused the player of stealing medicine.",
                    "theft_accusation", 1, MemoryTier.EPISODIC, 0.86, 0.60,
                    claim="player_stole", conflict_key="theft", source="arun"),
            _memory("a2", "mira", "A second vendor also reported the theft.",
                    "theft_accusation", 2, MemoryTier.EPISODIC, 0.80, 0.62,
                    claim="player_stole", conflict_key="theft", source="vendor_x",
                    status=BeliefStatus.CORROBORATED),
        ],
        "punitive",
        "Two independent sources, one corroborated: she should hold the belief and "
        "not serve.",
    ))

    # ---- 6. old superseded memory must not resurface ------------------------
    cases.append(LabelCase(
        "superseded-memory-stays-dead",
        _shopkeeper(trust=10.0), _world(day=30),
        [
            _memory("a1", "mira", "Arun accused the player of stealing medicine.",
                    "theft_accusation", 1, MemoryTier.ARCHIVE, 0.86, 0.60,
                    status=BeliefStatus.SUPERSEDED, claim="player_stole",
                    conflict_key="theft"),
            _memory("e1", "mira", "The guard proved Rohan stole the medicine.",
                    "innocence_verified", 3, MemoryTier.EPISODIC, 0.86, 0.95,
                    claim="rohan_stole", conflict_key="theft", source="guard"),
        ],
        "warm",
        "Long after the affair, the accusation is archived history. She should "
        "serve.",
    ))

    # ---- 7. no stock -> cannot sell, but not hostile ------------------------
    barren = _shopkeeper(trust=20.0)
    barren.inventory = {"medicine": 0}
    cases.append(LabelCase(
        "no-stock-removes-trade",
        barren, _world(),
        [_memory("h1", "mira", "The player returned her lost satchel.",
                 "help_player", 2, MemoryTier.WORKING, 0.5, 0.90)],
        "warm",
        "Nothing left to sell, so trade is inadmissible; friendliness otherwise "
        "stands. Punishing a helpful customer is wrong.",
        alternatives=("neutral",),
    ))

    # ---- 8. no money -> cannot sell ----------------------------------------
    cases.append(LabelCase(
        "no-money-removes-trade",
        _shopkeeper(trust=20.0),
        WorldState(4, "pharmacy", player_has_money=False, player_wanted=False),
        [_memory("h1", "mira", "The player returned her lost satchel.",
                 "help_player", 2, MemoryTier.WORKING, 0.5, 0.90)],
        "warm",
        "A penniless customer cannot buy; the NPC should not turn hostile over it.",
        alternatives=("neutral",),
    ))

    # ---- 9-10. the arrest gate ---------------------------------------------
    cases.append(LabelCase(
        "guard-without-warrant-cannot-arrest",
        _guard(trust=-20.0, aggressive=0.9), _world(),
        [_memory("t1", "kael", "Player stole medicine.", "theft_accusation", 1,
                 MemoryTier.EPISODIC, 0.95, 0.99, claim="player_stole",
                 conflict_key="theft")],
        "informative",
        "Belief is strong but the world grants no warrant: arrest is invalid. "
        "Question or warn instead -- this is the v0.2 arrest-gate bug.",
        alternatives=("punitive",),
    ))
    cases.append(LabelCase(
        "guard-with-warrant-may-arrest",
        _guard(trust=-20.0, aggressive=0.9),
        WorldState(4, "pharmacy", True, False, metadata={"permit_arrest": "true"}),
        [_memory("t1", "kael", "Player stole medicine.", "theft_accusation", 1,
                 MemoryTier.EPISODIC, 0.95, 0.99, claim="player_stole",
                 conflict_key="theft")],
        "punitive",
        "Same belief, but a warrant is in force, so arrest is admissible and "
        "expected of an aggressive guard.",
    ))

    # ---- 11. equal-confidence conflict stays unresolved ---------------------
    cases.append(LabelCase(
        "equal-confidence-conflict-is-disputed",
        _shopkeeper(trust=0.0), _world(),
        [
            _memory("a1", "mira", "Arun accused the player of stealing medicine.",
                    "theft_accusation", 1, MemoryTier.EPISODIC, 0.86, 0.80,
                    status=BeliefStatus.DISPUTED, claim="player_stole",
                    conflict_key="theft", source="arun"),
            _memory("e1", "mira", "Rohan insists he saw the player take it.",
                    "theft_accusation", 2, MemoryTier.EPISODIC, 0.70, 0.80,
                    status=BeliefStatus.DISPUTED, claim="player_stole",
                    conflict_key="theft", source="rohan"),
        ],
        "warm",
        "Neither claim wins, so nothing is established against the player. If the "
        "system can only refuse or arrest here, status filtering is broken.",
        alternatives=("neutral",),
    ))

    # ---- 12. hearsay about the player being innocent ------------------------
    cases.append(LabelCase(
        "low-confidence-hearsay-exoneration",
        _shopkeeper(trust=-5.0), _world(),
        [
            _memory("a1", "mira", "Arun accused the player of stealing medicine.",
                    "theft_accusation", 1, MemoryTier.EPISODIC, 0.86, 0.60,
                    claim="player_stole", conflict_key="theft"),
            _memory("h1", "mira", "A traveller said Rohan was seen with the jar.",
                    "rumour_innocence_verified", 3, MemoryTier.WORKING, 0.45, 0.35,
                    claim="rohan_stole", conflict_key="theft", source="hearsay"),
        ],
        "punitive",
        "A weak, uncorroborated exoneration should not outweigh her own held "
        "accusation. Serving here would be credulous.",
        alternatives=("neutral",),
    ))

    # ---- 13. semantic reputation summary ------------------------------------
    cases.append(LabelCase(
        "semantic-trust-summary-supports-warmth",
        _shopkeeper(trust=15.0), _world(),
        [
            _memory("r1", "mira", "Player is established as a reliable and trusted partner.",
                    "semantic_reputation", 4, MemoryTier.SEMANTIC, 0.82, 0.95,
                    source="consolidation",
                    metadata={"target_actor": "player", "feature_key": "help"}),
        ],
        "warm",
        "A consolidated reputation belief should be actionable. In v0.2 the "
        "semantic tier was inert against every decision.",
    ))

    # ---- 14. suspect cornered ----------------------------------------------
    cornered = NPCState("rohan", "suspect", -20.0, {"remorse": 0.7, "cautious": 0.6},
                        {"stolen_medicine": 1})
    cases.append(LabelCase(
        "cornered-suspect-cannot-flee",
        cornered, WorldState(4, "alley", True, False, metadata={"cornered": "true"}),
        [_memory("c1", "rohan", "The guard found the jar in my room.",
                 "theft_accusation", 3, MemoryTier.EPISODIC, 0.9, 0.95,
                 claim="player_stole", conflict_key="theft")],
        "neutral",
        "'flee' is inadmissible when cornered; deny or confess are the honest "
        "options.",
        alternatives=("informative",),
    ))

    # ---- 15. non-guard roles can never arrest -------------------------------
    cases.append(LabelCase(
        "vendor-cannot-arrest",
        NPCState("arun", "vendor", -30.0, {"cautious": 0.4}, {"apple": 10}),
        WorldState(4, "market", True, True),      # wanted, but still not a guard
        [_memory("t1", "arun", "Player stole from the stalls.", "theft_accusation", 1,
                 MemoryTier.EPISODIC, 0.9, 0.95, claim="player_stole",
                 conflict_key="theft")],
        "punitive",
        "A vendor may warn or refuse, but arrest is never in a vendor's action "
        "menu regardless of how wanted the player is.",
        alternatives=("neutral",),
    ))

    # ---- 16. two independent conflicts --------------------------------------
    cases.append(LabelCase(
        "second-conflict-does-not-leak",
        _shopkeeper(trust=5.0), _world(),
        [
            _memory("e1", "mira", "The guard proved Rohan stole the medicine.",
                    "innocence_verified", 3, MemoryTier.EPISODIC, 0.86, 0.95,
                    claim="rohan_stole", conflict_key="theft", source="guard"),
            _memory("b1", "mira", "The player broke a shelf during the market rush.",
                    "help_player", 2, MemoryTier.WORKING, 0.3, 0.80,
                    claim="player_clumsy", conflict_key="shelf"),
        ],
        "warm",
        "An unrelated minor complaint must not reactivate the settled theft "
        "conflict.",
    ))

    # ---- 17. stale rumour vs fresh exoneration ------------------------------
    cases.append(LabelCase(
        "fresh-evidence-beats-stale-rumour",
        _shopkeeper(trust=0.0), _world(day=12),
        [
            _memory("r1", "mira", "A passer-by repeated that the player stole medicine.",
                    "rumour_theft_accusation", 2, MemoryTier.WORKING, 0.5, 0.40,
                    claim="player_stole", conflict_key="theft", source="hearsay"),
            _memory("e1", "mira", "The guard proved Rohan stole the medicine.",
                    "innocence_verified", 11, MemoryTier.EPISODIC, 0.86, 0.95,
                    claim="rohan_stole", conflict_key="theft", source="guard"),
        ],
        "warm",
        "Recent, high-confidence, first-party evidence should dominate an old "
        "low-confidence rumour.",
    ))

    # ===== memory-pressure cases =====================================
    # With a handful of memories every retrieval policy returns the same thing,
    # so the labelled set above measures the decision engine, not the memory
    # architecture. These cases bury the decisive record under recent noise so
    # that top_k actually binds -- which is the regime the architecture claims
    # to help in.
    def noise(npc_id: str, count: int, day: int, until_day: int) -> List[MemoryRecord]:
        out = []
        for i in range(count):
            out.append(_memory(
                f"noise{i}", npc_id, f"A passing remark in the square ({i}).",
                "smalltalk", max(1, until_day - (i % day)), MemoryTier.WORKING, 0.08, 0.5,
                source="ambient",
            ))
        return out

    # 18. decisive exoneration buried under recent chatter
    cases.append(LabelCase(
        "buried-exoneration-still-absolves",
        _shopkeeper(trust=0.0), _world(day=6),
        noise("mira", 18, 3, 6) + [
            _memory("e1", "mira", "The guard proved that Rohan, not the player, stole the medicine.",
                    "innocence_verified", 3, MemoryTier.EPISODIC, 0.86, 0.95,
                    claim="rohan_stole", conflict_key="theft", source="guard"),
        ],
        "warm",
        "The decisive evidence is older than a pile of trivia. A policy that ranks "
        "purely by recency drops it and treats an exonerated player as a suspect.",
    ))

    # 19. decisive accusation buried under recent chatter
    cases.append(LabelCase(
        "buried-accusation-still-counts",
        _shopkeeper(trust=-10.0), _world(day=6),
        noise("mira", 18, 3, 6) + [
            _memory("a1", "mira", "Arun accused the player of stealing medicine.",
                    "theft_accusation", 2, MemoryTier.EPISODIC, 0.86, 0.60,
                    claim="player_stole", conflict_key="theft", source="arun"),
        ],
        "punitive",
        "She holds a real accusation she believes. Recency-only retrieval buries it "
        "and serves a suspected thief -- the mirror image of the previous case.",
    ))

    # 20. long history, one decisive event deep in the past
    cases.append(LabelCase(
        "deep-history-decisive-event",
        _shopkeeper(trust=5.0), _world(day=60),
        noise("mira", 30, 5, 60) + [
            _memory("e1", "mira", "The guard proved that Rohan, not the player, stole the medicine.",
                    "innocence_verified", 5, MemoryTier.EPISODIC, 0.86, 0.95,
                    claim="rohan_stole", conflict_key="theft", source="guard"),
        ],
        "warm",
        "55 days and 30 trivia records later, the certified exoneration must still "
        "outrank chatter.",
    ))

    # 21. three conflicts, only one of which is live
    mixed: List[MemoryRecord] = noise("mira", 10, 4, 8)
    mixed += [
        _memory("e1", "mira", "The guard proved that Rohan stole the medicine.",
                "innocence_verified", 3, MemoryTier.EPISODIC, 0.86, 0.95,
                claim="rohan_stole", conflict_key="medicine_theft", source="guard"),
        _memory("a1", "mira", "Arun accused the player of stealing medicine.",
                "theft_accusation", 1, MemoryTier.EPISODIC, 0.86, 0.60,
                status=BeliefStatus.SUPERSEDED, claim="player_stole",
                conflict_key="medicine_theft", source="arun"),
        _memory("c1", "mira", "The player overpaid for a bandage and left.",
                "trade", 4, MemoryTier.WORKING, 0.35, 0.9, claim="player_generous",
                conflict_key="ledger"),
        _memory("c2", "mira", "Arun claims the player short-changed him.",
                "theft_accusation", 5, MemoryTier.WORKING, 0.4, 0.4,
                status=BeliefStatus.DISPUTED, claim="player_shortchanged",
                conflict_key="ledger", source="hearsay_arun"),
    ]
    cases.append(LabelCase(
        "multiple-conflicts-stay-separated",
        _shopkeeper(trust=5.0), _world(day=8),
        mixed,
        "warm",
        "The settled theft case and a trivial disputed ledger complaint must not "
        "combine into hostility.",
    ))

    return cases


# ------------------------------------------------------------------ scoring
def run_labelled_suite(retrieval, top_k: int = 5) -> Dict[str, object]:
    """Score a retrieval policy on the labelled set. Returns per-case outcomes."""
    engine = UtilityDecisionEngine()
    outcomes: List[Dict[str, object]] = []

    for case in author_labelled_cases():
        retrieved = retrieval.retrieve(
            case.memories, npc_id=case.npc.npc_id,
            current_day=case.world.game_day, top_k=top_k,
        )
        selected = engine.decide(case.npc, case.world, retrieved).selected_action
        outcomes.append({
            "case_id": case.case_id,
            "expected_family": case.expected_family,
            "selected_action": selected,
            "selected_family": FAMILY.get(selected, "neutral"),
            "correct": case.is_correct(selected),
            "label_source": case.label_source,
            "rationale": case.rationale,
        })

    correct = sum(1 for o in outcomes if o["correct"])
    return {
        "label_source": outcomes[0]["label_source"] if outcomes else "author",
        "cases": len(outcomes),
        "correct": correct,
        "accuracy": correct / len(outcomes) if outcomes else 0.0,
        "outcomes": outcomes,
    }
