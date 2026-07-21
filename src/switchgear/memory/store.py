"""MemoryStore: agent-written durable knowledge (spec §5.1, §5.3).

Security invariant (spec §7.1): memory writes happen ONLY through the
methods here — key, status, timestamps, and supersession are set in code,
never taken from model output. Every write is audited. No hard eviction:
supersession at write time + soft archive; recency lives in the recall
score, never in a purge.
"""

import logging
import time
from typing import Callable
from uuid import uuid4

from switchgear.config import Settings
from switchgear.memory.embeddings import Embedder
from switchgear.storage.base import Storage

COLLECTION = "memories"

logger = logging.getLogger(__name__)


class MemoryError(Exception):
    """Validation/lookup failure. Intentionally shadows the builtin (which we
    never raise) inside this module — the name is part of the phase contract."""


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


class MemoryStore:
    def __init__(self, storage: Storage, embedder: Embedder, settings: Settings,
                 clock: Callable[[], float] = time.time):
        self._db = storage
        self._embedder = embedder
        self._s = settings
        self._now = clock

    # ---------- helpers ----------

    async def _audit(self, action: str, key: str, source: str = "owner") -> None:
        await self._db.put("audit", f"memory-{uuid4().hex}", {
            "action": action, "key": key, "source": source, "at": self._now()})

    async def _active(self, type: str) -> list[dict]:
        docs = await self._db.query(COLLECTION, where={"status": "active", "type": type})
        for doc in docs:
            doc.pop("_id", None)  # query() artifact; never persist it back
        return docs

    async def _supersede(self, old: dict, new_key: str) -> None:
        old["status"] = "superseded"
        old["superseded_by"] = new_key
        old["updated_at"] = self._now()
        await self._db.put(COLLECTION, old["key"], old)

    async def _find_active_matches(self, type: str, text: str,
                                    embedding: list[float] | None,
                                    exclude_key: str | None) -> list[dict]:
        """ACTIVE docs of the same type that match `text`/`embedding` under
        the supersession rule: cosine >= threshold for episodic, exact-
        normalized-text for core. `exclude_key` skips self-comparison for
        save()/update_text(); restore() passes None since the doc being
        restored is archived, not active, so it can't appear here anyway."""
        matches: list[dict] = []
        if type == "episodic":
            if embedding is None:
                return matches
            threshold = self._s.memory_supersede_threshold
            for old in await self._active("episodic"):
                if old["key"] == exclude_key or old.get("embedding") is None:
                    continue
                if cosine(embedding, old["embedding"]) >= threshold:
                    matches.append(old)
        elif type == "core":
            for old in await self._active("core"):
                if old["key"] == exclude_key:
                    continue
                if _normalize(old["text"]) == _normalize(text):
                    matches.append(old)
        return matches

    async def _supersede_matches(self, type: str, key: str, text: str,
                                  embedding: list[float] | None) -> None:
        """Mark other ACTIVE docs of the same type as superseded by `key`,
        using the same matching rule save() uses. Excludes `key` itself so
        callers (save, update_text) can share this against self-comparison."""
        for old in await self._find_active_matches(type, text, embedding, exclude_key=key):
            await self._supersede(old, key)

    # ---------- save ----------

    async def save(self, text: str, type: str, importance: int, source: str = "owner",
                   conversation_id: str | None = None) -> dict:
        text = (text or "").strip()
        if not text:
            raise MemoryError("memory text must be non-empty")
        if len(text) > self._s.memory_max_chars:
            raise MemoryError(f"memory text exceeds {self._s.memory_max_chars} characters")
        if type not in ("core", "episodic"):
            raise MemoryError("type must be 'core' or 'episodic'")
        importance = max(1, min(10, int(importance)))

        embedding = None
        if type == "episodic":
            try:
                embedding = (await self._embedder.embed([text], task="document"))[0]
            except Exception as e:  # degrade, never block a save (spec §5.2)
                logger.warning("embedding failed at save; storing null: %s", e)

        key = f"mem-{uuid4().hex[:12]}"
        now = self._now()
        doc = {
            "key": key, "text": text, "type": type, "status": "active",
            "importance": importance,
            "embedding": embedding,
            "embedding_model": (self._embedder.model_name
                                if embedding is not None else None),
            "source": source, "conversation_id": conversation_id,
            "superseded_by": None,
            "created_at": now, "updated_at": now,
            "last_accessed_at": None, "access_count": 0,
        }

        if type == "episodic" and embedding is not None:
            await self._supersede_matches("episodic", key, text, embedding)
        elif type == "core":
            await self._supersede_matches("core", key, text, None)

        await self._db.put(COLLECTION, key, doc)
        await self._audit("memory_save", key, source)
        return doc

    # ---------- recall ----------

    async def _backfill(self, docs: list[dict]) -> list[dict]:
        """One batch repair attempt for embeddings stored null after an
        embedder outage (spec §5.2). Failures stay null and are skipped."""
        missing = [d for d in docs if d.get("embedding") is None]
        if not missing:
            return docs
        try:
            vectors = await self._embedder.embed(
                [d["text"] for d in missing], task="document")
        except Exception as e:
            logger.warning("embedding backfill failed: %s", e)
            return docs
        for doc, vec in zip(missing, vectors):
            doc["embedding"] = vec
            doc["embedding_model"] = self._embedder.model_name
            doc["updated_at"] = self._now()
            await self._db.put(COLLECTION, doc["key"], doc)
        return docs

    async def recall(self, query: str, k: int | None = None,
                     floor: float | None = None) -> list[dict]:
        # NOTE (spec §5.7): brute-force, uncached cosine over the active
        # episodic set. Exact and sub-millisecond below tens of thousands of
        # memories; if the corpus ever approaches ~50K (or the deploy goes
        # multi-instance), migrate to a Firestore vector index per the spec —
        # docs already carry embedding + embedding_model, and the scoring
        # below stays as client-side re-ranking over the candidate set.
        k = self._s.memory_recall_k if k is None else k
        floor = self._s.memory_recall_floor if floor is None else floor
        try:
            query_vec = (await self._embedder.embed([query], task="query"))[0]
        except Exception as e:  # never block the caller on the embedder
            logger.warning("embedding failed at recall; skipping: %s", e)
            return []
        docs = await self._backfill(await self._active("episodic"))
        now = self._now()
        scored: list[tuple[float, dict]] = []
        for doc in docs:
            if doc.get("embedding") is None:
                continue
            cos = cosine(query_vec, doc["embedding"])
            if cos < floor:
                continue
            ref = doc.get("last_accessed_at") or doc.get("created_at") or now
            days = max(0.0, (now - ref) / 86400.0)
            recency = 0.5 ** (days / self._s.memory_recency_half_life_days)
            score = 0.70 * cos + 0.15 * recency + 0.15 * (doc["importance"] / 10)
            scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        out = []
        for _score, doc in scored[:k]:
            doc["last_accessed_at"] = now
            doc["access_count"] = int(doc.get("access_count") or 0) + 1
            await self._db.put(COLLECTION, doc["key"], doc)
            out.append({name: v for name, v in doc.items() if name != "embedding"})
        return out  # [] is a normal, first-class outcome

    async def core_block(self) -> str:
        docs = await self._active("core")
        if not docs:
            return ""
        docs.sort(key=lambda d: d.get("created_at") or 0, reverse=True)
        lines = [f"- {d['text']}" for d in docs]
        omitted = "(older standing instructions omitted — see /memories)"
        block = "\n".join(lines)
        while len(block) > self._s.memory_core_max_chars and len(lines) > 1:
            lines.pop()  # newest-first list: the tail is the oldest
            block = "\n".join([*lines, omitted])
        return block

    # ---------- lifecycle (UI-driven; spec §5.3, §5.8) ----------

    async def list(self, status: str | None = None, type: str | None = None) -> list[dict]:
        where: dict = {}
        if status:
            where["status"] = status
        if type:
            where["type"] = type
        docs = await self._db.query(COLLECTION, where=where or None)
        docs.sort(key=lambda d: d.get("created_at") or 0, reverse=True)
        return [{k: v for k, v in d.items() if k not in ("embedding", "_id")}
                for d in docs]

    async def update_text(self, key: str, text: str) -> dict | None:
        doc = await self._db.get(COLLECTION, key)
        if doc is None:
            return None
        # Editing superseded/archived docs is not a supported operation — the
        # UI only shows Edit on active rows; archived rows must restore first.
        if doc.get("status") != "active":
            return None
        text = (text or "").strip()
        if not text:
            raise MemoryError("memory text must be non-empty")
        if len(text) > self._s.memory_max_chars:
            raise MemoryError(f"memory text exceeds {self._s.memory_max_chars} characters")
        doc["text"] = text
        if doc["type"] == "episodic":
            try:
                doc["embedding"] = (await self._embedder.embed([text], task="document"))[0]
                doc["embedding_model"] = self._embedder.model_name
            except Exception as e:
                logger.warning("embedding failed at update; storing null: %s", e)
                doc["embedding"] = None
                doc["embedding_model"] = None
        doc["updated_at"] = self._now()
        await self._db.put(COLLECTION, key, doc)
        # Mirror save-time supersession: the freshly-edited text wins over
        # any other active doc it now matches (spec §5.3 hardening).
        await self._supersede_matches(doc["type"], key, text, doc.get("embedding"))
        await self._audit("memory_update_text", key)
        return {k: v for k, v in doc.items() if k != "embedding"}

    async def _set_status(self, key: str, status: str, action: str) -> dict | None:
        doc = await self._db.get(COLLECTION, key)
        if doc is None:
            return None
        doc["status"] = status
        doc["updated_at"] = self._now()
        await self._db.put(COLLECTION, key, doc)
        await self._audit(action, key)
        return {k: v for k, v in doc.items() if k != "embedding"}

    async def archive(self, key: str) -> dict | None:
        # archive reverses active ONLY (Task 4 reviewer follow-up): archiving
        # a superseded (or already-archived) doc, then restoring it, would
        # resurrect a duplicate-active memory via two calls — the same
        # invariant restore() enforces in the other direction.
        doc = await self._db.get(COLLECTION, key)
        if doc is None or doc.get("status") != "active":
            return None
        return await self._set_status(key, "archived", "memory_archive")

    async def restore(self, key: str) -> dict | None:
        # restore reverses archive ONLY (spec §5.3). Superseded docs must stay
        # superseded — reactivating one would recreate the duplicate-active
        # state supersession prevents, with a stale superseded_by pointer.
        doc = await self._db.get(COLLECTION, key)
        if doc is None or doc.get("status") != "archived":
            return None
        # Guard against the two-step duplicate: archive A, then save A' with
        # matching text/embedding (save-time supersession never saw A, since
        # it only scans ACTIVE docs). Reactivating A now would produce two
        # active docs violating the supersession invariant — refuse instead.
        if await self._find_active_matches(
                doc["type"], doc["text"], doc.get("embedding"), exclude_key=None):
            return None
        return await self._set_status(key, "active", "memory_restore")

    async def delete(self, key: str) -> bool:
        if await self._db.get(COLLECTION, key) is None:
            return False
        await self._db.delete(COLLECTION, key)
        await self._audit("memory_delete", key)
        return True
