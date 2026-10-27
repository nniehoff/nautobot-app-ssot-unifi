"""Test Nautobot adapter."""

from diffsync.exceptions import ObjectNotCreated
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from nautobot.core.testing import TransactionTestCase
from nautobot.dcim.models import (
    Cable,
    Controller,
    ControllerManagedDeviceGroup,
    Device,
    DeviceType,
    Interface,
    Location,
    LocationType,
    Manufacturer,
)
from nautobot.extras.models import JobResult, Role, Status
from nautobot.ipam.models import VLAN, IPAddress, IPAddressToInterface, Namespace, Prefix, VLANGroup
from nautobot.wireless.models import ControllerManagedDeviceGroupWirelessNetworkAssignment, WirelessNetwork

from nautobot_ssot_unifi.constants import SYSTEM_OF_RECORD
from nautobot_ssot_unifi.diffsync.adapters.nautobot import UniFiNautobotAdapter
from nautobot_ssot_unifi.diffsync.models.base import (
    CableModel,
    DeviceModel,
    InterfaceModel,
    IPAddressAssignmentModel,
    IPAddressModel,
    PrefixModel,
    VLANGroupModel,
    VLANModel,
)
from nautobot_ssot_unifi.jobs import UniFiDataSource
from nautobot_ssot_unifi.signals import nautobot_database_ready_callback
from nautobot_ssot_unifi.utils.nautobot import (
    find_unsynced_ip_address,
    find_unsynced_vlan,
    find_vlan,
    resolve_ip_interface_name,
)
from nautobot_ssot_unifi.utils.unifi import get_controller_name


