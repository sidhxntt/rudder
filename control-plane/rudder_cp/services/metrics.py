"""Collect and compact container metrics without a separate monitoring stack."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kubernetes_asyncio.client import ApiException
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import Deployment, Instance, InstanceStatus, Node, RuntimeMetric, Service
from rudder_cp.runtime.targets import load_kubernetes_client
from rudder_cp.services.agent_client import AgentClient, AgentError
from rudder_cp.services.kubernetes_namespace import environment_namespace

RAW_SECONDS = 10
MINUTE_SECONDS = 60
FIVE_MINUTE_SECONDS = 300


async def collect_runtime_metrics(session: Session, agent: AgentClient, settings: Settings) -> int:
    if settings.runtime == "kubernetes":
        return await _collect_kubernetes_runtime_metrics(session, settings)
    if settings.runtime != "docker":
        return 0
    rows = session.exec(
        select(Instance, Node)
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .join(Node, Node.id == Instance.node_id)  # type: ignore[arg-type]
        .where(Instance.status.in_((InstanceStatus.HEALTHY, InstanceStatus.UNHEALTHY)))  # type: ignore[attr-defined]
    ).all()
    now = datetime.now(UTC).replace(microsecond=0)
    added = 0
    for instance, node in rows:
        if not instance.container_id or not node.ip_address:
            continue
        try:
            observed = await agent.for_node(node.ip_address).runtime_metrics(instance.container_id)
        except AgentError:
            continue
        session.add(
            RuntimeMetric(
                instance_id=instance.id,
                captured_at=now,
                resolution_seconds=RAW_SECONDS,
                cpu_percent=observed.cpu_percent,
                memory_bytes=observed.memory_bytes,
            )
        )
        added += 1
    if added:
        session.commit()
    return added


async def _collect_kubernetes_runtime_metrics(session: Session, settings: Settings) -> int:
    """Persist metrics-server Pod usage without requiring access to GKE nodes."""
    rows = session.exec(
        select(Instance, Service)
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .join(Service, Service.id == Deployment.service_id)  # type: ignore[arg-type]
        .where(Instance.status.in_((InstanceStatus.HEALTHY, InstanceStatus.UNHEALTHY)))  # type: ignore[attr-defined]
    ).all()
    now = datetime.now(UTC).replace(microsecond=0)
    api = None
    added = 0
    try:
        api = await load_kubernetes_client(settings)
        for instance, service in rows:
            if not instance.container_id:
                continue
            namespace = environment_namespace(settings, service.environment_id)
            try:
                observed = await api.runtime_metrics(namespace, instance.container_id)
            except (ApiException, OSError, RuntimeError):
                continue
            session.add(
                RuntimeMetric(
                    instance_id=instance.id,
                    captured_at=now,
                    resolution_seconds=RAW_SECONDS,
                    cpu_percent=observed.cpu_percent,
                    memory_bytes=observed.memory_bytes,
                )
            )
            added += 1
        if added:
            session.commit()
    except (ApiException, OSError, RuntimeError):
        # Metrics are best-effort: a short control-plane or metrics-server
        # outage must not prevent deployments and reconciliation from running.
        return 0
    finally:
        if api is not None:
            try:
                await api.close()
            except (ApiException, OSError, RuntimeError):
                pass
    return added


def compact_runtime_metrics(session: Session, *, now: datetime | None = None) -> int:
    """Downsample raw → minute → five-minute and delete expired tiers."""
    now = now or datetime.now(UTC)
    inserted = 0
    inserted += _rollup(session, RAW_SECONDS, MINUTE_SECONDS, now - timedelta(hours=1))
    inserted += _rollup(session, MINUTE_SECONDS, FIVE_MINUTE_SECONDS, now - timedelta(hours=24))
    session.exec(
        RuntimeMetric.__table__.delete().where(
            (RuntimeMetric.resolution_seconds == RAW_SECONDS)
            & (RuntimeMetric.captured_at < now - timedelta(hours=1))
        )
    )
    session.exec(
        RuntimeMetric.__table__.delete().where(
            (RuntimeMetric.resolution_seconds == MINUTE_SECONDS)
            & (RuntimeMetric.captured_at < now - timedelta(hours=24))
        )
    )
    session.exec(
        RuntimeMetric.__table__.delete().where(
            (RuntimeMetric.resolution_seconds == FIVE_MINUTE_SECONDS)
            & (RuntimeMetric.captured_at < now - timedelta(days=7))
        )
    )
    session.commit()
    return inserted


def _rollup(session: Session, source_tier: int, target_tier: int, before: datetime) -> int:
    rows = session.exec(
        select(RuntimeMetric).where(
            RuntimeMetric.resolution_seconds == source_tier, RuntimeMetric.captured_at < before
        )
    ).all()
    buckets: dict[tuple[object, datetime], list[RuntimeMetric]] = {}
    for row in rows:
        epoch = int(row.captured_at.timestamp()) // target_tier * target_tier
        bucket_time = datetime.fromtimestamp(epoch, UTC)
        buckets.setdefault((row.instance_id, bucket_time), []).append(row)
    added = 0
    for (instance_id, captured_at), values in buckets.items():
        existing = session.exec(
            select(RuntimeMetric.id).where(
                RuntimeMetric.instance_id == instance_id,
                RuntimeMetric.captured_at == captured_at,
                RuntimeMetric.resolution_seconds == target_tier,
            )
        ).first()
        if existing is None:
            session.add(
                RuntimeMetric(
                    instance_id=instance_id,
                    captured_at=captured_at,
                    resolution_seconds=target_tier,
                    cpu_percent=sum(row.cpu_percent for row in values) / len(values),
                    memory_bytes=round(sum(row.memory_bytes for row in values) / len(values)),
                )
            )
            added += 1
    return added
