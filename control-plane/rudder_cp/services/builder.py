"""Clone, detect, render, build, push.

Everything here writes to the build log store as it goes, so the SSE endpoint
has something to tail. Nothing here touches the database — the caller owns
Deployment state transitions.

The build runs as a subprocess (`buildctl`) talking to the buildkitd service.
buildkitd shares the registry's network namespace, which is why the image tag
resolves identically for the push here and the pull on the node later.
"""

import asyncio
import json
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import httpx

from rudder_cp.config import Settings
from rudder_cp.logs.store import BuildLogStore
from rudder_cp.services.detect import detect, render_dockerfile

# git is chatty on stderr for ordinary progress, so both streams are merged into
# the build log rather than treated as failure signal.
_GIT_TIMEOUT_SECONDS = 300
_BUILD_TIMEOUT_SECONDS = 1800


class BuildFailed(Exception):
    """A build failed for a reason the user needs to read.

    The message lands in Deployment.error_message and is shown in the UI
    verbatim, so it must never contain a token or a raw traceback.
    """


@dataclass(frozen=True)
class BuildRequest:
    deployment_id: UUID
    service_id: UUID
    source_repo: str
    source_branch: str
    commit_sha: str | None
    dockerfile_path: str | None
    container_port: int
    start_command: str | None
    # A short-lived GitHub App installation token. It is never logged and
    # overrides the legacy install-wide PAT when the import flow supplied it.
    git_token: str | None = None
    # Public, frontend-only Docker build args. Runtime secrets never flow here.
    build_env: object = None


@dataclass(frozen=True)
class BuildResult:
    image_tag: str
    commit_sha: str


_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_BUILD_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


def validate_gke_image(image: str) -> str:
    """Accept only immutable Artifact Registry references for GKE releases."""

    repository, separator, digest = image.partition("@")
    hostname = repository.split("/", 1)[0]
    if (
        not separator
        or not _SHA256_DIGEST.fullmatch(digest)
        or not hostname.endswith("-docker.pkg.dev")
        or repository.count("/") < 2
    ):
        raise ValueError(
            "GKE releases require an Artifact Registry immutable digest reference."
        )
    return image


def frontend_build_env(detection: object, raw: object) -> dict[str, str]:
    """Validate static-site build variables before they reach a Docker build."""
    frontend = getattr(detection, "frontend", None)
    if frontend is None or raw is None:
        return {}
    if not isinstance(raw, dict):
        raise BuildFailed("Static frontend build_env must be an object of public string values.")
    prefix = getattr(frontend, "public_env_prefix", "")
    result: dict[str, str] = {}
    for key, value in raw.items():
        if (
            not isinstance(key, str)
            or not _BUILD_ENV_KEY.fullmatch(key)
            or not key.startswith(prefix)
        ):
            raise BuildFailed(
                f"Static frontend build_env keys must use the {prefix} public prefix."
            )
        if not isinstance(value, str):
            raise BuildFailed(f"Static frontend build_env value for {key} must be a string.")
        result[key] = value
    return result


