from enum import Enum

class InstanceStatus(str, Enum):
    DRAINING = "draining"
    HEALTHY = "healthy"
    STARTING = "starting"
    STOPPED = "stopped"
    UNHEALTHY = "unhealthy"

    def __str__(self) -> str:
        return str(self.value)
