"""Typed validation boundary for Kubernetes service operations.

These schemas intentionally describe desired intent only.  They are accepted
before a reconciler talks to Kubernetes, keeping unsafe combinations out of
both the database and a cluster.
"""

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rudder_cp.models.base import ServiceKind

_CPU_QUANTITY = re.compile(
    r"^(?:(?P<milli_number>(?:\d+(?:\.\d*)?|\.\d+))m|"
    r"(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))$"
)
_KUBERNETES_LABEL_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_CRON_INTEGER = re.compile(r"^\d+$")


class _OperationRequest(BaseModel):
    """Shared strict input boundary for every persisted operations request."""

    model_config = ConfigDict(extra="forbid")


def _cpu_cores(quantity: str) -> Decimal:
    """Parse the positive DecimalSI CPU quantities accepted by Kubernetes.

    CPU may be expressed in cores (``1``, ``0.5``, ``1e3``) or millicores
    (``500m``).  Memory suffixes such as ``Mi`` are intentionally rejected:
    they are valid memory quantities, not CPU quantities.
    """

    match = _CPU_QUANTITY.fullmatch(quantity)
    if match is None:
        raise ValueError("must be a valid Kubernetes CPU quantity")
    try:
        cores = Decimal(match.group("milli_number") or match.group("number"))
    except InvalidOperation as exc:  # defensive: regex should make this unreachable
        raise ValueError("must be a valid Kubernetes CPU quantity") from exc
    if match.group("milli_number"):
        cores /= Decimal(1000)
    if cores <= 0:
        raise ValueError("must be a positive Kubernetes CPU quantity")
    return cores


class ScaleRequest(_OperationRequest):
    replicas: int = Field(ge=0, le=100)
    service_kind: ServiceKind = Field(
        description=(
            "Untrusted client hint. The API router must replace it with the persisted "
            "Service kind before authorizing a scale operation."
        )
    )
    data_role: Literal["primary", "read_replica"] = Field(
        default="primary",
        description=(
            "Untrusted client hint. The API router must replace it with the persisted "
            "data role before authorizing a scale operation."
        ),
    )

    @model_validator(mode="after")
    def _reject_primary_database_scale(self) -> Self:
        if self.service_kind is ServiceKind.DATABASE and self.data_role == "primary":
            raise ValueError("manual scale cannot target database primaries")
        return self


class ResourceRequest(_OperationRequest):
    cpu_request: str | None = Field(default=None, min_length=1, max_length=32)
    cpu_limit: str | None = Field(default=None, min_length=1, max_length=32)
    memory_request_mb: int | None = Field(default=None, gt=0)
    memory_limit_mb: int | None = Field(default=None, gt=0)

    @field_validator("cpu_request", "cpu_limit")
    @classmethod
    def _validate_cpu_quantity(cls, quantity: str | None) -> str | None:
        if quantity is not None:
            _cpu_cores(quantity)
        return quantity

    @model_validator(mode="after")
    def _validate_resource_bounds(self) -> Self:
        if (
            self.cpu_request is not None
            and self.cpu_limit is not None
            and _cpu_cores(self.cpu_request) > _cpu_cores(self.cpu_limit)
        ):
            raise ValueError("cpu_request cannot exceed cpu_limit")
        if (
            self.memory_request_mb is not None
            and self.memory_limit_mb is not None
            and self.memory_request_mb > self.memory_limit_mb
        ):
            raise ValueError("memory_request_mb cannot exceed memory_limit_mb")
        return self


class AutoscalingRequest(_OperationRequest):
    min_replicas: int = Field(ge=1, le=100)
    max_replicas: int = Field(ge=1, le=100)
    target_cpu_percent: int = Field(default=80, ge=1, le=100)
    target_memory_percent: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_bounds(self) -> Self:
        if self.max_replicas < self.min_replicas:
            raise ValueError("max_replicas must be greater than or equal to min_replicas")
        return self


class PlacementRequest(_OperationRequest):
    node_selector: dict[str, str] = Field(default_factory=dict)
    topology_spread: bool = False
    anti_affinity: bool = False

    @field_validator("node_selector")
    @classmethod
    def _validate_node_selector(cls, node_selector: dict[str, str]) -> dict[str, str]:
        for key, value in node_selector.items():
            _validate_kubernetes_label_key(key)
            _validate_kubernetes_label_value(value)
        return node_selector


class RolloutRequest(_OperationRequest):
    strategy: Literal["rolling", "blue_green", "canary"] = "rolling"
    canary_steps: tuple[int, ...] = ()

    @model_validator(mode="after")
    def _validate_canary_steps(self) -> Self:
        if self.strategy == "canary" and not self.canary_steps:
            raise ValueError("canary rollout requires at least one traffic step")
        if any(step < 1 or step > 100 for step in self.canary_steps):
            raise ValueError("canary traffic steps must be between 1 and 100")
        if tuple(sorted(self.canary_steps)) != self.canary_steps:
            raise ValueError("canary traffic steps must be ordered")
        return self


class RollbackRequest(_OperationRequest):
    """Select a prior immutable deployment without invoking a source build."""

    deployment_id: uuid.UUID


class BackupRequest(_OperationRequest):
    retention_days: int = Field(default=7, ge=1, le=365)


class RestoreRequest(_OperationRequest):
    backup_id: uuid.UUID
    acknowledge_data_loss: bool = False

    @model_validator(mode="after")
    def _require_acknowledgement(self) -> Self:
        if not self.acknowledge_data_loss:
            raise ValueError("restore requires explicit acknowledgement of data loss")
        return self


