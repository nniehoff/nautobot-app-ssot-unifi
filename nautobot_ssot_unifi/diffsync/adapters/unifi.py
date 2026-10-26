"""Nautobot Adapter for UniFi SSoT plugin."""

from collections import Counter
from datetime import datetime
from typing import Optional

from diffsync import Adapter
from pyunifi.controller import Controller

from nautobot_ssot_unifi.constants import CLIENT_ROLE, DEVICETYPE_MAP, SYSTEM_OF_RECORD
from nautobot_ssot_unifi.diffsync.models.unifi import (
    UniFiDeviceModel,
    UniFiDeviceTypeModel,
    UniFiLocationModel,
    UniFiLocationTypeModel,
    UniFiManufacturerModel,
    UniFiRoleModel,
)
from nautobot_ssot_unifi.utils.unifi import (
    PLUGIN_CFG,
    get_controller_name,
    get_sites,
    is_random_mac,
    is_site_selected,
)


class UniFiAdapter(Adapter):
    """DiffSync adapter for UniFi."""

    locationtype = UniFiLocationTypeModel
    location = UniFiLocationModel
    manufacturer = UniFiManufacturerModel
    devicetype = UniFiDeviceTypeModel
    role = UniFiRoleModel
    device = UniFiDeviceModel

    top_level = ["locationtype", "location", "manufacturer", "devicetype", "role", "device"]

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

    def load_sites(self):
        """Load the selected Sites from UniFi as Locations, keyed by the site's short name."""
        self.get_or_instantiate(
            self.locationtype, ids={"name": "Site", "content_types": [{"app_label": "dcim", "model": "device"}]}
        )
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
                }
            )
        return records

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
                    "system_of_record": SYSTEM_OF_RECORD,
                    "ssot_last_synchronized": datetime.today().date().isoformat(),
                    "unifi_controller": self.controller_name,
                },
            )

    def load(self):
        """Load data from UniFi into DiffSync models."""
        self.load_sites()
        records = []
        # pyunifi reads one site at a time, and UniFi OS names sites with random IDs rather than "default".
        for site in self.sites:
            self.conn.site_id = site["name"]
            records.extend(self.get_unifi_devices(site))
            records.extend(self.get_clients(site))
        self.load_devices(records)
