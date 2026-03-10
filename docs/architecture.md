# Architecture

*ICS-SimLab Extended: Unseen University Power & Light Co.*

## Overview

ICS-SimLab Extended wraps the [Curtin ICS-SimLab](../curtin-ics-simlab/) control zone
simulator and adds an enterprise zone, an operational zone, a field device network, and
the network scaffolding that connects them. The result is a five-network Industrial
Control System environment suitable for open-ended red team exercises.

The environment simulates the operational infrastructure of **Unseen University Power &
Light Co.** (UU P&L), Ankh-Morpork's primary utility provider. A system characterised
by layered legacy technology, institutional knowledge gaps, and a cybersecurity posture
best described as emergent.

Players enter via SSH. What happens next is up to them.

## Network topology

Five Docker bridge networks. All are created by the shared
`infrastructure/networks/docker-compose.yml` stack before any zone stack starts.
Zone stacks declare all networks they use as `external`.

```
ics_internet   10.10.0.0/24   Public network. Jump host lives here.
ics_enterprise 10.10.1.0/24   Enterprise zone.
ics_operational 10.10.2.0/24  Operational zone.
ics_control    10.10.3.0/24   Control zone (ICS-SimLab).
ics_wan        10.10.4.0/24   OT/RTU network. City RTUs live here.
```

Zone isolation is enforced by Docker bridge separation. Containers only reach
containers that share a bridge. The DOCKER-USER iptables chain enforces additional
cross-zone policy on top of that (applied after all stacks are up, requires root).

### Pivot points

Three dual-homed containers bridge the zone boundaries:

| Container                 | Networks                         | IPs                      |
|---------------------------|----------------------------------|--------------------------|
| `jump-host`               | ics_internet + ics_enterprise    | 10.10.0.5 / 10.10.1.5    |
| `enterprise-workstation`  | ics_enterprise + ics_operational | 10.10.1.20 / 10.10.2.100 |
| `engineering-workstation` | ics_operational + ics_control    | 10.10.2.30 / 10.10.3.100 |

```
  Attacker
    │ SSH
    ▼
┌──────────────────────────────────────────────────────┐
│  ics_internet   10.10.0.0/24                         │
│  ┌─────────────────────────────────────────────────┐ │
│  │  jump-host  unseen-gate                         │ │
│  │  10.10.0.5 (internet) / 10.10.1.5 (enterprise)  │ │
│  └───────────────────────────┬─────────────────────┘ │
└──────────────────────────────┼───────────────────────┘
                               │ dual-homed
┌──────────────────────────────▼───────────────────────┐
│  ics_enterprise   10.10.1.0/24                       │
│                                                      │
│  legacy-workstation  10.10.1.10                      │
│  enterprise-workstation  10.10.1.20 / 10.10.2.100  ──┼───┐
└──────────────────────────────────────────────────────┘   │ dual-homed
                                                           │
┌──────────────────────────────────────────────────────────▼─┐
│  ics_operational   10.10.2.0/24                            │
│                                                            │
│  historian       10.10.2.10                                │
│  scada-server    10.10.2.20                                │
│  engineering-workstation 10.10.2.30 / 10.10.3.100  ────────┼──┐
└────────────────────────────────────────────────────────────┘  │ dual-homed
                                                                │
┌───────────────────────────────────────────────────────────────▼─┐
│  ics_control   10.10.3.0/24   (ICS-SimLab)                      │
│                                                                 │
│  hmi_main  10.10.3.10    hex_turbine_controller  10.10.3.21     │
│  ied_relay_a  10.10.3.31    ied_relay_b  10.10.3.32             │
│  ied_meter_main  10.10.3.33                                     │
│  sensors  10.10.3.41–47    actuators  10.10.3.51–54             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  ics_wan   10.10.4.0/24   (OT/RTU network)                      │
│                                                                 │
│  rtu-dolly-1   10.10.4.10   Dolly Sisters Substation            │
│  rtu-naphill-1 10.10.4.20   Nap Hill Feeder                     │
│  rtu-tump-1    10.10.4.30   Tump Crossing Distribution          │
│                                                                 │
│  SCADA polls RTUs outbound from ics_operational into ics_wan.   │
│  RTUs run Modbus TCP (502), SNMP (161). No authentication.      │
└─────────────────────────────────────────────────────────────────┘
```

`ics_wan` is not connected to `ics_control`. The RTUs and the IED network are
distinct. SCADA reaches both: the historian aggregates IED telemetry and polls
RTU state via Modbus outbound into `ics_wan`.

---

## Firewall policy

Rules applied to the DOCKER-USER chain after all zones are up. Requires root.
Generated from `orchestrator/firewall-rules.txt` by `orchestrator/generate.py`.

```
internet → enterprise/operational/control/wan    DROP
  (jump host bridges via dual-homing, not routing)

enterprise → historian:8080                      ACCEPT
enterprise → scada:8080                          ACCEPT
enterprise → engineering-workstation:22                  ACCEPT
enterprise → operational (rest)                  DROP
enterprise → control                             DROP
enterprise → wan                                 DROP

engineering-workstation → control:502                    ACCEPT  (Modbus)
operational → control (rest)                     DROP

scada → wan:502                                  ACCEPT  (Modbus poll)
scada → wan:161/udp                              ACCEPT  (SNMP)
engineering-workstation → wan:502                        ACCEPT
engineering-workstation → wan:161/udp                    ACCEPT
operational → wan (rest)                         DROP

control → enterprise/operational                 DROP
wan → internet/enterprise/operational/control    DROP

(final)                                          RETURN
```

