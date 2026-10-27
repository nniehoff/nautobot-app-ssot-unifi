"""DiffSync models for Nautobot SSoT UniFi."""

from nautobot_ssot_unifi.diffsync.models.base import (
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
)


class UniFiLocationTypeModel(LocationTypeModel):
    """UniFi implementation of LocationType DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create LocationType in UniFi from UniFiLocationTypeModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update LocationType in UniFi from UniFiLocationTypeModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete LocationType in UniFi from UniFiLocationTypeModel object."""
        return self


class UniFiLocationModel(LocationModel):
    """UniFi implementation of Location DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create Location in UniFi from UniFiLocationModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update Location in UniFi from UniFiLocationModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete Location in UniFi from UniFiLocationModel object."""
        return self


class UniFiManufacturerModel(ManufacturerModel):
    """UniFi implementation of Manufacturer DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create Manufacturer in UniFi from UniFiManufacturerModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update Manufacturer in UniFi from UniFiManufacturerModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete Manufacturer in UniFi from UniFiManufacturerModel object."""
        return self


class UniFiDeviceTypeModel(DeviceTypeModel):
    """UniFi implementation of DeviceType DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create DeviceType in UniFi from UniFiDeviceTypeModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update DeviceType in UniFi from UniFiDeviceTypeModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete DeviceType in UniFi from UniFiDeviceTypeModel object."""
        return self


class UniFiRoleModel(RoleModel):
    """UniFi implementation of Role DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create Role in UniFi from UniFiRoleModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update Role in UniFi from UniFiRoleModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete Role in UniFi from UniFiRoleModel object."""
        return self


class UniFiDeviceModel(DeviceModel):
    """UniFi implementation of Device DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create Device in UniFi from UniFiDevice object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update Device in UniFi from UniFiDevice object."""
        return super().update(attrs)

    def delete(self):
        """Delete Device in UniFi from UniFiDevice object."""
        return self


class UniFiPlatformModel(PlatformModel):
    """UniFi implementation of Platform DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create Platform in UniFi from UniFiPlatformModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update Platform in UniFi from UniFiPlatformModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete Platform in UniFi from UniFiPlatformModel object."""
        return self


class UniFiSoftwareVersionModel(SoftwareVersionModel):
    """UniFi implementation of SoftwareVersion DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create SoftwareVersion in UniFi from UniFiSoftwareVersionModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update SoftwareVersion in UniFi from UniFiSoftwareVersionModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete SoftwareVersion in UniFi from UniFiSoftwareVersionModel object."""
        return self


class UniFiControllerModel(ControllerModel):
    """UniFi implementation of Controller DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create Controller in UniFi from UniFiControllerModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update Controller in UniFi from UniFiControllerModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete Controller in UniFi from UniFiControllerModel object."""
        return self


class UniFiControllerManagedDeviceGroupModel(ControllerManagedDeviceGroupModel):
    """UniFi implementation of ControllerManagedDeviceGroup DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create ControllerManagedDeviceGroup in UniFi from UniFiControllerManagedDeviceGroupModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update ControllerManagedDeviceGroup in UniFi from UniFiControllerManagedDeviceGroupModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete ControllerManagedDeviceGroup in UniFi from UniFiControllerManagedDeviceGroupModel object."""
        return self


class UniFiWirelessNetworkModel(WirelessNetworkModel):
    """UniFi implementation of WirelessNetwork DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create WirelessNetwork in UniFi from UniFiWirelessNetworkModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update WirelessNetwork in UniFi from UniFiWirelessNetworkModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete WirelessNetwork in UniFi from UniFiWirelessNetworkModel object."""
        return self


class UniFiWirelessNetworkAssignmentModel(WirelessNetworkAssignmentModel):
    """UniFi implementation of WirelessNetwork assignment DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create WirelessNetwork assignment in UniFi from UniFiWirelessNetworkAssignmentModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update WirelessNetwork assignment in UniFi from UniFiWirelessNetworkAssignmentModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete WirelessNetwork assignment in UniFi from UniFiWirelessNetworkAssignmentModel object."""
        return self


class UniFiCableModel(CableModel):
    """UniFi implementation of Cable DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create Cable in UniFi from UniFiCableModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update Cable in UniFi from UniFiCableModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete Cable in UniFi from UniFiCableModel object."""
        return self


class UniFiPrefixModel(PrefixModel):
    """UniFi implementation of Prefix DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create Prefix in UniFi from UniFiPrefixModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update Prefix in UniFi from UniFiPrefixModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete Prefix in UniFi from UniFiPrefixModel object."""
        return self


class UniFiIPAddressModel(IPAddressModel):
    """UniFi implementation of IPAddress DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create IPAddress in UniFi from UniFiIPAddressModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update IPAddress in UniFi from UniFiIPAddressModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete IPAddress in UniFi from UniFiIPAddressModel object."""
        return self


class UniFiIPAddressAssignmentModel(IPAddressAssignmentModel):
    """UniFi implementation of IPAddress assignment DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create IPAddress assignment in UniFi from UniFiIPAddressAssignmentModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update IPAddress assignment in UniFi from UniFiIPAddressAssignmentModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete IPAddress assignment in UniFi from UniFiIPAddressAssignmentModel object."""
        return self


class UniFiVLANGroupModel(VLANGroupModel):
    """UniFi implementation of VLANGroup DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create VLANGroup in UniFi from UniFiVLANGroupModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update VLANGroup in UniFi from UniFiVLANGroupModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete VLANGroup in UniFi from UniFiVLANGroupModel object."""
        return self


class UniFiVLANModel(VLANModel):
    """UniFi implementation of VLAN DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create VLAN in UniFi from UniFiVLANModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update VLAN in UniFi from UniFiVLANModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete VLAN in UniFi from UniFiVLANModel object."""
        return self


class UniFiInterfaceModel(InterfaceModel):
    """UniFi implementation of Interface DiffSync model."""

    @classmethod
    def create(cls, adapter, ids, attrs):
        """Create Interface in UniFi from UniFiInterfaceModel object."""
        return super().create(adapter=adapter, ids=ids, attrs=attrs)

    def update(self, attrs):
        """Update Interface in UniFi from UniFiInterfaceModel object."""
        return super().update(attrs)

    def delete(self):
        """Delete Interface in UniFi from UniFiInterfaceModel object."""
        return self
