"""Nautobot Adapter for Unifi SSoT plugin."""

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

    def _handle_single_parameter(self, parameters, parameter_name, database_object, diffsync_model):
        """Read a Device's `mac_address` from its Interfaces, since Device has no such field."""
        if diffsync_model is DeviceModel and parameter_name == "mac_address":
            parameters[parameter_name] = get_device_mac(database_object)
            return
        super()._handle_single_parameter(parameters, parameter_name, database_object, diffsync_model)
