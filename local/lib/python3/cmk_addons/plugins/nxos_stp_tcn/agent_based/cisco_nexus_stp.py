#!/usr/bin/env python3
# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Cisco Nexus spanning-tree topology changes per VLAN.

Consumes the section written by the special agent ``agent_nxos_stp_tcn``::

    <<<nxos_stp_tcn:sep(59)>>>
    sysuptime;2590160436
    vlan;200;ok;37;2586624300
    vlan;30;timeout;;

Timer values are TimeTicks (1/100 s).
"""

from __future__ import annotations

import time
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from cmk.agent_based.v2 import (
    AgentSection,
    CheckPlugin,
    CheckResult,
    DiscoveryResult,
    GetRateError,
    Metric,
    Result,
    Service,
    State,
    StringTable,
    check_levels,
    get_rate,
    get_value_store,
    render,
)
from cmk_addons.plugins.nxos_stp_tcn.lib.vlan_ranges import parse_vlan_ranges

# dot1dStpTimeSinceTopologyChange is a 32 bit TimeTicks value: it wraps after ~497 days.
TIMETICKS_WRAP_SECONDS = 2**32 / 100
_WRAP_DETECTION_MARGIN = 2 * 86400

_STATUS_TEXT = {
    "nosuch": "The switch returns no spanning-tree data for this VLAN (noSuchInstance)",
    "timeout": "The SNMP context of this VLAN did not answer (timeout)",
    "error": "The SNMP query for this VLAN failed",
    "invalid": "Malformed SNMP data for this VLAN",
}


@dataclass(frozen=True)
class VlanStp:
    status: str
    changes: int | None = None
    age: float | None = None  # seconds since the last topology change


@dataclass(frozen=True)
class Section:
    vlans: Mapping[str, VlanStp]
    sysuptime: float | None = None  # seconds


def _to_int(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def parse_nxos_stp_tcn(string_table: StringTable) -> Section | None:
    vlans: dict[str, VlanStp] = {}
    sysuptime: float | None = None
    for row in string_table:
        if len(row) >= 2 and row[0] == "sysuptime":
            if (ticks := _to_int(row[1])) is not None and ticks >= 0:
                sysuptime = ticks / 100
        elif len(row) >= 3 and row[0] == "vlan" and row[1].isdigit():
            status = row[2]
            changes = _to_int(row[3]) if len(row) > 3 else None
            ticks = _to_int(row[4]) if len(row) > 4 else None
            if status == "ok" and (changes is None or ticks is None or changes < 0 or ticks < 0):
                status = "invalid"
            vlans[str(int(row[1]))] = VlanStp(
                status=status,
                changes=changes,
                age=ticks / 100 if ticks is not None else None,
            )
    if not vlans:
        return None
    return Section(vlans=vlans, sysuptime=sysuptime)


agent_section_nxos_stp_tcn = AgentSection(
    name="nxos_stp_tcn",
    parse_function=parse_nxos_stp_tcn,
)


def _vlan_selected(vlan: int, selection: object) -> bool:
    match selection:
        case ("include", str(spec)):
            try:
                return vlan in parse_vlan_ranges(spec)
            except ValueError:
                return True
        case ("exclude", str(spec)):
            try:
                return vlan not in parse_vlan_ranges(spec)
            except ValueError:
                return True
    return True


def discover_nxos_stp_tcn(params: Mapping[str, Any], section: Section) -> DiscoveryResult:
    selection = params.get("vlans", ("all", None))
    for item, data in sorted(section.vlans.items(), key=lambda entry: int(entry[0])):
        if data.status == "ok" and _vlan_selected(int(item), selection):
            yield Service(item=item)


def _unwrapped_age(value_store: MutableMapping[str, Any], changes: int, raw_age: float) -> float:
    """Compensate a TimeTicks wrap: same change count but the timer jumped back near 2^32 cs."""
    offset = 0.0
    if (previous := value_store.get("tc_timer")) is not None:
        prev_changes, prev_raw_age, prev_offset = previous
        if changes == prev_changes:
            offset = prev_offset
            if (
                changes > 0
                and raw_age < prev_raw_age
                and prev_raw_age >= TIMETICKS_WRAP_SECONDS - _WRAP_DETECTION_MARGIN
            ):
                offset += TIMETICKS_WRAP_SECONDS
    value_store["tc_timer"] = (changes, raw_age, offset)
    return raw_age + offset


def _age_state(age: float, params: Mapping[str, Any]) -> tuple[State, str]:
    crit = float(params["crit_within"])
    if age < crit:
        return State.CRIT, f"topology change within the last {render.timespan(crit)}"
    if (warn := params.get("warn_within")) is not None and age < float(warn):
        return State.WARN, f"topology change within the last {render.timespan(float(warn))}"
    return State.OK, ""


def _check_rate(
    value_store: MutableMapping[str, Any], changes: int, now: float, params: Mapping[str, Any]
) -> CheckResult:
    try:
        # raise_overflow: a decreasing counter (reboot, Counter32 wrap) must not yield a rate
        per_second = get_rate(value_store, "changes", now, changes, raise_overflow=True)
    except GetRateError:
        return
    yield from check_levels(
        per_second * 3600,
        levels_upper=params.get("rate_levels", ("no_levels", None)),
        metric_name="stp_topology_changes_rate",
        render_func=lambda value: f"{value:.2f}/h",
        label="Change rate",
        notice_only=True,
    )


def _check(
    item: str,
    params: Mapping[str, Any],
    section: Section,
    value_store: MutableMapping[str, Any],
    now: float,
) -> CheckResult:
    if (data := section.vlans.get(item)) is None:
        return  # VLAN vanished: Checkmk reports the item as not found
    if data.status != "ok" or data.changes is None or data.age is None:
        yield Result(state=State.UNKNOWN, summary=_STATUS_TEXT.get(data.status, data.status))
        return

    changes = data.changes
    age = _unwrapped_age(value_store, changes, data.age)

    yield Result(state=State.OK, summary=f"Topology changes: {changes}")
    yield Metric("stp_topology_changes_total", changes)

    if changes == 0:
        # Without any change the timer counts from STP start (e.g. a reboot), not from a change.
        yield Result(
            state=State.OK,
            summary="no change since spanning tree started",
            details=f"Spanning tree running without a topology change for {render.timespan(age)}",
        )
    else:
        state, reason = _age_state(age, params)
        text = f"Last change: {render.timespan(age)} ago"
        yield Result(state=state, summary=f"{text} ({reason})" if reason else text)
    yield Metric("stp_seconds_since_last_change", age)

    yield from _check_rate(value_store, changes, now, params)

    yield Result(state=State.OK, notice=f"SNMP context: {item}")
    if changes and section.sysuptime is not None and section.sysuptime >= data.age:
        uptime_at_change = section.sysuptime - data.age
        yield Result(
            state=State.OK,
            notice=f"Switch uptime at last change: {render.timespan(uptime_at_change)}",
        )


def check_nxos_stp_tcn(item: str, params: Mapping[str, Any], section: Section) -> CheckResult:
    yield from _check(item, params, section, get_value_store(), time.time())


check_plugin_nxos_stp_tcn = CheckPlugin(
    name="nxos_stp_tcn",
    service_name="STP Topology VLAN %s",
    discovery_function=discover_nxos_stp_tcn,
    discovery_ruleset_name="nxos_stp_tcn_discovery",
    discovery_default_parameters={"vlans": ("all", None)},
    check_function=check_nxos_stp_tcn,
    check_ruleset_name="nxos_stp_tcn",
    check_default_parameters={
        "crit_within": 43200.0,
        "rate_levels": ("no_levels", None),
    },
)