async def build_image(
    request: BuildRequest,
    store: BuildLogStore,
    settings: Settings,
) -> BuildResult:
    """Clone at a SHA, produce an image, push it. Raises BuildFailed."""
    workdir = Path(tempfile.mkdtemp(prefix=f"rudder-build-{request.service_id}-"))
    try:
        sha = request.commit_sha or await _resolve_branch_head(request, store, settings)
        repo_dir = workdir / "repo"
        await _clone_at_sha(request, sha, repo_dir, store, settings)

        detection = detect(repo_dir, request.dockerfile_path)
        # `build_env` is a frontend-preset feature. Explicit Dockerfiles are
        # user-owned and must not accidentally receive this separate channel.
        build_env = frontend_build_env(detection, request.build_env)
        request = replace(request, build_env=build_env)
        if detection.has_dockerfile and detection.dockerfile_path is not None:
            dockerfile_dir = repo_dir
            dockerfile_name = detection.dockerfile_path
            await _log(store, request, f"using repo Dockerfile: {dockerfile_name}")
        elif detection.is_unknown:
            raise BuildFailed(
                "Could not determine how to build this repository. "
                f"{detection.reason} Add a Dockerfile to the repo, or set "
                "dockerfile_path on the service."
            )
        else:
            # Keep generated Dockerfiles in the checked-out source tree.  The
            # local BuildKit path can use it directly, and the GKE Cloud Build
            # path can archive one self-contained build context.
            dockerfile_dir = repo_dir
            dockerfile_name = "Dockerfile"
            rendered = render_dockerfile(
                detection,
                container_port=request.container_port,
                start_command=request.start_command,
                build_env_keys=tuple(sorted(build_env)),
            )
            await asyncio.to_thread(_write_dockerfile, dockerfile_dir, dockerfile_name, rendered)
            await _log(store, request, f"detected {detection.language}; generated Dockerfile")
            await _log(store, request, rendered)

        repository = f"{settings.registry}/{request.service_id}"
        image_tag = f"{repository}:{sha}"
        image_reference = image_tag
        if settings.kubernetes_target == "gke":
            digest = await _cloud_build(
                request=request,
                context=repo_dir,
                dockerfile_name=dockerfile_name,
                image_tag=image_tag,
                store=store,
                settings=settings,
            )
            image_reference = validate_gke_image(f"{repository}@{digest}")
            await _log(store, request, f"pushed immutable image {image_reference}")
        else:
            await _buildctl(
                request,
                context=repo_dir,
                dockerfile_dir=dockerfile_dir,
                dockerfile_name=dockerfile_name,
                image_tag=image_tag,
                store=store,
                settings=settings,
            )
        return BuildResult(image_tag=image_reference, commit_sha=sha)
    except BuildFailed as exc:
        await _log(store, request, f"BUILD FAILED: {exc}")
        raise
    except Exception as exc:
        # Unexpected failures still have to close the log, or every SSE reader
        # attached to this build hangs until its client gives up.
        await _log(store, request, f"BUILD FAILED: {type(exc).__name__}")
        raise BuildFailed(f"Unexpected build error: {type(exc).__name__}") from exc
    finally:
        # Clones accumulate. Clean up on success, failure, and exception alike.
        shutil.rmtree(workdir, ignore_errors=True)


def _write_dockerfile(directory: Path, name: str, contents: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(contents, encoding="utf-8")


# ------------------------------------------------------------------ git


def _authed_remote(source_repo: str, settings: Settings, git_token: str | None = None) -> str:
    """Build the clone URL.

    D2: one install-wide token. It is embedded in the remote URL, which means it
    is visible in this host's process list — acceptable for a single-tenant
    install, and the reason `_scrub` exists so it never reaches a build log or
    an error message.
    """
    repo = source_repo.removeprefix("https://github.com/").removesuffix(".git")
    token = git_token or settings.github_token
    if token:
        return f"https://x-access-token:{token}@github.com/{repo}.git"
    return f"https://github.com/{repo}.git"


def _scrub(text: str, settings: Settings, git_token: str | None = None) -> str:
    for token in (settings.github_token, git_token):
        if token:
            text = text.replace(token, "***")
    return text


async def _resolve_branch_head(
    request: BuildRequest, store: BuildLogStore, settings: Settings
) -> str:
    """A manual deploy has no pushed SHA, so resolve the branch tip."""
    remote = _authed_remote(request.source_repo, settings, request.git_token)
    code, output = await _run(
        ["git", "ls-remote", remote, f"refs/heads/{request.source_branch}"],
        timeout=_GIT_TIMEOUT_SECONDS,
        settings=settings,
        git_token=request.git_token,
    )
    if code != 0 or not output.strip():
        raise BuildFailed(
            f"Could not resolve branch '{request.source_branch}' on {request.source_repo}. "
            "Check the repository name, the branch, and GITHUB_TOKEN access."
        )
    sha = output.split()[0]
    await _log(store, request, f"resolved {request.source_branch} -> {sha}")
    return sha


async def _clone_at_sha(
    request: BuildRequest,
    sha: str,
    repo_dir: Path,
    store: BuildLogStore,
    settings: Settings,
) -> None:
    """Fetch exactly one commit.

    `git clone` cannot check out an arbitrary SHA, and a full clone of a large
    repo on every push is wasted bandwidth, so this is init + fetch --depth 1.
    """
    await asyncio.to_thread(repo_dir.mkdir, parents=True)
    remote = _authed_remote(request.source_repo, settings, request.git_token)
    steps = [
        ["git", "init", "--quiet", str(repo_dir)],
        ["git", "-C", str(repo_dir), "remote", "add", "origin", remote],
        ["git", "-C", str(repo_dir), "fetch", "--depth", "1", "--quiet", "origin", sha],
        ["git", "-C", str(repo_dir), "checkout", "--quiet", "FETCH_HEAD"],
    ]
    for step in steps:
        code, output = await _run(
            step,
            timeout=_GIT_TIMEOUT_SECONDS,
            settings=settings,
            git_token=request.git_token,
        )
        if output.strip():
            await _log(store, request, output)
        if code != 0:
            raise BuildFailed(
                f"Failed to fetch {request.source_repo} at {sha[:8]}. "
                "Check that the commit exists and GITHUB_TOKEN can read the repo."
            )
    await _log(store, request, f"checked out {sha}")


# ------------------------------------------------------------------ Cloud Build (GKE)


_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)
_CLOUD_BUILD_API = "https://cloudbuild.googleapis.com/v1"
_GCS_UPLOAD_API = "https://storage.googleapis.com/upload/storage/v1"
_GCS_API = "https://storage.googleapis.com/storage/v1"


