#!/usr/bin/env python3
# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Per-VLAN metric names, shared by the check plug-in and the graphing definitions."""

from cmk_addons.plugins.nxos_stp_tcn.lib.vlan_ranges import VLAN_MAX, VLAN_MIN

VLAN_IDS = range(VLAN_MIN, VLAN_MAX + 1)


def vlan_age_metric(vlan: int) -> str:
    """Metric name for the time since the last topology change of one VLAN."""
    return f"stp_vlan_{vlan}_seconds_since_last_change"
