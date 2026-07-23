from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.domain_target_type import DomainTargetType
from ..types import UNSET, Unset
from typing import cast
from uuid import UUID






T = TypeVar("T", bound="DomainReplace")



@_attrs_define
class DomainReplace:
    """ Body of ``PUT /domains/{id}``. Every writable field, always.

        Attributes:
            hostname (str): Lowercase dot-separated DNS hostname, at most 253 characters. Normalised to lowercase on write.
            target_type (DomainTargetType | Unset):
            service_id (None | Unset | UUID): Required when target_type=service. Routes to whatever Deployment is live.
            deployment_id (None | Unset | UUID): Required when target_type=deployment. Pinned to one immutable build.
            tls_enabled (bool | None | Unset): Null means follow RUDDER_TLS_MODE: on for 'acme', off for 'off'. Set
                explicitly to override.
     """

    hostname: str
    target_type: DomainTargetType | Unset = UNSET
    service_id: None | Unset | UUID = UNSET
    deployment_id: None | Unset | UUID = UNSET
    tls_enabled: bool | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        hostname = self.hostname

        target_type: str | Unset = UNSET
        if not isinstance(self.target_type, Unset):
            target_type = self.target_type.value


        service_id: None | str | Unset
        if isinstance(self.service_id, Unset):
            service_id = UNSET
        elif isinstance(self.service_id, UUID):
            service_id = str(self.service_id)
        else:
            service_id = self.service_id

        deployment_id: None | str | Unset
        if isinstance(self.deployment_id, Unset):
            deployment_id = UNSET
        elif isinstance(self.deployment_id, UUID):
            deployment_id = str(self.deployment_id)
        else:
            deployment_id = self.deployment_id

        tls_enabled: bool | None | Unset
        if isinstance(self.tls_enabled, Unset):
            tls_enabled = UNSET
        else:
            tls_enabled = self.tls_enabled


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "hostname": hostname,
        })
        if target_type is not UNSET:
            field_dict["target_type"] = target_type
        if service_id is not UNSET:
            field_dict["service_id"] = service_id
        if deployment_id is not UNSET:
            field_dict["deployment_id"] = deployment_id
        if tls_enabled is not UNSET:
            field_dict["tls_enabled"] = tls_enabled

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        hostname = d.pop("hostname")

        _target_type = d.pop("target_type", UNSET)
        target_type: DomainTargetType | Unset
        if isinstance(_target_type,  Unset):
            target_type = UNSET
        else:
            target_type = DomainTargetType(_target_type)




        def _parse_service_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                service_id_type_0 = UUID(data)



                return service_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        service_id = _parse_service_id(d.pop("service_id", UNSET))


        def _parse_deployment_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                deployment_id_type_0 = UUID(data)



                return deployment_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        deployment_id = _parse_deployment_id(d.pop("deployment_id", UNSET))


        def _parse_tls_enabled(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        tls_enabled = _parse_tls_enabled(d.pop("tls_enabled", UNSET))


        domain_replace = cls(
            hostname=hostname,
            target_type=target_type,
            service_id=service_id,
            deployment_id=deployment_id,
            tls_enabled=tls_enabled,
        )


        domain_replace.additional_properties = d
        return domain_replace

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