async def _cloud_build(
    *,
    request: BuildRequest,
    context: Path,
    dockerfile_name: str,
    image_tag: str,
    store: BuildLogStore,
    settings: Settings,
) -> str:
    """Build an immutable GKE image with the managed Cloud Build service.

    The control plane already checked out an exact Git SHA using the GitHub App
    installation token.  It archives that tree, so Cloud Build never needs a
    GitHub credential, and the archive is deleted after the build finishes.
    Workload Identity supplies the control-plane's short-lived Google token;
    no Google key is mounted in the Pod.
    """
    if not settings.gke_cloud_build_configured:
        raise BuildFailed(
            "GKE Cloud Build is not configured. Set the GCP project, region, source bucket, "
            "logs bucket, and dedicated build service account."
        )

    archive = context.parent / "source.tar.gz"
    await asyncio.to_thread(_archive_source, context, archive)
    object_name = f"sources/{request.deployment_id}/{request.commit_sha or 'manual'}.tar.gz"
    token: str | None = None
    try:
        token = await _gcp_access_token()
        await _upload_source_archive(
            archive=archive,
            bucket=settings.gcp_build_source_bucket,
            object_name=object_name,
            token=token,
        )
        await _log(store, request, f"uploaded immutable source archive gs://{settings.gcp_build_source_bucket}/{object_name}")
        build = await _start_cloud_build(
            project_id=settings.gcp_project_id,
            region=settings.gcp_region,
            source_bucket=settings.gcp_build_source_bucket,
            source_object=object_name,
            logs_bucket=settings.gcp_build_logs_bucket,
            build_service_account=settings.gcp_build_service_account,
            dockerfile_name=dockerfile_name,
            image_tag=image_tag,
            build_env=request.build_env if isinstance(request.build_env, dict) else {},
            token=token,
        )
        build_id = _cloud_build_id(build)
        await _log(store, request, f"Cloud Build {build_id} queued")
        completed = await _wait_for_cloud_build(
            project_id=settings.gcp_project_id,
            region=settings.gcp_region,
            build_id=build_id,
            token=token,
            request=request,
            store=store,
        )
        return _cloud_build_digest(completed, image_tag)
    finally:
        archive.unlink(missing_ok=True)
        # The source object is not an artifact.  Leave no mutable source copy
        # after the Cloud Build result has become the immutable deployment.
        if token is not None:
            try:
                await _delete_source_archive(
                    bucket=settings.gcp_build_source_bucket,
                    object_name=object_name,
                    token=token,
                )
            except BuildFailed:
                # A completed build remains valid even when cleanup has a transient
                # failure; retain an explicit log for operator follow-up.
                await _log(store, request, "warning: could not delete Cloud Build source archive")


def _archive_source(context: Path, destination: Path) -> None:
    """Create a reproducible build context without Git metadata."""
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(context.rglob("*")):
            relative = path.relative_to(context)
            if ".git" in relative.parts:
                continue
            archive.add(path, arcname=str(relative), recursive=False)


