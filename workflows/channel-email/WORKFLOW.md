---
schema_version: 1
name: channel-email
ui_home: channels
description: Inbound messages on the agent's email channel
items:
  label: message
  label_plural: messages
  title_field: subject
  fields:
    subject:         {type: text}
    sender:          {type: text}
    to:              {type: text}
    thread_id:       {type: text}
    provider_id:     {type: text}
    rfc_message_id:  {type: text}
    body_text:       {type: markdown}
    received_at:     {type: timestamp}
    triage_route:    {type: enum}
    triage_reason:   {type: text}
    triage_status:   {type: status}
  list_fields: [subject, sender, triage_status, triage_route, received_at]
  sort: [-received_at]
actions:
  label: send
  label_plural: sends
  executor: channel-send
  approval_ttl: 3d
  draft_ttl: 14d
---
Every message the agent's email channel receives, stored after sanitization
(hidden text stripped, HTML flattened, bodies truncated) — the raw MIME never
leaves the provider. Triage outcomes land on each message once the classifier
ships (Phase 3); outbound send actions arrive with Phase 2.
