"""Clone, detect, render, build, push.

Everything here writes to the build log store as it goes, so the SSE endpoint
has something to tail. Nothing here touches the database — the caller owns
Deployment state transitions.

The build runs as a subprocess (`buildctl`) talking to the buildkitd service.
buildkitd shares the registry's network namespace, which is why the image tag
resolves identically for the push here and the pull on the node later.
"""

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

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


@dataclass(frozen=True)
class BuildResult:
    image_tag: str
    commit_sha: str


async def build_image(
    request: BuildRequest,
    store: BuildLogStore,
    settings: Settings,
) -> BuildResult:
    """Clone at a SHA, produce an image, push it. Raises BuildFailed."""
    await store.open_log(request.deployment_id)
    workdir = Path(tempfile.mkdtemp(prefix=f"rudder-build-{request.service_id}-"))
    try:
        sha = request.commit_sha or await _resolve_branch_head(request, store, settings)
        repo_dir = workdir / "repo"
        await _clone_at_sha(request, sha, repo_dir, store, settings)

        detection = detect(repo_dir, request.dockerfile_path)
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
            dockerfile_dir = workdir / "generated"
            dockerfile_name = "Dockerfile"
            rendered = render_dockerfile(
                detection,
                container_port=request.container_port,
                start_command=request.start_command,
            )
            await asyncio.to_thread(_write_dockerfile, dockerfile_dir, dockerfile_name, rendered)
            await _log(store, request, f"detected {detection.language}; generated Dockerfile")
            await _log(store, request, rendered)

        image_tag = f"{settings.registry}/{request.service_id}:{sha}"
        await _buildctl(
            request,
            context=repo_dir,
            dockerfile_dir=dockerfile_dir,
            dockerfile_name=dockerfile_name,
            image_tag=image_tag,
            store=store,
            settings=settings,
        )
        await store.close_log(request.deployment_id, "succeeded")
        return BuildResult(image_tag=image_tag, commit_sha=sha)
    except BuildFailed as exc:
        await _log(store, request, f"BUILD FAILED: {exc}")
        await store.close_log(request.deployment_id, "failed")
        raise
    except Exception as exc:
        # Unexpected failures still have to close the log, or every SSE reader
        # attached to this build hangs until its client gives up.
        await _log(store, request, f"BUILD FAILED: {type(exc).__name__}")
        await store.close_log(request.deployment_id, "failed")
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


# ------------------------------------------------------------------ buildkit


async def _buildctl(
    request: BuildRequest,
    *,
    context: Path,
    dockerfile_dir: Path,
    dockerfile_name: str,
    image_tag: str,
    store: BuildLogStore,
    settings: Settings,
) -> None:
    output_spec = ",".join(
        [
            "type=image",
            f"name={image_tag}",
            "push=true",
            # The local registry runs without TLS (D7). The matching host-daemon
            # insecure-registries entry is the documented one-time prerequisite.
            "registry.insecure=true",
        ]
    )
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
    await _log(store, request, f"building {image_tag}")
    code = await _stream(command, request, store, settings, timeout=_BUILD_TIMEOUT_SECONDS)
    if code != 0:
        raise BuildFailed(
            "Image build failed. The build log above has the reason. "
            "If it mentions an HTTPS/TLS error talking to the registry, the "
            "host Docker daemon is missing localhost:5000 in insecure-registries."
        )
    await _log(store, request, f"pushed {image_tag}")


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
