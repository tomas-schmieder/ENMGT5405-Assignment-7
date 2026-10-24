"""Kushim employee dashboard: case list, review queue, actionable HITL events.

"Submitted" always means *submitted internally for human review*; nothing is
filed. Reviewer actions are limited to what each escalation reason allows
(src/hitl.py) and every action needs a reviewer name and a rationale.
This classroom prototype has no login; the reviewer name is self-declared
(documented limitation).
"""

from __future__ import annotations

import json

import streamlit as st

from src.agents.intake_script import FACT_LABELS
from src.hitl import ACTION_LABELS
from src.service import ServiceError
from src.state import STATUS_LABELS
from src.tools.tax_calculations import STATUS_LABELS as FS_LABELS
from src.ui.components import badge, get_service, md, money
from src.ui.provenance_view import render_draft

IN_PROGRESS = {"intake", "awaiting_documents", "processing", "revising"}


def render() -> None:
    svc = get_service()
    st.title("Kushim review dashboard")
    reviewer = st.sidebar.text_input("Your name (recorded on every review action)", key="reviewer_name",
                                     placeholder="e.g. J. Rivera, Kushim volunteer")
    cases = svc.list_cases()
    counts = {
        "In progress": sum(1 for c in cases if c["status"] in IN_PROGRESS),
        "Needs human review": sum(1 for c in cases if c["status"] == "needs_human_review"),
        "Draft ready": sum(1 for c in cases if c["status"] == "draft_ready"),
        "Submitted (internal review)": sum(1 for c in cases if c["status"] == "submitted_for_internal_review"),
        "Referred out of scope": sum(1 for c in cases if c["status"] == "referred_out_of_scope"),
    }
    cols = st.columns(len(counts))
    for col, (label, n) in zip(cols, counts.items()):
        col.metric(label, n)

    st.markdown("### Cases")
    groups = {"All cases": None, "In progress": IN_PROGRESS, "Needs human review": {"needs_human_review"},
              "Draft ready": {"draft_ready"}, "Submitted internally for review": {"submitted_for_internal_review"},
              "Referred out of scope": {"referred_out_of_scope"}, "Errors": {"error"}}
    choice = st.radio("Show", list(groups), horizontal=True, label_visibility="collapsed")
    shown = [c for c in cases if groups[choice] is None or c["status"] in groups[choice]]
    if not shown:
        st.info("No cases in this group yet.")
        return
    rows = [{"Case": c["case_id"], "Taxpayer": c["taxpayer"] or "(not yet given)",
             "Status": STATUS_LABELS.get(c["status"], c["status"]),
             "Filing status": FS_LABELS.get(c["filing_status"], "-") if c["filing_status"] else "-",
             "Needs": c["pending_reason"] or "-", "Draft": f"v{c['draft_version']}" if c["draft_version"] else "-",
             "Refund / owed": (f"Refund {money(c['refund'])}" if c["refund"] not in (None, "0") else
                               f"Owes {money(c['owed'])}" if c["owed"] not in (None, "0") else "-"),
             "Updated (UTC)": (c["updated_at"] or "")[:16].replace("T", " ")} for c in shown]
    picked = st.dataframe(rows, hide_index=True, use_container_width=True, on_select="rerun",
                          selection_mode="single-row", key=f"cases_{choice}")
    sel = picked.selection.rows if picked and picked.selection else []
    queue = [c for c in cases if c["status"] == "needs_human_review"]
    if queue:
        st.markdown("#### Review queue")
        for c in queue:
            q = st.columns([2, 4, 1])
            q[0].markdown(f"**{c['case_id']}**  \n{md(c['taxpayer'] or '')}")
            q[1].markdown(f"**{md(c['pending_reason'])}**  \n{md(c['pending_summary'])}")
            if q[2].button("Open", key=f"open_{c['case_id']}", use_container_width=True):
                st.session_state["dash_case"] = c["case_id"]
    if sel:
        st.session_state["dash_case"] = shown[sel[0]]["case_id"]
    case_id = st.session_state.get("dash_case")
    if case_id:
        st.divider()
        _case_detail(svc, case_id, reviewer)


