# App Overview

This document provides an overview of the App including critical information and important considerations when applying it to your Nautobot environment.

!!! note
    Throughout this documentation, the terms "app" and "plugin" will be used interchangeably.

## Description

![Main Page](../media/ss_main_page_light.png#only-light)
![Main Page](../media/ss_main_page_dark.png#only-dark)

## Audience (User Personas) - Who should use this App?

!!! warning "Developer Note - Remove Me!"
    Who is this meant for/ who is the common user of this app?

## Authors and Maintainers

!!! warning "Developer Note - Remove Me!"
    Add the team and/or the main individuals maintaining this project. Include historical maintainers as well.

## Nautobot Features Used

!!! warning "Developer Note - Remove Me!"
    What is shown today in the Installed Apps page in Nautobot. What parts of Nautobot does it interact with, what does it add etc. ?

### Extras

#### Custom Fields

The app creates these Custom Fields when Nautobot starts. The sync uses them to match UniFi objects to Nautobot objects, and to load only objects it manages, so it never updates or deletes anything else.

| Key | Label | Applies to | Purpose |
| --- | ----- | ---------- | ------- |
| `system_of_record` | System of Record | Device, Interface, IP Address, Wireless Network | Set to `UniFi SSoT` on every Device and Wireless Network the sync creates. |
| `ssot_last_synchronized` | Last sync from System of Record | Device, Interface, IP Address, Wireless Network | Date of the last sync that touched the object. |
| `unifi_controller` | UniFi Controller | Device, Location, Controller Managed Device Group, Wireless Network | The `controller_name` setting of the controller the object came from. |
| `unifi_site` | UniFi Site | Location, Controller Managed Device Group | The site's short name, e.g. `default`. Identifies the Location and group, so renaming a site in UniFi renames them. |

Devices are identified by MAC address, which Nautobot keeps on Interfaces. Each Device the sync creates gets one Interface holding its UniFi MAC: `mgmt` (management only) for UniFi network devices, `eth0` for clients. Renaming a device or client in UniFi renames the Device in Nautobot. A Device with several MAC addresses is matched on its management Interfaces first, then by Interface name.

Device names come from the UniFi alias, then the hostname, then the MAC address. Names must be unique within a Location, so Devices that share a name get their MAC appended, e.g. `iPhone (fe:38:d1:f6:34:8e)`.

#### Software versions

Each UniFi network device gets a Platform for its kind (`UniFi Access Point`, `UniFi Switch`, `UniFi Gateway`, or `UniFi Device`) and a Software Version for the firmware it runs, e.g. `UniFi Switch 7.5.15.17146`. Software Versions no device runs any more are kept as history. Clients get neither.

#### Controller and wireless networks

With `import_wireless` on (the default), the sync also creates:

- A **Controller** named after `controller_name`, with the `wireless` capability, in the first synced site's Location.
- A **Controller Managed Device Group** per site, named after the site, holding the site's UniFi network devices.
- A **Wireless Network** per WLAN SSID, in Local (Flex) mode, assigned to the group of each site broadcasting it. Authentication follows the WLAN's security: WPA2/WPA3 transition mode maps to WPA2, and WLANs with security Nautobot has no choice for, such as WEP, are skipped with a warning.

Passphrases are never read into Nautobot. VLANs of the assignments, radio profiles, and data rates are not synced.

The Location Type of the controller's Location needs to allow Controllers, so the sync adds the Controller content type to it. Content types of Location Types and Roles, and Controller capabilities, are only ever added to, never removed.

#### Fields the sync only sets once

Role, Device Type, and Status are set when the sync creates a Device and never updated afterwards, serial is only updated when UniFi reports one (clients have none), and Platform only when Nautobot has none. Clients keep the Platform, Software Version, and device group set in Nautobot. Assign the right Role or a Device Type from the device type library in Nautobot and the sync keeps it. Location Type and Status of Locations, and Location and Status of the Controller, work the same way. Name, Location, serial, and the custom fields follow UniFi.

#### Devices and Locations already in Nautobot

A Device already in Nautobot, but not synced from this controller, that has an Interface with a MAC address UniFi reports, is handled by the job's **Existing devices** option. Each case is logged as a warning:

- **Skip** (default): the Device is left alone and the UniFi device is not synced.
- **Adopt**: the sync takes the Device over. The warning lists what changes (name, Location, serial) and what it keeps (Role, Device Type). From then on it is synced like any other Device. Run a dry run first and read the warnings.
- **Create**: the sync creates a separate Device from UniFi. This fails if the name is taken in the same Location.

A MAC address found on more than one Device is skipped in every mode. A Location named like a UniFi site that the sync did not create is used as is: the site's Devices are placed in it, and the Location is never changed. Controller Managed Device Groups and Wireless Networks work the same way: an existing group gets the site's Devices, and an existing Wireless Network is assigned to the site's group, without either being changed.

#### Jobs

- **UniFi to Nautobot** syncs UniFi sites, devices, clients, firmware versions, the controller, and WLANs into Nautobot.
- **Nautobot to UniFi** is a placeholder. Do not run it: it writes to Nautobot, not UniFi.
