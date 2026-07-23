"""rudder status / rudder ps.

There is no single endpoint that returns a service with its status and URL, so
this stitches four: services in the environment, then per service its
deployments (intent), its instances (fact) and its domains (routing). Deployment
status alone is not enough — a deployment can be `live` while its container has
since died, which is exactly the distinction Instance exists to record.
"""

from __future__ import annotations

from uuid import UUID

import typer
from rudder_sdk.api.deployments import list_deployments, list_instances
from rudder_sdk.api.services import list_service_domains, list_services
from rudder_sdk.models import DeploymentRead, DomainRead, InstanceRead, ServiceRead

from ..context import State, resolve_environment, resolve_project
from ..render import emit_json, out, table


def status(ctx: typer.Context) -> None:
    """Services in the selected environment, with status and URL."""
    state: State = ctx.obj
    project = resolve_project(state)
    environment = resolve_environment(state)
    services: list[ServiceRead] = (
        state.api.call(list_services.sync_detailed, UUID(str(environment.id))) or []
    )

    rows: list[list[str]] = []
    payload: list[dict[str, object]] = []
    for service in services:
        service_id = UUID(str(service.id))
        deployments: list[DeploymentRead] = (
            state.api.call(list_deployments.sync_detailed, service_id) or []
        )
        instances: list[InstanceRead] = (
            state.api.call(list_instances.sync_detailed, service_id) or []
        )
        domains: list[DomainRead] = (
            state.api.call(list_service_domains.sync_detailed, service_id) or []
        )

        latest = deployments[0] if deployments else None
        live = [i for i in instances if i.status.value in {"starting", "healthy", "unhealthy"}]
        url = ""
        if domains:
            scheme = "https" if domains[0].tls_enabled else "http"
            url = f"{scheme}://{domains[0].hostname}"

        rows.append(
            [
                service.name,
                latest.status.value if latest else "never deployed",
                live[0].status.value if live else "-",
                url or "-",
                str(latest.id)[:8] if latest else "-",
            ]
        )
        payload.append(
            {
                "service": service.name,
                "service_id": str(service.id),
                "deployment": latest.to_dict() if latest else None,
                "instances": [i.to_dict() for i in live],
                "url": url or None,
            }
        )

    if state.json_out:
        emit_json(
            {
                "project": project.name,
                "environment": environment.name,
                "services": payload,
            }
        )
        return

    out(f"project {project.name} / environment {environment.name}")
    out()
    table(["SERVICE", "DEPLOYMENT", "INSTANCE", "URL", "LATEST"], rows)
