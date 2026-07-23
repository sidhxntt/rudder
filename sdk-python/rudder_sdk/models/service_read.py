from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.service_kind import ServiceKind
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
  from ..models.service_read_build_config import ServiceReadBuildConfig





T = TypeVar("T", bound="ServiceRead")



@_attrs_define
class ServiceRead:
    """
        Attributes:
            id (UUID):
            environment_id (UUID):
            name (str):
            kind (ServiceKind):
            source_repo (None | str):
            source_branch (str):
            dockerfile_path (None | str):
            build_config (ServiceReadBuildConfig):
            start_command (None | str):
            container_port (int):
            health_check_path (str):
            health_check_port (int | None):
            cpu_limit (float):
            memory_limit_mb (int):
            replica_count (int):
            canvas_x (float):
            canvas_y (float):
            created_at (datetime.datetime):
     """

    id: UUID
    environment_id: UUID
    name: str
    kind: ServiceKind
    source_repo: None | str
    source_branch: str
    dockerfile_path: None | str
    build_config: ServiceReadBuildConfig
    start_command: None | str
    container_port: int
    health_check_path: str
    health_check_port: int | None
    cpu_limit: float
    memory_limit_mb: int
    replica_count: int
    canvas_x: float
    canvas_y: float
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.service_read_build_config import ServiceReadBuildConfig
        id = str(self.id)

        environment_id = str(self.environment_id)

        name = self.name

        kind = self.kind.value

        source_repo: None | str
        source_repo = self.source_repo

        source_branch = self.source_branch

        dockerfile_path: None | str
        dockerfile_path = self.dockerfile_path

        build_config = self.build_config.to_dict()

        start_command: None | str
        start_command = self.start_command

        container_port = self.container_port

        health_check_path = self.health_check_path

        health_check_port: int | None
        health_check_port = self.health_check_port

        cpu_limit = self.cpu_limit

        memory_limit_mb = self.memory_limit_mb

        replica_count = self.replica_count

        canvas_x = self.canvas_x

        canvas_y = self.canvas_y

        created_at = self.created_at.isoformat()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "environment_id": environment_id,
            "name": name,
            "kind": kind,
            "source_repo": source_repo,
            "source_branch": source_branch,
            "dockerfile_path": dockerfile_path,
            "build_config": build_config,
            "start_command": start_command,
            "container_port": container_port,
            "health_check_path": health_check_path,
            "health_check_port": health_check_port,
            "cpu_limit": cpu_limit,
            "memory_limit_mb": memory_limit_mb,
            "replica_count": replica_count,
            "canvas_x": canvas_x,
            "canvas_y": canvas_y,
            "created_at": created_at,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.service_read_build_config import ServiceReadBuildConfig
        d = dict(src_dict)
        id = UUID(d.pop("id"))




        environment_id = UUID(d.pop("environment_id"))




        name = d.pop("name")

        kind = ServiceKind(d.pop("kind"))




        def _parse_source_repo(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_repo = _parse_source_repo(d.pop("source_repo"))


        source_branch = d.pop("source_branch")

        def _parse_dockerfile_path(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        dockerfile_path = _parse_dockerfile_path(d.pop("dockerfile_path"))


        build_config = ServiceReadBuildConfig.from_dict(d.pop("build_config"))




        def _parse_start_command(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        start_command = _parse_start_command(d.pop("start_command"))


        container_port = d.pop("container_port")

        health_check_path = d.pop("health_check_path")

        def _parse_health_check_port(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        health_check_port = _parse_health_check_port(d.pop("health_check_port"))


        cpu_limit = d.pop("cpu_limit")

        memory_limit_mb = d.pop("memory_limit_mb")

        replica_count = d.pop("replica_count")

        canvas_x = d.pop("canvas_x")

        canvas_y = d.pop("canvas_y")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        service_read = cls(
            id=id,
            environment_id=environment_id,
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
            created_at=created_at,
        )


        service_read.additional_properties = d
        return service_read

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
