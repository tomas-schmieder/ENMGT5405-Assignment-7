"""Draft return with line-level provenance (assignment §4.2).

A reviewer picks any line and sees the amount, where it came from (document
box, dated answer, reviewer correction) and the exact MCP calculation trace
and rules behind it.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.agents.eligibility_rules import registry
from src.provenance import resolve
from src.ui.components import FORM_ORDER, LINE_LABELS, md, money

KIND_LABEL = {"document": "From a document", "direct_input": "Taxpayer's answer",
              "reviewer_correction": "Reviewer correction", "derived": "Calculated (MCP tool)"}


def _source_type(rec: dict, prov: dict) -> str:
    if rec.get("kind") != "derived":
        return KIND_LABEL.get(rec.get("kind"), rec.get("kind", ""))
    kinds = set()
    stack = [rec]
    seen = set()
    while stack:
        r = stack.pop()
        for inp in (r.get("inputs") or {}).values():
            for ref in inp.get("refs") or ([inp["ref"]] if inp.get("ref") else []):
                if ref in seen:
                    continue
                seen.add(ref)
                child = prov.get(ref) or {}
                if child.get("kind") == "derived":
                    stack.append(child)
                elif child:
                    kinds.add(KIND_LABEL.get(child["kind"], child["kind"]))
    return "Calculated from: " + (", ".join(sorted(kinds)) if kinds else "confirmed zero / scope rule")


def line_table(view: dict) -> list[dict]:
    rows = []
    prov = view["provenance"]
    for line in FORM_ORDER:
        entry = view["lines"].get(line)
        if not entry:
            continue
        rec = prov.get(f"line:{line}", {})
        rows.append({"Line": line, "Description": LINE_LABELS.get(line, line), "Amount": money(entry["value"]),
                     "Source": _source_type(rec, prov), "Tool call": rec.get("call_id", "")})
    return rows


def _render_record(rec: dict, key: str) -> None:
    kind = rec.get("kind")
    if kind == "document":
        st.markdown(md(f"**{rec.get('doc_type')}** from *{rec.get('file_name') or rec.get('doc_id')}* - box "
                       f"**{rec.get('box')}** ({rec.get('label')})"))
        st.markdown(md(f"Printed: `{rec.get('raw_text')}` -> used as **${float(rec.get('value') or 0):,.2f}**  \n"
                    f"Owner: {rec.get('owner')} | Tax year: {rec.get('tax_year')} | Read by: {rec.get('extracted_by')} "
                    f"| Source: {rec.get('source')} | SHA-256: `{(rec.get('sha256') or '')[:16]}...`"))
    elif kind == "direct_input":
        st.markdown(md(f"**Direct user input** by {rec.get('entered_by')} on {rec.get('entered_at')}  \n"
                       f"Question: *{rec.get('question_text')}*  \nAnswer recorded: **{rec.get('value')}**"))
    elif kind == "reviewer_correction":
        st.markdown(md(f"**Reviewer correction** by {rec.get('reviewer')} on {rec.get('entered_at')}: "
                       f"{rec.get('prior_value')} -> **{rec.get('value')}**  \nRationale: {rec.get('rationale')}  \n"
                       f"Evidence: {rec.get('evidence')}"))
    elif kind == "derived":
        st.markdown(f"**MCP tool `{rec.get('tool')}`** v{rec.get('tool_version')} - call `{rec.get('call_id')}` "
                    f"({rec.get('transport')}) at {rec.get('called_at')}")
        if rec.get("explanation"):
            st.info(md(rec["explanation"]))
        st.markdown("\n".join(f"{i + 1}. {md(step)}" for i, step in enumerate(rec.get("trace") or [])))
        rules = registry()
        cites = []
        for rid in rec.get("rule_ids") or []:
            r = rules.get(rid)
            if r:
                refs = "; ".join(f"{c['doc']}" + (f" p.{c['page']}" if c.get("page") else "") + f" ({c['section']})"
                                 for c in r["citations"])
                cites.append(f"- **{rid}** {r['title']}: {refs}")
        if cites:
            st.markdown("Rules and sources:\n" + "\n".join(cites))


def _render_tree(node: dict, prov: dict, depth: int = 0) -> None:
    rec = node.get("record")
    if node.get("missing"):
        st.error(f"Missing provenance record: {node['key']}")
        return
    label = node["key"]
    if rec.get("kind") == "derived":
        label = f"Line {rec['line']} = {money(rec['value'])}  ({LINE_LABELS.get(rec['line'], '')})"
    elif rec.get("kind") == "document":
        label = f"{rec.get('doc_type')} box {rec.get('box')}: ${float(rec.get('value') or 0):,.2f}"
    elif rec.get("kind") in {"direct_input", "reviewer_correction"}:
        label = f"{KIND_LABEL[rec['kind']]}: {rec.get('fact_id') or rec.get('key')} = {rec.get('value')}"
    if node.get("as_input"):
        label = f"{node['as_input']} <- {label}"
    with st.expander(md(label), expanded=depth == 0):
        _render_record(rec, node["key"])
        for child in node.get("children") or []:
            _render_tree(child, prov, depth + 1)


def render_draft(view: dict, key_prefix: str = "") -> None:
    assembly = view.get("assembly") or {}
    if not view.get("lines"):
        st.info("No calculations yet. The draft appears here once intake, documents and checks are complete.")
        return
    st.markdown('<div class="sf-draft-banner">DRAFT - not filed. Every amount below links to its source.</div>',
                unsafe_allow_html=True)
    if assembly.get("status") == "ready":
        c1, c2, c3 = st.columns([1, 1, 2])
        pdf = Path(assembly["pdf_path"])
        if pdf.exists():
            c1.download_button("Download draft Form 1040-SR (PDF)", pdf.read_bytes(), file_name=pdf.name,
                               mime="application/pdf", key=f"{key_prefix}pdf", use_container_width=True)
        audit = Path(assembly.get("audit_path", ""))
        if audit.exists():
            c2.download_button("Download audit record (JSON)", audit.read_bytes(), file_name=audit.name,
                               mime="application/json", key=f"{key_prefix}audit", use_container_width=True)
        chk = assembly.get("pdf_check", {})
        c3.markdown(f"Version {assembly.get('version')} | {assembly.get('fields_written')} fields | "
                    f"{chk.get('pages')} pages | field check: {'passed' if chk.get('logical_ok') else 'FAILED'} | "
                    f"visual check: {'passed' if chk.get('visible_ok') else 'FAILED'}")
        if assembly.get("cover_note"):
            st.markdown(f"**Cover note for the reviewer:** {md(assembly['cover_note'])}")
    else:
        st.warning("These values are not yet a finished draft (checks still running or a review is pending).")
    rows = line_table(view)
    st.dataframe(rows, hide_index=True, use_container_width=True,
                 column_config={"Amount": st.column_config.TextColumn(width="small"),
                                "Line": st.column_config.TextColumn(width="small")})
    lines = [r["Line"] for r in rows]
    pick = st.selectbox("Inspect a line: see the sources and the calculation", lines,
                        format_func=lambda l: f"Line {l} - {LINE_LABELS.get(l, '')} ({money(view['lines'][l]['value'])})",
                        key=f"{key_prefix}pick", index=lines.index("16") if "16" in lines else 0)
    _render_tree(resolve(view["provenance"], f"line:{pick}"), view["provenance"])
    if assembly.get("previews"):
        st.markdown("#### Form preview")
        tabs = st.tabs([f"Page {i + 1}" for i in range(len(assembly["previews"]))])
        for tab, path in zip(tabs, assembly["previews"]):
            if Path(path).exists():
                tab.image(path, use_container_width=True)
