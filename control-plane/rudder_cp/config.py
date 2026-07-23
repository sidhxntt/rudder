"""Settings. Every knob is an env var prefixed RUDDER_ (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RUDDER_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://rudder:rudder@localhost:5432/rudder"

    # D13 — MultiFernet over a comma-separated list, first key encrypts.
    secret_keys: str = ""
    jwt_secret: str = ""
    jwt_ttl_seconds: int = 60 * 60 * 12

    # Phase 1 step 3: one user, seeded on first boot. No signup.
    admin_email: str = "you@example.com"
    admin_password: str = "change-me"

    # D2 — one token for the whole install, no per-repo model in Phase 1.
    github_token: str = ""
    github_webhook_secret: str = ""

    # D8 — ACME cannot do HTTP-01 against localhost.
    tls_mode: Literal["off", "acme"] = "off"
    base_domain: str = "localhost"
    acme_email: str = ""

    registry: str = "localhost:5000"
    buildkit_addr: str = "tcp://registry:1234"
    docker_network: str = "rudder"

    # D3(b) — the control plane never touches Docker directly, it calls the agent.
    agent_url: str = "http://agent:9000"

    traefik_dynamic_dir: str = "/traefik/dynamic"
    build_log_dir: str = "/var/log/rudder/builds"

    # D12 — health check parameters.
    health_timeout_seconds: int = 60
    health_interval_seconds: int = 2
    health_start_grace_seconds: int = 5
    health_successes_required: int = 1

    # D10 — drain window before the old container is stopped.
    drain_seconds: int = 10

    @property
    def fernet_keys(self) -> list[str]:
        return [k.strip() for k in self.secret_keys.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
