"""Nautobot Adapter for Unifi SSoT plugin."""

from itertools import chain

from diffsync.exceptions import ObjectAlreadyExists
from django.db.models import Q
from nautobot.dcim.models import Cable, Device, Interface
from nautobot_ssot.contrib import NautobotAdapter

from nautobot_ssot_unifi.constants import SYSTEM_OF_RECORD
from nautobot_ssot_unifi.diffsync.models.base import (
    TOP_LEVEL,
    CableModel,
    ControllerManagedDeviceGroupModel,
    ControllerModel,
    DeviceModel,
    DeviceTypeModel,
    LocationModel,
    LocationTypeModel,
    ManufacturerModel,
    PlatformModel,
    RoleModel,
    SoftwareVersionModel,
    WirelessNetworkAssignmentModel,
    WirelessNetworkModel,
    get_device_mac,
)
from nautobot_ssot_unifi.utils.unifi import get_controller_name


class UniFiNautobotAdapter(NautobotAdapter):
    """DiffSync adapter for Nautobot."""

    locationtype = LocationTypeModel
    location = LocationModel
    manufacturer = ManufacturerModel
    devicetype = DeviceTypeModel
    role = RoleModel
    platform = PlatformModel
    softwareversion = SoftwareVersionModel
    controller = ControllerModel
    devicegroup = ControllerManagedDeviceGroupModel
    wirelessnetwork = WirelessNetworkModel
    wirelessnetworkassignment = WirelessNetworkAssignmentModel
    device = DeviceModel
    cable = CableModel

    top_level = TOP_LEVEL

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
        # Primary keys of the loaded Devices: only their Cables are loaded.
        self.device_pks = set()

    def _load_objects(self, diffsync_model):
        """Load Devices from the selected sites, plus the Devices being adopted, and their Cables."""
        if diffsync_model is CableModel:
            self._load_cables()
            return
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
            self.device_pks.add(device.pk)

    def _load_cables(self):
        """Load the Interface-to-Interface Cables synced from this controller whose downstream Device was loaded.

        Cables of Devices in sites left out of `sites` are not loaded, so they are never deleted.
        """
        cables = Cable.objects.filter(
            _custom_field_data__system_of_record=SYSTEM_OF_RECORD,
            _custom_field_data__unifi_controller=get_controller_name(),
        )
        for cable in cables:
            # Nautobot 3 keeps terminations in a separate table, so filter on their type here rather than in SQL.
            upstream, downstream = cable.termination_a, cable.termination_b
            if not isinstance(upstream, Interface) or not isinstance(downstream, Interface):
                continue
            if downstream.device_id not in self.device_pks:
                continue
            mac = get_device_mac(downstream.device, self.unifi_macs)
            upstream_mac = get_device_mac(upstream.device, self.unifi_macs)
            if mac is None or upstream_mac is None:
                continue
            try:
                self.add(
                    CableModel(
                        mac_address=mac,
                        interface=downstream.name,
                        upstream_mac_address=upstream_mac,
                        upstream_interface=upstream.name,
                        pk=cable.pk,
                    )
                )
            except ObjectAlreadyExists:
                self.job.logger.warning(
                    "%s has more than one Cable synced from UniFi; only %s is managed.",
                    downstream.device,
                    self.get(CableModel, mac).upstream_interface,
                    extra={"object": cable},
                )

    def _handle_single_parameter(self, parameters, parameter_name, database_object, diffsync_model):
        """Read a Device's `mac_address` from its Interfaces, since Device has no such field."""
        if diffsync_model is DeviceModel and parameter_name == "mac_address":
            parameters[parameter_name] = get_device_mac(database_object, self.unifi_macs)
            return
        super()._handle_single_parameter(parameters, parameter_name, database_object, diffsync_model)
