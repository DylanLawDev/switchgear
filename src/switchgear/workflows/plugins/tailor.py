class TailorResumeGenerator:
    """Generator protocol: generate(wf, item) -> dict. Wraps the existing
    TailorPipeline, which already knows its own collections, so wf is unused
    here — other generators (e.g. llm-brief) need it."""

    def __init__(self, pipeline):
        self._pipeline = pipeline

    async def generate(self, wf: dict, item: dict) -> dict:
        return await self._pipeline.tailor(item["key"])
