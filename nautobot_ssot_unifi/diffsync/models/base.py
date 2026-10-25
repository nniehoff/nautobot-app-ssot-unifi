"""DiffSyncModel subclasses for Nautobot-to-UniFi data sync."""

from typing import Annotated, List, Optional

from diffsync.enum import DiffSyncModelFlags
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import Role
from nautobot_ssot.contrib import CustomFieldAnnotation, NautobotModel
from typing_extensions import TypedDict


class ContentTypeDict(TypedDict):
    """Many-to-many relationship typed dict explaining which fields are interesting."""

    app_label: str
    model: str


class LocationTypeModel(NautobotModel):
    """DiffSync model for UniFi locations."""

    _model = LocationType
    _modelname = "locationtype"
    _identifiers = ("name",)
    _attributes = ("content_types",)
    _children = {}

    name: str
    content_types: List[ContentTypeDict] = []


class LocationModel(NautobotModel):
    """DiffSync model for UniFi locations."""

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

    _model = Manufacturer
    _modelname = "manufacturer"
    _identifiers = ("name",)
    _attributes = ()
    _children = {}

    name: str


class DeviceTypeModel(NautobotModel):
    """DiffSync model for UniFi device hardware."""

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
    )
    _children = {}

    name: str
    location__name: str
    serial: Optional[str] = None
    role__name: Optional[str] = None
    device_type__model: Optional[str] = None
    device_type__manufacturer__name: Optional[str] = None
    status__name: str

    system_of_record: Annotated[str, CustomFieldAnnotation(name="system_of_record")]
    ssot_last_synchronized: Annotated[str, CustomFieldAnnotation(name="ssot_last_synchronized")]


class InterfaceModel(NautobotModel):
    """DiffSync model for UniFi device interfaces."""

    _model = Interface
    _modelname = "interface"
    _identifiers = ("name",)
    _attributes = ("type", "mgmt_only")
    _children = {}

    name: str
    type: str
    mgmt_only: bool
