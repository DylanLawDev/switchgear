"""ChannelSendExecutor: the gated bridge between the workflow action state
machine and ChannelSendService. draft() only materializes payloads the
service already validated (via the prepared handoff); execute() delegates
every policy decision back to the service at execute time. The executor is
registered at app construction — the seeded WORKFLOW.md needs the name to
parse — and bound to the per-channel service during lifespan activation."""

from switchgear.channels.send import ChannelSendError
from switchgear.workflows.actions import DraftResult, ExecutionFailed


class ChannelSendExecutor:
    def __init__(self, send_service):
        self.send_service = send_service  # bound during channel activation

    async def draft(self, item: dict) -> DraftResult:
        svc = self.send_service
        if svc is None:
            return DraftResult(fields=[], error="channel-send is not bound "
                                                "to an active channel")
        prepared = svc.take_prepared(item.get("key"))
        if prepared is None:
            # e.g. the owner hit "act" in the generic workflow UI: there is
            # no validated payload to materialize, and free-form drafting
            # would bypass the send-function policy engine.
            return DraftResult(
                fields=[],
                notes="channel sends start from the channel_send tool, not "
                      "from the workflow UI",
                error="no prepared send for this message")
        fields = [
            {"selector": "function", "label": "Send function",
             "value": prepared["function"], "source": "rule",
             "needs_you": False, "kind": "text"},
            {"selector": "to", "label": "To", "value": prepared["to"],
             "source": "rule", "needs_you": False, "kind": "text"},
            {"selector": "subject", "label": "Subject",
             "value": prepared["subject"], "source": "template",
             "needs_you": False, "kind": "text"},
            {"selector": "body", "label": "Body (text/plain)",
             "value": prepared["body"], "source": "template",
             "needs_you": False, "kind": "multiline"},
        ]
        return DraftResult(fields=fields, extra={
            "function": prepared["function"], "params": prepared["params"],
            "source_message_key": prepared["source_message_key"]})

    async def execute(self, record: dict) -> dict:
        svc = self.send_service
        if svc is None:
            raise ExecutionFailed("channel-send is not bound to an active "
                                  "channel")
        try:
            return await svc.execute_prepared(record)
        except ChannelSendError as e:
            # raised strictly before the transport call — safe to re-approve;
            # transport errors propagate as-is -> possibly_executed
            raise ExecutionFailed(str(e)) from e
