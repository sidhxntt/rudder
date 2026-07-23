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
  from ..models.service_replace_build_config import ServiceReplaceBuildConfig





T = TypeVar("T", bound="ServiceReplace")



@_attrs_define
class ServiceReplace:
    """ Body of ``PUT /services/{id}``.

    Same fields as create, same defaults. A field left out is reset to its
    default — that is what makes PUT idempotent rather than a second PATCH.
    ``environment_id`` is not replaceable: moving a service between
    environments would change its hostname, its mesh subnet and its variables,
    and is not a Phase 1 operation.

        Attributes:
            name (str): Lowercase DNS label: a-z, 0-9 and hyphens, must start and end alphanumeric, 1-32 characters. This
                becomes a hostname label.
            kind (ServiceKind | Unset):
            source_repo (None | str | Unset): owner/repo on GitHub. Null for a service with no source (e.g. a database).
            source_branch (str | Unset): Branch that a push webhook deploys from. Default: 'main'.
            dockerfile_path (None | str | Unset): Path to a Dockerfile in the repo. Null means one is generated.
            build_config (ServiceReplaceBuildConfig | Unset): Free-form build knobs consumed by the builder.
            start_command (None | str | Unset): Overrides the image's CMD. Null keeps the image default.
            container_port (int | Unset): D1 — the port the app listens on. Traefik routes here. Default: 8080.
            health_check_path (str | Unset): Path polled until it returns 200 after a deploy. Default: '/'.
            health_check_port (int | None | Unset): Port for the health check. Null means use container_port (D1).
            cpu_limit (float | Unset): CPU cores. Default: 1.0.
            memory_limit_mb (int | Unset): Memory cap in MiB. Default: 512.
            replica_count (int | Unset): Desired instance count. Default: 1.
            canvas_x (float | Unset): D6 — UI-only canvas coordinate. Writable, and never a deploy trigger. Default: 0.0.
            canvas_y (float | Unset): D6 — UI-only canvas coordinate. Writable, and never a deploy trigger. Default: 0.0.
     """

    name: str
    kind: ServiceKind | Unset = UNSET
    source_repo: None | str | Unset = UNSET
    source_branch: str | Unset = 'main'
    dockerfile_path: None | str | Unset = UNSET
    build_config: ServiceReplaceBuildConfig | Unset = UNSET
    start_command: None | str | Unset = UNSET
    container_port: int | Unset = 8080
    health_check_path: str | Unset = '/'
    health_check_port: int | None | Unset = UNSET
    cpu_limit: float | Unset = 1.0
    memory_limit_mb: int | Unset = 512
    replica_count: int | Unset = 1
    canvas_x: float | Unset = 0.0
    canvas_y: float | Unset = 0.0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.service_replace_build_config import ServiceReplaceBuildConfig
        name = self.name

        kind: str | Unset = UNSET
        if not isinstance(self.kind, Unset):
            kind = self.kind.value


        source_repo: None | str | Unset
        if isinstance(self.source_repo, Unset):
            source_repo = UNSET
        else:
            source_repo = self.source_repo

        source_branch = self.source_branch

        dockerfile_path: None | str | Unset
        if isinstance(self.dockerfile_path, Unset):
            dockerfile_path = UNSET
        else:
            dockerfile_path = self.dockerfile_path

        build_config: dict[str, Any] | Unset = UNSET
        if not isinstance(self.build_config, Unset):
            build_config = self.build_config.to_dict()

        start_command: None | str | Unset
        if isinstance(self.start_command, Unset):
            start_command = UNSET
        else:
            start_command = self.start_command

        container_port = self.container_port

        health_check_path = self.health_check_path

        health_check_port: int | None | Unset
        if isinstance(self.health_check_port, Unset):
            health_check_port = UNSET
        else:
            health_check_port = self.health_check_port

        cpu_limit = self.cpu_limit

        memory_limit_mb = self.memory_limit_mb

        replica_count = self.replica_count

        canvas_x = self.canvas_x

        canvas_y = self.canvas_y


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
        })
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
        from ..models.service_replace_build_config import ServiceReplaceBuildConfig
        d = dict(src_dict)
        name = d.pop("name")

        _kind = d.pop("kind", UNSET)
        kind: ServiceKind | Unset
        if isinstance(_kind,  Unset):
            kind = UNSET
        else:
            kind = ServiceKind(_kind)




        def _parse_source_repo(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_repo = _parse_source_repo(d.pop("source_repo", UNSET))


        source_branch = d.pop("source_branch", UNSET)

        def _parse_dockerfile_path(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dockerfile_path = _parse_dockerfile_path(d.pop("dockerfile_path", UNSET))


        _build_config = d.pop("build_config", UNSET)
        build_config: ServiceReplaceBuildConfig | Unset
        if isinstance(_build_config,  Unset):
            build_config = UNSET
        else:
            build_config = ServiceReplaceBuildConfig.from_dict(_build_config)




        def _parse_start_command(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        start_command = _parse_start_command(d.pop("start_command", UNSET))


        container_port = d.pop("container_port", UNSET)

        health_check_path = d.pop("health_check_path", UNSET)

        def _parse_health_check_port(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        health_check_port = _parse_health_check_port(d.pop("health_check_port", UNSET))


        cpu_limit = d.pop("cpu_limit", UNSET)

        memory_limit_mb = d.pop("memory_limit_mb", UNSET)

        replica_count = d.pop("replica_count", UNSET)

        canvas_x = d.pop("canvas_x", UNSET)

        canvas_y = d.pop("canvas_y", UNSET)

        service_replace = cls(
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


        service_replace.additional_properties = d
        return service_replace

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