def _case_detail(svc, case_id: str, reviewer: str) -> None:
    try:
        view = svc.view(case_id)
    except ServiceError as exc:
        st.error(str(exc))
        return
    st.markdown(f"## {case_id} &nbsp; {badge(view['status'])}", unsafe_allow_html=True)
    f = view["facts"]
    st.markdown(f"**Taxpayer:** {f.get('tp.first_name', '')} {f.get('tp.last_name', '')} | "
                f"**Filing status:** {FS_LABELS.get(f.get('filing_status'), '-')} | "
                f"**Model mode:** {view['llm_mode']} | **Facts version:** {view['facts_version']}")
    if view.get("error"):
        st.error(md(f"Processing error: {view['error']}"))
        if st.button("Retry processing from the last checkpoint"):
            try:
                svc.retry(case_id)
            except ServiceError as exc:
                st.error(str(exc))
            st.rerun()
    pend = view["pending"]
    tab_names = (["Human review"] if pend and pend["kind"] == "human_review" else []) + \
        ["Draft & provenance", "Conversation", "Documents", "Rules & audit", "Review history", "Agent trace"]
    tabs = dict(zip(tab_names, st.tabs(tab_names)))
    if "Human review" in tabs:
        with tabs["Human review"]:
            _review_form(svc, view, pend["event"], reviewer)
    with tabs["Draft & provenance"]:
        render_draft(view, key_prefix=f"d_{case_id}_")
    with tabs["Conversation"]:
        notes = (view["intake"].get("notes_for_volunteer") or [])
        if notes:
            st.markdown("**Questions noted for the volunteer preparer:**")
            st.markdown("\n".join(f"- {md(n['text'])} ({n['at'][:16]})" for n in notes))
        for m in view["transcript"]:
            who = "SilverFile" if m["role"] == "assistant" else "Taxpayer"
            st.markdown(f"**{who}** ({(m.get('at') or '')[:16].replace('T', ' ')}): {md(m['text'])}")
    with tabs["Documents"]:
        if not view["documents"]:
            st.info("No documents yet.")
        for doc_id, d in view["documents"].items():
            ex = view["extractions"].get(doc_id, {})
            with st.expander(f"{d.get('doc_type')} - {d.get('file_name')} - {d.get('status')}"):
                st.markdown(f"Document id `{doc_id}` | read by **{ex.get('by')}** | payer **{ex.get('payer')}** | "
                            f"tax year {ex.get('tax_year')} | recipient SSN {(ex.get('recipient_ssn') or {}).get('masked')}")
                fields = [{"Box": b, "Label": v.get("label"), "Printed": v.get("raw") or "(blank)",
                           "Value used": v.get("value")} for b, v in (ex.get("fields") or {}).items()]
                if fields:
                    st.dataframe(fields, hide_index=True, use_container_width=True)
                if ex.get("issues"):
                    st.warning("; ".join(i["message"] for i in ex["issues"]))
                if d.get("path") and d.get("status") != "rejected":
                    try:
                        st.image(d["path"], use_container_width=True)
                    except Exception:
                        pass
    with tabs["Rules & audit"]:
        elig = view["eligibility"]
        st.markdown(f"**Rules check:** {elig.get('mode', '-')} / {elig.get('status', '-')}")
        for dcs in elig.get("decisions") or []:
            cites = "; ".join(c["doc"] + (f" p.{c['page']}" if c.get("page") else "") + f" {c['section']}"
                              for c in dcs["citations"])
            st.markdown(f"- `{dcs['rule_id']}` **{dcs['result']}** - {md(dcs['detail'])}  \n  <small>{md(cites)}</small>",
                        unsafe_allow_html=True)
        rv = view["review"]
        st.markdown(f"**Audit:** {rv.get('status', '-')} (revision passes in current streak: {rv.get('passes', 0)})")
        for h in rv.get("history") or []:
            st.markdown(f"- {h['at'][:19]}: {'passed' if not h['issues'] else str(len(h['issues'])) + ' issue(s)'}"
                        + "".join(f"\n    - `{i['check']}` -> {i['target']}: {md(i['detail'])}" for i in h["issues"]))
        for a in rv.get("advisory") or []:
            st.info(md(f"Advisory (line {a.get('line')}): {a.get('concern')}"))
    with tabs["Review history"]:
        events = view["human_events"]
        if not events:
            st.info("No human-review events on this case.")
        for e in events:
            r = e.get("resolution") or {}
            st.markdown(f"**{e['reason_label']}** ({e['assignment_ref']}) - {e['status']}  \n{md(e['summary'])}  \n"
                        f"Resolved by **{r.get('reviewer')}** at {r.get('at')} with *{ACTION_LABELS.get(r.get('action'), r.get('action'))}*  \n"
                        f"Rationale: {md(r.get('rationale'))}  \nEvidence: {md(r.get('evidence') or '-')}  \n"
                        f"Changes: {json.dumps(r.get('changes') or [])}")
    with tabs["Agent trace"]:
        st.dataframe([{"At": t["at"][11:19], "Agent": t["agent"], "Outcome": t["outcome"], "Summary": t["summary"]}
                      for t in view["trace"][-200:]], hide_index=True, use_container_width=True)
        model_calls = [m for m in view["metrics"] if m.get("kind") == "model_call"]
        tool_calls = [m for m in view["metrics"] if m.get("kind") == "tool_call"]
        st.caption(f"{len(tool_calls)} MCP tool calls, {len(model_calls)} model calls "
                   f"({sum(int(m.get('input_tokens') or 0) for m in model_calls):,} input tokens).")


