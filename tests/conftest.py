import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PLUGIN_DIR = SRC / "cmk_addons" / "plugins" / "nxos_stp_tcn"

sys.path.insert(0, str(SRC))


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
