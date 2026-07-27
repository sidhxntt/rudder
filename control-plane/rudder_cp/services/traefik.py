"""Traefik dynamic configuration, generated from `Domain` rows — never from
`Service` rows. This module is the entire reason D15 exists.

One router per Domain, one file per Domain, named `{domain_id}.yml` inside
`settings.traefik_dynamic_dir`. Traefik's file provider watches that directory
live (see `infra/traefik/traefik.yml`), so every write here is observed by a
running proxy within milliseconds. Two consequences drive the whole design:

1. **Every file write is atomic.** Content goes to a temp file that Traefik's
   file provider ignores (it only reads `.yml` / `.yaml` / `.toml` / `.json`),
   is fsynced, and is then `os.replace`d into place. Traefik therefore never
   reads a half-written router. A rewrite of the whole directory is a sequence
   of independent atomic swaps, so mid-rewrite Traefik can observe a *mix* of
   old and new files — but every individual file it sees is complete and valid,
   and because each file carries exactly one Domain's router with globally
   unique names, a mixed view just means "some domains have already caught up".
   No domain ever loses its route because a different domain's file was being
   written.

2. **Unchanged files are not rewritten.** Rendering is a pure function of DB
   state, so the desired bytes are compared against what is already on disk and
   only differences are swapped in. Rendering twice in a row touches nothing,
   which keeps Traefik from reloading for no reason.

Backends: deployed containers publish **no host ports** (Phase 1 step 1).
Traefik reaches them over the shared Docker network by container name on the
service's `container_port` (D1). `health_check_port` is a different thing and is
never used for routing.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlmodel import Session, select

from rudder_cp.config import Settings, get_settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    DomainTargetType,
    GitHubImport,
    GitHubImportService,
    Instance,
    InstanceStatus,
    Service,
)

# Router / Traefik-service names are global across every file the provider
# loads, so they are namespaced by domain id.
NAME_PREFIX = "rudder"
# Entrypoints declared in infra/traefik/traefik.yml (static config).
HTTP_ENTRYPOINT = "web"
# Only referenced when tls_mode=acme; the static config must declare it, along
# with certificatesResolvers.rudder (acme_email lives there too, not here).
HTTPS_ENTRYPOINT = "websecure"
CERT_RESOLVER = "rudder"

FILE_SUFFIX = ".yml"
TMP_SUFFIX = ".tmp"

# render_all is called from the deploy path, from domain create/delete and from
# instance state changes, all of which can overlap. Serialising renders inside
# the process means two callers cannot interleave their writes; because a render
# is a pure function of DB state, the second render simply re-derives the newest
# state and converges. There is exactly one control plane process (HA control
# plane is an explicit non-goal), so a process-local lock is sufficient.
_render_lock = asyncio.Lock()


@dataclass(frozen=True)
class Target:
    """What one Domain currently resolves to.

    `service` is the Service that owns the routed containers — it is where
    `container_port` comes from. `deployment` is the Deployment actually being
    routed to (the live one for target_type=service, the pinned one for
    target_type=deployment). `instances` are that Deployment's healthy
    Instances, and only those: starting, unhealthy, draining and stopped
    instances must never receive traffic (D10 shifts traffic *before* draining).
    """

    service: Service | None
    deployment: Deployment | None
    instances: tuple[Instance, ...]

    @property
    def backend_urls(self) -> tuple[str, ...]:
        if self.service is None:
            return ()
        port = self.service.container_port
        hosts = [host for host in (_instance_host(i) for i in self.instances) if host]
        return tuple(sorted({f"http://{host}:{port}/" for host in hosts}))


def _instance_host(instance: Instance) -> str | None:
    """The address Traefik uses to reach one running container.

    `Instance` carries exactly one container identifier: `container_id`. On a
    user-defined Docker network the daemon's embedded DNS resolves a container
    by its hostname, and Docker defaults that hostname to the 12-character short
    id — so the short id is a name Traefik can dial on the shared `rudder`
    network without any host port being published. `wg_ip` is deliberately not
    used: it is the mesh address from Phase 3, not an address on the Docker
    network Traefik sits on in Phase 1.

    An Instance with no container_id has no container yet and is not routable.
    """
    if not instance.container_id:
        return None
    return instance.container_id[:12]


def _live_deployment(session: Session, service_id: uuid.UUID) -> Deployment | None:
    """The Deployment currently serving a Service.

    D11 makes at most one Deployment `live` per service, but a render can land
    mid-shift, so ties are broken deterministically by liveness time and then by
    id rather than left to row order.
    """
    candidates = session.exec(
        select(Deployment).where(
            Deployment.service_id == service_id,
            Deployment.status == DeploymentStatus.LIVE,
        )
    ).all()
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda d: (d.became_live_at or d.created_at, str(d.id)),
    )


def _healthy_instances(session: Session, deployment_id: uuid.UUID) -> tuple[Instance, ...]:
    rows = session.exec(
        select(Instance).where(
            Instance.deployment_id == deployment_id,
            Instance.status == InstanceStatus.HEALTHY,
        )
    ).all()
    return tuple(sorted(rows, key=lambda i: str(i.id)))


def _compose_service_instances(
    session: Session, deployment: Deployment, mapping: GitHubImportService
) -> tuple[Instance, ...]:
    """Resolve one graph member from one immutable Compose release.

    ``GitHubImportService.container_id`` is a convenience projection for the
    current release and changes with every deployment. ``Instance`` preserves
    the Compose service name for its own release, which lets a restored
    historical deployment route to its original app or add-on container.
    The id fallback keeps releases created before the migration routable.
    """
    healthy = _healthy_instances(session, deployment.id)
    named = tuple(
        instance for instance in healthy if instance.compose_service == mapping.compose_service
    )
    if named:
        return named
    if mapping.container_id:
        return tuple(
            instance for instance in healthy if instance.container_id == mapping.container_id
        )
    return ()


def _compose_child_target(session: Session, service: Service) -> Target | None:
    """Resolve a public Compose child through its owner's live release.

    Imported Compose releases are one atomic deployment, but a public child
    (for example Grafana) must still route to *its* container rather than the
    app container that owns the release.  The mapping is only updated after a
    candidate is healthy, preserving the previous child route on failure.
    """
    mapping = session.exec(
        select(GitHubImportService).where(GitHubImportService.service_id == service.id)
    ).first()
    if mapping is None:
        return None
    imported = session.get(GitHubImport, mapping.github_import_id)
    if imported is None or imported.app_service_id == service.id:
        return None
    deployment = _live_deployment(session, imported.app_service_id)
    if deployment is None:
        return Target(service=service, deployment=deployment, instances=())
    instances = _compose_service_instances(session, deployment, mapping)
    return Target(service=service, deployment=deployment, instances=instances)


def _compose_app_target(
    session: Session,
    service: Service,
    deployment: Deployment | None = None,
) -> Target | None:
    """Resolve an imported Compose application's domain to its app container.

    A Compose release has one owning app deployment and one instance row per
    Compose container.  The generic service resolver cannot route every
    healthy instance from that deployment: databases and caches share the
    release but are not HTTP backends for the app's public domain.
    """
    imported = session.exec(
        select(GitHubImport).where(GitHubImport.app_service_id == service.id)
    ).first()
    if imported is None:
        return None
    deployment = deployment or _live_deployment(session, service.id)
    mapping = session.exec(
        select(GitHubImportService).where(
            GitHubImportService.github_import_id == imported.id,
            GitHubImportService.service_id == service.id,
        )
    ).first()
    if deployment is None or mapping is None:
        return Target(service=service, deployment=deployment, instances=())
    instances = _compose_service_instances(session, deployment, mapping)
    return Target(service=service, deployment=deployment, instances=instances)


def resolve_target(session: Session, domain: Domain) -> Target:
    """Resolve one Domain to the set of containers that should serve it.

    Two modes, both implemented even though Phase 1 only ever creates the first:

    - `target_type=service` (Railway semantics) — resolve to whatever Deployment
      of that Service is currently `live`, then to that Deployment's healthy
      Instances. The hostname follows the service across deploys.
    - `target_type=deployment` (Vercel semantics) — pinned to one immutable
      Deployment forever, regardless of what has since gone live. This is what
      makes rollback an UPDATE on a Domain row instead of a rebuild.
    """
    if domain.target_type == DomainTargetType.DEPLOYMENT:
        if domain.deployment_id is None:
            return Target(service=None, deployment=None, instances=())
        deployment = session.get(Deployment, domain.deployment_id)
        if deployment is None:
            return Target(service=None, deployment=None, instances=())
        service = session.get(Service, deployment.service_id)
        if service is not None:
            compose_app = _compose_app_target(session, service, deployment)
            if compose_app is not None:
                return compose_app
        return Target(
            service=service,
            deployment=deployment,
            instances=_healthy_instances(session, deployment.id),
        )

    if domain.service_id is None:
        return Target(service=None, deployment=None, instances=())
    service = session.get(Service, domain.service_id)
    if service is None:
        return Target(service=None, deployment=None, instances=())
    compose_child = _compose_child_target(session, service)
    if compose_child is not None:
        return compose_child
    compose_app = _compose_app_target(session, service)
    if compose_app is not None:
        return compose_app
    deployment = _live_deployment(session, service.id)
    if deployment is None:
        # The service exists and the domain is real; there is just nothing live
        # behind it yet. Keep the service so container_port stays available and
        # the router is still emitted (see render_router).
        return Target(service=service, deployment=None, instances=())
    return Target(
        service=service,
        deployment=deployment,
        instances=_healthy_instances(session, deployment.id),
    )


def render_router(domain: Domain, target: Target, settings: Settings) -> dict[str, object]:
    """The dynamic-config document for exactly one Domain.

    A Domain whose target has no healthy instances still gets a router, with an
    empty server list. Traefik answers such a request with 503 Service
    Unavailable rather than the 404 it would return if the router were omitted.
    That is the deliberate choice: the hostname *does* exist, it just has
    nothing behind it right now, and 503 is the honest, retryable answer — a 404
    tells the user their URL is wrong. Keeping the router also keeps the file
    (and, under acme, the certificate) stable instead of churning it in and out
    of the directory every time a service is briefly empty.
    """
    name = f"{NAME_PREFIX}-{domain.id}"
    router: dict[str, object] = {
        "rule": f"Host(`{domain.hostname}`)",
        "service": name,
    }
    if settings.tls_mode == "acme" and domain.tls_enabled:
        router["entryPoints"] = [HTTPS_ENTRYPOINT]
        router["tls"] = {
            "certResolver": CERT_RESOLVER,
            "domains": [{"main": domain.hostname}],
        }
    else:
        # D8: dev runs tls_mode=off on {service}.{env}.localhost, plain HTTP.
        router["entryPoints"] = [HTTP_ENTRYPOINT]

    servers = [{"url": url} for url in target.backend_urls]
    return {
        "http": {
            "routers": {name: router},
            "services": {name: {"loadBalancer": {"servers": servers}}},
        }
    }


def _render_bytes(domain: Domain, target: Target, settings: Settings) -> bytes:
    document = render_router(domain, target, settings)
    header = f"# Generated by Rudder for Domain {domain.id} ({domain.hostname}). Do not edit.\n"
    body = yaml.safe_dump(document, sort_keys=True, default_flow_style=False, allow_unicode=True)
    return (header + body).encode("utf-8")


def _router_file_name(domain_id: uuid.UUID) -> str:
    return f"{domain_id}{FILE_SUFFIX}"


def _is_owned_file(path: Path) -> bool:
    """True only for router files this module writes.

    Ownership is the filename convention from Phase 1 step 8: a UUID stem with a
    `.yml` suffix. Anything else in the directory — `.gitkeep`, a hand-written
    middlewares file, another tool's config — is not ours and is never touched.
    The directory is never emptied wholesale.
    """
    return path.suffix == FILE_SUFFIX and _is_uuid(path.stem) and path.is_file()


def _is_own_temp_file(path: Path) -> bool:
    """True for a temp file left behind by a crashed render of ours.

    Matches exactly the name `_write_atomic` builds: `.{uuid}.yml.tmp`.
    """
    name = path.name
    inner = name.removeprefix(".").removesuffix(f"{FILE_SUFFIX}{TMP_SUFFIX}")
    if name == inner or not name.startswith(".") or not name.endswith(TMP_SUFFIX):
        return False
    return _is_uuid(inner) and path.is_file()


def _is_uuid(value: str) -> bool:
    """Exact match against the canonical form we write, so a merely
    UUID-parseable name someone else chose is still not treated as ours."""
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _write_atomic(path: Path, content: bytes) -> None:
    """Replace `path` with `content` without any reader ever seeing a partial file.

    The temp file gets a `.tmp` suffix so Traefik's file provider ignores it
    entirely — it only loads `.yml`, `.yaml`, `.toml` and `.json`. `os.replace`
    is atomic within a filesystem, and the temp file lives in the same directory
    as its target, so the swap is a rename, never a copy.
    """
    tmp = path.with_name(f".{path.name}{TMP_SUFFIX}")
    with tmp.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _sync_render(directory: Path, desired: dict[str, bytes]) -> None:
    """The whole filesystem side of a render. Runs off the event loop."""
    directory.mkdir(parents=True, exist_ok=True)

    for file_name, content in desired.items():
        path = directory / file_name
        if path.is_file() and path.read_bytes() == content:
            # Byte-identical: leave the inode alone so Traefik does not reload.
            continue
        _write_atomic(path, content)

    for path in directory.iterdir():
        if _is_owned_file(path) and path.name not in desired:
            # A Domain row that no longer exists. Its router goes away with it.
            path.unlink()
        elif _is_own_temp_file(path):
            path.unlink()


async def render_all(session: Session, settings: Settings | None = None) -> None:
    """Regenerate every dynamic config file. Idempotent, whole-dir rewrite.

    Called on deploy success, on domain create/delete, and on instance state
    change. Safe to call repeatedly: two identical calls produce byte-identical
    files and no filesystem writes at all after the first. Safe to call
    concurrently: renders are serialised by `_render_lock`, and since the output
    is a pure function of DB state the later render wins and is correct.
    """
    settings = settings or get_settings()
    directory = Path(settings.traefik_dynamic_dir)

    domains = session.exec(select(Domain)).all()
    desired: dict[str, bytes] = {}
    for domain in domains:
        target = resolve_target(session, domain)
        desired[_router_file_name(domain.id)] = _render_bytes(domain, target, settings)

    async with _render_lock:
        await asyncio.to_thread(_sync_render, directory, desired)
