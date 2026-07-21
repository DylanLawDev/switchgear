"""ChannelSendService: THE sole outbound path for channel mail (spec §5.2).

Every non-owner-notify send — the channel_send tool, Phase 3's automatic
triage replies, and execution of approved drafts — funnels through this
service.
Security posture (spec §8 invariants 3, 4, 6):

- Recipients are derived from the recipient_rule in code: owner-authored
  fixed/allowlist addresses, settings.owner_email, or the stored message's
  sender. Model output never picks an address, and the structural rule
  (gate:auto => reply_to_thread|owner) is re-asserted here in case storage
  was written around the store.
- Suppression and rate limits are enforced against storage state, never in
  prompts. The authoritative rate check + increment runs under a lock in
  _transmit (the earlier checks in send()/execute_prepared are advisory,
  for early clean errors), and the counter increments BEFORE the transport
  call: a crashed send burns budget instead of minting retries (fail
  closed). A limit of 0 means no sends at all.
- gate:approve stops at a draft action on the channel workflow; only
  GatedActionService (hash-pinned payload, TTLs) can move it further, and
  execute_prepared() re-runs every policy check at execute time.
- Tier-a built-in replies (draft records with function None, materialized by
  Phase 3's draft_reply route) execute here too: recipient derived in code
  from the stored message's sender, suppression re-checked, and a global
  ceiling (channel_reply_rate_per_day, reserved counter "builtin-reply")
  bounds outbound volume.
- transport.send carries text/plain only — there is no HTML leg.
"""

import asyncio
import time
from uuid import uuid4

from switchgear.channels.sendfns import EMAIL_RE, RESERVED_NAMES, SLOT_RE

SUPPRESSION_COLLECTION = "channel-suppression"  # key = normalized address
RATE_COLLECTION = "channel-rate"                # key = f"{counter}-{YYYYMMDD}"
BUILTIN_REPLY_COUNTER = "builtin-reply"  # reserved: tier-a replies share it


class ChannelSendError(Exception):
    """Policy failure raised strictly BEFORE any transport side effect."""


def normalize_address(address: str) -> str:
    return (address or "").strip().lower()


def extract_address(sender: str) -> str | None:
    """'Jane <jane@x.com>' or bare 'jane@x.com' -> normalized address."""
    sender = (sender or "").strip()
    if sender.endswith(">") and "<" in sender:
        sender = sender.rsplit("<", 1)[1][:-1]
    candidate = normalize_address(sender)
    return candidate if EMAIL_RE.fullmatch(candidate) else None


