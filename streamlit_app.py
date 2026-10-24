"""SilverFile local web app.  Start with:  python run.py ui   (or: streamlit run streamlit_app.py)"""

import streamlit as st

st.set_page_config(page_title="SilverFile", page_icon="📄", layout="wide")

from src.ui import dashboard, taxpayer  # noqa: E402
from src.ui.components import apply_style, get_service, mode_caption  # noqa: E402
from src.ui.provenance_view import render_draft  # noqa: E402

apply_style()
service = get_service()
st.sidebar.markdown("## SilverFile")
st.sidebar.caption("Classroom prototype for Kushim. Prepares a DRAFT Form 1040-SR. Never files. Never gives advice.")
view = st.sidebar.radio("View", ["Taxpayer intake", "Employee dashboard", "Draft & provenance"])
st.sidebar.divider()
st.sidebar.caption(mode_caption(service))
health = service.health()
st.sidebar.caption(("MCP tax tools: connected (" + str(len(health["mcp_tools"])) + " tools)") if health["mcp_ok"]
                   else f"MCP tax tools: NOT available - {health.get('mcp_error')}")

if view == "Taxpayer intake":
    taxpayer.render()
elif view == "Employee dashboard":
    dashboard.render()
else:
    st.title("Draft return and provenance")
    cases = [c for c in service.list_cases() if c.get("draft_version")]
    if not cases:
        st.info("No drafts yet.")
    else:
        case_id = st.selectbox("Case", [c["case_id"] for c in cases],
                               format_func=lambda c: f"{c} - " + next((x['taxpayer'] or '' for x in cases if x['case_id'] == c), ''))
        render_draft(service.view(case_id), key_prefix="pv_")
