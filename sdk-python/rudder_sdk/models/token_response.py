from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import Literal, cast






T = TypeVar("T", bound="TokenResponse")



@_attrs_define
class TokenResponse:
    """ A freshly minted access token.

    ``expires_in`` is seconds from now, matching the OAuth 2.0 convention the
    CLI and both SDKs already expect from a bearer token response.

        Attributes:
            access_token (str):
            expires_in (int):
            token_type (Literal['bearer'] | Unset):  Default: 'bearer'.
     """

    access_token: str
    expires_in: int
    token_type: Literal['bearer'] | Unset = 'bearer'
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        access_token = self.access_token

        expires_in = self.expires_in

        token_type = self.token_type


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "access_token": access_token,
            "expires_in": expires_in,
        })
        if token_type is not UNSET:
            field_dict["token_type"] = token_type

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        access_token = d.pop("access_token")

        expires_in = d.pop("expires_in")

        token_type = cast(Literal['bearer'] | Unset , d.pop("token_type", UNSET))
        if token_type != 'bearer'and not isinstance(token_type, Unset):
            raise ValueError(f"token_type must match const 'bearer', got '{token_type}'")

        token_response = cls(
            access_token=access_token,
            expires_in=expires_in,
            token_type=token_type,
        )


        token_response.additional_properties = d
        return token_response

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
