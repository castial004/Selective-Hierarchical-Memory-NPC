"""SQLite persistence for memory records and decision traces.

v0.2.1 changes
-------------
* **Thread safety.** A ``":memory:"`` store keeps one shared connection. That
  connection was created on the importing thread with the default
  ``check_same_thread=True``, so the *first* request served by a second thread
  raised ``sqlite3.ProgrammingError``. The confirmed trigger was swapping
  ``HTTPServer`` for ``ThreadingHTTPServer`` in ``web/server.py`` -- i.e. the
  shipped simulator crashed the moment it was made concurrent. The shared
  connection is now opened with ``check_same_thread=False`` and every public
  operation is serialised by an ``RLock``.
* **No duplicated row mapping.** ``list_for_npc`` and ``list_by_tier`` shared a
  25-line copy-pasted row->record block; both now use ``_row_to_memory``.
* ``close()`` releases the shared in-memory connection.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from npc_memory_project.core.models import (
    BeliefStatus,
    DecisionTrace,
    MemoryRecord,
    MemoryTier,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    event_id TEXT PRIMARY KEY,
    npc_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    event_type TEXT NOT NULL,
    game_day INTEGER NOT NULL,
    tier TEXT NOT NULL,
    importance REAL NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_npc ON memories(npc_id);
CREATE INDEX IF NOT EXISTS idx_memories_npc_tier ON memories(npc_id, tier);

CREATE TABLE IF NOT EXISTS decision_traces (
    trace_id INTEGER PRIMARY KEY AUTOINCREMENT,
    npc_id TEXT NOT NULL,
    selected_action TEXT NOT NULL,
    game_day INTEGER NOT NULL,
    action_scores_json TEXT NOT NULL,
    retrieved_memory_ids_json TEXT NOT NULL,
    context_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_traces_npc ON decision_traces(npc_id);
"""

_COLUMNS = (
    "event_id, npc_id, summary, event_type, game_day, tier, importance, "
    "confidence, status, source, tags_json, metadata_json"
)


class SQLiteMemoryStore:
    """Small SQLite-backed store. Safe to share across threads."""

    def __init__(self, path: Union[str, Path] = ":memory:") -> None:
        self.path = str(path)
        self._is_memory = self.path == ":memory:"
        self._lock = threading.RLock()
        self._shared_conn: Optional[sqlite3.Connection] = None
        if self._is_memory:
            self._shared_conn = sqlite3.connect(
                ":memory:", check_same_thread=False
            )
        self._init_db()

    # ------------------------------------------------------------- plumbing
    def _connect(self) -> sqlite3.Connection:
        if self._is_memory:
            assert self._shared_conn is not None
            return self._shared_conn
        return sqlite3.connect(self.path)

    def _close(self, conn: sqlite3.Connection) -> None:
        if not self._is_memory:
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
                conn.commit()
            finally:
                self._close(conn)

    def close(self) -> None:
        with self._lock:
            if self._shared_conn is not None:
                self._shared_conn.close()
                self._shared_conn = None

    def clear(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM memories")
                conn.execute("DELETE FROM decision_traces")
                conn.commit()
            finally:
                self._close(conn)

    @staticmethod
    def _row_to_memory(row: Any) -> MemoryRecord:
        return MemoryRecord(
            event_id=row[0],
            npc_id=row[1],
            summary=row[2],
            event_type=row[3],
            game_day=row[4],
            tier=MemoryTier(row[5]),
            importance=row[6],
            confidence=row[7],
            status=BeliefStatus(row[8]),
            source=row[9],
            tags=json.loads(row[10]),
            metadata=json.loads(row[11]),
        )

    # ------------------------------------------------------------ memories
    def upsert(self, memory: MemoryRecord) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO memories (
                        event_id, npc_id, summary, event_type, game_day, tier,
                        importance, confidence, status, source, tags_json,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        npc_id=excluded.npc_id,
                        summary=excluded.summary,
                        event_type=excluded.event_type,
                        game_day=excluded.game_day,
                        tier=excluded.tier,
                        importance=excluded.importance,
                        confidence=excluded.confidence,
                        status=excluded.status,
                        source=excluded.source,
                        tags_json=excluded.tags_json,
                        metadata_json=excluded.metadata_json
                    """,
                    (
                        memory.event_id,
                        memory.npc_id,
                        memory.summary,
                        memory.event_type,
                        memory.game_day,
                        memory.tier.value,
                        memory.importance,
                        memory.confidence,
                        memory.status.value,
                        memory.source,
                        json.dumps(memory.tags),
                        json.dumps(memory.metadata),
                    ),
                )
                conn.commit()
            finally:
                self._close(conn)

    def upsert_many(self, memories: List[MemoryRecord]) -> None:
        for memory in memories:
            self.upsert(memory)

    def list_for_npc(self, npc_id: str) -> List[MemoryRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM memories WHERE npc_id = ? ORDER BY game_day ASC",
                    (npc_id,),
                ).fetchall()
            finally:
                self._close(conn)
        return [self._row_to_memory(row) for row in rows]

    def list_by_tier(self, npc_id: str, tier: MemoryTier) -> List[MemoryRecord]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM memories "
                    "WHERE npc_id = ? AND tier = ? ORDER BY game_day ASC",
                    (npc_id, tier.value),
                ).fetchall()
            finally:
                self._close(conn)
        return [self._row_to_memory(row) for row in rows]

    def get(self, event_id: str) -> Optional[MemoryRecord]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    f"SELECT {_COLUMNS} FROM memories WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
            finally:
                self._close(conn)
        return self._row_to_memory(row) if row else None

    # --------------------------------------------------------------- traces
    def record_trace(self, trace: DecisionTrace, game_day: int) -> None:
        scores_data = [
            {"action": s.action, "score": s.score, "factors": s.factors}
            for s in trace.action_scores
        ]
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO decision_traces (
                        npc_id, selected_action, game_day, action_scores_json,
                        retrieved_memory_ids_json, context_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.npc_id,
                        trace.selected_action,
                        game_day,
                        json.dumps(scores_data),
                        json.dumps(trace.retrieved_memory_ids),
                        json.dumps(trace.context),
                    ),
                )
                conn.commit()
            finally:
                self._close(conn)

    def list_traces_for_npc(self, npc_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT trace_id, npc_id, selected_action, game_day,
                           action_scores_json, retrieved_memory_ids_json,
                           context_json, created_at
                    FROM decision_traces
                    WHERE npc_id = ?
                    ORDER BY trace_id DESC
                    """,
                    (npc_id,),
                ).fetchall()
            finally:
                self._close(conn)

        return [
            {
                "trace_id": row[0],
                "npc_id": row[1],
                "selected_action": row[2],
                "game_day": row[3],
                "action_scores": json.loads(row[4]),
                "retrieved_memory_ids": json.loads(row[5]),
                "context": json.loads(row[6]),
                "created_at": row[7],
            }
            for row in rows
        ]
