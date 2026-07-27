"""The background deploy worker.

Long work never runs inside a request: POST /services/{id}/deploy writes
Deployment(status=queued) and returns 202. This loop is what picks it up. It is
started from the FastAPI lifespan. No Celery, no broker — the queue is a status
column, which is all one control-plane process needs.
"""

import asyncio
import logging

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.logs.store import BuildLogStore
from rudder_cp.models import Deployment, DeploymentStatus
from rudder_cp.services.agent_client import AgentClient
from rudder_cp.services.deploy import run_deployment
from rudder_cp.services.imports import app_dependency_state
from rudder_cp.services.monitor import reconcile_instances

log = logging.getLogger("rudder_cp.worker")


async def run_worker(
    *,
    engine: Engine,
    settings: Settings,
    store: BuildLogStore,
    agent: AgentClient,
    stop: asyncio.Event,
    poll_interval: float = 2.0,
) -> None:
    # A development reload or control-plane restart cancels the in-memory task
    # but deliberately leaves the candidate containers alone. Resume the one
    # release that could have been executing (the worker is sequential), then
    # close any older abandoned rows so their log streams cannot hang forever.
    try:
        await recover_interrupted_deployments(
            engine=engine,
            settings=settings,
            store=store,
            agent=agent,
        )
    except Exception:
        log.exception("interrupted deployment recovery failed")

    while not stop.is_set():
        try:
            await tick(engine=engine, settings=settings, store=store, agent=agent)
        except Exception:
            # A worker that dies stops every future deploy silently, which is
            # the worst possible failure mode. Log and keep the loop alive.
            log.exception("deploy worker tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval)
        except TimeoutError:
            continue


async def recover_interrupted_deployments(
    *,
    engine: Engine,
    settings: Settings,
    store: BuildLogStore,
    agent: AgentClient,
) -> int:
    """Finish the newest deploy interrupted by a control-plane restart.

    ``run_worker`` processes releases serially, so at most one BUILDING or
    DEPLOYING row was actually running when this process stopped.  Resuming the
    newest row makes its existing image/Compose project authoritative. Older
    rows are abandoned attempts; leaving them in an in-flight state would make
    their UI log streams wait forever and could accidentally revive stale code.
    """
    with Session(engine) as session:
        interrupted = list(
            session.exec(
                select(Deployment)
                .where(
                    Deployment.status.in_(  # type: ignore[attr-defined]
                        [DeploymentStatus.BUILDING, DeploymentStatus.DEPLOYING]
                    )
                )
                .order_by(Deployment.created_at.desc())  # type: ignore[attr-defined]
            ).all()
        )

    if not interrupted:
        return 0

    candidate, *abandoned = interrupted
    for deployment in abandoned:
        message = "Abandoned after a newer interrupted deployment was recovered."
        with Session(engine) as session:
            stale = session.get(Deployment, deployment.id)
            if stale is None:
                continue
            stale.status = DeploymentStatus.FAILED
            stale.error_message = message
            session.add(stale)
            session.commit()
        if store.exists(deployment.id):
            await store.append(deployment.id, f"DEPLOYMENT FAILED: {message}\n")
            await store.close_log(deployment.id, "failed")
        else:
            await store.open_log(deployment.id)
            await store.append(deployment.id, f"DEPLOYMENT FAILED: {message}\n")
            await store.close_log(deployment.id, "failed")

    with Session(engine) as session:
        outcome = await run_deployment(
            candidate.id,
            session=session,
            engine=engine,
            agent=agent,
            store=store,
            settings=settings,
        )
    log.info("recovered interrupted deployment %s -> %s", candidate.id, outcome.status)
    return 1


async def tick(
    *,
    engine: Engine,
    settings: Settings,
    store: BuildLogStore,
    agent: AgentClient,
) -> int:
    """Run every currently queued deployment. Returns how many were attempted."""
    with Session(engine) as session:
        queued = session.exec(
            select(Deployment)
            .where(Deployment.status == DeploymentStatus.QUEUED)
            .order_by(Deployment.created_at)  # type: ignore[arg-type]
        ).all()
        ids = [deployment.id for deployment in queued]

    for deployment_id in ids:
        # A fresh session per deployment: a long build must not hold one open,
        # and one failed deploy must not poison the next one's session state.
        with Session(engine) as session:
            deployment = session.get(Deployment, deployment_id)
            if deployment is None:
                continue
            dependency_state, reason = app_dependency_state(session, deployment.service_id)
            if dependency_state == "waiting":
                continue
            if dependency_state == "failed":
                deployment.status = DeploymentStatus.FAILED
                deployment.error_message = reason
                session.add(deployment)
                session.commit()
                await store.open_log(deployment.id)
                await store.append(
                    deployment.id,
                    f"DEPLOYMENT FAILED: {reason or 'A required managed dependency failed.'}\n",
                )
                await store.close_log(deployment.id, "failed")
                log.info("deployment %s -> failed (%s)", deployment_id, reason)
                continue
            outcome = await run_deployment(
                deployment_id,
                session=session,
                engine=engine,
                agent=agent,
                store=store,
                settings=settings,
            )
            log.info("deployment %s -> %s (%s)", deployment_id, outcome.status, outcome.detail)

    # Runs every tick, deploys or not. A container that dies on its own is the
    # only way the database and the node disagree without anyone asking.
    with Session(engine) as session:
        await reconcile_instances(session, agent, settings)

    return len(ids)
