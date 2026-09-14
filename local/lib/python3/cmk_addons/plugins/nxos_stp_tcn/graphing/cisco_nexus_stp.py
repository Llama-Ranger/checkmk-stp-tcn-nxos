#!/usr/bin/env python3
# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Metrics, graphs and perfometer for the "STP Topology" service.

Every VLAN has its own metric, ``stp_vlan_<id>_seconds_since_last_change``. Checkmk shows a
declared metric that belongs to no graph template as a graph of its own, so every VLAN gets one
graph. The definitions are generated for all valid VLAN IDs (1-4094) so each graph has a proper
title and time units; Checkmk collects them like any other ``metric_*`` module variable.
"""

from cmk.graphing.v1 import Title
from cmk.graphing.v1.graphs import Graph, MinimalRange
from cmk.graphing.v1.metrics import (
    AutoPrecision,
    Color,
    DecimalNotation,
    Metric,
    StrictPrecision,
    TimeNotation,
    Unit,
)
from cmk.graphing.v1.perfometers import Closed, FocusRange, Open, Perfometer
from cmk_addons.plugins.nxos_stp_tcn.lib.metric_names import VLAN_IDS, vlan_age_metric

_TIME = Unit(TimeNotation())

# --- one metric, and so one graph, per VLAN ----------------------------------------------------

for _vlan in VLAN_IDS:
    globals()[f"metric_{vlan_age_metric(_vlan)}"] = Metric(
        name=vlan_age_metric(_vlan),
        title=Title("VLAN %s: time since last STP topology change") % str(_vlan),
        unit=_TIME,
        color=Color.GREEN,
    )
del _vlan

# --- switch-wide metrics -------------------------------------------------------------------------

metric_stp_seconds_since_last_change = Metric(
    name="stp_seconds_since_last_change",
    title=Title("Time since last STP topology change (any VLAN)"),
    unit=_TIME,
    color=Color.GREEN,
)

metric_stp_topology_changes_total = Metric(
    name="stp_topology_changes_total",
    title=Title("STP topology changes (all VLANs, cumulative)"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.BLUE,
)

metric_stp_topology_changes_rate = Metric(
    name="stp_topology_changes_rate",
    title=Title("STP topology change rate (all VLANs)"),
    unit=Unit(DecimalNotation("/h"), AutoPrecision(2)),
    color=Color.ORANGE,
)

graph_stp_time_since_last_change = Graph(
    name="stp_time_since_last_change",
    title=Title("Time since last STP topology change (any VLAN)"),
    simple_lines=["stp_seconds_since_last_change"],
    minimal_range=MinimalRange(0, 86400),
)

graph_stp_topology_change_activity = Graph(
    name="stp_topology_change_activity",
    title=Title("STP topology change activity (all VLANs)"),
    compound_lines=["stp_topology_changes_rate"],
    minimal_range=MinimalRange(0, 1),
)

graph_stp_topology_changes_total = Graph(
    name="stp_topology_changes_total",
    title=Title("STP topology changes (all VLANs, cumulative)"),
    simple_lines=["stp_topology_changes_total"],
)

perfometer_stp_seconds_since_last_change = Perfometer(
    name="stp_seconds_since_last_change",
    focus_range=FocusRange(Closed(0), Open(7 * 86400)),
    segments=["stp_seconds_since_last_change"],
)
