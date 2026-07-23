"""Parse and validate CHANNEL.md definitions (spec §3.1).

Frontmatter is data only, parsed fail-fast at seed time — mirroring
workflows/model.py. The triage route set parsed here is the CLOSED enum the
Phase 3 classifier output is validated against: model output can never add
a route, a workflow, or a send function outside these declared sets.
"""

import logging
import time
from pathlib import Path

import yaml

from switchgear.storage.base import Storage
from switchgear.workflows.model import NAME_RE, WorkflowParseError, parse_duration

COLLECTION = "channels"
TRANSPORTS = {"console"}
TIERS = {"bulk", "chat", "writing"}
ROUTES = {"file", "workflow_item", "draft_reply", "auto_ack"}

logger = logging.getLogger(__name__)


class ChannelParseError(Exception):
    pass


def poll_cron(seconds: float) -> str:
    """Map a poll interval to the 5-field cron string both schedulers consume
    (LocalScheduler stores it; CloudScheduler passes it as job["schedule"]).

    Only intervals that map onto a fixed-step `*/N` cron field WITHOUT
    truncation are accepted: sub-hour intervals whose minutes evenly divide
    60 (so the pattern realigns every hour — */5, */6, */10, ... but not
    */7), whole-hour intervals whose hours evenly divide 24 (*/1, */2, */3,
    */4, */6, */8, */12, but not */5), and whole-day intervals. The previous
    implementation floored e.g. 90m to hourly (`minutes // 60`), silently
    running at the wrong cadence — anything non-representable now raises
    instead of being coerced.
    """
    seconds = float(seconds)
    if seconds <= 0 or seconds % 60 != 0:
        raise ValueError(
            f"poll_interval {seconds}s must be a positive whole number of minutes")
    minutes = int(seconds // 60)
    if minutes < 60:
        if 60 % minutes != 0:
            raise ValueError(
                f"poll_interval {minutes}m does not evenly divide 60 minutes "
                "(cron */N would drift) — use a divisor of 60, e.g. 5m/6m/10m/15m/30m")
        return f"*/{minutes} * * * *"
    if minutes % 60 != 0:
        raise ValueError(
            f"poll_interval {minutes}m is not a whole number of hours")
    hours = minutes // 60
    if hours < 24:
        if 24 % hours != 0:
            raise ValueError(
                f"poll_interval {hours}h does not evenly divide 24 hours "
                "(cron */N would drift) — use a divisor of 24, e.g. 1h/2h/3h/4h/6h/12h")
        return f"0 */{hours} * * *"
    if hours % 24 != 0:
        raise ValueError(
            f"poll_interval {hours}h is not a whole number of days")
    return f"0 0 */{hours // 24} * *"


def _parse_triage(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ChannelParseError("triage must be a mapping")
    tier = raw.get("tier")
    if tier not in TIERS:
        raise ChannelParseError(
            f"triage.tier {tier!r} must be one of bulk, chat, writing")
    routes = raw.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise ChannelParseError("triage.routes must be a non-empty mapping")
    unknown = sorted(set(routes) - ROUTES)
    if unknown:
        raise ChannelParseError(f"triage.routes: unknown routes {unknown}")
    if "file" not in routes:
        raise ChannelParseError("triage.routes.file is required (the fallback route)")
    parsed = {}
    for rname, spec in routes.items():
        spec = spec or {}
        if not isinstance(spec, dict):
            raise ChannelParseError(f"triage.routes.{rname} must be a mapping")
        if rname == "workflow_item":
            wfs = spec.get("workflows")
            if not isinstance(wfs, list) or not wfs:
                raise ChannelParseError(
                    "triage.routes.workflow_item.workflows must be a non-empty list")
            for w in wfs:
                if not isinstance(w, str) or not NAME_RE.match(w):
                    raise ChannelParseError(
                        f"triage.routes.workflow_item: invalid workflow name {w!r}")
            spec = {"workflows": [str(w) for w in wfs]}
        elif rname == "draft_reply":
            if spec.get("tier") not in TIERS:
                raise ChannelParseError(
                    "triage.routes.draft_reply.tier must be one of bulk, chat, writing")
            spec = {"tier": str(spec["tier"])}
        elif rname == "auto_ack":
            fn = spec.get("send_function")
            if not fn or not isinstance(fn, str) or not NAME_RE.match(fn):
                raise ChannelParseError(
                    "triage.routes.auto_ack.send_function is required "
                    "(a valid send function name)")
            spec = {"send_function": fn}
        else:  # file
            spec = {}
        parsed[rname] = spec
    return {"tier": str(tier), "routes": parsed}


def parse_channel(text: str) -> dict:
    if not text.startswith("---"):
        raise ChannelParseError("missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ChannelParseError("unterminated frontmatter")
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        raise ChannelParseError(f"bad yaml: {e}") from None
    if not isinstance(meta, dict):
        raise ChannelParseError("frontmatter must be a mapping")

    if meta.get("schema_version") != 1:
        raise ChannelParseError("schema_version must be 1")
    name = meta.get("name")
    if not name or not NAME_RE.match(str(name)):
        raise ChannelParseError("invalid name (lowercase alphanumerics and dashes)")
    transport = meta.get("transport")
    if transport not in TRANSPORTS:
        raise ChannelParseError(
            f"unknown transport {transport!r} (use console)")
    workflow = meta.get("workflow")
    if not workflow or not isinstance(workflow, str):
        raise ChannelParseError("workflow is required")
    address = meta.get("address")
    if address is not None and not isinstance(address, str):
        raise ChannelParseError("address must be a string")
    try:
        poll_interval = parse_duration(meta.get("poll_interval"))
    except WorkflowParseError as e:
        raise ChannelParseError(f"poll_interval: {e}") from None
    try:
        poll_cron(poll_interval)
    except ValueError as e:
        raise ChannelParseError(f"poll_interval: {e}") from None

    return {
        "schema_version": 1,
        "name": str(name),
        "transport": str(transport),
        "workflow": workflow,
        "address": address,
        "poll_interval": poll_interval,
        "triage": _parse_triage(meta.get("triage")),
        "body": parts[2].lstrip("\n"),
    }


class ChannelStore:
    """Mirrors WorkflowStore: repo seeds are active, agent saves are pending,
    seed_dir inserts missing defs and refreshes changed repo defs while
    preserving status. Collection: "channels"."""

    def __init__(self, storage: Storage):
        self._db = storage

    @staticmethod
    def validate(text: str) -> dict:
        return parse_channel(text)

    async def save(self, text: str, source: str, status: str | None = None) -> dict:
        doc = parse_channel(text)
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
        return [{"name": d["name"], "transport": d["transport"],
                 "workflow": d["workflow"], "status": d["status"],
                 "source": d["source"]} for d in docs]

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
            ch_file = child / "CHANNEL.md"
            if not (child.is_dir() and ch_file.exists()):
                continue
            text = ch_file.read_text()
            try:
                doc = parse_channel(text)
            except ChannelParseError as e:
                logger.warning("skipping channel %s: %s", ch_file, e)
                continue
            name = doc["name"]
            existing = await self.get(name)
            if existing is None:
                await self.save(text, source=source)
                count += 1
            elif existing.get("source") == source and existing.get("text") != text:
                record = {**existing, **doc, "text": text,
                          "status": existing["status"], "source": existing["source"],
                          "updated_at": time.time()}
                await self._db.put(COLLECTION, name, record)
                count += 1
        return count


async def validate_channel_refs(channel: dict, *, workflow_store,
                                send_function_names: set[str] | None = None,
                                send_functions: dict | None = None,
                                ) -> list[str]:
    """Reference checks that can only run after seeding (spec §3.1): the
    channel's workflow must exist and be active; workflow_item allowlist
    entries must exist; the auto_ack send function must exist when a name set
    is supplied (None = skip; Phase 2 wires the real names). When
    send_functions (name -> function doc) is also supplied, the auto_ack
    target must additionally be gate:auto with recipient_rule
    reply_to_thread (spec §3.1) — auto-fired sends must never bypass the
    gate/recipient safety a human-approved send function would enforce.
    Returns a list of problems — callers log + skip activation, never crash
    startup."""
    problems: list[str] = []
    workflow = channel.get("workflow")
    if not workflow:
        problems.append("channel has no workflow")
    else:
        wf = await workflow_store.get(workflow)
        if wf is None:
            problems.append(f"workflow {workflow!r} not found")
        elif wf.get("status") != "active":
            problems.append(f"workflow {workflow!r} is not active")
    routes = (channel.get("triage") or {}).get("routes") or {}
    for target in (routes.get("workflow_item") or {}).get("workflows", []):
        if await workflow_store.get(target) is None:
            problems.append(f"workflow_item target {target!r} not found")
    if send_function_names is not None and "auto_ack" in routes:
        fn = (routes.get("auto_ack") or {}).get("send_function")
        if not fn:
            problems.append("auto_ack route has no send_function")
        elif fn not in send_function_names:
            problems.append(f"auto_ack send function {fn!r} not found")
        elif send_functions is not None:
            fn_doc = send_functions.get(fn) or {}
            rule = (fn_doc.get("recipient_rule") or {}).get("type")
            if fn_doc.get("gate") != "auto" or rule != "reply_to_thread":
                problems.append(
                    f"auto_ack send function {fn!r} must be gate:auto with "
                    "recipient_rule reply_to_thread")
    return problems
