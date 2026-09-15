# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/).

## [Unreleased]

## [2.2.0] - 2026-09-15

### Added

- "Record one metric per VLAN" in the service rule, on by default. Turned off,
  the service records only the three switch-wide metrics (cumulative changes,
  change rate, time since the most recent change on any VLAN) instead of one
  metric per VLAN, which on a core with 80 VLANs meant 80 graphs in a single
  service.

  What the option does not change: every VLAN is still queried, still named in
  the summary, still listed in the details, and still decides the service state.
  Only the per-VLAN graphs disappear. Existing per-VLAN data is kept, so turning
  the option back on resumes the same graphs.

## [2.1.1] - 2026-09-15

### Changed

- `version.min_required` is 2.3.0: the package installs on Checkmk 2.3 as well.
  Every API it imports exists unchanged in 2.3, the password store is read
  through the same `cmk.utils.password_store.lookup` as on 2.4, and the package
  was run on a 2.3.0p49 site against a live Nexus. CI now runs the tests against
  the 2.3.0 plug-in APIs too, so the claim keeps being checked.

## [2.1.0] - 2026-09-15

### Added

- "Query the switch at most every" in the special-agent rule. The agent stores
  its answer in `$OMD_ROOT/tmp/check_mk/cache/nxos_stp_tcn.<host>` and re-serves
  it until it reaches that age, so a switch with many VLANs is no longer queried
  on every check. The section then carries `cached(<collected>,<validity>)`, so
  Checkmk knows the age of the data and the service does not go stale between
  two collections.

  This is the alternative to raising the host's check interval, which would also
  slow down every other data source of that host.

### Changed

- The section carries a `collected;<epoch>` line, and the change rate is measured
  between two collections instead of between two checks. Without it, a cached
  counter would report an hour's worth of changes as if they had happened in one
  minute. A section written by an older agent has no such line; the check then
  falls back to the current time, as before.

## [2.0.0] - 2026-09-14

### Changed (breaking)

- One `STP Topology` service per switch replaces the `STP Topology VLAN <id>`
  services. The summary names the VLANs with a recent topology change (most
  recent first), the details list every VLAN, and the service takes the state
  of the worst VLAN.
- One graph per VLAN: every VLAN has its own metric,
  `stp_vlan_<id>_seconds_since_last_change`. The metrics are declared for all
  VLAN IDs 1-4094, so every graph has a title and time units.
- The switch-wide metrics now cover all VLANs: `stp_topology_changes_total`
  (sum), `stp_topology_changes_rate` (sum of the per-VLAN rates) and
  `stp_seconds_since_last_change` (most recent change on any VLAN).
- The rule "Cisco Nexus STP topology changes" applies per host (there is no
  VLAN item any more) and now also holds the VLAN include/exclude filter.
  Rate levels are still evaluated per VLAN.

### Added

- "State if a VLAN cannot be queried" (default UNKNOWN). The VLAN is listed and
  all other VLANs are still evaluated.
- VLANs added on the switch appear in the service without a new service
  discovery.

### Removed

- The discovery rule "Cisco Nexus STP topology VLAN discovery". Its VLAN filter
  moved into "Cisco Nexus STP topology changes".

### Upgrading from 1.0.0

- After installing, run service discovery on the hosts: the
  `STP Topology VLAN <id>` services vanish and one `STP Topology` service
  appears. Graph history of the per-VLAN services is not carried over.
- Re-create threshold rules without a VLAN condition, and move a VLAN filter
  from the old discovery rule into "Cisco Nexus STP topology changes".
- The special-agent rule and its credentials stay as they are.

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

[Unreleased]: https://github.com/Llama-Ranger/checkmk-stp-tcn-nxos/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/Llama-Ranger/checkmk-stp-tcn-nxos/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/Llama-Ranger/checkmk-stp-tcn-nxos/releases/tag/v1.0.0
