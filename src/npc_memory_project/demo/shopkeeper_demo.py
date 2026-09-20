"""Mira shopkeeper demo: false accusation -> exoneration -> faithful explanation.

v0.2.1: the derived semantic belief is now linked to the exoneration it
summarises (``derived_from``). Without that link, lineage-aware ablation leaves
the summary behind, the exoneration's signal survives its own removal, and the
verifier reports that the guard's evidence had no causal effect -- which is how
a correct-looking pipeline silently becomes unfaithful.
"""

from pathlib import Path
import tempfile

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.models import GameEvent, MemoryTier, NPCState, WorldState
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.explainability.counterfactual import CounterfactualExplanationVerifier
from npc_memory_project.explainability.generator import generate_explanation
from npc_memory_project.memory.manager import HierarchicalMemoryManager
from npc_memory_project.persistence.sqlite_store import SQLiteMemoryStore


def main() -> None:
    manager = HierarchicalMemoryManager()
    updater = ContradictionAwareBeliefUpdater()
    engine = UtilityDecisionEngine()
    verifier = CounterfactualExplanationVerifier(engine)

    with tempfile.TemporaryDirectory() as td:
        store = SQLiteMemoryStore(Path(td) / "demo.db")
        mira = NPCState("mira", "shopkeeper", -30, {"fairness": .9, "cautious": .7}, {"medicine": 5})

        # Day 1 - hearsay reaches Mira at low confidence.
        accusation = GameEvent(
            'theft_accusation', 'arun', 'mira',
            "Arun accused the player of stealing Mira's medicine.",
            1, 'pharmacy', .8, -.7, .3, .8, 'arun', .60,
            {'conflict_key': 'medicine_theft', 'claim': 'player_stole'},
        )
        store.upsert(manager.event_to_memory(accusation))

        # Day 3 - the guard establishes who actually did it, at high confidence.
        exoneration = GameEvent(
            'innocence_verified', 'guard', 'mira',
            "The guard proved that Rohan, not the player, stole the medicine.",
            3, 'pharmacy', .9, .8, .6, .9, 'guard', .95,
            {'conflict_key': 'medicine_theft', 'claim': 'rohan_stole'},
        )
        incoming = manager.event_to_memory(exoneration)
        revised, incoming = updater.revise(store.list_for_npc('mira'), incoming)
        for m in revised:
            store.upsert(m)
        store.upsert(incoming)

        # The derived belief is linked to the evidence it compresses.
        semantic = updater.build_semantic_belief(
            npc_id='mira',
            event_id='semantic-false-accusation',
            summary="The player was falsely accused of stealing Mira's medicine.",
            event_type='belief_player_falsely_accused',
            game_day=3,
            confidence=.95,
            metadata={'conflict_key': 'medicine_theft', 'claim': 'player_falsely_accused'},
            derived_from=[incoming.event_id],
        )
        store.upsert(semantic)
        mira.trust = 10

        memories = store.list_for_npc('mira')
        print('\nStored memories after belief revision')
        for m in memories:
            print(f"Day {m.game_day}: {m.summary} | {m.tier.value} | {m.status.value}")

        # Day 4 - player returns.
        world = WorldState(4, 'pharmacy', True, False)
        retrieved = manager.retrieve(memories, npc_id='mira', current_day=4, top_k=5)

        print('\nRetrieved for decision (top_k=5)')
        for m in retrieved:
            print(f"  [{m.tier.value:8s}] {m.summary[:64]}")

        trace = engine.decide(mira, world, retrieved)
        print('\nAction scores')
        for x in trace.action_scores:
            print(f"{x.action:16s} {x.score:.3f} {x.factors}")

        print(f"\nSelected action: {trace.selected_action}")

        print('\nCounterfactual checks (ablation removes the memory and its derived summaries)')
        for e in verifier.verify_memories(mira, world, retrieved):
            if e.memory_id:
                group = sorted(verifier.ablation_group(
                    retrieved, next(m for m in retrieved if m.event_id == e.memory_id)
                ))
                note = f"| removed {len(group)} record(s)"
            else:
                note = ""
            print(f"Remove: {e.factor_name[:60]:60s} -> {e.action_without_factor:12s} "
                  f"changed={e.changed_action} delta={e.score_delta:+.3f} {note}")

        print('\nExplanation')
        print(generate_explanation(
            trace.selected_action, verifier.verify_memories(mira, world, retrieved)
        ))


if __name__ == '__main__':
    main()
