"""Test Nautobot adapter."""

from diffsync.exceptions import ObjectNotCreated
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
from nautobot.extras.choices import CustomFieldTypeChoices
from nautobot.extras.models import CustomField, JobResult, Role, Status
from nautobot.wireless.models import ControllerManagedDeviceGroupWirelessNetworkAssignment, WirelessNetwork

from nautobot_ssot_unifi.constants import SYSTEM_OF_RECORD
from nautobot_ssot_unifi.diffsync.adapters.nautobot import UniFiNautobotAdapter
from nautobot_ssot_unifi.diffsync.models.base import CableModel, DeviceModel
from nautobot_ssot_unifi.jobs import UniFiDataSource
from nautobot_ssot_unifi.utils.unifi import get_controller_name


class TestUniFiNautobotAdapterTestCase(TransactionTestCase):
    """Test UniFiNautobotAdapter class."""

    databases = ("default", "job_logs")

    @staticmethod
    def _create_custom_fields():
        """Create the Custom Fields the app's signal handler creates on a real install."""
        device_ct = ContentType.objects.get_for_model(Device)
        location_ct = ContentType.objects.get_for_model(Location)
        group_ct = ContentType.objects.get_for_model(ControllerManagedDeviceGroup)
        wireless_ct = ContentType.objects.get_for_model(WirelessNetwork)
        cable_ct = ContentType.objects.get_for_model(Cable)
        for key, content_types in (
            ("system_of_record", [cable_ct, device_ct, wireless_ct]),
            ("unifi_controller", [cable_ct, device_ct, location_ct, group_ct, wireless_ct]),
            ("unifi_site", [location_ct, group_ct]),
        ):
            custom_field, _ = CustomField.objects.get_or_create(
                key=key, defaults={"label": key, "type": CustomFieldTypeChoices.TYPE_TEXT}
            )
            custom_field.content_types.add(*content_types)

    def setUp(self):
        """Create Locations and Devices from this controller, another controller, another System of Record, and none."""
        self._create_custom_fields()
        device_ct = ContentType.objects.get_for_model(Device)

        status, _ = Status.objects.get_or_create(name="Active")
        status.content_types.add(device_ct, ContentType.objects.get_for_model(Interface))
        connected, _ = Status.objects.get_or_create(name="Connected")
        connected.content_types.add(ContentType.objects.get_for_model(Cable))
        role, _ = Role.objects.get_or_create(name="Router")
        role.content_types.add(device_ct)
        location_type, _ = LocationType.objects.get_or_create(name="Site")
        location_type.content_types.add(device_ct, ContentType.objects.get_for_model(Controller))
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
