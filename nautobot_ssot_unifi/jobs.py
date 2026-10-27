"""Jobs for UniFi SSoT integration."""

from nautobot.apps.jobs import BooleanVar, ChoiceVar, register_jobs
from nautobot_ssot.jobs.base import DataSource, DataTarget

from nautobot_ssot_unifi.diffsync.adapters.nautobot import UniFiNautobotAdapter
from nautobot_ssot_unifi.diffsync.adapters.unifi import UniFiAdapter
from nautobot_ssot_unifi.utils.nautobot import (
    find_devices_by_mac,
    find_interface,
    find_unsynced_cable,
    find_unsynced_device_group,
    find_unsynced_ip_address,
    find_unsynced_location,
    find_unsynced_prefix,
    find_unsynced_vlan,
    find_unsynced_vlan_group,
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
        "MAC address UniFi reports. Adopted Devices keep their Role, Device Type, and Status. Matching Locations, "
        "groups, Wireless Networks, VLANs, Prefixes, IP Addresses, and Cables are adopted with Adopt, and "
        "otherwise used as they are.",
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

        Before loading, handle Locations, device groups, Wireless Networks, VLANs, Devices, Cables, Prefixes, and IP
        Addresses that already exist in Nautobot but were not synced from this controller, as the `existing_devices`
        choice says. After loading, keep Nautobot's values for the fields the sync only sets on create, and drop the
        shared objects nothing needs any more.
        """
        self.handle_existing_locations()
        self.handle_existing_wireless()
        self.handle_existing_vlans()
        unifi_macs = {device.mac_address for device in self.source_adapter.get_all("device")}
        adopt_pks = self.handle_existing_devices(unifi_macs)
        self.source_adapter.prune_unused()
        self.handle_existing_cables()
        self.handle_existing_ip_addresses()
        self.target_adapter = UniFiNautobotAdapter(
            job=self,
            sync=self.sync,
            unifi_macs=unifi_macs,
            unifi_ips={assignment.host for assignment in self.source_adapter.get_all("ipassignment")},
            adopt_pks=adopt_pks,
            adopt=self.adopt,
            sites=self.source_adapter.sites if get_selected_sites() else None,
        )
        self.target_adapter.load()
        self.source_adapter.keep_nautobot_fields(self.target_adapter)
        self.source_adapter.prune_unused()

    def handle_existing(self, model_name: str, obj, existing, kind: str, identifiers=None) -> bool:
        """Adopt an existing object matching a UniFi one, or use it as is, as the `existing_devices` choice says.

        With Adopt, the object is loaded from Nautobot as the UniFi object's match, so the sync updates it and marks
        it as synced from now on. Otherwise the UniFi object is dropped, and the existing one is left unchanged.

        Args:
            model_name (str): DiffSync model name.
            obj (DiffSyncModel): The UniFi object.
            existing (Model): The matching Nautobot object, not synced from this controller.
            kind (str): What the object is, for the log, e.g. "Location".
            identifiers (dict, optional): Identifiers to load the existing object with, for models identified by
                custom fields it does not have yet.

        Returns:
            bool: True if the object is adopted.
        """
        if self.existing_devices == "adopt":
            self.logger.warning(
                "Adopting %s %s from UniFi: it is updated from UniFi from now on.",
                kind,
                existing,
                extra={"object": existing},
            )
            self.adopt.setdefault(model_name, {})[existing.pk] = identifiers or {}
            return True
        self.source_adapter.remove(obj)
        return False

    def handle_existing_locations(self):
        """Use or adopt an existing Location named like a UniFi site instead of creating a second one.

        A Location used as is gets the site's Devices, and is never changed, except to add the content types UniFi
        objects need to its Location Type.
        """
        for location in list(self.source_adapter.get_all("location")):
            existing = find_unsynced_location(location.name, location.unifi_site)
            if not existing:
                continue
            identifiers = {"unifi_site": location.unifi_site, "unifi_controller": location.unifi_controller}
            if not self.handle_existing("location", location, existing, "Location", identifiers):
                self.logger.warning(
                    "Location %s already exists and was not synced from UniFi; placing site %s's Devices in it "
                    "without changing the Location.",
                    existing.name,
                    location.unifi_site,
                    extra={"object": existing},
                )
            self.source_adapter.load_location_type(existing.location_type.name, required=True)

    def handle_existing_wireless(self):
        """Use or adopt existing device groups and Wireless Networks named like UniFi ones instead of duplicating them.

        Like existing Locations, a group used as is gets the site's Devices, and a Wireless Network used as is is
        assigned to the site's group, but neither is changed.
        """
        for group in list(self.source_adapter.get_all("devicegroup")):
            existing = find_unsynced_device_group(group.name, group.unifi_site)
            if not existing:
                continue
            identifiers = {"unifi_site": group.unifi_site, "unifi_controller": group.unifi_controller}
            if self.handle_existing("devicegroup", group, existing, "controller managed device group", identifiers):
                continue
            self.logger.warning(
                "Controller managed device group %s already exists and was not synced from UniFi; placing "
                "site %s's Devices in it without changing the group or its Wireless Networks.",
                existing.name,
                group.unifi_site,
                extra={"object": existing},
            )
            for assignment in list(self.source_adapter.get_all("wirelessnetworkassignment")):
                if assignment.controller_managed_device_group__name == group.name:
                    self.source_adapter.remove(assignment)
        for wireless_network in list(self.source_adapter.get_all("wirelessnetwork")):
            existing = find_unsynced_wireless_network(wireless_network.name)
            if not existing:
                continue
            if not self.handle_existing("wirelessnetwork", wireless_network, existing, "Wireless Network"):
                self.logger.warning(
                    "Wireless Network %s already exists and was not synced from UniFi; assigning it to UniFi "
                    "sites without changing it.",
                    existing.name,
                    extra={"object": existing},
                )

    def handle_existing_vlans(self):
        """Use or adopt existing VLAN Groups and VLANs instead of creating duplicates.

        A VLAN Group named like a UniFi site that the sync did not create gets the site's new VLANs. A VLAN ID that
        Nautobot already has a VLAN for, usable by Devices in the site's Location, is not created: switch ports use
        the existing VLAN, which keeps its VLAN Group when adopted.
        """
        for group in list(self.source_adapter.get_all("vlangroup")):
            existing = find_unsynced_vlan_group(group.name, group.unifi_site)
            if not existing:
                continue
            identifiers = {"unifi_site": group.unifi_site, "unifi_controller": group.unifi_controller}
            if not self.handle_existing("vlangroup", group, existing, "VLAN Group", identifiers):
                self.logger.warning(
                    "VLAN Group %s already exists and was not synced from UniFi; adding site %s's VLANs to it "
                    "without changing the group.",
                    existing.name,
                    group.unifi_site,
                    extra={"object": existing},
                )
        used = []
        for vlan in list(self.source_adapter.get_all("vlan")):
            # VLAN Groups are named after their site, like the site's Location.
            existing = find_unsynced_vlan(vlan.vid, vlan.vlan_group__name)
            if not existing:
                continue
            group_name = existing.vlan_group.name if existing.vlan_group else None
            if self.existing_devices == "adopt" and group_name != vlan.vlan_group__name:
                # Adopted VLANs keep their VLAN Group, which identifies them.
                self.source_adapter.remove(vlan)
                vlan, created = self.source_adapter.get_or_instantiate(
                    self.source_adapter.vlan,
                    ids={"vid": vlan.vid, "vlan_group__name": group_name},
                    attrs=vlan.get_attrs(),
                )
                if not created:
                    # Another site's VLAN already adopted this one.
                    continue
            if not self.handle_existing("vlan", vlan, existing, "VLAN"):
                used.append(existing)
        if used:
            self.logger.info(
                "Using %s existing VLANs not synced from UniFi as they are: %s",
                len(used),
                ", ".join(sorted(f"{vlan.vid} {vlan.name}" for vlan in used)),
            )

    def handle_existing_cables(self):
        """Leave Interfaces that already have a Cable the sync did not create alone, with a warning.

        A Cable made by hand between the same two Interfaces UniFi reports is used as is, or adopted; any other is
        reported as a conflict to fix in Nautobot or UniFi.
        """
        for cable in list(self.source_adapter.get_all("cable")):
            interfaces = [
                find_interface(cable.upstream_mac_address, cable.upstream_interface),
                find_interface(cable.mac_address, cable.interface),
            ]
            existing = next(filter(None, (find_unsynced_cable(interface) for interface in interfaces)), None)
            if existing is None:
                continue
            description = (
                f"{self.source_adapter.get('device', cable.upstream_mac_address).name} {cable.upstream_interface} "
                f"to {self.source_adapter.get('device', cable.mac_address).name} {cable.interface}"
            )
            if {existing.termination_a_id, existing.termination_b_id} == {
                interface.pk for interface in interfaces if interface
            }:
                if not self.handle_existing("cable", cable, existing, "Cable"):
                    self.logger.info(
                        "Cable %s already connects %s; leaving it as is.",
                        existing,
                        description,
                        extra={"object": existing},
                    )
                continue
            self.logger.warning(
                "Skipping the Cable from %s that UniFi reports: Cable %s, not synced from UniFi, is already on "
                "one of these Interfaces.",
                description,
                existing,
                extra={"object": existing},
            )
            self.source_adapter.remove(cable)

    def handle_existing_ip_addresses(self):
        """Use or adopt Prefixes and IP Addresses that already exist in Nautobot, instead of creating them.

        Used as is, they are never changed or deleted; only IP Addresses' assignments to the Interfaces of synced
        Devices are managed. Adopted IP Addresses are deleted when UniFi no longer reports them, like others the
        sync created.
        """
        for prefix in list(self.source_adapter.get_all("prefix")):
            existing = find_unsynced_prefix(prefix.network, prefix.prefix_length)
            if existing:
                self.handle_existing("prefix", prefix, existing, "Prefix")
        used = []
        for ip_address in list(self.source_adapter.get_all("ipaddress")):
            existing = find_unsynced_ip_address(ip_address.host)
            if existing and not self.handle_existing("ipaddress", ip_address, existing, "IP Address"):
                used.append(existing)
        if used:
            self.logger.info(
                "Assigning %s existing IP Addresses not synced from UniFi as they are: %s",
                len(used),
                ", ".join(sorted(str(ip_address) for ip_address in used)),
            )

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
        # Model name to primary key to identifiers of the existing objects to adopt.
        self.adopt = {}  # pylint: disable=attribute-defined-outside-init
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
