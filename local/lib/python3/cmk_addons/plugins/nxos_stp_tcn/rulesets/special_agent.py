#!/usr/bin/env python3
# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Ruleset: enable the Cisco Nexus STP special agent on selected hosts."""

from cmk.rulesets.v1 import Help, Title
from cmk.rulesets.v1.form_specs import (
    CascadingSingleChoice,
    CascadingSingleChoiceElement,
    DefaultValue,
    DictElement,
    Dictionary,
    FixedValue,
    Integer,
    Password,
    SingleChoice,
    SingleChoiceElement,
    String,
    validators,
)
from cmk.rulesets.v1.rule_specs import SpecialAgent, Topic

_AUTH_PROTOCOLS = [
    ("md5", "MD5"),
    ("sha", "SHA-1"),
    ("sha224", "SHA-224"),
    ("sha256", "SHA-256"),
    ("sha384", "SHA-384"),
    ("sha512", "SHA-512"),
]
_PRIV_PROTOCOLS = [
    ("des", "DES"),
    ("aes", "AES-128"),
    ("aes192", "AES-192"),
    ("aes256", "AES-256"),
    ("aes192c", "AES-192 (Cisco key extension)"),
    ("aes256c", "AES-256 (Cisco key extension)"),
]


def _choice(title: Title, options: list[tuple[str, str]], default: str) -> SingleChoice:
    return SingleChoice(
        title=title,
        elements=[SingleChoiceElement(name=name, title=Title(label)) for name, label in options],
        prefill=DefaultValue(default),
    )


def _form() -> Dictionary:
    return Dictionary(
        help_text=Help(
            "Monitors spanning-tree topology changes per VLAN on Cisco Nexus (NX-OS) switches. "
            "VLANs are discovered from CISCO-CONTEXT-MAPPING-MIB and queried through their "
            "numeric SNMPv3 contexts. Checkmk cannot pass a host's SNMP credentials to a "
            "special agent, so the SNMPv3 settings are configured here; store the passphrases "
            "in the password store. The hosts need the setting 'Configured API integrations, "
            "no Checkmk agent' (their SNMP checks keep running)."
        ),
        elements={
            "user": DictElement(
                required=True,
                parameter_form=String(
                    title=Title("SNMPv3 security name (user)"),
                    custom_validate=(validators.LengthInRange(min_value=1),),
                ),
            ),
            "auth_protocol": DictElement(
                required=True,
                parameter_form=_choice(Title("Authentication protocol"), _AUTH_PROTOCOLS, "sha"),
            ),
            "auth_password": DictElement(
                required=True,
                parameter_form=Password(title=Title("Authentication passphrase")),
            ),
            "privacy": DictElement(
                required=True,
                parameter_form=CascadingSingleChoice(
                    title=Title("Security level"),
                    prefill=DefaultValue("auth_priv"),
                    elements=[
                        CascadingSingleChoiceElement(
                            name="auth_priv",
                            title=Title("authPriv: authentication and encryption"),
                            parameter_form=Dictionary(
                                elements={
                                    "priv_protocol": DictElement(
                                        required=True,
                                        parameter_form=_choice(
                                            Title("Privacy protocol"), _PRIV_PROTOCOLS, "aes"
                                        ),
                                    ),
                                    "priv_password": DictElement(
                                        required=True,
                                        parameter_form=Password(title=Title("Privacy passphrase")),
                                    ),
                                },
                            ),
                        ),
                        CascadingSingleChoiceElement(
                            name="auth_no_priv",
                            title=Title("authNoPriv: authentication only"),
                            parameter_form=FixedValue(value=None),
                        ),
                    ],
                ),
            ),
            "port": DictElement(
                parameter_form=Integer(
                    title=Title("SNMP port"),
                    prefill=DefaultValue(161),
                    custom_validate=(validators.NetworkPort(),),
                ),
            ),
            "timeout": DictElement(
                parameter_form=Integer(
                    title=Title("Timeout per SNMP request"),
                    unit_symbol="s",
                    prefill=DefaultValue(2),
                    custom_validate=(validators.NumberInRange(min_value=1, max_value=30),),
                ),
            ),
            "retries": DictElement(
                parameter_form=Integer(
                    title=Title("Retries per SNMP request"),
                    prefill=DefaultValue(1),
                    custom_validate=(validators.NumberInRange(min_value=0, max_value=5),),
                ),
            ),
            "workers": DictElement(
                parameter_form=Integer(
                    title=Title("VLAN contexts queried in parallel"),
                    prefill=DefaultValue(4),
                    custom_validate=(validators.NumberInRange(min_value=1, max_value=16),),
                ),
            ),
        },
    )


rule_spec_nxos_stp_tcn_special_agent = SpecialAgent(
    name="nxos_stp_tcn",
    title=Title("Cisco Nexus STP topology changes (SNMPv3 VLAN contexts)"),
    topic=Topic.NETWORKING,
    parameter_form=_form,
)
