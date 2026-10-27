"""DiffSyncModel subclasses for Nautobot-to-UniFi data sync."""

from typing import Annotated, List, Optional

from diffsync.enum import DiffSyncModelFlags
from diffsync.exceptions import ObjectCrudException, ObjectNotCreated, ObjectNotDeleted, ObjectNotUpdated
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from nautobot.dcim.choices import InterfaceTypeChoices
from nautobot.dcim.models import (
    Cable,
    Controller,
    ControllerManagedDeviceGroup,
    Device,
    DeviceType,
    Interface,
    Location,
    LocationType,
    Manufacturer,
    Platform,
    SoftwareVersion,
)
from nautobot.extras.models import Role, Status
from nautobot.wireless.models import ControllerManagedDeviceGroupWirelessNetworkAssignment, WirelessNetwork
from nautobot_ssot.contrib import CustomFieldAnnotation, NautobotModel
from typing_extensions import TypedDict

from nautobot_ssot_unifi.constants import (
    CABLE_STATUS,
    CLIENT_INTERFACE_NAME,
    CLIENT_ROLE,
    DEVICE_INTERFACE_NAME,
    SYSTEM_OF_RECORD,
)
from nautobot_ssot_unifi.utils.nautobot import find_devices_by_mac
from nautobot_ssot_unifi.utils.unifi import get_controller_name, get_selected_sites

# Load and sync order of the models in both adapters: every model after the ones it refers to.
TOP_LEVEL = [
    "locationtype",
    "location",
    "controller",
    "devicegroup",
    "wirelessnetwork",
    "wirelessnetworkassignment",
    "manufacturer",
    "devicetype",
    "role",
    "platform",
    "softwareversion",
    "device",
    "cable",
]


class ContentTypeDict(TypedDict):
    """Many-to-many relationship typed dict explaining which fields are interesting."""

    app_label: str
    model: str


class LocationTypeModel(NautobotModel):
    """DiffSync model for UniFi locations."""

    # Shared with other Systems of Record: create what UniFi needs, never
    # delete what UniFi does not know about.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = LocationType
    _modelname = "locationtype"
    _identifiers = ("name",)
    _attributes = ("content_types",)
    _children = {}

    name: str
    content_types: List[ContentTypeDict] = []


class LocationModel(NautobotModel):
    """DiffSync model for UniFi sites.

    A site is identified by its short name (e.g. "default" or "nbxeaqa6"), which UniFi never changes,
    so renaming a site in UniFi renames its Location instead of creating a new one.
    """

    # Never delete Locations: Devices from other Systems of Record can sit in
    # them, and a site removed from `sites` should keep its Location.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = Location
    _modelname = "location"
    _identifiers = ("unifi_site", "unifi_controller")
    _attributes = ("name", "location_type__name", "status__name")
    _children = {}

    unifi_site: Annotated[str, CustomFieldAnnotation(key="unifi_site")]
    unifi_controller: Annotated[str, CustomFieldAnnotation(key="unifi_controller")]
    name: str
    location_type__name: str
    status__name: str

    @classmethod
    def _get_queryset(cls):
        """Load only Locations synced from the selected sites of this controller."""
        queryset = (
            super()
            ._get_queryset()
            .filter(_custom_field_data__unifi_controller=get_controller_name())
            .exclude(_custom_field_data__unifi_site__isnull=True)
            .exclude(_custom_field_data__unifi_site=None)
        )
        selected = get_selected_sites()
        if selected:
            queryset = queryset.filter(Q(_custom_field_data__unifi_site__in=selected) | Q(name__in=selected))
        return queryset


class ManufacturerModel(NautobotModel):
    """DiffSync model for UniFi client vendors."""

    # Shared with other Systems of Record: create what UniFi needs, never
    # delete what UniFi does not know about.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = Manufacturer
    _modelname = "manufacturer"
    _identifiers = ("name",)
    _attributes = ()
    _children = {}

    name: str


class DeviceTypeModel(NautobotModel):
    """DiffSync model for UniFi device hardware."""

    # Shared with other Systems of Record: create what UniFi needs, never
    # delete what UniFi does not know about.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = DeviceType
    _modelname = "devicetype"
    _identifiers = ("model", "manufacturer__name")
    _attributes = ()
    _children = {}

    model: str
    manufacturer__name: str


class RoleModel(NautobotModel):
    """DiffSync model for UniFi device roles."""

    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = Role
    _modelname = "role"
    _identifiers = ("name",)
    _attributes = ("content_types",)
    _children = {}

    name: str
    content_types: List[ContentTypeDict] = []


