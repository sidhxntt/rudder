from enum import Enum

class DeploymentStatus(str, Enum):
    BUILDING = "building"
    DEPLOYING = "deploying"
    FAILED = "failed"
    LIVE = "live"
    QUEUED = "queued"
    SUPERSEDED = "superseded"

    def __str__(self) -> str:
        return str(self.value)