class TestUniFiNautobotAdapterTestCase(TransactionTestCase):
    """Test UniFiNautobotAdapter class."""

    databases = ("default", "job_logs")

    def setUp(self):
        """Create Locations and Devices from this controller, another controller, another System of Record, and none."""
        # The Custom Fields the app creates when Nautobot starts, which TransactionTestCase flushes.
        nautobot_database_ready_callback(sender=None, apps=django_apps)
        # TransactionTestCase flushes the Global Namespace Nautobot's migrations create.
        Namespace.objects.get_or_create(name="Global")
        device_ct = ContentType.objects.get_for_model(Device)

        status, _ = Status.objects.get_or_create(name="Active")
        status.content_types.add(
            device_ct,
            ContentType.objects.get_for_model(Interface),
            ContentType.objects.get_for_model(IPAddress),
            ContentType.objects.get_for_model(Prefix),
            ContentType.objects.get_for_model(VLAN),
        )
        connected, _ = Status.objects.get_or_create(name="Connected")
        connected.content_types.add(ContentType.objects.get_for_model(Cable))
        role, _ = Role.objects.get_or_create(name="Router")
        role.content_types.add(device_ct)
        location_type, _ = LocationType.objects.get_or_create(name="Site")
        location_type.content_types.add(
            device_ct, ContentType.objects.get_for_model(Controller), ContentType.objects.get_for_model(VLANGroup)
        )
        status.content_types.add(ContentType.objects.get_for_model(Controller))
        location = Location.objects.create(name="Test", location_type=location_type, status=status)
        Location.objects.create(
            name="UniFi Site",
            location_type=location_type,
            status=status,
            _custom_field_data={"unifi_site": "default", "unifi_controller": get_controller_name()},
        )
        Location.objects.create(
            name="Other Controller Site",
            location_type=location_type,
            status=status,
            _custom_field_data={"unifi_site": "default", "unifi_controller": "other-controller.example.com"},
        )
        device_type = DeviceType.objects.create(
            model="Test Model", manufacturer=Manufacturer.objects.create(name="Test Manufacturer")
        )
        for name, system_of_record, controller, mac in (
            ("unifi-device", SYSTEM_OF_RECORD, get_controller_name(), "00:11:22:33:44:01"),
            ("other-controller-device", SYSTEM_OF_RECORD, "other-controller.example.com", "00:11:22:33:44:02"),
            ("other-device", "Other SSoT", None, None),
            ("no-mac-device", SYSTEM_OF_RECORD, get_controller_name(), None),
        ):
            device = Device.objects.create(
                name=name,
                location=location,
                role=role,
                device_type=device_type,
                status=status,
                _custom_field_data={
                    "system_of_record": system_of_record,
                    "unifi_controller": controller,
                },
            )
            if mac:
                # A data port sorting before the management Interface, to check which MAC identifies the Device.
                Interface.objects.create(
                    device=device, name="eth0", type="other", status=status, mac_address="00:11:22:33:44:ff"
                )
                Interface.objects.create(
                    device=device, name="mgmt", type="other", status=status, mgmt_only=True, mac_address=mac
                )
        Device.objects.create(
            name="no-sor-device", location=location, role=role, device_type=device_type, status=status
        )

        job = UniFiDataSource()
        job.job_result = JobResult.objects.create(name=job.class_path, task_name="fake task", worker="default")
        self.nautobot = UniFiNautobotAdapter(job=job, sync=None)

    def test_load_only_unifi_devices(self):
        """Devices from other controllers or Systems of Record are never loaded, so a sync cannot delete them."""
        self.nautobot.load()
        self.assertEqual({"unifi-device"}, {dev.name for dev in self.nautobot.get_all("device")})
        self.assertEqual({"00:11:22:33:44:01"}, {dev.get_unique_id() for dev in self.nautobot.get_all("device")})

    def test_load_only_unifi_locations(self):
        """Locations without a UniFi site, or from other controllers, are never loaded."""
        self.nautobot.load()
        self.assertEqual({"UniFi Site"}, {location.name for location in self.nautobot.get_all("location")})

    def test_create_device_with_mac_interface(self):
        """Creating a Device also creates the Interface holding its MAC, so the next sync matches it."""
        DeviceModel.create(
            adapter=self.nautobot,
            ids={"mac_address": "00:11:22:33:44:aa"},
            attrs={
                "name": "new-client",
                "location__name": "Test",
                "role__name": "Router",
                "device_type__model": "Test Model",
                "device_type__manufacturer__name": "Test Manufacturer",
                "status__name": "Active",
                "system_of_record": SYSTEM_OF_RECORD,
                "unifi_controller": get_controller_name(),
            },
        )
        interface = Interface.objects.get(device__name="new-client")
        self.assertEqual(("mgmt", True), (interface.name, interface.mgmt_only))
        self.nautobot.load()
        self.assertIn("00:11:22:33:44:aa", {dev.get_unique_id() for dev in self.nautobot.get_all("device")})

    def test_load_only_unifi_wireless(self):
        """Only this controller, its groups, the Wireless Networks it synced, and their assignments are loaded."""
        location = Location.objects.get(name="UniFi Site")
        controller = Controller.objects.create(
            name=get_controller_name(), location=location, status=Status.objects.get(name="Active")
        )
        other_controller = Controller.objects.create(
            name="other-controller.example.com", location=location, status=Status.objects.get(name="Active")
        )
        group = ControllerManagedDeviceGroup.objects.create(
            name="UniFi Site",
            controller=controller,
            _custom_field_data={"unifi_site": "default", "unifi_controller": get_controller_name()},
        )
        ControllerManagedDeviceGroup.objects.create(name="Other Group", controller=other_controller)
        synced = WirelessNetwork.objects.create(
            name="Home",
            ssid="Home",
            mode="Local (Flex)",
            authentication="WPA2 Personal",
            _custom_field_data={"system_of_record": SYSTEM_OF_RECORD, "unifi_controller": get_controller_name()},
        )
        manual = WirelessNetwork.objects.create(
            name="Manual", ssid="Manual", mode="Central", authentication="WPA2 Enterprise"
        )
        for wireless_network in (synced, manual):
            ControllerManagedDeviceGroupWirelessNetworkAssignment.objects.create(
                controller_managed_device_group=group, wireless_network=wireless_network
            )
        self.nautobot.load()
        self.assertEqual([get_controller_name()], [obj.name for obj in self.nautobot.get_all("controller")])
        self.assertEqual(["UniFi Site"], [obj.name for obj in self.nautobot.get_all("devicegroup")])
        self.assertEqual(["Home"], [obj.name for obj in self.nautobot.get_all("wirelessnetwork")])
        self.assertEqual(
            {"UniFi Site__Home", "UniFi Site__Manual"},
            {obj.get_unique_id() for obj in self.nautobot.get_all("wirelessnetworkassignment")},
        )

    def test_cable_create_move_and_conflict(self):
        """Cables are created with their Interfaces, move with the client, and never replace a hand-made Cable."""
        Role.objects.get_or_create(name="Client")[0].content_types.add(ContentType.objects.get_for_model(Device))
        DeviceModel.create(
            adapter=self.nautobot,
            ids={"mac_address": "00:11:22:33:44:aa"},
            attrs={
                "name": "new-client",
                "location__name": "Test",
                "role__name": "Client",
                "device_type__model": "Test Model",
                "device_type__manufacturer__name": "Test Manufacturer",
                "status__name": "Active",
                "system_of_record": SYSTEM_OF_RECORD,
                "unifi_controller": get_controller_name(),
            },
        )
        ids = {"mac_address": "00:11:22:33:44:aa"}
        attrs = {"interface": "eth0", "upstream_mac_address": "00:11:22:33:44:01", "upstream_interface": "Port 3"}
        CableModel.create(adapter=self.nautobot, ids=ids, attrs=attrs)
        switch = Device.objects.get(name="unifi-device")
        self.assertIsNotNone(switch.interfaces.get(name="Port 3").cable)

        self.nautobot.load()
        cable = self.nautobot.get("cable", "00:11:22:33:44:aa")
        self.assertEqual(("eth0", "Port 3"), (cable.interface, cable.upstream_interface))

        cable.update({"upstream_interface": "Port 4"})
        self.assertIsNone(switch.interfaces.get(name="Port 3").cable)
        self.assertIsNotNone(switch.interfaces.get(name="Port 4").cable)

        Cable.objects.create(
            termination_a=switch.interfaces.get(name="Port 3"),
            termination_b=Interface.objects.get(device__name="other-controller-device", name="eth0"),
            status=Status.objects.get(name="Connected"),
        )
        with self.assertRaises(ObjectNotCreated):
            CableModel.create(
                adapter=self.nautobot,
                ids={"mac_address": "00:11:22:33:44:02"},
                attrs={
                    "interface": "mgmt",
                    "upstream_mac_address": "00:11:22:33:44:01",
                    "upstream_interface": "Port 3",
                },
            )

    def test_ip_addresses(self):
        """IP Addresses are created under their Prefix and assigned; ones set up by hand keep their Interface."""
        PrefixModel.create(
            adapter=self.nautobot,
            ids={"network": "192.168.1.0", "prefix_length": 24, "namespace__name": "Global"},
            attrs={"status__name": "Active"},
        )
        IPAddressModel.create(
            adapter=self.nautobot,
            ids={"host": "192.168.1.20", "parent__namespace__name": "Global"},
            attrs={
                "mask_length": 24,
                "status__name": "Active",
                "type": "dhcp",
                "system_of_record": SYSTEM_OF_RECORD,
                "unifi_controller": get_controller_name(),
            },
        )
        IPAddressAssignmentModel.create(
            adapter=self.nautobot,
            ids={"mac_address": "00:11:22:33:44:01", "host": "192.168.1.20"},
            attrs={"interface": "mgmt"},
        )
        synced = IPAddress.objects.get(host="192.168.1.20")
        self.assertEqual("192.168.1.0/24", str(synced.parent.prefix))
        self.assertEqual(["mgmt"], [interface.name for interface in synced.interfaces.all()])

        # Addresses set up by hand: one UniFi reports, already on eth0, and one it does not.
        eth0 = Interface.objects.get(device__name="unifi-device", name="eth0")
        for address in ("192.168.1.30/24", "192.168.1.40/24"):
            manual = IPAddress.objects.create(address=address, status=Status.objects.get(name="Active"))
            IPAddressToInterface.objects.create(ip_address=manual, interface=eth0)
        self.assertEqual("eth0", resolve_ip_interface_name("00:11:22:33:44:01", "192.168.1.30", "mgmt"))
        self.assertEqual("mgmt", resolve_ip_interface_name("00:11:22:33:44:01", "192.168.1.99", "eth0"))
        self.assertIsNotNone(find_unsynced_ip_address("192.168.1.30"))
        self.assertIsNone(find_unsynced_ip_address("192.168.1.20"))

        nautobot = UniFiNautobotAdapter(job=self.nautobot.job, sync=None, unifi_ips={"192.168.1.30"})
        nautobot.load()
        self.assertEqual(["192.168.1.20"], [ip.host for ip in nautobot.get_all("ipaddress")])
        self.assertEqual(
            {("192.168.1.20", "mgmt"), ("192.168.1.30", "eth0")},
            {(assignment.host, assignment.interface) for assignment in nautobot.get_all("ipassignment")},
        )

        nautobot.get("ipassignment", "00:11:22:33:44:01__192.168.1.20").update({"interface": "eth0"})
        self.assertEqual(["eth0"], [interface.name for interface in synced.interfaces.all()])

        # Deleting the IP Address removes its assignment, so deleting the assignment afterwards is a no-op.
        nautobot.get("ipaddress", "192.168.1.20__Global").delete()
        nautobot.get("ipassignment", "00:11:22:33:44:01__192.168.1.20").delete()
        self.assertFalse(IPAddress.objects.filter(host="192.168.1.20").exists())
        self.assertEqual(2, IPAddressToInterface.objects.filter(interface=eth0).count())

    def test_switch_port_vlans(self):
        """Switch ports get their mode and VLANs, preferring the site's synced VLANs over ones made by hand."""
        VLANGroupModel.create(
            adapter=self.nautobot,
            ids={"unifi_site": "default", "unifi_controller": get_controller_name()},
            # The group must be in the Devices' Location for them to use its VLANs.
            attrs={"name": "UniFi Site", "location__name": "Test"},
        )
        for vid, name in ((1, "Default"), (20, "IoT")):
            VLANModel.create(
                adapter=self.nautobot,
                ids={"vid": vid, "vlan_group__name": "UniFi Site"},
                attrs={
                    "name": name,
                    "status__name": "Active",
                    "system_of_record": SYSTEM_OF_RECORD,
                    "unifi_controller": get_controller_name(),
                },
            )
        # A global VLAN made by hand: used for VLAN 30, which the site's group lacks, but not for VLAN 20.
        manual = VLAN.objects.create(vid=30, name="Cameras", status=Status.objects.get(name="Active"))
        VLAN.objects.create(vid=20, name="Manual IoT", status=Status.objects.get(name="Active"))
        location = Location.objects.get(name="Test")
        self.assertEqual("UniFi Site", find_vlan(20, location).vlan_group.name)
        self.assertEqual(manual, find_vlan(30, location))
        self.assertEqual(manual, find_unsynced_vlan(30, "Test"))

        InterfaceModel.create(
            adapter=self.nautobot,
            ids={"mac_address": "00:11:22:33:44:01", "name": "Port 1"},
            attrs={"type": "1000base-t", "mode": "tagged", "untagged_vid": 1, "tagged_vids": [20, 30]},
        )
        port = Interface.objects.get(device__name="unifi-device", name="Port 1")
        self.assertEqual(("1000base-t", "tagged", 1), (port.type, port.mode, port.untagged_vlan.vid))
        self.assertEqual({20, 30}, {vlan.vid for vlan in port.tagged_vlans.all()})

        self.nautobot.load()
        loaded = self.nautobot.get("interface", "00:11:22:33:44:01__Port 1")
        self.assertEqual(("tagged", 1, [20, 30]), (loaded.mode, loaded.untagged_vid, loaded.tagged_vids))
        self.assertEqual({1, 20}, {vlan.vid for vlan in self.nautobot.get_all("vlan")})

        loaded.update({"mode": "access", "untagged_vid": 20, "tagged_vids": []})
        port.refresh_from_db()
        self.assertEqual(("access", 20), (port.mode, port.untagged_vlan.vid))
        self.assertFalse(port.tagged_vlans.exists())

    def test_adopt_existing_objects(self):
        """Adopted objects load as UniFi's match, even when identified by custom fields they lack, and get them."""
        location = Location.objects.get(name="Test")
        Prefix.objects.create(prefix="192.168.1.0/24", status=Status.objects.get(name="Active"))
        ip_address = IPAddress.objects.create(address="192.168.1.50/24", status=Status.objects.get(name="Active"))
        nautobot = UniFiNautobotAdapter(
            job=self.nautobot.job,
            sync=None,
            adopt={
                "location": {location.pk: {"unifi_site": "office", "unifi_controller": get_controller_name()}},
                "ipaddress": {ip_address.pk: {}},
            },
        )
        nautobot.load()
        self.assertEqual(["192.168.1.50"], [ip.host for ip in nautobot.get_all("ipaddress")])
        adopted = nautobot.get("location", f"office__{get_controller_name()}")
        self.assertEqual("Test", adopted.name)

        adopted.update({"system_of_record": SYSTEM_OF_RECORD})
        location.refresh_from_db()
        self.assertEqual(
            {"unifi_site": "office", "unifi_controller": get_controller_name(), "system_of_record": SYSTEM_OF_RECORD},
            {key: location.cf.get(key) for key in ("unifi_site", "unifi_controller", "system_of_record")},
        )
        # Now synced, the Location loads without adopting it again.
        reloaded = UniFiNautobotAdapter(job=self.nautobot.job, sync=None)
        reloaded.load()
        self.assertIn(f"office__{get_controller_name()}", {obj.get_unique_id() for obj in reloaded.get_all("location")})
