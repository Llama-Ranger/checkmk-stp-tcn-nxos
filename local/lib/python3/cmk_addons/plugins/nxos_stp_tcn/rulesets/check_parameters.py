#!/usr/bin/env python3
# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Ruleset: thresholds and VLAN selection for the "STP Topology" service."""

from collections.abc import Mapping

from cmk.rulesets.v1 import Help, Message, Title
from cmk.rulesets.v1.form_specs import (
    CascadingSingleChoice,
    CascadingSingleChoiceElement,
    DefaultValue,
    DictElement,
    Dictionary,
    FixedValue,
    Float,
    LevelDirection,
    ServiceState,
    SimpleLevels,
    String,
    TimeMagnitude,
    TimeSpan,
    validators,
)
from cmk.rulesets.v1.rule_specs import CheckParameters, HostCondition, Topic
from cmk_addons.plugins.nxos_stp_tcn.lib.vlan_ranges import parse_vlan_ranges

_MAGNITUDES = [TimeMagnitude.DAY, TimeMagnitude.HOUR, TimeMagnitude.MINUTE]


def _validate_windows(value: Mapping[str, object]) -> None:
    warn, crit = value.get("warn_within"), value.get("crit_within")
    if isinstance(warn, int | float) and isinstance(crit, int | float) and warn <= crit:
        raise validators.ValidationError(
            Message("The warning window must be longer than the critical window.")
        )


def _validate_vlan_spec(value: str) -> None:
    try:
        parse_vlan_ranges(value)
    except ValueError as exc:
        raise validators.ValidationError(Message("%s") % str(exc)) from None


def _vlan_list(title: Title) -> String:
    return String(
        title=title,
        help_text=Help("Comma separated VLAN IDs and ranges, e.g. 10, 20-30, 200"),
        custom_validate=(_validate_vlan_spec,),
    )


def _check_form() -> Dictionary:
    return Dictionary(
        help_text=Help(
            "One service per switch shows all VLANs. It alerts when the most recent "
            "spanning-tree topology change of any VLAN happened recently and names the "
            "affected VLANs. VLANs that never had a topology change are always OK."
        ),
        custom_validate=(_validate_windows,),
        elements={
            "crit_within": DictElement(
                required=True,
                parameter_form=TimeSpan(
                    title=Title("Critical if the last topology change of a VLAN was within"),
                    help_text=Help("Default: 12 hours (same as the legacy check)."),
                    displayed_magnitudes=_MAGNITUDES,
                    prefill=DefaultValue(43200.0),
                    custom_validate=(validators.NumberInRange(min_value=60.0),),
                ),
            ),
            "warn_within": DictElement(
                parameter_form=TimeSpan(
                    title=Title("Warning if the last topology change of a VLAN was within"),
                    help_text=Help(
                        "Optional. Must be longer than the critical window; e.g. critical "
                        "within 12 hours, warning within 24 hours. Not set: no warning state."
                    ),
                    displayed_magnitudes=_MAGNITUDES,
                    prefill=DefaultValue(86400.0),
                    custom_validate=(validators.NumberInRange(min_value=60.0),),
                ),
            ),
            "rate_levels": DictElement(
                parameter_form=SimpleLevels(
                    title=Title("Upper levels on the topology change rate of a VLAN"),
                    help_text=Help(
                        "Changes per hour of each VLAN, averaged over one check interval. A "
                        "counter that goes down (reboot, counter wrap) produces no rate for "
                        "that interval."
                    ),
                    form_spec_template=Float(unit_symbol="changes/h"),
                    level_direction=LevelDirection.UPPER,
                    prefill_fixed_levels=DefaultValue((6.0, 30.0)),
                ),
            ),
            "vlans": DictElement(
                parameter_form=CascadingSingleChoice(
                    title=Title("VLANs to monitor"),
                    help_text=Help("Default: all VLANs that have spanning-tree data."),
                    prefill=DefaultValue("all"),
                    elements=[
                        CascadingSingleChoiceElement(
                            name="all",
                            title=Title("All VLANs that have spanning-tree data"),
                            parameter_form=FixedValue(value=None),
                        ),
                        CascadingSingleChoiceElement(
                            name="include",
                            title=Title("Only these VLANs"),
                            parameter_form=_vlan_list(Title("VLAN IDs")),
                        ),
                        CascadingSingleChoiceElement(
                            name="exclude",
                            title=Title("All VLANs except these"),
                            parameter_form=_vlan_list(Title("VLAN IDs")),
                        ),
                    ],
                ),
            ),
            "state_vlan_error": DictElement(
                parameter_form=ServiceState(
                    title=Title("State if a VLAN cannot be queried"),
                    help_text=Help(
                        "A VLAN whose SNMP context does not answer (e.g. deleted since the "
                        "last check) is listed with this state. All other VLANs are still "
                        "evaluated."
                    ),
                    prefill=DefaultValue(ServiceState.UNKNOWN),
                ),
            ),
        },
    )


rule_spec_nxos_stp_tcn_check = CheckParameters(
    name="nxos_stp_tcn",
    title=Title("Cisco Nexus STP topology changes"),
    topic=Topic.NETWORKING,
    parameter_form=_check_form,
    condition=HostCondition(),
)
