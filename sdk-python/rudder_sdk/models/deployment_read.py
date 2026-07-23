from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.deployment_status import DeploymentStatus
from typing import cast
from uuid import UUID






T = TypeVar("T", bound="DeploymentRead")



@_attrs_define
class DeploymentRead:
    """
        Attributes:
            id (UUID):
            service_id (UUID):
            status (DeploymentStatus):
            image_tag (None | str):
            commit_sha (None | str):
            error_message (None | str):
            created_at (Any):
            became_live_at (Any):
     """

    id: UUID
    service_id: UUID
    status: DeploymentStatus
    image_tag: None | str
    commit_sha: None | str
    error_message: None | str
    created_at: Any
    became_live_at: Any
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        service_id = str(self.service_id)

        status = self.status.value

        image_tag: None | str
        image_tag = self.image_tag

        commit_sha: None | str
        commit_sha = self.commit_sha

        error_message: None | str
        error_message = self.error_message

        created_at = self.created_at

        became_live_at = self.became_live_at


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "service_id": service_id,
            "status": status,
            "image_tag": image_tag,
            "commit_sha": commit_sha,
            "error_message": error_message,
            "created_at": created_at,
            "became_live_at": became_live_at,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))




        service_id = UUID(d.pop("service_id"))




        status = DeploymentStatus(d.pop("status"))




        def _parse_image_tag(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        image_tag = _parse_image_tag(d.pop("image_tag"))


        def _parse_commit_sha(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        commit_sha = _parse_commit_sha(d.pop("commit_sha"))


        def _parse_error_message(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error_message = _parse_error_message(d.pop("error_message"))


        created_at = d.pop("created_at")

        became_live_at = d.pop("became_live_at")

        deployment_read = cls(
            id=id,
            service_id=service_id,
            status=status,
            image_tag=image_tag,
            commit_sha=commit_sha,
            error_message=error_message,
            created_at=created_at,
            became_live_at=became_live_at,
        )


        deployment_read.additional_properties = d
        return deployment_read

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
