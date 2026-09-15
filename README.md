# nxos_stp_tcn: Cisco Nexus STP Topology Changes (Checkmk 2.4 / 2.5)

[![build](https://github.com/Llama-Ranger/checkmk-stp-tcn-nxos/actions/workflows/build.yml/badge.svg)](https://github.com/Llama-Ranger/checkmk-stp-tcn-nxos/actions/workflows/build.yml)

A Checkmk extension (MKP) that monitors spanning-tree topology changes of **every VLAN** on Cisco Nexus
switches over SNMPv3. One `STP Topology` service per switch lists all VLANs, names the VLANs with a
recent topology change, and draws one graph per VLAN. Alert windows are configurable. There is no CLI
scraping and no per-switch custom check.

| | |
|---|---|
| Package | `nxos_stp_tcn-<version>.mkp` from the [releases page](../../releases), or build it with `python3 scripts/build_mkp.py` |
| Checkmk | 2.4.x and 2.5.x (Check API v2, Rulesets API v1, Graphing API v1, Server-side calls API v1) |
| Verified devices | Nexus 9000 **C93240YC-FX2, NX-OS 10.2(5)** |
| Not supported | Nexus 9000 C93180YC-FX3, NX-OS 10.4(5): the switch serves no BRIDGE-MIB STP objects over SNMP |
| Authors | John Jimenez & Cledir Justo |
| License | GNU General Public License v2 or later (GPL-2.0-or-later), see [LICENSE](LICENSE) |

Background and evidence: [docs/snmp-findings.md](docs/snmp-findings.md) (SNMP-vs-CLI comparisons) and
[docs/architecture.md](docs/architecture.md).

---

## 1. What it monitors

One service per switch, **`STP Topology`**, covering all VLANs. For example:

```
STP Topology   CRIT   1 of 79 VLANs: VLAN 200 changed 2 hours 14 minutes ago
STP Topology   OK     79 VLANs, no recent topology change, most recent: VLAN 200 1 day 4 hours ago
```

The service details list every VLAN, e.g.
`VLAN 200: 120 topology changes, last change 2 hours 14 minutes ago - CRIT: topology change within the last 12 hours 0 minutes`.
The service has **one graph per VLAN** (time since that VLAN's last topology change), plus switch-wide graphs.

Data per VLAN (BRIDGE-MIB, read in the VLAN's SNMPv3 context):

| Object | OID | Use |
|---|---|---|
| dot1dStpTopChanges | `1.3.6.1.2.1.17.2.4.0` | cumulative topology changes (Counter32) |
| dot1dStpTimeSinceTopologyChange | `1.3.6.1.2.1.17.2.3.0` | TimeTicks (1/100 s) → seconds since last change |
| sysUpTime | `1.3.6.1.2.1.1.3.0` | details only: switch uptime at the last change |
| cContextMappingTable col. 2 | `1.3.6.1.4.1.9.9.468.1.5.1.2` | VLAN context discovery |

## 2. How Nexus VLAN contexts work (verified)

- NX-OS creates two read-only SNMPv3 contexts per VLAN automatically: `<id>` (e.g. `200`) and `vlan-<id>`.
  CISCO-CONTEXT-MAPPING-MIB lists them; the VLAN ID is a 4-byte little-endian value (`C8 00 00 00` = 200).
- The default context equals VLAN 1.
- **Numeric contexts are correct**. On NX-OS 10.2(5), `vlan-<id>` returned **another VLAN's data** for VLANs
  created after the last reboot, so the extension uses numeric contexts only.
- A request for a context that does not exist is silently dropped (timeout).
- Inside a VLAN context NX-OS answers only the first OID of a multi-OID GET, so one OID is requested per GET.

## 3. Architecture (why a special agent)

Checkmk's native SNMP sections cannot do per-VLAN contexts here (verified in the 2.4.0/2.5.0 source):
the context list is a static rule, and scalar OIDs that are identical in every context are dropped as
duplicates, so only one VLAN would survive. The extension therefore uses an **SNMP special agent**:

```
Checkmk (rule "Cisco Nexus STP topology changes (SNMPv3 VLAN contexts)")
  └─ server_side_calls → libexec/agent_nxos_stp_tcn  (Net-SNMP, SNMPv3)
        1. walk CISCO-CONTEXT-MAPPING-MIB (default context)  → VLAN list
        2. per numeric VLAN context: GET .17.2.4.0, GET .17.2.3.0   (parallel, isolated per VLAN)
        3. print <<<nxos_stp_tcn>>> section
  └─ agent_based check "STP Topology" (all VLANs) → rulesets → one metric/graph per VLAN
```

Source tree (`local/lib/python3/cmk_addons/plugins/nxos_stp_tcn/`, installed to `~/local/lib/python3/cmk_addons/plugins/nxos_stp_tcn/`):

```
agent_based/cisco_nexus_stp.py      section + check plugin
rulesets/special_agent.py           rule "Cisco Nexus STP topology changes (SNMPv3 VLAN contexts)"
rulesets/check_parameters.py        rule "Cisco Nexus STP topology changes" (thresholds, VLAN filter)
server_side_calls/special_agent.py  builds the agent command line
libexec/agent_nxos_stp_tcn          the special agent (SNMP collector)
graphing/cisco_nexus_stp.py         metrics (one per VLAN), graphs, perfometer
lib/metric_names.py                 per-VLAN metric name (shared)
lib/vlan_ranges.py                  VLAN list parsing (shared)
checkman/nxos_stp_tcn               man page
```

### How often the switch is queried

By default on every check: about 2 × (number of VLANs) SNMP GETs. A core with ~80 VLANs takes roughly half a
minute of a one-minute check interval, which is a lot for data that changes rarely.

Set **"Query the switch at most every"** in the special-agent rule (e.g. 1 hour). The agent then stores its
answer in `$OMD_ROOT/tmp/check_mk/cache/nxos_stp_tcn.<host>` and re-serves it until it reaches that age. The
file holds one host's section body and no credentials; the site's `tmp` is cleared on restart, so the first
check after a restart collects again.

Do **not** raise the host's check interval instead. That interval governs the host's `Check_MK` service,
which fetches *every* data source of the host, so the switch's normal SNMP checks would slow down with it.
The cache slows down this agent only.

While the cache is served, the section carries `cached(<collection time>,<validity>)`. Checkmk then knows how
old the data is, the service does not go stale between two collections, and the change rate is measured
between collections rather than between checks. The reported "time since the last change" is frozen between
collections too, so with a one-hour cache it advances in one-hour steps.

## 4. Required SNMP configuration

Nothing changes on the switches. You need:
- An SNMPv3 user on the Nexus with read access (the `network-operator` role is sufficient).
- The user, protocols and passphrases entered **once** in the special-agent rule. Store the passphrases in
  **Setup → General → Passwords** and select them from the rule.

**Why can't it reuse the SNMP credentials the host already has?** Checkmk gives a special agent only the
host name, alias, IP addresses and macros; the host's SNMP credentials are not part of that interface. The
host's SNMP credentials are also stored as plain values, not as a password-store entry that a second rule
could point at (verified in the Checkmk 2.4.0 and 2.5.0 source). Checkmk's own SNMP fetcher, which does use
those credentials, cannot query per-VLAN contexts correctly (see section 3). So the special agent needs its
own copy, entered once.

### How credentials stay protected
- The rule references password-store entries. Checkmk passes only `<id>:<store file>` on the command line.
- The agent resolves the passphrase in memory (Checkmk 2.5: `cmk.password_store.v1_unstable`; 2.4:
  `cmk.utils.password_store`) and writes a Net-SNMP config file with mode 0600 in a private 0700 temp directory.
  `SNMPCONFPATH` points at it and the directory is deleted after every run.
  Passphrases and the user name never appear in `ps`, the command line, logs or output.
- The package, tests and docs contain no credentials.

## 5. Which hosts are monitored (host selection)

Detection is by **rule**, not by guessing: the special-agent rule's conditions decide which hosts are queried.
Use explicit host names, a folder, a host tag, or a host label (recommended, e.g. `stp_topology:monitor`).
No host names are in the code. For reference, Nexus identity: sysObjectID `.1.3.6.1.4.1.9.12.3.1.3.*` plus
sysDescr containing `NX-OS` (FX2: `…3.2010`, FX3: `…3.2193`).

If the rule is ever applied to a switch without these objects (e.g. a 10.4(5) FX3), no services are
discovered. If the switch has no VLAN context table at all, the host's "Check_MK" service reports
`Cannot read the VLAN context table` or `no numeric VLAN contexts`.

## 6. Service discovery

- One `STP Topology` service per switch, discovered when at least one VLAN returns valid STP data.
- VLANs are evaluated at every check: a VLAN added on the switch appears in the service (and gets its graph)
  without a new discovery; a deleted VLAN simply drops out of the list.
- VLANs without STP data (`noSuchInstance`) are listed in the details as not monitored.
- Optional filter in the service rule (section 7): all VLANs (default), only listed VLANs, or all except
  listed (`10, 20-30, 200`).

## 7. Thresholds (GUI)

**Setup → Services → Service monitoring rules → "Cisco Nexus STP topology changes"**, condition: host.
Every setting applies to each VLAN; the service takes the state of the worst VLAN.

| Setting | Default | Meaning |
|---|---|---|
| Critical if the last topology change of a VLAN was within | **12 hours** | |
| Warning if the last topology change of a VLAN was within | not set (no WARN) | must be longer than the CRIT window |
| Upper levels on the topology change rate of a VLAN | no levels | changes/hour, e.g. WARN 6, CRIT 30 |
| VLANs to monitor | all VLANs with STP data | or only / all except listed VLANs (`10, 20-30, 200`) |
| State if a VLAN cannot be queried | UNKNOWN | the VLAN is listed; all other VLANs are still evaluated |

Examples:
- Default: any VLAN changed < 12 h ago → CRIT, else OK.
- Override: CRIT = 2 hours, WARN = 12 hours → a change < 2 h ago CRIT, 2–12 h WARN, else OK. No code changes.

Checkmk notifies on state changes. While the service is already CRIT because of one VLAN, a change on a
second VLAN updates the summary but raises no new notification; use periodic notifications if you want one.

A VLAN with **0** topology changes is always OK: without any change NX-OS's timer counts from spanning-tree
start (e.g. a reboot). A naive "last change < 12 h" check would therefore raise a false CRIT for 12 hours
after every reboot.

## 8. Metrics

| Metric | Unit | Meaning |
|---|---|---|
| `stp_vlan_<id>_seconds_since_last_change` | time | per VLAN: seconds since that VLAN's last topology change (since STP start if there never was one) |
| `stp_seconds_since_last_change` | time | switch-wide: the most recent topology change on any VLAN |
| `stp_topology_changes_total` | count | switch-wide: sum of the cumulative topology changes of all VLANs (resets on reboot) |
| `stp_topology_changes_rate` | /h | switch-wide: sum of the per-VLAN change rates over the last check interval; a VLAN whose counter decreased (reboot, Counter32 wrap) contributes no rate for that interval |

The per-VLAN metric definitions are generated for all VLAN IDs 1–4094, so each has a title
("VLAN 200: time since last STP topology change") and time units.

## 9. Graphs

| Graph | Shows |
|---|---|
| VLAN `<id>`: time since last STP topology change | one graph per VLAN: rises steadily, drops to ~0 at each change of that VLAN |
| Time since last STP topology change (any VLAN) | the same for the switch as a whole |
| STP topology change activity (all VLANs) | change rate per hour (area); spikes show instability |
| STP topology changes (all VLANs, cumulative) | the counter; steps show when changes happened |

Perfometer: time since the most recent change on any VLAN (0–7 days focus).

## 10. Installation (Checkmk 2.4 / 2.5)

The package requires Checkmk 2.4.0 or later. Do not install it on 2.3 or older.

1. Download `nxos_stp_tcn-<version>.mkp` from the [releases page](../../releases) (or build it, see
   [Development](#17-development)) and copy it to the Checkmk server.
2. As the site user: `mkp add nxos_stp_tcn-<version>.mkp && mkp enable nxos_stp_tcn <version>`
   (or **Setup → Maintenance → Extension packages → Upload package**).
3. **Setup → General → Passwords**: add the SNMPv3 auth (and privacy) passphrase.
4. For each Nexus host to monitor → **Properties → Monitoring agents → Checkmk agent / API integrations:
   "Configured API integrations, no Checkmk agent"**. Leave SNMP as it is; the SNMP checks keep running.
5. **Setup → Agents → Other integrations → "Cisco Nexus STP topology changes (SNMPv3 VLAN contexts)"**:
   create a rule with user, protocols and the stored passwords. Condition: the hosts (or a host label).
6. Run service discovery on the hosts and accept the `STP Topology` service. Activate changes.

## 11. Validation

```bash
mkp list | grep nxos_stp_tcn                       # installed and enabled
cmk -d <HOST> | sed -n '/<<<nxos_stp_tcn/,/<<</p' | head -20   # raw section from the special agent
cmk -II <HOST> && cmk -O                        # or discovery in the GUI
cmk -n <HOST> | grep 'STP Topology'             # check results without submitting
```

Do **not** use `cmk -D` or `-vv`/`--debug` output for sharing: they can show the host's normal SNMP credentials.

Compare against the switch CLI for a few VLANs (count must match; age differs by the time between runs):

```
show clock
show spanning-tree vlan 1,30,200 detail | egrep "executing|topology changes"
```

Then check the rules: the default gives CRIT only for changes < 12 h. Set CRIT 2 h / WARN 12 h for one switch
and confirm WARN for a VLAN that changed 2–12 h ago. The per-VLAN graphs appear after a few check cycles; the
rate metric needs two check intervals.

## 12. Upgrade notes: Checkmk 2.5

- Same MKP. All APIs used exist unchanged in 2.5 (verified against the 2.5.0 source; tests run against both).
- Password store: 2.5 uses the public `cmk.password_store.v1_unstable` API ("unstable" by Checkmk's
  naming). The agent falls back to the 2.4 API automatically. After the upgrade, run `cmk -d <HOST>` once
  to confirm the agent still reads its passwords.
- 2.5 renames editions (Raw → Community, etc.). No effect on this package.
- `version.usable_until` is not set, so the package stays enabled across upgrades. Re-test before upgrading
  to 2.6.

### Upgrading the package from 1.0.0 to 2.0.0

2.0.0 replaces the `STP Topology VLAN <id>` services with one `STP Topology` service (see CHANGELOG):
1. Install the new MKP and run service discovery on the hosts: the per-VLAN services vanish, one
   `STP Topology` service appears. The per-VLAN graph history of 1.0.0 is not carried over.
2. Re-create threshold rules without a VLAN condition, and move a VLAN filter from the removed discovery
   rule "Cisco Nexus STP topology VLAN discovery" into "Cisco Nexus STP topology changes".
3. The special-agent rule and its credentials stay as they are.

## 13. Troubleshooting

| Symptom | Check |
|---|---|
| No `STP Topology` service | Host agent setting (step 4). Does the rule match the host? `cmk -d <host>` shows the section? |
| Check_MK service: `Cannot read the VLAN context table: Timeout` | IP/port, SNMPv3 user/protocols/passphrases in the rule, switch ACL for the Checkmk server |
| `Cannot read password … from the Checkmk password store` | The selected password entry exists and the rule points at it |
| `STP Topology` UNKNOWN "1 VLAN without data: VLAN 30" | That VLAN's context did not answer (just deleted, or transient SNMP loss); the details say why. The state is configurable (section 7) |
| A VLAN listed as "No spanning-tree data (not monitored)" | STP does not run on that VLAN; nothing to do |
| No service on a 10.4(5) FX3 switch | Expected: NX-OS 10.4(5) FX3 serves no BRIDGE-MIB STP objects |

Manual SNMP cross-check (run yourself; prompts keep passphrases out of history and command lines as far as Net-SNMP allows):

```bash
read -rs -p 'Auth pass: ' SA; echo; read -rs -p 'Priv pass: ' SX; echo    # run this line on its own
snmpget -v3 -l authPriv -u <SNMP_USER> -a <AUTH_PROTOCOL> -A "$SA" -x <PRIV_PROTOCOL> -X "$SX" -n <VLAN_ID> -On <HOST> 1.3.6.1.2.1.17.2.4.0
snmpget -v3 -l authPriv -u <SNMP_USER> -a <AUTH_PROTOCOL> -A "$SA" -x <PRIV_PROTOCOL> -X "$SX" -n <VLAN_ID> -On <HOST> 1.3.6.1.2.1.17.2.3.0
unset SA SX
```

## 14. Known limitations

- Verified only on C93240YC-FX2 / NX-OS 10.2(5). C93180YC-FX3 / 10.4(5) exposes no data. C93180YC-FX
  / 10.2(6) serves data, but its default context did not match context `1`; this was not investigated.
- VLANs without a numeric context are skipped (a `vlan-<id>`-only fallback is deliberately not used).
- With zero changes the timer only shows time since STP start, so it carries no change information (reported OK).
- TimeTicks wrap after ~497 days without a change. The check compensates using its stored previous value; if
  monitoring starts or restarts right after a wrap, one false "recent change" can appear.
- A reboot produces a real burst of topology changes during convergence. This is reported as such (CRIT for
  the window). The details show the switch uptime at each VLAN's last change to recognise it.
- One service means one state: a second VLAN changing while the service is already CRIT raises no new
  notification (see section 7).
- One metric per VLAN: a core with ~80 VLANs records ~80 metrics in one service (plus 3 switch-wide).
- Passphrases containing `"` or `\` are escaped for Net-SNMP's config parser but were not tested against a switch.
- Each collection runs about 2 × (number of VLANs) SNMP GETs per switch (4 in parallel by default).
  Without a cache that happens on every check; see "How often the switch is queried" in section 3.
- The Checkmk 2.4 password-store access uses the internal `cmk.utils.password_store.lookup` (no public API in 2.4).

## 15. Migrating from a CLI-scraping check

A common predecessor is a script that parses saved `show spanning-tree detail` output, run as one custom
check per switch. The new `STP Topology` service doesn't collide with such checks, so both can run side by
side.

1. Install the MKP (section 10). Leave the old checks untouched.
2. Enable the rule for one switch; discover; compare with the switch CLI (section 11).
3. Add the remaining switches; compare.
4. Run old and new in parallel for an agreed period. First make sure the old check's input is still
   current: scripts that read saved CLI captures silently keep reporting OK if the collection job stops.
5. Confirm thresholds, graphs and notifications (e.g. test a CRIT 2 h / WARN 12 h override).
6. Confirm every switch and VLAN is covered (compare with `show spanning-tree summary`).
7. Disable (don't delete) the old custom-check rules and activate changes. Keep the old scripts for rollback.
8. Remove the old rules and scripts after the observation period.

## 16. Rollback

1. Disable or delete the "Cisco Nexus STP topology changes (SNMPv3 VLAN contexts)" rule. Optionally
   `mkp disable nxos_stp_tcn <version>` (or `mkp remove nxos_stp_tcn <version>`).
2. Run service discovery on the hosts and remove the vanished `STP Topology` service.
3. Set the hosts' agent setting back to its previous value (typically "No API integrations, no Checkmk agent").
4. Re-enable the previous checks (if they were only disabled), then activate changes.

## 17. Development

The repository mirrors a site's layout: everything below `local/` can be copied 1:1 into `~/local/` of a
Checkmk 2.4/2.5 test site. `package.manifest` lists the packaged files and holds the version.

The tests run against Checkmk's **real** plug-in APIs, installed from the Checkmk source of the release
branch (they are not on PyPI). CI does exactly this for 2.4.0 (Python 3.12) and 2.5.0 (Python 3.13).
Clone outside the repository so ruff and git don't see it:

```bash
# Checkmk 2.4 (for 2.5: --branch 2.5.0, python3.13, packages cmk-plugin-apis cmk-mkp-tool, plus cryptography)
git clone --depth 1 --filter=blob:none --sparse --branch 2.4.0 https://github.com/Checkmk/checkmk.git ../checkmk-2.4.0
git -C ../checkmk-2.4.0 sparse-checkout set packages/cmk-agent-based packages/cmk-rulesets \
    packages/cmk-graphing packages/cmk-server-side-calls packages/cmk-mkp-tool
python3.12 -m venv .venv
.venv/bin/pip install pytest pydantic ruff
# editable installs: building wheels from the partial checkout fails, -e works
for p in cmk-agent-based cmk-rulesets cmk-graphing cmk-server-side-calls cmk-mkp-tool; do
    .venv/bin/pip install -e ../checkmk-2.4.0/packages/$p
done

.venv/bin/python -m pytest -q                        # tests
.venv/bin/ruff check . && .venv/bin/ruff format --check .   # lint, as in CI
python3 scripts/build_mkp.py --check                 # manifest and version consistency only
python3 scripts/build_mkp.py                         # -> dist/nxos_stp_tcn-<version>.mkp
python3 scripts/build_mkp.py --update-manifest       # after adding/removing files below local/
```

### CI and releases

`.github/workflows/build.yml` runs on every push to `main` and on pull requests:
- ruff lint and format check, manifest and version check
- tests against Checkmk 2.4.0 and 2.5.0
- MKP build, uploaded as the `mkp` workflow artifact

To release, bump `version` in `package.manifest`, `pyproject.toml` and `__version__` in
`libexec/agent_nxos_stp_tcn`, update `CHANGELOG.md`, and push a tag `v<version>`. The workflow checks that
the tag matches the package version, builds the `.mkp` and attaches it to a GitHub release.

## 18. Future enhancements

- Support for NX-OS releases that stop serving BRIDGE-MIB STP objects (e.g. via NX-API).
- Optional "ignore changes within N minutes after a reboot" (sysUpTime is already collected).
- Per-VLAN root-bridge / root-port change detection (dot1dStpDesignatedRoot, `.17.2.5.0`).
- Inventory of STP mode/priority per VLAN.

## License

Copyright (C) 2026 John Jimenez & Cledir Justo

This program is free software; you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation; either version 2 of the
License, or (at your option) any later version (SPDX: `GPL-2.0-or-later`). It is distributed in the
hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [LICENSE](LICENSE) file for the full
text of the GNU General Public License version 2.
