"""DiffSyncModel subclasses for Nautobot-to-UniFi data sync."""

from typing import Annotated, List, Optional

from diffsync.enum import DiffSyncModelFlags
from diffsync.exceptions import ObjectCrudException, ObjectNotCreated
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from nautobot.dcim.choices import InterfaceTypeChoices
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role, Status
from nautobot_ssot.contrib import CustomFieldAnnotation, NautobotModel
from typing_extensions import TypedDict

from nautobot_ssot_unifi.constants import (
    CLIENT_INTERFACE_NAME,
    CLIENT_ROLE,
    DEVICE_INTERFACE_NAME,
    SYSTEM_OF_RECORD,
)
from nautobot_ssot_unifi.utils.unifi import get_controller_name, get_selected_sites


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


class DeviceModel(NautobotModel):
    """DiffSync model for UniFi devices and clients.

    Devices are identified by MAC address, so renaming one in UniFi renames it in Nautobot. Nautobot keeps
    MAC addresses on Interfaces: the sync creates one Interface per Device to hold it, and the Nautobot
    adapter reads `mac_address` back from the Device's Interfaces (see `get_device_mac()`).
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

    system_of_record: Annotated[Optional[str], CustomFieldAnnotation(name="system_of_record")] = None
    ssot_last_synchronized: Annotated[Optional[str], CustomFieldAnnotation(name="ssot_last_synchronized")] = None
    unifi_controller: Annotated[Optional[str], CustomFieldAnnotation(name="unifi_controller")] = None

    @classmethod
    def _get_queryset(cls):
        """Load only Devices synced from the selected sites of this controller.

        A sync deletes every loaded Device that UniFi no longer reports, so this must never load
        Devices from other Systems of Record, other UniFi controllers, or sites left out of `sites`.
        Devices without a MAC address on any Interface cannot be matched and are left alone.
        """
        queryset = (
            super()
            ._get_queryset()
            .filter(
                _custom_field_data__system_of_record=SYSTEM_OF_RECORD,
                _custom_field_data__unifi_controller=get_controller_name(),
                pk__in=Interface.objects.exclude(mac_address__isnull=True).exclude(mac_address="").values("device"),
            )
            .prefetch_related("interfaces")
        )
        selected = get_selected_sites()
        if selected:
            queryset = queryset.filter(
                Q(location___custom_field_data__unifi_site__in=selected) | Q(location__name__in=selected)
            )
        return queryset

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


def get_device_mac(device: Device) -> Optional[str]:
    """MAC address identifying a Device: management Interfaces first, then by name.

    Args:
        device (Device): Device with its `interfaces` prefetched.

    Returns:
        Optional[str]: Lowercase MAC address, as UniFi reports it, or None if no Interface has one.
    """
    interfaces = sorted(device.interfaces.all(), key=lambda interface: (not interface.mgmt_only, interface.name))
    for interface in interfaces:
        if interface.mac_address:
            return str(interface.mac_address).lower()
    return None
