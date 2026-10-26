"""Nautobot Adapter for Unifi SSoT plugin."""

from itertools import chain

from django.db.models import Q
from nautobot.dcim.models import Device
from nautobot_ssot.contrib import NautobotAdapter

from nautobot_ssot_unifi.diffsync.models.base import (
    DeviceModel,
    DeviceTypeModel,
    LocationModel,
    LocationTypeModel,
    ManufacturerModel,
    RoleModel,
    get_device_mac,
)


class UniFiNautobotAdapter(NautobotAdapter):
    """DiffSync adapter for Nautobot."""

    locationtype = LocationTypeModel
    location = LocationModel
    manufacturer = ManufacturerModel
    devicetype = DeviceTypeModel
    role = RoleModel
    device = DeviceModel

    top_level = ["locationtype", "location", "manufacturer", "devicetype", "role", "device"]

    def __init__(self, *args, unifi_macs=frozenset(), adopt_pks=(), sites=None, **kwargs):
        """Initialize the Nautobot adapter.

        Args:
            *args: Positional arguments passed to NautobotAdapter.
            unifi_macs (frozenset): Lowercase MAC addresses UniFi reports, preferred when matching Devices.
            adopt_pks (Iterable): Primary keys of Devices not yet synced from this controller to load anyway,
                so the sync takes them over.
            sites (list, optional): Selected UniFi sites. When set, only Devices in their Locations are loaded,
                matched by the Location's `unifi_site` or by the site's name.
            **kwargs: Keyword arguments passed to NautobotAdapter.
        """
        super().__init__(*args, **kwargs)
        self.unifi_macs = frozenset(unifi_macs)
        self.adopt_pks = list(adopt_pks)
        self.sites = sites

    def _load_objects(self, diffsync_model):
        """Load Devices from the selected sites, plus the Devices being adopted."""
        if diffsync_model is not DeviceModel:
            super()._load_objects(diffsync_model)
            return
        queryset = DeviceModel._get_queryset()
        if self.sites is not None:
            queryset = queryset.filter(
                Q(location___custom_field_data__unifi_site__in=[site["name"] for site in self.sites])
                | Q(location__name__in=[site["desc"] for site in self.sites])
            )
        adopted = Device.objects.filter(pk__in=self.adopt_pks).prefetch_related("interfaces")
        parameter_names = DeviceModel.get_synced_attributes()
        for device in chain(queryset, adopted):
            self._load_single_object(device, DeviceModel, parameter_names)

    def _handle_single_parameter(self, parameters, parameter_name, database_object, diffsync_model):
        """Read a Device's `mac_address` from its Interfaces, since Device has no such field."""
        if diffsync_model is DeviceModel and parameter_name == "mac_address":
            parameters[parameter_name] = get_device_mac(database_object, self.unifi_macs)
            return
        super()._handle_single_parameter(parameters, parameter_name, database_object, diffsync_model)
