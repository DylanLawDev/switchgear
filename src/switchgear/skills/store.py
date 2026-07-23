import time
from pathlib import Path

from switchgear.skills.model import parse_skill
from switchgear.storage.base import Storage

COLLECTION = "skills"


class SkillStore:
    def __init__(self, storage: Storage):
        self._db = storage

    @staticmethod
    def validate(text: str) -> dict:
        return parse_skill(text)

    async def save(self, text: str, source: str, status: str | None = None) -> dict:
        doc = parse_skill(text)
        status = status or ("active" if source in {"repo", "owner"} else "pending")
        record = {**doc, "text": text, "status": status, "source": source,
                  "updated_at": time.time()}
        await self._db.put(COLLECTION, doc["name"], record)
        return record

    async def get(self, name: str) -> dict | None:
        return await self._db.get(COLLECTION, name)

    async def list(self) -> list[dict]:
        docs = await self._db.query(COLLECTION)
        docs.sort(key=lambda d: d["name"])
        return [{"name": d["name"], "description": d["description"],
                 "status": d["status"], "source": d["source"],
                 "schedule": d.get("schedule")} for d in docs]

    async def set_status(self, name: str, status: str) -> dict | None:
        doc = await self._db.get(COLLECTION, name)
        if doc is None:
            return None
        doc["status"] = status
        doc["updated_at"] = time.time()
        await self._db.put(COLLECTION, name, doc)
        return doc

    async def seed_dir(self, path: str, *, source: str = "repo") -> int:
        root = Path(path)
        if not root.exists():
            return 0
        count = 0
        for child in sorted(root.iterdir()):
            skill_file = child / "SKILL.md"
            if child.is_dir() and skill_file.exists():
                text = skill_file.read_text()
                name = parse_skill(text)["name"]
                if await self.get(name) is None:
                    await self.save(text, source=source)
                    count += 1
        return count
