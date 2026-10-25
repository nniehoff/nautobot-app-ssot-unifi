"""DiffSyncModel subclasses for Nautobot-to-UniFi data sync."""

from typing import Annotated, List, Optional

from diffsync.enum import DiffSyncModelFlags
from nautobot.dcim.models import Device, DeviceType, Location, LocationType, Manufacturer
from nautobot.extras.models import Role
from nautobot_ssot.contrib import CustomFieldAnnotation, NautobotModel
from typing_extensions import TypedDict

from nautobot_ssot_unifi.constants import SYSTEM_OF_RECORD
from nautobot_ssot_unifi.utils.unifi import get_controller_name


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
    """DiffSync model for UniFi locations."""

    # Shared with other Systems of Record: create what UniFi needs, never
    # delete what UniFi does not know about.
    model_flags: DiffSyncModelFlags = DiffSyncModelFlags.SKIP_UNMATCHED_DST

    _model = Location
    _modelname = "location"
    _identifiers = ("name", "location_type__name")
    _attributes = ("status__name",)
    _children = {}

    name: str
    location_type__name: str
    status__name: str


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
    """DiffSync model for UniFi devices."""

    _model = Device
    _modelname = "device"
    _identifiers = ("name",)
    _attributes = (
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
        """Load only Devices synced from this controller, so a sync never deletes Devices from other sources.

        Filtering on the controller as well as the System of Record keeps one controller's sync from
        deleting Devices that another UniFi controller manages.
        """
        return (
            super()
            ._get_queryset()
            .filter(
                _custom_field_data__system_of_record=SYSTEM_OF_RECORD,
                _custom_field_data__unifi_controller=get_controller_name(),
            )
        )
