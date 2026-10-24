"""Shared pytest fixtures.

Layers (docs/ACCEPTANCE_RESULTS.md):
* unit         - pure functions; agents with an in-process tool stub
* integration  - the real graph + the real MCP server over stdio + offline LLM
* live         - real Anthropic API calls (skipped unless ANTHROPIC_API_KEY is set)
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SILVERFILE_LLM_MODE", "offline")


class LocalTools:
    """Unit-test stand-in for the MCP client: calls the same pure functions
    in-process. Integration tests use the real MCP server instead."""

    tool_names: list[str] = []

    def start(self):
        return None

    def call(self, name: str, args: dict) -> dict:
        from src.tools import tax_calculations as tc

        res = getattr(tc, name)(**args)
        res["call_id"] = f"local-{uuid.uuid4().hex[:8]}"
        res["transport"] = "in-process (unit test)"
        return res


@pytest.fixture
def local_tools():
    return LocalTools()


@pytest.fixture
def settings(tmp_path):
    from src.config import get_settings

    s = get_settings()
    s.var_dir = tmp_path / "var"
    s.llm_mode = "offline"
    s.fault_injection = ""
    return s


@pytest.fixture
def runtime(settings, local_tools):
    from src.agents.base import Runtime
    from src.llm import OfflineLLM

    return Runtime(llm=OfflineLLM(), tools=local_tools, settings=settings)


@pytest.fixture(scope="session")
def mcp_tools():
    from src.tools.mcp_client import TaxToolClient

    client = TaxToolClient()
    client.start()
    yield client
    client.close()


@pytest.fixture
def service_factory(tmp_path, mcp_tools):
    """Build services sharing one var dir (to simulate restarts) and the real MCP server."""
    from src.config import get_settings
    from src.llm import OfflineLLM
    from src.service import SilverFileService

    def make(fault: str = "", overrides: dict | None = None, var_dir: Path | None = None):
        s = get_settings()
        s.var_dir = var_dir or (tmp_path / "var")
        s.llm_mode = "offline"
        s.fault_injection = fault
        return SilverFileService(settings=s, llm=OfflineLLM(), tools=mcp_tools, overrides=overrides)

    return make
