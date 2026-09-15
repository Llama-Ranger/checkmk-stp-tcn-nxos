#!/usr/bin/env python3
# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Cisco Nexus spanning-tree topology changes: one service for all VLANs of a switch.

Consumes the section written by the special agent ``agent_nxos_stp_tcn``::

    <<<nxos_stp_tcn:sep(59)>>>
    sysuptime;2590160436
    vlan;200;ok;37;2586624300
    vlan;30;timeout;;

Timer values are TimeTicks (1/100 s). Every VLAN gets its own metric, and therefore its own
graph: ``stp_vlan_<id>_seconds_since_last_change``.
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
    get_rate,
    get_value_store,
    render,
)
from cmk_addons.plugins.nxos_stp_tcn.lib.metric_names import vlan_age_metric
from cmk_addons.plugins.nxos_stp_tcn.lib.vlan_ranges import parse_vlan_ranges

# dot1dStpTimeSinceTopologyChange is a 32 bit TimeTicks value: it wraps after ~497 days.
TIMETICKS_WRAP_SECONDS = 2**32 / 100
_WRAP_DETECTION_MARGIN = 2 * 86400
_MAX_VLANS_IN_SUMMARY = 5

_STATUS_TEXT = {
    "timeout": "SNMP context did not answer (timeout)",
    "error": "SNMP query failed",
    "invalid": "malformed SNMP data",
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
    # When the agent last talked to the switch. With a cache configured, several checks in a
    # row see the same data carrying the same timestamp, which is what keeps the change rate
    # from being computed over a minute that contained no new measurement. An older agent does
    # not write the line, and then the check falls back to the current time.
    collected: float | None = None


def _to_int(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def parse_nxos_stp_tcn(string_table: StringTable) -> Section | None:
    vlans: dict[str, VlanStp] = {}
    sysuptime: float | None = None
    collected: float | None = None
    for row in string_table:
        if len(row) >= 2 and row[0] == "collected":
            if (epoch := _to_int(row[1])) is not None and epoch > 0:
                collected = float(epoch)
        elif len(row) >= 2 and row[0] == "sysuptime":
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
    return Section(vlans=vlans, sysuptime=sysuptime, collected=collected)


agent_section_nxos_stp_tcn = AgentSection(
    name="nxos_stp_tcn",
    parse_function=parse_nxos_stp_tcn,
)


def discover_nxos_stp_tcn(section: Section) -> DiscoveryResult:
    if any(vlan.status == "ok" for vlan in section.vlans.values()):
        yield Service()


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


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _truncated(items: list[str]) -> str:
    text = ", ".join(items[:_MAX_VLANS_IN_SUMMARY])
    if (more := len(items) - _MAX_VLANS_IN_SUMMARY) > 0:
        text += f", +{more} more"
    return text


def _unwrapped_age(
    value_store: MutableMapping[str, Any], key: str, changes: int, raw_age: float
) -> float:
    """Compensate a TimeTicks wrap: same change count but the timer jumped back near 2^32 cs."""
    offset = 0.0
    if (previous := value_store.get(key)) is not None:
        prev_changes, prev_raw_age, prev_offset = previous
        if changes == prev_changes:
            offset = prev_offset
            if (
                changes > 0
                and raw_age < prev_raw_age
                and prev_raw_age >= TIMETICKS_WRAP_SECONDS - _WRAP_DETECTION_MARGIN
            ):
                offset += TIMETICKS_WRAP_SECONDS
    value_store[key] = (changes, raw_age, offset)
    return raw_age + offset


def _age_state(age: float, params: Mapping[str, Any]) -> tuple[State, str]:
    crit = float(params["crit_within"])
    if age < crit:
        return State.CRIT, f"within the last {render.timespan(crit)}"
    if (warn := params.get("warn_within")) is not None and age < float(warn):
        return State.WARN, f"within the last {render.timespan(float(warn))}"
    return State.OK, ""


def _rate_per_hour(
    value_store: MutableMapping[str, Any], key: str, changes: int, now: float
) -> float | None:
    try:
        # raise_overflow: a decreasing counter (reboot, Counter32 wrap) must not yield a rate
        return get_rate(value_store, key, now, changes, raise_overflow=True) * 3600
    except GetRateError:
        return None


def _rate_state(rate: float, levels: object) -> State:
    match levels:
        case ("fixed", (warn, crit)):
            if rate >= crit:
                return State.CRIT
            if rate >= warn:
                return State.WARN
    return State.OK


@dataclass(frozen=True)
class _VlanStatus:
    vlan: int
    changes: int
    age: float
    rate: float | None
    state: State
    alert: str  # short text for the summary when the state is not OK
    detail: str  # one line for the long output


def _evaluate_vlan(
    vlan: int,
    data: VlanStp,
    params: Mapping[str, Any],
    sysuptime: float | None,
    value_store: MutableMapping[str, Any],
    now: float,
) -> _VlanStatus:
    assert data.changes is not None and data.age is not None
    changes = data.changes
    age = _unwrapped_age(value_store, f"tc_timer.{vlan}", changes, data.age)
    rate = _rate_per_hour(value_store, f"changes.{vlan}", changes, now)

    state, reasons, alerts = State.OK, [], []
    if changes == 0:
        # Without any change the timer counts from STP start (e.g. a reboot), not from a change.
        detail = f"VLAN {vlan}: no topology change since spanning tree started"
        detail += f" {render.timespan(age)} ago"
    else:
        detail = f"VLAN {vlan}: {_plural(changes, 'topology change')}, last change"
        detail += f" {render.timespan(age)} ago"
        if sysuptime is not None and sysuptime >= data.age:
            detail += f" (switch uptime then: {render.timespan(sysuptime - data.age)})"
        age_state, reason = _age_state(age, params)
        if age_state is not State.OK:
            state = age_state
            reasons.append(f"topology change {reason}")
            alerts.append(f"VLAN {vlan} changed {render.timespan(age)} ago")

    if rate is not None:
        detail += f", {rate:.2f} changes/h"
        rate_state = _rate_state(rate, params.get("rate_levels", ("no_levels", None)))
        if rate_state is not State.OK:
            state = State.worst(state, rate_state)
            reasons.append("change rate above the configured levels")
            alerts.append(f"VLAN {vlan} at {rate:.2f} changes/h")

    if state is not State.OK:
        detail += f" - {state.name}: {', '.join(reasons)}"
    return _VlanStatus(vlan, changes, age, rate, state, ", ".join(alerts), detail)


def _check(
    params: Mapping[str, Any],
    section: Section,
    value_store: MutableMapping[str, Any],
    now: float,
) -> CheckResult:
    selection = params.get("vlans", ("all", None))
    selected = sorted(
        (int(vid), data)
        for vid, data in section.vlans.items()
        if _vlan_selected(int(vid), selection)
    )
    usable = [(vid, data) for vid, data in selected if data.status == "ok"]
    no_stp = [vid for vid, data in selected if data.status == "nosuch"]
    failed = [(vid, data) for vid, data in selected if data.status not in ("ok", "nosuch")]

    if not usable and not failed:
        yield Result(state=State.UNKNOWN, summary="No VLAN with spanning-tree data to monitor")
        return

    statuses = [
        _evaluate_vlan(vid, data, params, section.sysuptime, value_store, now)
        for vid, data in usable
    ]

    alerting = sorted((s for s in statuses if s.state is not State.OK), key=lambda s: s.age)
    changed = [s for s in statuses if s.changes]
    if alerting:
        yield Result(
            state=State.worst(*(s.state for s in alerting)),
            summary=f"{len(alerting)} of {_plural(len(statuses), 'VLAN')}: "
            + _truncated([s.alert for s in alerting]),
        )
    elif statuses:
        latest = min(changed, key=lambda s: s.age) if changed else None
        text = f"{_plural(len(statuses), 'VLAN')}, no recent topology change"
        if latest is not None:
            text += f", most recent: VLAN {latest.vlan} {render.timespan(latest.age)} ago"
        else:
            text += " since spanning tree started"
        yield Result(state=State.OK, summary=text)

    if failed:
        yield Result(
            state=State(params.get("state_vlan_error", 3)),
            summary=f"{_plural(len(failed), 'VLAN')} without data: "
            + _truncated([f"VLAN {vid}" for vid, _data in failed]),
        )

    # One metric - and so one graph - per VLAN, off by default: on a core with 80
    # VLANs that is 80 graphs in one service, and the switch-wide metrics below
    # already cover every VLAN together.
    if params.get("per_vlan_metrics", False):
        for s in statuses:
            yield Metric(vlan_age_metric(s.vlan), s.age)
    # switch-wide metrics
    yield Metric("stp_topology_changes_total", sum(s.changes for s in statuses))
    if changed:
        yield Metric("stp_seconds_since_last_change", min(s.age for s in changed))
    if rates := [s.rate for s in statuses if s.rate is not None]:
        yield Metric("stp_topology_changes_rate", sum(rates))

    for vid, data in failed:
        yield Result(
            state=State.OK, notice=f"VLAN {vid}: {_STATUS_TEXT.get(data.status, data.status)}"
        )
    for s in statuses:
        yield Result(state=State.OK, notice=s.detail)
    if no_stp:
        yield Result(
            state=State.OK,
            notice="No spanning-tree data (not monitored): "
            + ", ".join(f"VLAN {vid}" for vid in no_stp),
        )


def check_nxos_stp_tcn(params: Mapping[str, Any], section: Section) -> CheckResult:
    # The rate is measured between two collections, not between two checks: with a cache
    # configured the same counter is served for a while, and using the wall clock there would
    # report a change that happened over an hour as if it had happened in one minute.
    yield from _check(params, section, get_value_store(), section.collected or time.time())


check_plugin_nxos_stp_tcn = CheckPlugin(
    name="nxos_stp_tcn",
    service_name="STP Topology",
    discovery_function=discover_nxos_stp_tcn,
    check_function=check_nxos_stp_tcn,
    check_ruleset_name="nxos_stp_tcn",
    check_default_parameters={
        "crit_within": 43200.0,
        "rate_levels": ("no_levels", None),
        "vlans": ("all", None),
        "per_vlan_metrics": False,
        "state_vlan_error": 3,
    },
)
