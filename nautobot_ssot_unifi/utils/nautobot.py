"""Utility functions for finding Nautobot objects that UniFi objects collide with."""

from collections import defaultdict

from nautobot.dcim.models import ControllerManagedDeviceGroup, Interface, Location
from nautobot.wireless.models import WirelessNetwork

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


def find_unsynced_device_group(name: str, unifi_site: str):
    """Find a controller-managed device group with a UniFi site's name that a sync from this controller does not manage.

    Args:
        name (str): The UniFi site's description, used as the group name.
        unifi_site (str): The UniFi site's short name.

    Returns:
        ControllerManagedDeviceGroup: The colliding group, or None.
    """
    synced = ControllerManagedDeviceGroup.objects.filter(
        _custom_field_data__unifi_controller=get_controller_name(), _custom_field_data__unifi_site=unifi_site
    )
    if synced.exists():
        return None
    return ControllerManagedDeviceGroup.objects.filter(name=name).first()


def find_unsynced_wireless_network(name: str):
    """Find a Wireless Network named like a UniFi WLAN that was not synced from this controller.

    Args:
        name (str): The WLAN's SSID, used as the Wireless Network name.

    Returns:
        WirelessNetwork: The colliding Wireless Network, or None.
    """
    return (
        WirelessNetwork.objects.filter(name=name)
        .exclude(
            _custom_field_data__system_of_record=SYSTEM_OF_RECORD,
            _custom_field_data__unifi_controller=get_controller_name(),
        )
        .first()
    )


def resolve_interface_name(mac: str, candidates, default: str) -> str:
    """Name of the Interface of the Device with a MAC address that matches the first candidate name it has.

    Args:
        mac (str): Lowercase MAC address identifying the Device.
        candidates (Iterable[str]): Interface names to look for, in order of preference.
        default (str): Name to use when the Device is not in Nautobot yet, or has none of the candidates.

    Returns:
        str: Interface name.
    """
    devices = find_devices_by_mac([mac]).get(mac, [])
    if len(devices) != 1:
        return default
    names = set(devices[0].interfaces.values_list("name", flat=True))
    return next((name for name in candidates if name in names), default)


def resolve_mac_interface_name(mac: str, default: str) -> str:
    """Name of the Interface holding a MAC address, such as a client's.

    Args:
        mac (str): Lowercase MAC address.
        default (str): Name to use when no Interface has the MAC yet.

    Returns:
        str: Interface name.
    """
    interface = Interface.objects.filter(mac_address=mac, device__isnull=False).order_by("name").first()
    return interface.name if interface else default


def find_interface(mac: str, interface_name: str):
    """Find the named Interface of the Device with a MAC address.

    Args:
        mac (str): Lowercase MAC address identifying the Device.
        interface_name (str): Interface name.

    Returns:
        Interface: The Interface, or None if there is not exactly one such Device or it has no such Interface.
    """
    devices = find_devices_by_mac([mac]).get(mac, [])
    if len(devices) != 1:
        return None
    return devices[0].interfaces.filter(name=interface_name).first()


def find_unsynced_cable(interface):
    """The Cable on an Interface, if a sync from this controller did not create it.

    Args:
        interface (Interface): Interface, or None.

    Returns:
        Cable: The Cable, or None if there is no Interface, it has no Cable, or the sync created it.
    """
    cable = interface.cable if interface else None
    if cable is None or (
        cable.cf.get("system_of_record") == SYSTEM_OF_RECORD
        and cable.cf.get("unifi_controller") == get_controller_name()
    ):
        return None
    return cable
