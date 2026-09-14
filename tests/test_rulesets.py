# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
import pytest
from cmk.rulesets.v1.form_specs import validators
from cmk.rulesets.v1.rule_specs import HostCondition
from cmk_addons.plugins.nxos_stp_tcn.agent_based.cisco_nexus_stp import (
    check_plugin_nxos_stp_tcn as plugin,
)
from cmk_addons.plugins.nxos_stp_tcn.rulesets import check_parameters as cp
from cmk_addons.plugins.nxos_stp_tcn.rulesets import special_agent as sa


def test_forms_build() -> None:
    assert set(cp._check_form().elements) == {
        "crit_within",
        "warn_within",
        "rate_levels",
        "vlans",
        "state_vlan_error",
    }
    assert "privacy" in sa._form().elements


def test_rule_names_match_plugins() -> None:
    assert cp.rule_spec_nxos_stp_tcn_check.name == plugin.check_ruleset_name
    assert isinstance(cp.rule_spec_nxos_stp_tcn_check.condition, HostCondition)  # one service
    assert plugin.discovery_ruleset_name is None
    assert sa.rule_spec_nxos_stp_tcn_special_agent.name == "nxos_stp_tcn"


def test_defaults_match_the_plugin() -> None:
    form = cp._check_form().elements
    assert form["crit_within"].required
    assert form["crit_within"].parameter_form.prefill.value == 43200.0
    assert plugin.check_default_parameters["crit_within"] == 43200.0
    assert "warn_within" not in plugin.check_default_parameters  # WARN disabled by default
    assert form["state_vlan_error"].parameter_form.prefill.value == 3
    assert plugin.check_default_parameters["state_vlan_error"] == 3
    assert plugin.check_default_parameters["vlans"] == ("all", None)


def test_warn_must_be_longer_than_crit() -> None:
    cp._validate_windows({"crit_within": 43200.0})
    cp._validate_windows({"crit_within": 7200.0, "warn_within": 43200.0})
    with pytest.raises(validators.ValidationError):
        cp._validate_windows({"crit_within": 43200.0, "warn_within": 3600.0})


def test_vlan_spec_validation() -> None:
    cp._validate_vlan_spec("10, 20-30")
    with pytest.raises(validators.ValidationError):
        cp._validate_vlan_spec("10-x")
