"""Intake agent - the only agent that talks to the taxpayer.

Responsibilities: ask one question at a time, record answers as confirmed
facts with direct-input provenance, accept corrections and "go back", relay
follow-up questions written by other agents or reviewers, collect document
uploads, and notice conversational red flags (advice requests, signs of
exploitation, out-of-scope situations, a request for a person).

Constraints (assignment §4): Intake never does arithmetic and never
interprets tax rules. It records facts; the Eligibility & Rules agent decides
what they mean. Follow-up questions that contain amounts are written by the
Rules agent from MCP tool output and relayed verbatim.

Each call pauses the graph with a LangGraph ``interrupt`` carrying the next
question; the taxpayer's reply resumes it. Everything before ``interrupt``
is deterministic, so LangGraph's node replay on resume is safe.
"""

from __future__ import annotations

import re
from typing import Any

from langgraph.types import interrupt

from src.agents.base import Runtime, flat_facts
from src.agents.intake_script import (CONFIRM_QUESTION_ID, DEPENDENT_FIELDS, DOC_COUNT_FACTS, FACT_LABELS,
                                      QUESTIONS, QUESTIONS_BY_ID, UPLOAD_QUESTION_ID, Invalid, Question,
                                      v_yes_no)
from src.contracts import AgentResult, Correction, IntakeInterpretation, IntakeSignals, Outcome
from src.hitl import make_escalation
from src.memory import build_intake_context, confirmed_fact_lines
from src.provenance import direct_input_record, fact_key
from src.ssn import redact_ssns

AGENT = "intake"

SYSTEM_PROMPT = """You are the Intake agent of SilverFile, a classroom prototype that helps older adults prepare a DRAFT 2025 Form 1040-SR for review by a human volunteer. You interpret the taxpayer's latest reply to the current question and return JSON for the given schema.

Rules you must follow:
- Never give tax advice, planning or optimisation, and never say whether something is deductible or cheaper. If asked, set intent "advice" and signals.advice_request true.
- Never do arithmetic and never decide tax rules. Only report what the person said.
- For the answer field: yes/no questions -> "yes" or "no"; dates -> YYYY-MM-DD; amounts -> digits exactly as the person said them (e.g. "52000" or "1250.75"), never computed; counts -> a digit; choice questions -> one option value; names -> the name only.
- If the reply does not answer the current question, set answer to null and choose the best intent.
- corrections: only when the person clearly changes an earlier answer; use the earlier question's id from the session summary or recent turns.
- signals: set a flag only when the person's own words clearly support it; out_of_scope lists only situations the person says apply to them (not ones they deny). Put a short supporting quote in evidence.
- third_party_without_authority: someone else is answering for the taxpayer and has not stated legal authority.
- exploitation_concern: pressure or coercion, or a refund going to someone else's or an unknown account.
- reply: at most two short, warm, plain-language sentences. No numbers, no advice, no promises about the outcome. If intent is "clarify", explain the word simply.
"""

_ACKS = ["Thank you.", "Got it, thank you.", "Thanks, I've noted that.", "Thank you, that's saved."]

# ---------------------------------------------------------------------------
# deterministic guardrail patterns (defence in depth; also the offline parser)
# ---------------------------------------------------------------------------

_NEG = re.compile(r"\b(no|not|don'?t|didn'?t|never|without|none|nor|haven'?t|wasn'?t)\b[^.?!]{0,25}$", re.I)

