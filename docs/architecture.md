# nxos_stp_tcn — architecture (v2.0)

## Decision: SNMP special agent + agent-based check (not a native SNMPSection)

A native `SNMPSection` cannot deliver per-VLAN STP data from Nexus, verified against the Checkmk
2.4.0 / 2.5.0 source (`cmk/snmplib/_table.py`, `_getoid.py`, `cmk/snmplib/_typedefs.py`):

1. **Static context list.** The rule "SNMPv3 contexts to use in requests" (`snmpv3_contexts`) is a fixed
   list of context names per section. New VLANs would require editing the rule; nothing discovers
   contexts at runtime.
2. **Scalars from several contexts collide.** Rows from all contexts are concatenated with no context
   marker, and a row whose OID was already seen in an earlier context is dropped as a duplicate.
   `1.3.6.1.2.1.17.2.3.0` / `.2.4.0` have the same OID in every VLAN context, so only one VLAN survives.
   Single-OID GETs stop at the first context that answers.
3. **Timeouts.** NX-OS silently drops requests for unknown contexts (a deleted VLAN). The native fetcher
   either fails the whole section, or skips that context but still fails if every context timed out.

A special agent is still a pure SNMP solution. It runs on the Checkmk server, discovers the VLAN
contexts from the switch, queries each context, and hands structured data to a normal Check API v2 plugin.

## Components (all under `cmk_addons/plugins/nxos_stp_tcn/`)

| Path | API | Purpose |
|------|-----|---------|
| `rulesets/special_agent.py` | rulesets v1 `SpecialAgent` | "Cisco Nexus STP topology changes (SNMPv3 VLAN contexts)": SNMPv3 user, security level, auth/priv protocol, passphrases (password store), timeout, retries |
| `server_side_calls/special_agent.py` | server_side_calls v1 `SpecialAgentConfig` | Builds the command line. Passphrases are passed as `Secret` → `<id>:<store file>`, never plaintext |
| `libexec/agent_nxos_stp_tcn` | executable (Python) | SNMP collector: context discovery + per-context GETs, prints agent section |
| `agent_based/cisco_nexus_stp.py` | agent_based v2 | `AgentSection` + `CheckPlugin` "STP Topology" (one service per switch) |
| `rulesets/check_parameters.py` | rulesets v1 `CheckParameters` (host condition) | CRIT/WARN windows, per-VLAN rate levels, VLAN include/exclude filter, state for unanswered VLANs |
| `graphing/cisco_nexus_stp.py` | graphing v1 | One metric per VLAN (generated for IDs 1–4094), switch-wide metrics, graphs, perfometer |
| `lib/metric_names.py`, `lib/vlan_ranges.py` | shared | Per-VLAN metric name; VLAN list parsing |
| `checkman/nxos_stp_tcn` | checkman | Man page |

## Collector flow (per host, per check interval)

1. Resolve passphrases from the Checkmk password store (compat shim: 2.5 `cmk.password_store.v1_unstable`,
   2.4 `cmk.utils.password_store.lookup`).
2. Write a 0600 temporary `snmp.conf` (`defSecurityName`, `defSecurityLevel`, `defAuthType`,
   `defAuthPassphrase`, `defPrivType`, `defPrivPassphrase`) in a private temp directory; point
   `SNMPCONFPATH` at it. Credentials never appear in argv, `ps`, logs or output. The directory is always
   removed afterwards.
3. Walk `.1.3.6.1.4.1.9.9.468.1.5.1.2` (default context) with the site's Net-SNMP `snmpwalk`.
   Decode context name → VLAN ID (4-byte little-endian). Keep only **numeric** contexts whose name equals
   the VLAN ID. `vlan-<id>` contexts were proven unreliable for post-boot VLANs.
4. For each VLAN context: two single-OID `snmpget` calls (`.17.2.4.0`, `.17.2.3.0`), short timeout,
   low retries. One failed VLAN is reported as an error row; the others continue.
5. Read `sysUpTime` (default context) once.
6. Print `<<<nxos_stp_tcn:sep(59)>>>` rows: `sysuptime;<ticks>` and `vlan;<id>;<status>;<changes>;<ticks>`.

## Check logic

- Discovery: one `STP Topology` service per switch if at least one VLAN has valid STP data. VLANs are
  evaluated at check time, so VLANs added or removed on the switch need no rediscovery.
- Per VLAN (after the optional include/exclude filter):
  - Changes = 0 → **OK** regardless of age: the timer then counts from STP start, not from a change.
  - Otherwise the age of the last change decides: default CRIT if < 12 h, WARN disabled.
  - Optional rate: `get_rate` on the VLAN's change counter (changes/hour). A counter decrease (reboot or
    Counter32 wrap) → no rate for that interval. Off by default.
  - TimeTicks wrap (2^32 cs ≈ 497 d): tracked per VLAN in the value store. If the count is unchanged and
    the timer went backwards from near the wrap point, 497.1 d is added.
- Service state = worst VLAN. The summary names the alerting VLANs, most recent first (at most five, then
  "+N more"). The details list every VLAN; VLANs without STP data are listed as not monitored.
- VLANs that returned no data (timeout/error/malformed) are listed and set a configurable state
  (default UNKNOWN); all other VLANs are still evaluated, and a CRIT still wins.
- Metrics: `stp_vlan_<id>_seconds_since_last_change` per VLAN (one graph each), plus switch-wide
  `stp_seconds_since_last_change` (most recent change, any VLAN), `stp_topology_changes_total` (sum) and
  `stp_topology_changes_rate` (sum of per-VLAN rates).
- Checkmk notifies on state changes. While the service is already CRIT because of one VLAN, a change on a
  second VLAN updates the summary but does not raise a new notification (use periodic notifications if
  wanted).

## Credentials

- Stored only in the Checkmk password store and referenced by the special-agent rule.
- Checkmk passes `<id>:<password-store-file>` on the command line (`Secret`, pass_safely). The agent
  resolves them in memory.
- Temporary Net-SNMP config file: mode 0600 inside a mode-0700 temp dir, deleted in `finally`.
- Nothing credential-related in the source, tests, fixtures, docs or MKP.
- Why the host's own SNMP credentials cannot be reused (verified in the 2.4.0/2.5.0 source): the
  server-side-calls API gives a special agent only host name, alias, IP addresses and macros
  (`HostConfig`), and the host's SNMP credentials are stored as plain values (`SNMPCredentials` in
  `cmk/snmplib/_typedefs.py`; a plain `Password` field in `cmk/gui/watolib/attributes.py`), with no
  password-store reference that a rule could share. The SNMPv3 settings are therefore entered once in
  the special-agent rule.

## Host scope

The special-agent rule's conditions decide which hosts are monitored: explicit hosts, a folder, a tag, or
a label such as `stp_topology:monitor`. The plugin contains no host names. Hosts need the agent setting
"Configured API integrations, no Checkmk agent" (`special-agents`). Their SNMP checks keep running.
