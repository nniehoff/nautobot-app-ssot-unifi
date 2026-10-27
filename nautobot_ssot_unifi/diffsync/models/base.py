"""DiffSyncModel subclasses for Nautobot-to-UniFi data sync."""

from datetime import date
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
from nautobot.ipam.models import VLAN, IPAddress, IPAddressToInterface, Namespace, Prefix, VLANGroup
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
from nautobot_ssot_unifi.utils.nautobot import find_devices_by_mac, find_vlan
from nautobot_ssot_unifi.utils.unifi import get_controller_name, get_namespace, get_selected_sites

# Custom fields on every object the sync creates or adopts: the System of Record, the date of the last sync that
# saw it, and the controller it came from. Querysets load only objects carrying this controller's values, so a
# sync never changes or deletes objects from elsewhere.
SystemOfRecord = Annotated[Optional[str], CustomFieldAnnotation(name="system_of_record")]
LastSynchronized = Annotated[Optional[str], CustomFieldAnnotation(name="ssot_last_synchronized")]
UniFiController = Annotated[Optional[str], CustomFieldAnnotation(name="unifi_controller")]
SYNCED_FIELDS = ("system_of_record", "ssot_last_synchronized", "unifi_controller")


def custom_field_data(attrs: dict) -> dict:
    """The synced custom fields set in a DiffSync model's attributes, for creating an object directly."""
    return {key: attrs[key] for key in SYNCED_FIELDS if attrs.get(key) is not None}


def synced_custom_field_data() -> dict:
    """Custom field data marking an object the sync creates outside a DiffSync model, such as an Interface."""
    return {
        "system_of_record": SYSTEM_OF_RECORD,
        "ssot_last_synchronized": date.today().isoformat(),
        "unifi_controller": get_controller_name(),
    }


def owned_filter() -> dict:
    """Queryset filter for objects synced from this controller."""
    return {
        "_custom_field_data__system_of_record": SYSTEM_OF_RECORD,
        "_custom_field_data__unifi_controller": get_controller_name(),
    }


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
    "vlangroup",
    "vlan",
    "device",
    "interface",
    "prefix",
    "ipaddress",
    "ipassignment",
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
    _attributes = ("name", "location_type__name", "status__name", "system_of_record", "ssot_last_synchronized")
    _children = {}

    unifi_site: Annotated[str, CustomFieldAnnotation(key="unifi_site")]
    unifi_controller: Annotated[str, CustomFieldAnnotation(key="unifi_controller")]
    name: str
    location_type__name: str
    status__name: str
    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None

    def update(self, attrs):
        """Update the object, also writing the custom fields identifying it, which an adopted one lacks."""
        return super().update({"unifi_site": self.unifi_site, "unifi_controller": self.unifi_controller, **attrs})

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
    _attributes = (
        "location__name",
        "status__name",
        "capabilities",
        "system_of_record",
        "ssot_last_synchronized",
        "unifi_controller",
    )
    _children = {}

    name: str
    location__name: str
    status__name: str
    capabilities: Optional[List[str]] = None
    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None
    unifi_controller: UniFiController = None

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
    _attributes = ("name", "controller__name", "capabilities", "system_of_record", "ssot_last_synchronized")
    _children = {}

    unifi_site: Annotated[str, CustomFieldAnnotation(key="unifi_site")]
    unifi_controller: Annotated[str, CustomFieldAnnotation(key="unifi_controller")]
    name: str
    controller__name: str
    capabilities: Optional[List[str]] = None
    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None

    def update(self, attrs):
        """Update the object, also writing the custom fields identifying it, which an adopted one lacks."""
        return super().update({"unifi_site": self.unifi_site, "unifi_controller": self.unifi_controller, **attrs})

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

    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None
    unifi_controller: UniFiController = None

    @classmethod
    def _get_queryset(cls):
        """Load only Wireless Networks synced from this controller, and with `sites` set, used by a selected site.

        A sync deletes every loaded Wireless Network UniFi no longer reports, and Wireless Networks have no
        Location, so without the second filter a WLAN of a site left out of `sites` would be deleted.
        """
        queryset = super()._get_queryset().filter(**owned_filter())
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


