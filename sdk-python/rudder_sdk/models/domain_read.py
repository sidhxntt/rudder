from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.domain_target_type import DomainTargetType
from typing import cast
from uuid import UUID
import datetime






T = TypeVar("T", bound="DomainRead")



@_attrs_define
class DomainRead:
    """
        Attributes:
            id (UUID):
            hostname (str):
            environment_id (UUID):
            target_type (DomainTargetType):
            service_id (None | UUID):
            deployment_id (None | UUID):
            is_system (bool): True for the auto-generated {service}.{env}.{base_domain}. System domains are managed by the
                control plane and are read-only here.
            tls_enabled (bool):
            created_at (datetime.datetime):
     """

    id: UUID
    hostname: str
    environment_id: UUID
    target_type: DomainTargetType
    service_id: None | UUID
    deployment_id: None | UUID
    is_system: bool
    tls_enabled: bool
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        hostname = self.hostname

        environment_id = str(self.environment_id)

        target_type = self.target_type.value

        service_id: None | str
        if isinstance(self.service_id, UUID):
            service_id = str(self.service_id)
        else:
            service_id = self.service_id

        deployment_id: None | str
        if isinstance(self.deployment_id, UUID):
            deployment_id = str(self.deployment_id)
        else:
            deployment_id = self.deployment_id

        is_system = self.is_system

        tls_enabled = self.tls_enabled

        created_at = self.created_at.isoformat()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "hostname": hostname,
            "environment_id": environment_id,
            "target_type": target_type,
            "service_id": service_id,
            "deployment_id": deployment_id,
            "is_system": is_system,
            "tls_enabled": tls_enabled,
            "created_at": created_at,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))




        hostname = d.pop("hostname")

        environment_id = UUID(d.pop("environment_id"))




        target_type = DomainTargetType(d.pop("target_type"))




        def _parse_service_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                service_id_type_0 = UUID(data)



                return service_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        service_id = _parse_service_id(d.pop("service_id"))


        def _parse_deployment_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                deployment_id_type_0 = UUID(data)



                return deployment_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        deployment_id = _parse_deployment_id(d.pop("deployment_id"))


        is_system = d.pop("is_system")

        tls_enabled = d.pop("tls_enabled")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))




        domain_read = cls(
            id=id,
            hostname=hostname,
            environment_id=environment_id,
            target_type=target_type,
            service_id=service_id,
            deployment_id=deployment_id,
            is_system=is_system,
            tls_enabled=tls_enabled,
            created_at=created_at,
        )


        domain_read.additional_properties = d
        return domain_read

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
