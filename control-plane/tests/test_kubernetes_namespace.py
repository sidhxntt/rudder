import uuid

from rudder_cp.config import Settings
from rudder_cp.services.kubernetes_namespace import environment_namespace


def test_environment_namespace_uses_the_configured_prefix_and_stable_id_fragment():
    environment_id = uuid.UUID("8b1870ad-c287-4e3f-8f18-84e15bcae98a")

    settings = Settings(kubernetes_namespace_prefix="tenant")

    assert environment_namespace(settings, environment_id) == "tenant-8b1870adc287"
