#!/usr/bin/env python3
"""Parsing of VLAN ID lists such as "10, 20-30, 200".

Shared by the discovery ruleset (validation) and the check plugin (filtering).
"""

VLAN_MIN = 1
VLAN_MAX = 4094


def parse_vlan_ranges(spec: str) -> frozenset[int]:
    """Return the VLAN IDs described by a comma separated list of IDs and ranges.

    >>> sorted(parse_vlan_ranges("10, 20-22,200"))
    [10, 20, 21, 22, 200]

    Raises ValueError for anything that is not a valid VLAN ID or range.
    """
    vlans: set[int] = set()
    for token in spec.replace(";", ",").split(","):
        if not (token := token.strip()):
            continue
        low_text, is_range, high_text = token.partition("-")
        try:
            low = int(low_text)
            high = int(high_text) if is_range else low
        except ValueError:
            raise ValueError(f"Invalid VLAN entry: {token!r}") from None
        if not VLAN_MIN <= low <= high <= VLAN_MAX:
            raise ValueError(f"Invalid VLAN range: {token!r} (IDs must be {VLAN_MIN}-{VLAN_MAX})")
        vlans.update(range(low, high + 1))
    if not vlans:
        raise ValueError("No VLAN IDs given")
    return frozenset(vlans)
