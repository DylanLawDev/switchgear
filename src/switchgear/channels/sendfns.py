"""SendFunctionStore: validated CRUD for declarative send functions (spec §5.1).

Send functions are the ONLY way the agent reaches non-owner recipients. They
are pure data — typed params, string templates, a recipient rule, a gate —
so no code execution path exists from a definition (spec §8 invariant 7).
Every structural guarantee is enforced here at save time, fail-fast, so the
send path (send.py) can trust any stored doc. The load-bearing rule: cold
outbound (fixed / allowlist recipients) is structurally gate:approve —
save() rejects gate:auto for those rules, so an injected "send this to X"
can never ride an auto function to a new address.
"""

import re
import time
from uuid import uuid4

from switchgear.config import Settings
from switchgear.resources.store import NAME_RE  # same name grammar as resources
from switchgear.storage.base import Storage

COLLECTION = "send-functions"
BUILTIN_SLOTS = {"sender", "date"}  # code-derived render values (spec §4.3)
RESERVED_PARAMS = {"to", "message_key"} | BUILTIN_SLOTS
PARAM_TYPES = {"string", "number", "enum"}
RECIPIENT_TYPES = {"fixed", "reply_to_thread", "allowlist", "owner"}
AUTO_SAFE_RULES = {"reply_to_thread", "owner"}
GATES = {"approve", "auto"}
MAX_PARAM_CHARS = 2000
DEFAULT_RATE_LIMIT = 5  # per function per UTC day; 0 = no sends allowed
RESERVED_NAMES = {"builtin-reply"}  # the built-in reply rate counter's key

SLOT_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
# RFC-lite on purpose: enough to reject junk and header tricks; the
# provider is the real arbiter of deliverability.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class SendFunctionError(Exception):
    pass


def _validate_params_schema(raw: object) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SendFunctionError("params must be a mapping")
    params: dict = {}
    for pname, spec in raw.items():
        pname = str(pname)
        if not PARAM_NAME_RE.fullmatch(pname):
            raise SendFunctionError(f"bad param name {pname!r}")
        if pname in RESERVED_PARAMS:
            raise SendFunctionError(f"param name {pname!r} is reserved")
        if not isinstance(spec, dict) or spec.get("type") not in PARAM_TYPES:
            raise SendFunctionError(
                f"param {pname!r} needs a type: string|number|enum")
        if spec["type"] == "string":
            max_chars = spec.get("max_chars")
            if (not isinstance(max_chars, int) or isinstance(max_chars, bool)
                    or not 1 <= max_chars <= MAX_PARAM_CHARS):
                raise SendFunctionError(
                    f"param {pname!r}: string needs max_chars in "
                    f"1..{MAX_PARAM_CHARS}")
            params[pname] = {"type": "string", "max_chars": max_chars}
        elif spec["type"] == "number":
            params[pname] = {"type": "number"}
        else:
            values = spec.get("values")
            if (not isinstance(values, list) or not values
                    or not all(isinstance(v, str) and v for v in values)):
                raise SendFunctionError(
                    f"param {pname!r}: enum needs a non-empty list of "
                    "string values")
            params[pname] = {"type": "enum", "values": [str(v) for v in values]}
    return params


def _validate_template(field: str, template: object, allowed: set[str]) -> str:
    if not isinstance(template, str) or not template.strip():
        raise SendFunctionError(f"{field} is required")
    for slot in SLOT_RE.findall(template):
        if slot not in allowed:
            raise SendFunctionError(f"{field}: unknown slot {{{{{slot}}}}}")
    if "{{" in SLOT_RE.sub("", template):
        raise SendFunctionError(
            f"{field}: malformed placeholder (use {{{{name}}}})")
    return template


