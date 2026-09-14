# Nexus STP over SNMP — verified findings

These findings come from manual SNMP tests on production Nexus 9000 switches, compared against
`show spanning-tree detail` CLI output. Device names are neutral. The raw values are kept because the
tests use them. No credentials are recorded.

| Name used here | Model | NX-OS | Result |
|---|---|---|---|
| Core A, Core B | N9K-C93240YC-FX2 | 10.2(5) | **Supported:** per-VLAN STP data via numeric SNMPv3 contexts |
| ToR (FX) | N9K-C93180YC-FX | 10.2(6) | Serves data. Unresolved anomaly (see below), not in scope |
| ToR (FX3), 12 switches | N9K-C93180YC-FX3 | 10.4(5) | **No** BRIDGE-MIB STP scalars over SNMP |

Version 1.0 targets the Core A/B platform.

## Core A: first tests (SNMPv3 authPriv)

| # | Test | Result |
|---|------|--------|
| 1 | `cmk --snmpget` default context `.1.3.6.1.2.1.17.2.3.0` / `.2.4.0` | 2586192400 cs (~299 d 7 h 52 m) / 6 |
| 2 | sysUpTime | 2589606455 cs (~299 d 17 h 21 m) |
| 3 | `cmk --snmpwalk --oid .1.3.6.1.4.1.9.9.468` | 158 contexts: numeric (`1`,`10`,`200`…) **and** `vlan-<id>` for every VLAN |
| 4 | `cContextMappingTable` `.468.1.1.1` | cols .2/.3/.4 (VRF/topology/proto-instance names) empty; .5 = 3 nonVolatile; .6 = 1 active |
| 5 | `.468.1.5.1` (index = context name + `.1`) | col .2 = VLAN ID, 4-byte little-endian (`C8 00 00 00` = 200); .3 = 5 readOnly; .4 = 1 active |
| 6 | Net-SNMP v3 `-n vlan-200` | `.2.4.0` = Counter32 **37**; `.2.3.0` = 2586624300 cs |
| 7 | Net-SNMP v3 `-n vlan-10` | `.2.4.0` = **0**; `.2.3.0` = 2590140200 cs; sysUpTime 2590160436 cs → timer ≈ sysUpTime − ≤202 s |
| 8 | Net-SNMP v3 `-n vlan-30` | `.2.4.0` = **15**; `.2.3.0` = 2586873900 cs |

