from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset







T = TypeVar("T", bound="VariableUpsert")



@_attrs_define
class VariableUpsert:
    """ Body of ``PUT /services/{service_id}/variables/{key}``.

    Only the value. The key is in the path (that is what makes the PUT
    idempotent and addressable) and ``is_reference`` is derived from the value by
    the service layer, never asserted by the client.

        Attributes:
            value (str): Write-only. A literal value, or a reference of the form ${{service-name.VAR_NAME}} resolved against
                a sibling service in the same environment at deploy time. Never returned by any endpoint.
     """

    value: str





    def to_dict(self) -> dict[str, Any]:
        value = self.value


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "value": value,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        value = d.pop("value")

        variable_upsert = cls(
            value=value,
        )

        return variable_upsert
