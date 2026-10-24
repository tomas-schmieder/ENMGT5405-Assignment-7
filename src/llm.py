"""Model access for SilverFile agents.

Two interchangeable back ends implement :class:`LLM`:

* :class:`AnthropicLLM` - the Anthropic Messages API with JSON-schema
  structured outputs (``output_config.format``). Every call records real
  token usage, including cache fields, for the context-window experiment.
* :class:`OfflineLLM` - deterministic stand-ins supplied by each agent
  (keyword parsing for intake, OCR + layout parsing for W-2 images). Used for
  the automated test-suite and when no API key is configured. Offline calls
  report no token usage; they are never presented as model measurements.

Model output is untrusted: it is validated against a pydantic schema and the
agents re-check anything that matters deterministically.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Model call failed (network, refusal, or invalid structured output)."""


@dataclass
class LLMCall:
    data: Any
    usage: dict
    record: dict = field(default_factory=dict)


class LLM(Protocol):
    mode: str
    model: str

    def structured(self, *, agent: str, system: str, messages: list[dict], schema: type[T],
                   offline: Callable[[], T], purpose: str, max_tokens: int = 4000) -> LLMCall: ...


def image_block(data: bytes, media_type: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.standard_b64encode(data).decode("ascii")}}


def _record(agent: str, purpose: str, mode: str, model: str, usage: dict, started: float,
            ok: bool, error: str = "") -> dict:
    return {
        "id": f"llm-{uuid.uuid4().hex[:10]}", "kind": "model_call", "agent": agent, "purpose": purpose,
        "mode": mode, "model": model, "ok": ok, "error": error,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1), **usage,
    }


class OfflineLLM:
    """Runs the agent-supplied deterministic handler. No tokens are used."""

    mode = "offline"
    model = "offline-deterministic"

    def structured(self, *, agent, system, messages, schema, offline, purpose, max_tokens=4000):
        started = time.perf_counter()
        data = offline()
        if not isinstance(data, schema):
            data = schema.model_validate(data)
        usage = {"input_tokens": None, "output_tokens": None, "cache_creation_input_tokens": None,
                 "cache_read_input_tokens": None}
        return LLMCall(data=data, usage=usage, record=_record(agent, purpose, self.mode, self.model, usage,
                                                               started, True))


class AnthropicLLM:
    """Anthropic Messages API with JSON-schema structured output."""

    mode = "anthropic"

    def __init__(self, model: str, effort: str = "low", use_fallbacks: bool = True,
                 client: Any | None = None) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic(max_retries=2, timeout=120)
        self.model = model
        self.effort = effort
        self.use_fallbacks = use_fallbacks

    def _create(self, **kwargs: Any) -> Any:
        if self.use_fallbacks:
            try:
                return self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            except self._anthropic.BadRequestError as exc:
                # Some accounts/models may not accept server-side fallbacks; continue without them.
                if "fallback" not in str(exc).lower():
                    raise
                self.use_fallbacks = False
        return self.client.messages.create(**kwargs)

    def structured(self, *, agent, system, messages, schema, offline, purpose, max_tokens=4000):
        anthropic = self._anthropic
        started = time.perf_counter()
        json_schema = anthropic.transform_schema(schema)
        convo = list(messages)
        usage_total = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
                       "cache_read_input_tokens": 0}
        last_error = ""
        for attempt in range(2):
            try:
                resp = self._create(
                    model=self.model, max_tokens=max_tokens, system=system, messages=convo,
                    output_config={"format": {"type": "json_schema", "schema": json_schema},
                                   "effort": self.effort},
                )
            except anthropic.APIConnectionError as exc:
                raise LLMError(f"Could not reach the Anthropic API: {exc}") from exc
            except anthropic.AuthenticationError as exc:
                raise LLMError("Anthropic API key was rejected. Check ANTHROPIC_API_KEY.") from exc
            except anthropic.NotFoundError as exc:
                raise LLMError(f"Model {self.model!r} was not found. Check ANTHROPIC_MODEL.") from exc
            except anthropic.RateLimitError as exc:
                raise LLMError("Anthropic rate limit reached; try again shortly.") from exc
            except anthropic.APIStatusError as exc:
                raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
            u = resp.usage
            for key in usage_total:
                usage_total[key] += int(getattr(u, key, 0) or 0)
            if resp.stop_reason == "refusal":
                last_error = "model declined the request"
                break
            text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
            try:
                data = schema.model_validate(json.loads(text))
                rec = _record(agent, purpose, self.mode, getattr(resp, "model", self.model), usage_total,
                              started, True)
                rec["attempts"] = attempt + 1
                return LLMCall(data=data, usage=usage_total, record=rec)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = f"invalid structured output: {exc}"[:300]
                convo = convo + [
                    {"role": "assistant", "content": text or "(empty)"},
                    {"role": "user", "content": "That output did not match the required JSON schema "
                                                f"({last_error}). Return only valid JSON for the schema."},
                ]
        err = LLMError(f"{agent}: {last_error}")
        err.record = _record(agent, purpose, self.mode, self.model, usage_total, started, False, last_error)
        raise err


def build_llm(settings) -> LLM:
    mode = settings.resolved_llm_mode()
    if mode == "anthropic":
        return AnthropicLLM(settings.anthropic_model, settings.effort, settings.use_fallbacks)
    return OfflineLLM()
