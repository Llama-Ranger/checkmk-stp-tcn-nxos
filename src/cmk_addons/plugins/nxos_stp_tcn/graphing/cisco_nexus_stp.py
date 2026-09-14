#!/usr/bin/env python3
"""Metrics, graphs and perfometer for "STP Topology VLAN <id>" services."""

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

metric_stp_seconds_since_last_change = Metric(
    name="stp_seconds_since_last_change",
    title=Title("Time since last STP topology change"),
    unit=Unit(TimeNotation()),
    color=Color.GREEN,
)

metric_stp_topology_changes_total = Metric(
    name="stp_topology_changes_total",
    title=Title("STP topology changes (cumulative)"),
    unit=Unit(DecimalNotation(""), StrictPrecision(0)),
    color=Color.BLUE,
)

metric_stp_topology_changes_rate = Metric(
    name="stp_topology_changes_rate",
    title=Title("STP topology change rate"),
    unit=Unit(DecimalNotation("/h"), AutoPrecision(2)),
    color=Color.ORANGE,
)

graph_stp_time_since_last_change = Graph(
    name="stp_time_since_last_change",
    title=Title("Time since last STP topology change"),
    simple_lines=["stp_seconds_since_last_change"],
    minimal_range=MinimalRange(0, 86400),
)

graph_stp_topology_change_activity = Graph(
    name="stp_topology_change_activity",
    title=Title("STP topology change activity"),
    compound_lines=["stp_topology_changes_rate"],
    minimal_range=MinimalRange(0, 1),
)

graph_stp_topology_changes_total = Graph(
    name="stp_topology_changes_total",
    title=Title("STP topology changes (cumulative)"),
    simple_lines=["stp_topology_changes_total"],
)

perfometer_stp_seconds_since_last_change = Perfometer(
    name="stp_seconds_since_last_change",
    focus_range=FocusRange(Closed(0), Open(7 * 86400)),
    segments=["stp_seconds_since_last_change"],
)
