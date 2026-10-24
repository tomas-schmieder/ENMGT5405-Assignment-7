"""Shared runtime handed to every agent node.

Agents receive their dependencies (model client, MCP tool client, settings,
clock) through :class:`Runtime` so tests can substitute fakes - for example a
deliberately faulty agent to exercise the loop guard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from src.config import Settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Runtime:
    llm: Any
    tools: Any
    settings: Settings
    now: Callable[[], str] = utc_now
    overrides: dict[str, Callable] = field(default_factory=dict)  # agent name -> replacement node (tests)

    def tool(self, name: str, args: dict, metrics: list) -> dict:
        """Call an MCP tool and record a metric entry."""
        result = self.tools.call(name, args)
        metrics.append({"id": result.get("call_id"), "kind": "tool_call", "tool": name,
                        "at": self.now(), "elapsed_ms": result.get("elapsed_ms"),
                        "transport": result.get("transport")})
        return result


def flat_facts(state: dict) -> dict[str, Any]:
    """fact_id -> value for confirmed facts only (unknown is simply absent)."""
    return {k: f.get("value") for k, f in (state.get("facts") or {}).items() if f.get("status") == "confirmed"}
