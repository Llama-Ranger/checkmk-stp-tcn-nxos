# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check plugin tests. Values are taken from the real NX-OS 10.2(5) validation (see docs)."""

from collections.abc import Mapping, MutableMapping
from types import SimpleNamespace
from typing import Any

import pytest
from cmk.agent_based.v2 import Metric, Result, Service, State
from cmk_addons.plugins.nxos_stp_tcn.agent_based import cisco_nexus_stp as stp
from cmk_addons.plugins.nxos_stp_tcn.lib.metric_names import vlan_age_metric

DEFAULTS = stp.check_plugin_nxos_stp_tcn.check_default_parameters
HOUR = 3600
OLD = 2586624300  # ~299 days, in TimeTicks


def vlan(vid: int, changes: int, ticks: int) -> list[str]:
    return ["vlan", str(vid), "ok", str(changes), str(ticks)]


def section(*rows: list[str]) -> stp.Section:
    parsed = stp.parse_nxos_stp_tcn([["sysuptime", "2590160436"], *rows])
    assert parsed is not None
    return parsed


QUIET = section(vlan(1, 6, 2586192400), vlan(10, 0, 20000), vlan(200, 37, OLD))


def run(
    sect: stp.Section,
    params: Mapping[str, Any] | None = None,
    store: MutableMapping[str, Any] | None = None,
    now: float = 1_000_000.0,
) -> list[Result | Metric]:
    return list(
        stp._check({**DEFAULTS, **(params or {})}, sect, {} if store is None else store, now)
    )


def worst(results: list[Result | Metric]) -> State:
    return State.worst(*(r.state for r in results if isinstance(r, Result)))


def summary(results: list[Result | Metric]) -> str:
    return ", ".join(r.summary for r in results if isinstance(r, Result) and r.summary)


def details(results: list[Result | Metric]) -> list[str]:
    return [r.details for r in results if isinstance(r, Result)]


def metrics(results: list[Result | Metric]) -> dict[str, float]:
    return {m.name: m.value for m in results if isinstance(m, Metric)}


# --- parsing ---------------------------------------------------------------------------------


def test_parse() -> None:
    parsed = section(vlan(200, 37, OLD), ["vlan", "30", "timeout", "", ""])
    assert parsed.sysuptime == 25901604.36
    assert parsed.vlans["200"] == stp.VlanStp("ok", 37, 25866243.0)
    assert parsed.vlans["30"].status == "timeout"


def test_parse_malformed_rows_do_not_crash() -> None:
    parsed = stp.parse_nxos_stp_tcn(
        [
            [],
            ["garbage"],
            ["vlan", "abc", "ok", "1", "2"],
            ["vlan", "5", "ok", "x", "100"],
            ["vlan", "6", "ok", "-1", "100"],
            ["vlan", "7", "ok"],
            ["sysuptime", "not-a-number"],
        ]
    )
    assert parsed is not None
    assert set(parsed.vlans) == {"5", "6", "7"}
    assert {v.status for v in parsed.vlans.values()} == {"invalid"}
    assert parsed.sysuptime is None


def test_parse_empty() -> None:
    assert stp.parse_nxos_stp_tcn([]) is None


# --- discovery -------------------------------------------------------------------------------


def test_one_service_per_switch() -> None:
    assert list(stp.discover_nxos_stp_tcn(QUIET)) == [Service()]
    assert stp.check_plugin_nxos_stp_tcn.service_name == "STP Topology"


def test_no_service_without_spanning_tree_data() -> None:
    no_data = section(["vlan", "30", "timeout", "", ""], ["vlan", "99", "nosuch", "", ""])
    assert list(stp.discover_nxos_stp_tcn(no_data)) == []


# --- all VLANs in one service ----------------------------------------------------------------


def test_quiet_switch_is_ok_and_names_the_most_recent_change() -> None:
    results = run(QUIET)
    assert worst(results) is State.OK
    assert summary(results).startswith("3 VLANs, no recent topology change, most recent: VLAN 1 ")