## Components

### Internet zone

#### jump-host (`unseen-gate`, 10.10.0.5 / 10.10.1.5)

The sole entry point. Dual-homed on `ics_internet` and `ics_enterprise`.
Five adversary accounts (`moist`, `teatime`, `carrot`, `angua`, `vimes`).
Key-only SSH. A README in each home directory describes what lies beyond.

### Enterprise zone

#### legacy-workstation (`hex-legacy-1`, 10.10.1.10)

A Win95-era workstation running legacy UU P&L inventory software. Single-homed
on `ics_enterprise`.

- SMB null session
- Anonymous FTP with readable directories
- Telnet service
- Hardcoded local credentials

#### enterprise-workstation (`bursar-desk`, 10.10.1.20 / 10.10.2.100)

The Bursar's administrative workstation. Dual-homed on `ics_enterprise` and
`ics_operational`, the IT/OT convergence point. Accumulated network access
that was never revoked.

- Weak SSH password
- Plaintext operational credentials in config files

### Operational zone

#### historian (`uupl-historian`, 10.10.2.10)

Time-series store for plant measurements. Flask + SQLite. Seeded with data
from the active ICS process.

- SQL injection in the `/report` query endpoint
- Database password `Historian2015`, set at installation, never rotated

#### scada-server (`distribution-scada`, 10.10.2.20)

SCADA aggregation point. Pulls historian data and proxies RTU state. Flask
with HTTP basic auth.

- Default admin credentials

#### engineering-workstation (`uupl-eng-ws`, 10.10.2.30 / 10.10.3.100)

Engineering workstation for PLC/IED configuration. Dual-homed on
`ics_operational` and `ics_control`. Contains credentials for every device
in the control zone, stored in plaintext.

- Plaintext PLC/IED credentials in `/home/engineer/plc-access.conf`
- Python Modbus client tools, pre-configured
- Direct network access to control zone
- No audit logging

### Control zone

Managed by the [Curtin ICS-SimLab](../curtin-ics-simlab/) framework. The ICS
process is selected in `ctf-config.yaml`; the control zone compose file is
generated by `orchestrator/generate.py` wrapping ICS-SimLab's output.

Default process: `uupl_ied`, UU P&L Hex Steam Turbine with protective relay IEDs.

| Device                   | Type | IP            | Role                                        |
|--------------------------|------|---------------|---------------------------------------------|
| `hmi_main`               | HMI  | 10.10.3.10    | Operator display                            |
| `hex_turbine_controller` | PLC  | 10.10.3.21    | Turbine control logic                       |
| `ied_relay_a`            | IED  | 10.10.3.31    | Protective relay, Dolly Sisters feeder      |
| `ied_relay_b`            | IED  | 10.10.3.32    | Protective relay, Nap Hill feeder           |
| `ied_meter_main`         | IED  | 10.10.3.33    | Revenue meter                               |
| sensors                  | —    | 10.10.3.41–47 | RPM, temp, pressure, line voltages/currents |
| actuators                | —    | 10.10.3.51–54 | Throttle valve, governor, breakers A/B      |

All devices speak Modbus TCP with no authentication. Any host with control zone
network access can read and write registers.

A Hardware-in-the-Loop module (`turbine_hil.py`) simulates the physical process:
turbine RPM, temperature, pressure, line voltages and currents. Alarms and trips
are real consequences of register manipulation.

### OT/RTU network (`ics_wan`)

City RTUs distributed across Ankh-Morpork's distribution network. On `ics_wan`
because they were connected to public cellular IPs with no private APN and no VPN.

| Hostname        | Location                   | IP         |
|-----------------|----------------------------|------------|
| `rtu-dolly-1`   | Dolly Sisters Substation   | 10.10.4.10 |
| `rtu-naphill-1` | Nap Hill Feeder            | 10.10.4.20 |
| `rtu-tump-1`    | Tump Crossing Distribution | 10.10.4.30 |

Default vendor: `generic-rtu-v1`, Modbus TCP (502) and SNMP (161, community
`public`). No authentication on either protocol. Vendor is pluggable per entry
in `ctf-config.yaml`.

A misconfigured RTU that appears on `ics_internet` is a property of that RTU's
implementation, not a network-wide configuration flag.

## Configuration engine

`orchestrator/ctf-config.yaml` is the single source of truth for topology and
addressing. `orchestrator/generate.py` reads it and produces:

```
infrastructure/networks/docker-compose.yml
infrastructure/firewall.sh
infrastructure/jump-host/docker-compose.yml
infrastructure/jump-host/adversary-readme.txt
zones/enterprise/docker-compose.yml
zones/operational/docker-compose.yml
zones/field-devices/docker-compose.yml
zones/control/docker-compose.yml
start.sh
stop.sh
```

Vulnerabilities are properties of the simulated systems, baked into their
implementations. They are not configuration options. The config engine controls
what is deployed, topology, addressing, ICS process, RTU inventory, not how
vulnerable things are.

## Scale-out: Phase 2

When zones move to separate Hetzner instances, the shared Docker bridge networks
become WireGuard tunnels. Zone compose files do not change, only the Docker
network driver changes.
