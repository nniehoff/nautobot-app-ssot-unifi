"""Test Nautobot adapter."""

from django.contrib.contenttypes.models import ContentType
from nautobot.core.testing import TransactionTestCase
from nautobot.dcim.models import Device, DeviceType, Location, LocationType, Manufacturer
from nautobot.extras.choices import CustomFieldTypeChoices
from nautobot.extras.models import CustomField, JobResult, Role, Status

from nautobot_ssot_unifi.constants import SYSTEM_OF_RECORD
from nautobot_ssot_unifi.diffsync.adapters.nautobot import UniFiNautobotAdapter
from nautobot_ssot_unifi.jobs import UniFiDataSource
from nautobot_ssot_unifi.utils.unifi import get_controller_name


class TestUniFiNautobotAdapterTestCase(TransactionTestCase):
    """Test UniFiNautobotAdapter class."""

    databases = ("default", "job_logs")

    def setUp(self):
        """Create Devices from this controller, another controller, another System of Record, and none."""
        device_ct = ContentType.objects.get_for_model(Device)
        sor_cf, _ = CustomField.objects.get_or_create(
            key="system_of_record", defaults={"label": "System of Record", "type": CustomFieldTypeChoices.TYPE_TEXT}
        )
        sor_cf.content_types.add(device_ct)
        controller_cf, _ = CustomField.objects.get_or_create(
            key="unifi_controller", defaults={"label": "UniFi Controller", "type": CustomFieldTypeChoices.TYPE_TEXT}
        )
        controller_cf.content_types.add(device_ct)

        status, _ = Status.objects.get_or_create(name="Active")
        status.content_types.add(device_ct)
        role, _ = Role.objects.get_or_create(name="Router")
        role.content_types.add(device_ct)
        location_type, _ = LocationType.objects.get_or_create(name="Site")
        location_type.content_types.add(device_ct)
        location = Location.objects.create(name="Test", location_type=location_type, status=status)
        device_type = DeviceType.objects.create(
            model="Test Model", manufacturer=Manufacturer.objects.create(name="Test Manufacturer")
        )
        for name, system_of_record, controller in (
            ("unifi-device", SYSTEM_OF_RECORD, get_controller_name()),
            ("other-controller-device", SYSTEM_OF_RECORD, "other-controller.example.com"),
            ("other-device", "Other SSoT", None),
        ):
            Device.objects.create(
                name=name,
                location=location,
                role=role,
                device_type=device_type,
                status=status,
                _custom_field_data={"system_of_record": system_of_record, "unifi_controller": controller},
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
        self.assertEqual({"unifi-device"}, {dev.get_unique_id() for dev in self.nautobot.get_all("device")})
