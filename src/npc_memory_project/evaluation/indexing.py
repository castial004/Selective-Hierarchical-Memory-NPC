"""Does the retrieval index actually pay for itself?

The retention experiment established that the lifecycle's exclusions never change a
decision and always shrink the set a decision could have used. That makes the
exclusion machinery a *cost* mechanism, and this measures the cost it controls.

Three stores, chosen to separate the two effects the index can have:

* **archived-heavy** -- the day-120 store from ``longitudinal.py``: 243 records,
  7 retrievable. The index wins here by skipping expired chatter.
* **multi-NPC** -- 60 NPCs x 50 records each. Wins here by partitioning: a decision
  for one NPC never looks at the other 2,950 records.
* **deep-history** -- one NPC, 4,800 records, most of them still retrievable. The
  index barely helps, and that is reported rather than hidden: if the hot set is
  the whole store, there is nothing to skip.

Every run asserts that the indexed retrieval returns *the same records* as the
brute-force scan. A speedup that changes the answer is not a speedup.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from npc_memory_project.core.models import MemoryRecord
from npc_memory_project.evaluation.stats import summarise
from npc_memory_project.memory.index import RetrievalIndex
from npc_memory_project.memory.manager import HierarchicalMemoryManager


@dataclass
class IndexResult:
    store: str
    npcs: int
    records: int
    retrievable_for_npc: int
    median_ms: float
    p95_ms: float
    indexed_median_ms: float
    indexed_p95_ms: float
    identical: bool

    @property
    def speedup(self) -> float:
        if self.indexed_median_ms <= 0:
            return float("inf")
        return self.median_ms / self.indexed_median_ms

    @property
    def skipped(self) -> int:
        return max(0, self.records - self.retrievable_for_npc)


def _archived_heavy_store() -> Tuple[List[MemoryRecord], str, int, int]:
    """The day-120 store from the retention experiment."""
    from npc_memory_project.evaluation.longitudinal import Timeline

    timeline = Timeline(name="exonerated", horizon=120)
    timeline.build()
    return timeline.store, "mira", 120, 1


def _multi_npc_store(npcs: int = 60, per_npc: int = 50):
    from npc_memory_project.evaluation.scaling import _synthetic_memories

    rng = random.Random(20260920)
    store: List[MemoryRecord] = []
    for index in range(npcs):
        npc_id = "mira" if index == 0 else f"npc_{index}"
        store.extend(_synthetic_memories(npc_id, per_npc, current_day=30, rng=rng))
    return store, "mira", 30, npcs


def _deep_history_store(per_npc: int = 4800):
    from npc_memory_project.evaluation.scaling import _synthetic_memories

    rng = random.Random(20260920)
    return _synthetic_memories("mira", per_npc, current_day=30, rng=rng), "mira", 30, 1


def benchmark_store(
    store: Sequence[MemoryRecord],
    npc_id: str,
    current_day: int,
    npcs: int,
    *,
    label: str,
    iterations: int = 200,
    top_k: int = 5,
) -> IndexResult:
    manager = HierarchicalMemoryManager()
    index = RetrievalIndex()
    index.sync(store)                                  # once, after the write burst

    held = sum(1 for m in store if m.npc_id == npc_id)

    # equivalence first: an index that changes the answer is not an optimisation
    baseline_top = [m.event_id for m in manager.retrieve(
        store, npc_id=npc_id, current_day=current_day, top_k=top_k)]
    indexed_top = [m.event_id for m in manager.retrieve(
        index.hot(npc_id), npc_id=npc_id, current_day=current_day, top_k=top_k)]
    identical = baseline_top == indexed_top

    baseline_times: List[float] = []
    indexed_times: List[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        manager.retrieve(store, npc_id=npc_id, current_day=current_day, top_k=top_k)
        baseline_times.append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        manager.retrieve(index.hot(npc_id), npc_id=npc_id, current_day=current_day,
                         top_k=top_k)
        indexed_times.append((time.perf_counter() - start) * 1000)

    base = summarise(baseline_times)
    fast = summarise(indexed_times)
    return IndexResult(
        store=label,
        npcs=npcs,
        records=len(store),
        retrievable_for_npc=len(index.hot(npc_id)),
        median_ms=base["median"],
        p95_ms=base["p95"],
        indexed_median_ms=fast["median"],
        indexed_p95_ms=fast["p95"],
        identical=identical,
    )


def run_indexing_experiment(iterations: int = 200) -> List[IndexResult]:
    stores = [
        (*_archived_heavy_store(), "archived-heavy (day 120)"),
        (*_multi_npc_store(), "multi-NPC (60 x 50)"),
        (*_deep_history_store(), "deep history (1 x 4800)"),
    ]
    return [
        benchmark_store(store, npc_id, day, npcs, label=label, iterations=iterations)
        for store, npc_id, day, npcs, label in stores
    ]


def print_indexing_report(results: Sequence[IndexResult]) -> None:
    print("\nRetrieval index -- latency per decision\n")
    print(f"  {'store':<26}{'records':>9}{'hot':>6}{'skipped':>9}"
          f"{'median':>10}{'indexed':>10}{'speedup':>9}{'same?':>7}")
    print("  " + "-" * 86)
    for row in results:
        print(f"  {row.store:<26}{row.records:>9}{row.retrievable_for_npc:>6}"
              f"{row.skipped:>9}{row.median_ms:>9.3f}m{row.indexed_median_ms:>9.3f}m"
              f"{row.speedup:>8.1f}x{'yes' if row.identical else 'NO':>7}")
    print()
