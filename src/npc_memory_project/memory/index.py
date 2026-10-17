"""An incremental "hot set" of records a decision may use.

The long-horizon experiment produced a result that reads as a negative and is
actually a division of labour:

* Superseding, disputing, expiring and archiving records changes **no decision** --
  the tier filter and the status filter are mutually redundant, so either one alone
  reproduces every result (see ``docs/EVALUATION.md``).
* What that machinery *does* control is how much of the store still has to be
  considered. At day 120 of the retention experiment the store holds 243 records and
  exactly 7 are retrievable: the other 236 are archived or expired chatter no
  decision can ever reach.

The manager used to re-derive that exclusion on every call, scoring all 243 records
to keep 5. This index keeps the retrievable subset per NPC up to date instead, so a
decision scores the 7 and skips the 236.

Correctness contract
--------------------
* The predicate lives in :func:`npc_memory_project.memory.manager.is_retrievable`
  and is used by *both* the index and ``HierarchicalMemoryManager.retrieve``, so the
  two cannot disagree about what "retrievable" means.
* **Writes are keyed by** ``event_id``, like the SQLite store's primary key: an
  update replaces the record in place. An earlier version keyed by ``event_id`` in a
  plain dict and silently *dropped* duplicates, while a brute-force scan kept both --
  the benchmark's equivalence check caught it (the indexed path returned a different
  top-5). Now duplicates are counted in :meth:`stats` instead of being hidden, and
  a test plants one to make sure it stays visible.
* ``sync(memories)`` rebuilds from a full list; call it after bulk work.
  ``hot_validated(npc_id, memories)`` re-syncs when a count check fails, for callers
  that cannot guarantee the write hooks ran.
* ``hot()`` returns the internal list without copying, so the benchmark measures the
  real cost. Treat it as read-only.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from npc_memory_project.core.models import MemoryRecord
from npc_memory_project.memory.manager import is_retrievable


class RetrievalIndex:
    """Per-NPC partition with a retrievable subset kept up to date."""

    name = "retrieval index"

    def __init__(self) -> None:
        self._all: Dict[str, List[MemoryRecord]] = {}
        self._hot: Dict[str, List[MemoryRecord]] = {}
        self._position: Dict[str, Dict[str, int]] = {}
        self._duplicates = 0
        self.syncs = 0
        self.updates = 0

    # ------------------------------------------------------------ write path
    def note(self, record: MemoryRecord) -> None:
        """Insert or replace one record (the write hook)."""
        held = self._all.setdefault(record.npc_id, [])
        hot = self._hot.setdefault(record.npc_id, [])
        positions = self._position.setdefault(record.npc_id, {})

        previous = positions.get(record.event_id)
        if previous is None:
            positions[record.event_id] = len(held)
            held.append(record)
            if is_retrievable(record):
                hot.append(record)
        else:
            held[previous] = record
            # retrievability may have changed (a record can be superseded,
            # archived or exonerated in place), so rebuild just this NPC's hot list
            hot[:] = [m for m in hot if m.event_id != record.event_id]
            if is_retrievable(record):
                hot.append(record)
        self.updates += 1

    def note_all(self, records: Iterable[MemoryRecord]) -> None:
        for record in records:
            self.note(record)

    def note_removal(self, npc_id: str, event_id: str) -> None:
        """Drop one record by id from both the partition and the hot set."""
        held = self._all.get(npc_id)
        if held is None:
            return
        kept = [m for m in held if m.event_id != event_id]
        removed = len(held) - len(kept)
        if not removed:
            return
        self._all[npc_id] = kept
        self._hot[npc_id] = [m for m in self._hot.get(npc_id, [])
                             if m.event_id != event_id]
        self._position[npc_id] = {m.event_id: i for i, m in enumerate(kept)}
        self.updates += removed

    def sync(self, memories: Sequence[MemoryRecord]) -> None:
        """Rebuild from a full list. O(n) cheap predicates, no scoring."""
        self._all = {}
        self._hot = {}
        self._position = {}
        self._duplicates = 0
        for record in memories:
            positions = self._position.setdefault(record.npc_id, {})
            if record.event_id in positions:
                self._duplicates += 1
            self.note(record)
        self.syncs += 1

    # ------------------------------------------------------------- read path
    def hot(self, npc_id: str, include_disputed: bool = False) -> List[MemoryRecord]:
        """Retrievable records for one NPC. O(1) lookup, no copy."""
        if include_disputed:
            return self._all.get(npc_id, [])
        return self._hot.get(npc_id, [])

    def all_for(self, npc_id: str) -> List[MemoryRecord]:
        return list(self._all.get(npc_id, []))

    def hot_validated(self, npc_id: str, memories: Sequence[MemoryRecord],
                      include_disputed: bool = False) -> List[MemoryRecord]:
        """``hot``, but re-sync first if the store moved underneath the index."""
        expected = sum(1 for m in memories if m.npc_id == npc_id)
        if expected != len(self._all.get(npc_id, [])):
            self.sync(memories)
        return self.hot(npc_id, include_disputed=include_disputed)

    # ---------------------------------------------------------- diagnostics
    def stats(self) -> Dict[str, object]:
        return {
            "npcs": len(self._all),
            "records": sum(len(held) for held in self._all.values()),
            "retrievable": sum(len(held) for held in self._hot.values()),
            "duplicate_event_ids": self._duplicates,
            "syncs": self.syncs,
            "updates": self.updates,
        }
