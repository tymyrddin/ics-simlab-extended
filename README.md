# ICS-SimLab

A three-zone Industrial Control System simulation built for realistic red team exercises and making PoC's. The
environment models the operational infrastructure of a fictional utility, complete with legacy equipment, accumulated
technical debt, and the kind of security posture that develops when a system works and nobody wants to touch it.

Three network zones (enterprise, operational, control) are separated by deliberate, exploitable boundaries.
Vulnerabilities are properties of the simulated systems, not configuration options. Consequences (operational,
reputational, procedural) emerge from what players actually do.

The simulation is configured through a top-level YAML file that selects the network topology and component variants. 
A code generator produces Docker Compose stacks for each zone from this configuration. The control
zone runs an IED network: protective relays, revenue meters, a Hex Steam Turbine controller. The enterprise and
operational zones are purpose-built containers running realistic service stacks. The whole environment runs on a
single host and is designed to scale to zone-per-host when needed.

## Dependencies

**Platform: Linux only (for now).** Docker's custom bridge networking with fixed IP addresses and inter-container
routing works correctly on Linux. On macOS and Windows, Docker runs containers inside a VM; the networking model
differs and the zone topology will not behave as designed.

| Dependency     | Version     | Notes                                                      |
|----------------|-------------|------------------------------------------------------------|
| Linux          | kernel 5.x+ | Ubuntu 22.04 / Debian 12 tested                            |
| Docker Engine  | 24+         | Not Docker Desktop                                         |
| Docker Compose | v2.20+      | Plugin (`docker compose`), not standalone `docker-compose` |
| Python         | 3.10+       | For the orchestrator                                       |
| PyYAML         | any recent  | `pip install pyyaml` or `apt install python3-yaml`         |

The orchestrator (`orchestrator/generate.py`) and the upstream Curtin ICS-SimLab generator (`curtin-ics-simlab/main.py`)
must both be runnable with `python3`. No other Python packages are required on the host; everything else runs inside containers.

## Hardware

The full environment runs approximately 20 containers simultaneously (enterprise: 2, operational: 3, control zone: 9, jump host: 1, network init: 1).

| Resource | Minimum    | Recommended |
|----------|------------|-------------|
| RAM      | 4 GB       | 8 GB        |
| CPU      | 2 cores    | 4 cores     |
| Disk     | 10 GB free | 20 GB free  |
| Network  | single NIC | single NIC  |

A Hetzner CX32 (4 vCPU / 8 GB) or equivalent runs the full stack comfortably. The architecture is designed to
split to zone-per-host via WireGuard mesh in a later phase if needed.

## Running the whole system

### First run

```bash
# 1. Generate all compose files and scripts from the config
make generate

# 2. Build all Docker images (slow the first time; cached thereafter)
make build
make build-jump-host

# 3. Bring up all zones and the jump host
make up

# 4. Apply inter-zone firewall rules (separate step: see below)
make firewall
```

`make up` runs `generate` first automatically, so after the first image build you can just:

```bash
make up
make firewall
```

### Stopping

```bash
make down      # stop and remove all containers (jump host first, then zones, then networks)
```

To pause without removing containers:

```bash
make stop      # stop containers, keep them (no generate dependency)
make start     # restart stopped containers (no generate dependency)
```

### Clean-up

```bash
make clean     # down + remove all generated files (compose files, start.sh, stop.sh)
make purge     # clean + remove all images (useful for a full reset on Hetzner)
```

### Using an alternate config

```bash
CONFIG=path/to/other-config.yaml make generate
```

### Available make commands

| Target                 | Description                                                        |
|------------------------|--------------------------------------------------------------------|
| `make generate`        | Read `ctf-config.yaml`, write all docker-compose files and scripts |
| `make build`           | Build all zone Docker images (runs generate first)                 |
| `make build-jump-host` | Build the jump host image (runs generate first)                    |
| `make up`              | Generate + start all zones and jump host                           |
| `make down`            | Stop and remove all containers and networks                        |
| `make stop`            | Stop containers without removing them (no generate dependency)     |
| `make start`           | Restart stopped containers (no generate dependency)                |
| `make firewall`        | Apply inter-zone iptables rules (`sudo` required)                  |
| `make deploy`          | Alias for `make up`                                                |
| `make start-jump-host` | Start the jump host container only                                 |
| `make stop-jump-host`  | Stop and remove the jump host container only                       |
| `make clean`           | `down` + remove all generated files                                |
| `make purge`           | `clean` + remove all Docker images                                 |

