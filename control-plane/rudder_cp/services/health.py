"""Health polling. D12 parameters live here, not in the agent.

The agent performs one probe and reports one result. The loop, the timeout, the
grace period, and the success threshold are policy, and policy belongs to the
control plane.
"""

import asyncio
from dataclasses import dataclass

from rudder_cp.config import Settings
from rudder_cp.services.agent_client import AgentClient, AgentError


@dataclass(frozen=True)
class HealthOutcome:
    healthy: bool
    reason: str | None = None


async def wait_until_healthy(
    agent: AgentClient,
    container_id: str,
    *,
    path: str,
    port: int,
    protocol: str = "http",
    settings: Settings,
) -> HealthOutcome:
    """Poll until the container answers, it dies, or we run out of time.

    Returns rather than raising, because "this deploy failed health checks" is
    an ordinary outcome that becomes Deployment.error_message.
    """
    await asyncio.sleep(settings.health_start_grace_seconds)

    deadline = asyncio.get_running_loop().time() + settings.health_timeout_seconds
    successes = 0
    last_reason = "no probe completed"

    while asyncio.get_running_loop().time() < deadline:
        # A container that has already exited will never become healthy, so stop
        # burning the timeout on it and report the real reason.
        try:
            state = await agent.inspect(container_id)
        except AgentError as exc:
            return HealthOutcome(False, f"Lost contact with the container: {exc}")
        if state.status == "stopped":
            return HealthOutcome(
                False,
                f"Container exited before becoming healthy (exit code {state.exit_code}).",
            )

        try:
            probe_kwargs = {"path": path, "port": port}
            # Keep the existing HTTP request shape untouched. Apart from
            # compatibility with older agents, this makes the new TCP mode an
            # explicit opt-in for managed add-ons.
            if protocol != "http":
                probe_kwargs["protocol"] = protocol
            probe = await agent.probe(container_id, **probe_kwargs)
        except AgentError as exc:
            last_reason = str(exc)
        else:
            if probe.ok:
                successes += 1
                if successes >= settings.health_successes_required:
                    return HealthOutcome(True)
            else:
                # Consecutive, not cumulative: a flapping container is unhealthy.
                successes = 0
                last_reason = probe.reason or f"HTTP {probe.status_code}"

        await asyncio.sleep(settings.health_interval_seconds)

    return HealthOutcome(
        False,
        f"Health check on {path}:{port} did not pass within "
        f"{settings.health_timeout_seconds}s. Last result: {last_reason}",
    )


async def is_still_alive(agent: AgentClient, container_id: str) -> bool:
    """Re-check immediately before shifting traffic.

    A container can report 200 and then die while the traffic shift is being
    prepared. Checking once at the decision point is not the same as checking at
    the moment of the shift, and this is the gap the phase doc calls out.
    """
    try:
        state = await agent.inspect(container_id)
    except AgentError:
        return False
    return state.status in {"healthy", "starting"} and state.docker_status == "running"
