#!/usr/bin/env python3
"""Build dist/nxos_stp_tcn-<version>.mkp from src/ without a Checkmk site.

Requires a Python environment with Checkmk's cmk-mkp-tool package installed.
Only the files listed in FILES are packaged (no __pycache__, tests, docs or captures).
"""

import io
import sys
import tarfile
import time
from pathlib import Path

from cmk.mkp_tool import Manifest, PackageName, PackagePart, PackageVersion

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "src" / "cmk_addons" / "plugins"
FAMILY = "nxos_stp_tcn"
VERSION = "1.0.0"

FILES = [
    "agent_based/cisco_nexus_stp.py",
    "checkman/nxos_stp_tcn",
    "graphing/cisco_nexus_stp.py",
    "lib/vlan_ranges.py",
    "libexec/agent_nxos_stp_tcn",
    "rulesets/check_parameters.py",
    "rulesets/special_agent.py",
    "server_side_calls/special_agent.py",
]


def main() -> int:
    files = [Path(FAMILY, name) for name in FILES]
    missing = [str(f) for f in files if not (PLUGINS_DIR / f).is_file()]
    if missing:
        sys.stderr.write(f"Missing files: {missing}\n")
        return 1

    manifest = Manifest(
        title="Cisco Nexus STP Topology Changes",
        name=PackageName(FAMILY),
        description=(
            "Monitors spanning-tree topology changes per VLAN on Cisco Nexus (NX-OS) switches "
            "via SNMPv3. A special agent discovers the VLAN contexts from "
            "CISCO-CONTEXT-MAPPING-MIB and reads BRIDGE-MIB dot1dStpTopChanges and "
            "dot1dStpTimeSinceTopologyChange per numeric VLAN context. One service per VLAN, "
            "configurable CRIT/WARN windows (default CRIT < 12 h), optional change-rate levels, "
            "VLAN include/exclude filter, graphs.\n\n"
            "Setup: create a rule 'Cisco Nexus STP topology changes (SNMPv3 VLAN contexts)', set "
            "the hosts to 'Configured API integrations, no Checkmk agent', run service discovery.\n"
            "Verified on Nexus 9000 C93240YC-FX2 / NX-OS 10.2(5).\n\n"
            "License: GNU General Public License v2 (GPLv2)."
        ),
        version=PackageVersion(VERSION),
        version_packaged="2.4.0",
        version_min_required="2.4.0",
        version_usable_until=None,
        author="John Jimenez & Cledir Justo",
        download_url="",
        files={PackagePart.CMK_ADDONS_PLUGINS: files},
    )

    target = ROOT / "dist" / f"{FAMILY}-{VERSION}.mkp"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(build_mkp(manifest, files))
    print(target)
    return 0


def _member(name: str, size: int, mode: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = size, mode, int(time.time())
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    return info


def build_mkp(manifest: Manifest, files: list[Path]) -> bytes:
    """Same layout as Checkmk's create_mkp(): info, info.json and one tar per package part.

    Checkmk's own builder shells out to GNU tar (--force-local), which macOS lacks, so the
    inner tar is written with Python's tarfile. The installer sets final permissions anyway
    (libexec executable, everything else 0644).
    """
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for rel in files:
            data = (PLUGINS_DIR / rel).read_bytes()
            mode = 0o755 if rel.parent.name == "libexec" else 0o644
            tar.addfile(_member(str(rel), len(data), mode), io.BytesIO(data))

    outer = io.BytesIO()
    with tarfile.open(fileobj=outer, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for name, data in (
            ("info", manifest.file_content().encode()),
            ("info.json", manifest.json_file_content().encode()),
            (f"{PackagePart.CMK_ADDONS_PLUGINS.ident}.tar", inner.getvalue()),
        ):
            tar.addfile(_member(name, len(data), 0o644), io.BytesIO(data))
    return outer.getvalue()


if __name__ == "__main__":
    sys.exit(main())