async def _gcp_access_token() -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(_METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
            response.raise_for_status()
            token = response.json().get("access_token")
    except (httpx.HTTPError, ValueError) as exc:
        raise BuildFailed(
            "Could not obtain a Workload Identity access token for Cloud Build."
        ) from exc
    if not isinstance(token, str) or not token:
        raise BuildFailed("Workload Identity did not return a Cloud Build access token.")
    return token


async def _upload_source_archive(
    *, archive: Path, bucket: str, object_name: str, token: str
) -> None:
    url = f"{_GCS_UPLOAD_API}/b/{bucket}/o"
    try:
        contents = await asyncio.to_thread(archive.read_bytes)
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                params={"uploadType": "media", "name": object_name},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/gzip",
                },
                content=contents,
            )
            response.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        raise BuildFailed("Could not upload the source archive for Cloud Build.") from exc


async def _delete_source_archive(*, bucket: str, object_name: str, token: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"{_GCS_API}/b/{bucket}/o/{quote(object_name, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code != 404:
                response.raise_for_status()
    except httpx.HTTPError as exc:
        raise BuildFailed("Could not delete the Cloud Build source archive.") from exc


async def _start_cloud_build(
    *,
    project_id: str,
    region: str,
    source_bucket: str,
    source_object: str,
    logs_bucket: str,
    build_service_account: str,
    dockerfile_name: str,
    image_tag: str,
    token: str,
    build_env: dict[str, str] | None = None,
) -> dict[str, object]:
    body = {
        "source": {"storageSource": {"bucket": source_bucket, "object": source_object}},
        "steps": [
            {
                "name": "gcr.io/cloud-builders/docker",
                "args": [
                    "build", "--tag", image_tag, "--file", dockerfile_name,
                    *[
                        item
                        for key, value in sorted((build_env or {}).items())
                        for item in ("--build-arg", f"{key}={value}")
                    ],
                    ".",
                ],
            }
        ],
        "images": [image_tag],
        "serviceAccount": f"projects/{project_id}/serviceAccounts/{build_service_account}",
        "logsBucket": f"gs://{logs_bucket}",
        "options": {"logging": "GCS_ONLY"},
        "timeout": f"{_BUILD_TIMEOUT_SECONDS}s",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{_CLOUD_BUILD_API}/projects/{project_id}/locations/{region}/builds",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise BuildFailed("Cloud Build could not start the image build.") from exc
    if not isinstance(payload, dict):
        raise BuildFailed("Cloud Build returned an invalid build response.")
    return payload


def _cloud_build_id(operation: dict[str, object]) -> str:
    """Extract the build identifier from Cloud Build's create Operation.

    ``projects.locations.builds.create`` returns a long-running Operation.
    Its metadata contains the queued Build, which is the resource that the
    regional ``builds.get`` endpoint accepts for status polling.
    """
    metadata = operation.get("metadata")
    if not isinstance(metadata, dict):
        raise BuildFailed("Cloud Build did not return operation metadata.")
    build = metadata.get("build")
    if not isinstance(build, dict):
        raise BuildFailed("Cloud Build did not return a queued build.")
    return _required_text(build, "id", "Cloud Build did not return a build id.")


async def _wait_for_cloud_build(
    *,
    project_id: str,
    region: str,
    build_id: str,
    token: str,
    request: BuildRequest,
    store: BuildLogStore,
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + _BUILD_TIMEOUT_SECONDS
    last_status = ""
    while True:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{_CLOUD_BUILD_API}/projects/{project_id}/locations/{region}/builds/{build_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BuildFailed("Could not read Cloud Build status.") from exc
        if not isinstance(payload, dict):
            raise BuildFailed("Cloud Build returned an invalid status response.")
        status = str(payload.get("status", "STATUS_UNKNOWN"))
        if status != last_status:
            await _log(store, request, f"Cloud Build {build_id}: {status}")
            last_status = status
        if status == "SUCCESS":
            return payload
        if status in {"FAILURE", "INTERNAL_ERROR", "TIMEOUT", "CANCELLED", "EXPIRED"}:
            raise BuildFailed(f"Cloud Build {build_id} ended with status {status}.")
        if asyncio.get_running_loop().time() >= deadline:
            raise BuildFailed(f"Cloud Build {build_id} timed out after {_BUILD_TIMEOUT_SECONDS}s.")
        await asyncio.sleep(2)


def _cloud_build_digest(build: dict[str, object], image_tag: str) -> str:
    results = build.get("results")
    if not isinstance(results, dict):
        raise BuildFailed("Cloud Build returned no image results.")
    images = results.get("images")
    if not isinstance(images, list):
        raise BuildFailed("Cloud Build returned no immutable image digest.")
    for image in images:
        if not isinstance(image, dict) or image.get("name") != image_tag:
            continue
        digest = image.get("digest")
        if isinstance(digest, str) and _SHA256_DIGEST.fullmatch(digest):
            return digest
    raise BuildFailed("Cloud Build returned no immutable image digest.")


def _required_text(payload: dict[str, object], key: str, error: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise BuildFailed(error)
    return value


# ------------------------------------------------------------------ buildkit (local only)


async def _buildctl(
    request: BuildRequest,
    *,
    context: Path,
    dockerfile_dir: Path,
    dockerfile_name: str,
    image_tag: str,
    store: BuildLogStore,
    settings: Settings,
    metadata_file: Path | None = None,
) -> str | None:
    output_spec = ",".join(
        [
            "type=image",
            f"name={image_tag}",
            "push=true",
        ]
    )
    if settings.kubernetes_target != "gke":
        # The local registry runs without TLS (D7). Production Artifact
        # Registry must use normal TLS and credentials instead.
        output_spec = f"{output_spec},registry.insecure=true"
    command = [
        "buildctl",
        "--addr",
        settings.buildkit_addr,
        "build",
        "--frontend",
        "dockerfile.v0",
        "--local",
        f"context={context}",
        "--local",
        f"dockerfile={dockerfile_dir}",
        "--opt",
        f"filename={dockerfile_name}",
        "--opt",
        f"build-arg:PORT={request.container_port}",
        "--output",
        output_spec,
        "--progress",
        "plain",
    ]
    for key, value in sorted(
        (request.build_env if isinstance(request.build_env, dict) else {}).items()
    ):
        command.extend(["--opt", f"build-arg:{key}={value}"])
    if metadata_file is not None:
        command.extend(["--metadata-file", str(metadata_file)])
    await _log(store, request, f"building {image_tag}")
    code = await _stream(command, request, store, settings, timeout=_BUILD_TIMEOUT_SECONDS)
    if code != 0:
        raise BuildFailed(
            "Image build failed. The build log above has the reason. "
            "If it mentions an HTTPS/TLS error talking to the registry, the "
            "host Docker daemon is missing localhost:5000 in insecure-registries."
        )
    await _log(store, request, f"pushed {image_tag}")
    if metadata_file is None:
        return None
    return _read_image_digest(metadata_file)


def _read_image_digest(metadata_file: Path) -> str:
    try:
        document = json.loads(metadata_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildFailed("BuildKit did not write image metadata.") from exc
    digest = document.get("containerimage.digest")
    if not isinstance(digest, str) or not _SHA256_DIGEST.fullmatch(digest):
        raise BuildFailed("BuildKit metadata has no valid immutable image digest.")
    return digest


# ------------------------------------------------------------------ subprocess


# ASYNC109: the timeout is a subprocess kill deadline, not a cancellation scope
# the caller should own — a half-killed git or buildctl process is worse than a
# late one. asyncio.wait_for is used internally to enforce it.
async def _run(
    command: list[str],
    *,
    timeout: int,  # noqa: ASYNC109
    settings: Settings,
    git_token: str | None = None,
) -> tuple[int, str]:
    """Run to completion, capturing merged output. For short commands only."""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise BuildFailed(f"'{command[0]}' timed out after {timeout}s") from None
    return process.returncode or 0, _scrub(
        stdout.decode(errors="replace"), settings, git_token
    )


async def _stream(
    command: list[str],
    request: BuildRequest,
    store: BuildLogStore,
    settings: Settings,
    *,
    timeout: int,  # noqa: ASYNC109 — see _run
) -> int:
    """Run, streaming output into the build log line by line as it arrives.

    The log is a file and the SSE endpoint tails that file, so a client that
    disconnects here changes nothing — this loop never looks at a connection.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None

    async def pump() -> None:
        async for raw in process.stdout:  # type: ignore[union-attr]
            await _log(
                store,
                request,
                _scrub(raw.decode(errors="replace").rstrip("\n"), settings, request.git_token),
            )

    try:
        await asyncio.wait_for(asyncio.gather(pump(), process.wait()), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise BuildFailed(f"Build timed out after {timeout}s") from None
    return process.returncode or 0


async def _log(store: BuildLogStore, request: BuildRequest, text: str) -> None:
    await store.append(request.deployment_id, text if text.endswith("\n") else f"{text}\n")
