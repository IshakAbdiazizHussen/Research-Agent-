"""Environment-driven settings (Feature 1: User Identity & Data Foundation;
extended in Feature 2 for the LLM/web-search providers).

Every value here comes from the environment (or a local .env file) — nothing
downstream should hardcode a database URL, Redis URL, credential, or model
name. See docs/architecture.md (core/config.py) and docs/constraints.md.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Postgres, via Prisma. Required — the app must fail to start without it
    # rather than silently falling back to a default connection string.
    database_url: str

    # Redis (cache layer, Feature 3). Optional for Feature 1 since nothing
    # here touches Redis yet, but declared now so config stays centralized.
    redis_url: str = "redis://localhost:6379/0"

    environment: str = "development"

    # LLM provider (Feature 2: grader/rewriter/synthesizer nodes). Required —
    # picked and approved via user sign-off per docs/constraints.md ("any new
    # paid API or third-party service"). Model name is configurable, not
    # hardcoded in any node, so it can be tuned without a code change.
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — import and call this, don't re-instantiate
    Settings() elsewhere, so the whole app shares one parsed configuration."""
    return Settings()
