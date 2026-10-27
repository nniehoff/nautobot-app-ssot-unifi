"""Utility functions for working with UniFi."""

from collections import Counter
from typing import Optional

from django.conf import settings
from pyunifi.controller import Controller

from nautobot_ssot_unifi.constants import (
    DEFAULT_NAMESPACE,
    DEFAULT_PLATFORM,
    DEFAULT_VLAN_ID,
    PLATFORM_MAP,
    PORT_MEDIA_PREFIXES,
    VLAN_NETWORK_PURPOSES,
)

PLUGIN_CFG = settings.PLUGINS_CONFIG["nautobot_ssot_unifi"]


def connect_controller():
    """Generate connection to UniFi controller API endpoint.

    Returns:
        Controller: Connection to UniFi Controller.
    """
    return Controller(
        host=PLUGIN_CFG["unifi_host"],
        username=PLUGIN_CFG["unifi_user"],
        password=PLUGIN_CFG["unifi_password"],
        port=PLUGIN_CFG["unifi_port"],
        version=PLUGIN_CFG.get("unifi_version", "v5"),
        ssl_verify=PLUGIN_CFG["verify"],
    )


def get_controller_name() -> str:
    """Name of the configured UniFi controller, stored on every Device synced from it.

    Defaults to `unifi_host`. Set `controller_name` to keep the same name when the
    controller moves to a new address, so its Devices are not orphaned.

    Returns:
        str: Controller name.
    """
    return PLUGIN_CFG.get("controller_name") or PLUGIN_CFG["unifi_host"]


def get_namespace() -> str:
    """Namespace of the Prefixes and IP Addresses the sync creates and matches (`namespace`, default "Global").

    Returns:
        str: Namespace name.
    """
    return PLUGIN_CFG.get("namespace") or DEFAULT_NAMESPACE


def get_networks(conn: Controller) -> list:
    """Read the networks of the site the client is pointed at.

    pyunifi has no method for networks, so this reads the legacy `rest/networkconf` endpoint directly.

    Args:
        conn (Controller): Connection to UniFi controller.

    Returns:
        list: Networks, each with an `ip_subnet` such as "192.168.1.1/24" (gateway address and length) if it has one.
    """
    return conn._api_read("rest/networkconf")  # pylint: disable=protected-access


def get_port_profiles(conn: Controller) -> dict:
    """Read the port profiles of the site the client is pointed at.

    Args:
        conn (Controller): Connection to UniFi controller.

    Returns:
        dict: Port profiles from the legacy `rest/portconf` endpoint, by ID.
    """
    profiles = conn._api_read("rest/portconf")  # pylint: disable=protected-access
    return {profile.get("_id") or profile.get("id"): profile for profile in profiles}


def get_network_vlans(networks: list) -> dict:
    """VLAN ID of each UniFi network that can be on a switch port.

    Args:
        networks (list): Networks from `get_networks()`.

    Returns:
        dict: Network ID to VLAN ID; the network without a VLAN, the default one, is VLAN 1.
    """
    vlans = {}
    for network in networks:
        if network.get("purpose") not in VLAN_NETWORK_PURPOSES:
            continue
        vlan = network.get("vlan") if network.get("vlan_enabled") else None
        vlans[network.get("_id") or network.get("id")] = int(vlan) if vlan else DEFAULT_VLAN_ID
    return vlans


def get_default_port_names(port_table: list) -> dict:
    """Name UniFi gives each switch port until it is renamed: "SFP+ 2" for fiber ports, else "Port <n>".

    Args:
        port_table (list): A device's `port_table`.

    Returns:
        dict: Port number to default name.
    """
    counts = Counter()
    names = {}
    for port in sorted(port_table, key=lambda port: port["port_idx"]):
        media = port.get("media")
        if media in PORT_MEDIA_PREFIXES:
            counts[media] += 1
            names[port["port_idx"]] = f"{media} {counts[media]}"
        else:
            names[port["port_idx"]] = f"Port {port['port_idx']}"
    return names


