"""Nautobot Adapter for UniFi SSoT plugin."""

from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from diffsync import Adapter
from diffsync.exceptions import ObjectNotFound
from pyunifi.controller import Controller

from nautobot_ssot_unifi.constants import (
    CLIENT_INTERFACE_NAME,
    CLIENT_ROLE,
    DEVICETYPE_MAP,
    SYSTEM_OF_RECORD,
    WIRELESS_CAPABILITY,
    WIRELESS_NETWORK_MODE,
)
from nautobot_ssot_unifi.diffsync.models.base import TOP_LEVEL
from nautobot_ssot_unifi.diffsync.models.unifi import (
    UniFiCableModel,
    UniFiControllerManagedDeviceGroupModel,
    UniFiControllerModel,
    UniFiDeviceModel,
    UniFiDeviceTypeModel,
    UniFiLocationModel,
    UniFiLocationTypeModel,
    UniFiManufacturerModel,
    UniFiPlatformModel,
    UniFiRoleModel,
    UniFiSoftwareVersionModel,
    UniFiWirelessNetworkAssignmentModel,
    UniFiWirelessNetworkModel,
)
from nautobot_ssot_unifi.utils.nautobot import resolve_interface_name, resolve_mac_interface_name
from nautobot_ssot_unifi.utils.unifi import (
    PLUGIN_CFG,
    get_controller_name,
    get_platform,
    get_sites,
    get_wlan_authentication,
    is_random_mac,
    is_site_selected,
)


def import_wireless() -> bool:
    """Whether to sync the controller, its device groups, and wireless networks (`import_wireless`, default True)."""
    return PLUGIN_CFG.get("import_wireless", True)


def import_cables() -> bool:
    """Whether to sync Cables from wired devices and clients to their switch ports (`import_cables`, default True)."""
    return PLUGIN_CFG.get("import_cables", True)


def port_interface_names(port_names: dict, port: int) -> list:
    """Interface names a UniFi switch port may have in Nautobot, in order of preference.

    Args:
        port_names (dict): Port number to name in UniFi, e.g. {1: "Port 1", 8: "Uplink", 9: "SFP 1"}.
        port (int): Port number.

    Returns:
        list: The port's name in UniFi, then "Port <n>", then "<n>".
    """
    return list(dict.fromkeys(name for name in (port_names.get(port), f"Port {port}", str(port)) if name))


def sorted_content_types(content_types) -> list:
    """Deduplicate and sort content types, so lists holding the same ones compare equal."""
    return sorted(
        {(content_type["app_label"], content_type["model"]) for content_type in content_types},
    )


