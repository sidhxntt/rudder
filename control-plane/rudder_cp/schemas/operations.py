"""Typed validation boundary for Kubernetes service operations.

These schemas intentionally describe desired intent only.  They are accepted
before a reconciler talks to Kubernetes, keeping unsafe combinations out of
both the database and a cluster.
"""

import uuid
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from rudder_cp.models.base import ServiceKind


class ScaleRequest(BaseModel):
    replicas: int = Field(ge=0, le=100)
    service_kind: ServiceKind
    data_role: Literal["primary", "read_replica"] = "primary"

    @model_validator(mode="after")
    def _reject_primary_database_scale(self) -> Self:
        if self.service_kind is ServiceKind.DATABASE and self.data_role == "primary":
            raise ValueError("manual scale cannot target database primaries")
        return self


class ResourceRequest(BaseModel):
    cpu_request: str | None = Field(default=None, min_length=1, max_length=32)
    cpu_limit: str | None = Field(default=None, min_length=1, max_length=32)
    memory_request_mb: int | None = Field(default=None, gt=0)
    memory_limit_mb: int | None = Field(default=None, gt=0)


class AutoscalingRequest(BaseModel):
    min_replicas: int = Field(ge=1, le=100)
    max_replicas: int = Field(ge=1, le=100)
    target_cpu_percent: int = Field(default=80, ge=1, le=100)
    target_memory_percent: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_bounds(self) -> Self:
        if self.max_replicas < self.min_replicas:
            raise ValueError("max_replicas must be greater than or equal to min_replicas")
        return self


class PlacementRequest(BaseModel):
    node_selector: dict[str, str] = Field(default_factory=dict)
    topology_spread: bool = False
    anti_affinity: bool = False


class RolloutRequest(BaseModel):
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


class RollbackRequest(BaseModel):
    """Select a prior immutable deployment without invoking a source build."""

    deployment_id: uuid.UUID


class BackupRequest(BaseModel):
    retention_days: int = Field(default=7, ge=1, le=365)


class RestoreRequest(BaseModel):
    backup_id: uuid.UUID
    acknowledge_data_loss: bool = False

    @model_validator(mode="after")
    def _require_acknowledgement(self) -> Self:
        if not self.acknowledge_data_loss:
            raise ValueError("restore requires explicit acknowledgement of data loss")
        return self


class ReadReplicaRequest(BaseModel):
    replicas: int = Field(ge=1, le=10)
    public: bool = False

    @model_validator(mode="after")
    def _keep_replicas_private(self) -> Self:
        if self.public:
            raise ValueError("read replicas must remain private")
        return self


class StorageResizeRequest(BaseModel):
    current_size_mb: int = Field(gt=0)
    requested_size_mb: int = Field(gt=0)

    @model_validator(mode="after")
    def _reject_shrink(self) -> Self:
        if self.requested_size_mb < self.current_size_mb:
            raise ValueError("persistent volumes cannot shrink")
        return self


class _CommandRequest(BaseModel):
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
        if len(cron.split()) != 5:
            raise ValueError("cron schedules must have five fields")
        return cron


class OneOffJobRequest(_CommandRequest):
    timeout_seconds: int = Field(default=900, ge=1, le=86_400)
    retries: int = Field(default=0, ge=0, le=10)


class ObservabilityRequest(BaseModel):
    prometheus: bool = False
    grafana: bool = False


class ServiceOperationsIntent(BaseModel):
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