def get_port_switching(port: dict, profiles: dict, network_vlans: dict) -> Optional[tuple]:
    """802.1Q mode and VLANs of a switch port, from its port profile if it has one, else its own settings.

    Ports block, allow all, or allow all but some tagged VLANs (`tagged_vlan_mgmt`); older controllers set
    `forward` to "native", "all", or "customize" with a list of tagged networks instead. The port's native
    network is its untagged VLAN.

    Args:
        port (dict): Port from a device's `port_table`.
        profiles (dict): Port profiles from `get_port_profiles()`.
        network_vlans (dict): Network ID to VLAN ID, from `get_network_vlans()`.

    Returns:
        Optional[tuple]: (mode, untagged VLAN ID or None, sorted tagged VLAN IDs); mode is None for a disabled
            port. None when the settings are not understood.
    """
    config = profiles.get(port.get("portconf_id")) or port
    management, forward = config.get("tagged_vlan_mgmt"), config.get("forward")
    if forward == "disabled":
        return (None, None, [])
    untagged = network_vlans.get(config.get("native_networkconf_id"))
    if management == "block_all" or (management is None and forward == "native"):
        return ("access", untagged, [])
    if management == "auto" or (management is None and forward == "all"):
        return ("tagged-all", untagged, [])
    if management == "custom":
        excluded = set(config.get("excluded_networkconf_ids") or [])
        tagged = {vlan for network_id, vlan in network_vlans.items() if network_id not in excluded}
    elif management is None and forward == "customize":
        tagged = {network_vlans[i] for i in config.get("tagged_networkconf_ids") or [] if i in network_vlans}
    else:
        return None
    tagged.discard(untagged)
    return ("tagged", untagged, sorted(tagged))


def get_sites(conn: Controller) -> dict:
    """Gather location information from UniFi.

    Args:
        conn (Controller): Connection to UniFi controller.

    Returns:
        dict: List of Site locations from UniFi controller.
    """
    return conn._read(url=conn.url + "api/self/sites")  # pylint: disable=protected-access


def get_selected_sites() -> list:
    """Sites the sync is limited to, by short name or description. Empty means every site.

    Returns:
        list: Configured site short names (e.g. "default") or descriptions (e.g. "Default").
    """
    return PLUGIN_CFG.get("sites") or []


def is_site_selected(site: dict) -> bool:
    """Whether a UniFi site is part of the sync.

    Args:
        site (dict): Site from the UniFi `api/self/sites` endpoint.

    Returns:
        bool: True if no sites are configured or the site's short name or description is listed.
    """
    selected = get_selected_sites()
    return not selected or site["name"] in selected or site["desc"] in selected


def is_random_mac(mac: str) -> bool:
    """Whether a MAC address is locally administered, as the private addresses phones and laptops rotate are.

    Args:
        mac (str): MAC address such as "fe:38:d1:f6:34:8e".

    Returns:
        bool: True if the locally administered bit of the first octet is set.
    """
    return bool(int(mac.split(":")[0], 16) & 0x02)


def get_platform(device: dict) -> str:
    """Platform of a UniFi network device, one per kind of device since UniFi releases firmware per kind.

    Args:
        device (dict): Device from the UniFi `stat/device` endpoint.

    Returns:
        str: Platform name, e.g. "UniFi Switch".
    """
    return PLATFORM_MAP.get(device.get("type"), DEFAULT_PLATFORM)


def get_wlan_authentication(wlan: dict) -> Optional[str]:
    """Nautobot Wireless Network authentication matching a UniFi WLAN's security settings.

    WPA2/WPA3 transition mode maps to the WPA2 variant, the weakest security clients may use.

    Args:
        wlan (dict): WLAN from the UniFi `list/wlanconf` endpoint.

    Returns:
        Optional[str]: Authentication choice, or None for security Nautobot has no choice for, such as WEP.
    """
    wpa3_only = wlan.get("wpa3_support") and not wlan.get("wpa3_transition")
    security = wlan.get("security")
    if security == "open":
        return "Open"
    if security == "wpapsk":
        return "WPA3 Personal" if wpa3_only else "WPA2 Personal"
    if security == "wpaeap":
        if wlan.get("wpa3_enhanced_192"):
            return "WPA3 Enterprise 192Bit"
        return "WPA3 Enterprise" if wpa3_only else "WPA2 Enterprise"
    return None
