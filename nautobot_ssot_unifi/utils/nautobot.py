"""Utility functions for finding Nautobot objects that UniFi objects collide with."""

from collections import defaultdict

from nautobot.dcim.models import Interface, Location

from nautobot_ssot_unifi.constants import SYSTEM_OF_RECORD
from nautobot_ssot_unifi.utils.unifi import get_controller_name


def is_synced_device(device) -> bool:
    """Whether a Device was created or adopted by a sync from this controller.

    Args:
        device (Device): Nautobot Device.

    Returns:
        bool: True if the Device's System of Record and UniFi Controller custom fields point here.
    """
    return (
        device.cf.get("system_of_record") == SYSTEM_OF_RECORD
        and device.cf.get("unifi_controller") == get_controller_name()
    )


def find_devices_by_mac(macs) -> dict:
    """Find the Nautobot Devices with an Interface carrying each MAC address.

    Args:
        macs (Iterable[str]): MAC addresses, any case.

    Returns:
        dict: Lowercase MAC address to the list of distinct Devices with that MAC, for MACs found.
    """
    devices = defaultdict(dict)
    interfaces = Interface.objects.filter(mac_address__in=list(macs), device__isnull=False).select_related(
        "device__device_type__manufacturer", "device__location", "device__role", "device__status"
    )
    for interface in interfaces:
        devices[str(interface.mac_address).lower()][interface.device.pk] = interface.device
    return {mac: list(by_pk.values()) for mac, by_pk in devices.items()}


def find_unsynced_location(name: str, unifi_site: str):
    """Find a Location with a UniFi site's name that a sync from this controller does not manage.

    Args:
        name (str): The UniFi site's description, used as the Location name.
        unifi_site (str): The UniFi site's short name.

    Returns:
        Location: The colliding Location, or None if there is none or the sync already manages this site's Location.
    """
    synced = Location.objects.filter(
        _custom_field_data__unifi_controller=get_controller_name(), _custom_field_data__unifi_site=unifi_site
    )
    if synced.exists():
        return None
    return Location.objects.filter(name=name).first()
