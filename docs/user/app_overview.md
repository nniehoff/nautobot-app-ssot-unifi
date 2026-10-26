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
| `system_of_record` | System of Record | Device, Interface, IP Address | Set to `UniFi SSoT` on every Device the sync creates. |
| `ssot_last_synchronized` | Last sync from System of Record | Device, Interface, IP Address | Date of the last sync that touched the object. |
| `unifi_controller` | UniFi Controller | Device, Location | The `controller_name` setting of the controller the object came from. |
| `unifi_site` | UniFi Site | Location | The site's short name, e.g. `default`. Identifies the Location, so renaming a site in UniFi renames the Location. |

Devices are identified by MAC address, which Nautobot keeps on Interfaces. Each Device the sync creates gets one Interface holding its UniFi MAC: `mgmt` (management only) for UniFi network devices, `eth0` for clients. Renaming a device or client in UniFi renames the Device in Nautobot. A Device with several MAC addresses is matched on its management Interfaces first, then by Interface name.

Device names come from the UniFi alias, then the hostname, then the MAC address. Names must be unique within a Location, so Devices that share a name get their MAC appended, e.g. `iPhone (fe:38:d1:f6:34:8e)`.

#### Fields the sync only sets once

Role, Device Type, and Status are set when the sync creates a Device and never updated afterwards, and serial is only updated when UniFi reports one (clients have none). Assign the right Role or a Device Type from the device type library in Nautobot and the sync keeps it. Location Type and Status of Locations work the same way. Name, Location, serial, and the custom fields follow UniFi.

#### Devices and Locations already in Nautobot

A Device already in Nautobot, but not synced from this controller, that has an Interface with a MAC address UniFi reports, is handled by the job's **Existing devices** option. Each case is logged as a warning:

- **Skip** (default): the Device is left alone and the UniFi device is not synced.
- **Adopt**: the sync takes the Device over. The warning lists what changes (name, Location, serial) and what it keeps (Role, Device Type). From then on it is synced like any other Device. Run a dry run first and read the warnings.
- **Create**: the sync creates a separate Device from UniFi. This fails if the name is taken in the same Location.

A MAC address found on more than one Device is skipped in every mode. A Location named like a UniFi site that the sync did not create is used as is: the site's Devices are placed in it, and the Location is never changed.

#### Jobs

- **UniFi to Nautobot** syncs UniFi sites, devices, and clients into Nautobot.
- **Nautobot to UniFi** is a placeholder. Do not run it: it writes to Nautobot, not UniFi.
