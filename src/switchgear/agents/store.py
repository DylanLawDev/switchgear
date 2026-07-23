import logging
import time
from pathlib import Path

from switchgear.agents.model import AgentProfileError, parse_agent_profile
from switchgear.tools.base import ExecutionPolicy

COLLECTION = "agent-profiles"
logger = logging.getLogger(__name__)


class AgentProfileStore:
    def __init__(self, storage):
        self._db = storage

    async def save(self, text: str, source: str, status: str | None = None) -> dict:
        doc = parse_agent_profile(text)
        existing = await self.get(doc["name"])
        now = time.time()
        record = {
            **doc, "text": text, "source": source,
            "status": status or ("active" if source in {"repo", "owner"} else "pending"),
            "created_at": (existing or {}).get("created_at", now), "updated_at": now,
        }
        await self._db.put(COLLECTION, doc["name"], record)
        return record

    @staticmethod
    def validate(text: str) -> dict:
        return parse_agent_profile(text)

    async def get(self, name: str) -> dict | None:
        return await self._db.get(COLLECTION, name)

    async def list(self) -> list[dict]:
        docs = await self._db.query(COLLECTION)
        docs.sort(key=lambda d: d.get("name", ""))
        return [{k: d.get(k) for k in ("name", "description", "model_tier", "status",
                                       "source", "tools", "resources", "skills", "updated_at")}
                for d in docs]

    async def delete(self, name: str) -> bool:
        if await self.get(name) is None:
            return False
        await self._db.delete(COLLECTION, name)
        return True

    async def seed_dir(self, root: str, *, source: str = "repo") -> int:
        path = Path(root)
        if not path.exists():
            return 0
        count = 0
        for child in sorted(path.iterdir()):
            file = child / "AGENT.md"
            if not file.is_file():
                continue
            try:
                parsed = parse_agent_profile(file.read_text())
            except (OSError, AgentProfileError) as exc:
                logger.warning("skipping agent profile %s: %s", file, exc)
                continue
            if await self.get(parsed["name"]) is None:
                await self.save(file.read_text(), source=source)
                count += 1
        return count

    @staticmethod
    def policy(profile: dict | None) -> ExecutionPolicy:
        if profile is None:
            return ExecutionPolicy()
        return ExecutionPolicy(
            tools=None if profile.get("tools") is None else tuple(profile["tools"]),
            resources=(None if profile.get("resources") is None
                       else tuple(p.strip("/") for p in profile["resources"])),
            skills=None if profile.get("skills") is None else tuple(profile["skills"]),
        )
