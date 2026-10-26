"""Nautobot Adapter for UniFi SSoT plugin."""

from datetime import datetime

from diffsync import Adapter
from pyunifi.controller import Controller

from nautobot_ssot_unifi.constants import DEVICETYPE_MAP, SYSTEM_OF_RECORD
from nautobot_ssot_unifi.diffsync.models.unifi import (
    UniFiDeviceModel,
    UniFiDeviceTypeModel,
    UniFiLocationModel,
    UniFiLocationTypeModel,
    UniFiManufacturerModel,
    UniFiRoleModel,
)
from nautobot_ssot_unifi.utils.unifi import get_controller_name, get_sites


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
        self.site_map = {}
        self.controller_name = get_controller_name()

    def load_sites(self):
        """Load Sites from UniFi as Locations."""
        self.get_or_instantiate(
            self.locationtype, ids={"name": "Site", "content_types": [{"app_label": "dcim", "model": "device"}]}
        )
        self.sites = get_sites(conn=self.conn)
        for site in self.sites:
            self.site_map[site["_id"]] = site["desc"]
            if self.job.debug:
                self.job.logger.debug("Loaded UniFi site %s (%s)", site["desc"], site["name"])
            self.get_or_instantiate(
                self.location,
                ids={"name": site["desc"], "location_type__name": "Site"},
                attrs={"status__name": "Active"},
            )

    def load_manufacturer(self, manu_name: str = "Ubiquiti"):
        """Load Manufacturer from UniFi as Manufacturer."""
        self.get_or_instantiate(self.manufacturer, ids={"name": manu_name})

    def load_devicetype(self, model: str, manu_name: str = "Ubiquiti"):
        """Load Device models from UniFi as DeviceType."""
        self.get_or_instantiate(self.devicetype, {"model": model, "manufacturer__name": manu_name})

    def load_unifi_devices(self):
        """Load Devices from UniFi as Devices."""
        aps = self.conn.get_aps()
        self.job.logger.info("Found %s devices in UniFi site %s", len(aps), self.conn.site_id)
        for ap in aps:
            model = DEVICETYPE_MAP[ap["model"]] if DEVICETYPE_MAP.get(ap["model"]) else ap["model"]
            location = self.site_map[ap["site_id"]] if ap.get("site_id") else "Unknown"
            if self.job.debug:
                self.job.logger.debug("Loaded UniFi device %s (%s) in %s", ap["name"], model, location)
            self.load_manufacturer()
            self.load_devicetype(model)
            self.get_or_instantiate(
                self.device,
                ids={"name": ap["name"]},
                attrs={
                    "location__name": location,
                    "serial": ap["serial"],
                    "role__name": "Unknown",
                    "device_type__model": model,
                    "device_type__manufacturer__name": "Ubiquiti",
                    "status__name": "Active",
                    "system_of_record": SYSTEM_OF_RECORD,
                    "ssot_last_synchronized": datetime.today().date().isoformat(),
                    "unifi_controller": self.controller_name,
                },
            )
            self.get_or_instantiate(
                self.role, ids={"name": "Unknown"}, attrs={"content_types": [{"app_label": "dcim", "model": "device"}]}
            )

    def load_clients(self):
        """Load client devices from UniFi as Devices."""
        clients = self.conn.get_clients()
        self.job.logger.info("Found %s clients in UniFi site %s", len(clients), self.conn.site_id)
        for client in clients:
            if not client.get("hostname") or client["hostname"] == "\x03":
                if self.job.debug:
                    self.job.logger.debug("Skipping UniFi client %s: no hostname", client.get("mac"))
                continue
            site = self.site_map[client["site_id"]] if client.get("site_id") else "Unknown"
            manu_name = client["oui"] if client.get("oui") else "Unknown"
            self.load_manufacturer(manu_name=manu_name)
            self.load_devicetype(model="Unknown Device", manu_name=manu_name)
            self.get_or_instantiate(
                self.device,
                ids={"name": client["hostname"]},
                attrs={
                    "location__name": site,
                    "serial": "",
                    "role__name": "Client",
                    "device_type__model": "Unknown Device",
                    "device_type__manufacturer__name": manu_name,
                    "status__name": "Active",
                    "system_of_record": SYSTEM_OF_RECORD,
                    "ssot_last_synchronized": datetime.today().date().isoformat(),
                    "unifi_controller": self.controller_name,
                },
            )
            self.get_or_instantiate(
                self.role,
                ids={"name": "Client"},
                attrs={"content_types": [{"app_label": "dcim", "model": "device"}]},
            )

    def load(self):
        """Load data from UniFi into DiffSync models."""
        self.load_sites()
        # pyunifi reads one site at a time, and UniFi OS names sites with random IDs rather than "default".
        for site in self.sites:
            self.conn.site_id = site["name"]
            self.load_unifi_devices()
            self.load_clients()
