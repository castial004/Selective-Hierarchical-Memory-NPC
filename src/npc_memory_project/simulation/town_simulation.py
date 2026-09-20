"""Persistent multi-NPC town simulation.

v0.2.1 changes
--------------
* ``present_evidence`` / ``persuade_rohan`` / ``reset`` moved here from the HTTP
  handler, so the API layer is transport-only and the scenario is testable
  without a socket.
* `share_rumour` works in the shipped default flow. v0.2 selected the speaker's
  strongest ACTIVE memory, and Arun -- the NPC the UI's rumour button posts as
  speaker -- never owned a memory, so the button always returned
  ``no_memory_to_share``. The preset now records Arun's own (first-person)
  accusation on Day 1, which is also the realistic model of an accuser who
  believes what he says.
* The Day-3 exoneration rewires belief with an explicit evidence lineage, so the
  derived semantic belief can be ablated together with its source.
* The apology trust bump is now a documented, configurable attribute instead of
  a magic number inside the interaction path, and it is reported in the decision
  trace context.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from npc_memory_project.beliefs.updater import ContradictionAwareBeliefUpdater
from npc_memory_project.core.models import (
    BeliefStatus,
    GameEvent,
    MemoryRecord,
    MemoryTier,
    NPCState,
    WorldState,
)
from npc_memory_project.decision.engine import UtilityDecisionEngine
from npc_memory_project.explainability.counterfactual import (
    CounterfactualExplanationVerifier,
    lineage_closure,
)
from npc_memory_project.explainability.dialogue import FaithfulDialogueSynthesizer
from npc_memory_project.memory.consolidation import SemanticConsolidator
from npc_memory_project.memory.manager import HierarchicalMemoryManager
from npc_memory_project.persistence.sqlite_store import SQLiteMemoryStore
from npc_memory_project.social.rumours import RumourDiffusion


class TownSimulation:
    """Multi-NPC persistent world: memory tiers, rumours, explainable decisions."""

    #: Trust granted to the NPC that chooses to apologise. Was a bare ``+15.0``
    #: inside ``interact_with_npc``; now explicit so the audit trail can state it.
    apology_trust_gain: float = 15.0

    def __init__(self, db_path: str = ":memory:") -> None:
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

    # ------------------------------------------------------------ scenario
    def init_characters(self) -> None:
        self.npcs = {
            "mira": NPCState(
                npc_id="mira",
                role="shopkeeper",
                trust=-30.0,
                personality={"fairness": 0.90, "cautious": 0.70},
                inventory={"medicine": 5, "bandage": 10, "herbs": 8},
                goals=["protect_inventory", "run_apothecary"],
            ),
            "arun": NPCState(
                npc_id="arun",
                role="vendor",
                trust=0.0,
                personality={"fairness": 0.40, "cautious": 0.40, "aggressive": 0.60},
                inventory={"apple": 20, "bread": 15, "rumour": 99},
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

    def reset(self) -> None:
        """Return the world to the Day-1 baseline."""
        self.store.clear()
        self.event_log.clear()
        self.world.game_day = 1
        self.world.location = "town_square"
        self.player_pos = {"x": 10, "y": 8}
        self.init_characters()
        self.load_preset_benchmark()

    def load_preset_benchmark(self) -> None:
        """Seed the baseline IEEE paper Day-1 state."""
        self.store.clear()
        self.world.game_day = 1
        self.npcs["mira"].trust = -30.0

        # Mira hears the accusation from Arun.
        self.record_event(GameEvent(
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
        ))
        self._log("Arun informed Mira that the player stole medicine (Day 1).")

        # Arun also holds the claim he is spreading (he is the rumour source).
        self.record_event(GameEvent(
            event_type="theft_accusation",
            actor="arun",
            target_npc="arun",
            description="Arun told the market stalls that the player stole Mira's medicine.",
            game_day=1,
            location="market",
            emotional_impact=0.5,
            relationship_impact=-0.4,
            quest_relevance=0.3,
            novelty=0.7,
            source="arun",
            confidence=0.60,
            metadata={"conflict_key": "medicine_theft", "claim": "player_stole"},
        ))

    # --------------------------------------------------------------- events
    def record_event(self, event: GameEvent) -> MemoryRecord:
        """Dispatch an event: admit to a tier, revise contradictions, persist."""
        memory = self.manager.event_to_memory(event)
        existing = self.store.list_for_npc(event.target_npc)
        revised, incoming = self.updater.revise(existing, memory)
        for m in revised:
            self.store.upsert(m)
        self.store.upsert(incoming)
        return incoming

    def advance_day(self) -> Dict[str, Any]:
        """Advance the clock, run memory lifecycle + consolidation, fire scripted events."""
        self.world.game_day += 1
        day = self.world.game_day

        for npc_id in self.npcs:
            memories = self.store.list_for_npc(npc_id)
            managed = self.manager.manage_lifecycle(memories, day, npc_id)
            for m in managed:
                self.store.upsert(m)
            for m in self.consolidator.consolidate(managed, day, npc_id):
                self.store.upsert(m)

        self._apply_scripted_events(day)
        self._log(f"Dawn of Game Day {day}.")
        return {"current_day": day, "status": "advanced"}

    def _apply_scripted_events(self, day: int) -> None:
        """Scenario beats. The Mira benchmark turns on the Day-3 exoneration."""
        if day != 3:
            return

        exoneration = GameEvent(
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
        self.record_event(exoneration)

        self.store.upsert(self.updater.build_semantic_belief(
            npc_id="mira",
            event_id="semantic-false-accusation",
            summary="The player was falsely accused of stealing Mira's medicine.",
            event_type="belief_player_falsely_accused",
            game_day=3,
            confidence=0.95,
            metadata={"conflict_key": "medicine_theft", "claim": "player_falsely_accused"},
            derived_from=[exoneration.event_id],
        ))
        self.npcs["mira"].trust = 10.0
        self._log("Officer Kael verified Rohan was the thief. Mira revised her beliefs (Day 3).")

    # ---------------------------------------------------------- interaction
    def interact_with_npc(self, npc_id: str) -> Dict[str, Any]:
        """Retrieve -> decide -> verify causality -> speak. Returns the full trace."""
        if npc_id not in self.npcs:
            return {"error": "NPC not found", "npc_id": npc_id}

        npc = self.npcs[npc_id]
        memories = self.store.list_for_npc(npc_id)
        retrieved = self.manager.retrieve(
            memories, npc_id=npc_id, current_day=self.world.game_day, top_k=5
        )

        trace = self.engine.decide(npc, self.world, retrieved)
        self.store.record_trace(trace, self.world.game_day)

        evidence = self.verifier.verify_memories(npc, self.world, retrieved)
        synthesis = self.synthesizer.synthesize(npc, trace.selected_action, evidence)

        trust_before = npc.trust
        if trace.selected_action == "apologise" and npc.trust < 20:
            npc.trust = min(30.0, npc.trust + self.apology_trust_gain)

        self._log(f"Player spoke to {npc_id.capitalize()}. Action: '{trace.selected_action}'.")

        return {
            "npc_id": npc_id,
            "role": npc.role,
            "selected_action": trace.selected_action,
            "dialogue": synthesis["dialogue"],
            "dialogue_source": synthesis.get("dialogue_source", "deterministic"),
            "faithful": synthesis.get("faithful", True),
            "grounded_factor": synthesis.get("grounded_factor"),
            "persona": synthesis.get("persona"),
            "trust": npc.trust,
            "trust_delta": round(npc.trust - trust_before, 2),
            "action_scores": [
                {"action": s.action, "score": s.score, "factors": s.factors}
                for s in trace.action_scores
            ],
            "causal_evidence": [
                {
                    "memory_id": e.memory_id,
                    "factor": e.factor_name,
                    "action_without": e.action_without_factor,
                    "changed_action": e.changed_action,
                    "score_delta": round(e.score_delta, 4),
                    "ablated_group": sorted(self.verifier.ablation_group(
                        retrieved, next(m for m in retrieved if m.event_id == e.memory_id)
                    )) if any(m.event_id == e.memory_id for m in retrieved) else [],
                }
                for e in evidence
            ],
        }

    # --------------------------------------------------------------- social
    def share_rumour(self, speaker_id: str, listener_id: str) -> Optional[Dict[str, Any]]:
        """Speaker passes their most salient belief to the listener."""
        speaker = self.npcs.get(speaker_id)
        listener = self.npcs.get(listener_id)
        if not speaker or not listener:
            return None

        candidates = [
            m for m in self.store.list_for_npc(speaker_id)
            if m.tier != MemoryTier.ARCHIVE
            and m.status in {BeliefStatus.ACTIVE, BeliefStatus.CORROBORATED}
        ]
        if not candidates:
            # fall back to a contested claim: an NPC can still voice what it heard
            candidates = [
                m for m in self.store.list_for_npc(speaker_id)
                if m.tier != MemoryTier.ARCHIVE
            ]
        if not candidates:
            return None

        top = max(candidates, key=lambda m: m.importance * m.confidence)
        rumour_event = self.rumour_diffuser.share_memory(
            top, speaker, listener, self.world.game_day,
            speaker_listener_trust=10.0,
            location=self.world.location,
        )
        stored = self.record_event(rumour_event)
        self._log(f"{speaker_id.capitalize()} shared rumours with {listener_id.capitalize()}.")
        return {
            "status": "shared",
            "speaker": speaker_id,
            "listener": listener_id,
            "about": top.summary,
            "event": rumour_event.description,
            "confidence": rumour_event.confidence,
            # what the listener actually ended up believing
            "listener_belief_status": stored.status.value,
            "listener_usable_in_decisions": stored.status
            in {BeliefStatus.ACTIVE, BeliefStatus.CORROBORATED},
        }

    # ----------------------------------------------------------- player acts
    def present_evidence(self, target: str = "kael") -> Dict[str, Any]:
        """Player shows stamped receipts; the target (and Mira, via Kael) revise."""
        if target not in self.npcs:
            return {"error": "NPC not found", "npc_id": target}

        self.record_event(GameEvent(
            event_type="innocence_verified",
            actor="player",
            target_npc=target,
            description="The player presented stamped pharmacy receipts proving Rohan stole the medicine.",
            game_day=self.world.game_day,
            location="pharmacy",
            emotional_impact=0.9,
            relationship_impact=0.8,
            quest_relevance=0.8,
            novelty=0.9,
            source="direct_proof",
            confidence=0.98,
            metadata={"conflict_key": "medicine_theft", "claim": "rohan_stole"},
        ))

        if target == "kael":
            exoneration = GameEvent(
                event_type="innocence_verified",
                actor="kael",
                target_npc="mira",
                description="Officer Kael officially confirmed the player's receipt evidence proving Rohan stole.",
                game_day=self.world.game_day,
                location="pharmacy",
                emotional_impact=0.9,
                relationship_impact=0.8,
                quest_relevance=0.7,
                novelty=0.9,
                source="guard",
                confidence=0.95,
                metadata={"conflict_key": "medicine_theft", "claim": "rohan_stole"},
            )
            self.record_event(exoneration)
            self.store.upsert(self.updater.build_semantic_belief(
                npc_id="mira",
                event_id=f"semantic-false-accusation-{uuid.uuid4().hex[:6]}",
                summary="The player was falsely accused of stealing Mira's medicine.",
                event_type="belief_player_falsely_accused",
                game_day=self.world.game_day,
                confidence=0.95,
                metadata={"conflict_key": "medicine_theft", "claim": "player_falsely_accused"},
                derived_from=[exoneration.event_id],
            ))
            self.npcs["mira"].trust = 10.0

        self._log(f"Player presented evidence to {target.capitalize()}.")
        return {"status": "evidence_presented", "target": target}

    def persuade_rohan(self) -> Dict[str, Any]:
        """Corner Rohan: he confesses to Kael."""
        self.world.metadata["cornered"] = "true"
        self.record_event(GameEvent(
            event_type="confess_theft",
            actor="rohan",
            target_npc="kael",
            description="Rohan confessed in tears that he stole the medicine out of desperation.",
            game_day=self.world.game_day,
            location="alley",
            emotional_impact=0.95,
            relationship_impact=0.5,
            quest_relevance=0.9,
            novelty=0.9,
            source="confession",
            confidence=0.99,
            metadata={"conflict_key": "medicine_theft", "claim": "rohan_stole"},
        ))
        self._log("Rohan confessed to Officer Kael! Medicine theft resolved.")
        return {"status": "confessed", "npc_id": "rohan"}

    # ----------------------------------------------------------- inspection
    def get_npc_brain(self, npc_id: str) -> Dict[str, Any]:
        """Memory tiers, belief state and latest decision analysis for the inspector."""
        if npc_id not in self.npcs:
            return {"error": "NPC not found", "npc_id": npc_id}

        npc = self.npcs[npc_id]
        all_memories = self.store.list_for_npc(npc_id)

        tiers: Dict[str, List[Dict[str, Any]]] = {t.value: [] for t in MemoryTier}
        for m in all_memories:
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

        retrieved = self.manager.retrieve(
            all_memories, npc_id=npc_id, current_day=self.world.game_day, top_k=5
        )
        trace = self.engine.decide(npc, self.world, retrieved)
        evidence = self.verifier.verify_memories(npc, self.world, retrieved)
        by_id = {m.event_id: m for m in retrieved}

        return {
            "npc_id": npc.npc_id,
            "role": npc.role,
            "trust": round(npc.trust, 1),
            "personality": npc.personality,
            "inventory": npc.inventory,
            "tiers": tiers,
            "retrieved_ids": [m.event_id for m in retrieved],
            "current_action": trace.selected_action,
            "action_scores": [
                {"action": s.action, "score": s.score, "factors": s.factors}
                for s in trace.action_scores
            ],
            "causal_evidence": [
                {
                    "memory_id": e.memory_id,
                    "factor": e.factor_name,
                    "action_without": e.action_without_factor,
                    "changed_action": e.changed_action,
                    "score_delta": round(e.score_delta, 4),
                    "ablated_group": sorted(self.verifier.ablation_group(retrieved, by_id[e.memory_id]))
                    if e.memory_id in by_id else [],
                }
                for e in evidence
            ],
            "llm_mode": "llm" if self.synthesizer.llm_hook.is_configured else "deterministic",
        }

    def simulate_counterfactual(self, npc_id: str, disabled_event_ids: List[str]) -> Dict[str, Any]:
        """Ablate memories (and their derived descendants) to explore alternate decisions."""
        npc = self.npcs.get(npc_id)
        if not npc:
            return {"error": "NPC not found", "npc_id": npc_id}

        all_memories = self.store.list_for_npc(npc_id)
        removed = lineage_closure(all_memories, disabled_event_ids) if disabled_event_ids else set()
        active = [m for m in all_memories if m.event_id not in removed]
        retrieved = self.manager.retrieve(
            active, npc_id=npc_id, current_day=self.world.game_day, top_k=5
        )
        trace = self.engine.decide(npc, self.world, retrieved)

        return {
            "npc_id": npc_id,
            "requested_ablations": list(disabled_event_ids),
            "ablated_ids": sorted(removed),
            "ablated_count": len(removed),
            "selected_action": trace.selected_action,
            "action_scores": [
                {"action": s.action, "score": s.score, "factors": s.factors}
                for s in trace.action_scores
            ],
        }

    # ----------------------------------------------------------------- misc
    def _log(self, text: str) -> None:
        self.event_log.append({"day": self.world.game_day, "text": text})
        if len(self.event_log) > 50:
            self.event_log.pop(0)
