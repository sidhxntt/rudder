from enum import Enum

class DomainTargetType(str, Enum):
    DEPLOYMENT = "deployment"
    SERVICE = "service"

    def __str__(self) -> str:
        return str(self.value)
