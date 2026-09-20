from dataclasses import replace
from typing import List, Dict
import uuid

from npc_memory_project.core.features import feature_key_for_claim
from npc_memory_project.core.models import (
    MemoryRecord,
    MemoryTier,
    BeliefStatus,
)

class SemanticConsolidator:
    """
    Evaluates episodic and working memories for patterns, recurring themes,
    or resolved conflicts, consolidating them into persistent Semantic Beliefs.
    """

    def __init__(self, consolidation_threshold: int = 2):
        self.consolidation_threshold = consolidation_threshold

    def consolidate(
        self,
        memories: List[MemoryRecord],
        current_day: int,
        npc_id: str,
    ) -> List[MemoryRecord]:
        """
        Scans an NPC's memories and generates semantic insights.
        Returns the updated memory list with newly generated semantic beliefs included.
        """
        existing_semantic_keys = {
            m.metadata.get("semantic_group_id")
            for m in memories
            if m.tier == MemoryTier.SEMANTIC and m.metadata.get("semantic_group_id")
        }

        # 1. Group episodic memories by conflict_key
        conflict_groups: Dict[str, List[MemoryRecord]] = {}
        for m in memories:
            ck = m.metadata.get("conflict_key")
            if ck and m.status in {BeliefStatus.ACTIVE, BeliefStatus.CORROBORATED, BeliefStatus.SUPERSEDED}:
                conflict_groups.setdefault(ck, []).append(m)

        new_semantics: List[MemoryRecord] = []

        for ck, group in conflict_groups.items():
            group_key = f"resolved_conflict_{ck}"
            if group_key in existing_semantic_keys:
                continue

            active_claims = [m for m in group if m.status in {BeliefStatus.ACTIVE, BeliefStatus.CORROBORATED}]
            superseded_claims = [m for m in group if m.status == BeliefStatus.SUPERSEDED]

            # If there is a superseded accusation and an active exoneration, synthesize false-accusation semantic belief
            if superseded_claims and active_claims:
                best_active = max(active_claims, key=lambda m: m.confidence)
                summary = (
                    f"Factual consensus established: {best_active.summary} "
                    f"(previous contradictory claims superseded)."
                )
                consensus_feature = feature_key_for_claim(best_active.metadata.get("claim"))
                semantic_rec = MemoryRecord(
                    event_id=f"semantic-{uuid.uuid4().hex[:8]}",
                    npc_id=npc_id,
                    summary=summary,
                    event_type="semantic_consensus",
                    game_day=current_day,
                    tier=MemoryTier.SEMANTIC,
                    importance=0.92,
                    confidence=best_active.confidence,
                    status=BeliefStatus.ACTIVE,
                    source="consolidation",
                    tags=["semantic", "consensus", ck],
                    metadata={
                        "conflict_key": ck,
                        "semantic_group_id": group_key,
                        "derived_from": ",".join(m.event_id for m in group),
                        # without an explicit feature key this record is inert
                        # in the utility engine (see core/features.py)
                        **({"feature_key": consensus_feature} if consensus_feature else {}),
                    },
                )
                new_semantics.append(semantic_rec)

        # 2. Group positive trades or interactions by actor
        trade_groups: Dict[str, List[MemoryRecord]] = {}
        for m in memories:
            if "trade" in m.tags or "help" in m.tags:
                actor = m.tags[1] if len(m.tags) > 1 else "player"
                trade_groups.setdefault(actor, []).append(m)

        for actor, group in trade_groups.items():
            group_key = f"trust_trend_{actor}"
            if group_key in existing_semantic_keys:
                continue
            if len(group) >= self.consolidation_threshold:
                avg_confidence = sum(m.confidence for m in group) / len(group)
                summary = f"{actor.capitalize()} is established as a reliable and trusted partner."
                semantic_rec = MemoryRecord(
                    event_id=f"semantic-{uuid.uuid4().hex[:8]}",
                    npc_id=npc_id,
                    summary=summary,
                    event_type="semantic_reputation",
                    game_day=current_day,
                    tier=MemoryTier.SEMANTIC,
                    importance=0.82,
                    confidence=avg_confidence,
                    status=BeliefStatus.ACTIVE,
                    source="consolidation",
                    tags=["semantic", "reputation", actor],
                    metadata={
                        "semantic_group_id": group_key,
                        "target_actor": actor,
                        "interaction_count": str(len(group)),
                        "feature_key": "help",
                    },
                )
                new_semantics.append(semantic_rec)

        return list(memories) + new_semantics
