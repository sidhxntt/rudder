from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset






T = TypeVar("T", bound="EnvironmentReplace")



@_attrs_define
class EnvironmentReplace:
    """ Body of ``PUT /environments/{id}``.

    ``wg_subnet`` is intentionally absent. It is allocated once at create time
    and never renumbered, so it cannot participate in a full replacement
    without breaking the mesh in Phase 3.

        Attributes:
            name (str): Lowercase DNS label: a-z, 0-9 and hyphens, must start and end alphanumeric, 1-32 characters. This
                becomes a hostname label.
            is_production (bool | Unset):  Default: False.
     """

    name: str
    is_production: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        name = self.name

        is_production = self.is_production


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
        })
        if is_production is not UNSET:
            field_dict["is_production"] = is_production

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        is_production = d.pop("is_production", UNSET)

        environment_replace = cls(
            name=name,
            is_production=is_production,
        )


        environment_replace.additional_properties = d
        return environment_replace

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