ADVICE_PATTERNS = [
    r"\bshould (i|we)\b", r"\bwould (i|we) (pay|save|owe|get)\b", r"\bpay less\b", r"\bsave (on )?(my )?tax",
    r"\bis it better\b", r"\bbetter (for me|for us|to file)\b", r"\bcan (i|we) deduct\b", r"\bdeductible\b",
    r"\bconvert (my|an|the|our) ira\b", r"\broth conversion\b", r"\b(reduce|lower|minimi[sz]e) (my|our) tax",
    r"\bwhat do you (recommend|suggest)\b", r"\b(tax )?advice\b", r"\bbest way to\b", r"\bget a bigger refund\b",
]
EXPLOIT_PATTERNS = [
    r"\b(nephew|niece|son|daughter|grandson|granddaughter|neighbou?r|caregiver|friend|boyfriend|girlfriend|"
    r"helper|someone)\b[^.?!]{0,50}\b(wants|takes|keeps|gets|needs|told me|said)\b[^.?!]{0,30}\b(refund|money|account)\b",
    r"\b(refund|money)\b[^.?!]{0,40}\b(his|her|their|my (son|daughter|nephew|niece|grandson|granddaughter|"
    r"neighbou?r|caregiver|friend)'?s?) (account|bank)\b",
    r"\bnot my (account|bank)\b", r"\bdon'?t know (whose|which|what) (account|bank)\b",
    r"\b(told|making|made|forcing|pressur\w*|threaten\w*) me\b",
    r"\bi'?m (answering|doing this) for (him|her|my (mother|father|mom|dad|aunt|uncle|grandmother|grandfather))\b",
    r"\bon (his|her) behalf\b",
]
SCOPE_PATTERNS = {
    "self_employment": r"\b(self[- ]employ\w*|my own business|side (work|job|gig|business)|1099-nec|freelanc\w*|"
                       r"schedule c|i (run|own) a (small )?business)\b",
    "rental_income": r"\b(rental (income|property|house)|rent(ed|ing)? (it )?out|landlord|tenants?|schedule e)\b",
    "capital_gains": r"\b(sold (some |my |our )?(stocks?|shares|house|home|property|land)|capital gains?|"
                     r"schedule d|1099-b)\b",
    "digital_assets": r"\b(crypto\w*|bitcoin|ethereum|digital assets?|nfts?)\b",
    "foreign_income": r"\b(foreign (income|account|bank|pension)|income from (another|a foreign) country|"
                      r"overseas (account|income)|fbar)\b",
    "amended_or_prior_year": r"\b(amend\w*|prior[- ]year return|(2024|2023|2022) return|fix (a|my) return)\b",
    "state_return": r"\bstate (tax )?return\b",
    "itemized_deductions": r"\b(itemi[sz]\w*|schedule a)\b",
}
SPOUSE_DEATH = re.compile(r"\b(husband|wife|spouse|partner)\b[^.?!]{0,40}\b(died|passed( away| on)?|death)\b"
                          r"[^.?!]{0,30}\b(2025|this year|this past year|last month|in (january|february|march|april|"
                          r"may|june|july|august|september|october|november|december))\b", re.I)
HELP_RE = re.compile(r"\b((talk|speak) (to|with) (a |an )?(real )?(person|human|someone|volunteer|agent)|human|"
                     r"a volunteer|real person|get help)\b", re.I)
UNSURE_RE = re.compile(r"\b(not sure|unsure|don'?t know|do not know|no idea|can'?t remember|not certain|i forget|"
                       r"no clue)\b", re.I)
BACK_RE = re.compile(r"\b(go back|previous question|back up|undo|redo that|last question)\b", re.I)
REPEAT_RE = re.compile(r"\b(repeat|say (that|it) again|didn'?t (understand|catch)|what was the question|pardon|"
                       r"come again)\b", re.I)
CLARIFY_RE = re.compile(r"(\bwhat (does|is|'s|do you mean by) (a |an |the )?[\w\- ]{2,40}\??$|\bwhat do you mean\b|"
                        r"\bmean\?|\bexplain\b)", re.I)
CORRECT_RE = re.compile(r"\b(actually|i meant|correction|i made a mistake|change my|that was wrong|wrong answer|"
                        r"let me fix|i was wrong)\b", re.I)

CORRECTION_KEYWORDS = [
    (r"\b(spouse|wife|husband)'?s?\b[^.]{0,30}\b(birth|born|birthday)\b", "sp_dob"),
    (r"\b(birth|born|birthday|date of birth)\b", "tp_dob"),
    (r"\b(spouse|wife|husband)'?s?\b[^.]{0,20}\bfirst name\b", "sp_first_name"),
    (r"\b(spouse|wife|husband)'?s?\b[^.]{0,20}\blast name\b", "sp_last_name"),
    (r"\bfirst name\b", "tp_first_name"),
    (r"\b(last name|surname)\b", "tp_last_name"),
    (r"\b(filing status|file (jointly|separately)|single|head of household)\b", "filing_status"),
    (r"\b(wages?|earned|salary|pay from)\b", "stated_wages"),
    (r"\bestimated\b", "est_amount"),
    (r"\bblind\b", "tp_blind"),
    (r"\b(w-?2s?)\b", "has_w2"),
    (r"\b(ssa-?1099|social security (statement|form))\b", "has_ssa1099"),
    (r"\b1099-?r\b", "has_1099r"),
    (r"\b1099-?int\b", "has_1099int"),
    (r"\b1099-?div\b", "has_1099div"),
]


def _pattern_hit(patterns: list[str], text: str) -> str | None:
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            if _NEG.search(text[:m.start()]):
                continue
            return m.group(0)
    return None


