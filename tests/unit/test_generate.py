"""Unit tests for orchestrator/generate.py.

No Docker. No subprocess calls. Tests each generator function in isolation
using the real ctf-config.yaml.
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))

import generate as gen  # noqa: E402

CONFIG_PATH = REPO_ROOT / "orchestrator" / "ctf-config.yaml"


@pytest.fixture(scope="module")
def config():
    return gen.load_config(CONFIG_PATH)


@pytest.fixture(scope="module")
def enterprise_output_path():
    return REPO_ROOT / "zones" / "enterprise" / "docker-compose.yml"


@pytest.fixture(scope="module")
def operational_output_path():
    return REPO_ROOT / "zones" / "operational" / "docker-compose.yml"


@pytest.fixture(scope="module")
def jump_host_output_path():
    return REPO_ROOT / "infrastructure" / "jump-host" / "docker-compose.yml"


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def test_render_templates(config):
    """Known placeholders resolve; unknown placeholders are left intact."""
    text = "subnet={{ networks.control.subnet }} unknown={{ no.such.key }}"
    result = gen._render_templates(text, config)

    expected_subnet = config["networks"]["control"]["subnet"]
    assert expected_subnet in result, "control subnet should be resolved"
    assert "{{ no.such.key }}" in result, "unresolved placeholders should be preserved"
    assert "{{ networks.control.subnet }}" not in result, "resolved placeholder should not remain"


# ---------------------------------------------------------------------------
# Networks compose
# ---------------------------------------------------------------------------

def test_generate_networks_compose(config):
    """Four networks with correct docker_name keys and IPAM subnets."""
    compose = gen.generate_networks_compose(config)

    networks = compose["networks"]
    assert len(networks) == 5, "expected 5 networks"

    for key, net_cfg in config["networks"].items():
        docker_name = net_cfg["docker_name"]
        subnet = net_cfg["subnet"]
        assert docker_name in networks, f"network {docker_name!r} missing"
        ipam_subnets = [
            c["subnet"]
            for c in networks[docker_name].get("ipam", {}).get("config", [])
        ]
        assert subnet in ipam_subnets, f"subnet {subnet} not in IPAM for {docker_name}"


# ---------------------------------------------------------------------------
# Enterprise compose
# ---------------------------------------------------------------------------

def test_generate_enterprise_compose(config, enterprise_output_path):
    """Legacy workstation on enterprise only; enterprise-workstation dual-homed."""
    compose = gen.generate_enterprise_compose(config, enterprise_output_path)
    services = compose["services"]

    ent_net = gen._net(config, "enterprise")
    ops_net = gen._net(config, "operational")
    lw_ip = config["enterprise_zone"]["legacy_workstation"]["ip"]
    ew_ip = config["enterprise_zone"]["enterprise_workstation"]["ip"]
    ew_ops_ip = config["enterprise_zone"]["enterprise_workstation"]["ops_ip"]

    # Legacy workstation — enterprise only
    assert "legacy-workstation" in services
    lw = services["legacy-workstation"]
    assert ent_net in lw["networks"], "legacy-workstation should be on enterprise network"
    assert ops_net not in lw["networks"], "legacy-workstation should not be on ops network"
    assert lw["networks"][ent_net]["ipv4_address"] == lw_ip

    # Enterprise workstation — dual-homed
    assert "enterprise-workstation" in services
    ew = services["enterprise-workstation"]
    assert ent_net in ew["networks"], "enterprise-workstation missing enterprise network"
    assert ops_net in ew["networks"], "enterprise-workstation missing operational network"
    assert ew["networks"][ent_net]["ipv4_address"] == ew_ip
    assert ew["networks"][ops_net]["ipv4_address"] == ew_ops_ip


# ---------------------------------------------------------------------------
# Operational compose
# ---------------------------------------------------------------------------

def test_generate_operational_compose(config, operational_output_path):
    """Historian/SCADA on ops only; engineering-workstation dual-homed to control."""
    compose = gen.generate_operational_compose(config, operational_output_path)
    services = compose["services"]

    ops_net = gen._net(config, "operational")
    ctrl_net = gen._net(config, "control")
    hist_ip = config["operational_zone"]["historian"]["ip"]
    scada_ip = config["operational_zone"]["scada_server"]["ip"]
    eng_ip = config["operational_zone"]["engineering_workstation"]["ip"]
    eng_ctrl_ip = config["operational_zone"]["engineering_workstation"]["ctrl_ip"]

    # Historian — ops only
    assert "historian" in services
    hist = services["historian"]
    assert ops_net in hist["networks"]
    assert ctrl_net not in hist["networks"]
    assert hist["networks"][ops_net]["ipv4_address"] == hist_ip

    # SCADA — ops only
    assert "scada-server" in services
    scada = services["scada-server"]
    assert ops_net in scada["networks"]
    assert ctrl_net not in scada["networks"]
    assert scada["networks"][ops_net]["ipv4_address"] == scada_ip

    # Eng workstation — dual-homed
    assert "engineering-workstation" in services
    eng = services["engineering-workstation"]
    assert ops_net in eng["networks"]
    assert ctrl_net in eng["networks"]
    assert eng["networks"][ops_net]["ipv4_address"] == eng_ip
    assert eng["networks"][ctrl_net]["ipv4_address"] == eng_ctrl_ip


# ---------------------------------------------------------------------------
# Firewall script
# ---------------------------------------------------------------------------

def test_generate_firewall_sh(config):
    """All zone subnets present; root-check and iptables flush present."""
    script = gen.generate_firewall_sh(config)

    for key in ("internet", "enterprise", "operational", "control", "wan"):
        subnet = config["networks"][key]["subnet"]
        assert subnet in script, f"subnet {subnet} ({key}) missing from firewall.sh"

    assert 'if [ "$EUID" -ne 0 ]' in script, "root check block missing"
    assert "iptables -F DOCKER-USER" in script, "iptables flush missing"
    assert "-A DOCKER-USER -j RETURN" in script, "final RETURN rule missing"


# ---------------------------------------------------------------------------
# Adversary README
# ---------------------------------------------------------------------------

def test_generate_adversary_readme(config):
    """All three placeholders resolved; no bare braces remain."""
    readme = gen.generate_adversary_readme(config)

    enterprise_subnet = config["networks"]["enterprise"]["subnet"]
    legacy_ip = config["enterprise_zone"]["legacy_workstation"]["ip"]
    ent_ws_ip = config["enterprise_zone"]["enterprise_workstation"]["ip"]

    assert enterprise_subnet in readme, "enterprise subnet not resolved in readme"
    assert legacy_ip in readme, "legacy workstation IP not resolved in readme"
    assert ent_ws_ip in readme, "enterprise workstation IP not resolved in readme"
    assert "{" not in readme, f"unresolved placeholder(s) remain in readme:\n{readme}"


# ---------------------------------------------------------------------------
# Jump host compose
# ---------------------------------------------------------------------------

def test_generate_jump_host_compose(config, jump_host_output_path):
    """Jump host: dual-homed internet+enterprise, correct IPs, port 22, both volume mounts."""
    compose = gen.generate_jump_host_compose(config, jump_host_output_path)
    services = compose["services"]

    assert "jump-host" in services
    jh = services["jump-host"]

    inet_net = gen._net(config, "internet")
    ent_net  = gen._net(config, "enterprise")
    jh_internet_ip = config["jump_host"]["internet_ip"]
    jh_ip          = config["jump_host"]["ip"]

    assert inet_net in jh["networks"], "jump-host missing internet network"
    assert jh["networks"][inet_net]["ipv4_address"] == jh_internet_ip
    assert ent_net in jh["networks"], "jump-host missing enterprise network"
    assert jh["networks"][ent_net]["ipv4_address"] == jh_ip
    assert "22:22" in jh["ports"], "jump-host should expose port 22"

    volumes_str = " ".join(jh.get("volumes", []))
    assert "adversary-keys" in volumes_str, "adversary-keys volume missing"
    assert "adversary-readme.txt" in volumes_str, "adversary-readme.txt volume missing"


