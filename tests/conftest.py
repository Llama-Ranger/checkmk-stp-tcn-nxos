# Cisco Nexus STP topology change monitoring for Checkmk (nxos_stp_tcn)
# Copyright (C) 2026 John Jimenez & Cledir Justo
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared test fixtures.

The plug-ins live in ``local/lib/python3`` exactly as in a site, so that
directory is put on ``sys.path``. The tests import Checkmk's real plug-in APIs
(installed from the Checkmk source, see README "Development").
"""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON3_DIR = REPO_ROOT / "local" / "lib" / "python3"
PLUGIN_DIR = PYTHON3_DIR / "cmk_addons" / "plugins" / "nxos_stp_tcn"

if str(PYTHON3_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON3_DIR))


@pytest.fixture(scope="session")
def agent_module() -> ModuleType:
    """The special agent executable (no .py suffix) loaded as a module."""
    path = PLUGIN_DIR / "libexec" / "agent_nxos_stp_tcn"
    loader = importlib.machinery.SourceFileLoader("agent_nxos_stp_tcn", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module