def guardrail_signals(text: str) -> IntakeSignals:
    """Keyword scan that runs on every reply in both modes."""
    t = text or ""
    advice = _pattern_hit(ADVICE_PATTERNS, t)
    exploit = _pattern_hit(EXPLOIT_PATTERNS, t)
    scope = []
    evidence = advice or exploit or ""
    for cat, pat in SCOPE_PATTERNS.items():
        hit = _pattern_hit([pat], t)
        if hit:
            scope.append(cat)
            evidence = evidence or hit
    death = SPOUSE_DEATH.search(t)
    if death:
        evidence = evidence or death.group(0)
    return IntakeSignals(advice_request=bool(advice), third_party_without_authority=False,
                         exploitation_concern=bool(exploit), spouse_died_2025=bool(death),
                         out_of_scope=scope, evidence=evidence[:160])


def offline_interpret(step: dict, text: str) -> IntakeInterpretation:
    """Deterministic interpretation used without a model (tests, no API key)."""
    t = (text or "").strip()
    signals = guardrail_signals(t)
    corrections: list[Correction] = []
    intent = "answer"
    answer: str | None = t
    if signals.advice_request:
        intent, answer = "advice", None
        # keep an answer if the reply starts with one (e.g. "Yes. Should I ...")
        first = re.split(r"[.!?]", t, maxsplit=1)[0]
        if _validates(step, first):
            answer = first
    elif HELP_RE.search(t):
        intent, answer = "help", None
    elif BACK_RE.search(t):
        intent, answer = "go_back", None
    elif CORRECT_RE.search(t):
        intent, answer = "correction", None
        qid = next((q for pat, q in CORRECTION_KEYWORDS if re.search(pat, t, re.I)), None)
        if qid:
            corrections.append(Correction(question_id=qid, new_answer=_after_is(t)))
    elif REPEAT_RE.search(t):
        intent, answer = "repeat", None
    elif UNSURE_RE.search(t) and (step.get("kind") in {"text", "upload", "choice"} or not _validates(step, t)):
        intent, answer = "unsure", None
    elif CLARIFY_RE.search(t) and not _validates(step, t):
        intent, answer = "clarify", None
    elif not _validates(step, t) and re.search(r"\b(is|was|should be)\b", t, re.I):
        qid = next((q for pat, q in CORRECTION_KEYWORDS if re.search(pat, t, re.I)), None)
        if qid and qid != step.get("question_id"):
            intent, answer = "correction", None
            corrections.append(Correction(question_id=qid, new_answer=_after_is(t)))
    return IntakeInterpretation(intent=intent, answer=answer, corrections=corrections, signals=signals, reply="")


def _after_is(text: str) -> str:
    """The new value in 'actually my X is Y': the text after the last is/was."""
    matches = list(re.finditer(r"\b(is|was|should be|are|were)\b\s+", text, re.I))
    return (text[matches[-1].end():] if matches else text).strip(" .")


def _validates(step: dict, text: str) -> bool:
    validator = _validator_for(step)
    if validator is None:
        return True
    try:
        validator(text)
        return True
    except Invalid:
        return False


def _validator_for(step: dict):
    qid = step.get("question_id")
    if qid in QUESTIONS_BY_ID:
        return QUESTIONS_BY_ID[qid].validator
    if qid and qid.startswith("dep_"):
        field_name = qid.split("_", 1)[1]
        for name, _, _, validator in DEPENDENT_FIELDS:
            if name == field_name:
                return validator
        if field_name == "more":
            return v_yes_no
    if step.get("validator") == "yes_no" or step.get("kind") == "yes_no" or qid == CONFIRM_QUESTION_ID:
        return v_yes_no
    if qid == SUBMIT_QUESTION_ID:
        def _submit(text: str) -> str:
            t = (text or "").strip().lower()
            if any(w in t for w in ("change", "fix", "edit", "wrong")) or t in {"no", "not yet", "n"}:
                return "change"
            # A bare "yes" is not enough: it could be a late reply to the previous question.
            if any(w in t for w in ("submit", "send", "review", "go ahead")):
                return "submit"
            raise Invalid("To send your draft, choose 'Send it to Kushim for review' (or type 'send it'). "
                          "To change something, choose 'I want to change something'.")
        return _submit
    if step.get("kind") == "choice" and step.get("options"):
        values = {o["value"] for o in step["options"]}
        labels = {o["label"].lower(): o["value"] for o in step["options"]}

        def _choice(text: str) -> str:
            t = (text or "").strip().lower().strip(".")
            if t in values:
                return t
            for lbl, val in labels.items():
                if t == lbl or lbl.startswith(t) or t in lbl:
                    return val
            raise Invalid("Please choose one of the options shown.")
        return _choice
    return None


