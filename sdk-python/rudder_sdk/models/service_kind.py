from enum import Enum

class ServiceKind(str, Enum):
    APP = "app"
    DATABASE = "database"
    STATIC = "static"

    def __str__(self) -> str:
        return str(self.value)
