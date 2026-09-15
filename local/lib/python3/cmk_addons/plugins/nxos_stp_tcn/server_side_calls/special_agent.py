#!/usr/bin/env python3
# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Command line for the special agent agent_nxos_stp_tcn.

Passphrases are passed as Secret objects: Checkmk puts only "<id>:<password store file>"
on the command line, the agent resolves the value itself.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from cmk.server_side_calls.v1 import HostConfig, Secret, SpecialAgentCommand, SpecialAgentConfig


@dataclass(frozen=True)
class Params:
    user: str
    auth_protocol: str
    auth_password: Secret
    priv_protocol: str | None = None
    priv_password: Secret | None = None
    port: int = 161
    timeout: int = 2
    retries: int = 1
    workers: int = 4
    cache_age: int = 0  # 0: no cache, query the switch on every check


def parse_params(raw: Mapping[str, object]) -> Params:
    level, privacy = raw["privacy"]  # type: ignore[misc]
    priv_protocol = priv_password = None
    if level == "auth_priv" and isinstance(privacy, Mapping):
        priv_protocol = str(privacy["priv_protocol"])
        priv_password = privacy["priv_password"]
    return Params(
        user=str(raw["user"]),
        auth_protocol=str(raw["auth_protocol"]),
        auth_password=raw["auth_password"],  # type: ignore[arg-type]
        priv_protocol=priv_protocol,
        priv_password=priv_password,  # type: ignore[arg-type]
        port=int(raw.get("port", 161)),  # type: ignore[call-overload]
        timeout=int(raw.get("timeout", 2)),  # type: ignore[call-overload]
        retries=int(raw.get("retries", 1)),  # type: ignore[call-overload]
        workers=int(raw.get("workers", 4)),  # type: ignore[call-overload]
        # the form stores a TimeSpan in seconds
        cache_age=int(raw.get("cache_age", 0)),  # type: ignore[call-overload]
    )


def generate_commands(params: Params, host_config: HostConfig) -> Iterable[SpecialAgentCommand]:
    args: list[str | Secret] = [
        "--host", host_config.primary_ip_config.address,
        "--port", str(params.port),
        "--user", params.user,
        "--auth-protocol", params.auth_protocol,
        "--auth-password-id", params.auth_password,
        "--timeout", str(params.timeout),
        "--retries", str(params.retries),
        "--workers", str(params.workers),
    ]  # fmt: skip
    if params.cache_age > 0:
        args += ["--cache-age", str(params.cache_age)]
    if params.priv_protocol and params.priv_password is not None:
        args += [
            "--security-level", "authPriv",
            "--priv-protocol", params.priv_protocol,
            "--priv-password-id", params.priv_password,
        ]  # fmt: skip
    else:
        args += ["--security-level", "authNoPriv"]
    yield SpecialAgentCommand(command_arguments=args)


special_agent_nxos_stp_tcn = SpecialAgentConfig(
    name="nxos_stp_tcn",
    parameter_parser=parse_params,
    commands_function=generate_commands,
)