def test_one_metric_and_graph_per_vlan() -> None:
    values = metrics(run(QUIET))
    assert values[vlan_age_metric(1)] == 25861924.0
    assert values[vlan_age_metric(10)] == 200.0
    assert values[vlan_age_metric(200)] == 25866243.0
    assert values["stp_topology_changes_total"] == 43
    assert values["stp_seconds_since_last_change"] == 25861924.0  # most recent change, any VLAN


def test_every_vlan_is_listed_in_the_details() -> None:
    lines = details(run(QUIET))
    assert any(
        line.startswith("VLAN 1: 6 topology changes, last change 299 days") for line in lines
    )
    assert any(
        line.startswith("VLAN 10: no topology change since spanning tree started") for line in lines
    )
    assert any(line.startswith("VLAN 200: 37 topology changes") for line in lines)


def test_singular_wording_for_one_change() -> None:
    lines = details(run(section(vlan(30, 1, OLD))))
    assert any(line.startswith("VLAN 30: 1 topology change, last change") for line in lines)


def test_recent_change_is_crit_and_named_in_the_summary() -> None:
    results = run(section(vlan(1, 6, 2586192400), vlan(300, 120, 1_000_000)))  # 2 h 46 min
    assert worst(results) is State.CRIT
    assert summary(results).startswith("1 of 2 VLANs: VLAN 300 changed 2 hours 46 minutes ago")
    assert any(
        "VLAN 300:" in line and "CRIT: topology change within the last 12 hours" in line
        for line in details(results)
    )
    assert any("switch uptime then" in line for line in details(results))


def test_warn_disabled_by_default() -> None:
    assert worst(run(section(vlan(400, 15, 20 * HOUR * 100)))) is State.OK  # 20 h ago


def test_warn_window() -> None:
    assert (
        worst(run(section(vlan(400, 15, 20 * HOUR * 100)), {"warn_within": 24.0 * HOUR}))
        is State.WARN
    )


def test_override_crit_2h_warn_12h() -> None:
    params = {"crit_within": 2.0 * HOUR, "warn_within": 12.0 * HOUR}
    assert worst(run(section(vlan(300, 120, 1_000_000)), params)) is State.WARN  # 2 h 46 min
    assert worst(run(section(vlan(400, 15, 20 * HOUR * 100)), params)) is State.OK  # 20 h
    assert worst(run(section(vlan(5, 3, HOUR * 100)), params)) is State.CRIT  # 1 h


def test_zero_changes_is_never_crit() -> None:
    results = run(section(vlan(10, 0, 20000)))  # timer 200 s: would be CRIT in the legacy script
    assert worst(results) is State.OK
    assert summary(results) == "1 VLAN, no recent topology change since spanning tree started"


def test_worst_vlan_wins_and_the_summary_is_truncated() -> None:
    rows = [vlan(vid, 5, (vid + 1) * 100 * 60) for vid in range(1, 8)]  # 7 VLANs, 2-8 min ago
    results = run(section(*rows, vlan(400, 15, 20 * HOUR * 100)), {"warn_within": 24.0 * HOUR})
    assert worst(results) is State.CRIT
    text = summary(results)
    assert text.startswith("8 of 8 VLANs: VLAN 1 changed 2 minutes 0 seconds ago, VLAN 2 changed")
    assert text.endswith(", +3 more")


# --- errors and filtering --------------------------------------------------------------------


def test_unanswered_vlan_is_unknown_but_the_others_are_evaluated() -> None:
    results = run(section(vlan(200, 37, OLD), ["vlan", "30", "timeout", "", ""]))
    assert worst(results) is State.UNKNOWN
    assert "1 VLAN without data: VLAN 30" in summary(results)
    assert "VLAN 30: SNMP context did not answer (timeout)" in details(results)
    assert vlan_age_metric(200) in metrics(results)


def test_unanswered_vlan_does_not_hide_a_crit() -> None:
    results = run(section(vlan(300, 120, 1_000_000), ["vlan", "30", "timeout", "", ""]))
    assert worst(results) is State.CRIT


