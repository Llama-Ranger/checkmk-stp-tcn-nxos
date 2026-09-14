# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
from cmk.graphing.v1.graphs import Graph
from cmk.graphing.v1.metrics import Metric
from cmk_addons.plugins.nxos_stp_tcn.graphing import cisco_nexus_stp as graphing

from .conftest import PLUGIN_DIR


def _objects(kind: type) -> list:
    return [v for k, v in vars(graphing).items() if isinstance(v, kind)]


def test_metrics_used_by_the_check_are_defined() -> None:
    names = {m.name for m in _objects(Metric)}
    assert names == {
        "stp_seconds_since_last_change",
        "stp_topology_changes_total",
        "stp_topology_changes_rate",
    }
    check_source = (PLUGIN_DIR / "agent_based" / "cisco_nexus_stp.py").read_text()
    assert all(f'"{name}"' in check_source for name in names)


def test_graphs_reference_defined_metrics() -> None:
    names = {m.name for m in _objects(Metric)}
    for graph in _objects(Graph):
        assert set(graph.simple_lines) | set(graph.compound_lines) <= names


def test_checkman_present() -> None:
    text = (PLUGIN_DIR / "checkman" / "nxos_stp_tcn").read_text()
    for key in (
        "title:",
        "agents:",
        "catalog:",
        "license:",
        "distribution:",
        "description:",
        "item:",
        "discovery:",
    ):
        assert key in text
