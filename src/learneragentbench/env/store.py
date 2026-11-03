"""SQLite-backed record store with versioning, soft deletes, full history, snapshots.

Tables
    records(kind, id, json, version, created_at, updated_at, deleted)   current rows
    history(seq, kind, id, version, op, at, json)                        every create/update/delete
    kv(key, value)                                                       small typed metadata (clock, skill graph, outages)

Rows are Pydantic records serialised as JSON; queries are done in Python because
a task's world holds at most a few thousand rows. Optimistic concurrency: an
update must carry the version it read, otherwise ``ConflictError``.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from ..schema.common import Record

R = TypeVar("R", bound=Record)


class StoreError(Exception):
    pass


class NotFoundError(StoreError):
    pass


class ConflictError(StoreError):
    pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    kind TEXT NOT NULL, id TEXT NOT NULL, json TEXT NOT NULL, version INTEGER NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, id));
CREATE TABLE IF NOT EXISTS history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, id TEXT NOT NULL,
    version INTEGER NOT NULL, op TEXT NOT NULL, at TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS history_kind_id ON history(kind, id);
"""


class Store:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(path) if path else ":memory:"
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ records
    def put(self, rec: Record, *, now: datetime) -> Record:
        kind = type(rec).kind
        row = self.conn.execute(
            "SELECT deleted FROM records WHERE kind=? AND id=?", (kind, rec.id)
        ).fetchone()
        if row is not None and not row[0]:
            raise ConflictError(f"{kind}/{rec.id} already exists")
        rec = rec.model_copy(update={"created_at": now, "updated_at": now, "version": 1, "deleted": False})
        payload = rec.model_dump_json()
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO records(kind,id,json,version,created_at,updated_at,deleted) "
                "VALUES (?,?,?,?,?,?,0)",
                (kind, rec.id, payload, 1, now.isoformat(), now.isoformat()),
            )
            self._hist(kind, rec.id, 1, "create", now, payload)
        return rec

    def get(self, cls: type[R], rec_id: str, *, include_deleted: bool = False) -> R | None:
        row = self.conn.execute(
            "SELECT json, deleted FROM records WHERE kind=? AND id=?", (cls.kind, rec_id)
        ).fetchone()
        if row is None or (row[1] and not include_deleted):
            return None
        return cls.model_validate_json(row[0])

    def require(self, cls: type[R], rec_id: str) -> R:
        rec = self.get(cls, rec_id)
        if rec is None:
            raise NotFoundError(f"{cls.kind}/{rec_id} not found")
        return rec

    def list(self, cls: type[R], *, include_deleted: bool = False) -> list[R]:
        q = "SELECT json FROM records WHERE kind=?" + ("" if include_deleted else " AND deleted=0")
        rows = self.conn.execute(q + " ORDER BY rowid", (cls.kind,)).fetchall()
        return [cls.model_validate_json(r[0]) for r in rows]

    def update(self, rec: Record, *, now: datetime, expected_version: int | None = None) -> Record:
        kind = type(rec).kind
        row = self.conn.execute(
            "SELECT version, deleted FROM records WHERE kind=? AND id=?", (kind, rec.id)
        ).fetchone()
        if row is None or row[1]:
            raise NotFoundError(f"{kind}/{rec.id} not found")
        current = int(row[0])
        expected = rec.version if expected_version is None else expected_version
        if expected != current:
            raise ConflictError(f"{kind}/{rec.id}: version {expected} is stale (current {current})")
        rec = rec.model_copy(update={"version": current + 1, "updated_at": now})
        payload = rec.model_dump_json()
        with self.conn:
            self.conn.execute(
                "UPDATE records SET json=?, version=?, updated_at=? WHERE kind=? AND id=?",
                (payload, rec.version, now.isoformat(), kind, rec.id),
            )
            self._hist(kind, rec.id, rec.version, "update", now, payload)
        return rec

    def delete(self, cls: type[Record], rec_id: str, *, now: datetime) -> Record:
        rec = self.require(cls, rec_id)
        rec = rec.model_copy(update={"deleted": True, "version": rec.version + 1, "updated_at": now})
        payload = rec.model_dump_json()
        with self.conn:
            self.conn.execute(
                "UPDATE records SET json=?, version=?, updated_at=?, deleted=1 WHERE kind=? AND id=?",
                (payload, rec.version, now.isoformat(), cls.kind, rec_id),
            )
            self._hist(cls.kind, rec_id, rec.version, "delete", now, payload)
        return rec

    def history(self, cls: type[Record], rec_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT version, op, at, json FROM history WHERE kind=? AND id=? ORDER BY seq",
            (cls.kind, rec_id),
        ).fetchall()
        return [{"version": r[0], "op": r[1], "at": r[2], "record": json.loads(r[3])} for r in rows]

    def count(self, cls: type[Record]) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM records WHERE kind=? AND deleted=0", (cls.kind,)).fetchone()[0])

    def iter_all(self) -> Iterator[tuple[str, str, dict[str, Any]]]:
        for kind, rid, js in self.conn.execute("SELECT kind, id, json FROM records WHERE deleted=0"):
            yield kind, rid, json.loads(js)

    def _hist(self, kind: str, rid: str, version: int, op: str, at: datetime, payload: str) -> None:
        self.conn.execute(
            "INSERT INTO history(kind,id,version,op,at,json) VALUES (?,?,?,?,?,?)",
            (kind, rid, version, op, at.isoformat(), payload),
        )

    # ----------------------------------------------------------------------- kv
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row[0])

    def kv_set(self, key: str, value: Any) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO kv(key, value) VALUES (?, ?)", (key, json.dumps(value))
            )

    def kv_keys(self, prefix: str = "") -> list[str]:
        rows = self.conn.execute("SELECT key FROM kv WHERE key LIKE ? ORDER BY key", (prefix + "%",))
        return [r[0] for r in rows.fetchall()]

    # ---------------------------------------------------------------- snapshots
    def snapshot_bytes(self) -> bytes:
        return self.conn.serialize()

    def restore_bytes(self, data: bytes) -> None:
        self.conn.deserialize(data)

    def snapshot_to(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        dest = sqlite3.connect(str(path))
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
        return path

    @classmethod
    def from_snapshot(cls, path: str | Path, *, into: str | Path | None = None) -> Store:
        store = cls(into)
        src = sqlite3.connect(str(path))
        try:
            src.backup(store.conn)
        finally:
            src.close()
        return store

    def close(self) -> None:
        self.conn.close()