def test_state_for_unanswered_vlans_is_configurable() -> None:
    sect = section(vlan(200, 37, OLD), ["vlan", "30", "error", "", ""])
    assert worst(run(sect, {"state_vlan_error": 0})) is State.OK
    assert worst(run(sect, {"state_vlan_error": 1})) is State.WARN


def test_invalid_value_counts_as_without_data() -> None:
    results = run(section(vlan(200, 37, OLD), ["vlan", "5", "ok", "x", "100"]))
    assert worst(results) is State.UNKNOWN
    assert "VLAN 5: malformed SNMP data" in details(results)


def test_vlans_without_spanning_tree_are_listed_but_not_monitored() -> None:
    results = run(section(vlan(200, 37, OLD), ["vlan", "99", "nosuch", "", ""]))
    assert worst(results) is State.OK
    assert "No spanning-tree data (not monitored): VLAN 99" in details(results)


def test_vlan_filter() -> None:
    included = metrics(run(QUIET, {"vlans": ("include", "200")}))
    assert vlan_age_metric(200) in included and vlan_age_metric(1) not in included
    excluded = metrics(run(QUIET, {"vlans": ("exclude", "1-10")}))
    assert vlan_age_metric(200) in excluded and vlan_age_metric(1) not in excluded


def test_filter_that_leaves_nothing_is_unknown() -> None:
    results = run(QUIET, {"vlans": ("include", "3000")})
    assert worst(results) is State.UNKNOWN
    assert summary(results) == "No VLAN with spanning-tree data to monitor"


def test_new_and_removed_vlans_need_no_rediscovery() -> None:
    store: dict[str, Any] = {}
    run(QUIET, store=store)
    grown = run(section(vlan(1, 6, 2586192400), vlan(200, 37, OLD), vlan(555, 1, OLD)), store=store)
    assert vlan_age_metric(555) in metrics(grown)
    shrunk = run(section(vlan(1, 6, 2586192400)), store=store)
    assert vlan_age_metric(200) not in metrics(shrunk)
    assert worst(shrunk) is State.OK


# --- rate ------------------------------------------------------------------------------------


def test_rate_needs_two_samples_then_reports_per_hour() -> None:
    store: dict[str, Any] = {}
    first = run(section(vlan(7, 100, 360_000_000)), store=store, now=0.0)
    assert "stp_topology_changes_rate" not in metrics(first)
    second = run(section(vlan(7, 103, 360_000_000), vlan(8, 0, OLD)), store=store, now=HOUR)
    assert metrics(second)["stp_topology_changes_rate"] == 3.0
    assert any("VLAN 7:" in line and "3.00 changes/h" in line for line in details(second))


def test_counter_reset_gives_no_rate() -> None:
    store: dict[str, Any] = {}
    run(section(vlan(7, 120, 360_000_000)), store=store, now=0.0)
    after_reboot = run(section(vlan(7, 2, 30_000)), store=store, now=600.0)
    assert "stp_topology_changes_rate" not in metrics(after_reboot)
    next_interval = run(section(vlan(7, 3, 36_000)), store=store, now=HOUR + 600)
    assert metrics(next_interval)["stp_topology_changes_rate"] == 1.0


def test_rate_levels_per_vlan() -> None:
    store: dict[str, Any] = {}
    params = {"rate_levels": ("fixed", (1.0, 2.0))}
    run(section(vlan(7, 100, 360_000_000)), params, store, now=0.0)
    results = run(section(vlan(7, 103, 360_000_000)), params, store, now=HOUR)
    assert worst(results) is State.CRIT
    assert summary(results) == "1 of 1 VLAN: VLAN 7 at 3.00 changes/h"


# --- TimeTicks wrap --------------------------------------------------------------------------


