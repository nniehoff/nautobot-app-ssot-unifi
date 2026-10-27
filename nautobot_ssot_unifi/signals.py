"""Signals triggered when Nautobot starts to perform certain actions."""

from nautobot.extras.choices import CustomFieldTypeChoices


def nautobot_database_ready_callback(sender, *, apps, **kwargs):  # pylint: disable=unused-argument
    """Add the CustomFields this app syncs.

    System of Record, Last Sync'd, and UniFi Controller go on every model the sync creates or adopts: Cable,
    Controller, ControllerManagedDeviceGroup, Device, Interface, IPAddress, Location, Prefix, VLAN, VLANGroup, and
    WirelessNetwork. UniFi Site goes on Location, ControllerManagedDeviceGroup, and VLANGroup.

    Callback function triggered by the nautobot_database_ready signal when the Nautobot database is fully ready.
    """
    # pylint: disable=invalid-name, too-many-locals
    ContentType = apps.get_model("contenttypes", "ContentType")
    CustomField = apps.get_model("extras", "CustomField")
    Cable = apps.get_model("dcim", "Cable")
    Controller = apps.get_model("dcim", "Controller")
    ControllerManagedDeviceGroup = apps.get_model("dcim", "ControllerManagedDeviceGroup")
    Device = apps.get_model("dcim", "Device")
    Location = apps.get_model("dcim", "Location")
    Interface = apps.get_model("dcim", "Interface")
    IPAddress = apps.get_model("ipam", "IPAddress")
    Prefix = apps.get_model("ipam", "Prefix")
    VLAN = apps.get_model("ipam", "VLAN")
    VLANGroup = apps.get_model("ipam", "VLANGroup")
    WirelessNetwork = apps.get_model("wireless", "WirelessNetwork")

    sor_cf_dict = {
        "type": CustomFieldTypeChoices.TYPE_TEXT,
        "key": "system_of_record",
        "label": "System of Record",
    }
    sor_custom_field, _ = CustomField.objects.update_or_create(key=sor_cf_dict["key"], defaults=sor_cf_dict)
    sync_cf_dict = {
        "type": CustomFieldTypeChoices.TYPE_DATE,
        "key": "ssot_last_synchronized",
        "label": "Last sync from System of Record",
    }
    sync_custom_field, _ = CustomField.objects.update_or_create(key=sync_cf_dict["key"], defaults=sync_cf_dict)
    synced_models = [
        Cable,
        Controller,
        ControllerManagedDeviceGroup,
        Device,
        Interface,
        IPAddress,
        Location,
        Prefix,
        VLAN,
        VLANGroup,
        WirelessNetwork,
    ]
    for model in synced_models:
        sor_custom_field.content_types.add(ContentType.objects.get_for_model(model))
        sync_custom_field.content_types.add(ContentType.objects.get_for_model(model))
    controller_cf_dict = {
        "type": CustomFieldTypeChoices.TYPE_TEXT,
        "key": "unifi_controller",
        "label": "UniFi Controller",
    }
    controller_custom_field, _ = CustomField.objects.update_or_create(
        key=controller_cf_dict["key"], defaults=controller_cf_dict
    )
    for model in synced_models:
        controller_custom_field.content_types.add(ContentType.objects.get_for_model(model))
    site_cf_dict = {
        "type": CustomFieldTypeChoices.TYPE_TEXT,
        "key": "unifi_site",
        "label": "UniFi Site",
    }
    site_custom_field, _ = CustomField.objects.update_or_create(key=site_cf_dict["key"], defaults=site_cf_dict)
    for model in [Location, ControllerManagedDeviceGroup, VLANGroup]:
        site_custom_field.content_types.add(ContentType.objects.get_for_model(model))
