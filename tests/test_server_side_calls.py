# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
from cmk.server_side_calls.v1 import HostConfig, IPv4Config, Secret
from cmk_addons.plugins.nxos_stp_tcn.server_side_calls.special_agent import (
    special_agent_nxos_stp_tcn as config,
)

from .conftest import PLUGIN_DIR

HOST = HostConfig(name="switch-test", ipv4_config=IPv4Config(address="192.0.2.10"))
AUTH, PRIV = Secret(1), Secret(2)
RAW = {
    "user": "monitor",
    "auth_protocol": "sha",
    "auth_password": AUTH,
    "privacy": ("auth_priv", {"priv_protocol": "aes", "priv_password": PRIV}),
}


def args_of(raw: dict[str, object]) -> list[object]:
    (command,) = list(config(raw, HOST))
    return list(command.command_arguments)


def test_executable_name_matches() -> None:
    assert (PLUGIN_DIR / "libexec" / f"agent_{config.name}").is_file()


def test_auth_priv_command_passes_secrets_by_reference() -> None:
    args = args_of(RAW)
    assert args[args.index("--host") + 1] == "192.0.2.10"
    assert args[args.index("--auth-password-id") + 1] is AUTH
    assert args[args.index("--priv-password-id") + 1] is PRIV
    assert args[args.index("--security-level") + 1] == "authPriv"
    assert args[args.index("--port") + 1] == "161"
    assert all(isinstance(a, str) for a in args if a not in (AUTH, PRIV))


def test_auth_no_priv() -> None:
    args = args_of({**RAW, "privacy": ("auth_no_priv", None), "timeout": 5})
    assert args[args.index("--security-level") + 1] == "authNoPriv"
    assert "--priv-password-id" not in args
    assert args[args.index("--timeout") + 1] == "5"


def test_cache_age_is_passed_only_when_configured() -> None:
    assert "--cache-age" not in args_of(RAW)
    args = args_of({**RAW, "cache_age": 3600.0})
    assert args[args.index("--cache-age") + 1] == "3600"