## Running zones individually

All compose files are generated by `make generate` (or `python3 orchestrator/generate.py`) and written to their zone
directories. The shared networks must be up before any zone stack starts.

```bash
# Generate compose files first (required)
python3 orchestrator/generate.py

# 1. Shared networks: always start this first
docker compose -f infrastructure/networks/docker-compose.yml up -d

# Enterprise zone only
docker compose -f zones/enterprise/docker-compose.yml up -d

# Operational zone only
docker compose -f zones/operational/docker-compose.yml up -d

# Control zone only
docker compose -f zones/control/docker-compose.yml up -d
```

Zones can be stopped individually without affecting the others:

```bash
docker compose -f zones/operational/docker-compose.yml down
```

Tear down the shared networks last, after all zone stacks are down:

```bash
docker compose -f infrastructure/networks/docker-compose.yml down
```

## Inter-zone firewall

`infrastructure/firewall.sh` applies iptables rules to the host's `DOCKER-USER` chain after all zones are up. This chain intercepts all traffic routed between Docker bridge networks and enforces the intended inter-zone policy. Intra-zone traffic (same bridge) is unaffected.

**Requires root.** Run `make firewall` as a separate step after `make up`:

```bash
make up
make firewall    # writes iptables rules to DOCKER-USER
```

On Hetzner, `setup.sh` adds a sudoers rule that allows the deploy user to run only the specific iptables commands used by `firewall.sh` without a full root shell. On a local dev machine, skip `make firewall` if you don't need inter-zone isolation: zones still come up and are reachable directly via Docker bridge IPs.

The rules are generated from `ctf-config.yaml` and written to `infrastructure/firewall.sh`. The allowed paths are:

| Source                  | Destination             | Protocol | Reason                  |
|-------------------------|-------------------------|----------|-------------------------|
| Enterprise              | Historian               | TCP/8080 | historian web interface |
| Enterprise              | SCADA server            | TCP/8080 | SCADA web interface     |
| Enterprise              | Engineering-workstation | TCP/22   | SSH pivot point         |
| Engineering-workstation | Control zone            | TCP/502  | Modbus to PLCs and IEDs |

Everything else between zones is dropped. The internet network is isolated from internal zones: the jump host bridges them via dual-homing, not routing. The control zone does not initiate outbound connections.

`make down` runs `stop.sh`, which flushes `DOCKER-USER` back to a bare `RETURN` rule on teardown, restoring Docker's default inter-network isolation.

## Control zone device map

The control zone IED network topology is defined in `ctf-config.yaml` under `control_zone.devices`
and patched into `zones/control/config/uupl_ied/configuration.json` by `generate.py` before
ICS-SimLab runs. `ctf-config.yaml` is the single source of truth for all network addressing.

| Device                  | Type                       | IP         |
|-------------------------|----------------------------|------------|
| `hmi_main`              | HMI                        | 10.10.3.10 |
| `turbine_plc`           | PLC                        | 10.10.3.21 |
| `ied_relay_a`           | IED — Dolly Sisters feeder | 10.10.3.31 |
| `ied_relay_b`           | IED — Nap Hill feeder      | 10.10.3.32 |
| `ied_meter_main`        | IED — revenue meter        | 10.10.3.33 |
| `actuator_fuel_valve`   | Actuator                   | 10.10.3.51 |
| `actuator_cooling_pump` | Actuator                   | 10.10.3.52 |
| `actuator_breaker_a`    | Actuator                   | 10.10.3.53 |
| `actuator_breaker_b`    | Actuator                   | 10.10.3.54 |

Sensors are Modbus registers on the PLC, not separate containers.

