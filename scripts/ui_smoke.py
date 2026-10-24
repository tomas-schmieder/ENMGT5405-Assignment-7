"""Browser smoke test: drive a fixture case through the running Streamlit UI.

Plays the taxpayer through the chat and option buttons, uploads the fixture
images with the file picker, and (with a third argument) plays the reviewer in
the dashboard. Saves screenshots to OUT_DIR.

Usage (app must be running; default URL http://localhost:8501, override with
SILVERFILE_URL):

    python scripts/ui_smoke.py OUT_DIR eval_case_1
    python scripts/ui_smoke.py OUT_DIR eval_case_2 review

Needs ``pip install playwright`` and a Chromium build. Set CHROMIUM_PATH to an
existing browser executable, or run ``playwright install chromium`` once.
"""
import json
import os
import re
import sys

sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright  # noqa: E402

from src.agents.intake_script import QUESTIONS  # noqa: E402

SP, CASE = sys.argv[1], sys.argv[2]
REVIEW = len(sys.argv) > 3
spec = json.load(open(f"data/fixtures/{CASE}/case.json"))
by_text = {}
for q in QUESTIONS:
    if q.id in spec["answers"] or q.text not in by_text:
        by_text[q.text] = q.id


def wait_change(page, prev, timeout_ms=30000):
    waited = 0
    while waited < timeout_ms:
        page.wait_for_timeout(500)
        waited += 500
        if page.locator("[data-testid='stStatusWidget']").count() == 0 and current_question(page) != prev:
            return
    print("  (timeout waiting for", (prev or "")[:40], ")")


def current_question(page):
    loc = page.locator(".sf-q")
    if loc.count() == 0:
        return None
    return loc.first.inner_text().strip()


with sync_playwright() as p:
    exe = os.environ.get("CHROMIUM_PATH")
    b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    page = b.new_page(viewport={"width": 1300, "height": 1000})
    page.goto(os.environ.get("SILVERFILE_URL", "http://localhost:8501"), wait_until="networkidle")
    page.wait_for_timeout(5000)
    page.get_by_role("button", name="Start").click()
    page.wait_for_timeout(4000)
    page.screenshot(path=f"{SP}/ui_start_{CASE}.png", full_page=True)
    case_id = re.search(r"SF-\d{8}-[A-F0-9]{6}", page.content()).group(0)
    print("case", case_id)
    for turn in range(80):
        q = current_question(page)
        if q is None:
            break
        qid = by_text.get(q)
        if q.startswith("Please add a photo"):
            for d in spec["documents"]:
                page.locator("input[type=file]").set_input_files(d["file"])
                page.wait_for_timeout(2500)
                page.get_by_role("button", name=re.compile("^Add '")).first.click()
                page.wait_for_timeout(2500)
            page.screenshot(path=f"{SP}/ui_upload_{CASE}.png", full_page=True)
            page.get_by_role("button", name="Send these forms").click()
            wait_change(page, q, 60000)
            continue
        if q.startswith("Here is a summary"):
            page.screenshot(path=f"{SP}/ui_summary_{CASE}.png", full_page=True)
            qid = "confirm_summary"
        if q.startswith("Your draft Form 1040-SR is ready"):
            page.screenshot(path=f"{SP}/ui_draft_ready_{CASE}.png", full_page=True)
            page.get_by_role("button", name="Send it to Kushim for review").click()
            page.wait_for_timeout(4000)
            break
        if q.startswith("Your W-2 form shows wages"):
            page.screenshot(path=f"{SP}/ui_conflict_{CASE}.png", full_page=True)
            page.get_by_role("button", name="My number is right").click()
            wait_change(page, q)
            continue
        if qid is None:
            print("UNKNOWN QUESTION", q[:80])
            break
        if qid in {"spouse_died_2025", "tp_blind", "us_resident"}:
            # use the Yes/No buttons for some yes/no questions (keyboard-reachable buttons)
            page.get_by_role("button", name=spec["answers"][qid].capitalize(), exact=True).click()
        else:
            box = page.get_by_placeholder(re.compile("press Enter"))
            box.fill(str(spec["answers"][qid]))
            box.press("Enter")
        wait_change(page, q)
        if turn == 4:
            page.screenshot(path=f"{SP}/ui_turn4_{CASE}.png", full_page=True)
    page.wait_for_timeout(2000)
    page.screenshot(path=f"{SP}/ui_end_{CASE}.png", full_page=True)
    print("final question:", current_question(page))
    print("waiting for volunteer:", "volunteer is looking" in page.content())
    print("submitted:", "has been sent to a Kushim volunteer" in page.content())
    if REVIEW:
        page.get_by_text("Employee dashboard").click()
        page.wait_for_timeout(4000)
        page.get_by_placeholder("e.g. J. Rivera, Kushim volunteer").fill("J. Rivera (demo reviewer)")
        page.keyboard.press("Tab")
        page.wait_for_timeout(1500)
        page.screenshot(path=f"{SP}/ui_dashboard_{CASE}.png", full_page=True)
        page.get_by_role("button", name="Open").first.click()
        page.wait_for_timeout(4000)
        page.screenshot(path=f"{SP}/ui_review_{CASE}.png", full_page=True)
        act = spec["reviewer_actions"][0]
        page.get_by_text("Confirm the document value is correct (evidence required)").click()
        page.get_by_placeholder("What you checked and why this decision is right").fill(act["rationale"])
        page.get_by_placeholder(re.compile("Phone call with the taxpayer")).fill(act["evidence"])
        page.get_by_role("button", name="Record decision and resume the case").click()
        page.wait_for_timeout(9000)
        page.screenshot(path=f"{SP}/ui_after_review_{CASE}.png", full_page=True)
        print("after review contains 'Draft ready':", "Draft ready" in page.content())
    b.close()