class UniFiAdapter(Adapter):
    """DiffSync adapter for UniFi."""

    locationtype = UniFiLocationTypeModel
    location = UniFiLocationModel
    manufacturer = UniFiManufacturerModel
    devicetype = UniFiDeviceTypeModel
    role = UniFiRoleModel
    platform = UniFiPlatformModel
    softwareversion = UniFiSoftwareVersionModel
    controller = UniFiControllerModel
    devicegroup = UniFiControllerManagedDeviceGroupModel
    wirelessnetwork = UniFiWirelessNetworkModel
    wirelessnetworkassignment = UniFiWirelessNetworkAssignmentModel
    device = UniFiDeviceModel
    cable = UniFiCableModel

    top_level = TOP_LEVEL

    def __init__(self, *args, job=None, sync=None, client: Controller, **kwargs):
        """Initialize UniFi Controller.

        Args:
            *args: Positional arguments passed to the DiffSync Adapter.
            job (object, optional): UniFi Job. Defaults to None.
            sync (object, optional): UniFi DiffSync. Defaults to None.
            client (Controller): UniFi API client connection object.
            **kwargs: Keyword arguments passed to the DiffSync Adapter.
        """
        super().__init__(*args, **kwargs)
        self.job = job
        self.sync = sync
        self.conn = client

        self.sites = []
        # MAC -> name of the UniFi devices in the site being read, to match clients' uplinks by name.
        self.uplink_names = {}
        self.controller_name = get_controller_name()
        # Location Types of existing Locations the sync uses as is, kept by `prune_unused()` although no
        # synced Location refers to them, so the content types UniFi objects need are added to them.
        self.required_location_types = set()
        # Port number to name of each UniFi device with switch ports, by lowercase MAC.
        self.port_names = {}
        # Wired links read from UniFi, loaded as Cables by `load_cables()` once all Devices are loaded.
        self.links = []

    @staticmethod
    def location_content_types() -> list:
        """Content types Locations of UniFi sites must allow: Devices, and the Controller when it is synced."""
        content_types = [{"app_label": "dcim", "model": "device"}]
        if import_wireless():
            content_types.append({"app_label": "dcim", "model": "controller"})
        return content_types

    def load_location_type(self, name: str, required: bool = False):
        """Load a Location Type allowing the content types UniFi objects in its Locations need.

        Args:
            name (str): Location Type name.
            required (bool): Keep it even if no synced Location refers to it, for existing Locations used as is.
        """
        if required:
            self.required_location_types.add(name)
        self.get_or_instantiate(
            self.locationtype, ids={"name": name}, attrs={"content_types": self.location_content_types()}
        )

    def load_sites(self):
        """Load the selected Sites from UniFi as Locations, keyed by the site's short name."""
        self.load_location_type("Site")
        for site in get_sites(conn=self.conn):
            if not is_site_selected(site):
                if self.job.debug:
                    self.job.logger.debug("Skipping UniFi site %s (%s): not in `sites`", site["desc"], site["name"])
                continue
            self.sites.append(site)
            if self.job.debug:
                self.job.logger.debug("Loaded UniFi site %s (%s)", site["desc"], site["name"])
            self.get_or_instantiate(
                self.location,
                ids={"unifi_site": site["name"], "unifi_controller": self.controller_name},
                attrs={"name": site["desc"], "location_type__name": "Site", "status__name": "Active"},
            )

    def load_controller(self):
        """Load the controller, placed in the first selected site's Location."""
        if not import_wireless() or not self.sites:
            return
        self.get_or_instantiate(
            self.controller,
            ids={"name": self.controller_name},
            attrs={
                "location__name": self.sites[0]["desc"],
                "status__name": "Active",
                "capabilities": [WIRELESS_CAPABILITY],
            },
        )

    def load_device_group(self, site: dict):
        """Load a site's group of controller-managed devices, named after the site.

        Args:
            site (dict): Site the client is pointed at.
        """
        self.get_or_instantiate(
            self.devicegroup,
            ids={"unifi_site": site["name"], "unifi_controller": self.controller_name},
            attrs={
                "name": site["desc"],
                "controller__name": self.controller_name,
                "capabilities": [WIRELESS_CAPABILITY],
            },
        )

    def load_wlans(self, site: dict):
        """Load a site's WLANs as Wireless Networks assigned to the site's group. Passphrases are never read.

        Args:
            site (dict): Site the client is pointed at.
        """
        wlans = self.conn.get_wlan_conf()
        self.job.logger.info("Found %s WLANs in UniFi site %s", len(wlans), site["desc"])
        for wlan in wlans:
            authentication = get_wlan_authentication(wlan)
            if authentication is None:
                self.job.logger.warning(
                    "Skipping UniFi WLAN %s in site %s: Nautobot has no authentication matching security %r.",
                    wlan["name"],
                    site["desc"],
                    wlan.get("security"),
                )
                continue
            if self.job.debug:
                self.job.logger.debug("Loaded UniFi WLAN %s (%s) in %s", wlan["name"], authentication, site["desc"])
            self.get_or_instantiate(
                self.wirelessnetwork,
                ids={"name": wlan["name"]},
                attrs={
                    "ssid": wlan["name"],
                    "mode": WIRELESS_NETWORK_MODE,
                    "enabled": bool(wlan.get("enabled", True)),
                    "authentication": authentication,
                    "hidden": bool(wlan.get("hide_ssid", False)),
                    "system_of_record": SYSTEM_OF_RECORD,
                    "ssot_last_synchronized": datetime.today().date().isoformat(),
                    "unifi_controller": self.controller_name,
                },
            )
            self.get_or_instantiate(
                self.wirelessnetworkassignment,
                ids={"controller_managed_device_group__name": site["desc"], "wireless_network__name": wlan["name"]},
            )

    def load_manufacturer(self, manu_name: str = "Ubiquiti"):
        """Load Manufacturer from UniFi as Manufacturer."""
        self.get_or_instantiate(self.manufacturer, ids={"name": manu_name})

    def load_devicetype(self, model: str, manu_name: str = "Ubiquiti"):
        """Load Device models from UniFi as DeviceType."""
        self.get_or_instantiate(self.devicetype, {"model": model, "manufacturer__name": manu_name})

    def get_unifi_devices(self, site: dict) -> list:
        """Read the UniFi network devices adopted in a site.

        Args:
            site (dict): Site the client is pointed at.

        Returns:
            list: One record per device, as expected by `load_devices()`.
        """
        aps = self.conn.get_aps()
        self.job.logger.info("Found %s devices in UniFi site %s", len(aps), site["desc"])
        self.uplink_names = {ap["mac"].lower(): ap.get("name") or ap["mac"] for ap in aps}
        records = []
        for ap in aps:
            self.read_device_link(ap)
            model = DEVICETYPE_MAP[ap["model"]] if DEVICETYPE_MAP.get(ap["model"]) else ap["model"]
            records.append(
                {
                    "mac": ap["mac"],
                    "name": ap.get("name") or ap["mac"],
                    "location": site["desc"],
                    "serial": ap["serial"],
                    "role": "Unknown",
                    "model": model,
                    "manufacturer": "Ubiquiti",
                    "platform": get_platform(ap),
                    "version": ap.get("version") or None,
                    "group": site["desc"] if import_wireless() else None,
                }
            )
        return records

    def read_device_link(self, device: dict):
        """Record a UniFi device's switch port names and its wired uplink.

        Args:
            device (dict): Device from the UniFi `stat/device` endpoint.
        """
        mac = device["mac"].lower()
        port_names = {
            port["port_idx"]: port.get("name") for port in device.get("port_table") or [] if "port_idx" in port
        }
        if port_names:
            self.port_names[mac] = port_names
        uplink = device.get("uplink") or {}
        if uplink.get("type") != "wire" or not uplink.get("uplink_mac") or not uplink.get("uplink_remote_port"):
            return
        if port_names and uplink.get("port_idx"):
            interfaces = port_interface_names(port_names, uplink["port_idx"])
            default = f"Port {uplink['port_idx']}"
        else:
            # Access points: no switch ports, just the Ethernet interface UniFi names, e.g. "eth0".
            interfaces = [uplink.get("name") or CLIENT_INTERFACE_NAME]
            default = interfaces[0]
        self.links.append(
            {
                "mac": mac,
                "interface": interfaces,
                "default": default,
                "upstream_mac": uplink["uplink_mac"].lower(),
                "upstream_port": int(uplink["uplink_remote_port"]),
            }
        )

    def load_cables(self):
        """Load a Cable for each wired link between two loaded Devices.

        Links of a device or client left out of the sync are skipped. A switch port with several links,
        such as clients behind an unmanaged switch or a host with virtual machines, gets no Cable unless
        one of them is a UniFi device, which then wins.
        """
        if not import_cables():
            return
        loaded = {device.mac_address for device in self.get_all(self.device)}
        links = [link for link in self.links if link["mac"] in loaded and link["upstream_mac"] in loaded]
        by_port = defaultdict(list)
        for link in links:
            by_port[(link["upstream_mac"], link["upstream_port"])].append(link)
        for (upstream_mac, port), port_links in by_port.items():
            devices = [link for link in port_links if link["interface"] is not None]
            chosen = devices if len(devices) == 1 else port_links
            if len(chosen) != 1:
                if self.job.debug:
                    self.job.logger.debug(
                        "Skipping Cables to %s port %s: %s links (%s)",
                        self.uplink_names.get(upstream_mac, upstream_mac),
                        port,
                        len(port_links),
                        ", ".join(link["mac"] for link in port_links),
                    )
                continue
            link = chosen[0]
            if link["interface"] is None:
                interface = resolve_mac_interface_name(link["mac"], CLIENT_INTERFACE_NAME)
            else:
                interface = resolve_interface_name(link["mac"], link["interface"], link["default"])
            port_names = port_interface_names(self.port_names.get(upstream_mac, {}), port)
            self.get_or_instantiate(
                self.cable,
                ids={"mac_address": link["mac"]},
                attrs={
                    "interface": interface,
                    "upstream_mac_address": upstream_mac,
                    "upstream_interface": resolve_interface_name(upstream_mac, port_names, f"Port {port}"),
                },
            )

    def client_skip_reason(self, client: dict) -> Optional[str]:
        """Why a client is left out of the sync, or None to sync it.

        In order: wireless clients unless `import_wireless_clients` is set; clients whose uplink
        (the switch or access point they connect through, by name or MAC) or network is not in
        a non-empty `include_client_uplinks` / `include_client_networks`, or is in
        `exclude_client_uplinks` / `exclude_client_networks`; and clients with a randomized
        (locally administered) MAC and no alias in UniFi, because their MAC, which identifies
        them in Nautobot, can change at any time.

        Args:
            client (dict): Client from the UniFi `stat/sta` endpoint.

        Returns:
            Optional[str]: Reason for the debug log, or None.
        """
        if not client.get("is_wired") and not PLUGIN_CFG.get("import_wireless_clients", True):
            return "wireless"
        uplink_mac = ((client.get("sw_mac") if client.get("is_wired") else client.get("ap_mac")) or "").lower()
        uplink = {uplink_mac, self.uplink_names.get(uplink_mac)} - {"", None}
        network = {client.get("network")} - {None}
        for kind, raw_values in (("uplink", uplink), ("network", network)):
            values = {value.lower() for value in raw_values}
            include = {value.lower() for value in PLUGIN_CFG.get(f"include_client_{kind}s") or []}
            exclude = {value.lower() for value in PLUGIN_CFG.get(f"exclude_client_{kind}s") or []}
            if include and not values & include:
                return f"{kind} {', '.join(sorted(values)) or 'unknown'} not in include_client_{kind}s"
            if values & exclude:
                return f"{kind} {', '.join(sorted(values))} in exclude_client_{kind}s"
        if is_random_mac(client["mac"]) and not client.get("name"):
            return "randomized MAC without an alias"
        return None

    def get_clients(self, site: dict) -> list:
        """Read the clients connected to a site, minus the ones `client_skip_reason()` rejects.

        Must run after `get_unifi_devices()` for the same site, which records the uplink names.

        Args:
            site (dict): Site the client is pointed at.

        Returns:
            list: One record per client, as expected by `load_devices()`.
        """
        if not PLUGIN_CFG.get("import_clients", True):
            return []
        clients = self.conn.get_clients()
        records = []
        for client in clients:
            skip_reason = self.client_skip_reason(client)
            if skip_reason:
                if self.job.debug:
                    self.job.logger.debug("Skipping UniFi client %s: %s", client["mac"], skip_reason)
                continue
            if client.get("is_wired") and client.get("sw_mac") and client.get("sw_port"):
                self.links.append(
                    {
                        "mac": client["mac"].lower(),
                        "interface": None,
                        "upstream_mac": client["sw_mac"].lower(),
                        "upstream_port": int(client["sw_port"]),
                    }
                )
            hostname = client.get("hostname") if client.get("hostname") != "\x03" else None
            records.append(
                {
                    "mac": client["mac"],
                    "name": client.get("name") or hostname or client["mac"],
                    "location": site["desc"],
                    "serial": "",
                    "role": CLIENT_ROLE,
                    "model": "Unknown Device",
                    "manufacturer": client.get("oui") or "Unknown",
                    "platform": None,
                    "version": None,
                    "group": None,
                }
            )
        self.job.logger.info("Found %s clients in UniFi site %s, loading %s", len(clients), site["desc"], len(records))
        return records

    def load_devices(self, records: list):
        """Load UniFi devices and clients as Devices, keyed by MAC address.

        Device names must be unique within a Location, so every record sharing a name with
        another in the same Location gets its MAC appended, e.g. "iPhone (fe:38:d1:f6:34:8e)".

        Args:
            records (list): Records from `get_unifi_devices()` and `get_clients()`.
        """
        name_counts = Counter((record["location"], record["name"]) for record in records)
        for record in records:
            name = record["name"]
            if name_counts[(record["location"], name)] > 1:
                name = f"{name} ({record['mac']})"
            if self.job.debug:
                self.job.logger.debug(
                    "Loaded UniFi %s %s (%s) in %s", record["role"], name, record["mac"], record["location"]
                )
            self.load_manufacturer(manu_name=record["manufacturer"])
            self.load_devicetype(model=record["model"], manu_name=record["manufacturer"])
            self.get_or_instantiate(
                self.role,
                ids={"name": record["role"]},
                attrs={"content_types": [{"app_label": "dcim", "model": "device"}]},
            )
            if record["platform"]:
                self.get_or_instantiate(self.platform, ids={"name": record["platform"]})
            if record["platform"] and record["version"]:
                self.get_or_instantiate(
                    self.softwareversion,
                    ids={"platform__name": record["platform"], "version": record["version"]},
                    attrs={"status__name": "Active"},
                )
            self.get_or_instantiate(
                self.device,
                ids={"mac_address": record["mac"].lower()},
                attrs={
                    "name": name,
                    "location__name": record["location"],
                    "serial": record["serial"],
                    "role__name": record["role"],
                    "device_type__model": record["model"],
                    "device_type__manufacturer__name": record["manufacturer"],
                    "status__name": "Active",
                    "platform__name": record["platform"],
                    "software_version__platform__name": record["platform"] if record["version"] else None,
                    "software_version__version": record["version"],
                    "controller_managed_device_group__name": record["group"],
                    "system_of_record": SYSTEM_OF_RECORD,
                    "ssot_last_synchronized": datetime.today().date().isoformat(),
                    "unifi_controller": self.controller_name,
                },
            )

    def load(self):
        """Load data from UniFi into DiffSync models."""
        self.load_sites()
        self.load_controller()
        records = []
        # pyunifi reads one site at a time, and UniFi OS names sites with random IDs rather than "default".
        for site in self.sites:
            self.conn.site_id = site["name"]
            if import_wireless():
                self.load_device_group(site)
                self.load_wlans(site)
            records.extend(self.get_unifi_devices(site))
            records.extend(self.get_clients(site))
        self.load_devices(records)
        self.load_cables()

    def keep_nautobot_fields(self, target: Adapter):
        """Copy the fields the sync only sets on create, or only adds to, from Nautobot over the UniFi values.

        Devices already in `target` keep Role, Device Type, and Status, serial and Platform unless Nautobot
        has none, and for clients also Platform, Software Version, and device group. Locations keep Location
        Type and Status; the Controller keeps Location and Status. Content types of Location Types and Roles,
        and Controller capabilities, become the union of both, so the sync only ever adds to them.

        Args:
            target (Adapter): Loaded Nautobot adapter.
        """
        for device in self.get_all(self.device):
            existing = self._get_existing(target, device)
            if existing is None:
                continue
            if device.role__name == CLIENT_ROLE:
                device.platform__name = existing.platform__name
                device.software_version__platform__name = existing.software_version__platform__name
                device.software_version__version = existing.software_version__version
                device.controller_managed_device_group__name = existing.controller_managed_device_group__name
            device.role__name = existing.role__name
            device.device_type__model = existing.device_type__model
            device.device_type__manufacturer__name = existing.device_type__manufacturer__name
            device.status__name = existing.status__name
            device.serial = existing.serial or device.serial
            device.platform__name = existing.platform__name or device.platform__name
        for location in self.get_all(self.location):
            existing = self._get_existing(target, location)
            if existing is not None:
                location.location_type__name = existing.location_type__name
                location.status__name = existing.status__name
        for controller in self.get_all(self.controller):
            existing = self._get_existing(target, controller)
            if existing is not None:
                controller.location__name = existing.location__name
                controller.status__name = existing.status__name
                controller.capabilities = sorted(set(controller.capabilities or []) | set(existing.capabilities or []))
        for model in (self.locationtype, self.role):
            for obj in self.get_all(model):
                existing = self._get_existing(target, obj)
                if existing is not None:
                    merged = [
                        {"app_label": app_label, "model": name}
                        for app_label, name in sorted_content_types(obj.content_types + existing.content_types)
                    ]
                    obj.content_types = merged
                    # Nautobot returns content types in no particular order; sort them so only additions diff.
                    existing.content_types = [
                        {"app_label": app_label, "model": name}
                        for app_label, name in sorted_content_types(existing.content_types)
                    ]

    @staticmethod
    def _get_existing(target: Adapter, obj):
        """The object in `target` with the same identifiers as `obj`, or None."""
        try:
            return target.get(obj.__class__, obj.get_unique_id())
        except ObjectNotFound:
            return None

    def prune_unused(self):
        """Drop Cables and shared objects that no remaining Device or Location needs.

        Cables to Devices left out of the sync go, as do unreferenced Roles, Device Types, Manufacturers,
        Platforms, Software Versions, and Location Types.

        Devices left out of the sync, and the Nautobot values kept by `keep_nautobot_fields()`, leave
        UniFi's versions of these unreferenced; without this the sync would create them for nothing.
        """
        devices = self.get_all(self.device)
        roles = {device.role__name for device in devices}
        device_types = {(device.device_type__model, device.device_type__manufacturer__name) for device in devices}
        manufacturers = {manufacturer for _, manufacturer in device_types}
        versions = {
            (device.software_version__platform__name, device.software_version__version)
            for device in devices
            if device.software_version__version
        }
        platforms = {device.platform__name for device in devices} | {platform for platform, _ in versions}
        macs = {device.mac_address for device in devices}
        for cable in list(self.get_all(self.cable)):
            if cable.mac_address not in macs or cable.upstream_mac_address not in macs:
                self.remove(cable)
        location_types = {location.location_type__name for location in self.get_all(self.location)}
        location_types |= self.required_location_types
        for model, keep in (
            (self.role, lambda role: role.name in roles),
            (self.devicetype, lambda dt: (dt.model, dt.manufacturer__name) in device_types),
            (self.manufacturer, lambda manufacturer: manufacturer.name in manufacturers),
            (self.softwareversion, lambda version: (version.platform__name, version.version) in versions),
            (self.platform, lambda platform: platform.name in platforms),
            (self.locationtype, lambda location_type: location_type.name in location_types),
        ):
            for obj in list(self.get_all(model)):
                if not keep(obj):
                    self.remove(obj)
