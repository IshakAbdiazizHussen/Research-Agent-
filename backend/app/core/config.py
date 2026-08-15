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

    # Embeddings (Feature 5: Long-Term Memory). Same OpenAI account/key as
    # above, not a new provider — cost pre-anticipated in docs/constraints.md
    # ("≤ 1 embedding call per completed run"). Model configurable, same
    # reasoning as openai_model.
    openai_embedding_model: str = "text-embedding-3-small"

    # Long-term memory backend (Feature 5). Swappable per the decision log
    # in docs/architecture.md — "in_memory" is the only implemented value
    # for v1; memory/base.py's get_memory_store() is the single place that
    # reads this, never re-checked at each call site.
    memory_backend: str = "in_memory"

    # CORS (Feature 6: Frontend Research UI) — comma-separated origins the
    # browser frontend is served from. Required for the frontend's
    # fetch()/SSE calls to backend/app/api/routes/research.py to work at
    # all (cross-origin by default: frontend on :3000, backend on :8000).
    #
    # Both localhost and 127.0.0.1 variants included deliberately, not
    # just localhost — a browser treats them as two distinct origins even
    # though they resolve to the same host, and a real preflight 400
    # ("Disallowed CORS origin") was reproduced against this exact gap:
    # http://localhost:3000 was allowed, http://127.0.0.1:3000 was not,
    # so accessing the frontend via the 127.0.0.1 form broke every
    # POST/GET call to this API. See docs/architecture.md's decision log.
    cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — import and call this, don't re-instantiate
    Settings() elsewhere, so the whole app shares one parsed configuration."""
    return Settings()
