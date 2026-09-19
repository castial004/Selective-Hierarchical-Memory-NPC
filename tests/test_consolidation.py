from npc_memory_project.core.models import MemoryRecord, MemoryTier, BeliefStatus
from npc_memory_project.memory.consolidation import SemanticConsolidator

def test_semantic_consolidation_from_resolved_conflict():
    old = MemoryRecord(
        "e1", "mira", "Player accused of theft", "theft_accusation", 1,
        MemoryTier.EPISODIC, 0.8, 0.6, status=BeliefStatus.SUPERSEDED,
        metadata={"conflict_key": "theft_case", "claim": "player_stole"}
    )
    new = MemoryRecord(
        "e2", "mira", "Guard proved Rohan stole", "innocence_verified", 3,
        MemoryTier.EPISODIC, 0.9, 0.95, status=BeliefStatus.ACTIVE,
        metadata={"conflict_key": "theft_case", "claim": "rohan_stole"}
    )
    consolidator = SemanticConsolidator()
    updated = consolidator.consolidate([old, new], current_day=4, npc_id="mira")

    semantic_records = [m for m in updated if m.tier == MemoryTier.SEMANTIC]
    assert len(semantic_records) == 1
    assert "Factual consensus" in semantic_records[0].summary
    assert semantic_records[0].metadata["conflict_key"] == "theft_case"

def test_semantic_consolidation_from_repeated_trades():
    t1 = MemoryRecord("t1", "mira", "Player traded herbs", "trade", 1, MemoryTier.WORKING, 0.4, 1.0, tags=["trade", "player"])
    t2 = MemoryRecord("t2", "mira", "Player traded potions", "trade", 2, MemoryTier.WORKING, 0.4, 1.0, tags=["trade", "player"])
    consolidator = SemanticConsolidator(consolidation_threshold=2)
    updated = consolidator.consolidate([t1, t2], current_day=3, npc_id="mira")

    semantic_records = [m for m in updated if m.tier == MemoryTier.SEMANTIC]
    assert len(semantic_records) == 1
    assert "trusted partner" in semantic_records[0].summary
