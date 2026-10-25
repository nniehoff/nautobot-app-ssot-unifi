# Installing the App in Nautobot

Here you will find detailed instructions on how to **install** and **configure** the App within your Nautobot environment.

!!! warning "Developer Note - Remove Me!"
    Detailed instructions on installing the App. You will need to update this section based on any additional dependencies or prerequisites.

## Prerequisites

- The app is compatible with Nautobot 2.4 LTS (2.4.22 or later) and Nautobot 3.x.
- Python 3.14 requires Nautobot 3.x; Nautobot 2.4 supports Python 3.10 through 3.12.
- Databases supported: PostgreSQL, MySQL

!!! note
    Please check the [dedicated page](compatibility_matrix.md) for a full compatibility matrix and the deprecation policy.

### Access Requirements

!!! warning "Developer Note - Remove Me!"
    What external systems (if any) it needs access to in order to work.

## Install Guide

!!! note
    Apps can be installed manually or using Python's `pip`. See the [nautobot documentation](https://docs.nautobot.com/projects/core/en/stable/plugins/#install-the-package) for more details. The pip package name for this app is [`nautobot-ssot-unifi`](https://pypi.org/project/nautobot-ssot-unifi/).

The app is available as a Python package via PyPI and can be installed with `pip`:

```shell
pip install nautobot-ssot-unifi
```

To ensure Nautobot SSoT UniFi is automatically re-installed during future upgrades, create a file named `local_requirements.txt` (if not already existing) in the Nautobot root directory (alongside `requirements.txt`) and list the `nautobot-ssot-unifi` package:

```shell
echo nautobot-ssot-unifi >> local_requirements.txt
```

Once installed, the app needs to be enabled in your Nautobot configuration. The following block of code below shows the additional configuration required to be added to your `nautobot_config.py` file:

- Append `"nautobot_ssot_unifi"` to the `PLUGINS` list.
- Append the `"nautobot_ssot_unifi"` dictionary to the `PLUGINS_CONFIG` dictionary and override any defaults.

```python
# In your nautobot_config.py
PLUGINS = [
    "nautobot_ssot",
    "nautobot_ssot_unifi",
]

PLUGINS_CONFIG = {
    "nautobot_ssot": {
        "hide_example_jobs": True,
    },
    "nautobot_ssot_unifi": {
        "controller_name": os.getenv("UNIFI_CONTROLLER_NAME", ""),
        "unifi_host": os.getenv("UNIFI_HOST", ""),
        "unifi_password": os.getenv("UNIFI_PASSWORD", ""),
        "unifi_port": int(os.getenv("UNIFI_PORT", "8443")),
        "unifi_user": os.getenv("UNIFI_USER", ""),
        "unifi_version": os.getenv("UNIFI_VERSION", "v5"),
        "verify": is_truthy(os.getenv("UNIFI_VERIFY", "true")),
    },
}
```

Once the Nautobot configuration is updated, run the Post Upgrade command (`nautobot-server post_upgrade`) to run migrations and clear any cache:

```shell
nautobot-server post_upgrade
```

Then restart (if necessary) the Nautobot services which may include:

- Nautobot
- Nautobot Workers
- Nautobot Scheduler

```shell
sudo systemctl restart nautobot nautobot-worker nautobot-scheduler
```

## App Configuration

The app behavior can be controlled with the following list of settings:

| Key              | Example              | Default | Description                                                   |
| ---------------- | -------------------- | ------- | ------------------------------------------------------------- |
| `controller_name` | `"home"`            | `unifi_host` | Name stored in each synced Device's UniFi Controller custom field. A sync only updates or deletes Devices with this controller's name, so several controllers can sync into one Nautobot. Set it to keep the name stable if the controller's address changes. |
| `unifi_host`     | `"unifi.example.com"` | N/A     | Hostname or IP address of the UniFi Network controller.      |
| `unifi_password` | `"changeme"`         | N/A     | Password for the UniFi controller user.                       |
| `unifi_port`     | `8443`               | N/A     | Port of the UniFi controller API. Use `443` for UniFi OS consoles. |
| `unifi_user`     | `"nautobot"`         | N/A     | Username for authenticating to the UniFi controller.          |
| `unifi_version`  | `"UDMP-unifiOS"`     | `"v5"`  | Controller API flavor passed to pyunifi. Use `"UDMP-unifiOS"` for UniFi OS consoles and UniFi OS Server, `"v5"` for a standalone Network application. |
| `verify`         | `True`               | N/A     | Whether to verify the controller's TLS certificate.           |
