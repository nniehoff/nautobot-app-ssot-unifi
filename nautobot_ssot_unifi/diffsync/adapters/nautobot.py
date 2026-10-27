"""Nautobot Adapter for Unifi SSoT plugin."""

from itertools import chain

from diffsync.exceptions import ObjectAlreadyExists
from django.db.models import Q
from nautobot.dcim.models import Cable, Device, Interface
from nautobot.ipam.models import IPAddressToInterface
from nautobot_ssot.contrib import NautobotAdapter

from nautobot_ssot_unifi.constants import SYSTEM_OF_RECORD
from nautobot_ssot_unifi.diffsync.models.base import (
    SYNCED_FIELDS,
    TOP_LEVEL,
    CableModel,
    ControllerManagedDeviceGroupModel,
    ControllerModel,
    DeviceModel,
    DeviceTypeModel,
    InterfaceModel,
    IPAddressAssignmentModel,
    IPAddressModel,
    LocationModel,
    LocationTypeModel,
    ManufacturerModel,
    PlatformModel,
    PrefixModel,
    RoleModel,
    SoftwareVersionModel,
    VLANGroupModel,
    VLANModel,
    WirelessNetworkAssignmentModel,
    WirelessNetworkModel,
    get_device_mac,
)
from nautobot_ssot_unifi.utils.unifi import get_controller_name, get_namespace


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
    vlangroup = VLANGroupModel
    vlan = VLANModel
    device = DeviceModel
    interface = InterfaceModel
    prefix = PrefixModel
    ipaddress = IPAddressModel
    ipassignment = IPAddressAssignmentModel
    cable = CableModel

    top_level = TOP_LEVEL

    def __init__(  # pylint: disable=too-many-arguments
        self, *args, unifi_macs=frozenset(), unifi_ips=frozenset(), adopt_pks=(), adopt=None, sites=None, **kwargs
    ):
        """Initialize the Nautobot adapter.

        Args:
            *args: Positional arguments passed to NautobotAdapter.
            unifi_macs (frozenset): Lowercase MAC addresses UniFi reports, preferred when matching Devices.
            unifi_ips (frozenset): IP addresses UniFi reports, whose Interface assignments are loaded even when the
                sync did not create the IP Address.
            adopt_pks (Iterable): Primary keys of Devices not yet synced from this controller to load anyway,
                so the sync takes them over.
            adopt (dict, optional): Other objects to take over: model name to primary key to the identifiers to load
                the object with, for objects identified by custom fields they do not have yet.
            sites (list, optional): Selected UniFi sites. When set, only Devices in their Locations are loaded,
                matched by the Location's `unifi_site` or by the site's name.
            **kwargs: Keyword arguments passed to NautobotAdapter.
        """
        super().__init__(*args, **kwargs)
        self.unifi_macs = frozenset(unifi_macs)
        self.unifi_ips = frozenset(unifi_ips)
        self.adopt_pks = list(adopt_pks)
        self.adopt = adopt or {}
        # Identifiers to load adopted objects with, by primary key.
        self.adopt_identifiers = {
            pk: identifiers for by_pk in self.adopt.values() for pk, identifiers in by_pk.items() if identifiers
        }
        self.sites = sites
        # Primary keys of the loaded Devices: only their Cables are loaded.
        self.device_pks = set()

    def _load_objects(self, diffsync_model):
        """Load the objects synced from this controller, plus the ones being adopted.

        Devices are limited to the selected sites; Cables, Interfaces, and IP Addresses to the loaded Devices'.
        """
        if diffsync_model is CableModel:
            self._load_cables()
            return
        if diffsync_model is InterfaceModel:
            self._load_interfaces()
            return
        if diffsync_model is IPAddressModel:
            self._load_ip_addresses()
            return
        if diffsync_model is IPAddressAssignmentModel:
            self._load_ip_assignments()
            return
        if diffsync_model is not DeviceModel:
            super()._load_objects(diffsync_model)
            self._load_adopted(diffsync_model)
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

    def _load_adopted(self, diffsync_model):
        """Load the objects of a model the sync is adopting, which its queryset leaves out as not synced yet."""
        pks = self.adopt.get(diffsync_model._modelname, {})
        if not pks:
            return
        parameter_names = diffsync_model.get_synced_attributes()
        for database_object in diffsync_model._model.objects.filter(pk__in=list(pks)):
            self._load_single_object(database_object, diffsync_model, parameter_names)

    def _load_cables(self):
        """Load the Interface-to-Interface Cables synced from this controller whose downstream Device was loaded.

        Cables of Devices in sites left out of `sites` are not loaded, so they are never deleted.
        """
        cables = Cable.objects.filter(
            Q(
                _custom_field_data__system_of_record=SYSTEM_OF_RECORD,
                _custom_field_data__unifi_controller=get_controller_name(),
            )
            | Q(pk__in=list(self.adopt.get(CableModel._modelname, {})))
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
                        **{key: cable.cf.get(key) for key in SYNCED_FIELDS},
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

    def _load_interfaces(self):
        """Load the Interfaces of the loaded Devices with their 802.1Q settings, VLANs by VLAN ID."""
        devices = {
            device.pk: device for device in Device.objects.filter(pk__in=self.device_pks).prefetch_related("interfaces")
        }
        interfaces = (
            Interface.objects.filter(device__in=self.device_pks)
            .select_related("untagged_vlan")
            .prefetch_related("tagged_vlans")
        )
        for interface in interfaces:
            mac = get_device_mac(devices[interface.device_id], self.unifi_macs)
            if mac is None:
                continue
            self.add(
                InterfaceModel(
                    mac_address=mac,
                    name=interface.name,
                    type=interface.type,
                    mode=interface.mode or None,
                    untagged_vid=interface.untagged_vlan.vid if interface.untagged_vlan else None,
                    tagged_vids=sorted({vlan.vid for vlan in interface.tagged_vlans.all()}),
                    **{key: interface.cf.get(key) for key in SYNCED_FIELDS},
                    pk=interface.pk,
                )
            )

    def _load_ip_addresses(self):
        """Load the IP Addresses synced from this controller; with `sites` set, only those of the loaded Devices.

        IP Addresses have no Location, so without the filter those of a site left out of `sites` would be deleted.
        """
        queryset = IPAddressModel._get_queryset()
        if self.sites is not None:
            queryset = queryset.filter(interface_assignments__interface__device__in=self.device_pks).distinct()
        parameter_names = IPAddressModel.get_synced_attributes()
        for ip_address in queryset:
            self._load_single_object(ip_address, IPAddressModel, parameter_names)
        self._load_adopted(IPAddressModel)

    def _load_ip_assignments(self):
        """Load the IP Address assignments to Interfaces of the loaded Devices that the sync manages.

        Those are assignments of IP Addresses the sync created, or that UniFi reports. Other addresses set up by
        hand on a synced Device are never loaded, so never removed.
        """
        assignments = IPAddressToInterface.objects.filter(
            interface__device__in=self.device_pks,
            ip_address__parent__namespace__name=get_namespace(),
        ).select_related("interface", "ip_address")
        synced_ips = {ip_address.host for ip_address in self.get_all(IPAddressModel)}
        devices = {
            device.pk: device for device in Device.objects.filter(pk__in=self.device_pks).prefetch_related("interfaces")
        }
        for assignment in assignments.order_by("interface__name"):
            host = assignment.ip_address.host
            if host not in synced_ips and host not in self.unifi_ips:
                continue
            mac = get_device_mac(devices[assignment.interface.device_id], self.unifi_macs)
            if mac is None:
                continue
            try:
                self.add(
                    IPAddressAssignmentModel(
                        mac_address=mac, host=host, interface=assignment.interface.name, pk=assignment.pk
                    )
                )
            except ObjectAlreadyExists:
                # The same address on several Interfaces of one Device: the first by name is managed.
                continue

    def _handle_single_parameter(self, parameters, parameter_name, database_object, diffsync_model):
        """Read a Device's `mac_address` from its Interfaces, since Device has no such field.

        Adopted objects identified by custom fields they do not have yet are loaded with the identifiers they get.
        """
        identifiers = self.adopt_identifiers.get(database_object.pk, {})
        if parameter_name in identifiers:
            parameters[parameter_name] = identifiers[parameter_name]
            return
        if diffsync_model is DeviceModel and parameter_name == "mac_address":
            parameters[parameter_name] = get_device_mac(database_object, self.unifi_macs)
            return
        super()._handle_single_parameter(parameters, parameter_name, database_object, diffsync_model)
