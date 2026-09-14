# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check plugin tests. Values are taken from the real NX-OS 10.2(5) validation (see docs)."""

from collections.abc import Mapping, MutableMapping
from typing import Any

from cmk.agent_based.v2 import Metric, Result, Service, State
from cmk_addons.plugins.nxos_stp_tcn.agent_based import cisco_nexus_stp as stp

DEFAULTS = stp.check_plugin_nxos_stp_tcn.check_default_parameters
HOUR = 3600

STRING_TABLE = [
    ["sysuptime", "2590160436"],
    ["vlan", "1", "ok", "6", "2586192400"],  # ~299 days
    ["vlan", "10", "ok", "0", "20000"],  # no change, STP started 200 s ago
    ["vlan", "200", "ok", "37", "2586624300"],
    ["vlan", "300", "ok", "120", "1000000"],  # 10 000 s = 2 h 46 min
    ["vlan", "400", "ok", "15", str(20 * HOUR * 100)],  # 20 h
    ["vlan", "30", "timeout", "", ""],
    ["vlan", "99", "nosuch", "", ""],
]
SECTION = stp.parse_nxos_stp_tcn(STRING_TABLE)


def run_check(
    item: str,
    params: Mapping[str, Any] | None = None,
    section: stp.Section | None = None,
    store: MutableMapping[str, Any] | None = None,
    now: float = 1_000_000.0,
) -> list[Result | Metric]:
    return list(
        stp._check(
            item,
            {**DEFAULTS, **(params or {})},
            section or SECTION,
            {} if store is None else store,
            now,
        )
    )


def worst(results: list[Result | Metric]) -> State:
    return State.worst(*(r.state for r in results if isinstance(r, Result)))


def summary(results: list[Result | Metric]) -> str:
    return ", ".join(r.summary for r in results if isinstance(r, Result) and r.summary)


def metrics(results: list[Result | Metric]) -> dict[str, float]:
    return {m.name: m.value for m in results if isinstance(m, Metric)}


# --- parsing ---------------------------------------------------------------------------------


def test_parse() -> None:
    assert SECTION is not None
    assert SECTION.sysuptime == 25901604.36
    assert SECTION.vlans["200"] == stp.VlanStp("ok", 37, 25866243.0)
    assert SECTION.vlans["30"].status == "timeout"


