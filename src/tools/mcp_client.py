"""Synchronous facade over a persistent MCP client session.

LangGraph nodes and Streamlit callbacks are synchronous, while the MCP SDK is
async. This module runs one event loop in a background thread, launches the
tax-tool server as a stdio subprocess once per process, keeps the session
open, and exposes a blocking :meth:`TaxToolClient.call`.

There is deliberately **no in-process fallback**: if the MCP server is not
reachable the call raises :class:`MCPUnavailableError` and the case stops with
an error instead of computing numbers some other way.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import sys
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from src.config import PROJECT_ROOT


class MCPUnavailableError(RuntimeError):
    """The MCP tax-tool server could not be started or reached."""


class ToolCallError(RuntimeError):
    """A tool rejected its inputs (e.g. negative amount, unknown status)."""


class TaxToolClient:
    def __init__(self, startup_timeout: float = 30.0, call_timeout: float = 30.0) -> None:
        self._startup_timeout = startup_timeout
        self._call_timeout = call_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session = None
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._error: BaseException | None = None
        self._lock = threading.Lock()
        self.tool_names: list[str] = []
        self.calls = 0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._session is not None:
                return
            self._ready.clear()
            self._error = None
            self._thread = threading.Thread(target=self._run_loop, name="silverfile-mcp", daemon=True)
            self._thread.start()
        if not self._ready.wait(self._startup_timeout):
            raise MCPUnavailableError("Timed out starting the SilverFile MCP tax-tool server.")
        if self._error is not None:
            raise MCPUnavailableError(f"Could not start the MCP tax-tool server: {self._error}")

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except BaseException as exc:  # pragma: no cover - surfaced via start()
            self._error = exc
            self._ready.set()

    async def _serve(self) -> None:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        env = {"PYTHONPATH": str(PROJECT_ROOT), "PYTHONUNBUFFERED": "1"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                       env=env, cwd=str(PROJECT_ROOT))
        self._stop = asyncio.Event()
        errlog = open(os.devnull, "w")  # server logs stay out of the UI
        try:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.tool_names = sorted(t.name for t in listed.tools)
                    self._session = session
                    self._ready.set()
                    await self._stop.wait()
        except BaseException as exc:
            self._error = exc
            self._ready.set()
        finally:
            self._session = None
            errlog.close()

    def close(self) -> None:
        if self._loop and self._stop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread:
            self._thread.join(timeout=5)
        self._session = None

    # -- calls -------------------------------------------------------------
    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke ``tool`` and return its structured result dictionary."""
        if self._session is None:
            self.start()
        assert self._loop is not None
        started = time.perf_counter()
        future = asyncio.run_coroutine_threadsafe(self._session.call_tool(tool, arguments), self._loop)
        try:
            result = future.result(self._call_timeout)
        except FutureTimeout as exc:
            raise MCPUnavailableError(f"MCP tool {tool} timed out") from exc
        except Exception as exc:
            raise MCPUnavailableError(f"MCP tool {tool} failed: {exc}") from exc
        self.calls += 1
        text = " ".join(getattr(c, "text", "") for c in (result.content or []))
        if result.is_error:
            raise ToolCallError(text or f"{tool} returned an error")
        data = result.structured_content
        if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], dict):
            data = data["result"]
        if not isinstance(data, dict):
            data = json.loads(text)
        data["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return data


_client: TaxToolClient | None = None
_client_lock = threading.Lock()


def get_tax_tools() -> TaxToolClient:
    """Process-wide client (Streamlit reruns reuse the same server process)."""
    global _client
    with _client_lock:
        if _client is None:
            _client = TaxToolClient()
            atexit.register(_client.close)
        return _client
