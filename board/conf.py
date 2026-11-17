"""
The operation's configuration for this deployment.

settings.DOCKOPS holds only what differs from the demo defaults of dockops.OpsConfig,
for example {"bays": (1, 2, 3, 4)}. An unknown name or an invalid shift fails loudly.
"""
from django.conf import settings

from dockops.models import OpsConfig


def get_ops_config() -> OpsConfig:
    return OpsConfig(**getattr(settings, "DOCKOPS", {}))
