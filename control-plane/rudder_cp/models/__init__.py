"""SQLModel tables. Importing this package registers every table on the shared
metadata, which is what Alembic's env.py relies on.

Tables only. No methods that perform I/O — that logic belongs in services/.
"""

from rudder_cp.models.authorization_handoff import AuthorizationHandoff
from rudder_cp.models.base import (
    DeploymentStatus,
    DomainTargetType,
    InstanceStatus,
    NodeStatus,
    ServiceKind,
)
from rudder_cp.models.deployment import Deployment, Instance
from rudder_cp.models.domain import Domain
from rudder_cp.models.github_import import GitHubImport, GitHubImportService
from rudder_cp.models.metrics import RuntimeMetric
from rudder_cp.models.node import Node
from rudder_cp.models.operations import (
    OperationKind,
    OperationStatus,
    ServiceManagedCapabilities,
    ServiceOperation,
    ServiceOperationsState,
)
from rudder_cp.models.pr_notification import PullRequestNotification
from rudder_cp.models.project import Environment, Project
from rudder_cp.models.service import Service, Variable, Volume
from rudder_cp.models.user import User

__all__ = [
    "AuthorizationHandoff",
    "Deployment",
    "DeploymentStatus",
    "Domain",
    "DomainTargetType",
    "Environment",
    "GitHubImport",
    "GitHubImportService",
    "Instance",
    "InstanceStatus",
    "Node",
    "NodeStatus",
    "OperationKind",
    "OperationStatus",
    "Project",
    "PullRequestNotification",
    "RuntimeMetric",
    "Service",
    "ServiceManagedCapabilities",
    "ServiceOperation",
    "ServiceOperationsState",
    "ServiceKind",
    "User",
    "Variable",
    "Volume",
]
