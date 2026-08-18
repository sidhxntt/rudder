"""Unit coverage for the local Kind acceptance verifier's isolation proof."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def _verifier_module():
    path = Path(__file__).parents[1] / "scripts" / "verify_kind.py"
    spec = importlib.util.spec_from_file_location("verify_kind", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_kind_verifier_proves_namespace_guardrails_and_private_network_policy() -> None:
    verifier = _verifier_module()
    namespace = "rudder-environment"
    environment_label = "environment-123"
    quota = SimpleNamespace(
        spec=SimpleNamespace(
            hard={"requests.cpu": "4", "requests.memory": "8Gi", "pods": "30"}
        )
    )
    limit = SimpleNamespace(
        spec=SimpleNamespace(
            limits=[
                SimpleNamespace(
                    type="Container",
                    default={"cpu": "500m", "memory": "512Mi"},
                    default_request={"cpu": "250m", "memory": "256Mi"},
                )
            ]
        )
    )
    own_namespace = SimpleNamespace(match_labels={"rudder.environment": environment_label})
    ingress_namespace = SimpleNamespace(
        match_labels={"kubernetes.io/metadata.name": "ingress-nginx"}
    )
    kube_system_namespace = SimpleNamespace(
        match_labels={"kubernetes.io/metadata.name": "kube-system"}
    )
    policy = SimpleNamespace(
        spec=SimpleNamespace(
            pod_selector=SimpleNamespace(match_labels={}),
            policy_types=["Ingress", "Egress"],
            ingress=[
                SimpleNamespace(
                    _from=[
                        SimpleNamespace(namespace_selector=own_namespace, ip_block=None),
                        SimpleNamespace(namespace_selector=ingress_namespace, ip_block=None),
                    ]
                )
            ],
            egress=[
                SimpleNamespace(
                    to=[
                        SimpleNamespace(namespace_selector=own_namespace, ip_block=None),
                        SimpleNamespace(namespace_selector=kube_system_namespace, ip_block=None),
                    ]
                )
            ],
        )
    )
    api = SimpleNamespace(
        core=SimpleNamespace(
            read_namespace=lambda _namespace: _async(
                SimpleNamespace(
                    metadata=SimpleNamespace(
                        labels={"rudder.environment": environment_label}
                    )
                )
            ),
            read_namespaced_resource_quota=lambda _name, _namespace: _async(quota),
            read_namespaced_limit_range=lambda _name, _namespace: _async(limit),
            read_namespaced_service_account=lambda _name, _namespace: _async(
                SimpleNamespace(automount_service_account_token=False)
            ),
            list_namespaced_pod=lambda _namespace: _async(SimpleNamespace(items=[])),
        ),
        networking=SimpleNamespace(
            read_namespaced_network_policy=lambda _name, _namespace: _async(policy)
        ),
    )

    await verifier._assert_namespace_guardrails(api, namespace)


@pytest.mark.asyncio
async def test_kind_verifier_rejects_a_workload_identity_that_mounts_a_token() -> None:
    """The acceptance check must catch accidental default-token exposure."""

    verifier = _verifier_module()
    namespace = "rudder-environment"
    environment_label = "environment-123"
    quota = SimpleNamespace(
        spec=SimpleNamespace(
            hard={"requests.cpu": "4", "requests.memory": "8Gi", "pods": "30"}
        )
    )
    limit = SimpleNamespace(
        spec=SimpleNamespace(
            limits=[
                SimpleNamespace(
                    type="Container",
                    default={"cpu": "500m", "memory": "512Mi"},
                    default_request={"cpu": "250m", "memory": "256Mi"},
                )
            ]
        )
    )
    own = SimpleNamespace(match_labels={"rudder.environment": environment_label})
    ingress = SimpleNamespace(
        match_labels={"kubernetes.io/metadata.name": "ingress-nginx"}
    )
    system = SimpleNamespace(match_labels={"kubernetes.io/metadata.name": "kube-system"})
    policy = SimpleNamespace(
        spec=SimpleNamespace(
            pod_selector=SimpleNamespace(match_labels={}),
            policy_types=["Ingress", "Egress"],
            ingress=[SimpleNamespace(_from=[
                SimpleNamespace(namespace_selector=own, ip_block=None),
                SimpleNamespace(namespace_selector=ingress, ip_block=None),
            ])],
            egress=[SimpleNamespace(to=[
                SimpleNamespace(namespace_selector=own, ip_block=None),
                SimpleNamespace(namespace_selector=system, ip_block=None),
            ])],
        )
    )
    api = SimpleNamespace(
        core=SimpleNamespace(
            read_namespace=lambda _namespace: _async(
                SimpleNamespace(
                    metadata=SimpleNamespace(
                        labels={"rudder.environment": environment_label}
                    )
                )
            ),
            read_namespaced_resource_quota=lambda _name, _namespace: _async(quota),
            read_namespaced_limit_range=lambda _name, _namespace: _async(limit),
            read_namespaced_service_account=lambda _name, _namespace: _async(
                SimpleNamespace(automount_service_account_token=True)
            ),
        ),
        networking=SimpleNamespace(
            read_namespaced_network_policy=lambda _name, _namespace: _async(policy)
        ),
    )

    with pytest.raises(RuntimeError, match="workload ServiceAccount"):
        await verifier._assert_namespace_guardrails(api, namespace)


@pytest.mark.asyncio
async def test_kind_verifier_rejects_a_role_binding_for_the_workload_identity() -> None:
    """A tokenless ServiceAccount must also have no direct RBAC grant."""

    verifier = _verifier_module()
    bound_subject = SimpleNamespace(
        kind="ServiceAccount", name="rudder-workload", namespace="rudder-environment"
    )
    api = SimpleNamespace(
        rbac=SimpleNamespace(
            list_namespaced_role_binding=lambda _namespace: _async(
                SimpleNamespace(items=[SimpleNamespace(subjects=[bound_subject])])
            ),
            list_cluster_role_binding=lambda: _async(SimpleNamespace(items=[])),
        )
    )

    with pytest.raises(RuntimeError, match="RoleBinding"):
        await verifier._assert_workload_identity_has_no_rbac_grants(
            api, "rudder-environment"
        )


@pytest.mark.asyncio
async def test_kind_verifier_allows_unbound_workload_identity() -> None:
    verifier = _verifier_module()
    api = SimpleNamespace(
        rbac=SimpleNamespace(
            list_namespaced_role_binding=lambda _namespace: _async(SimpleNamespace(items=[])),
            list_cluster_role_binding=lambda: _async(SimpleNamespace(items=[])),
        )
    )

    await verifier._assert_workload_identity_has_no_rbac_grants(api, "rudder-environment")


@pytest.mark.asyncio
async def test_kind_verifier_requires_a_ready_network_policy_enforcer() -> None:
    verifier = _verifier_module()
    api = SimpleNamespace(
        apps=SimpleNamespace(
            read_namespaced_daemon_set=lambda _name, _namespace: _async(
                SimpleNamespace(status=SimpleNamespace(desired_number_scheduled=1, number_ready=0))
            )
        )
    )

    with pytest.raises(RuntimeError, match="NetworkPolicy enforcement"):
        await verifier._assert_network_policy_enforcer(api)


async def _async(value):
    return value
