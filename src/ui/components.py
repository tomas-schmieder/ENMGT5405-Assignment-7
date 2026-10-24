"""Shared Streamlit pieces: styling, service handle, status badges, line labels."""

from __future__ import annotations

import streamlit as st

from src.state import STATUS_LABELS

LINE_LABELS = {
    "1a": "Wages from Form(s) W-2, box 1", "1z": "Total wages (lines 1a-1h)",
    "2a": "Tax-exempt interest", "2b": "Taxable interest", "3a": "Qualified dividends", "3b": "Ordinary dividends",
    "4a": "IRA distributions", "4b": "IRA distributions - taxable amount", "5a": "Pensions and annuities",
    "5b": "Pensions and annuities - taxable amount", "6a": "Social Security benefits",
    "6b": "Social Security benefits - taxable amount", "7a": "Capital gain or (loss)",
    "8": "Additional income (Schedule 1, line 10)", "9": "Total income", "10": "Adjustments (Schedule 1, line 26)",
    "11a": "Adjusted gross income", "11b": "Adjusted gross income (repeated)", "12e": "Standard deduction",
    "13a": "Qualified business income deduction", "13b": "Additional deductions (Schedule 1-A, senior deduction)",
    "14": "Total deductions", "15": "Taxable income", "16": "Tax", "17": "Schedule 2, line 3", "18": "Lines 16 + 17",
    "19": "Credit for dependents (Schedule 8812)", "20": "Schedule 3, line 8", "21": "Lines 19 + 20",
    "22": "Line 18 minus line 21", "23": "Other taxes (Schedule 2, line 21)", "24": "Total tax",
    "25a": "Federal tax withheld - Form(s) W-2", "25b": "Federal tax withheld - Form(s) 1099 / SSA-1099",
    "25c": "Federal tax withheld - other forms", "25d": "Total federal tax withheld",
    "26": "2025 estimated tax payments", "31": "Schedule 3, line 15", "32": "Other payments and refundable credits",
    "33": "Total payments", "34": "Amount overpaid", "35a": "Amount to be refunded", "37": "Amount you owe",
}

FORM_ORDER = ["1a", "1z", "2a", "2b", "3a", "3b", "4a", "4b", "5a", "5b", "6a", "6b", "7a", "8", "9", "10", "11a",
              "11b", "12e", "13a", "13b", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25a",
              "25b", "25c", "25d", "26", "31", "32", "33", "34", "35a", "37"]

STATUS_STYLE = {
    "intake": ("#1d4ed8", "#dbeafe"), "awaiting_documents": ("#1d4ed8", "#dbeafe"),
    "processing": ("#6d28d9", "#ede9fe"), "revising": ("#6d28d9", "#ede9fe"),
    "needs_human_review": ("#9a3412", "#ffedd5"), "draft_ready": ("#166534", "#dcfce7"),
    "submitted_for_internal_review": ("#065f46", "#d1fae5"), "referred_out_of_scope": ("#374151", "#e5e7eb"),
    "closed": ("#374151", "#e5e7eb"), "error": ("#991b1b", "#fee2e2"),
}

CSS = """
<style>
:root { --sf-ink: #111827; --sf-muted: #4b5563; --sf-line: #d1d5db; --sf-accent: #1e3a8a; }
html, body, [class*="css"] { font-family: "Source Sans Pro", "Segoe UI", Arial, sans-serif; }
.block-container { padding-top: 1.6rem; max-width: 1200px; }
h1, h2, h3 { color: var(--sf-accent); letter-spacing: 0; }
.sf-badge { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 0.4rem; font-weight: 600;
            font-size: 0.9rem; border: 1px solid currentColor; white-space: nowrap; }
.sf-question { border: 2px solid var(--sf-accent); border-radius: 0.6rem; padding: 1.1rem 1.3rem;
               background: #f8fafc; margin: 0.6rem 0 0.8rem 0; }
.sf-question .sf-q { font-size: 1.45rem; line-height: 1.45; color: var(--sf-ink); font-weight: 600; white-space: pre-line; }
.sf-question .sf-gloss { font-size: 1.05rem; color: var(--sf-muted); margin-top: 0.5rem; }
.sf-question .sf-section { font-size: 0.95rem; color: var(--sf-muted); text-transform: uppercase; letter-spacing: 0.04em; }
.sf-hint { font-size: 1.1rem; color: #9a3412; font-weight: 600; margin-top: 0.4rem; }
.sf-large [data-testid="stChatMessageContent"] p { font-size: 1.2rem; line-height: 1.55; }
.sf-card { border: 1px solid var(--sf-line); border-radius: 0.5rem; padding: 0.9rem 1rem; background: #ffffff; }
.sf-kv { font-size: 0.95rem; color: var(--sf-muted); }
.sf-amount { font-variant-numeric: tabular-nums; font-weight: 600; }
.sf-draft-banner { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; padding: 0.5rem 0.8rem;
                   border-radius: 0.4rem; font-weight: 600; }
</style>
"""


def md(text) -> str:
    """Escape text for st.markdown: '$' would otherwise start a LaTeX formula."""
    return str(text if text is not None else "").replace("$", "\\$")


def html(text) -> str:
    """Escape text placed inside raw HTML blocks."""
    import html as _h

    return _h.escape(str(text if text is not None else "")).replace("$", "&#36;").replace("\n", "<br>")


def apply_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner="Starting SilverFile (tax tools and case store)...")
def get_service():
    from src.service import SilverFileService

    return SilverFileService()


def badge(status: str) -> str:
    fg, bg = STATUS_STYLE.get(status, ("#374151", "#f3f4f6"))
    label = STATUS_LABELS.get(status, status)
    return f'<span class="sf-badge" style="color:{fg};background:{bg}">{label}</span>'


def money(value) -> str:
    try:
        return f"${int(value):,}"
    except (TypeError, ValueError):
        return "-"


def mode_caption(service) -> str:
    if service.llm.mode == "anthropic":
        return f"Live mode: Anthropic model `{service.llm.model}` reads documents and conversation."
    return ("Offline mode: no API key set, so documents are read with on-device OCR and replies with rule-based "
            "parsing. Set ANTHROPIC_API_KEY for live mode.")
