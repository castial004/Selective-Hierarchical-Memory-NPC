import tempfile
from pathlib import Path
from npc_memory_project.core.models import MemoryRecord, MemoryTier, BeliefStatus, ActionScore, DecisionTrace
from npc_memory_project.persistence.sqlite_store import SQLiteMemoryStore

def test_sqlite_persistence_tiers_and_traces():
    with tempfile.TemporaryDirectory() as td:
        db_file = Path(td) / "test.db"
        store = SQLiteMemoryStore(db_file)

        m1 = MemoryRecord("m1", "mira", "Working thought", "thought", 1, MemoryTier.WORKING, 0.2, 0.9)
        m2 = MemoryRecord("m2", "mira", "Episodic theft", "theft", 1, MemoryTier.EPISODIC, 0.8, 0.95)
        m3 = MemoryRecord("m3", "mira", "Archived rumour", "rumour", 1, MemoryTier.ARCHIVE, 0.1, 0.5)

        store.upsert(m1)
        store.upsert(m2)
        store.upsert(m3)

        working = store.list_by_tier("mira", MemoryTier.WORKING)
        assert len(working) == 1
        assert working[0].event_id == "m1"

        episodic = store.list_by_tier("mira", MemoryTier.EPISODIC)
        assert len(episodic) == 1
        assert episodic[0].event_id == "m2"

        # Record decision trace
        score = ActionScore("apologise", 0.581, {"innocence": 0.42})
        trace = DecisionTrace("mira", "apologise", [score], ["m2"], {"day": "4"})
        store.record_trace(trace, game_day=4)

        traces = store.list_traces_for_npc("mira")
        assert len(traces) == 1
        assert traces[0]["selected_action"] == "apologise"
        assert traces[0]["action_scores"][0]["score"] == 0.581
