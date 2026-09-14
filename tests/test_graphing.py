# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
from cmk.graphing.v1 import entry_point_prefixes
from cmk.graphing.v1.graphs import Graph
from cmk.graphing.v1.metrics import Metric
from cmk_addons.plugins.nxos_stp_tcn.graphing import cisco_nexus_stp as graphing
from cmk_addons.plugins.nxos_stp_tcn.lib.metric_names import vlan_age_metric

from .conftest import PLUGIN_DIR

SWITCH_WIDE = {
    "stp_seconds_since_last_change",
    "stp_topology_changes_total",
    "stp_topology_changes_rate",
}


def _objects(kind: type) -> list:
    return [v for v in vars(graphing).values() if isinstance(v, kind)]


def test_one_metric_is_declared_per_vlan_id() -> None:
    names = {m.name for m in _objects(Metric)}
    per_vlan = {vlan_age_metric(v) for v in range(1, 4095)}
    assert len(per_vlan) == 4094
    assert names == per_vlan | SWITCH_WIDE


def test_generated_metrics_are_found_by_checkmk() -> None:
    """Checkmk collects module variables whose names carry the metric_ prefix."""
    prefix = entry_point_prefixes()[Metric]
    for vid in (1, 200, 4094):
        metric = vars(graphing)[f"{prefix}{vlan_age_metric(vid)}"]
        assert metric.name == vlan_age_metric(vid)
        assert (
            metric.title.localize(lambda s: s) == f"VLAN {vid}: time since last STP topology change"
        )
    assert all(
        name.startswith(prefix)
        for name, value in vars(graphing).items()
        if isinstance(value, Metric)
    )


def test_switch_wide_metrics_are_used_by_the_check() -> None:
    check_source = (PLUGIN_DIR / "agent_based" / "cisco_nexus_stp.py").read_text()
    assert all(f'"{name}"' in check_source for name in SWITCH_WIDE)


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
        "discovery:",
    ):
        assert key in text
