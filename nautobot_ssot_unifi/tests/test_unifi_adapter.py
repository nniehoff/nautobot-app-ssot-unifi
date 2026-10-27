"""Test UniFi adapter."""

import json
from unittest.mock import MagicMock, patch

from nautobot.core.testing import TransactionTestCase
from nautobot.extras.models import JobResult

from nautobot_ssot_unifi.diffsync.adapters.unifi import UniFiAdapter
from nautobot_ssot_unifi.jobs import UniFiDataSource
from nautobot_ssot_unifi.utils.unifi import PLUGIN_CFG, get_controller_name, get_wlan_authentication


def load_json(path):
    """Load a json file."""
    with open(path, encoding="utf-8") as file:
        return json.loads(file.read())


SITE_FIXTURE = load_json("./nautobot_ssot_unifi/tests/fixtures/get_sites.json")
AP_FIXTURE = load_json("./nautobot_ssot_unifi/tests/fixtures/get_aps.json")
WLAN_FIXTURE = load_json("./nautobot_ssot_unifi/tests/fixtures/get_wlanconf.json")


class TestUniFiAdapterTestCase(TransactionTestCase):
    """Test NautobotSsotUniFiAdapter class."""

    job_class = UniFiDataSource
    databases = ("default", "job_logs")

    def setUp(self):
        """Initialize test case."""
        self.unifi_client = MagicMock()
        self.unifi_client.get_aps.return_value = AP_FIXTURE
        self.unifi_client.get_clients.return_value = []
        self.unifi_client.get_wlan_conf.return_value = WLAN_FIXTURE

        self.job = self.job_class()
        self.job.job_result = JobResult.objects.create(
            name=self.job.class_path, task_name="fake task", worker="default"
        )
        self.unifi = UniFiAdapter(job=self.job, sync=None, client=self.unifi_client)

    @patch("nautobot_ssot_unifi.diffsync.adapters.unifi.get_sites")
    def test_load_sites(self, mock_get_sites):
        """Test Nautobot SSoT UniFi load_sites() function."""
        mock_get_sites.return_value = SITE_FIXTURE
        self.unifi.load_sites()
        self.assertEqual(
            {"Site"},
            {site.get_unique_id() for site in self.unifi.get_all("locationtype")},
        )
        self.assertEqual(
            {f"default__{get_controller_name()}"},
            {site.get_unique_id() for site in self.unifi.get_all("location")},
        )
        self.assertEqual("Test", self.unifi.get_all("location")[0].name)

    @patch.dict(PLUGIN_CFG, {"sites": ["Second"]})
    @patch("nautobot_ssot_unifi.diffsync.adapters.unifi.get_sites")
    def test_load_sites_limited_to_selected(self, mock_get_sites):
        """Only sites listed in `sites`, by short name or description, are loaded."""
        mock_get_sites.return_value = SITE_FIXTURE + [{"_id": "second-site-id", "name": "nbxeaqa6", "desc": "Second"}]
        self.unifi.load_sites()
        self.assertEqual(["nbxeaqa6"], [site["name"] for site in self.unifi.sites])

    def test_load_manufacturer(self):
        """Test Nautobot SSoT UniFi load_manufacturer() function."""
        self.unifi.load_manufacturer()
        self.assertEqual({"Ubiquiti"}, {manu.get_unique_id() for manu in self.unifi.get_all("manufacturer")})

    def test_load_devicetype(self):
        """Test Nautobot SSoT UniFi load_devicetype() function."""
        self.unifi.load_devicetype(model="Test")
        self.assertEqual({"Test__Ubiquiti"}, {dt.get_unique_id() for dt in self.unifi.get_all("devicetype")})

    def test_load_unifi_devices(self):
        """UniFi network devices are loaded as Devices keyed by MAC address."""
        self.unifi.load_devices(self.unifi.get_unifi_devices(SITE_FIXTURE[0]))
        self.assertEqual(
            {dev["mac"] for dev in AP_FIXTURE}, {dev.get_unique_id() for dev in self.unifi.get_all("device")}
        )
        self.assertEqual({dev["name"] for dev in AP_FIXTURE}, {dev.name for dev in self.unifi.get_all("device")})

    @patch.dict(PLUGIN_CFG, {"import_wireless_clients": False})
    def test_get_clients_filters(self):
        """Wireless clients and unnamed clients with randomized MACs are skipped; names fall back to hostname."""
        self.unifi_client.get_clients.return_value = [
            {"mac": "00:11:22:33:44:01", "is_wired": True, "hostname": "nas", "oui": "Synology"},
            {"mac": "00:11:22:33:44:02", "is_wired": False, "hostname": "phone"},
            {"mac": "fe:11:22:33:44:03", "is_wired": True, "hostname": "laptop"},
            {"mac": "fe:11:22:33:44:04", "is_wired": True, "hostname": "kvm", "name": "Rack KVM"},
        ]
        records = self.unifi.get_clients(SITE_FIXTURE[0])
        self.assertEqual(
            [("00:11:22:33:44:01", "nas"), ("fe:11:22:33:44:04", "Rack KVM")],
            [(record["mac"], record["name"]) for record in records],
        )

    @patch.dict(PLUGIN_CFG, {"import_clients": False})
    def test_get_clients_disabled(self):
        """No clients are read when `import_clients` is off."""
        self.assertEqual([], self.unifi.get_clients(SITE_FIXTURE[0]))
        self.unifi_client.get_clients.assert_not_called()

    def test_load_devices_duplicate_names(self):
        """Devices sharing a name within a Location get their MAC appended."""
        self.unifi_client.get_clients.return_value = [
            {"mac": "00:11:22:33:44:01", "is_wired": True, "hostname": "glkvm"},
            {"mac": "00:11:22:33:44:02", "is_wired": True, "hostname": "glkvm"},
            {"mac": "00:11:22:33:44:03", "is_wired": True, "hostname": "nas"},
        ]
        self.unifi.load_devices(self.unifi.get_clients(SITE_FIXTURE[0]))
        self.assertEqual(
            {"glkvm (00:11:22:33:44:01)", "glkvm (00:11:22:33:44:02)", "nas"},
            {dev.name for dev in self.unifi.get_all("device")},
        )

    @patch("nautobot_ssot_unifi.diffsync.adapters.unifi.get_sites")
    def test_load_reads_every_site(self, mock_get_sites):
        """load() switches the client to each site's short name before reading its devices and clients."""
        mock_get_sites.return_value = SITE_FIXTURE + [{"_id": "second-site-id", "name": "nbxeaqa6", "desc": "Second"}]
        seen_sites = []
        self.unifi_client.get_aps.side_effect = lambda: seen_sites.append(self.unifi_client.site_id) or AP_FIXTURE
        self.unifi.load()
        self.assertEqual(["default", "nbxeaqa6"], seen_sites)
        self.assertEqual(2, self.unifi_client.get_clients.call_count)

    @patch.dict(PLUGIN_CFG, {"exclude_client_uplinks": ["WAN Switch"], "exclude_client_networks": ["guest"]})
    def test_client_skip_reason_exclude(self):
        """Clients behind an excluded uplink (by name) or on an excluded network (any case) are skipped."""
        self.unifi.uplink_names = {"8c:ed:e1:b0:19:f5": "WAN Switch", "f4:e2:c6:bf:5c:fd": "Office Switch"}
        self.assertIn(
            "exclude_client_uplinks",
            self.unifi.client_skip_reason(
                {"mac": "00:11:22:33:44:01", "is_wired": True, "sw_mac": "8C:ED:E1:B0:19:F5"}
            ),
        )
        self.assertIn(
            "exclude_client_networks",
            self.unifi.client_skip_reason({"mac": "00:11:22:33:44:02", "is_wired": True, "network": "Guest"}),
        )
        self.assertIsNone(
            self.unifi.client_skip_reason({"mac": "00:11:22:33:44:03", "is_wired": True, "sw_mac": "f4:e2:c6:bf:5c:fd"})
        )

    @patch.dict(PLUGIN_CFG, {"include_client_uplinks": ["f4:e2:c6:bf:5c:fd"]})
    def test_client_skip_reason_include(self):
        """With `include_client_uplinks` set, only clients behind a listed uplink (by MAC) are synced."""
        self.unifi.uplink_names = {"f4:e2:c6:bf:5c:fd": "Office Switch"}
        self.assertIsNone(
            self.unifi.client_skip_reason({"mac": "00:11:22:33:44:01", "is_wired": True, "sw_mac": "f4:e2:c6:bf:5c:fd"})
        )
        self.assertIn(
            "not in include_client_uplinks",
            self.unifi.client_skip_reason(
                {"mac": "00:11:22:33:44:02", "is_wired": False, "ap_mac": "60:22:32:fd:ac:92"}
            ),
        )

    def test_keep_nautobot_fields_and_prune(self):
        """Devices already in Nautobot keep its Role, Device Type, Status, and serial; unused shared objects are dropped."""
        self.unifi_client.get_clients.return_value = [{"mac": "00:11:22:33:44:01", "is_wired": True, "hostname": "nas"}]
        self.unifi.load_devices(self.unifi.get_clients(SITE_FIXTURE[0]))
        target = UniFiAdapter(job=self.job, sync=None, client=MagicMock())
        target.add(
            target.device(
                mac_address="00:11:22:33:44:01",
                name="nas",
                location__name="Test",
                serial="SN123",
                role__name="Storage",
                device_type__model="DS920+",
                device_type__manufacturer__name="Synology",
                status__name="Planned",
            )
        )
        self.unifi.keep_nautobot_fields(target)
        self.unifi.prune_unused()
        device = self.unifi.get("device", "00:11:22:33:44:01")
        self.assertEqual(
            ("Storage", "DS920+", "Synology", "Planned", "SN123"),
            (
                device.role__name,
                device.device_type__model,
                device.device_type__manufacturer__name,
                device.status__name,
                device.serial,
            ),
        )
        self.assertEqual([], self.unifi.get_all("role"))
        self.assertEqual([], self.unifi.get_all("devicetype"))
        self.assertEqual([], self.unifi.get_all("manufacturer"))

    @patch("nautobot_ssot_unifi.diffsync.adapters.unifi.get_sites")
    def test_load_wireless_and_software(self, mock_get_sites):
        """The controller, a group per site, WLANs, and device Platforms and Software Versions are loaded."""
        mock_get_sites.return_value = SITE_FIXTURE
        self.unifi.load()
        controller = self.unifi.get("controller", get_controller_name())
        self.assertEqual(("Test", ["wireless"]), (controller.location__name, controller.capabilities))
        group = self.unifi.get_all("devicegroup")[0]
        self.assertEqual(
            ("default", "Test", get_controller_name()), (group.unifi_site, group.name, group.controller__name)
        )
        self.assertEqual(
            {("Home", "WPA3 Personal", True, False), ("Guest", "WPA2 Personal", False, True)},
            {
                (wlan.ssid, wlan.authentication, wlan.enabled, wlan.hidden)
                for wlan in self.unifi.get_all("wirelessnetwork")
            },
        )
        self.assertEqual(
            {("Test", "Home"), ("Test", "Guest")},
            {
                (assignment.controller_managed_device_group__name, assignment.wireless_network__name)
                for assignment in self.unifi.get_all("wirelessnetworkassignment")
            },
        )
        device = self.unifi.get("device", AP_FIXTURE[0]["mac"])
        self.assertEqual(
            ("UniFi Gateway", "UniFi Gateway", "4.4.57.5578372", "Test"),
            (
                device.platform__name,
                device.software_version__platform__name,
                device.software_version__version,
                device.controller_managed_device_group__name,
            ),
        )
        self.assertEqual(
            {"UniFi Gateway__4.4.57.5578372"},
            {version.get_unique_id() for version in self.unifi.get_all("softwareversion")},
        )
        self.assertEqual(
            [{"app_label": "dcim", "model": "device"}, {"app_label": "dcim", "model": "controller"}],
            self.unifi.get("locationtype", "Site").content_types,
        )

    @patch.dict(PLUGIN_CFG, {"import_wireless": False})
    @patch("nautobot_ssot_unifi.diffsync.adapters.unifi.get_sites")
    def test_load_without_wireless(self, mock_get_sites):
        """With `import_wireless` off, no controller, groups, or WLANs are read or loaded."""
        mock_get_sites.return_value = SITE_FIXTURE
        self.unifi.load()
        self.unifi_client.get_wlan_conf.assert_not_called()
        for model in ("controller", "devicegroup", "wirelessnetwork", "wirelessnetworkassignment"):
            self.assertEqual([], self.unifi.get_all(model))
        self.assertIsNone(self.unifi.get("device", AP_FIXTURE[0]["mac"]).controller_managed_device_group__name)

    def test_get_wlan_authentication(self):
        """UniFi security settings map to Nautobot authentication; transition mode maps to WPA2."""
        for wlan, expected in (
            ({"security": "open"}, "Open"),
            ({"security": "wpapsk"}, "WPA2 Personal"),
            ({"security": "wpapsk", "wpa3_support": True, "wpa3_transition": True}, "WPA2 Personal"),
            ({"security": "wpapsk", "wpa3_support": True}, "WPA3 Personal"),
            ({"security": "wpaeap"}, "WPA2 Enterprise"),
            ({"security": "wpaeap", "wpa3_support": True}, "WPA3 Enterprise"),
            ({"security": "wpaeap", "wpa3_support": True, "wpa3_enhanced_192": True}, "WPA3 Enterprise 192Bit"),
            ({"security": "wep"}, None),
        ):
            self.assertEqual(expected, get_wlan_authentication(wlan), wlan)

    def test_keep_nautobot_fields_platform_and_content_types(self):
        """Devices keep Nautobot's Platform; content types only grow; unused Platforms and versions are dropped."""
        self.unifi.load_location_type("Site")
        self.unifi.load_devices(self.unifi.get_unifi_devices(SITE_FIXTURE[0]))
        target = UniFiAdapter(job=self.job, sync=None, client=MagicMock())
        target.add(target.locationtype(name="Site", content_types=[{"app_label": "dcim", "model": "rack"}]))
        target.add(
            target.device(
                mac_address=AP_FIXTURE[0]["mac"],
                name="usg",
                location__name="Test",
                role__name="Router",
                device_type__model="UGW3",
                device_type__manufacturer__name="Ubiquiti",
                status__name="Active",
                platform__name="vyos",
            )
        )
        self.unifi.keep_nautobot_fields(target)
        self.unifi.prune_unused()
        device = self.unifi.get("device", AP_FIXTURE[0]["mac"])
        self.assertEqual(("vyos", "UniFi Gateway"), (device.platform__name, device.software_version__platform__name))
        self.assertEqual({"UniFi Gateway"}, {platform.name for platform in self.unifi.get_all("platform")})
        self.assertEqual(
            {("dcim", "controller"), ("dcim", "device"), ("dcim", "rack")},
            {(ct["app_label"], ct["model"]) for ct in self.unifi.get("locationtype", "Site").content_types},
        )

    def test_load_cables(self):
        """Wired devices and clients get a Cable to their switch port; shared ports and wireless clients do not."""
        switch = {
            "mac": "F4:E2:C6:BF:5C:FD",
            "name": "officesw1",
            "model": "US8P150",
            "type": "usw",
            "serial": "",
            "port_table": [
                {"port_idx": 1, "name": "Printer"},
                {"port_idx": 3, "name": "Port 3"},
                {"port_idx": 8, "name": "Port 8"},
            ],
            "uplink": {"type": "wire", "uplink_mac": "00:00:00:00:00:99", "uplink_remote_port": 1},
        }
        access_point = {
            "mac": "60:22:32:fd:ae:68",
            "name": "Office",
            "model": "U6ENT",
            "type": "uap",
            "serial": "",
            "uplink": {
                "type": "wire",
                "name": "eth0",
                "port_idx": 1,
                "uplink_mac": "f4:e2:c6:bf:5c:fd",
                "uplink_remote_port": 8,
            },
        }
        self.unifi_client.get_aps.return_value = [switch, access_point]
        self.unifi_client.get_clients.return_value = [
            {
                "mac": "00:11:22:33:44:01",
                "is_wired": True,
                "hostname": "printer",
                "sw_mac": "f4:e2:c6:bf:5c:fd",
                "sw_port": 1,
            },
            {
                "mac": "00:11:22:33:44:02",
                "is_wired": True,
                "hostname": "vm1",
                "sw_mac": "f4:e2:c6:bf:5c:fd",
                "sw_port": 3,
            },
            {
                "mac": "00:11:22:33:44:03",
                "is_wired": True,
                "hostname": "vm2",
                "sw_mac": "f4:e2:c6:bf:5c:fd",
                "sw_port": 3,
            },
            {
                "mac": "00:11:22:33:44:04",
                "is_wired": True,
                "hostname": "behind-ap",
                "sw_mac": "f4:e2:c6:bf:5c:fd",
                "sw_port": 8,
            },
            {"mac": "00:11:22:33:44:05", "is_wired": False, "hostname": "phone", "ap_mac": "60:22:32:fd:ae:68"},
        ]
        site = SITE_FIXTURE[0]
        records = self.unifi.get_unifi_devices(site) + self.unifi.get_clients(site)
        self.unifi.load_devices(records)
        self.unifi.load_cables()
        self.assertEqual(
            {
                ("60:22:32:fd:ae:68", "eth0", "f4:e2:c6:bf:5c:fd", "Port 8"),
                ("00:11:22:33:44:01", "eth0", "f4:e2:c6:bf:5c:fd", "Port 1"),
            },
            {
                (cable.mac_address, cable.interface, cable.upstream_mac_address, cable.upstream_interface)
                for cable in self.unifi.get_all("cable")
            },
        )
        # A device left out of the sync, e.g. skipped as an existing Device, takes its Cable with it.
        self.unifi.remove(self.unifi.get("device", "00:11:22:33:44:01"))
        self.unifi.prune_unused()
        self.assertEqual(["60:22:32:fd:ae:68"], [cable.mac_address for cable in self.unifi.get_all("cable")])

    @patch.dict(PLUGIN_CFG, {"import_cables": False})
    def test_load_cables_disabled(self):
        """No Cables are loaded when `import_cables` is off."""
        self.unifi.links = [{"mac": "a", "interface": None, "upstream_mac": "b", "upstream_port": 1}]
        self.unifi.load_cables()
        self.assertEqual([], self.unifi.get_all("cable"))
