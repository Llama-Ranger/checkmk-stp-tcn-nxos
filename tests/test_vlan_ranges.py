# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
import pytest
from cmk_addons.plugins.nxos_stp_tcn.lib.vlan_ranges import parse_vlan_ranges


def test_ids_and_ranges() -> None:
    assert parse_vlan_ranges("10, 20-22;200") == {10, 20, 21, 22, 200}


@pytest.mark.parametrize("spec", ["", "abc", "0", "4095", "30-20", "-5", "10,,x"])
def test_invalid(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_vlan_ranges(spec)
