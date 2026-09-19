import uuid
from typing import Dict, List, Optional, Any
from pathlib import Path

from npc_memory_project.core.models import (
    GameEvent,
    MemoryRecord,
    NPCState,
    WorldState,
    MemoryTier,
    BeliefStatus,
    DecisionTrace,
)
from npc_memory_project.memory.manager import HierarchicalMemoryManager
from npc_memory_project.memory.consolidation import SemanticConsolidator
from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.explainability.counterfactual import CounterfactualExplanationVerifier
from npc_memory_project.explainability.dialogue import FaithfulDialogueSynthesizer
from npc_memory_project.social.rumours import RumourDiffusion
from npc_memory_project.persistence.sqlite_store import SQLiteMemoryStore

class TownSimulation:
    """
    Complete persistent multi-NPC game world orchestrating town characters,
    memory tier lifecycles, rumour diffusion, and faithful explainable decision-making.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.store = SQLiteMemoryStore(db_path)
        self.manager = HierarchicalMemoryManager()
        self.updater = ContradictionAwareBeliefUpdater()
        self.consolidator = SemanticConsolidator()
        self.engine = UtilityDecisionEngine()
        self.verifier = CounterfactualExplanationVerifier(self.engine)
        self.synthesizer = FaithfulDialogueSynthesizer()
        self.rumour_diffuser = RumourDiffusion()

        self.world = WorldState(
            game_day=1,
            location="town_square",
            player_has_money=True,
            player_wanted=False,
            metadata={"theft_occurred": "true", "stolen_item": "medicine"},
        )

        self.player_pos = {"x": 10, "y": 8}
        self.npcs: Dict[str, NPCState] = {}
        self.event_log: List[Dict[str, Any]] = []

        self.init_characters()
        self.load_preset_benchmark()

    def init_characters(self) -> None:
        self.npcs = {
            "mira": NPCState(
                npc_id="mira",
                role="shopkeeper",
                trust=-30.0,
                personality={"fairness": 0.90, "cautious": 0.70},
                inventory={"medicine": 5, "bandage": 10},
                goals=["protect_inventory", "run_apothecary"],
            ),
            "arun": NPCState(
                npc_id="arun",
                role="vendor",
                trust=0.0,
                personality={"fairness": 0.40, "cautious": 0.40, "aggressive": 0.60},
                inventory={"apples": 20, "bread": 15},
                goals=["sell_goods", "gossip"],
            ),
            "kael": NPCState(
                npc_id="kael",
                role="guard",
                trust=10.0,
                personality={"fairness": 0.90, "cautious": 0.80, "aggressive": 0.30},
                inventory={"sword": 1, "shackles": 2},
                goals=["keep_order", "find_thief"],
            ),
            "rohan": NPCState(
                npc_id="rohan",
                role="suspect",
                trust=-20.0,
                personality={"remorse": 0.70, "cautious": 0.60},
                inventory={"stolen_medicine": 1, "lockpick": 1},
                goals=["hide_evidence", "avoid_guard"],
            ),
        }

    def load_preset_benchmark(self) -> None:
        """Initializes the baseline IEEE paper Day 1 benchmark state."""
        self.store.clear()
        self.world.game_day = 1
        self.npcs["mira"].trust = -30.0

        # Day 1: Arun accuses the player of theft
        e1 = GameEvent(
            event_type="theft_accusation",
            actor="arun",
            target_npc="mira",
            description="Arun accused the player of stealing Mira's medicine.",
            game_day=1,
            location="pharmacy",
            emotional_impact=0.8,
            relationship_impact=-0.7,
            quest_relevance=0.3,
            novelty=0.8,
            source="arun",
            confidence=0.60,
            metadata={"conflict_key": "medicine_theft", "claim": "player_stole"},
        )
        self.record_event(e1)
        self._log("Arun informed Mira that the player stole medicine (Day 1).")

    def record_event(self, event: GameEvent) -> None:
        """Dispatches an event, promotes to memory tier, resolves contradictions, and saves."""
        target_npc = event.target_npc
        memory = self.manager.event_to_memory(event)

        existing = self.store.list_for_npc(target_npc)
        revised, incoming = self.updater.revise(existing, memory)

        for m in revised:
            self.store.upsert(m)
        self.store.upsert(incoming)

    def advance_day(self) -> Dict[str, Any]:
        """Progresses the world by one day and triggers memory consolidation."""
        self.world.game_day += 1
        day = self.world.game_day

        for npc_id in self.npcs:
            mems = self.store.list_for_npc(npc_id)
            # Enforce lifecycle, decay, and archival
            managed = self.manager.manage_lifecycle(mems, day, npc_id)
            for m in managed:
                self.store.upsert(m)

            # Consolidate semantic beliefs
            consolidated = self.consolidator.consolidate(managed, day, npc_id)
            for m in consolidated:
                self.store.upsert(m)

        # Pre-scripted paper event on Day 3 if player reaches day 3
        if day == 3:
            e2 = GameEvent(
                event_type="innocence_verified",
                actor="kael",
                target_npc="mira",
                description="The guard proved that Rohan, not the player, stole the medicine.",
                game_day=3,
                location="pharmacy",
                emotional_impact=0.9,
                relationship_impact=0.8,
                quest_relevance=0.6,
                novelty=0.9,
                source="guard",
                confidence=0.95,
                metadata={"conflict_key": "medicine_theft", "claim": "rohan_stole"},
            )
            self.record_event(e2)

            # Semantic belief synthesis as in demo
            semantic = self.updater.build_semantic_belief(
                npc_id="mira",
                event_id="semantic-false-accusation",
                summary="The player was falsely accused of stealing Mira's medicine.",
                event_type="belief_player_falsely_accused",
                game_day=3,
                confidence=0.95,
                metadata={"conflict_key": "medicine_theft", "claim": "player_falsely_accused"},
            )
            self.store.upsert(semantic)
            self.npcs["mira"].trust = 10.0
            self._log("Officer Kael verified Rohan was the thief. Mira revised her beliefs (Day 3).")

        self._log(f"Dawn of Game Day {day}.")
        return {"current_day": day, "status": "advanced"}

    def interact_with_npc(self, npc_id: str) -> Dict[str, Any]:
        """Player interacts with an NPC: retrieves memory, scores actions, verifies causality, speaks."""
        if npc_id not in self.npcs:
            return {"error": "NPC not found"}

        npc = self.npcs[npc_id]
        memories = self.store.list_for_npc(npc_id)
        retrieved = self.manager.retrieve(
            memories,
            npc_id=npc_id,
            current_day=self.world.game_day,
            top_k=5,
        )

        trace = self.engine.decide(npc, self.world, retrieved)
        self.store.record_trace(trace, self.world.game_day)

        evidence = self.verifier.verify_memories(npc, self.world, retrieved)
        synth_res = self.synthesizer.synthesize(npc, trace.selected_action, evidence)
        dialogue_text = synth_res["dialogue"] if isinstance(synth_res, dict) else synth_res
        grounded_factor = synth_res.get("grounded_factor") if isinstance(synth_res, dict) else None
        persona_applied = synth_res.get("persona") if isinstance(synth_res, dict) else "neutral"

        # Update trust if apologizing
        if trace.selected_action == "apologise" and npc.trust < 20:
            npc.trust = min(30.0, npc.trust + 15.0)

        self._log(f"Player spoke to {npc_id.capitalize()}. Action: '{trace.selected_action}'.")

        return {
            "npc_id": npc_id,
            "role": npc.role,
            "selected_action": trace.selected_action,
            "dialogue": dialogue_text,
            "grounded_factor": grounded_factor,
            "persona": persona_applied,
            "trust": npc.trust,
            "action_scores": [
                {"action": s.action, "score": s.score, "factors": s.factors}
                for s in trace.action_scores
            ],
            "causal_evidence": [
                {
                    "factor": e.factor_name,
                    "action_without": e.action_without_factor,
                    "changed_action": e.changed_action,
                    "score_delta": round(e.score_delta, 4),
                }
                for e in evidence
            ],
        }

    def share_rumour(self, speaker_id: str, listener_id: str) -> Optional[Dict[str, Any]]:
        """Speaker NPC shares their top active memory with listener NPC."""
        speaker = self.npcs.get(speaker_id)
        listener = self.npcs.get(listener_id)
        if not speaker or not listener:
            return None

        speaker_mems = [
            m for m in self.store.list_for_npc(speaker_id)
            if m.status in {BeliefStatus.ACTIVE, BeliefStatus.CORROBORATED}
            and m.tier != MemoryTier.ARCHIVE
        ]
        if not speaker_mems:
            return None

        top_mem = max(speaker_mems, key=lambda m: m.importance * m.confidence)
        rumour_event = self.rumour_diffuser.share_memory(
            top_mem,
            speaker,
            listener,
            self.world.game_day,
            speaker_listener_trust=10.0,
        )
        self.record_event(rumour_event)
        self._log(f"{speaker_id.capitalize()} shared rumours with {listener_id.capitalize()}.")
        return {"event": rumour_event.description, "confidence": rumour_event.confidence}

    def get_npc_brain(self, npc_id: str) -> Dict[str, Any]:
        """Returns structured memory tiers, belief graph, and latest decision analysis for the inspector."""
        if npc_id not in self.npcs:
            return {"error": "NPC not found"}

        npc = self.npcs[npc_id]
        all_mems = self.store.list_for_npc(npc_id)

        tiers = {
            "working": [],
            "episodic": [],
            "semantic": [],
            "archive": [],
        }
        for m in all_mems:
            tiers[m.tier.value].append({
                "event_id": m.event_id,
                "summary": m.summary,
                "game_day": m.game_day,
                "importance": round(m.importance, 3),
                "confidence": round(m.confidence, 3),
                "status": m.status.value,
                "source": m.source,
                "metadata": m.metadata,
            })

        retrieved = self.manager.retrieve(all_mems, npc_id=npc_id, current_day=self.world.game_day, top_k=5)
        trace = self.engine.decide(npc, self.world, retrieved)
        evidence = self.verifier.verify_memories(npc, self.world, retrieved)

        return {
            "npc_id": npc.npc_id,
            "role": npc.role,
            "trust": round(npc.trust, 1),
            "personality": npc.personality,
            "inventory": npc.inventory,
            "tiers": tiers,
            "current_action": trace.selected_action,
            "action_scores": [
                {"action": s.action, "score": s.score, "factors": s.factors}
                for s in trace.action_scores
            ],
            "causal_evidence": [
                {
                    "factor": e.factor_name,
                    "action_without": e.action_without_factor,
                    "changed_action": e.changed_action,
                    "score_delta": round(e.score_delta, 4),
                }
                for e in evidence
            ],
        }

    def simulate_counterfactual(self, npc_id: str, disabled_event_ids: List[str]) -> Dict[str, Any]:
        """Ablates specific memory IDs to simulate alternate decisions in real time."""
        npc = self.npcs.get(npc_id)
        if not npc:
            return {"error": "NPC not found"}

        all_mems = self.store.list_for_npc(npc_id)
        active_mems = [m for m in all_mems if m.event_id not in disabled_event_ids]
        retrieved = self.manager.retrieve(active_mems, npc_id=npc_id, current_day=self.world.game_day, top_k=5)

        trace = self.engine.decide(npc, self.world, retrieved)
        return {
            "npc_id": npc_id,
            "ablated_count": len(disabled_event_ids),
            "selected_action": trace.selected_action,
            "action_scores": [
                {"action": s.action, "score": s.score, "factors": s.factors}
                for s in trace.action_scores
            ],
        }

    def _log(self, text: str) -> None:
        self.event_log.append({
            "day": self.world.game_day,
            "text": text,
        })
        if len(self.event_log) > 50:
            self.event_log.pop(0)