def _review_form(svc, view: dict, event: dict, reviewer: str) -> None:
    st.markdown(f"### {event['reason_label']}  \n<small>Assignment {event['assignment_ref']} - raised by "
                f"{event.get('raised_by')}</small>", unsafe_allow_html=True)
    st.markdown(md(event["summary"]))
    also = (event.get("details") or {}).get("also")
    if also:
        st.markdown("Also flagged: " + md("; ".join(also)))
    if event.get("evidence"):
        with st.expander("Evidence", expanded=True):
            for ev in event["evidence"]:
                if ev.get("type") == "taxpayer_message":
                    st.markdown(f"Taxpayer said: *\"{md(ev['text'])}\"*")
                elif ev.get("type") == "rule":
                    st.markdown(f"Rule `{ev['rule_id']}`: " + "; ".join(
                        c["doc"] + (f" p.{c['page']}" if c.get("page") else "") + f" {c['section']}" for c in ev["citations"]))
                elif ev.get("type") == "tool":
                    st.markdown("MCP check: " + md(" ".join(ev.get("trace") or [])))
                else:
                    st.json(ev, expanded=False)
    labels = {a: ACTION_LABELS[a] for a in event["allowed_actions"]}
    with st.form(f"review_{event['id']}"):
        action = st.radio("Decision (only actions allowed for this situation are shown)", list(labels),
                          format_func=lambda a: labels[a])
        rationale = st.text_area("Rationale (required)", placeholder="What you checked and why this decision is right")
        evidence = st.text_area("Evidence (required to correct or confirm a value)",
                                placeholder="e.g. Phone call with the taxpayer on 10/24; W-2 box 1 confirmed")
        facts = sorted(view["facts"])
        doc_fields = [f"doc:{d}:{b}" for d, ex in view["extractions"].items() for b in (ex.get("fields") or {})]
        doc_flags = [f"doc:{d}:flag:taxable_not_determined" for d, ex in view["extractions"].items()
                     if ex.get("doc_type") == "1099-R"]
        fact_choices = facts + doc_fields + doc_flags
        st.markdown("Only for *correct a recorded fact*:")
        fact_id = st.selectbox("Fact to correct", ["(none)"] + fact_choices,
                               format_func=lambda k: FACT_LABELS.get(k, k))
        new_value = st.text_input("New value")
        st.markdown("Only for *set the filing status*:")
        fs = st.selectbox("Filing status", ["(none)", "single", "mfj", "mfs", "hoh", "qss"],
                          format_func=lambda k: FS_LABELS.get(k, k))
        st.markdown("Only for *ask the taxpayer a question*:")
        question = st.text_input("Question for the taxpayer")
        submitted = st.form_submit_button("Record decision and resume the case", type="primary")
    if submitted:
        if not reviewer.strip():
            st.error("Enter your name in the sidebar first; it is recorded on the decision.")
            return
        try:
            svc.resolve_review(view["case_id"], event["id"], action=action, reviewer=reviewer, rationale=rationale,
                               evidence=evidence, fact_id=None if fact_id == "(none)" else fact_id,
                               new_value=new_value or None, filing_status=None if fs == "(none)" else fs,
                               question=question or None)
            st.success("Decision recorded. The case has resumed.")
            st.rerun()
        except ServiceError as exc:
            st.error(str(exc))