def test_timeticks_wrap_does_not_look_like_a_new_change() -> None:
    store: dict[str, Any] = {}
    run(section(vlan(7, 37, 2**32 - 6000)), store=store, now=0.0)
    wrapped = run(section(vlan(7, 37, 3000)), store=store, now=90.0)
    assert worst(wrapped) is State.OK
    assert metrics(wrapped)[vlan_age_metric(7)] == 2**32 / 100 + 30
    later = run(section(vlan(7, 37, 9000)), store=store, now=150.0)
    assert metrics(later)[vlan_age_metric(7)] == 2**32 / 100 + 90


def test_real_change_after_long_quiet_period_is_crit() -> None:
    store: dict[str, Any] = {}
    run(section(vlan(7, 37, 2**32 - 6000)), store=store, now=0.0)
    changed = run(section(vlan(7, 38, 3000)), store=store, now=90.0)
    assert worst(changed) is State.CRIT


# --- collection time -------------------------------------------------------------------------


def cached_section(collected: int, changes: int) -> stp.Section:
    parsed = stp.parse_nxos_stp_tcn(
        [["collected", str(collected)], ["sysuptime", "2590160436"], vlan(200, changes, OLD)]
    )
    assert parsed is not None
    return parsed


def test_parse_reads_the_collection_time() -> None:
    assert cached_section(1_700_000_000, 37).collected == 1_700_000_000.0
    assert QUIET.collected is None  # an older agent does not write the line


def test_rate_is_measured_between_collections_not_between_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store: dict[str, Any] = {}
    monkeypatch.setattr(stp, "get_value_store", lambda: store)
    monkeypatch.setattr(stp, "time", SimpleNamespace(time=lambda: 9_000_000.0))

    first = list(stp.check_nxos_stp_tcn(DEFAULTS, cached_section(1_700_000_000, 37)))
    assert "stp_topology_changes_rate" not in metrics(first)

    # the cache is served again: same data, same collection time, so there is nothing to rate
    repeat = list(stp.check_nxos_stp_tcn(DEFAULTS, cached_section(1_700_000_000, 37)))
    assert "stp_topology_changes_rate" not in metrics(repeat)

    # one hour later the switch was asked again and had three more changes
    later = list(stp.check_nxos_stp_tcn(DEFAULTS, cached_section(1_700_003_600, 40)))
    assert metrics(later)["stp_topology_changes_rate"] == 3.0


def test_without_a_collection_time_the_check_falls_back_to_the_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store: dict[str, Any] = {}
    monkeypatch.setattr(stp, "get_value_store", lambda: store)
    clock = SimpleNamespace(now=9_000_000.0)
    monkeypatch.setattr(stp, "time", SimpleNamespace(time=lambda: clock.now))

    list(stp.check_nxos_stp_tcn(DEFAULTS, section(vlan(200, 37, OLD))))
    clock.now += HOUR
    later = list(stp.check_nxos_stp_tcn(DEFAULTS, section(vlan(200, 40, OLD))))
    assert metrics(later)["stp_topology_changes_rate"] == 3.0


# --- per-VLAN metrics ------------------------------------------------------------------------


def test_one_metric_per_vlan_can_be_turned_off() -> None:
    switch_wide = {
        "stp_topology_changes_total",
        "stp_topology_changes_rate",
        "stp_seconds_since_last_change",
    }
    without = metrics(run(QUIET, {"per_vlan_metrics": False}))
    assert set(without) <= switch_wide
    assert vlan_age_metric(200) not in without
    # the VLANs are still evaluated and still listed
    assert "3 VLANs" in summary(run(QUIET, {"per_vlan_metrics": False}))
    assert any("VLAN 200" in d for d in details(run(QUIET, {"per_vlan_metrics": False})))


def test_turning_the_per_vlan_metrics_off_keeps_the_state() -> None:
    recent = section(vlan(200, 38, 60000))  # 10 minutes ago: inside the default CRIT window
    assert worst(run(recent, {"per_vlan_metrics": False})) is State.CRIT
    assert vlan_age_metric(200) not in metrics(run(recent, {"per_vlan_metrics": False}))