class PlatformModel(NautobotModel):
    """DiffSync model for the Platform of each kind of UniFi device."""

    # Shared with other Systems of Record: create what UniFi needs, never
    # delete what UniFi does not know about.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = Platform
    _modelname = "platform"
    _identifiers = ("name",)
    _attributes = ()
    _children = {}

    name: str


class SoftwareVersionModel(NautobotModel):
    """DiffSync model for UniFi device firmware versions."""

    # Versions no device runs any more are kept as history.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = SoftwareVersion
    _modelname = "softwareversion"
    _identifiers = ("platform__name", "version")
    _attributes = ("status__name",)
    _children = {}

    platform__name: str
    version: str
    status__name: str


class ControllerModel(NautobotModel):
    """DiffSync model for the UniFi controller itself, managing its sites' devices and wireless networks.

    Location and Status are only set when the sync creates the Controller, and capabilities are only added to.
    """

    # Never delete the Controller: Devices of other sites, or another sync, may still use it.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = Controller
    _modelname = "controller"
    _identifiers = ("name",)
    _attributes = ("location__name", "status__name", "capabilities")
    _children = {}

    name: str
    location__name: str
    status__name: str
    capabilities: Optional[List[str]] = None

    @classmethod
    def _get_queryset(cls):
        """Load only this controller."""
        return super()._get_queryset().filter(name=get_controller_name())


class ControllerManagedDeviceGroupModel(NautobotModel):
    """DiffSync model for a UniFi site's group of devices managed by the controller.

    Like Locations, a group is identified by its site's short name, and named after the site.
    """

    # Never delete groups, like Locations: a site removed from `sites` keeps its group.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = ControllerManagedDeviceGroup
    _modelname = "devicegroup"
    _identifiers = ("unifi_site", "unifi_controller")
    _attributes = ("name", "controller__name", "capabilities")
    _children = {}

    unifi_site: Annotated[str, CustomFieldAnnotation(key="unifi_site")]
    unifi_controller: Annotated[str, CustomFieldAnnotation(key="unifi_controller")]
    name: str
    controller__name: str
    capabilities: Optional[List[str]] = None

    @classmethod
    def _get_queryset(cls):
        """Load only groups synced from the selected sites of this controller."""
        queryset = (
            super()
            ._get_queryset()
            .filter(_custom_field_data__unifi_controller=get_controller_name())
            .exclude(_custom_field_data__unifi_site__isnull=True)
            .exclude(_custom_field_data__unifi_site=None)
        )
        selected = get_selected_sites()
        if selected:
            queryset = queryset.filter(Q(_custom_field_data__unifi_site__in=selected) | Q(name__in=selected))
        return queryset


class WirelessNetworkModel(NautobotModel):
    """DiffSync model for UniFi WLANs, identified by SSID.

    A WLAN with the same SSID in several sites is one Wireless Network, assigned to each site's group.
    Passphrases are never synced.
    """

    _model = WirelessNetwork
    _modelname = "wirelessnetwork"
    _identifiers = ("name",)
    _attributes = (
        "ssid",
        "mode",
        "enabled",
        "authentication",
        "hidden",
        "system_of_record",
        "ssot_last_synchronized",
        "unifi_controller",
    )
    _children = {}

    name: str
    ssid: str
    mode: str
    enabled: bool
    authentication: str
    hidden: bool

    system_of_record: Annotated[Optional[str], CustomFieldAnnotation(name="system_of_record")] = None
    ssot_last_synchronized: Annotated[Optional[str], CustomFieldAnnotation(name="ssot_last_synchronized")] = None
    unifi_controller: Annotated[Optional[str], CustomFieldAnnotation(name="unifi_controller")] = None

    @classmethod
    def _get_queryset(cls):
        """Load only Wireless Networks synced from this controller, and with `sites` set, used by a selected site.

        A sync deletes every loaded Wireless Network UniFi no longer reports, and Wireless Networks have no
        Location, so without the second filter a WLAN of a site left out of `sites` would be deleted.
        """
        queryset = (
            super()
            ._get_queryset()
            .filter(
                _custom_field_data__system_of_record=SYSTEM_OF_RECORD,
                _custom_field_data__unifi_controller=get_controller_name(),
            )
        )
        if get_selected_sites():
            queryset = queryset.filter(
                controller_managed_device_group_assignments__controller_managed_device_group__in=(
                    ControllerManagedDeviceGroupModel._get_queryset()
                )
            ).distinct()
        return queryset


