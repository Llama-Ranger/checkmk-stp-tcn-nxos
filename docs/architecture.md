# nxos_stp_tcn — architecture (v1.0)

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
| `rulesets/special_agent.py` | rulesets v1 `SpecialAgent` | "Cisco Nexus STP topology (SNMPv3)": SNMPv3 user, security level, auth/priv protocol, passphrases (password store), timeout, retries |
| `server_side_calls/special_agent.py` | server_side_calls v1 `SpecialAgentConfig` | Builds the command line. Passphrases are passed as `Secret` → `<id>:<store file>`, never plaintext |
| `libexec/agent_nxos_stp_tcn` | executable (Python) | SNMP collector: context discovery + per-context GETs, prints agent section |
| `agent_based/cisco_nexus_stp.py` | agent_based v2 | `AgentSection` + `CheckPlugin` "STP Topology VLAN %s" |
| `rulesets/check_parameters.py` | rulesets v1 `CheckParameters`, `DiscoveryParameters` | Thresholds (CRIT 12 h, WARN off, optional rate levels); VLAN include/exclude filter |
| `graphing/cisco_nexus_stp.py` | graphing v1 | Metrics, graphs, perfometer |
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
6. Print `<<<nxos_stp_tcn:sep(59)>>>` rows: `vlan;status;changes;timeticks;sysuptime_ticks`.

## Check logic

- Discovery: one service per VLAN row with status `ok` and valid numbers (after the optional VLAN filter).
  Contexts without STP data (noSuchInstance) are not discovered. Removed VLANs vanish at the next discovery.
- Changes = 0 → **OK** regardless of age: the timer then counts from STP start, not from a change.
- Otherwise `check_levels(age, levels_lower=...)`: default CRIT if age < 12 h, WARN disabled.
- TimeTicks wrap (2^32 cs ≈ 497 d): tracked in the value store. If the count is unchanged and the timer
  went backwards, 497.1 d is added, so a wrap can never look like a fresh change.
- Optional rate: `get_rate` on the change counter (changes/hour). Counter decrease (reboot or Counter32
  wrap) → skip one interval, no absurd rates. Off by default.
- Missing/errored VLAN at check time → UNKNOWN for that VLAN only.

## Credentials

- Stored only in the Checkmk password store and referenced by the special-agent rule.
- Checkmk passes `<id>:<password-store-file>` on the command line (`Secret`, pass_safely). The agent
  resolves them in memory.
- Temporary Net-SNMP config file: mode 0600 inside a mode-0700 temp dir, deleted in `finally`.
- Nothing credential-related in the source, tests, fixtures, docs or MKP.
- Note: the special agent cannot reuse the host's SNMP credential attribute (`HostConfig` has no SNMP
  fields), so the SNMPv3 settings are entered once in the rule, pointing at password-store entries.

## Host scope

The special-agent rule's conditions decide which hosts are monitored: explicit hosts, a folder, a tag, or
a label such as `stp_topology:monitor`. The plugin contains no host names. Hosts need the agent setting
"Configured API integrations, no Checkmk agent" (`special-agents`). Their SNMP checks keep running.
