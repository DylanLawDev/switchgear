"""Transactional SQLite storage for single-instance portable deployments."""

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from switchgear.storage.base import Storage

SCHEMA_VERSION = 1


class SQLiteStorage(Storage):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = db.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                db.execute("INSERT INTO schema_version(version) VALUES (0)")
                version = 0
            else:
                version = int(row["version"])
            if version < 1:
                db.execute(
                    """CREATE TABLE documents (
                         collection TEXT NOT NULL,
                         key TEXT NOT NULL,
                         document TEXT NOT NULL CHECK(json_valid(document)),
                         PRIMARY KEY(collection, key)
                       )"""
                )
                db.execute("UPDATE schema_version SET version = 1")
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema {version} is newer than supported {SCHEMA_VERSION}"
                )

    async def get(self, collection: str, key: str) -> dict | None:
        def run():
            with closing(self._connect()) as db:
                row = db.execute(
                    "SELECT document FROM documents WHERE collection=? AND key=?",
                    (collection, key),
                ).fetchone()
                return json.loads(row["document"]) if row else None

        return await asyncio.to_thread(run)

    async def put(self, collection: str, key: str, doc: dict) -> None:
        payload = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)

        def run():
            with closing(self._connect()) as db:
                db.execute(
                    """INSERT INTO documents(collection,key,document) VALUES(?,?,?)
                       ON CONFLICT(collection,key) DO UPDATE SET document=excluded.document""",
                    (collection, key, payload),
                )

        await asyncio.to_thread(run)

    async def delete(self, collection: str, key: str) -> None:
        def run():
            with closing(self._connect()) as db:
                db.execute(
                    "DELETE FROM documents WHERE collection=? AND key=?", (collection, key)
                )

        await asyncio.to_thread(run)

    async def query(self, collection: str, where: dict | None = None,
                    limit: int | None = None) -> list[dict]:
        def run():
            with closing(self._connect()) as db:
                rows = db.execute(
                    "SELECT key, document FROM documents WHERE collection=? ORDER BY rowid",
                    (collection,),
                ).fetchall()
            out = []
            for row in rows:
                doc = json.loads(row["document"])
                if where and any(doc.get(field) != value for field, value in where.items()):
                    continue
                out.append({**doc, "_id": row["key"]})
                if limit is not None and len(out) >= limit:
                    break
            return out

        return await asyncio.to_thread(run)

    async def compare_and_set(self, collection: str, key: str, expected: dict,
                              updates: dict) -> dict | None:
        def run():
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT document FROM documents WHERE collection=? AND key=?",
                    (collection, key),
                ).fetchone()
                if row is None:
                    db.rollback()
                    return None
                doc = json.loads(row["document"])
                if any(doc.get(field) != value for field, value in expected.items()):
                    db.rollback()
                    return None
                merged = {**doc, **updates}
                db.execute(
                    "UPDATE documents SET document=? WHERE collection=? AND key=?",
                    (json.dumps(merged, separators=(",", ":"), ensure_ascii=False),
                     collection, key),
                )
                db.commit()
                return merged
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

        return await asyncio.to_thread(run)