class VLANGroupModel(NautobotModel):
    """DiffSync model for the VLAN Group holding a UniFi site's VLANs, in the site's Location.

    Like Locations, a group is identified by its site's short name, and named after the site.
    """

    # Never delete VLAN Groups, like Locations: a site removed from `sites` keeps its group.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = VLANGroup
    _modelname = "vlangroup"
    _identifiers = ("unifi_site", "unifi_controller")
    _attributes = ("name", "location__name", "system_of_record", "ssot_last_synchronized")
    _children = {}

    unifi_site: Annotated[str, CustomFieldAnnotation(key="unifi_site")]
    unifi_controller: Annotated[str, CustomFieldAnnotation(key="unifi_controller")]
    name: str
    location__name: Optional[str] = None
    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None

    def update(self, attrs):
        """Update the object, also writing the custom fields identifying it, which an adopted one lacks."""
        return super().update({"unifi_site": self.unifi_site, "unifi_controller": self.unifi_controller, **attrs})

    @classmethod
    def _get_queryset(cls):
        """Load only VLAN Groups synced from the selected sites of this controller."""
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


class VLANModel(NautobotModel):
    """DiffSync model for the VLAN of a UniFi network, in its site's VLAN Group, or for an adopted VLAN, its own.

    Status is only set when the sync creates the VLAN. VLANs are never deleted: a network removed from UniFi may
    still be configured elsewhere.
    """

    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = VLAN
    _modelname = "vlan"
    _identifiers = ("vid", "vlan_group__name")
    _attributes = ("name", "status__name", *SYNCED_FIELDS)
    _children = {}

    vid: int
    vlan_group__name: Optional[str] = None
    name: str
    status__name: str
    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None
    unifi_controller: UniFiController = None

    @classmethod
    def _get_queryset(cls):
        """Load only VLANs synced from this controller, or in one of its VLAN Groups."""
        return (
            super()
            ._get_queryset()
            .filter(Q(**owned_filter()) | Q(vlan_group__in=VLANGroupModel._get_queryset()))
            .distinct()
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

    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None
    unifi_controller: UniFiController = None

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
                **owned_filter(),
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
                    _custom_field_data=synced_custom_field_data(),
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


def get_or_create_interface(mac: str, name: str, interface_type: str = InterfaceTypeChoices.TYPE_OTHER) -> Interface:
    """Get or create the named Interface of the Device with a MAC address.

    Args:
        mac (str): Lowercase MAC address identifying the Device.
        name (str): Interface name.
        interface_type (str): Type of the Interface if it is created.

    Returns:
        Interface: The Interface, created and marked as synced if the Device had none by that name.
    """
    devices = find_devices_by_mac([mac]).get(mac, [])
    if len(devices) != 1:
        raise ObjectCrudException(f"Expected one Device with MAC {mac}, found {len(devices)}.")
    interface = Interface.objects.filter(device=devices[0], name=name).first()
    if interface is None:
        interface = Interface(
            device=devices[0],
            name=name,
            type=interface_type,
            status=Status.objects.get(name="Active"),
            _custom_field_data=synced_custom_field_data(),
        )
        interface.validated_save()
    return interface


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
    _attributes = ("interface", "upstream_mac_address", "upstream_interface", *SYNCED_FIELDS)
    _children = {}

    mac_address: str
    interface: str
    upstream_mac_address: str
    upstream_interface: str
    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None
    unifi_controller: UniFiController = None

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
            upstream = get_or_create_interface(attrs["upstream_mac_address"], attrs["upstream_interface"])
            downstream = get_or_create_interface(ids["mac_address"], attrs["interface"])
            cls._free(upstream)
            cls._free(downstream)
            cable = Cable(
                termination_a=upstream,
                termination_b=downstream,
                status=Status.objects.get(name=CABLE_STATUS),
                # Always marked as synced: the Nautobot adapter only loads Cables it can tell are its own.
                _custom_field_data={**synced_custom_field_data(), **custom_field_data(attrs)},
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
        """Replace the Cable with one between the Interfaces UniFi now reports, or only update its custom fields."""
        merged = {**self.get_attrs(), **attrs}
        try:
            if set(attrs) <= set(SYNCED_FIELDS):
                cable = Cable.objects.get(pk=self.pk)
                cable._custom_field_data.update(custom_field_data(merged))  # pylint: disable=protected-access
                cable.validated_save()
            else:
                self._disconnect()
                cable = self._connect(self.get_identifiers(), merged)
        except (Cable.DoesNotExist, ObjectCrudException, ValidationError) as error:
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


class PrefixModel(NautobotModel):
    """DiffSync model for the subnet of each UniFi network, in the sync's Namespace.

    Status is only set when the sync creates the Prefix.
    """

    # Never delete Prefixes: other IP Addresses may be in a subnet UniFi stops using.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = Prefix
    _modelname = "prefix"
    _identifiers = ("network", "prefix_length", "namespace__name")
    _attributes = ("status__name", *SYNCED_FIELDS)
    _children = {}

    network: str
    prefix_length: int
    namespace__name: str
    status__name: str
    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None
    unifi_controller: UniFiController = None

    @classmethod
    def _get_queryset(cls):
        """Load only Prefixes synced from this controller in the sync's Namespace."""
        return super()._get_queryset().filter(**owned_filter(), namespace__name=get_namespace())

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create the Prefix; Nautobot needs the whole prefix at once to compute its range and parent."""
        try:
            prefix = Prefix(
                prefix=f"{ids['network']}/{ids['prefix_length']}",
                namespace=Namespace.objects.get(name=ids["namespace__name"]),
                status=Status.objects.get(name=attrs["status__name"]),
                _custom_field_data=custom_field_data(attrs),
            )
            prefix.validated_save()
        except (Namespace.DoesNotExist, Status.DoesNotExist, ValidationError) as error:
            raise ObjectNotCreated(error) from error
        # Skip NautobotModel.create, which would create the Prefix again from ids and attrs.
        model = super(NautobotModel, cls).create(adapter, ids, attrs)
        model.pk = prefix.pk
        return model


class IPAddressModel(NautobotModel):
    """DiffSync model for the IP address of a UniFi device or client, identified by address and Namespace.

    The mask comes from the UniFi network containing the address, else the narrowest Prefix in Nautobot. Status is
    only set when the sync creates the IP Address. The sync only changes or deletes IP Addresses it created or adopted;
    others are assigned to Interfaces as they are (see `UniFiDataSource.handle_existing_ip_addresses()`).
    """

    _model = IPAddress
    _modelname = "ipaddress"
    _identifiers = ("host", "parent__namespace__name")
    _attributes = (
        "mask_length",
        "status__name",
        "type",
        "system_of_record",
        "ssot_last_synchronized",
        "unifi_controller",
    )
    _children = {}

    host: str
    parent__namespace__name: str
    mask_length: int
    status__name: str
    type: str

    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None
    unifi_controller: UniFiController = None

    @classmethod
    def _get_queryset(cls):
        """Load only IP Addresses synced from this controller in the sync's Namespace.

        UniFiNautobotAdapter narrows this to the IP Addresses of the loaded Devices when `sites` is set.
        """
        return super()._get_queryset().filter(**owned_filter(), parent__namespace__name=get_namespace())

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create the IP Address under the narrowest Prefix containing it in the Namespace."""
        try:
            ip_address = IPAddress(
                address=f"{ids['host']}/{attrs['mask_length']}",
                namespace=Namespace.objects.get(name=ids["parent__namespace__name"]),
                status=Status.objects.get(name=attrs["status__name"]),
                type=attrs["type"],
                _custom_field_data=custom_field_data(attrs),
            )
            ip_address.validated_save()
        except (Namespace.DoesNotExist, Status.DoesNotExist, ValidationError) as error:
            raise ObjectNotCreated(error) from error
        # Skip NautobotModel.create, which would create the IP Address again from ids and attrs.
        model = super(NautobotModel, cls).create(adapter, ids, attrs)
        model.pk = ip_address.pk
        return model


class IPAddressAssignmentModel(NautobotModel):
    """DiffSync model for an IP address on the Interface of a UniFi device or client.

    Identified by the Device's MAC address and the address; moving the address to another Interface of the same
    Device updates the assignment.
    """

    _model = IPAddressToInterface
    _modelname = "ipassignment"
    _identifiers = ("mac_address", "host")
    _attributes = ("interface",)
    _children = {}

    mac_address: str
    host: str
    interface: str

    @staticmethod
    def _get_ip_address(host: str) -> IPAddress:
        """The IP Address in the sync's Namespace."""
        ip_address = IPAddress.objects.filter(host=host, parent__namespace__name=get_namespace()).first()
        if ip_address is None:
            raise ObjectCrudException(f"IP Address {host} not found in Namespace {get_namespace()}.")
        return ip_address

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Assign the IP Address to the Interface, creating the Interface if needed."""
        try:
            with transaction.atomic():
                assignment = IPAddressToInterface(
                    ip_address=cls._get_ip_address(ids["host"]),
                    interface=get_or_create_interface(ids["mac_address"], attrs["interface"]),
                )
                assignment.validated_save()
        except (ObjectCrudException, ValidationError) as error:
            raise ObjectNotCreated(error) from error
        model = super(NautobotModel, cls).create(adapter, ids, attrs)
        model.pk = assignment.pk
        return model

    def update(self, attrs):
        """Move the IP Address to the Interface UniFi now reports it on."""
        try:
            with transaction.atomic():
                assignment = IPAddressToInterface.objects.get(pk=self.pk)
                assignment.interface = get_or_create_interface(self.mac_address, attrs["interface"])
                assignment.validated_save()
        except (IPAddressToInterface.DoesNotExist, ObjectCrudException, ValidationError) as error:
            raise ObjectNotUpdated(error) from error
        return super(NautobotModel, self).update(attrs)

    def delete(self):
        """Delete the assignment, unless deleting its IP Address or Device earlier in the sync already did."""
        if not self._model.objects.filter(pk=self.pk).exists():
            # Skip NautobotModel.delete, which fails on a missing object.
            return super(NautobotModel, self).delete()
        return super().delete()


class InterfaceModel(NautobotModel):
    """DiffSync model for the 802.1Q settings of a UniFi switch port, identified by its Device's MAC and its name.

    VLANs are compared by VLAN ID and set to the VLAN `find_vlan()` picks for the Device's Location, so a VLAN made by
    hand is used when it fits. Type is only set when the sync creates the Interface. Interfaces are never deleted.
    The Interfaces of a synced or adopted Device belong to it, so the sync marks the ports it manages as synced.
    """

    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = Interface
    _modelname = "interface"
    _identifiers = ("mac_address", "name")
    _attributes = ("type", "mode", "untagged_vid", "tagged_vids", *SYNCED_FIELDS)
    _children = {}

    mac_address: str
    name: str
    type: str
    mode: Optional[str] = None
    untagged_vid: Optional[int] = None
    tagged_vids: List[int] = []
    system_of_record: SystemOfRecord = None
    ssot_last_synchronized: LastSynchronized = None
    unifi_controller: UniFiController = None

    @staticmethod
    def _get_vlan(vid: int, interface: Interface) -> VLAN:
        """The VLAN with an ID that the Interface's Device can use."""
        vlan = find_vlan(vid, interface.device.location)
        if vlan is None:
            raise ObjectCrudException(f"No VLAN {vid} available to {interface.device} in {interface.device.location}.")
        return vlan

    @classmethod
    def _apply(cls, interface: Interface, attrs: dict):
        """Set the Interface's mode, VLANs, and synced custom fields."""
        interface.mode = attrs.get("mode") or ""
        untagged_vid = attrs.get("untagged_vid")
        interface.untagged_vlan = cls._get_vlan(untagged_vid, interface) if untagged_vid else None
        interface._custom_field_data.update(custom_field_data(attrs))  # pylint: disable=protected-access
        interface.validated_save()
        if interface.mode == "tagged":
            interface.tagged_vlans.set([cls._get_vlan(vid, interface) for vid in attrs.get("tagged_vids") or []])

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create the Interface if the Device has none by that name, and set its mode and VLANs."""
        try:
            with transaction.atomic():
                interface = get_or_create_interface(ids["mac_address"], ids["name"], attrs["type"])
                cls._apply(interface, attrs)
        except (ObjectCrudException, ValidationError) as error:
            raise ObjectNotCreated(error) from error
        model = super(NautobotModel, cls).create(adapter, ids, attrs)
        model.pk = interface.pk
        return model

    def update(self, attrs):
        """Set the Interface's mode and VLANs to what UniFi now reports."""
        try:
            with transaction.atomic():
                self._apply(Interface.objects.get(pk=self.pk), {**self.get_attrs(), **attrs})
        except (Interface.DoesNotExist, ObjectCrudException, ValidationError) as error:
            raise ObjectNotUpdated(error) from error
        return super(NautobotModel, self).update(attrs)
