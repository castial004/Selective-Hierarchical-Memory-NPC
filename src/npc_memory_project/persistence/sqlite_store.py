import json
import sqlite3
from pathlib import Path
from typing import List

from npc_memory_project.core.models import (
    MemoryRecord,
    MemoryTier,
    BeliefStatus,
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
"""


class SQLiteMemoryStore:

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        conn = self._connect()

        try:
            conn.execute(SCHEMA)
            conn.commit()

        finally:
            conn.close()

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
            conn.close()

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
            conn.close()

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