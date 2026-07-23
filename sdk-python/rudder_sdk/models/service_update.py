from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.service_kind import ServiceKind
from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.service_update_build_config_type_0 import ServiceUpdateBuildConfigType0





T = TypeVar("T", bound="ServiceUpdate")



@_attrs_define
class ServiceUpdate:
    """ Body of ``PATCH /services/{id}``. Absent fields are left alone.

    Renaming rewrites the service's system domain hostname. Moving the node on
    the canvas (``canvas_x`` / ``canvas_y``) is pure metadata per D6 — it
    persists and triggers nothing.

        Attributes:
            name (None | str | Unset):
            kind (None | ServiceKind | Unset):
            source_repo (None | str | Unset): owner/repo on GitHub. Null for a service with no source (e.g. a database).
            source_branch (None | str | Unset): Branch that a push webhook deploys from.
            dockerfile_path (None | str | Unset): Path to a Dockerfile in the repo. Null means one is generated.
            build_config (None | ServiceUpdateBuildConfigType0 | Unset): Free-form build knobs consumed by the builder.
            start_command (None | str | Unset): Overrides the image's CMD. Null keeps the image default.
            container_port (int | None | Unset): D1 — the port the app listens on. Traefik routes here.
            health_check_path (None | str | Unset): Path polled until it returns 200 after a deploy.
            health_check_port (int | None | Unset): Port for the health check. Null means use container_port (D1).
            cpu_limit (float | None | Unset):
            memory_limit_mb (int | None | Unset):
            replica_count (int | None | Unset):
            canvas_x (float | None | Unset): D6 — UI-only canvas coordinate. Writable, and never a deploy trigger.
            canvas_y (float | None | Unset): D6 — UI-only canvas coordinate. Writable, and never a deploy trigger.
     """

    name: None | str | Unset = UNSET
    kind: None | ServiceKind | Unset = UNSET
    source_repo: None | str | Unset = UNSET
    source_branch: None | str | Unset = UNSET
    dockerfile_path: None | str | Unset = UNSET
    build_config: None | ServiceUpdateBuildConfigType0 | Unset = UNSET
    start_command: None | str | Unset = UNSET
    container_port: int | None | Unset = UNSET
    health_check_path: None | str | Unset = UNSET
    health_check_port: int | None | Unset = UNSET
    cpu_limit: float | None | Unset = UNSET
    memory_limit_mb: int | None | Unset = UNSET
    replica_count: int | None | Unset = UNSET
    canvas_x: float | None | Unset = UNSET
    canvas_y: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.service_update_build_config_type_0 import ServiceUpdateBuildConfigType0
        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        kind: None | str | Unset
        if isinstance(self.kind, Unset):
            kind = UNSET
        elif isinstance(self.kind, ServiceKind):
            kind = self.kind.value
        else:
            kind = self.kind

        source_repo: None | str | Unset
        if isinstance(self.source_repo, Unset):
            source_repo = UNSET
        else:
            source_repo = self.source_repo

        source_branch: None | str | Unset
        if isinstance(self.source_branch, Unset):
            source_branch = UNSET
        else:
            source_branch = self.source_branch

        dockerfile_path: None | str | Unset
        if isinstance(self.dockerfile_path, Unset):
            dockerfile_path = UNSET
        else:
            dockerfile_path = self.dockerfile_path

        build_config: dict[str, Any] | None | Unset
        if isinstance(self.build_config, Unset):
            build_config = UNSET
        elif isinstance(self.build_config, ServiceUpdateBuildConfigType0):
            build_config = self.build_config.to_dict()
        else:
            build_config = self.build_config

        start_command: None | str | Unset
        if isinstance(self.start_command, Unset):
            start_command = UNSET
        else:
            start_command = self.start_command

        container_port: int | None | Unset
        if isinstance(self.container_port, Unset):
            container_port = UNSET
        else:
            container_port = self.container_port

        health_check_path: None | str | Unset
        if isinstance(self.health_check_path, Unset):
            health_check_path = UNSET
        else:
            health_check_path = self.health_check_path

        health_check_port: int | None | Unset
        if isinstance(self.health_check_port, Unset):
            health_check_port = UNSET
        else:
            health_check_port = self.health_check_port

        cpu_limit: float | None | Unset
        if isinstance(self.cpu_limit, Unset):
            cpu_limit = UNSET
        else:
            cpu_limit = self.cpu_limit

        memory_limit_mb: int | None | Unset
        if isinstance(self.memory_limit_mb, Unset):
            memory_limit_mb = UNSET
        else:
            memory_limit_mb = self.memory_limit_mb

        replica_count: int | None | Unset
        if isinstance(self.replica_count, Unset):
            replica_count = UNSET
        else:
            replica_count = self.replica_count

        canvas_x: float | None | Unset
        if isinstance(self.canvas_x, Unset):
            canvas_x = UNSET
        else:
            canvas_x = self.canvas_x

        canvas_y: float | None | Unset
        if isinstance(self.canvas_y, Unset):
            canvas_y = UNSET
        else:
            canvas_y = self.canvas_y


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
        })
        if name is not UNSET:
            field_dict["name"] = name
        if kind is not UNSET:
            field_dict["kind"] = kind
        if source_repo is not UNSET:
            field_dict["source_repo"] = source_repo
        if source_branch is not UNSET:
            field_dict["source_branch"] = source_branch
        if dockerfile_path is not UNSET:
            field_dict["dockerfile_path"] = dockerfile_path
        if build_config is not UNSET:
            field_dict["build_config"] = build_config
        if start_command is not UNSET:
            field_dict["start_command"] = start_command
        if container_port is not UNSET:
            field_dict["container_port"] = container_port
        if health_check_path is not UNSET:
            field_dict["health_check_path"] = health_check_path
        if health_check_port is not UNSET:
            field_dict["health_check_port"] = health_check_port
        if cpu_limit is not UNSET:
            field_dict["cpu_limit"] = cpu_limit
        if memory_limit_mb is not UNSET:
            field_dict["memory_limit_mb"] = memory_limit_mb
        if replica_count is not UNSET:
            field_dict["replica_count"] = replica_count
        if canvas_x is not UNSET:
            field_dict["canvas_x"] = canvas_x
        if canvas_y is not UNSET:
            field_dict["canvas_y"] = canvas_y

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.service_update_build_config_type_0 import ServiceUpdateBuildConfigType0
        d = dict(src_dict)
        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))


        def _parse_kind(data: object) -> None | ServiceKind | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                kind_type_0 = ServiceKind(data)



                return kind_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ServiceKind | Unset, data)

        kind = _parse_kind(d.pop("kind", UNSET))


        def _parse_source_repo(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_repo = _parse_source_repo(d.pop("source_repo", UNSET))


        def _parse_source_branch(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_branch = _parse_source_branch(d.pop("source_branch", UNSET))


        def _parse_dockerfile_path(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dockerfile_path = _parse_dockerfile_path(d.pop("dockerfile_path", UNSET))


        def _parse_build_config(data: object) -> None | ServiceUpdateBuildConfigType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                build_config_type_0 = ServiceUpdateBuildConfigType0.from_dict(data)



                return build_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ServiceUpdateBuildConfigType0 | Unset, data)

        build_config = _parse_build_config(d.pop("build_config", UNSET))


        def _parse_start_command(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        start_command = _parse_start_command(d.pop("start_command", UNSET))


        def _parse_container_port(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        container_port = _parse_container_port(d.pop("container_port", UNSET))


        def _parse_health_check_path(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        health_check_path = _parse_health_check_path(d.pop("health_check_path", UNSET))


        def _parse_health_check_port(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        health_check_port = _parse_health_check_port(d.pop("health_check_port", UNSET))


        def _parse_cpu_limit(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        cpu_limit = _parse_cpu_limit(d.pop("cpu_limit", UNSET))


        def _parse_memory_limit_mb(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        memory_limit_mb = _parse_memory_limit_mb(d.pop("memory_limit_mb", UNSET))


        def _parse_replica_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        replica_count = _parse_replica_count(d.pop("replica_count", UNSET))


        def _parse_canvas_x(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        canvas_x = _parse_canvas_x(d.pop("canvas_x", UNSET))


        def _parse_canvas_y(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        canvas_y = _parse_canvas_y(d.pop("canvas_y", UNSET))


        service_update = cls(
            name=name,
            kind=kind,
            source_repo=source_repo,
            source_branch=source_branch,
            dockerfile_path=dockerfile_path,
            build_config=build_config,
            start_command=start_command,
            container_port=container_port,
            health_check_path=health_check_path,
            health_check_port=health_check_port,
            cpu_limit=cpu_limit,
            memory_limit_mb=memory_limit_mb,
            replica_count=replica_count,
            canvas_x=canvas_x,
            canvas_y=canvas_y,
        )


        service_update.additional_properties = d
        return service_update

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
