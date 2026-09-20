"""Tests for the retrieval index and the long-horizon retention experiment.

The index exists to cash in a measured fact: the lifecycle's exclusions never
change a decision but always shrink the set a decision could use (7 of 243 records
are reachable at day 120). Skipping the rest is only safe if the index returns
*exactly* what the brute-force filter would, so that equivalence is the first thing
tested here -- and the test that plants duplicate ``event_id``s exists because the
first implementation silently deduplicated them and the benchmark caught it.
"""

from __future__ import annotations

from npc_memory_project.core.models import (
    BeliefStatus, MemoryRecord, MemoryTier,
)
from npc_memory_project.evaluation.baselines import RecencyOnly
from npc_memory_project.evaluation.indexing import (
    _archived_heavy_store, _multi_npc_store, benchmark_store, run_indexing_experiment,
)
from npc_memory_project.evaluation.longitudinal import (
    PROBE_DAYS, Timeline, run_longitudinal_experiment,
)
from npc_memory_project.memory.index import RetrievalIndex
from npc_memory_project.memory.manager import HierarchicalMemoryManager, is_retrievable


def _record(event_id: str, npc_id: str = "mira", *, day: int = 1,
            status: BeliefStatus = BeliefStatus.ACTIVE,
            tier: MemoryTier = MemoryTier.EPISODIC,
            importance: float = 0.8, confidence: float = 0.9,
            event_type: str = "trade") -> MemoryRecord:
    return MemoryRecord(
        event_id=event_id, npc_id=npc_id, summary=f"record {event_id}",
        event_type=event_type, game_day=day, tier=tier, importance=importance,
        confidence=confidence, status=status, source="direct", tags=[], metadata={},
    )


# ------------------------------------------------------------- the predicate
def test_is_retrievable_matches_the_manager_filter():
    manager = HierarchicalMemoryManager()
    records = [
        _record("a"),
        _record("b", status=BeliefStatus.SUPERSEDED),
        _record("c", status=BeliefStatus.DISPUTED),
        _record("d", status=BeliefStatus.EXPIRED),
        _record("e", tier=MemoryTier.ARCHIVE),
        _record("f", npc_id="arun"),
    ]
    by_manager = {m.event_id for m in manager.retrieve(records, npc_id="mira",
                                                       current_day=1, top_k=10)}
    by_predicate = {m.event_id for m in records
                    if m.npc_id == "mira" and is_retrievable(m)}
    assert by_manager == by_predicate == {"a"}

    with_disputed = manager.retrieve(records, npc_id="mira", current_day=1, top_k=10,
                                     include_disputed=True)
    assert {m.event_id for m in with_disputed} == {"a", "c"}


# -------------------------------------------------------------- equivalence
def test_index_matches_brute_force_on_a_real_store():
    store, npc_id, day, _ = _archived_heavy_store()
    manager = HierarchicalMemoryManager()
    index = RetrievalIndex()
    index.sync(store)

    baseline = [m.event_id for m in manager.retrieve(store, npc_id=npc_id,
                                                     current_day=day, top_k=5)]
    indexed = [m.event_id for m in manager.retrieve(index.hot(npc_id), npc_id=npc_id,
                                                    current_day=day, top_k=5)]
    assert baseline == indexed
    assert len(index.hot(npc_id)) < len([m for m in store if m.npc_id == npc_id])


def test_index_matches_brute_force_across_many_npcs():
    store, npc_id, day, npcs = _multi_npc_store(npcs=12, per_npc=20)
    manager = HierarchicalMemoryManager()
    index = RetrievalIndex()
    index.sync(store)

    for target in ("mira", "npc_3", "npc_9"):
        baseline = [m.event_id for m in manager.retrieve(store, npc_id=target,
                                                         current_day=day, top_k=5)]
        indexed = [m.event_id for m in manager.retrieve(index.hot(target),
                                                        npc_id=target,
                                                        current_day=day, top_k=5)]
        assert baseline == indexed, target


def test_duplicate_event_ids_are_reported_not_swallowed():
    """The bug the benchmark caught: a dict keyed by event_id dropped one of them."""
    a = _record("dup", importance=0.9)
    b = _record("dup", importance=0.1)
    index = RetrievalIndex()
    index.sync([a, b])
    assert index.stats()["duplicate_event_ids"] == 1
    # the write path is upsert semantics (a store keys on event_id), so the
    # partition holds one record -- and says so, rather than hiding the collision
    assert len(index.all_for("mira")) == 1
    assert index.all_for("mira")[0].event_id == "dup"
    assert index.all_for("mira")[0].importance == 0.1      # last write wins


# ------------------------------------------------------------------ updates
def test_updating_a_record_moves_it_out_of_the_hot_set():
    record = _record("theft", event_type="theft_accusation")
    index = RetrievalIndex()
    index.note(record)
    assert [m.event_id for m in index.hot("mira")] == ["theft"]

    from dataclasses import replace as dc_replace

    superseded = dc_replace(record, status=BeliefStatus.SUPERSEDED)
    index.note(superseded)
    assert index.hot("mira") == []
    assert len(index.all_for("mira")) == 1          # still in the store, just cold

    archived = dc_replace(record, tier=MemoryTier.ARCHIVE)
    index.note(archived)
    assert index.hot("mira") == []
    assert index.all_for("mira")[0].tier == MemoryTier.ARCHIVE


