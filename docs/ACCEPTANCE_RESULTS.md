# Acceptance results

Recorded during the build on **2026-10-24** on branch `claude/sharp-wozniak-038bl3` (the commit that adds this
file; the code under test was last changed in the same commit). Environment: Linux x86_64 cloud container,
Python 3.11.17, **offline model mode** (no Anthropic API key was available), MCP server over stdio, Docker 29.9.1
with Compose v5.6.0. These results were produced by the AI build session (see [AI_DISCLOSURE](AI_DISCLOSURE.md)).
Team members should add their own runs below, especially on their Macs and in live mode.

## Results

| Check | Command / action | Result | Evidence |
|---|---|---|---|
| Unit tests | `python -m pytest tests/unit -q` | **237 passed** | tax tools vs all 2,062 printed IRS Tax Table rows x 4 statuses; TCW and Social Security oracles; decision table; reducer order; intake/guardrails; reviewer constraints; OCR on fixture images; graph shape |
| Integration tests | `python -m pytest tests/integration -q` | **32 passed** | all draft cases vs hand-worked results; 10 mandatory stops; HITL round trip; parallel extraction; review cycle and bound; both loop-guard triggers; restart persistence; duplicates; correction invalidation; live-mode plumbing with a fake Anthropic client |
| Live API tests | `python -m pytest tests/live -q` | **3 skipped (not run)** | needs `ANTHROPIC_API_KEY` |
| Evaluation catalogue | `python run.py eval` | **18/18 passed** | `traces/eval_results.json`, per-case traces in `traces/` |
| Environment check | `python run.py check` | passed (offline) | form templates, MCP server (14 tools), model mode |
| Fresh install | new venv, `pip install -r requirements.txt`, `run.py check`, eval cases 1-2 | passed | (opencv-python GUI build in this path; the lock uses the headless build) |
| Browser: clean case | `scripts/ui_smoke.py ... eval_case_1` against `run.py ui` | completed, draft submitted | screenshots taken during the build (not committed) |
| Browser: HITL case | `scripts/ui_smoke.py ... eval_case_2 review` | conflict follow-up -> interrupt -> dashboard decision -> draft ready | screenshots taken during the build |
| Keyboard only | Tab/Shift+Tab/Enter through Start, the answer box and option buttons | reachable and usable | build session log |
| Text enlargement | 650 px viewport at 2x scale (= 200% zoom of a 1300 px window) | layout reflows, sidebar collapses, question card readable | build session log |
| PDF output | assembly checks on every draft: field read-back + visible text on a flattened copy | passed for all draft cases | `assembly.pdf_check` in each case; previews in the dashboard |
| Docker image | `docker build` (the `ca_bundle` build secret was needed only for this sandbox's TLS proxy) | built | - |
| Docker run | container healthy; `run.py check`; eval cases 1, 2, unseen, 1099-R stop inside the container | passed | - |
| Docker persistence | restart the container; cases still listed from the `/data` volume | passed (4/4 cases kept) | - |
| Docker compose | `docker compose up -d`; health check; browser HITL flow on :8501 | passed | - |
| Context experiment (harness) | `run.py benchmark --proxy` both ways | harness works; strategy off grows 1 -> 10 images per call, strategy on stays at 1; extractions identical | `docs/metrics.md` (labelled proxy, not tokens) |

## Not run / still open

| Item | Why | Who / how |
|---|---|---|
| Live model runs (intake interpretation, Claude vision W-2 reading, critique) | no API key in the build environment | `python -m pytest tests/live -q` and the demo cases with a key set |
| §4.5 token measurements | needs live API usage numbers | `python run.py benchmark --no-context-strategy`, `python run.py benchmark`, `python run.py metrics` |
| Native run on macOS; Docker on Apple Silicon | build ran on Linux x86_64 | Person 5 |
| Screen-reader test | not available in the build environment | Person 2 |
| Human re-check of hand-worked expected results | expected results were worked by the AI separately from the code | Person 5 / Person 6 |
| GitHub Actions workflow (`.github/workflows/tests.yml`) | added but not yet observed running on GitHub | first push to `main` / PR |

## Team runs

| Date | Who | Machine | Mode | Commands | Result | Notes |
|---|---|---|---|---|---|---|
| | | | | | | |
