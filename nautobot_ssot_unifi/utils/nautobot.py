"""Utility functions for finding Nautobot objects that UniFi objects collide with."""

from collections import defaultdict
from typing import Optional

from django.db.models import Q
from nautobot.dcim.models import ControllerManagedDeviceGroup, Interface, Location
from nautobot.ipam.models import VLAN, IPAddress, IPAddressToInterface, Prefix, VLANGroup
from nautobot.wireless.models import WirelessNetwork

from nautobot_ssot_unifi.constants import SYSTEM_OF_RECORD
from nautobot_ssot_unifi.utils.unifi import get_controller_name, get_namespace


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


def find_unsynced_ip_address(host: str):
    """Find an IP Address in the sync's Namespace that was not synced from this controller.

    Args:
        host (str): IP address without mask, e.g. "192.168.1.10".

    Returns:
        IPAddress: The existing IP Address, or None.
    """
    return (
        IPAddress.objects.filter(host=host, parent__namespace__name=get_namespace())
        .exclude(
            _custom_field_data__system_of_record=SYSTEM_OF_RECORD,
            _custom_field_data__unifi_controller=get_controller_name(),
        )
        .first()
    )


def find_prefix_length(host: str) -> Optional[int]:
    """Length of the narrowest Prefix in the sync's Namespace containing an IP address.

    Args:
        host (str): IP address without mask.

    Returns:
        Optional[int]: Prefix length, or None if no Prefix contains the address.
    """
    prefix = (
        Prefix.objects.filter(namespace__name=get_namespace())
        .net_contains_or_equals(host)
        .order_by("-prefix_length")
        .first()
    )
    return prefix.prefix_length if prefix else None


def resolve_ip_interface_name(mac: str, host: str, default: str) -> str:
    """Name of the Interface an IP address of the Device with a MAC address belongs on.

    In order: the Interface of that Device the IP Address is already assigned to, so addresses set up by hand stay
    where they are; the Interface holding the MAC address; then `default`.

    Args:
        mac (str): Lowercase MAC address identifying the Device.
        host (str): IP address without mask.
        default (str): Name to use when the Device is not in Nautobot yet, or has neither Interface.

    Returns:
        str: Interface name.
    """
    devices = find_devices_by_mac([mac]).get(mac, [])
    if len(devices) != 1:
        return default
    assignment = (
        IPAddressToInterface.objects.filter(
            interface__device=devices[0],
            ip_address__host=host,
            ip_address__parent__namespace__name=get_namespace(),
        )
        .order_by("interface__name")
        .first()
    )
    if assignment:
        return assignment.interface.name
    interface = devices[0].interfaces.filter(mac_address=mac).order_by("name").first()
    return interface.name if interface else default


def find_unsynced_vlan_group(name: str, unifi_site: str):
    """Find a VLAN Group with a UniFi site's name that a sync from this controller does not manage.

    Args:
        name (str): The UniFi site's description, used as the VLAN Group name.
        unifi_site (str): The UniFi site's short name.

    Returns:
        VLANGroup: The colliding VLAN Group, or None.
    """
    synced = VLANGroup.objects.filter(
        _custom_field_data__unifi_controller=get_controller_name(), _custom_field_data__unifi_site=unifi_site
    )
    if synced.exists():
        return None
    return VLANGroup.objects.filter(name=name).first()


def available_vlans(vid: int, location):
    """VLANs with an ID that Interfaces of Devices in a Location can use.

    Those are VLANs that are global or in the Location or one of its parents, in no VLAN Group or in one that is
    global or in the Location or one of its parents.

    Args:
        vid (int): VLAN ID.
        location (Location): The Devices' Location, or None.

    Returns:
        QuerySet: Matching VLANs.
    """
    location_ids = list(location.ancestors(include_self=True).values_list("pk", flat=True)) if location else []
    return (
        VLAN.objects.filter(vid=vid)
        .filter(Q(locations__isnull=True) | Q(locations__in=location_ids))
        .filter(
            Q(vlan_group__isnull=True) | Q(vlan_group__location__isnull=True) | Q(vlan_group__location__in=location_ids)
        )
        .distinct()
    )


def find_vlan(vid: int, location):
    """The VLAN an Interface of a Device in a Location should use for a VLAN ID.

    VLANs in a VLAN Group synced from this controller come first, then VLANs in a Location, then global ones.

    Args:
        vid (int): VLAN ID.
        location (Location): The Device's Location, or None.

    Returns:
        VLAN: The VLAN, or None if there is none.
    """
    vlans = available_vlans(vid, location)
    synced = vlans.filter(vlan_group___custom_field_data__unifi_controller=get_controller_name()).first()
    if synced:
        return synced
    candidates = sorted(vlans, key=lambda vlan: (not vlan.locations.exists(), vlan.vlan_group_id is None, str(vlan.pk)))
    return candidates[0] if candidates else None


def find_unsynced_vlan(vid: int, location_name: str):
    """Find a VLAN that Devices in a Location can use and that is not in a VLAN Group synced from this controller.

    Args:
        vid (int): VLAN ID.
        location_name (str): Name of the UniFi site's Location.

    Returns:
        VLAN: The existing VLAN, or None.
    """
    location = Location.objects.filter(name=location_name).first()
    return (
        available_vlans(vid, location)
        .exclude(vlan_group___custom_field_data__unifi_controller=get_controller_name())
        .first()
    )
