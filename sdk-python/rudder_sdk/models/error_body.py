from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.error_body_details import ErrorBodyDetails





T = TypeVar("T", bound="ErrorBody")



@_attrs_define
class ErrorBody:
    """ The uniform error shape from the PRD's API design rules.

    Declared here because auth is the first workstream to need it. When a shared
    ``rudder_cp/errors.py`` appears, this moves there unchanged.

        Attributes:
            code (str):
            message (str):
            details (ErrorBodyDetails | Unset):
     """

    code: str
    message: str
    details: ErrorBodyDetails | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.error_body_details import ErrorBodyDetails
        code = self.code

        message = self.message

        details: dict[str, Any] | Unset = UNSET
        if not isinstance(self.details, Unset):
            details = self.details.to_dict()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "code": code,
            "message": message,
        })
        if details is not UNSET:
            field_dict["details"] = details

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.error_body_details import ErrorBodyDetails
        d = dict(src_dict)
        code = d.pop("code")

        message = d.pop("message")

        _details = d.pop("details", UNSET)
        details: ErrorBodyDetails | Unset
        if isinstance(_details,  Unset):
            details = UNSET
        else:
            details = ErrorBodyDetails.from_dict(_details)




        error_body = cls(
            code=code,
            message=message,
            details=details,
        )


        error_body.additional_properties = d
        return error_body

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