# ---------------------------------------------------------------------------
# what to ask next
# ---------------------------------------------------------------------------


def _expected_docs(facts: dict) -> dict[str, int]:
    return {dt: int(facts.get(fid) or 0) for dt, fid in DOC_COUNT_FACTS.items() if facts.get(fid)}


def _present_docs(state: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in (state.get("documents") or {}).values():
        if d.get("status") in {"rejected", "duplicate"}:
            continue
        counts[d.get("doc_type")] = counts.get(d.get("doc_type"), 0) + 1
    return counts


def missing_documents(state: dict) -> dict[str, int]:
    facts = flat_facts(state)
    present = _present_docs(state)
    return {dt: n - present.get(dt, 0) for dt, n in _expected_docs(facts).items() if n > present.get(dt, 0)}


def _dependent_step(state: dict, facts: dict) -> dict | None:
    intake = state.get("intake") or {}
    if facts.get("dependents.any") is not True or facts.get("dependents.done") is True:
        return None
    draft = intake.get("dep_draft") or {}
    count = len(facts.get("dependents") or [])
    if count and not intake.get("dep_adding"):
        return None  # ask "another dependent?" next
    for name, text, kind, _ in DEPENDENT_FIELDS:
        if name not in draft:
            return {"question_id": f"dep_{name}", "fact": f"dependent.{name}", "text": text, "gloss": "",
                    "kind": kind, "options": [], "section": f"Dependent {count + 1}",
                    "sensitive": kind == "ssn"}
    return None  # pragma: no cover - a complete draft is committed immediately


SUBMIT_QUESTION_ID = "submit_draft"


def _draft_current(state: dict) -> bool:
    calc = state.get("calc") or {}
    assembly = state.get("assembly") or {}
    review = state.get("review") or {}
    return (assembly.get("status") == "ready" and assembly.get("calc") == calc.get("calc_id")
            and review.get("status") == "passed" and review.get("for_calc") == calc.get("calc_id")
            and calc.get("facts_version") == int(state.get("facts_version") or 0))


def next_step(state: dict) -> dict | None:
    """Return the next prompt for the taxpayer, or None when intake is done."""
    intake = state.get("intake") or {}
    facts = flat_facts(state)
    followups = [f for f in intake.get("followups") or [] if f.get("status", "open") == "open"]
    if followups:
        f = followups[0]
        return {"question_id": f"followup:{f['id']}", "fact": f.get("fact"), "text": f["text"],
                "gloss": f.get("gloss", ""), "kind": f.get("kind", "text"), "options": f.get("options", []),
                "section": "A quick check", "followup_id": f["id"], "sensitive": False}
    override = intake.get("cursor_override")
    if override and override in QUESTIONS_BY_ID:
        q = QUESTIONS_BY_ID[override]
        if q.applies(facts):
            return q.payload(facts)
    if intake.get("complete") and not intake.get("submitted") and _draft_current(state):
        return {"question_id": SUBMIT_QUESTION_ID, "fact": None, "kind": "choice", "section": "Your draft",
                "sensitive": False,
                "text": ("Your draft Form 1040-SR is ready. It has not been filed. Would you like to send it to a "
                         "Kushim volunteer for review, or change something first?"),
                "gloss": "Sending it for review does not file anything. A volunteer checks every number with you.",
                "options": [{"value": "submit", "label": "Send it to Kushim for review"},
                            {"value": "change", "label": "I want to change something"}]}
    for q in QUESTIONS:
        if not q.applies(facts):
            continue
        if q.fact not in facts:
            return q.payload(facts)
        if q.id == "dependents_any":
            dep = _dependent_step(state, facts)
            if dep:
                return dep
            if facts.get("dependents.any") is True and facts.get("dependents.done") is not True:
                n = len(facts.get("dependents") or [])
                return {"question_id": "dep_more", "fact": "dependents.done",
                        "text": "Do you have another dependent to add?", "gloss": "", "kind": "yes_no",
                        "options": [], "section": f"Dependent {n + 1}", "sensitive": False}
    missing = missing_documents(state)
    if missing:
        listing = ", ".join(f"{n} {dt}" for dt, n in missing.items())
        return {"question_id": UPLOAD_QUESTION_ID, "fact": None, "kind": "upload", "options": [],
                "section": "Your forms", "sensitive": False,
                "text": (f"Please add a photo or scan of each form you mentioned. Still needed: {listing}. "
                         "Use the 'Add your forms' box below the chat, then type 'done'."),
                "gloss": "For forms other than the W-2 you can type the boxes in yourself instead.",
                "missing": missing}
    if facts.get("summary_confirmed") is not True:
        lines = confirmed_fact_lines({"facts": state.get("facts")}, FACT_LABELS)
        docs = [f"- {d.get('doc_type')}: {d.get('file_name')}" for d in (state.get("documents") or {}).values()
                if d.get("status") not in {"rejected", "duplicate"}]
        body = "\n".join(lines) + ("\n\nForms received:\n" + "\n".join(docs) if docs else "")
        return {"question_id": CONFIRM_QUESTION_ID, "fact": "summary_confirmed", "kind": "yes_no",
                "options": [], "section": "Check your answers", "sensitive": False,
                "text": "Here is a summary of what you've told me:\n" + body + "\n\nIs everything correct?",
                "gloss": "If something is wrong, say no and tell me what to change."}
    return None


def progress(state: dict) -> dict:
    facts = flat_facts(state)
    applicable = [q for q in QUESTIONS if q.applies(facts)]
    answered = sum(1 for q in applicable if q.fact in facts)
    return {"answered": answered, "total": len(applicable)}


# ---------------------------------------------------------------------------
# node
# ---------------------------------------------------------------------------


def intake_node(state: dict, rt: Runtime) -> dict:
    step = next_step(state)
    if step is None:
        intake = dict(state.get("intake") or {})
        intake["complete"] = True
        return AgentResult(agent=AGENT, outcome=Outcome.SUCCESS, summary="Intake complete.",
                           patch={"intake": intake}).to_update(rt.now())
    intake = state.get("intake") or {}
    payload = {"kind": "taxpayer_question", "case_id": state.get("case_id"), "step": step,
               "hint": intake.get("hint"), "ack": intake.get("pending_ack"), "progress": progress(state)}
    reply = interrupt(payload)
    if not isinstance(reply, dict) or reply.get("kind") != "taxpayer_message":
        # Only taxpayer messages can answer an intake question.
        return AgentResult(agent=AGENT, outcome=Outcome.NEED_INPUT,
                           summary="Ignored a resume value that was not a taxpayer message.").to_update(rt.now())
    return handle_reply(state, step, reply, rt)


def _fact_record(value: Any, now: str, step: dict, raw: str | None, prior: dict | None,
                 entered_by: str = "taxpayer (intake dialogue)") -> dict:
    history = list((prior or {}).get("history") or [])
    if prior and prior.get("status") == "confirmed":
        history.append({"value": prior.get("value"), "at": prior.get("source", {}).get("at"),
                        "replaced_at": now})
    return {"value": value, "status": "confirmed", "history": history,
            "source": {"kind": "direct_input", "entered_by": entered_by, "at": now,
                       "question_id": step.get("question_id"), "question_text": step.get("text"),
                       "raw_answer": raw}}


def handle_reply(state: dict, step: dict, reply: dict, rt: Runtime) -> dict:
    now = rt.now()
    raw = str(reply.get("text") or "")
    uploads = list(reply.get("uploads") or [])
    facts_all = dict(state.get("facts") or {})
    intake = {k: (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v))
              for k, v in (state.get("intake") or {}).items()}
    intake["hint"] = None
    intake["pending_ack"] = None
    qid = step.get("question_id")
    kind = step.get("kind")
    new_facts: dict[str, dict] = {}
    provenance: dict[str, dict] = {}
    notes: list[str] = []
    metrics: list[dict] = []
    escalation = None

    # --- privacy: SSNs only where an SSN was asked for --------------------------
    if kind == "ssn":
        stored_text = "[Social Security number entered]"
        text_for_model = stored_text
    else:
        stored_text, n_redacted = redact_ssns(raw)
        text_for_model = stored_text
        if n_redacted:
            notes.append("For your privacy, I removed a number that looked like a Social Security number. "
                         "I'll only ask for that when it's needed.")
    transcript = [{"role": "assistant", "text": step.get("text"), "question_id": qid, "at": now},
                  {"role": "user", "text": stored_text or "(no text)", "question_id": qid, "at": now}]

    # --- documents attached to this message ---------------------------------------
    documents_patch = {}
    for doc in uploads:
        documents_patch[doc["doc_id"]] = {**doc, "status": "queued"}
    if uploads:
        notes.append(f"I received {len(uploads)} document{'s' if len(uploads) != 1 else ''}. "
                     "I'll read them in a moment.")
    if kind == "upload":
        still = dict(missing_documents(state))
        for doc in uploads:
            if still.get(doc.get("doc_type"), 0) > 0:
                still[doc["doc_type"]] -= 1
        still = {k: v for k, v in still.items() if v > 0}
        if still:
            notes.append("I still need: " + ", ".join(f"{n} {dt}" for dt, n in still.items()) + ".")

    # --- interpret ----------------------------------------------------------------
    if kind == "ssn":
        interp = IntakeInterpretation(intent="answer", answer=raw, corrections=[],
                                      signals=guardrail_signals(""), reply="")
    elif kind == "upload":
        interp = offline_interpret(step, text_for_model)
        if interp.intent == "answer":
            interp.answer = text_for_model or "done"
    else:
        call_step = step
        if rt.llm.mode == "offline" or not text_for_model.strip():
            interp = offline_interpret(step, text_for_model)
        else:
            from src.agents.intake_script import FACT_LABELS as labels
            options = "; ".join(f"{o['value']}={o['label']}" for o in step.get("options") or [])
            qtext = f"[{qid}] ({kind}) {step.get('text')}" + (f" Options: {options}" if options else "")
            messages = build_intake_context(state, qtext, text_for_model,
                                            strategy_enabled=rt.settings.context_strategy,
                                            recent_turns=rt.settings.context_recent_turns, labels=labels)
            try:
                call = rt.llm.structured(agent=AGENT, system=SYSTEM_PROMPT, messages=messages,
                                         schema=IntakeInterpretation,
                                         offline=lambda: offline_interpret(call_step, text_for_model),
                                         purpose="interpret_reply", max_tokens=1500)
                interp = call.data
                metrics.append(call.record)
            except Exception as exc:  # model failure must not lose the answer
                interp = offline_interpret(step, text_for_model)
                metrics.append({"kind": "model_call", "agent": AGENT, "ok": False, "error": str(exc)[:200],
                                "fallback": "offline_interpret", "at": now})
        # deterministic guardrails always run as well
        g = guardrail_signals(text_for_model)
        s = interp.signals
        interp.signals = IntakeSignals(
            advice_request=s.advice_request or g.advice_request,
            third_party_without_authority=s.third_party_without_authority,
            exploitation_concern=s.exploitation_concern or g.exploitation_concern,
            spouse_died_2025=s.spouse_died_2025 or g.spouse_died_2025,
            out_of_scope=sorted(set(s.out_of_scope) | set(g.out_of_scope)),
            evidence=s.evidence or g.evidence)

    # --- corrections ------------------------------------------------------------------
    for corr in interp.corrections:
        q = QUESTIONS_BY_ID.get(corr.question_id)
        if q is None:
            continue
        try:
            value = q.validator(corr.new_answer)
        except Invalid as exc:
            intake["cursor_override"] = q.id
            notes.append(f"Let's fix your answer about {q.label.lower() or q.id}. {exc}")
            continue
        prior = facts_all.get(q.fact)
        new_facts[q.fact] = _fact_record(value, now, q.payload({}), corr.new_answer, prior)
        notes.append(f"I've updated your answer about {(q.label or q.id).lower()}.")

    # --- the answer itself ----------------------------------------------------------
    answered = False
    if interp.intent in {"answer", "advice", "off_topic"} and interp.answer not in (None, ""):
        answered = _apply_answer(state, step, interp.answer, raw if kind != "ssn" else None, now, facts_all,
                                 new_facts, intake, notes)
        if not answered and interp.intent == "answer" and interp.answer != raw and kind != "ssn":
            # the model's normalisation failed validation; try the literal reply
            hint_before = intake.get("hint")
            answered = _apply_answer(state, step, raw, raw, now, facts_all, new_facts, intake, notes)
            if answered:
                intake["hint"] = None
            elif hint_before:
                intake["hint"] = hint_before
    if kind == "ssn" and not answered:
        intake["rejected_ssn_attempts"] = int(intake.get("rejected_ssn_attempts") or 0) + 1

    # --- conversational intents ----------------------------------------------------------
    gloss = step.get("gloss") or ""
    if interp.intent == "go_back":
        asked = [a for a in intake.get("asked") or [] if a in QUESTIONS_BY_ID]
        prev = asked[-1] if asked and asked[-1] != qid else (asked[-2] if len(asked) > 1 else None)
        if prev:
            intake["cursor_override"] = prev
            notes.append("Sure, let's go back to the previous question. Your other answers are kept.")
        else:
            notes.append("This is the first question, so there's nothing earlier to go back to.")
    elif interp.intent == "repeat":
        notes.append("Of course. Here it is again." + (f" {gloss}" if gloss else ""))
    elif interp.intent == "clarify":
        reply_text = _safe_reply(interp.reply) if rt.llm.mode != "offline" else ""
        notes.append(reply_text or (f"Here's what that means: {gloss}" if gloss else
                                    "Let me put it another way. Answer as best you can, or say 'not sure'."))
    elif interp.intent == "off_topic" and not answered:
        notes.append(_safe_reply(interp.reply) or "I understand. Let's come back to the question when you're ready.")

    # --- escalations (most serious first) ------------------------------------------------
    sig = interp.signals
    evidence = [{"type": "taxpayer_message", "text": stored_text[:300], "question_id": qid, "at": now}]
    if sig.exploitation_concern or sig.third_party_without_authority:
        escalation = make_escalation(
            "exploitation_concern",
            "The conversation suggests possible pressure or a third party controlling the refund.",
            raised_by=AGENT, evidence=evidence,
            taxpayer_message=("Thank you for telling me. I'd like a Kushim volunteer to check a few things with "
                              "you before we go on. Your answers are saved."))
    elif sig.advice_request or interp.intent == "advice":
        intake.setdefault("notes_for_volunteer", [])
        intake["notes_for_volunteer"] = list(intake["notes_for_volunteer"]) + [{"text": stored_text[:300], "at": now}]
        escalation = make_escalation(
            "advice_request", "The taxpayer asked for tax advice or planning.", raised_by=AGENT, evidence=evidence,
            taxpayer_message=("That's a good question, but SilverFile can't give tax advice. I've noted it so a "
                              "Kushim volunteer preparer can talk it through with you. Your answers are saved."))
    elif sig.out_of_scope:
        escalation = make_escalation(
            "out_of_scope", "The taxpayer mentioned: " + ", ".join(c.replace("_", " ") for c in sig.out_of_scope) + ".",
            raised_by=AGENT, evidence=evidence, details={"categories": list(sig.out_of_scope)},
            taxpayer_message=("Thank you. That's something SilverFile doesn't handle, so I'm passing your case to a "
                              "Kushim volunteer who can help. Your answers are saved."))
    elif sig.spouse_died_2025:
        escalation = make_escalation(
            "filing_status_ambiguity", "The taxpayer mentioned their spouse died during 2025.", raised_by=AGENT,
            evidence=evidence, taxpayer_message=("I'm very sorry for your loss. A Kushim volunteer will help choose "
                                                 "the right filing status with you. Your answers are saved."))
    elif interp.intent == "help":
        escalation = make_escalation(
            "taxpayer_needs_help", f"The taxpayer asked to speak with a person (at question '{qid}').",
            raised_by=AGENT, evidence=evidence,
            taxpayer_message="Of course. I've asked a Kushim volunteer to contact you. Your answers are saved.")
    elif interp.intent == "unsure" and not answered:
        if qid == "filing_status":
            escalation = make_escalation(
                "filing_status_ambiguity", "The taxpayer is not sure which filing status applies.", raised_by=AGENT,
                evidence=evidence, taxpayer_message=("That's completely fine. I'm not able to choose a filing status "
                                                     "for you, so I've flagged this for a Kushim volunteer. Your "
                                                     "answers are saved."))
        elif kind == "upload":
            escalation = make_escalation(
                "document_problem", "The taxpayer is not sure they can provide a form they listed.", raised_by=AGENT,
                evidence=evidence, details={"missing": step.get("missing")},
                taxpayer_message=("That's okay. I'm not sure how to go on without that form, so I've flagged it "
                                  "for a Kushim volunteer. Your answers are saved."))
        else:
            escalation = make_escalation(
                "taxpayer_needs_help", f"The taxpayer was unsure how to answer: {step.get('text')}", raised_by=AGENT,
                evidence=evidence, affected=[step.get("fact") or ""],
                details={"question_id": qid, "fact": step.get("fact")},
                taxpayer_message=("That's okay - I'm not sure either, so let me flag this for a volunteer. "
                                  "Your answers are saved."))

    # --- bookkeeping -----------------------------------------------------------------------
    if qid == CONFIRM_QUESTION_ID and (answered and new_facts.get("summary_confirmed") or interp.corrections):
        intake["awaiting_change"] = False
    if answered and qid in QUESTIONS_BY_ID:
        asked = [a for a in intake.get("asked") or [] if a != qid]
        intake["asked"] = asked + [qid]
        if intake.get("cursor_override") == qid:
            intake["cursor_override"] = None
    if answered and not notes and escalation is None:
        n = len(intake.get("asked") or [])
        notes.append(_ACKS[n % len(_ACKS)])
    elif not answered and escalation is None and not notes and not uploads:
        notes.append(intake.get("hint") or "I didn't quite catch that.")
    reply_text = " ".join(notes)
    if escalation:
        reply_text = (reply_text + " " if reply_text else "") + escalation["taxpayer_message"]
    if reply_text:
        transcript.append({"role": "assistant", "text": reply_text, "at": now})
    intake["pending_ack"] = reply_text or None

    for fact_id, rec in new_facts.items():
        provenance[fact_key(fact_id)] = direct_input_record(
            fact_id=fact_id, value=rec["value"], entered_by=rec["source"]["entered_by"], entered_at=now,
            question_id=rec["source"]["question_id"], question_text=rec["source"]["question_text"],
            raw_answer=rec["source"]["raw_answer"])

    patch: dict[str, Any] = {"intake": intake, "transcript": transcript, "metrics": metrics}
    if new_facts:
        patch["facts"] = new_facts
        patch["facts_version"] = int(state.get("facts_version") or 0) + 1
        patch["provenance"] = provenance
    if documents_patch:
        patch["documents"] = documents_patch
    outcome = Outcome.ESCALATION if escalation else (Outcome.SUCCESS if answered or uploads else Outcome.NEED_INPUT)
    summary = (f"Escalation requested: {escalation['reason']}" if escalation else
               f"Recorded answer for {qid}." if answered else f"Re-asking {qid} ({interp.intent}).")
    return AgentResult(agent=AGENT, outcome=outcome, summary=summary, patch=patch,
                       escalation=escalation).to_update(now)