To change device addressing: edit `ctf-config.yaml` under `control_zone.devices`, then run `make generate`.
The generator patches `configuration.json` and passes it to ICS-SimLab. Register maps, logic files
(`turbine_plc.py`, `relay_logic.py`, `meter_logic.py`), and physics (`turbine_hil.py`) stay in
`zones/control/config/uupl_ied/` and are not regenerated.

The engineering workstation (`ctrl_ip: 10.10.3.100`) is managed by `operational_zone` and does not
appear in the control zone device list.

## Hetzner deployment

The jump host is the sole public entry point into the simulation. It runs as a container on the Hetzner host.
The host's own sshd moves to port 2222; the jump host container claims port 22.

**One-time host preparation** (run once on a fresh Hetzner instance as root):

```bash
bash infrastructure/jump-host/setup.sh
```

This moves the host sshd to port 2222. After that, reconnect on port 2222 for all host administration.

**Add adversary public keys** before building:

```bash
cp infrastructure/jump-host/adversary-keys.example infrastructure/jump-host/adversary-keys
# Edit adversary-keys: one line per adversary: username pubkey [comment]
# Valid usernames: moist teatime carrot angua vimes
```

**Build and deploy**:

```bash
make generate
make build
make build-jump-host
make up
make firewall
```

For local development, set `ssh_host_port: 2222` in `ctf-config.yaml` under `jump_host` (it is already the default).
This binds the jump host container to port 2222 on the host, avoiding conflict with the host's own sshd on port 22.
On Hetzner, change it to `22`: `setup.sh` already moves the host sshd to port 2222.

**Adversary access** (Hetzner, `ssh_host_port: 22`):

```
ssh moist@<hetzner-ip>    # port 22, key auth only
```

**Local dev access** (`ssh_host_port: 2222`):

```
ssh moist@localhost -p 2222
```

Each adversary lands as their named user in the jump host container. A README in their home directory tells them
what network lies beyond. No credentials are stored in the container: keys are mounted at runtime from the
gitignored `adversary-keys` file.

## Testing

Three test levels; each can be run independently.

### Unit tests: no Docker required

Tests the orchestrator generator functions in isolation:

```bash
pip install -r tests/requirements.txt
make test-unit
# or: pytest tests/unit/ -v
```

### Artefact tests: no Docker required

Runs `generate.py`, then verifies all nine output files exist, parse as valid YAML, and contain expected IPs:

```bash
make test-artifacts
# or: make generate && pytest tests/integration/ -v
```

### Smoke tests: Docker required

Starts real containers and checks network topology, service ports, and inter-zone routing:

```bash
make build          # build images first (once)
make test-smoke     # runs all tests/smoke/test_*.sh scripts
```

The firewall test requires root (it writes iptables rules):

```bash
make test-firewall
# or: sudo bash tests/smoke/test_firewall.sh
```

### Run everything

```bash
make test           # unit + artifacts + smoke (no firewall)
```

## Configuration

Edit `orchestrator/ctf-config.yaml` to change the network topology, IP addressing, component variants, or ICS process. 
Run `make generate` (or `make up`) afterwards. The compose files are always regenerated from the config and should not 
be edited directly.

See [docs/architecture.md](docs/architecture.md) for the full system design.

## Thank you

This repository originally extended [Curtin ICS-SimLab](https://github.com/JaxsonBrownie/ICS-SimLab), a Docker-based ICS 
simulation framework developed at Curtin University and presented at the First International Workshop on Secure 
Industrial Control Systems and Industrial IoT (IEEE, 2025). The original work, by J. Brown, D. S. Pham, S. Soh, 
F. Motalebi, S. Eswaran, and M. Almashor, provides the control zone simulator, the Modbus TCP/RTU communication 
layer, and the Hardware-in-the-Loop physical process model that sits at the heart of this environment. None of that 
code has been modified. If you use the original ICS-SimLab in your own work, please cite their paper.

The control zone containers in this repository are purpose-built replacements: they add realistic vulnerabilities and 
Discworld-themed service stacks that the original framework was not designed for.
