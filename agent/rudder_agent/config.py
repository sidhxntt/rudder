"""Agent process settings. Everything here is host-local; the agent never reads
the control plane database and holds no desired state."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUDDER_AGENT_", extra="ignore")

    bind: str = "0.0.0.0"
    port: int = 9000

    # D10: drain window default. The control plane normally passes an explicit
    # value per request; this is only the fallback.
    drain_seconds: float = 10.0

    # Timeout for a single health probe. The poll loop (D12) lives in the
    # control plane, not here.
    probe_timeout_seconds: float = 5.0

    # Seconds Docker waits after SIGTERM before SIGKILL when stopping.
    stop_timeout_seconds: int = 10

    # Compose manifests are written only beneath this host-local directory.
    # Imported repositories never choose arbitrary Docker Compose file paths.
    compose_state_dir: str = "/var/lib/rudder-agent/compose"
