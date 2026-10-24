"""Real Anthropic API checks. Skipped unless ANTHROPIC_API_KEY is set.

    ANTHROPIC_API_KEY=... python -m pytest tests/live -q
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def live_llm():
    from src.config import get_settings
    from src.llm import AnthropicLLM

    s = get_settings()
    return AnthropicLLM(s.anthropic_model, s.effort, s.use_fallbacks)


def test_live_w2_image_extraction(live_llm):
    from src.agents.document_extraction import SYSTEM_PROMPT, build_record
    from src.contracts import DocumentExtraction
    from src.llm import image_block

    data = (ROOT / "demo" / "w2_image_1.png").read_bytes()
    call = live_llm.structured(agent="document_extraction", system=SYSTEM_PROMPT, schema=DocumentExtraction,
                               messages=[{"role": "user", "content": [image_block(data, "image/png"),
                                                                      {"type": "text", "text": "Form W-2, 2025."}]}],
                               offline=lambda: None, purpose="live-test")
    rec = build_record({"doc_id": "d", "doc_type": "W-2", "revision": 0}, call.data, "anthropic", None, "now")
    assert rec["fields"]["1"]["value"] == "46850.00"
    assert rec["fields"]["2"]["value"] == "3980.00"
    assert rec["tax_year"] == "2025" and rec["recipient_ssn"]["last4"] == "1234"
    assert call.usage["input_tokens"] > 0


def test_live_intake_detects_advice(live_llm):
    from src.agents.intake import SYSTEM_PROMPT
    from src.contracts import IntakeInterpretation

    content = ("CURRENT QUESTION: [filing_status] (choice) Which filing status will you use?\n"
               "TAXPAYER'S REPLY: Would we pay less tax if we filed separately?\nInterpret the reply.")
    call = live_llm.structured(agent="intake", system=SYSTEM_PROMPT, schema=IntakeInterpretation,
                               messages=[{"role": "user", "content": content}], offline=lambda: None,
                               purpose="live-test")
    assert call.data.intent == "advice" or call.data.signals.advice_request


def test_live_end_to_end_case_1(tmp_path):
    from src.config import get_settings
    from src.driver import load_case, run_case
    from src.service import SilverFileService

    s = get_settings()
    s.var_dir = tmp_path / "var"
    s.llm_mode = "anthropic"
    view = run_case(SilverFileService(settings=s), load_case("eval_case_1"))
    assert view["status"] == "submitted_for_internal_review"
    assert view["lines"]["1z"]["value"] == "46850" and view["lines"]["34"]["value"] == "1443"
