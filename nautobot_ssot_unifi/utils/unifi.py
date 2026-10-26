"""Utility functions for working with UniFi."""

from django.conf import settings
from pyunifi.controller import Controller

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
