"""Agent memory: durable case state versus bounded model context.

The full transcript and every fact live in the checkpointed graph state and
are never trimmed. What a model sees on each call is built here, separately:

* strategy **enabled** (default) - *selective recall*: a compact structured
  summary of confirmed facts and session decisions, the last few turns, and
  the current item (question or document) only.
* strategy **disabled** (``--no-context-strategy``) - the whole accumulated
  conversation is replayed on every call, as a naive chat thread would.

The summary is generated deterministically from state. It copies amounts
exactly as stored (or omits them); it never rounds, merges or invents values,
and SSNs are masked.
"""

from __future__ import annotations

from src.ssn import mask_ssn
from src.state import fact_value


def _fmt_value(fact_id: str, value) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if fact_id.endswith(".ssn") or fact_id.endswith("_ssn"):
        return mask_ssn(str(value))
    if fact_id == "dependents" and isinstance(value, list):
        return "; ".join(f"{d.get('first', '')} {d.get('last', '')} ({d.get('relationship', '')}, SSN {mask_ssn(d.get('ssn'))})"
                         for d in value) or "none"
    return str(value)


def confirmed_fact_lines(state: dict, labels: dict[str, str] | None = None) -> list[str]:
    labels = labels or {}
    lines = []
    for fact_id, fact in sorted((state.get("facts") or {}).items()):
        if fact.get("status") != "confirmed":
            continue
        label = labels.get(fact_id, fact_id)
        lines.append(f"- {label}: {_fmt_value(fact_id, fact.get('value'))}")
    return lines


def session_summary(state: dict, labels: dict[str, str] | None = None) -> str:
    """Compact structured summary of what is settled and what is open."""
    parts = ["CONFIRMED FACTS:"]
    parts += confirmed_fact_lines(state, labels) or ["- none yet"]
    docs = state.get("documents") or {}
    if docs:
        parts.append("DOCUMENTS:")
        for d in docs.values():
            parts.append(f"- {d.get('doc_type')} '{d.get('file_name')}' status={d.get('status')}")
    elig = state.get("eligibility") or {}
    if elig.get("status"):
        parts.append(f"ELIGIBILITY: {elig.get('status')}")
    events = [e for e in (state.get("human_events") or []) if e.get("status") == "resolved"]
    if events:
        parts.append("RESOLVED REVIEWS:")
        for e in events[-5:]:
            parts.append(f"- {e.get('reason_label')}: {e.get('resolution', {}).get('action')}")
    notes = (state.get("intake") or {}).get("notes_for_volunteer") or []
    if notes:
        parts.append("NOTED FOR VOLUNTEER: " + "; ".join(n.get("text", "") for n in notes[-3:]))
    return "\n".join(parts)


def intake_summary(state: dict) -> str:
    """Minimal session summary for interpreting one reply: which earlier
    questions exist (so corrections can name them), the filing status, and open
    follow-ups. Values are deliberately omitted - the reply's meaning never
    depends on them, and they stay in durable state."""
    intake = state.get("intake") or {}
    asked = intake.get("asked") or []
    parts = ["ANSWERED QUESTION IDS: " + (", ".join(asked) if asked else "none yet")]
    fs = fact_value(state, "filing_status")
    if fs:
        parts.append(f"FILING STATUS: {fs}")
    open_f = [f["id"] for f in intake.get("followups") or [] if f.get("status", "open") == "open"]
    if open_f:
        parts.append("OPEN FOLLOW-UPS: " + ", ".join(open_f))
    return "\n".join(parts)


def transcript_messages(transcript: list[dict]) -> list[dict]:
    """Convert stored transcript entries to alternating API messages."""
    msgs: list[dict] = []
    for entry in transcript:
        role = "assistant" if entry.get("role") == "assistant" else "user"
        text = entry.get("text") or ""
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + text
        else:
            msgs.append({"role": role, "content": text})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def build_intake_context(state: dict, question_text: str, user_text: str, *, strategy_enabled: bool,
                         recent_turns: int, labels: dict[str, str]) -> list[dict]:
    """Messages for one intake interpretation call (system prompt is separate)."""
    current = (f"CURRENT QUESTION: {question_text}\n"
               f"TAXPAYER'S REPLY: {user_text}\n"
               "Interpret the reply for the current question.")
    transcript = state.get("transcript") or []
    if strategy_enabled:
        recent = transcript[-recent_turns * 2:] if recent_turns > 0 else []
        recent_txt = "\n".join(f"{e.get('role')}: {e.get('text')}" for e in recent) or "(none)"
        content = (f"SESSION SUMMARY (authoritative, from case state):\n{intake_summary(state)}\n\n"
                   f"RECENT TURNS:\n{recent_txt}\n\n{current}")
        return [{"role": "user", "content": content}]
    history = transcript_messages(transcript)
    if history and history[-1]["role"] == "user":
        history[-1]["content"] += "\n\n" + current
    else:
        history.append({"role": "user", "content": current})
    return history


def build_document_context(prior: list[dict], current_blocks: list[dict], summary: str, *,
                           strategy_enabled: bool) -> list[dict]:
    """Messages for a document-extraction call in a multi-document thread.

    ``prior`` holds earlier ``{"user": [blocks], "assistant": "json text"}``
    turns from the same thread. With the strategy enabled only the summary
    and the current document are sent.
    """
    if strategy_enabled:
        return [{"role": "user", "content": [{"type": "text", "text": "SESSION SUMMARY:\n" + summary}]
                 + current_blocks}]
    msgs: list[dict] = []
    for turn in prior:
        msgs.append({"role": "user", "content": turn["user"]})
        msgs.append({"role": "assistant", "content": turn["assistant"]})
    msgs.append({"role": "user", "content": current_blocks})
    return msgs


def resume_summary(state: dict, labels: dict[str, str]) -> list[str]:
    """Plain-language 'here is what we already covered' for a returning taxpayer."""
    out = []
    name = fact_value(state, "tp.first_name")
    if name:
        out.append(f"Your name: {name} {fact_value(state, 'tp.last_name') or ''}".strip())
    for line in confirmed_fact_lines(state, labels):
        if any(k in line for k in ("first name", "last name")):
            continue
        out.append(line.lstrip("- "))
    return out