class WirelessNetworkAssignmentModel(NautobotModel):
    """DiffSync model for the Wireless Networks of a UniFi site's group."""

    _model = ControllerManagedDeviceGroupWirelessNetworkAssignment
    _modelname = "wirelessnetworkassignment"
    _identifiers = ("controller_managed_device_group__name", "wireless_network__name")
    _attributes = ()
    _children = {}

    controller_managed_device_group__name: str
    wireless_network__name: str

    def delete(self):
        """Delete the assignment, unless deleting its Wireless Network earlier in the sync already did."""
        if not self._model.objects.filter(pk=self.pk).exists():
            # Skip NautobotModel.delete, which fails on a missing object.
            return super(NautobotModel, self).delete()
        return super().delete()

    @classmethod
    def _get_queryset(cls):
        """Load only the assignments of groups synced from the selected sites of this controller."""
        return (
            super()
            ._get_queryset()
            .filter(controller_managed_device_group__in=ControllerManagedDeviceGroupModel._get_queryset())
        )


class DeviceModel(NautobotModel):
    """DiffSync model for UniFi devices and clients.

    Devices are identified by MAC address, so renaming one in UniFi renames it in Nautobot. Nautobot keeps
    MAC addresses on Interfaces: the sync creates one Interface per Device to hold it, and the Nautobot
    adapter reads `mac_address` back from the Device's Interfaces (see `get_device_mac()`).

    Role, Device Type, and Status are only set when the sync creates a Device, and serial and Platform only
    when UniFi reports one and Nautobot has none: `UniFiAdapter.keep_nautobot_fields()` copies the Nautobot
    values over UniFi's before the diff, so corrections made in Nautobot are never reverted. Clients keep
    the Platform, Software Version, and device group set in Nautobot.
    """

    _model = Device
    _modelname = "device"
    _identifiers = ("mac_address",)
    _attributes = (
        "name",
        "location__name",
        "serial",
        "role__name",
        "device_type__model",
        "device_type__manufacturer__name",
        "status__name",
        "platform__name",
        "software_version__platform__name",
        "software_version__version",
        "controller_managed_device_group__name",
        "system_of_record",
        "ssot_last_synchronized",
        "unifi_controller",
    )
    _children = {}

    mac_address: str
    name: str
    location__name: str
    serial: Optional[str] = None
    role__name: Optional[str] = None
    device_type__model: Optional[str] = None
    device_type__manufacturer__name: Optional[str] = None
    status__name: str
    platform__name: Optional[str] = None
    software_version__platform__name: Optional[str] = None
    software_version__version: Optional[str] = None
    controller_managed_device_group__name: Optional[str] = None

    system_of_record: Annotated[Optional[str], CustomFieldAnnotation(name="system_of_record")] = None
    ssot_last_synchronized: Annotated[Optional[str], CustomFieldAnnotation(name="ssot_last_synchronized")] = None
    unifi_controller: Annotated[Optional[str], CustomFieldAnnotation(name="unifi_controller")] = None

    @classmethod
    def _get_queryset(cls):
        """Load only Devices synced from this controller.

        A sync deletes every loaded Device that UniFi no longer reports, so this must never load
        Devices from other Systems of Record or other UniFi controllers. Devices without a MAC
        address on any Interface cannot be matched and are left alone. UniFiNautobotAdapter
        narrows this to the selected sites and adds adopted Devices.
        """
        return (
            super()
            ._get_queryset()
            .filter(
                _custom_field_data__system_of_record=SYSTEM_OF_RECORD,
                _custom_field_data__unifi_controller=get_controller_name(),
                pk__in=Interface.objects.exclude(mac_address__isnull=True).exclude(mac_address="").values("device"),
            )
            .prefetch_related("interfaces")
        )

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create the Device, then the Interface holding its MAC address.

        `mac_address` is not a Device field, so it is kept out of the parameters NautobotModel sets on the Device.
        """
        device = Device()
        is_client = attrs.get("role__name") == CLIENT_ROLE
        try:
            # One transaction, so a Device is never left without the Interface that identifies it.
            with transaction.atomic():
                cls._update_obj_with_parameters(device, attrs, adapter)
                Interface(
                    device=device,
                    name=CLIENT_INTERFACE_NAME if is_client else DEVICE_INTERFACE_NAME,
                    type=InterfaceTypeChoices.TYPE_OTHER,
                    mgmt_only=not is_client,
                    mac_address=ids["mac_address"],
                    status=Status.objects.get(name="Active"),
                ).validated_save()
        except (ObjectCrudException, ValidationError) as error:
            raise ObjectNotCreated(error) from error
        # Skip NautobotModel.create, which would create the Device again from ids and attrs.
        return super(NautobotModel, cls).create(adapter, ids, attrs)


def get_device_mac(device: Device, preferred: frozenset = frozenset()) -> Optional[str]:
    """MAC address identifying a Device: one UniFi reports, else management Interfaces first, then by name.

    Preferring a MAC UniFi reports matters for Devices with several MAC addresses, such as a switch whose
    ports all have one: matching on another MAC would leave the Device unmatched, and the sync would delete it.

    Args:
        device (Device): Device with its `interfaces` prefetched.
        preferred (frozenset): Lowercase MAC addresses UniFi reports.

    Returns:
        Optional[str]: Lowercase MAC address, as UniFi reports it, or None if no Interface has one.
    """
    interfaces = sorted(device.interfaces.all(), key=lambda interface: (not interface.mgmt_only, interface.name))
    macs = [str(interface.mac_address).lower() for interface in interfaces if interface.mac_address]
    return next((mac for mac in macs if mac in preferred), macs[0] if macs else None)


def is_synced_cable(cable: Cable) -> bool:
    """Whether a Cable was created by a sync from this controller.

    Args:
        cable (Cable): Nautobot Cable.

    Returns:
        bool: True if its System of Record and UniFi Controller custom fields point here.
    """
    return (
        cable.cf.get("system_of_record") == SYSTEM_OF_RECORD
        and cable.cf.get("unifi_controller") == get_controller_name()
    )


class CableModel(NautobotModel):
    """DiffSync model for the wired link from a UniFi device or client to the switch port UniFi reports it on.

    Every device and client has one uplink, so a Cable is identified by the MAC address of its downstream
    end, `termination_b`. The upstream switch port is `termination_a`. Ports are matched to Interfaces by
    name (see `UniFiAdapter.load_cables()`); a missing Interface is created when the Cable is.

    The sync only changes or deletes Cables it created. Creating a Cable on an Interface that already has
    one the sync did not create fails; one the sync created, for a device that moved, is replaced.
    """

    _model = Cable
    _modelname = "cable"
    _identifiers = ("mac_address",)
    _attributes = ("interface", "upstream_mac_address", "upstream_interface")
    _children = {}

    mac_address: str
    interface: str
    upstream_mac_address: str
    upstream_interface: str

    @staticmethod
    def _get_interface(mac: str, name: str) -> Interface:
        """Get or create the named Interface of the Device with a MAC address."""
        devices = find_devices_by_mac([mac]).get(mac, [])
        if len(devices) != 1:
            raise ObjectCrudException(f"Expected one Device with MAC {mac}, found {len(devices)}.")
        interface = Interface.objects.filter(device=devices[0], name=name).first()
        if interface is None:
            interface = Interface(
                device=devices[0],
                name=name,
                type=InterfaceTypeChoices.TYPE_OTHER,
                status=Status.objects.get(name="Active"),
            )
            interface.validated_save()
        return interface

    @staticmethod
    def _free(interface: Interface):
        """Remove a Cable the sync created from an Interface; refuse to touch any other Cable."""
        cable = interface.cable
        if cable is None:
            return
        if not is_synced_cable(cable):
            raise ObjectCrudException(
                f"{interface.device} {interface} already has Cable {cable} not synced from UniFi."
            )
        cable.delete()
        interface.refresh_from_db()

    @classmethod
    def _connect(cls, ids: dict, attrs: dict) -> Cable:
        """Create the Cable between the two Interfaces, creating them if needed."""
        with transaction.atomic():
            upstream = cls._get_interface(attrs["upstream_mac_address"], attrs["upstream_interface"])
            downstream = cls._get_interface(ids["mac_address"], attrs["interface"])
            cls._free(upstream)
            cls._free(downstream)
            cable = Cable(
                termination_a=upstream,
                termination_b=downstream,
                status=Status.objects.get(name=CABLE_STATUS),
                _custom_field_data={
                    "system_of_record": SYSTEM_OF_RECORD,
                    "unifi_controller": get_controller_name(),
                },
            )
            cable.validated_save()
        return cable

    def _disconnect(self):
        """Delete this Cable, unless something earlier in the sync, such as deleting a Device, already did."""
        cable = Cable.objects.filter(pk=self.pk).first()
        if cable is not None:
            cable.delete()

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create the Cable, and any Interface it needs."""
        try:
            cable = cls._connect(ids, attrs)
        except (ObjectCrudException, ValidationError) as error:
            raise ObjectNotCreated(error) from error
        model = super(NautobotModel, cls).create(adapter, ids, attrs)
        model.pk = cable.pk
        return model

    def update(self, attrs):
        """Replace the Cable with one between the Interfaces UniFi now reports."""
        merged = {**self.get_attrs(), **attrs}
        try:
            self._disconnect()
            cable = self._connect(self.get_identifiers(), merged)
        except (ObjectCrudException, ValidationError) as error:
            raise ObjectNotUpdated(error) from error
        self.pk = cable.pk
        return super(NautobotModel, self).update(attrs)

    def delete(self):
        """Delete the Cable. Interfaces the sync created for it are kept."""
        try:
            self._disconnect()
        except ValidationError as error:
            raise ObjectNotDeleted(error) from error
        return super(NautobotModel, self).delete()
