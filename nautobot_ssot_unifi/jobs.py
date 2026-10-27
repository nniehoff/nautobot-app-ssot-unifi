"""Jobs for UniFi SSoT integration."""

from nautobot.apps.jobs import BooleanVar, ChoiceVar, register_jobs
from nautobot_ssot.jobs.base import DataSource, DataTarget

from nautobot_ssot_unifi.diffsync.adapters.nautobot import UniFiNautobotAdapter
from nautobot_ssot_unifi.diffsync.adapters.unifi import UniFiAdapter
from nautobot_ssot_unifi.utils.nautobot import (
    find_devices_by_mac,
    find_unsynced_device_group,
    find_unsynced_location,
    find_unsynced_wireless_network,
    is_synced_device,
)
from nautobot_ssot_unifi.utils.unifi import connect_controller, get_selected_sites

name = "UniFi SSoT"  # pylint: disable=invalid-name

EXISTING_DEVICE_CHOICES = (
    ("skip", "Skip: leave them alone and log a warning"),
    ("adopt", "Adopt: update them from UniFi from now on"),
    ("create", "Create: add a separate Device from UniFi"),
)


class UniFiDataSource(DataSource):
    """UniFi SSoT Data Source."""

    debug = BooleanVar(description="Enable for more verbose debug logging", default=False)
    existing_devices = ChoiceVar(
        choices=EXISTING_DEVICE_CHOICES,
        default="skip",
        label="Existing devices",
        description="What to do with Devices already in Nautobot, not synced from this controller, that have a "
        "MAC address UniFi reports. Adopted Devices keep their Role, Device Type, and Status.",
    )

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta data for UniFi."""

        name = "UniFi to Nautobot"
        data_source = "UniFi"
        data_target = "Nautobot"
        description = "Sync information from UniFi to Nautobot"

    @classmethod
    def config_information(cls):
        """Dictionary describing the configuration of this DataSource."""
        return {}

    @classmethod
    def data_mappings(cls):
        """List describing the data mappings involved in this DataSource."""
        return ()

    def load_source_adapter(self):
        """Load data from UniFi into DiffSync models."""
        conn = connect_controller()
        self.source_adapter = UniFiAdapter(job=self, sync=self.sync, client=conn)
        self.source_adapter.load()

    def load_target_adapter(self):
        """Load data from Nautobot into DiffSync models.

        Before loading, handle Locations, device groups, Wireless Networks, and Devices that already exist in Nautobot but were not synced
        from this controller. After loading, keep Nautobot's values for the fields the sync only sets on
        create, and drop the shared objects nothing needs any more.
        """
        self.handle_existing_locations()
        self.handle_existing_wireless()
        unifi_macs = {device.mac_address for device in self.source_adapter.get_all("device")}
        adopt_pks = self.handle_existing_devices(unifi_macs)
        self.target_adapter = UniFiNautobotAdapter(
            job=self,
            sync=self.sync,
            unifi_macs=unifi_macs,
            adopt_pks=adopt_pks,
            sites=self.source_adapter.sites if get_selected_sites() else None,
        )
        self.target_adapter.load()
        self.source_adapter.keep_nautobot_fields(self.target_adapter)
        self.source_adapter.prune_unused()

    def handle_existing_locations(self):
        """Use an existing Location named like a UniFi site instead of creating a second one.

        The sync places the site's Devices in it, but never changes the Location itself, except to add the
        Device and Controller content types to its Location Type.
        """
        for location in list(self.source_adapter.get_all("location")):
            existing = find_unsynced_location(location.name, location.unifi_site)
            if existing:
                self.logger.warning(
                    "Location %s already exists and was not synced from UniFi; placing site %s's Devices in it "
                    "without changing the Location.",
                    existing.name,
                    location.unifi_site,
                    extra={"object": existing},
                )
                self.source_adapter.remove(location)
                self.source_adapter.load_location_type(existing.location_type.name, required=True)

    def handle_existing_wireless(self):
        """Use existing device groups and Wireless Networks named like UniFi ones instead of creating duplicates.

        Like existing Locations, the sync places the site's Devices in an existing group, and assigns its
        group to an existing Wireless Network, but never changes either.
        """
        for group in list(self.source_adapter.get_all("devicegroup")):
            existing = find_unsynced_device_group(group.name, group.unifi_site)
            if existing:
                self.logger.warning(
                    "Controller managed device group %s already exists and was not synced from UniFi; placing "
                    "site %s's Devices in it without changing the group or its Wireless Networks.",
                    existing.name,
                    group.unifi_site,
                    extra={"object": existing},
                )
                self.source_adapter.remove(group)
                for assignment in list(self.source_adapter.get_all("wirelessnetworkassignment")):
                    if assignment.controller_managed_device_group__name == group.name:
                        self.source_adapter.remove(assignment)
        for wireless_network in list(self.source_adapter.get_all("wirelessnetwork")):
            existing = find_unsynced_wireless_network(wireless_network.name)
            if existing:
                self.logger.warning(
                    "Wireless Network %s already exists and was not synced from UniFi; assigning it to UniFi "
                    "sites without changing it.",
                    existing.name,
                    extra={"object": existing},
                )
                self.source_adapter.remove(wireless_network)

    def handle_existing_devices(self, unifi_macs) -> list:
        """Apply the `existing_devices` choice to Devices that share a MAC with UniFi but are not synced from here.

        Args:
            unifi_macs (set): Lowercase MAC addresses UniFi reports.

        Returns:
            list: Primary keys of the Devices to adopt.
        """
        adopt_pks = []
        for mac, devices in find_devices_by_mac(unifi_macs).items():
            if any(is_synced_device(device) for device in devices):
                continue
            unifi_device = self.source_adapter.get("device", mac)
            if len(devices) > 1:
                self.logger.warning(
                    "UniFi %s (%s) matches %s Devices in Nautobot (%s); skipping it until only one has this MAC.",
                    unifi_device.name,
                    mac,
                    len(devices),
                    ", ".join(sorted(str(device) for device in devices)),
                )
                self.source_adapter.remove(unifi_device)
                continue
            device = devices[0]
            if self.existing_devices == "adopt":
                self.logger.warning(
                    "Adopting %s (%s) from UniFi %s: %s",
                    device,
                    mac,
                    unifi_device.name,
                    self.describe_adoption(device, unifi_device),
                    extra={"object": device},
                )
                adopt_pks.append(device.pk)
            elif self.existing_devices == "create":
                self.logger.warning(
                    "Creating UniFi %s (%s) as a new Device although %s has the same MAC.",
                    unifi_device.name,
                    mac,
                    device,
                    extra={"object": device},
                )
            else:
                self.logger.warning(
                    "Skipping UniFi %s (%s): %s has the same MAC and was not synced from UniFi. "
                    "Run with Existing devices set to Adopt to take it over.",
                    unifi_device.name,
                    mac,
                    device,
                    extra={"object": device},
                )
                self.source_adapter.remove(unifi_device)
        return adopt_pks

    @staticmethod
    def describe_adoption(device, unifi_device) -> str:
        """Summarize what adopting a Device changes and what it keeps.

        Args:
            device (Device): The Nautobot Device being adopted.
            unifi_device (DeviceModel): The matching UniFi device.

        Returns:
            str: Changed fields as "field: old -> new", then the kept fields that differ from UniFi.
        """
        changes = [
            f"{field}: {old!r} -> {new!r}"
            for field, old, new in (
                ("name", device.name, unifi_device.name),
                ("location", device.location.name, unifi_device.location__name),
                ("serial", device.serial, unifi_device.serial or device.serial),
            )
            if old != new
        ]
        kept = [
            f"{field} {old!r} (UniFi reports {new!r})"
            for field, old, new in (
                ("role", device.role.name, unifi_device.role__name),
                ("device type", device.device_type.model, unifi_device.device_type__model),
            )
            if old != new
        ]
        return "; ".join(
            [
                "changes " + (", ".join(changes) if changes else "nothing"),
                *(["keeps " + ", ".join(kept)] if kept else []),
            ]
        )

    def run(self, *args, **kwargs):
        """Perform data synchronization."""
        self.debug = kwargs.pop("debug", False)
        self.existing_devices = kwargs.pop("existing_devices", "skip")
        super().run(*args, **kwargs)


class UniFiDataTarget(DataTarget):
    """UniFi SSoT Data Target."""

    debug = BooleanVar(description="Enable for more verbose debug logging", default=False)

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta data for UniFi."""

        name = "Nautobot to UniFi"
        data_source = "Nautobot"
        data_target = "UniFi"
        description = "Sync information from Nautobot to UniFi"

    @classmethod
    def config_information(cls):
        """Dictionary describing the configuration of this DataTarget."""
        return {}

    @classmethod
    def data_mappings(cls):
        """List describing the data mappings involved in this DataSource."""
        return ()

    def load_source_adapter(self):
        """Load data from Nautobot into DiffSync models."""
        self.source_adapter = UniFiNautobotAdapter(job=self, sync=self.sync)
        self.source_adapter.load()

    def load_target_adapter(self):
        """Load data from UniFi into DiffSync models."""
        conn = connect_controller()
        self.target_adapter = UniFiAdapter(job=self, sync=self.sync, client=conn)
        self.target_adapter.load()

    def run(self, *args, **kwargs):
        """Perform data synchronization."""
        self.debug = kwargs.pop("debug", False)
        super().run(*args, **kwargs)


jobs = [UniFiDataSource, UniFiDataTarget]
register_jobs(*jobs)
