import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any

from npc_memory_project.core.models import (
    MemoryRecord,
    MemoryTier,
    BeliefStatus,
    DecisionTrace,
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
"""

class SQLiteMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._is_memory = (self.path == ":memory:")
        self._shared_conn = sqlite3.connect(":memory:") if self._is_memory else None
        self._init_db()

    def _connect(self):
        if self._is_memory:
            return self._shared_conn
        return sqlite3.connect(self.path)

    def _close(self, conn: sqlite3.Connection) -> None:
        if not self._is_memory:
            conn.close()

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            self._close(conn)

    def clear(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM memories")
            conn.execute("DELETE FROM decision_traces")
            conn.commit()
        finally:
            self._close(conn)

    def upsert(self, memory: MemoryRecord) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO memories (
                    event_id,
                    npc_id,
                    summary,
                    event_type,
                    game_day,
                    tier,
                    importance,
                    confidence,
                    status,
                    source,
                    tags_json,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def list_for_npc(self, npc_id: str) -> List[MemoryRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    event_id,
                    npc_id,
                    summary,
                    event_type,
                    game_day,
                    tier,
                    importance,
                    confidence,
                    status,
                    source,
                    tags_json,
                    metadata_json
                FROM memories
                WHERE npc_id = ?
                ORDER BY game_day ASC
                """,
                (npc_id,),
            ).fetchall()
        finally:
            self._close(conn)

        memories = []
        for row in rows:
            memory = MemoryRecord(
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
            memories.append(memory)
        return memories

    def list_by_tier(self, npc_id: str, tier: MemoryTier) -> List[MemoryRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    event_id,
                    npc_id,
                    summary,
                    event_type,
                    game_day,
                    tier,
                    importance,
                    confidence,
                    status,
                    source,
                    tags_json,
                    metadata_json
                FROM memories
                WHERE npc_id = ? AND tier = ?
                ORDER BY game_day ASC
                """,
                (npc_id, tier.value),
            ).fetchall()
        finally:
            self._close(conn)

        memories = []
        for row in rows:
            memories.append(
                MemoryRecord(
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
            )
        return memories

    def record_trace(self, trace: DecisionTrace, game_day: int) -> None:
        conn = self._connect()
        scores_data = [
            {"action": s.action, "score": s.score, "factors": s.factors}
            for s in trace.action_scores
        ]
        try:
            conn.execute(
                """
                INSERT INTO decision_traces (
                    npc_id,
                    selected_action,
                    game_day,
                    action_scores_json,
                    retrieved_memory_ids_json,
                    context_json
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
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT
                    trace_id,
                    npc_id,
                    selected_action,
                    game_day,
                    action_scores_json,
                    retrieved_memory_ids_json,
                    context_json,
                    created_at
                FROM decision_traces
                WHERE npc_id = ?
                ORDER BY trace_id DESC
                """,
                (npc_id,),
            ).fetchall()
        finally:
            self._close(conn)

        traces = []
        for row in rows:
            traces.append({
                "trace_id": row[0],
                "npc_id": row[1],
                "selected_action": row[2],
                "game_day": row[3],
                "action_scores": json.loads(row[4]),
                "retrieved_memory_ids": json.loads(row[5]),
                "context": json.loads(row[6]),
                "created_at": row[7],
            })
        return traces