def _strip_crlf(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ")


class ChannelSendService:
    def __init__(self, storage, transport, sendfn_store, workflow_store,
                 gated_actions, channel: dict, settings, clock=time.time):
        self._db = storage
        self._transport = transport
        self._sendfns = sendfn_store
        self._workflows = workflow_store
        self._gated = gated_actions
        self._channel = channel
        self._s = settings
        self._now = clock
        # start_draft's executor hook receives only the item, so the
        # materialized payload rides this handoff, keyed by item key. The
        # lock serializes THIS service's sends so stage/pop pairs never
        # interleave — it cannot exclude an EXTERNAL gated.start_draft
        # (e.g. the workflow UI) for the same item, which invokes the same
        # executor and can pop a staged payload first. That race is
        # accepted: the stolen draft is fully policy-derived (recipient,
        # subject, and body were all validated in code — nothing the
        # external caller chooses), pop-once means the payload lands on at
        # most one draft (never a duplicate send), and the losing send()
        # raises a clean "no prepared send" ChannelSendError — worst case
        # is an orphaned but valid pending draft. The window is the sub-ms
        # span of one start_draft call on a single-instance deployment.
        self._prepared: dict[str, dict] = {}
        self._draft_lock = asyncio.Lock()
        # Serializes the authoritative rate read-check-increment in
        # _transmit; never held across the transport call.
        self._rate_lock = asyncio.Lock()

    # ---------- public API ----------

    async def send(self, function_name: str, params: dict, actor: str,
                   source_message_key: str | None = None) -> dict:
        fn = await self._fn_or_error(function_name)                     # step 1
        params = dict(params or {})
        message_key = source_message_key or params.pop("message_key", None)
        to_param = params.pop("to", None)
        if to_param is not None and fn["recipient_rule"]["type"] != "allowlist":
            raise ChannelSendError("'to' is only accepted for allowlist "
                                   "functions")
        values = self._validate_params(fn, params)                      # step 2
        source = await self._load_source(message_key)
        rendered = self._render(fn, values, source)                     # step 3
        recipient = self._resolve_recipient(fn, to_param, source,
                                            message_key)                # step 4
        await self._check_suppression(fn["name"], recipient, actor)
        await self._check_rate(counter=fn["name"], function=fn["name"],
                               limit=fn["rate_limit_per_day"],
                               recipient=recipient, actor=actor)        # step 5
        if fn["gate"] == "approve":                                     # step 6
            key = await self._create_draft(fn, values, rendered, recipient,
                                           message_key)
            return {"status": "pending_approval", "key": key,
                    "approval": {"kind": "workflow_action", "id": key,
                                 "context": "channel-email"}}
        in_reply_to = None                                           # steps 7-8
        if fn["recipient_rule"]["type"] == "reply_to_thread" and source:
            in_reply_to = source.get("rfc_message_id") or None
        await self._transmit(counter=fn["name"], function=fn["name"],
                             gate=fn["gate"], to=recipient,
                             subject=rendered["subject"],
                             body=rendered["body"], in_reply_to=in_reply_to,
                             actor=actor, limit=fn["rate_limit_per_day"])
        return {"status": "sent", "to": recipient}

    async def execute_prepared(self, record: dict) -> dict:
        """Execute-time policy re-run, then the transport send.

        Two record shapes (decision 9): function: <name> re-runs the full
        send-function pipeline (steps 1-5); function: None is a tier-a
        built-in reply materialized by Phase 3's draft_reply route and takes
        the built-in branch. Either way, everything before the transport
        call raises ChannelSendError — policy failures AND pre-send storage
        failures alike (the latter wrapped in _transmit) — which the
        executor maps to ExecutionFailed (no side effect, safe to
        re-approve); only the transport call and what follows it propagate
        untouched so the gate records possibly_executed.
        The approved (possibly owner-edited) subject/body are what gets
        sent — approval hash-pins them; the recipient is re-derived in code,
        so an edited 'to' can never escape the rule (or the message sender).
        """
        fields = {f["selector"]: f.get("value")
                  for f in record.get("fields", [])}
        function_name = record.get("function")
        if function_name is None:
            return await self._execute_builtin_reply(record, fields)
        fn = await self._fn_or_error(function_name)                     # step 1
        values = self._validate_params(fn, dict(record.get("params") or {}))
        message_key = record.get("source_message_key")                  # step 2
        source = await self._load_source(message_key)
        self._render(fn, values, source)   # step 3: must still render
        to_field = normalize_address(str(fields.get("to") or ""))
        if fn["recipient_rule"]["type"] == "allowlist":                 # step 4
            recipient = self._resolve_recipient(fn, to_field, source,
                                                message_key)
        else:
            recipient = self._resolve_recipient(fn, None, source, message_key)
            if to_field != recipient:
                raise ChannelSendError("approved recipient no longer matches "
                                       "the recipient rule — re-draft")
        await self._check_suppression(fn["name"], recipient, "owner")
        await self._check_rate(counter=fn["name"], function=fn["name"],
                               limit=fn["rate_limit_per_day"],
                               recipient=recipient, actor="owner")      # step 5
        subject = _strip_crlf(str(fields.get("subject") or ""))
        body = str(fields.get("body") or "")
        if not subject.strip() or not body.strip():
            raise ChannelSendError("approved send needs a subject and a body")
        in_reply_to = None
        if fn["recipient_rule"]["type"] == "reply_to_thread" and source:
            in_reply_to = source.get("rfc_message_id") or None
        await self._transmit(counter=fn["name"], function=fn["name"],
                             gate=fn["gate"], to=recipient, subject=subject,
                             body=body, in_reply_to=in_reply_to,
                             actor="owner", limit=fn["rate_limit_per_day"])
        return {"sent_to": recipient}

    async def _execute_builtin_reply(self, record: dict,
                                     fields: dict) -> dict:
        """Tier-a built-in reply (spec §2): a draft action with function
        None. No send function governs it, so enabled/params/render and the
        per-function rate limit don't apply — but the recipient is still
        derived in code from the stored source message, suppression is
        re-checked, and the global channel_reply_rate_per_day ceiling
        (reserved counter "builtin-reply") bounds outbound volume.
        """
        wf = await self._wf()
        # canonical: source_message_key persisted on the record (Phase 3
        # sets it); fallback: the action's item ref — for reply drafts the
        # item IS the source message.
        message_key = (record.get("source_message_key")
                       or record.get(wf["actions"]["item_ref_field"]))
        if not message_key:
            raise ChannelSendError("reply draft carries no source message key")
        source = await self._load_source(message_key)  # raises if missing
        recipient = extract_address(source.get("sender"))
        if not recipient:
            raise ChannelSendError(
                "could not derive a reply address from the message")
        to_field = normalize_address(str(fields.get("to") or ""))
        if to_field and to_field != recipient:
            raise ChannelSendError("approved recipient no longer matches "
                                   "the message sender — re-draft")
        await self._check_suppression(None, recipient, "owner")
        await self._check_rate(counter=BUILTIN_REPLY_COUNTER, function=None,
                               limit=self._s.channel_reply_rate_per_day,
                               recipient=recipient, actor="owner")
        subject = _strip_crlf(str(fields.get("subject") or ""))
        body = str(fields.get("body") or "")
        if not subject.strip() or not body.strip():
            raise ChannelSendError("approved send needs a subject and a body")
        await self._transmit(counter=BUILTIN_REPLY_COUNTER, function=None,
                             gate="approve", to=recipient, subject=subject,
                             body=body,
                             in_reply_to=source.get("rfc_message_id") or None,
                             actor="owner",
                             limit=self._s.channel_reply_rate_per_day)
        return {"sent_to": recipient}

    def take_prepared(self, item_key: str) -> dict | None:
        return self._prepared.pop(item_key, None)

    # ---------- steps 1-2 ----------

    async def _fn_or_error(self, name: str) -> dict:
        if name in RESERVED_NAMES:
            # save-time symmetry: a doc written around the store under the
            # reserved name must never execute (it would share the built-in
            # reply's rate counter).
            raise ChannelSendError(f"{name!r} is a reserved name")
        fn = await self._sendfns.get(name)
        if fn is None:
            raise ChannelSendError(f"unknown send function {name!r}")
        if not fn.get("enabled", True):
            raise ChannelSendError(f"send function {name!r} is disabled")
        if (fn.get("gate") == "auto"
                and fn["recipient_rule"]["type"] not in ("reply_to_thread",
                                                         "owner")):
            # the store enforces this at save; re-assert in case storage was
            # written around it (spec §8 invariant 3, belt and braces)
            raise ChannelSendError(
                f"send function {name!r} violates the auto-gate rule")
        return fn

    def _validate_params(self, fn: dict, params: dict) -> dict:
        declared = fn.get("params") or {}
        unknown = set(params) - set(declared)
        if unknown:
            raise ChannelSendError(f"unknown params: {sorted(unknown)}")
        missing = set(declared) - set(params)
        if missing:
            raise ChannelSendError(f"missing params: {sorted(missing)}")
        values: dict[str, str] = {}
        for pname, spec in declared.items():
            value = params[pname]
            if spec["type"] == "number":
                if isinstance(value, bool) or not isinstance(value,
                                                             (int, float)):
                    raise ChannelSendError(f"param {pname!r} must be a number")
                values[pname] = str(value)
                continue
            if not isinstance(value, str):
                raise ChannelSendError(f"param {pname!r} must be a string")
            value = _strip_crlf(value)  # single-line by construction
            if spec["type"] == "enum":
                if value not in spec["values"]:
                    raise ChannelSendError(
                        f"param {pname!r} must be one of {spec['values']}")
            elif len(value) > spec["max_chars"]:
                raise ChannelSendError(
                    f"param {pname!r} exceeds {spec['max_chars']} chars")
            values[pname] = value
        return values

    # ---------- step 3 ----------

    def _render(self, fn: dict, values: dict, source: dict | None) -> dict:
        slots = dict(values)
        slots["date"] = time.strftime("%Y-%m-%d", time.gmtime(self._now()))
        if source is not None:
            counterparty = extract_address(source.get("sender"))
            if counterparty:
                slots["sender"] = counterparty

        def render_one(field: str, template: str) -> str:
            def repl(match):
                name = match.group(1)
                if name not in slots:
                    raise ChannelSendError(
                        f"{field}: unfilled template slot {{{{{name}}}}}")
                return slots[name]

            out = SLOT_RE.sub(repl, template)
            if "{{" in out:  # a param VALUE tried to smuggle a placeholder
                raise ChannelSendError(
                    f"{field}: unresolved placeholder after render")
            return out

        subject = _strip_crlf(render_one("subject_template",
                                         fn["subject_template"]))
        body = render_one("body_template", fn["body_template"])
        if not subject.strip() or not body.strip():
            raise ChannelSendError("rendered subject and body must be "
                                   "non-empty")
        return {"subject": subject, "body": body}

    # ---------- step 4 ----------

    async def _wf(self) -> dict:
        wf = await self._workflows.get(self._channel["workflow"])
        if wf is None or wf.get("status") != "active" or not wf.get("actions"):
            raise ChannelSendError("channel workflow is not active")
        return wf

    async def _load_source(self, message_key: str | None) -> dict | None:
        if message_key is None:
            return None
        wf = await self._wf()
        doc = await self._db.get(wf["items"]["collection"], message_key)
        if doc is None:
            raise ChannelSendError(f"source message {message_key!r} not found")
        return doc

    def _resolve_recipient(self, fn: dict, to_param, source: dict | None,
                           message_key: str | None) -> str:
        rule = fn["recipient_rule"]
        if rule["type"] == "fixed":
            return rule["address"]
        if rule["type"] == "owner":
            owner = normalize_address(self._s.owner_email)
            if not owner:
                raise ChannelSendError("owner_email is not configured")
            return owner
        if rule["type"] == "allowlist":
            to = normalize_address(str(to_param or ""))
            if not to:
                raise ChannelSendError("allowlist functions need a 'to' param")
            if to not in rule["addresses"]:
                raise ChannelSendError(f"{to!r} is not in the allowlist")
            return to
        # reply_to_thread: counterparty derived in code from the stored message
        if message_key is None or source is None:
            raise ChannelSendError(
                "reply_to_thread needs a source message key")
        counterparty = extract_address(source.get("sender"))
        if not counterparty:
            raise ChannelSendError(
                "could not derive a reply address from the message")
        return counterparty

    async def _check_suppression(self, function: str | None, recipient: str,
                                 actor: str) -> None:
        if await self._db.get(SUPPRESSION_COLLECTION, recipient) is not None:
            await self._audit_rejected(function, recipient, actor,
                                       "suppressed")
            raise ChannelSendError(f"{recipient} is on the suppression list")

    # ---------- step 5 ----------

    def _rate_key(self, counter: str) -> str:
        day = time.strftime("%Y%m%d", time.gmtime(self._now()))
        return f"{counter}-{day}"

    async def _check_rate(self, *, counter: str, function: str | None,
                          limit: int, recipient: str, actor: str) -> None:
        doc = await self._db.get(RATE_COLLECTION, self._rate_key(counter)) or {}
        if int(doc.get("count") or 0) >= limit:
            await self._audit_rejected(function, recipient, actor,
                                       "rate-limited")
            raise ChannelSendError(
                f"rate limit reached for {counter} ({limit}/day)")

    # ---------- step 6 ----------

    async def _create_draft(self, fn: dict, values: dict, rendered: dict,
                            recipient: str, message_key: str | None) -> str:
        wf = await self._wf()
        if message_key is not None:
            item_key = message_key
        else:
            # Cold sends have no inbound message, but start_draft requires a
            # real item (and the sibling-conflict rule keys off it), so each
            # cold send gets its own synthetic outbound item — a unique key,
            # so independent sends never block each other, and the pending
            # send is visible in the workflow UI.
            item_key = f"out-{uuid4().hex[:12]}"
            await self._db.put(wf["items"]["collection"], item_key, {
                "key": item_key, "subject": rendered["subject"],
                "sender": "agent", "to": recipient, "thread_id": "",
                "provider_id": "", "body_text": rendered["body"],
                "received_at": self._now(), "triage_route": "",
                "triage_reason": f"outbound: {fn['name']}",
                "triage_status": "outbound"})
        prepared = {"function": fn["name"], "params": values,
                    "source_message_key": message_key, "to": recipient,
                    "subject": rendered["subject"], "body": rendered["body"]}
        async with self._draft_lock:
            self._prepared[item_key] = prepared
            try:
                record = await self._gated.start_draft(wf, item_key)
            finally:
                self._prepared.pop(item_key, None)
        key = record.get(wf["actions"]["key_field"])
        if not key or record.get("error"):
            raise ChannelSendError(
                f"draft creation failed: {record.get('error') or 'unknown'}")
        return key

    # ---------- steps 7-8 ----------

    async def _transmit(self, *, counter: str, function: str | None,
                        gate: str, to: str, subject: str, body: str,
                        in_reply_to: str | None, actor: str,
                        limit: int) -> None:
        try:
            async with self._rate_lock:
                # Authoritative rate check: the earlier _check_rate calls
                # are advisory (early clean errors); this locked
                # read-check-increment is the one that counts, so two
                # concurrent sends sharing a counter can neither lose an
                # increment nor both slip under the ceiling. The increment
                # lands BEFORE the transport call (fail closed: a crashed
                # send burns budget instead of minting retries), but the
                # lock is released before the network call below.
                key = self._rate_key(counter)
                doc = await self._db.get(RATE_COLLECTION, key) or {}
                if int(doc.get("count") or 0) >= limit:
                    await self._audit_rejected(function, to, actor,
                                               "rate-limited")
                    raise ChannelSendError(
                        f"rate limit reached for {counter} ({limit}/day)")
                doc.pop("_id", None)
                doc["count"] = int(doc.get("count") or 0) + 1
                await self._db.put(RATE_COLLECTION, key, doc)
            prior = await self._db.query(
                "audit", where={"tool": "channel-send", "recipient": to},
                limit=1)
        except ChannelSendError:
            raise
        except Exception as e:
            # Storage died before any side effect: still a clean pre-send
            # failure (-> ExecutionFailed, safe to retry), never ambiguity.
            # The ambiguity boundary is exactly the transport call below —
            # from there on, errors propagate untouched so the gate records
            # possibly_executed.
            raise ChannelSendError(
                f"pre-send bookkeeping failed: {type(e).__name__}: {e}"
            ) from e
        # text/plain only — the transport signature has no html leg (§8.6)
        await self._transport.send(to, subject, body, in_reply_to=in_reply_to)
        await self._db.put("audit", f"chsend-{uuid4().hex}", {
            "tool": "channel-send", "function": function, "recipient": to,
            "gate": gate, "actor": actor, "new_recipient": not prior,
            "at": self._now()})

    async def _audit_rejected(self, function: str | None, recipient: str,
                              actor: str, reason: str) -> None:
        # distinct tool key so new_recipient scans over ACTUAL sends only
        await self._db.put("audit", f"chsend-{uuid4().hex}", {
            "tool": "channel-send-rejected", "function": function,
            "recipient": recipient, "reason": reason, "actor": actor,
            "at": self._now()})
