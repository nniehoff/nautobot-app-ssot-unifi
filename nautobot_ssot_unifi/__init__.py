"""App declaration for nautobot_ssot_unifi."""

# Metadata is inherited from Nautobot. If not including Nautobot in the environment, this should be added
from importlib import metadata

from nautobot.apps import NautobotAppConfig, nautobot_database_ready

from nautobot_ssot_unifi.signals import nautobot_database_ready_callback

__version__ = metadata.version(__name__)


class NautobotSsotUniFiConfig(NautobotAppConfig):
    """App configuration for the nautobot_ssot_unifi app."""

    name = "nautobot_ssot_unifi"
    verbose_name = "Nautobot SSoT UniFi"
    version = __version__
    author = "Justin Drew"
    description = "Nautobot SSoT App for UniFi."
    base_url = "ssot-unifi"
    required_settings = []
    default_settings = {}
    docs_view_name = "plugins:nautobot_ssot_unifi:docs"
    searchable_models = []

    def ready(self):
        """Trigger callback when database is ready."""
        super().ready()

        nautobot_database_ready.connect(nautobot_database_ready_callback, sender=self)


config = NautobotSsotUniFiConfig  # pylint:disable=invalid-name
