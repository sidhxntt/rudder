"""Agent process settings. Everything here is host-local; the agent never reads
the control plane database and holds no desired state."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUDDER_AGENT_", extra="ignore")

    bind: str = "0.0.0.0"
    port: int = 9000

    control_plane_url: str = "http://localhost:8000"
    shared_secret: str = "secret"  # Replace with a real secret in production
    node_hostname: str = "localhost"
    # Reachable address the control plane uses for command requests. This must
    # be the node's private IP in a multi-host deployment, not a Docker IP.
    advertise_address: str = "127.0.0.1"

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
