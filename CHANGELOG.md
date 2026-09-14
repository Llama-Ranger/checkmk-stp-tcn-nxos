# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-09-14

First public release.

### Added

- Special agent `agent_nxos_stp_tcn`: discovers the VLAN contexts of a Cisco
  Nexus switch from CISCO-CONTEXT-MAPPING-MIB and reads BRIDGE-MIB
  `dot1dStpTopChanges` and `dot1dStpTimeSinceTopologyChange` in each VLAN's
  numeric SNMPv3 context, one OID per request. The `vlan-<id>` contexts are
  deliberately not used: on NX-OS 10.2(5) they returned another VLAN's data for
  VLANs created after the last reboot.
- SNMPv3 credentials are read from the Checkmk password store and handed to
  Net-SNMP through a private temporary `snmp.conf`, so they never appear on a
  command line.
- One `STP Topology VLAN <id>` service per VLAN with spanning-tree data. New
  VLANs are picked up by service discovery; removed ones vanish.
- Rules: CRIT window for the last topology change (default 12 hours),
  optional WARN window, optional upper levels on the change rate, and a
  discovery rule to include or exclude VLANs.
- A VLAN with zero topology changes is always OK (the NX-OS timer then counts
  from spanning-tree start, not from a change).
- TimeTicks wrap (~497 days) compensation and counter-reset handling for the
  change rate.
- Metrics `stp_seconds_since_last_change`, `stp_topology_changes_total`,
  `stp_topology_changes_rate`, three graphs and a perf-o-meter.
- Tests against the real Checkmk 2.4.0 and 2.5.0 plug-in APIs, `package.manifest`,
  `scripts/build_mkp.py` and CI that builds the `.mkp` and attaches it to tagged
  releases.

[Unreleased]: https://github.com/Llama-Ranger/checkmk-stp-tcn-nxos/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Llama-Ranger/checkmk-stp-tcn-nxos/releases/tag/v1.0.0
