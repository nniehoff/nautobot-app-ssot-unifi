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
| `system_of_record` | System of Record | Cable, Device, Interface, IP Address, Wireless Network | Set to `UniFi SSoT` on every Cable, Device, IP Address, and Wireless Network the sync creates. |
| `ssot_last_synchronized` | Last sync from System of Record | Cable, Device, Interface, IP Address, Wireless Network | Date of the last sync that touched the object. |
| `unifi_controller` | UniFi Controller | Cable, Device, IP Address, Location, Controller Managed Device Group, VLAN Group, Wireless Network | The `controller_name` setting of the controller the object came from. |
| `unifi_site` | UniFi Site | Location, Controller Managed Device Group, VLAN Group | The site's short name, e.g. `default`. Identifies the Location and groups, so renaming a site in UniFi renames them. |

Devices are identified by MAC address, which Nautobot keeps on Interfaces. Each Device the sync creates gets one Interface holding its UniFi MAC: `mgmt` (management only) for UniFi network devices, `eth0` for clients. Renaming a device or client in UniFi renames the Device in Nautobot. A Device with several MAC addresses is matched on its management Interfaces first, then by Interface name.

Device names come from the UniFi alias, then the hostname, then the MAC address. Names must be unique within a Location, so Devices that share a name get their MAC appended, e.g. `iPhone (fe:38:d1:f6:34:8e)`.

#### Software versions

Each UniFi network device gets a Platform for its kind (`UniFi Access Point`, `UniFi Switch`, `UniFi Gateway`, or `UniFi Device`) and a Software Version for the firmware it runs, e.g. `UniFi Switch 7.5.15.17146`. Software Versions no device runs any more are kept as history. Clients get neither.

#### Cables

With `import_cables` on (the default), the sync creates a Cable from each wired UniFi device and client to the switch port UniFi reports it on: the upstream switch port is the Cable's A side, the device or client its B side. A Cable moves when the device or client moves to another port, and is deleted when either end leaves the sync.

Ports are matched to Interfaces by name: the port's name in UniFi (e.g. `Uplink`), then the name UniFi gives it by default (`Port 8`, or `SFP+ 1` for fiber ports), then `Port 8`, then `8`. A port with no matching Interface gets a new Interface with the default name, and an access point an `eth0` Interface. Clients are cabled from the Interface holding their MAC address. Switch Interfaces named `Port <n>`, as UniFi names ports by default, are used as they are.

Some links get no Cable:

- Wireless clients, and access points uplinked over mesh.
- Ports with several clients, such as clients behind an unmanaged switch or a host with virtual machines. When one of them is a UniFi device, its Cable is created and the clients are skipped.
- Links to devices or clients left out of the sync, such as an upstream device outside UniFi.
- Interfaces that already have a Cable the sync did not create. A matching Cable made by hand is left as is; any other is logged as a warning.

#### IP addresses

With `import_ip_addresses` on (the default), the sync creates a Prefix for the subnet of each UniFi network, and an IP Address for the address UniFi reports for each synced device and client, in the Namespace set by `namespace` (`Global` by default). The mask comes from the UniFi network containing the address, else from the narrowest Prefix in Nautobot containing it. Addresses with neither, such as a gateway's public WAN address, are skipped. Clients with a fixed IP in UniFi, and devices with a static management address, get type Host; others DHCP.

Each IP Address is assigned to an Interface of its Device:

- The Interface it is already assigned to, if it was set up on that Device by hand, e.g. on `eth0` instead of `mgmt`.
- Otherwise the Interface holding the Device's MAC address, else a new `mgmt` (UniFi devices) or `eth0` (clients) Interface.

When a client's address changes, its assignment and the old IP Address go, so DHCP addresses follow UniFi. Prefixes and IP Addresses already in Nautobot are used as they are: the sync assigns them to Interfaces but never changes or deletes them, and addresses set up by hand that UniFi does not report are never unassigned. Prefixes are never deleted, and keep the Status set in Nautobot, as do IP Addresses. Primary IPs are not set.

#### VLANs and switch ports

With `import_vlans` on (the default), each site's networks become VLANs in a VLAN Group named after the site, in the site's Location, whose Location Type gets the VLAN Group content type; the network without a VLAN, UniFi's default network, is VLAN 1. WAN and VPN networks are skipped. VLANs are never deleted, and keep the Status set in Nautobot.

Each port of a UniFi switch, or of a gateway with switch ports, gets the 802.1Q settings of its port profile, or its own settings when it has no profile:

| UniFi tagged VLAN management | 802.1Q mode | Tagged VLANs |
| ---------------------------- | ----------- | ------------ |
| Block all | Access | None |
| Allow all | Tagged (All) | None |
| Custom | Tagged | Every VLAN except the excluded ones and the native one |

The port's native network is the untagged VLAN. A disabled port gets no mode. Ports in a link aggregation group, other than the group's first port, are skipped. Ports are matched to Interfaces as for Cables, and a missing one is created with a type from the port's media, e.g. `2.5gbase-t` or `10gbase-x-sfpp`. Existing Interfaces keep their type.

VLANs already in Nautobot are used as they are, never changed: a VLAN ID that has a VLAN usable in the site's Location, global or in that Location or a parent, is not created in the site's group, and ports use the existing VLAN. A VLAN Group named like the site that the sync did not create gets the site's VLANs without being changed.

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

- **UniFi to Nautobot** syncs UniFi sites, devices, clients, cables, IP addresses, network subnets, VLANs, switch port settings, firmware versions, the controller, and WLANs into Nautobot.
- **Nautobot to UniFi** is a placeholder. Do not run it: it writes to Nautobot, not UniFi.