def _validate_recipient_rule(raw: object) -> dict:
    if not isinstance(raw, dict) or raw.get("type") not in RECIPIENT_TYPES:
        raise SendFunctionError(
            "recipient_rule.type must be fixed|reply_to_thread|allowlist|owner")
    rtype = raw["type"]
    if rtype == "fixed":
        address = str(raw.get("address") or "").strip().lower()
        if not EMAIL_RE.fullmatch(address):
            raise SendFunctionError("recipient_rule: fixed needs a valid address")
        return {"type": "fixed", "address": address}
    if rtype == "allowlist":
        raw_addresses = raw.get("addresses")
        if not isinstance(raw_addresses, list) or not raw_addresses:
            raise SendFunctionError(
                "recipient_rule: allowlist needs a non-empty addresses list")
        addresses = []
        for entry in raw_addresses:
            address = str(entry or "").strip().lower()
            if not EMAIL_RE.fullmatch(address):
                raise SendFunctionError(
                    f"recipient_rule: invalid address {entry!r}")
            addresses.append(address)
        return {"type": "allowlist", "addresses": addresses}
    return {"type": rtype}


class SendFunctionStore:
    def __init__(self, storage: Storage, settings: Settings):
        self._db = storage
        self._s = settings

    async def _audit(self, action: str, name: str, source: str) -> None:
        await self._db.put("audit", f"sendfn-{uuid4().hex}", {
            "action": action, "name": name, "source": source, "at": time.time()})

    async def save(self, doc: dict, source: str = "user") -> dict:
        if not isinstance(doc, dict):
            raise SendFunctionError("send function must be a mapping")
        name = str(doc.get("name") or "")
        if not NAME_RE.fullmatch(name):
            raise SendFunctionError(
                f"invalid name {name!r} (must match ^[a-z0-9][a-z0-9-]{{1,63}}$)")
        if name in RESERVED_NAMES:
            raise SendFunctionError(f"{name!r} is a reserved name")
        description = doc.get("description")
        if not isinstance(description, str) or not description.strip():
            raise SendFunctionError("description is required")
        params = _validate_params_schema(doc.get("params"))
        allowed = set(params) | BUILTIN_SLOTS
        subject_template = _validate_template(
            "subject_template", doc.get("subject_template"), allowed)
        body_template = _validate_template(
            "body_template", doc.get("body_template"), allowed)
        rule = _validate_recipient_rule(doc.get("recipient_rule"))
        gate = doc.get("gate", "approve")
        if gate not in GATES:
            raise SendFunctionError("gate must be approve or auto")
        if gate == "auto" and rule["type"] not in AUTO_SAFE_RULES:
            raise SendFunctionError(
                "gate:auto requires recipient_rule reply_to_thread or owner — "
                "cold outbound always needs approval")
        rate = doc.get("rate_limit_per_day", DEFAULT_RATE_LIMIT)
        if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
            raise SendFunctionError(
                "rate_limit_per_day must be an int >= 0 (0 = no sends allowed)")
        enabled = doc.get("enabled", True)
        if not isinstance(enabled, bool):
            raise SendFunctionError("enabled must be a boolean")

        existing = await self._db.get(COLLECTION, name)
        now = time.time()
        record = {
            "name": name, "description": description.strip(), "params": params,
            "subject_template": subject_template, "body_template": body_template,
            "recipient_rule": rule, "gate": gate, "rate_limit_per_day": rate,
            "enabled": enabled, "source": source,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        await self._db.put(COLLECTION, name, record)
        await self._audit("sendfn_save", name, source)
        return record

    async def get(self, name: str) -> dict | None:
        return await self._db.get(COLLECTION, name)

    async def list(self) -> list[dict]:
        docs = await self._db.query(COLLECTION)
        docs.sort(key=lambda d: d.get("name") or "")
        return [{k: v for k, v in d.items() if k != "_id"} for d in docs]

    async def names(self) -> set[str]:
        return {d["name"] for d in await self._db.query(COLLECTION) if d.get("name")}

    async def delete(self, name: str) -> bool:
        if await self._db.get(COLLECTION, name) is None:
            return False
        await self._db.delete(COLLECTION, name)
        await self._audit("sendfn_delete", name, "user")
        return True