vacmContextTable (`.1.3.6.1.6.3.16.1.1.1.1`) returned nothing (not exposed to the monitoring user's view).

### Comparison with an older CLI capture

| VLAN | CLI count | SNMP count | CLI age + capture age | SNMP age | Δ |
|------|-----------|------------|-----------------------|----------|---|
| 1 (default ctx) | 6 | 6 | 25,863,097 s | 25,861,924 s (query time not stamped) | consistent |
| 200 (`vlan-200`) | 37 | 37 | 25,866,302 s | 25,866,243 s | 59 s |

The ~59 s offset is the same for every VLAN: the capture file's timestamp is written after the CLI's
"ago" values were computed.

### Behaviour observed
- BRIDGE-MIB STP scalars are per VLAN and are selected by SNMPv3 context.
- The default context is VLAN 1.
- The context → VLAN mapping can be discovered over SNMP (`.468.1.5.1.2`). NX-OS creates the rows
  automatically (readOnly).
- TimeTicks have 1-second resolution (values end in `00`). `dot1dStpTopChanges` is a Counter32.
- **Zero changes:** `dot1dStpTopChanges` = 0 and the timer ≈ sysUpTime, i.e. the timer counts from STP
  start, not from a change. On a freshly rebooted switch this looks like "changed minutes ago", so
  count = 0 must be treated as OK.
- A reboot is followed by a real burst of topology changes during convergence (last changes ~9 h after boot here).
- **Multi-OID GET inside a VLAN context:** only the first varbind is answered. Use one OID per GET.

### `vlan-<id>` contexts can return the wrong VLAN's data
VLAN 30 was created months after the switch last booted. CLI ground truth at the time of the test:
```
VLAN0004 ... Number of topology changes 15 last change occurred 7185:55:37 ago
VLAN0030 ... Number of topology changes 0 last change occurred 7195:03:20 ago
```
- Context `vlan-30` returned 15 / `7185:45:39`, which is **VLAN 4's data**.
- The mapping table is correct for both names (`30`/`vlan-30` → `1E 00 00 00`).
- **Numeric context `30`** returned 0 / `7195:15:15`, which is VLAN 30's real data (CLI ~12 min earlier: 0 / `7195:03:20`).
- Numeric context `200` returned 37 (correct, same as `vlan-200`) → numeric contexts are correct for
  VLANs created before and after boot.
- A new VLAN with zero changes shows a timer counting from STP start (≈ boot), not from VLAN creation.

**Conclusion:** use numeric contexts only.

### Unknown contexts
A request in context `3000` (no such VLAN) → `Timeout: No Response`. NX-OS silently drops SNMPv3
requests for unknown contexts. Only query contexts listed in `.468.1.5.1`, keep per-request timeouts
short, and isolate failures per VLAN.

## Final validation on Core A and Core B (numeric contexts vs fresh CLI)

Core A, VLANs created after boot:
| VLAN | CLI count / age | SNMP count / age | Δ age |
|------|-----------------|------------------|-------|
| 32  | 0 / 7197:57:47 | 0 / 7198:02:04 | 257 s |
| 120 | 0 / 7197:57:47 | 0 / 7198:02:04 | 257 s |
| 121 | 0 / 7197:57:47 | 0 / 7198:02:04 | 257 s |

Core B:
| VLAN | CLI count / age | SNMP count / age | Δ age |
|------|-----------------|------------------|-------|
| 1   | 9 / 3557:21:38   | 9 / 3557:25:40   | 242 s |
| 30  | 1 / 1199:55:19   | 1 / 1199:59:22   | 243 s |
| 200 | 120 / 28:44:13   | 120 / 28:48:16   | 243 s |

- Counts are identical, and the age offset is the same for every VLAN on a switch (the time between the
  CLI and SNMP runs) → **SNMP matches the CLI on both cores.**
- Core B default context (9) = VLAN 1 (9).
- Zero-change VLANs share the STP-start timer, so SNMP can't tell them apart. This doesn't matter for monitoring.

**Data source:** numeric contexts from `.1.3.6.1.4.1.9.9.468.1.5.1.2`, single-OID GETs per context,
BRIDGE-MIB `.1.3.6.1.2.1.17.2.3.0` / `.2.4.0`.

## ToR (FX3, NX-OS 10.4(5)): not supported

- The context mapping works: 72 contexts = 36 VLANs × (numeric + `vlan-`), and the VLAN list is identical
  to the CLI's STP VLAN list.
- The CLI shows normal STP activity (e.g. VLAN 113: 130 changes). 0-change VLANs have a timer ≈ uptime
  (148 d), as on the cores.
- SNMP contexts `120`, `vlan-120`, `113`, `vlan-113`: `.2.4.0` and `.2.3.0` → **`No Such Instance`**.
  Authentication succeeds and nothing times out.
- Default context: both absent as well.
- `snmpgetnext` in context `113`: `.17.1.2.0` (dot1dBaseNumPorts) = 10 and `.17.2.1.0`
  (dot1dStpProtocolSpecification) = 1. A walk of the dot1dStp scalars returns **only** `.17.2.1.0`.
  On Core A the same walk returns `.17.2.1.0`–`.17.2.14.0`.
- The ToR's SNMP user has the more privileged `network-admin` role (the cores use `network-operator`), so
  this is not a view/role restriction.
- Fleet survey (default context `dot1dStpTopChanges`): every 10.2(x) switch returns a value, and all
  12 FX3/10.4(5) switches return nothing. Support follows 10.4(5)/FX3, not the ToR role.
- No public Cisco documentation or bug found for this.

## ToR (FX, NX-OS 10.2(6)): unresolved anomaly
Serves per-VLAN data (context `1`: 115 changes), but its default context returned 11 changes. On the
cores, the default context equals VLAN 1. Not investigated further (out of scope).

## Detection data
| Platform | sysObjectID |
|---|---|
| N9K-C93240YC-FX2 | `.1.3.6.1.4.1.9.12.3.1.3.2010` |
| N9K-C93180YC-FX3 | `.1.3.6.1.4.1.9.12.3.1.3.2193` |

sysDescr example: `Cisco NX-OS(tm) Nexus9000 C93240YC-FX2, Software (NXOS 64-bit), Version 10.2(5)`.
`.1.3.6.1.4.1.9.12.3.1.3.*` is Cisco's generic chassis branch (also used by non-Nexus platforms). A
Nexus test would therefore be: sysObjectID starts with `.1.3.6.1.4.1.9.` **and** sysDescr contains `NX-OS`.
The extension itself selects hosts by rule, not by detection.

## Other notes
- TimeTicks wraps at 2^32 cs (~497.1 d). One VLAN 1 timer was already at ~299 d.
- A VLAN with a context but no STP instance was not observed on the cores. The collector treats
  `noSuchInstance` as "no STP data" and does not discover such VLANs.
