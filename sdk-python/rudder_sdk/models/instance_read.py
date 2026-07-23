from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.instance_status import InstanceStatus
from typing import cast
from uuid import UUID






T = TypeVar("T", bound="InstanceRead")



@_attrs_define
class InstanceRead:
    """
        Attributes:
            id (UUID):
            deployment_id (UUID):
            node_id (UUID):
            status (InstanceStatus):
            container_id (None | str):
            started_at (Any):
            stopped_at (Any):
     """

    id: UUID
    deployment_id: UUID
    node_id: UUID
    status: InstanceStatus
    container_id: None | str
    started_at: Any
    stopped_at: Any
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        deployment_id = str(self.deployment_id)

        node_id = str(self.node_id)

        status = self.status.value

        container_id: None | str
        container_id = self.container_id

        started_at = self.started_at

        stopped_at = self.stopped_at


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "deployment_id": deployment_id,
            "node_id": node_id,
            "status": status,
            "container_id": container_id,
            "started_at": started_at,
            "stopped_at": stopped_at,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))




        deployment_id = UUID(d.pop("deployment_id"))




        node_id = UUID(d.pop("node_id"))




        status = InstanceStatus(d.pop("status"))




        def _parse_container_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        container_id = _parse_container_id(d.pop("container_id"))


        started_at = d.pop("started_at")

        stopped_at = d.pop("stopped_at")

        instance_read = cls(
            id=id,
            deployment_id=deployment_id,
            node_id=node_id,
            status=status,
            container_id=container_id,
            started_at=started_at,
            stopped_at=stopped_at,
        )


        instance_read.additional_properties = d
        return instance_read

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