def _safe_reply(text: str) -> str:
    """Model replies are shown only if short, number-free and advice-free."""
    t = (text or "").strip()
    if not t or len(t) > 320 or re.search(r"\d", t) or _pattern_hit(ADVICE_PATTERNS, t):
        return ""
    if re.search(r"\b(you should|we recommend|i recommend|deduct)\b", t, re.I):
        return ""
    return t


def _apply_answer(state: dict, step: dict, answer: str, raw: str | None, now: str, facts_all: dict,
                  new_facts: dict, intake: dict, notes: list[str]) -> bool:
    qid = step.get("question_id") or ""
    validator = _validator_for(step)
    try:
        value = validator(answer) if validator else answer
    except Invalid as exc:
        intake["hint"] = str(exc)
        return False

    if qid.startswith("followup:"):
        fid = step.get("followup_id")
        intake["followups"] = [dict(f, status="answered", answer=value, answered_at=now) if f["id"] == fid else f
                               for f in intake.get("followups") or []]
        if step.get("fact"):
            new_facts[step["fact"]] = _fact_record(value, now, step, raw, facts_all.get(step["fact"]))
        return True
    if qid == UPLOAD_QUESTION_ID:
        return True
    if qid.startswith("dep_"):
        field_name = qid.split("_", 1)[1]
        if field_name == "more":
            if value is True:
                intake["dep_adding"] = True
            else:
                new_facts["dependents.done"] = _fact_record(True, now, step, raw, facts_all.get("dependents.done"))
            return True
        draft = dict(intake.get("dep_draft") or {})
        draft[field_name] = value
        if all(name in draft for name, *_ in DEPENDENT_FIELDS):
            deps = list((facts_all.get("dependents") or {}).get("value") or [])
            deps.append(draft)
            new_facts["dependents"] = _fact_record(deps, now, {"question_id": "dependents",
                                                               "text": "Dependents"}, None,
                                                   facts_all.get("dependents"))
            intake["dep_draft"] = {}
            intake["dep_adding"] = False
        else:
            intake["dep_draft"] = draft
        return True
    if qid == SUBMIT_QUESTION_ID:
        if value == "submit":
            intake["submitted"] = True
            intake["submitted_at"] = now
            notes.append("Thank you. Your draft has been sent to a Kushim volunteer for review. Nothing has been "
                         "filed; they will contact you to go over it.")
        else:
            notes.append("No problem. Tell me what to change, for example 'my date of birth is March 5, 1955'.")
        return True
    if qid == CONFIRM_QUESTION_ID and value is False:
        intake["awaiting_change"] = True
        notes.append("No problem. What would you like to change? You can say, for example, "
                     "'my date of birth is March 5, 1955', or 'go back'.")
        return True
    fact_id = step.get("fact")
    if not fact_id:
        return True
    new_facts[fact_id] = _fact_record(value, now, step, raw, facts_all.get(fact_id))
    if qid == "tp_ssn" or qid == "sp_ssn":
        notes.append("Thank you. I've saved that test number.")
    return True
