import asyncio

from switchgear.storage.base import Storage


class FirestoreStorage(Storage):
    """Thin adapter over google-cloud-firestore. Uses default GCP credentials."""

    def __init__(self):
        from google.cloud import firestore

        self._db = firestore.Client()

    async def get(self, collection: str, key: str) -> dict | None:
        snap = await asyncio.to_thread(self._db.collection(collection).document(key).get)
        return snap.to_dict() if snap.exists else None

    async def put(self, collection: str, key: str, doc: dict) -> None:
        await asyncio.to_thread(self._db.collection(collection).document(key).set, doc)

    async def delete(self, collection: str, key: str) -> None:
        await asyncio.to_thread(self._db.collection(collection).document(key).delete)

    async def query(
        self, collection: str, where: dict | None = None, limit: int | None = None
    ) -> list[dict]:
        def _run() -> list[dict]:
            q = self._db.collection(collection)
            for f, v in (where or {}).items():
                q = q.where(field_path=f, op_string="==", value=v)
            if limit:
                q = q.limit(limit)
            return [{**s.to_dict(), "_id": s.id} for s in q.stream()]

        return await asyncio.to_thread(_run)

    async def compare_and_set(self, collection: str, key: str, expected: dict,
                              updates: dict) -> dict | None:
        def _run() -> dict | None:
            from google.cloud import firestore

            ref = self._db.collection(collection).document(key)
            transaction = self._db.transaction()

            @firestore.transactional
            def update(transaction):
                snapshot = ref.get(transaction=transaction)
                if not snapshot.exists:
                    return None
                doc = snapshot.to_dict()
                if any(doc.get(field) != value for field, value in expected.items()):
                    return None
                transaction.update(ref, updates)
                return {**doc, **updates}

            return update(transaction)

        return await asyncio.to_thread(_run)
