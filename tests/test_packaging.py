# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the repository layout, the manifest and the .mkp builder."""

from __future__ import annotations

import ast
import json
import keyword
import sys
import tarfile

import pytest

from .conftest import PLUGIN_DIR, REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_mkp


@pytest.fixture(scope="module")
def manifest() -> dict:
    return build_mkp.load_manifest(REPO_ROOT / "package.manifest")


def test_manifest_matches_the_local_tree(manifest: dict) -> None:
    problems = build_mkp.check_manifest(manifest, build_mkp.scan_parts(REPO_ROOT))
    assert problems == [], "run 'python3 scripts/build_mkp.py --update-manifest'"


def test_versions_agree(manifest: dict) -> None:
    assert build_mkp.agent_version(REPO_ROOT) == manifest["version"]
    assert build_mkp.pyproject_version(REPO_ROOT) == manifest["version"]
    assert build_mkp.check_versions(REPO_ROOT, manifest) == []


def test_manifest_has_the_fields_checkmk_requires(manifest: dict) -> None:
    for key in (
        "name",
        "title",
        "version",
        "version.min_required",
        "version.packaged",
        "version.usable_until",
        "author",
        "description",
        "download_url",
        "files",
    ):
        assert key in manifest, key
    assert manifest["name"] == "nxos_stp_tcn"
    # 2.3 is supported: the tests run against the 2.3.0 plug-in APIs in CI as well
    assert manifest["version.min_required"] == "2.3.0"


def test_every_plugin_directory_is_present() -> None:
    for subdir in (
        "agent_based",
        "checkman",
        "graphing",
        "lib",
        "libexec",
        "rulesets",
        "server_side_calls",
    ):
        assert (PLUGIN_DIR / subdir).is_dir(), subdir


def test_the_special_agent_is_executable() -> None:
    agent = PLUGIN_DIR / "libexec" / "agent_nxos_stp_tcn"
    assert agent.stat().st_mode & 0o111, "agent_nxos_stp_tcn must be executable"


def test_every_check_plugin_has_a_checkman_page() -> None:
    """Each 'CheckPlugin(name=...)' needs a man page of the same name."""
    documented = {p.name for p in (PLUGIN_DIR / "checkman").iterdir() if p.is_file()}
    declared = set()
    for source in (PLUGIN_DIR / "agent_based").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "CheckPlugin"
            ):
                for kw in node.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        declared.add(kw.value.value)
    assert declared, "no CheckPlugin found"
    assert declared - documented == set(), f"missing checkman pages: {declared - documented}"


def test_choice_element_names_are_valid_python_identifiers() -> None:
    """Checkmk rejects a rule spec whose choice names are not identifiers."""
    offenders = []
    for source in (PLUGIN_DIR / "rulesets").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id
                in ("SingleChoiceElement", "MultipleChoiceElement", "CascadingSingleChoiceElement")
            ):
                for kw in node.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        name = kw.value.value
                        if not name.isidentifier() or keyword.iskeyword(name):
                            offenders.append(f"{source.name}: {name}")
    assert offenders == [], f"not valid Python identifiers: {offenders}"


def test_build_produces_an_installable_mkp(tmp_path, manifest: dict) -> None:
    target = build_mkp.build_mkp(REPO_ROOT, manifest, tmp_path)
    assert target.name == f"nxos_stp_tcn-{manifest['version']}.mkp"

    with tarfile.open(target, "r:gz") as tar:
        assert tar.getnames() == ["info", "info.json", "cmk_addons_plugins.tar"]
        assert json.loads(tar.extractfile("info.json").read()) == manifest
        part = tar.extractfile("cmk_addons_plugins.tar")
        with tarfile.open(fileobj=part, mode="r:") as inner:
            members = {m.name: m for m in inner.getmembers()}

    assert set(members) == set(manifest["files"]["cmk_addons_plugins"])
    # the agent keeps its executable bit, everything else does not get one
    assert members["nxos_stp_tcn/libexec/agent_nxos_stp_tcn"].mode == 0o755
    assert members["nxos_stp_tcn/agent_based/cisco_nexus_stp.py"].mode == 0o644
    # tar entries are owned by root so unpacking in a site is predictable
    assert all(m.uid == 0 and m.gid == 0 for m in members.values())


def test_the_info_member_is_readable_by_checkmk(tmp_path, manifest: dict) -> None:
    """Checkmk reads the 'info' member as a Python literal ..."""
    target = build_mkp.build_mkp(REPO_ROOT, manifest, tmp_path)
    with tarfile.open(target, "r:gz") as tar:
        info = ast.literal_eval(tar.extractfile("info").read().decode("utf-8"))
    assert info == manifest


def test_checkmk_package_reader_accepts_the_mkp(tmp_path, manifest: dict) -> None:
    """... and validates it with its own manifest model (cmk-mkp-tool)."""
    pytest.importorskip("cmk.mkp_tool")
    try:
        from cmk.mkp_tool import extract_manifest
    except ImportError:
        from cmk.mkp_tool._mkp import extract_manifest

    target = build_mkp.build_mkp(REPO_ROOT, manifest, tmp_path)
    packaged = extract_manifest(target.read_bytes())
    assert packaged.name == manifest["name"]
    assert packaged.version == manifest["version"]
    assert packaged.version_min_required == manifest["version.min_required"]
    assert packaged.author == manifest["author"]
    files = {str(f) for files in packaged.files.values() for f in files}
    assert files == set(manifest["files"]["cmk_addons_plugins"])
