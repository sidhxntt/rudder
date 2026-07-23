from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset







T = TypeVar("T", bound="LoginRequest")



@_attrs_define
class LoginRequest:
    """ Credentials for ``POST /auth/token``.

    ``email`` is a plain ``str``, not ``EmailStr``: pydantic's email validator is
    a separate package that is not in ``pyproject.toml``, and there is exactly
    one user whose address came from ``.env`` — validating its format here would
    buy nothing and add a dependency.

        Attributes:
            email (str):
            password (str):
     """

    email: str
    password: str





    def to_dict(self) -> dict[str, Any]:
        email = self.email

        password = self.password


        field_dict: dict[str, Any] = {}

        field_dict.update({
            "email": email,
            "password": password,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        email = d.pop("email")

        password = d.pop("password")

        login_request = cls(
            email=email,
            password=password,
        )

        return login_request