def test_parse_malformed_rows_do_not_crash() -> None:
    section = stp.parse_nxos_stp_tcn(
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
    assert section is not None
    assert set(section.vlans) == {"5", "6", "7"}
    assert {v.status for v in section.vlans.values()} == {"invalid"}
    assert section.sysuptime is None


def test_parse_empty() -> None:
    assert stp.parse_nxos_stp_tcn([]) is None


# --- discovery -------------------------------------------------------------------------------


def discovered(params: Mapping[str, Any]) -> list[str]:
    return [s.item for s in stp.discover_nxos_stp_tcn(params, SECTION) if isinstance(s, Service)]


def test_discovery_multiple_vlans_only_with_valid_data() -> None:
    assert discovered({"vlans": ("all", None)}) == ["1", "10", "200", "300", "400"]


def test_discovery_include_and_exclude() -> None:
    assert discovered({"vlans": ("include", "1, 200-300")}) == ["1", "200", "300"]
    assert discovered({"vlans": ("exclude", "10,400")}) == ["1", "200", "300"]


def test_removed_vlan_is_no_longer_discovered_and_yields_nothing() -> None:
    section = stp.parse_nxos_stp_tcn([r for r in STRING_TABLE if r[1:2] != ["200"]])
    assert section is not None
    assert "200" not in [s.item for s in stp.discover_nxos_stp_tcn({}, section)]
    assert run_check("200", section=section) == []  # Checkmk: "item not found" -> vanished


# --- thresholds ------------------------------------------------------------------------------


def test_old_change_is_ok() -> None:
    results = run_check("200")
    assert worst(results) is State.OK
    assert summary(results).startswith("Topology changes: 37, Last change: 299 days")
    assert metrics(results)["stp_topology_changes_total"] == 37
    assert metrics(results)["stp_seconds_since_last_change"] == 25866243.0


def test_recent_change_is_crit_by_default() -> None:
    results = run_check("300")
    assert worst(results) is State.CRIT
    assert "within the last 12 hours" in summary(results)


def test_warn_disabled_by_default() -> None:
    assert worst(run_check("400")) is State.OK  # 20 h ago, only CRIT < 12 h configured


def test_warn_window() -> None:
    assert worst(run_check("400", {"warn_within": 24.0 * HOUR})) is State.WARN


def test_override_crit_2h_warn_12h() -> None:
    params = {"crit_within": 2.0 * HOUR, "warn_within": 12.0 * HOUR}
    assert worst(run_check("300", params)) is State.WARN  # 2 h 46 min
    assert worst(run_check("400", params)) is State.OK  # 20 h
    one_hour = stp.parse_nxos_stp_tcn([["vlan", "5", "ok", "3", str(HOUR * 100)]])
    assert worst(run_check("5", params, one_hour)) is State.CRIT


def test_zero_changes_is_never_crit() -> None:
    results = run_check("10")  # timer 200 s: would be CRIT in the legacy script
    assert worst(results) is State.OK
    assert "no change since spanning tree started" in summary(results)


# --- errors ----------------------------------------------------------------------------------


def test_unanswered_context_is_unknown_only_for_that_vlan() -> None:
    assert worst(run_check("30")) is State.UNKNOWN
    assert worst(run_check("99")) is State.UNKNOWN
    assert worst(run_check("200")) is State.OK


def test_invalid_value_is_unknown() -> None:
    section = stp.parse_nxos_stp_tcn([["vlan", "5", "ok", "x", "100"]])
    assert worst(run_check("5", section=section)) is State.UNKNOWN


# --- rate ------------------------------------------------------------------------------------


def section_with(changes: int, ticks: int = 360_000_000) -> stp.Section:
    section = stp.parse_nxos_stp_tcn([["vlan", "7", "ok", str(changes), str(ticks)]])
    assert section is not None
    return section


def test_rate_needs_two_samples_then_reports_per_hour() -> None:
    store: dict[str, Any] = {}
    first = run_check("7", section=section_with(100), store=store, now=0.0)
    assert "stp_topology_changes_rate" not in metrics(first)
    second = run_check("7", section=section_with(103), store=store, now=HOUR)
    assert metrics(second)["stp_topology_changes_rate"] == 3.0


def test_counter_reset_gives_no_rate() -> None:
    store: dict[str, Any] = {}
    run_check("7", section=section_with(120), store=store, now=0.0)
    after_reboot = run_check("7", section=section_with(2, 30_000), store=store, now=600.0)
    assert "stp_topology_changes_rate" not in metrics(after_reboot)
    next_interval = run_check("7", section=section_with(3, 36_000), store=store, now=HOUR + 600)
    assert metrics(next_interval)["stp_topology_changes_rate"] == 1.0


def test_rate_levels() -> None:
    store: dict[str, Any] = {}
    params = {"rate_levels": ("fixed", (1.0, 2.0))}
    run_check("7", params, section_with(100), store, now=0.0)
    results = run_check("7", params, section_with(103), store, now=HOUR)
    assert worst(results) is State.CRIT
    assert "Change rate: 3.00/h" in summary(results)


# --- TimeTicks wrap --------------------------------------------------------------------------


def test_timeticks_wrap_does_not_look_like_a_new_change() -> None:
    store: dict[str, Any] = {}
    run_check("7", section=section_with(37, 2**32 - 6000), store=store, now=0.0)
    wrapped = run_check("7", section=section_with(37, 3000), store=store, now=90.0)
    assert worst(wrapped) is State.OK
    assert metrics(wrapped)["stp_seconds_since_last_change"] == 2**32 / 100 + 30
    later = run_check("7", section=section_with(37, 9000), store=store, now=150.0)
    assert metrics(later)["stp_seconds_since_last_change"] == 2**32 / 100 + 90


def test_real_change_after_long_quiet_period_is_crit() -> None:
    store: dict[str, Any] = {}
    run_check("7", section=section_with(37, 2**32 - 6000), store=store, now=0.0)
    changed = run_check("7", section=section_with(38, 3000), store=store, now=90.0)
    assert worst(changed) is State.CRIT


def test_details_contain_context_and_uptime_at_change() -> None:
    details = [r.details for r in run_check("300") if isinstance(r, Result)]
    assert "SNMP context: 300" in details
    assert any(d.startswith("Switch uptime at last change:") for d in details)
