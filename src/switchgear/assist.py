PRESETS = {
    "prompt": {
        "name": "Prompt generation",
        "prompt": ("You improve operational prompts for autonomous agents. Preserve the user's "
                   "intent, make data sources and completion criteria explicit, and return only "
                   "the finished prompt."),
    },
    "workflow": {
        "name": "Workflow generation",
        "prompt": ("You design schema-version-2 switchgear workflow manifests. Use an ordered, "
                   "bounded sequence of agent, deterministic tool, and CEL transform steps. "
                   "Return only the complete WORKFLOW.md text."),
    },
    "parameters": {
        "name": "Workflow parameter generation",
        "prompt": ("You produce workflow input parameters from the user's request and available "
                   "context. Return only JSON matching the supplied workflow input schema."),
    },
}


class AssistService:
    def __init__(self, agent_runner, workflow_store):
        self._agents = agent_runner
        self._workflows = workflow_store

    def list(self) -> list[dict]:
        return [{"id": key, "name": value["name"]} for key, value in PRESETS.items()]

    async def run(self, preset_id: str, user_prompt: str, *, draft: str = "",
                  workflow: str = "") -> dict:
        preset = PRESETS.get(preset_id)
        if preset is None:
            return {"ok": False, "error": "unknown assistance preset"}
        context: dict = {"current_draft": draft}
        schema = None
        if preset_id == "parameters":
            definition = await self._workflows.get(workflow)
            if definition is None or not definition.get("execution"):
                return {"ok": False, "error": "select an executable workflow"}
            schema = definition["execution"]["inputs"]
            context.update({"workflow": workflow, "input_schema": schema})
        return await self._agents.run(user_prompt, context=context, output_schema=schema,
                                      origin=f"assist:{preset_id}",
                                      instructions=preset["prompt"])
