from functools import lru_cache
from importlib.util import find_spec
from typing import Literal

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SESSION_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SWITCHGEAR_", env_file=".env", extra="ignore")

    gateway_base_url: str = "https://openrouter.ai/api/v1"
    gateway_api_key: str = ""
    model_chat: str = "anthropic/claude-sonnet-4.5"
    model_bulk: str = "google/gemini-2.5-flash"
    model_writing: str = "anthropic/claude-sonnet-4.5"
    owner_email: str = ""
    owner_nickname: str = ""
    session_secret: str = "dev-secret-change-me"
    storage_backend: Literal["sqlite", "memory", "firestore"] = "sqlite"
    email_backend: Literal["console", "smtp"] = "console"
    # Containers set this to /data; source checkouts default to a local ignored dir.
    state_dir: str = ".state"
    local_password_hash: str = ""
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict"] = "lax"
    public_base_url: str = "http://localhost:8080"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    run_token_budget: int = 200000
    max_loop_iterations: int = 20
    service_url: str = "http://localhost:8080"
    cron_secret: str = ""
    setup_token: str = ""
    gcp_project: str = ""
    gcp_region: str = "us-central1"
    skills_dir: str = "skills"
    workflows_dir: str = "workflows"
    agents_dir: str = "agents"
    scheduler_backend: Literal["local", "cloud"] = "local"
    task_queue: str = "switchgear-workflows"
    owner_timezone: str = "Etc/UTC"
    approval_chat_escalation_seconds: int = 900
    jsearch_api_key: str = ""
    career_dir: str = "career"
    pdf_backend: str = "none"
    resources_dir: str = "resources"
    resource_max_bytes: int = 800_000
    resource_read_chars: int = 60_000
    embedding_backend: str = "fake"  # fake | gemini
    gemini_api_key: str = ""
    memory_max_chars: int = 1000
    memory_core_max_chars: int = 6000
    memory_recall_k: int = 4
    memory_recall_floor: float = 0.55
    memory_supersede_threshold: float = 0.92
    memory_recency_half_life_days: float = 14.0
    memory_reflection_min_interval: int = 600
    channels_dir: str = "channels"
    channel_backend: Literal["console"] = "console"
    channel_email_address: str = ""
    channel_body_max_chars: int = 20_000
    channel_backfill_max: int = 200
    channel_reply_rate_per_day: int = 20

    def model_for(self, tier: str) -> str:
        tiers = {"chat": self.model_chat, "bulk": self.model_bulk, "writing": self.model_writing}
        return tiers[tier]

    @property
    def sqlite_path(self) -> Path:
        return Path(self.state_dir) / "switchgear.sqlite3"

    def validate_runtime(self) -> None:
        """Validate only settings needed by selected runtime adapters."""
        if self.session_secret == DEV_SESSION_SECRET and self.cookie_secure:
            # Local development remains convenient when explicitly bound to localhost.
            host = self.public_base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
            if host not in {"localhost", "127.0.0.1", "::1"}:
                raise RuntimeError("SWITCHGEAR_SESSION_SECRET must be changed for a public service")
        if self.email_backend == "smtp" and (not self.smtp_host or not self.smtp_from):
            raise RuntimeError("SWITCHGEAR_SMTP_HOST and SWITCHGEAR_SMTP_FROM are required for SMTP")
        if self.scheduler_backend == "cloud" and not self.cron_secret:
            raise RuntimeError("SWITCHGEAR_CRON_SECRET is required for cloud scheduling")
        if (self.storage_backend == "firestore" or self.scheduler_backend == "cloud") \
                and find_spec("google") is None:
            raise RuntimeError("selected GCP adapter is unavailable; install switchgear[gcp]")
        if self.pdf_backend == "chromium" and find_spec("playwright") is None:
            raise RuntimeError("Chromium is unavailable; use the browser image or install [browser]")


@lru_cache
def get_settings() -> Settings:
    return Settings()
