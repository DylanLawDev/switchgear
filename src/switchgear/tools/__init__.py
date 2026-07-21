from switchgear.config import Settings
from switchgear.gateway import Gateway
from switchgear.storage.base import Storage
from switchgear.tools.base import ToolRegistry
from switchgear.tools.fetch_jobs import make_fetch_jobs_tool
from switchgear.tools.http_fetch import make_http_fetch_tool
from switchgear.tools.llm_tool import make_llm_tool
from switchgear.tools.score_jobs import make_score_jobs_tool
from switchgear.tools.storage_tool import make_storage_tool


def build_registry(settings: Settings, storage: Storage, gateway: Gateway,
                   email_sender=None, skill_store=None, scheduler=None,
                   tailor_pipeline=None, browser_manager=None,
                   resource_store=None, memory_store=None,
                   channel_send_service=None, workflow_store=None,
                   resource_writes=None, skill_writes=None) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(make_http_fetch_tool())
    reg.register(make_storage_tool(storage))
    reg.register(make_llm_tool(gateway))
    reg.register(make_fetch_jobs_tool(settings, storage))
    reg.register(make_score_jobs_tool(settings, storage, gateway))
    if email_sender is not None:
        from switchgear.tools.send_email import make_send_email_tool

        reg.register(make_send_email_tool(settings, email_sender, storage))
    if skill_store is not None:
        from switchgear.tools.skill_tools import make_read_skill_tool, make_write_skill_tool

        reg.register(make_read_skill_tool(skill_store))
        reg.register(make_write_skill_tool(skill_writes or skill_store))
    if scheduler is not None and skill_store is not None:
        from switchgear.tools.schedule_tool import make_schedule_tool

        reg.register(make_schedule_tool(scheduler, skill_store, storage))
    if resource_store is not None:
        from switchgear.tools.resource_tool import make_resources_tool

        reg.register(make_resources_tool(resource_store, settings,
                                         writes=resource_writes))
    if tailor_pipeline is not None:
        from switchgear.tools.tailor_resume import make_tailor_resume_tool

        reg.register(make_tailor_resume_tool(tailor_pipeline))
    if browser_manager is not None:
        from switchgear.tools.browser_tool import make_browser_tool

        reg.register(make_browser_tool(browser_manager, storage))
    if memory_store is not None:
        from switchgear.tools.memory_tools import make_manage_memories_tool, make_save_memory_tool, make_search_memory_tool

        reg.register(make_save_memory_tool(memory_store))
        reg.register(make_search_memory_tool(memory_store))
        reg.register(make_manage_memories_tool(memory_store))
    if channel_send_service is not None:
        from switchgear.tools.channel_tools import make_channel_send_tool

        reg.register(make_channel_send_tool(channel_send_service))
    if workflow_store is not None:
        from switchgear.tools.channel_tools import make_channel_messages_tool

        reg.register(make_channel_messages_tool(workflow_store, storage))
    from switchgear.subagent import make_spawn_subagent_tool

    reg.register(make_spawn_subagent_tool(gateway, reg, settings, storage))
    return reg
