"""Narrow GKE Workload Identity binding for CloudNativePG backups.

Only the separately deployed backup-identity broker mutates Google IAM.  The
control plane calls that private in-cluster service and never receives the IAM
permissions needed to change a Google service-account policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from urllib.parse import quote

import httpx

from rudder_cp.runtime.models import dns_label


class GoogleIamPolicyApi(Protocol):
    """Minimal IAM policy surface needed by the backup-identity broker."""

    async def get_policy(self, service_account: str) -> dict[str, object]: ...

    async def set_policy(self, service_account: str, policy: dict[str, object]) -> None: ...


class MetadataGoogleIamPolicyApi:
    """Google IAM policy client authenticated by the GKE workload token.

    The metadata server issues the control plane's short-lived Workload
    Identity token.  No service-account key is read from configuration, a
    Kubernetes Secret, or a container filesystem.
    """

    _METADATA_TOKEN_URL = (
        "http://metadata.google.internal/computeMetadata/v1/instance/"
        "service-accounts/default/token"
    )
    _IAM_BASE_URL = "https://iam.googleapis.com/v1/projects/-/serviceAccounts"

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=10.0)

    async def _authorized_headers(self) -> dict[str, str]:
        response = await self.http.get(
            self._METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token") if isinstance(payload, Mapping) else None
        if not isinstance(token, str) or not token:
            raise RuntimeError("GKE metadata server did not return an access token")
        return {"Authorization": f"Bearer {token}"}

    def _service_account_url(self, service_account: str, action: str) -> str:
        return f"{self._IAM_BASE_URL}/{quote(service_account, safe='@')}{action}"

    async def get_policy(self, service_account: str) -> dict[str, object]:
        response = await self.http.post(
            self._service_account_url(service_account, ":getIamPolicy"),
            headers=await self._authorized_headers(),
            json={},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Google IAM returned an invalid service-account policy")
        return payload

    async def set_policy(self, service_account: str, policy: dict[str, object]) -> None:
        response = await self.http.post(
            self._service_account_url(service_account, ":setIamPolicy"),
            headers=await self._authorized_headers(),
            json={"policy": policy},
        )
        response.raise_for_status()


class GkeBackupIdentityBroker:
    """Broker-side policy writer for one dedicated GCP backup identity.

    This class is intentionally instantiated only by ``rudder_cp.backup_broker``.
    Keeping it here makes the exact policy contract independently testable.
    """

    def __init__(
        self,
        *,
        project_id: str,
        backup_service_account: str,
        iam: GoogleIamPolicyApi,
    ) -> None:
        self.project_id = project_id
        self.backup_service_account = backup_service_account
        self.iam = iam

    async def ensure_cnpg_binding(
        self, *, namespace: str, service_account_name: str
    ) -> None:
        """Grant Workload Identity to exactly one generated environment KSA.

        CNPG creates the ServiceAccount named after its Cluster.  The runtime
        supplies that stable name; this broker rejects an arbitrary namespace
        or malformed KSA before making a cloud IAM call.
        """

        if not namespace.startswith("rudder-"):
            raise ValueError("backup identity requires a Rudder environment namespace")
        if dns_label(service_account_name) != service_account_name:
            raise ValueError("backup identity requires a generated PostgreSQL ServiceAccount")

        member = (
            f"serviceAccount:{self.project_id}.svc.id.goog["
            f"{namespace}/{service_account_name}]"
        )
        policy = await self.iam.get_policy(self.backup_service_account)
        bindings_raw = policy.get("bindings", [])
        bindings = [
            {
                **dict(binding),
                "members": list(binding.get("members", [])),
            }
            for binding in bindings_raw
            if isinstance(binding, Mapping)
        ]
        for binding in bindings:
            if binding.get("role") != "roles/iam.workloadIdentityUser":
                continue
            members = binding["members"]
            assert isinstance(members, list)
            if member in members:
                return
            members.append(member)
            await self.iam.set_policy(
                self.backup_service_account, {**policy, "bindings": bindings}
            )
            return

        bindings.append(
            {
                "role": "roles/iam.workloadIdentityUser",
                "members": [member],
            }
        )
        await self.iam.set_policy(self.backup_service_account, {**policy, "bindings": bindings})


class HttpBackupIdentityBroker:
    """Control-plane client for the private backup identity broker service."""

    def __init__(self, *, base_url: str, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=10.0)

    async def ensure_cnpg_binding(
        self, *, namespace: str, service_account_name: str
    ) -> None:
        if not namespace.startswith("rudder-"):
            raise ValueError("backup identity requires a Rudder environment namespace")
        if dns_label(service_account_name) != service_account_name:
            raise ValueError("backup identity requires a generated PostgreSQL ServiceAccount")
        try:
            response = await self.http.post(
                f"{self.base_url}/internal/backup-identities/cloudnativepg",
                json={
                    "namespace": namespace,
                    "service_account_name": service_account_name,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                "backup identity broker could not bind the CNPG service account"
            ) from exc
