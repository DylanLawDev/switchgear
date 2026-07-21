from dataclasses import dataclass, field

from switchgear.config import Settings
from switchgear.chat_runs import ChatRunManager
from switchgear.conversations import ConversationStore
from switchgear.live import LiveUpdates
from switchgear.storage.base import Storage
from switchgear.tools.base import ToolRegistry


@dataclass
class AppState:
    settings: Settings
    gateway: object
    storage: Storage
    registry: ToolRegistry
    conversations: ConversationStore
    skill_store: object = None
    skill_writes: object = None
    scheduler: object = None
    skill_runner: object = None
    agent_profiles: object = None
    agent_runner: object = None
    resource_store: object = None
    resource_writes: object = None
    bank_provider: object = None
    tailor_pipeline: object = None
    browser_manager: object = None
    workflow_store: object = None
    workflow_runner: object = None
    workflow_schedules: object = None
    references: object = None
    assists: object = None
    workflow_plugins: object = None
    gated_actions: object = None
    channel_store: object = None
    channels: dict = field(default_factory=dict)
    channel_triage: dict = field(default_factory=dict)
    sendfn_store: object = None
    channel_send: dict = field(default_factory=dict)
    embedder: object = None
    memory_store: object = None
    reflection: object = None
    reflection_tasks: set = field(default_factory=set)
    live_updates: LiveUpdates | None = None
    chat_runs: ChatRunManager = field(default_factory=ChatRunManager)
    approvals: object = None
    definition_writes: object = None
