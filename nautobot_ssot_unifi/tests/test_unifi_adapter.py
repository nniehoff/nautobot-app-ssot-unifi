"""Test UniFi adapter."""

import json
from unittest.mock import MagicMock, patch

from nautobot.core.testing import TransactionTestCase
from nautobot.extras.models import JobResult

from nautobot_ssot_unifi.diffsync.adapters.unifi import UniFiAdapter
from nautobot_ssot_unifi.jobs import UniFiDataSource
from nautobot_ssot_unifi.utils.unifi import PLUGIN_CFG, get_controller_name


def load_json(path):
    """Load a json file."""
    with open(path, encoding="utf-8") as file:
        return json.loads(file.read())


SITE_FIXTURE = load_json("./nautobot_ssot_unifi/tests/fixtures/get_sites.json")
AP_FIXTURE = load_json("./nautobot_ssot_unifi/tests/fixtures/get_aps.json")


class TestUniFiAdapterTestCase(TransactionTestCase):
    """Test NautobotSsotUniFiAdapter class."""

    job_class = UniFiDataSource
    databases = ("default", "job_logs")

    def setUp(self):
        """Initialize test case."""
        self.unifi_client = MagicMock()
        self.unifi_client.get_aps.return_value = AP_FIXTURE
        self.unifi_client.get_clients.return_value = []

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