class ReadReplicaRequest(_OperationRequest):
    replicas: int = Field(ge=1, le=10)
    public: bool = False

    @model_validator(mode="after")
    def _keep_replicas_private(self) -> Self:
        if self.public:
            raise ValueError("read replicas must remain private")
        return self


class StorageResizeRequest(_OperationRequest):
    current_size_mb: int = Field(gt=0)
    requested_size_mb: int = Field(gt=0)

    @model_validator(mode="after")
    def _reject_shrink(self) -> Self:
        if self.requested_size_mb < self.current_size_mb:
            raise ValueError("persistent volumes cannot shrink")
        return self


class _CommandRequest(_OperationRequest):
    command: tuple[str, ...]

    @field_validator("command")
    @classmethod
    def _require_nonempty_arguments(cls, command: tuple[str, ...]) -> tuple[str, ...]:
        if not command:
            raise ValueError("command must contain at least one argument")
        if len(command) > 32:
            raise ValueError("command may contain at most 32 arguments")
        if any(not argument.strip() for argument in command):
            raise ValueError("command arguments cannot be blank")
        return command


class CronJobRequest(_CommandRequest):
    cron: str = Field(min_length=9, max_length=100)
    timeout_seconds: int = Field(default=900, ge=1, le=86_400)
    retries: int = Field(default=1, ge=0, le=10)
    concurrency_policy: Literal["allow", "forbid", "replace"] = "forbid"

    @field_validator("cron")
    @classmethod
    def _validate_five_field_cron(cls, cron: str) -> str:
        fields = cron.split()
        if len(fields) != 5:
            raise ValueError("cron schedules must have five fields")
        for value, minimum, maximum, name in zip(
            fields,
            (0, 0, 1, 1, 0),
            (59, 23, 31, 12, 7),
            ("minute", "hour", "day of month", "month", "day of week"),
            strict=True,
        ):
            _validate_cron_field(value, minimum=minimum, maximum=maximum, name=name)
        return cron


class OneOffJobRequest(_CommandRequest):
    timeout_seconds: int = Field(default=900, ge=1, le=86_400)
    retries: int = Field(default=0, ge=0, le=10)


class ObservabilityRequest(_OperationRequest):
    prometheus: bool = False
    grafana: bool = False


class ServiceOperationsIntent(_OperationRequest):
    """Normalized desired operation state persisted by later API slices."""

    resources: ResourceRequest | None = None
    autoscaling: AutoscalingRequest | None = None
    placement: PlacementRequest | None = None
    rollout: RolloutRequest | None = None
    backups: BackupRequest | None = None
    read_replicas: ReadReplicaRequest | None = None
    storage: StorageResizeRequest | None = None
    schedules: tuple[CronJobRequest, ...] = ()
    observability: ObservabilityRequest | None = None


def _validate_kubernetes_label_key(key: str) -> None:
    if not key or key.count("/") > 1:
        raise ValueError("node_selector keys must be valid Kubernetes label keys")

    prefix, separator, name = key.partition("/")
    if separator:
        if not prefix or len(prefix) > 253:
            raise ValueError("node_selector keys must be valid Kubernetes label keys")
        labels = prefix.split(".")
        if any(
            not label or len(label) > 63 or _DNS_LABEL.fullmatch(label) is None
            for label in labels
        ):
            raise ValueError("node_selector keys must be valid Kubernetes label keys")
    else:
        name = prefix

    if len(name) > 63 or _KUBERNETES_LABEL_NAME.fullmatch(name) is None:
        raise ValueError("node_selector keys must be valid Kubernetes label keys")


def _validate_kubernetes_label_value(value: str) -> None:
    # Kubernetes permits an empty label value, which is useful for presence-only
    # selectors. Non-empty values share the label-name character restrictions.
    if value and (len(value) > 63 or _KUBERNETES_LABEL_NAME.fullmatch(value) is None):
        raise ValueError("node_selector values must be valid Kubernetes label values")


def _validate_cron_field(value: str, *, minimum: int, maximum: int, name: str) -> None:
    """Validate Kubernetes' five-field numeric cron grammar without accepting junk.

    Kubernetes cron jobs use numeric five-field schedules. Lists, ranges, and
    positive step values are accepted; named months/weekdays and six-field
    schedules are deliberately not, because Kubernetes does not support them.
    """

    if not value or any(not item for item in value.split(",")):
        raise ValueError(f"cron {name} must be a valid cron expression")

    for item in value.split(","):
        base, separator, raw_step = item.partition("/")
        if separator:
            if not raw_step or not _CRON_INTEGER.fullmatch(raw_step):
                raise ValueError(f"cron {name} has an invalid step")
            step = int(raw_step)
            if step < 1 or step > maximum - minimum + 1:
                raise ValueError(f"cron {name} has an invalid step")
        if "/" in raw_step:
            raise ValueError(f"cron {name} has an invalid step")

        if base == "*":
            continue

        if "-" in base:
            start, dash, end = base.partition("-")
            if not dash or not _CRON_INTEGER.fullmatch(start) or not _CRON_INTEGER.fullmatch(end):
                raise ValueError(f"cron {name} has an invalid range")
            start_value, end_value = int(start), int(end)
            if not (minimum <= start_value <= end_value <= maximum):
                raise ValueError(f"cron {name} has an invalid range")
            continue

        if _CRON_INTEGER.fullmatch(base) is None:
            raise ValueError(f"cron {name} must be numeric, a range, or wildcard")
        numeric_value = int(base)
        if not minimum <= numeric_value <= maximum:
            raise ValueError(f"cron {name} is outside its allowed range")
