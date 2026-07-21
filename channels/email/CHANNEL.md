---
schema_version: 1
name: email
transport: console
workflow: channel-email
poll_interval: 5m
triage:
  tier: bulk
  routes:
    file: {}
    draft_reply: {tier: writing}
---
The agent's email channel. Console transport is the safe default. Configure a
provider-neutral transport adapter in a deployment layer when live delivery is
needed. Automatic acknowledgement remains disabled unless explicitly configured.
