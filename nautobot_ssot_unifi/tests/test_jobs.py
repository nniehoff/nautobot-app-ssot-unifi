"""Test the UniFi to Nautobot job's handling of Devices already in Nautobot."""

from unittest.mock import MagicMock

from django.contrib.contenttypes.models import ContentType
from nautobot.core.testing import TransactionTestCase
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer
from nautobot.extras.models import JobResult, Role, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix

from nautobot_ssot_unifi.diffsync.adapters.unifi import UniFiAdapter
from nautobot_ssot_unifi.jobs import UniFiDataSource

MAC = "f4:e2:c6:e4:69:3a"


class TestExistingDevicesTestCase(TransactionTestCase):
    """Test UniFiDataSource.handle_existing_devices()."""

    databases = ("default", "job_logs")

    def setUp(self):
        """Create a hand-made Device whose Interface has a MAC UniFi reports, and a UniFi adapter with that device."""
        status, _ = Status.objects.get_or_create(name="Active")
        status.content_types.add(
            ContentType.objects.get_for_model(Device), ContentType.objects.get_for_model(Interface)
        )
        role = Role.objects.create(name="Access Switch")
        role.content_types.add(ContentType.objects.get_for_model(Device))
        location_type, _ = LocationType.objects.get_or_create(name="Site")
        location_type.content_types.add(ContentType.objects.get_for_model(Device))
        self.device = Device.objects.create(
            name="usw1-manual",
            location=Location.objects.create(name="Home", location_type=location_type, status=status),
            role=role,
            device_type=DeviceType.objects.create(
                model="USW-Enterprise-24-PoE", manufacturer=Manufacturer.objects.create(name="Ubiquiti Networks")
            ),
            status=status,
        )
        # Port MAC first: matching must use the MAC UniFi reports, not the first one found.
        Interface.objects.create(
            device=self.device, name="Port 1", type="1000base-t", status=status, mac_address="F4:E2:C6:E4:69:3B"
        )
        Interface.objects.create(device=self.device, name="mgmt", type="other", status=status, mac_address=MAC.upper())

        self.job = UniFiDataSource()
        self.job.job_result = JobResult.objects.create(
            name=self.job.class_path, task_name="fake task", worker="default"
        )
        self.job.debug = False
        self.job.adopt = {}
        self.job.source_adapter = UniFiAdapter(job=self.job, sync=None, client=MagicMock())
        self.job.source_adapter.add(
            self.job.source_adapter.device(
                mac_address=MAC,
                name="usw1",
                location__name="Home",
                serial="ABC",
                role__name="Unknown",
                device_type__model="Switch Enterprise 24 PoE",
                device_type__manufacturer__name="Ubiquiti",
                status__name="Active",
            )
        )

    def test_skip(self):
        """Skip leaves the Device alone and drops it from the sync."""
        self.job.existing_devices = "skip"
        self.assertEqual([], self.job.handle_existing_devices({MAC}))
        self.assertEqual([], self.job.source_adapter.get_all("device"))

    def test_adopt(self):
        """Adopt loads the Device and matches it by the MAC UniFi reports, keeping its Role and Device Type."""
        self.job.existing_devices = "adopt"
        self.job.sync = None
        self.assertEqual([self.device.pk], self.job.handle_existing_devices({MAC}))
        self.job.load_target_adapter()
        adopted = self.job.target_adapter.get("device", MAC)
        self.assertEqual("usw1-manual", adopted.name)
        unifi_device = self.job.source_adapter.get("device", MAC)
        self.assertEqual(
            ("Access Switch", "USW-Enterprise-24-PoE"), (unifi_device.role__name, unifi_device.device_type__model)
        )

    def test_create(self):
        """Create keeps the UniFi device, so the sync adds a separate Device."""
        self.job.existing_devices = "create"
        self.assertEqual([], self.job.handle_existing_devices({MAC}))
        self.assertEqual([MAC], [device.mac_address for device in self.job.source_adapter.get_all("device")])

    def test_describe_adoption(self):
        """The adoption warning lists what changes and what is kept."""
        description = UniFiDataSource.describe_adoption(self.device, self.job.source_adapter.get("device", MAC))
        self.assertIn("name: 'usw1-manual' -> 'usw1'", description)
        self.assertIn("serial: '' -> 'ABC'", description)
        self.assertIn("keeps role 'Access Switch' (UniFi reports 'Unknown')", description)

    def _add_unifi_ip_address(self):
        """Create an IP Address by hand, and the same address in the UniFi adapter."""
        Namespace.objects.get_or_create(name="Global")
        status = Status.objects.get(name="Active")
        status.content_types.add(
            ContentType.objects.get_for_model(Prefix), ContentType.objects.get_for_model(IPAddress)
        )
        Prefix.objects.create(prefix="10.31.0.0/24", status=status)
        existing = IPAddress.objects.create(address="10.31.0.87/24", status=status)
        self.job.source_adapter.add(
            self.job.source_adapter.ipaddress(
                host="10.31.0.87",
                parent__namespace__name="Global",
                mask_length=24,
                status__name="Active",
                type="host",
            )
        )
        return existing

    def test_existing_ip_address_skip(self):
        """With Skip, an existing IP Address is used as is: dropped from the sync, never adopted."""
        self._add_unifi_ip_address()
        self.job.existing_devices = "skip"
        self.job.handle_existing_ip_addresses()
        self.assertEqual([], self.job.source_adapter.get_all("ipaddress"))
        self.assertEqual({}, self.job.adopt)

    def test_existing_ip_address_adopt(self):
        """With Adopt, an existing IP Address stays in the sync and is loaded from Nautobot as its match."""
        existing = self._add_unifi_ip_address()
        self.job.existing_devices = "adopt"
        self.job.handle_existing_ip_addresses()
        self.assertEqual(["10.31.0.87"], [ip.host for ip in self.job.source_adapter.get_all("ipaddress")])
        self.assertEqual({"ipaddress": {existing.pk: {}}}, self.job.adopt)