def test_removal_and_validated_lookup_recover_from_drift():
    first = _record("a")
    index = RetrievalIndex()
    index.note(first)
    store = [first, _record("b"), _record("c")]
    # the store grew without the hook running: hot_validated must notice and resync
    assert {m.event_id for m in index.hot_validated("mira", store)} == {"a", "b", "c"}

    index.note_removal("mira", "b")
    assert {m.event_id for m in index.hot("mira")} == {"a", "c"}


def test_index_stats_describe_the_store():
    store, npc_id, _, _ = _archived_heavy_store()
    index = RetrievalIndex()
    index.sync(store)
    stats = index.stats()
    assert stats["records"] == len(store)
    assert stats["npcs"] == 1
    assert stats["retrievable"] < stats["records"] / 10      # the point of the index
    assert stats["duplicate_event_ids"] == 0                 # fixture is well-formed


# --------------------------------------------------------------- benchmark
def test_benchmark_is_only_reported_when_it_is_equivalent():
    store, npc_id, day, npcs = _multi_npc_store(npcs=10, per_npc=20)
    result = benchmark_store(store, npc_id, day, npcs, label="test", iterations=10)
    assert result.identical is True
    assert result.retrievable_for_npc < result.records
    assert result.speedup > 0


def test_indexing_experiment_covers_every_store_type():
    results = run_indexing_experiment(iterations=10)
    labels = {r.store for r in results}
    assert labels == {"archived-heavy (day 120)", "multi-NPC (60 x 50)",
                      "deep history (1 x 4800)"}
    assert all(r.identical for r in results)
    assert all(r.skipped > 0 for r in results)


# ------------------------------------------------------------- longitudinal
def test_retention_over_120_days():
    """Timeline A keeps the exoneration; timeline B keeps the accusation."""
    report = run_longitudinal_experiment(probe_days=(5, 20, 60, 120))
    scores = report["retention"]["SHM (this architecture)"]
    assert scores["exonerated_accuracy"] == 1.0
    assert scores["accused_accuracy"] == 1.0
    assert scores["exonerated_decisive_in_k"] == 1.0
    assert scores["accused_decisive_in_k"] == 1.0


def test_recency_only_forgets_everything_and_still_looks_right_on_one_timeline():
    """The methodological finding: accuracy alone would have flattered it.

    recency-only scores 100% on the exoneration timeline while never retrieving the
    decisive record -- it answers "warm" because it has no signal at all. The
    decisive-in-top-k column is what exposes that, so it is asserted here.
    """
    report = run_longitudinal_experiment(probe_days=(5, 20, 60, 120))
    scores = report["retention"]["recency only"]     # the name in the report table
    assert scores["exonerated_accuracy"] == 1.0
    assert scores["exonerated_decisive_in_k"] == 0.0
    assert scores["accused_accuracy"] == 0.0


def test_the_archive_tier_is_redundant_with_belief_status():
    """Measured, not asserted from theory: every archived record is also excluded.

    The lifecycle only archives records it has already superseded or expired, so the
    ARCHIVE tier filter excludes a subset of what the status filter excludes. That is
    why removing tiers changes nothing -- documented in docs/EVALUATION.md.
    """
    timeline = Timeline(name="exonerated", horizon=60)
    timeline.build()
    last = timeline.snapshots[-1]
    assert last.archived_total > 0
    assert last.tier_redundancy == 1.0
    assert last.by_status.get("expired", 0) + last.by_status.get("superseded", 0) \
        >= last.archived_total


def test_lifecycle_work_shrinks_the_reachable_set():
    """The cost half of the finding the index exploits."""
    timeline = Timeline(name="exonerated", horizon=120)
    timeline.build()
    index = RetrievalIndex()
    index.sync(timeline.store)
    stats = index.stats()
    assert stats["records"] == 243
    assert stats["retrievable"] == 7
    assert PROBE_DAYS[-1] == 120


def test_simulation_index_stays_consistent_with_its_store():
    """The wired-in path, not just the benchmark path."""
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    from npc_memory_project.simulation.town_simulation import TownSimulation

    sim = TownSimulation(":memory:")
    manager = HierarchicalMemoryManager()
    for _ in range(4):
        sim.advance_day()

    for npc_id in ("mira", "kael", "rohan"):
        held = sim.store.list_for_npc(npc_id)
        brute = {m.event_id for m in manager.retrieve(
            held, npc_id=npc_id, current_day=sim.world.game_day, top_k=99)}
        indexed = {m.event_id for m in sim.retrievable_for(npc_id, held)}
        assert indexed == brute, npc_id
        # what the index hands over is already filtered, so the decision path
        # never scores archived history
        assert all(is_retrievable(m) for m in sim.retrievable_for(npc_id, held))
