"""Service layer: the only API the UI (and tests, CLI, Docker) use.

Keeps graph execution, persistence and validation out of UI callbacks. One
compiled graph and one MCP tool session are shared per process; each case is
a LangGraph thread persisted in SQLite, so a case survives browser reloads and
application restarts.

Trust boundary: taxpayer actions (``send_message``, ``add_upload``) can only
answer an intake question; reviewer actions (``resolve_review``) can only
answer a human-review event, and are validated against the pending event
before the graph is resumed.
"""

from __future__ import annotations

import hashlib
import io
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from src.agents.base import Runtime, utc_now
from src.agents.intake import progress
from src.agents.intake_script import FACT_LABELS
from src.config import SCHEMA_VERSION, TAX_YEAR, Settings, get_settings
from src.graph import RECURSION_LIMIT, build_graph
from src.hitl import ACTION_LABELS, DecisionError, validate_decision
from src.llm import build_llm
from src.memory import resume_summary
from src.state import STATUS_LABELS, new_case_state
from src.store import CaseStore

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
DOC_TYPES = ["W-2", "1099-INT", "1099-DIV", "1099-R", "SSA-1099"]


class ServiceError(RuntimeError):
    """A user-facing problem (bad upload, wrong case state, invalid decision)."""


class SilverFileService:
    def __init__(self, settings: Settings | None = None, llm=None, tools=None, overrides: dict | None = None) -> None:
        self.settings = settings or get_settings()
        for d in (self.settings.var_dir, self.settings.uploads_dir, self.settings.outputs_dir):
            d.mkdir(parents=True, exist_ok=True)
        if tools is None:
            from src.tools.mcp_client import get_tax_tools

            tools = get_tax_tools()
        self.tools = tools
        self.llm = llm or build_llm(self.settings)
        self.runtime = Runtime(llm=self.llm, tools=tools, settings=self.settings, overrides=overrides or {})
        self._conn = sqlite3.connect(str(self.settings.checkpoint_path), check_same_thread=False)
        self.checkpointer = SqliteSaver(self._conn)
        self.graph = build_graph(self.runtime, self.checkpointer)
        self.store = CaseStore(self.settings.db_path)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def _lock(self, case_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(case_id, threading.Lock())

    @staticmethod
    def _config(case_id: str) -> dict:
        return {"configurable": {"thread_id": case_id}, "recursion_limit": RECURSION_LIMIT}

    def _run(self, case_id: str, payload: Any) -> None:
        """Invoke the graph until it pauses (interrupt) or ends; record errors."""
        try:
            self.graph.invoke(payload, self._config(case_id))
            self._sync(case_id, error=None)
        except Exception as exc:  # keep the checkpoint; surface the error, never a false success
            self._sync(case_id, error=f"{type(exc).__name__}: {exc}"[:500])
            raise ServiceError(f"Processing stopped: {type(exc).__name__}: {exc}") from exc

    def _snapshot(self, case_id: str):
        snap = self.graph.get_state(self._config(case_id))
        if not snap or not snap.values:
            raise ServiceError(f"Unknown case {case_id}")
        return snap

    def pending(self, case_id: str) -> dict | None:
        snap = self._snapshot(case_id)
        for intr in snap.interrupts or ():
            return dict(intr.value)
        return None

    def _sync(self, case_id: str, error: str | None) -> None:
        snap = self.graph.get_state(self._config(case_id))
        v = snap.values or {}
        facts = {k: f.get("value") for k, f in (v.get("facts") or {}).items() if f.get("status") == "confirmed"}
        pend = None
        for intr in snap.interrupts or ():
            pend = intr.value
        lines = v.get("lines") or {}
        status = v.get("status", "intake")
        if error:
            status = "error"
        row = {
            "case_id": case_id, "created_at": v.get("created_at", utc_now()), "updated_at": utc_now(),
            "status": status,
            "taxpayer": f"{facts.get('tp.first_name', '')} {facts.get('tp.last_name', '')}".strip() or None,
            "filing_status": facts.get("filing_status"),
            "pending_kind": pend.get("kind") if pend else None,
            "pending_event_id": pend["event"]["id"] if pend and pend.get("kind") == "human_review" else None,
            "pending_reason": pend["event"]["reason_label"] if pend and pend.get("kind") == "human_review" else None,
            "pending_summary": pend["event"]["summary"] if pend and pend.get("kind") == "human_review" else None,
            "draft_version": (v.get("assembly") or {}).get("version"),
            "refund": (lines.get("34") or {}).get("value"), "owed": (lines.get("37") or {}).get("value"),
            "llm_mode": self.llm.mode, "error": error,
            "extra": {"open_events": sum(1 for e in v.get("human_events") or [] if e.get("status") != "resolved")},
        }
        self.store.upsert(row)

    # ------------------------------------------------------------------ cases
    def create_case(self) -> str:
        case_id = f"SF-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        state = new_case_state(case_id, utc_now(), TAX_YEAR, SCHEMA_VERSION)
        with self._lock(case_id):
            self._run(case_id, state)
        return case_id

    def list_cases(self, status: str | None = None) -> list[dict]:
        rows = self.store.list(status)
        for r in rows:
            r["status_label"] = STATUS_LABELS.get(r["status"], r["status"])
        return rows

    def view(self, case_id: str) -> dict:
        snap = self._snapshot(case_id)
        v = snap.values
        facts = {k: f.get("value") for k, f in (v.get("facts") or {}).items() if f.get("status") == "confirmed"}
        meta = self.store.get(case_id) or {}
        pend = None
        for intr in snap.interrupts or ():
            pend = dict(intr.value)
        return {
            "case_id": case_id, "status": meta.get("status") if meta.get("error") else v.get("status"),
            "status_label": STATUS_LABELS.get(meta.get("status") if meta.get("error") else v.get("status"), v.get("status")),
            "error": meta.get("error"), "pending": pend, "facts": facts, "facts_detail": v.get("facts") or {},
            "facts_version": v.get("facts_version"), "transcript": v.get("transcript") or [],
            "documents": v.get("documents") or {}, "extractions": v.get("extractions") or {},
            "source_facts": v.get("source_facts") or {}, "eligibility": v.get("eligibility") or {},
            "lines": v.get("lines") or {}, "provenance": v.get("provenance") or {}, "calc": v.get("calc") or {},
            "review": v.get("review") or {}, "assembly": v.get("assembly") or {},
            "human_events": v.get("human_events") or [], "intake": v.get("intake") or {},
            "routing": v.get("routing") or {}, "metrics": v.get("metrics") or [], "trace": v.get("trace") or [],
            "progress": progress(v), "resume_summary": resume_summary(v, FACT_LABELS),
            "created_at": v.get("created_at"), "llm_mode": self.llm.mode,
        }

    def retry(self, case_id: str) -> None:
        """Continue a case from its last checkpoint after an error."""
        with self._lock(case_id):
            self._run(case_id, None)

    # ------------------------------------------------------------------ taxpayer actions
    def add_upload(self, case_id: str, file_name: str, data: bytes, doc_type: str) -> dict:
        """Store an uploaded form image; returns a document record to attach to the next message."""
        if doc_type not in DOC_TYPES:
            raise ServiceError(f"Unknown form type {doc_type!r}.")
        if not data:
            raise ServiceError("The file is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ServiceError("The file is larger than 10 MB. Please upload a smaller photo or scan.")
        image_bytes, media_type = _normalise_image(data)
        sha = hashlib.sha256(data).hexdigest()
        doc_id = f"doc-{sha[:12]}"
        existing = (self._snapshot(case_id).values.get("documents") or {})
        if doc_id in existing and existing[doc_id].get("status") not in {"rejected"}:
            raise ServiceError("That exact file was already uploaded; it will only be used once.")
        folder = self.settings.uploads_dir / case_id
        folder.mkdir(parents=True, exist_ok=True)
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}[media_type]
        path = folder / f"{doc_id}.{ext}"
        path.write_bytes(image_bytes)
        return {"doc_id": doc_id, "doc_type": doc_type, "file_name": Path(file_name).name[:120], "sha256": sha,
                "path": str(path), "media_type": media_type, "source": "upload", "uploaded_at": utc_now(),
                "revision": int(existing.get(doc_id, {}).get("revision", -1)) + 1}

    def add_manual_document(self, case_id: str, doc_type: str, fields: dict[str, str], *, payer: str = "",
                            checkboxes: list[str] | None = None, code: str | None = None,
                            owner: str = "taxpayer") -> dict:
        """A non-W-2 form typed in by the taxpayer (recorded as direct user input)."""
        if doc_type == "W-2":
            raise ServiceError("Please upload a photo or scan of the W-2.")
        if doc_type not in DOC_TYPES:
            raise ServiceError(f"Unknown form type {doc_type!r}.")
        clean = {k: (v or "").strip() for k, v in fields.items()}
        body = repr((doc_type, sorted(clean.items()), payer, sorted(checkboxes or []), code, owner))
        sha = hashlib.sha256(body.encode()).hexdigest()
        return {"doc_id": f"man-{sha[:12]}", "doc_type": doc_type, "file_name": f"typed {doc_type} ({payer or 'payer'})",
                "sha256": sha, "path": None, "source": "manual", "manual_fields": clean, "payer": payer,
                "manual_checkboxes": checkboxes or [], "manual_code": code, "owner": owner,
                "uploaded_at": utc_now(), "revision": 0}

    def send_message(self, case_id: str, text: str, uploads: list[dict] | None = None) -> dict:
        with self._lock(case_id):
            pend = self.pending(case_id)
            if not pend or pend.get("kind") != "taxpayer_question":
                raise ServiceError("SilverFile isn't waiting for an answer right now"
                                   + (" - a Kushim volunteer is reviewing this case." if pend else "."))
            self._run(case_id, Command(resume={"kind": "taxpayer_message", "text": text or "",
                                               "uploads": uploads or [], "at": utc_now()}))
        return self.view(case_id)

    # ------------------------------------------------------------------ reviewer actions
    def resolve_review(self, case_id: str, event_id: str, *, action: str, reviewer: str, rationale: str,
                       evidence: str = "", fact_id: str | None = None, new_value: Any = None,
                       filing_status: str | None = None, question: str | None = None) -> dict:
        decision = {"kind": "reviewer_decision", "event_id": event_id, "action": action, "reviewer": reviewer,
                    "rationale": rationale, "evidence": evidence, "fact_id": fact_id, "new_value": new_value,
                    "filing_status": filing_status, "question": question, "at": utc_now()}
        with self._lock(case_id):
            pend = self.pending(case_id)
            if not pend or pend.get("kind") != "human_review":
                raise ServiceError("This case has no pending review (it may already have been resolved).")
            try:
                validate_decision(pend["event"], decision)
            except DecisionError as exc:
                raise ServiceError(str(exc)) from exc
            self._run(case_id, Command(resume=decision))
        return self.view(case_id)

    # ------------------------------------------------------------------ health
    def health(self) -> dict:
        info = {"llm_mode": self.llm.mode, "model": getattr(self.llm, "model", None), "mcp_ok": False,
                "mcp_tools": [], "var_dir": str(self.settings.var_dir)}
        try:
            self.tools.start()
            info["mcp_ok"] = True
            info["mcp_tools"] = list(self.tools.tool_names)
        except Exception as exc:
            info["mcp_error"] = str(exc)
        return info


def _normalise_image(data: bytes) -> tuple[bytes, str]:
    """Accept common image types and PDFs (first page); reject anything else."""
    from PIL import Image, UnidentifiedImageError

    if data[:5] == b"%PDF-":
        import pymupdf

        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
            png = doc[0].get_pixmap(dpi=200).tobytes("png")
        except Exception as exc:
            raise ServiceError("That PDF could not be opened.") from exc
        return png, "image/png"
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        fmt = img.format
    except (UnidentifiedImageError, OSError) as exc:
        raise ServiceError("That file isn't a readable image. Please upload a PNG, JPEG or PDF.") from exc
    if fmt not in IMAGE_TYPES:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    return data, IMAGE_TYPES[fmt]


def action_labels() -> dict[str, str]:
    return dict(ACTION_LABELS)
