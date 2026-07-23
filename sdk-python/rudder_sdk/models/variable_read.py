from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID
import datetime






T = TypeVar("T", bound="VariableRead")



@_attrs_define
class VariableRead:
    """ A variable, minus its value. This is the entire public shape.

        Attributes:
            id (UUID):
            service_id (UUID):
            key (str):
            is_reference (bool): True when the value is a ${{service.VAR}} reference.
            created_at (datetime.datetime):
     """

    id: UUID
    service_id: UUID
    key: str
    is_reference: bool
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        service_id = str(self.service_id)

        key = self.key

        is_reference = self.is_reference

        created_at = self.created_at.isoformat()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "service_id": service_id,
            "key": key,
            "is_reference": is_reference,
            "created_at": created_at,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))




        service_id = UUID(d.pop("service_id"))




        key = d.pop("key")

        is_reference = d.pop("is_reference")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        variable_read = cls(
            id=id,
            service_id=service_id,
            key=key,
            is_reference=is_reference,
            created_at=created_at,
        )


        variable_read.additional_properties = d
        return variable_read

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
