from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast
from uuid import UUID
import datetime






T = TypeVar("T", bound="EnvironmentRead")



@_attrs_define
class EnvironmentRead:
    """
        Attributes:
            id (UUID):
            project_id (UUID):
            name (str):
            is_production (bool):
            created_at (datetime.datetime):
            github_pr_number (None | int): Pull request number for an ephemeral PR environment.
     """

    id: UUID
    project_id: UUID
    name: str
    is_production: bool
    github_pr_number: None | int
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        project_id = str(self.project_id)

        name = self.name

        is_production = self.is_production

        created_at = self.created_at.isoformat()

        github_pr_number = self.github_pr_number


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "project_id": project_id,
            "name": name,
            "is_production": is_production,
            "github_pr_number": github_pr_number,
            "created_at": created_at,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))




        project_id = UUID(d.pop("project_id"))




        name = d.pop("name")

        is_production = d.pop("is_production")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        def _parse_github_pr_number(data: object) -> None | int:
            if data is None:
                return data
            return cast(int, data)

        github_pr_number = _parse_github_pr_number(d.pop("github_pr_number"))


        environment_read = cls(
            id=id,
            project_id=project_id,
            name=name,
            is_production=is_production,
            github_pr_number=github_pr_number,
            created_at=created_at,
        )


        environment_read.additional_properties = d
        return environment_read

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
