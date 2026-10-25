"""Nautobot Adapter for Unifi SSoT plugin."""

from nautobot_ssot.contrib import NautobotAdapter

from nautobot_ssot_unifi.diffsync.models.base import (
    DeviceModel,
    DeviceTypeModel,
    LocationModel,
    LocationTypeModel,
    ManufacturerModel,
    RoleModel,
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
