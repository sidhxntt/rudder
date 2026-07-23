"""A fake Docker client, shaped like the parts of the SDK the agent uses.

Injected through `DockerOps(client)` — no module globals are monkeypatched, and
no test needs a live Docker daemon.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import docker.errors

# Builds a POST /containers body with overrides. See the `spec_body` fixture.
SpecBuilder = Callable[..., dict[str, Any]]


def make_attrs(
    status: str = "running",
    health: str | None = None,
    ip: str | None = "172.20.0.5",
    network: str = "rudder",
    exit_code: int | None = 0,
    image: str = "localhost:5000/svc:abc123",
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "Status": status,
        "ExitCode": exit_code,
        "StartedAt": "2026-07-23T10:00:00.000000000Z",
    }
    if health is not None:
        state["Health"] = {"Status": health}
    networks: dict[str, Any] = {network: {"IPAddress": ip or ""}}
    return {
        "State": state,
        "NetworkSettings": {"Networks": networks},
        "Config": {"Image": image},
    }


class FakeContainer:
    def __init__(
        self,
        container_id: str,
        name: str,
        attrs: dict[str, Any] | None = None,
        recorder: FakeDockerClient | None = None,
    ) -> None:
        self.id = container_id
        self.name = name
        self.attrs = attrs if attrs is not None else make_attrs()
        self.status = self.attrs["State"]["Status"]
        self._recorder = recorder
        self.started = False
        self.stopped = False
        self.removed = False

    def _record(self, call: str) -> None:
        if self._recorder is not None:
            self._recorder.record(call)

    def start(self) -> None:
        self._record("container.start")
        if self._recorder is not None and self._recorder.start_error is not None:
            raise self._recorder.start_error
        self.started = True

    def stop(self, timeout: int | None = None) -> None:
        self._record("container.stop")
        if self._recorder is not None and self._recorder.stop_error is not None:
            raise self._recorder.stop_error
        self.stopped = True
        self.attrs["State"]["Status"] = "exited"
        self.status = "exited"

    def remove(self, v: bool = False, force: bool = False) -> None:
        self._record("container.remove")
        self.removed = True
        if self._recorder is not None:
            self._recorder.containers._store.pop(self.id, None)


class _FakeContainerCollection:
    def __init__(self, client: FakeDockerClient) -> None:
        self._client = client
        self._store: dict[str, FakeContainer] = {}

    def add(self, container: FakeContainer) -> FakeContainer:
        self._store[container.id] = container
        return container

    def get(self, container_id: str) -> FakeContainer:
        self._client.record("containers.get")
        if self._client.get_error is not None:
            raise self._client.get_error
        try:
            return self._store[container_id]
        except KeyError as exc:
            raise docker.errors.NotFound(f"no such container: {container_id}") from exc

    def create(self, **kwargs: Any) -> FakeContainer:
        self._client.record("containers.create")
        self._client.create_kwargs = kwargs
        if self._client.create_error is not None:
            raise self._client.create_error
        name = str(kwargs.get("name"))
        if any(c.name == name for c in self._store.values()):
            raise docker.errors.APIError(
                "Conflict. The container name is already in use.",
                response=_FakeResponse(409),
            )
        container = FakeContainer(
            container_id=self._client.next_id,
            name=name,
            attrs=make_attrs(status="created", exit_code=None, image=str(kwargs.get("image"))),
            recorder=self._client,
        )
        return self.add(container)


class _FakeImageCollection:
    def __init__(self, client: FakeDockerClient) -> None:
        self._client = client
        self.present: set[str] = set()

    def get(self, image: str) -> object:
        self._client.record("images.get")
        if image not in self.present:
            raise docker.errors.ImageNotFound(f"no such image: {image}")
        return object()

    def pull(self, image: str) -> object:
        self._client.record("images.pull")
        if self._client.pull_error is not None:
            raise self._client.pull_error
        self.present.add(image)
        return object()


class _FakeResponse:
    """Minimal stand-in for the requests.Response docker.errors.APIError wants."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.reason = "Conflict" if status_code == 409 else "Error"
        self.url = "http+docker://localhost/v1.45/containers/create"

    def json(self) -> dict[str, Any]:
        return {}


class FakeDockerClient:
    """Records every call and the thread it ran on, so tests can assert the
    blocking SDK calls left the event loop thread."""

    def __init__(self, next_id: str = "c0ffee1234") -> None:
        self.containers = _FakeContainerCollection(self)
        self.images = _FakeImageCollection(self)
        self.next_id = next_id
        self.calls: list[str] = []
        self.call_threads: list[int] = []
        self.create_kwargs: dict[str, Any] | None = None

        # Injectable failures. None means "succeed".
        self.get_error: BaseException | None = None
        self.create_error: BaseException | None = None
        self.start_error: BaseException | None = None
        self.stop_error: BaseException | None = None
        self.pull_error: BaseException | None = None

        # Set to a threading.Event to make every call block until it is set.
        self.gate: threading.Event | None = None

    def record(self, call: str) -> None:
        self.calls.append(call)
        self.call_threads.append(threading.get_ident())
        if self.gate is not None:
            self.gate.wait(timeout=5)
