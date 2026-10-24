# ENMGT5405-Assignment-7
SilverFile: a LangGraph multi-agent system that guides seniors through preparing a draft IRS Form 1040-SR (tax year 2025), with per-line provenance, human-in-the-loop escalation, and a staff review dashboard. Built for Kushim Financial as a Cornell ENMGT 5405 team project.

> **Classroom prototype.** SilverFile prepares a **draft** for a Kushim volunteer to review. It never files
> anything and never gives tax advice. Use only made-up information and test Social Security numbers that start
> with 9 (for example `900-12-3456`); real-looking SSNs are refused.

![SilverFile orchestration](docs/graph.png)

## Contents
- [Quick start](#quick-start)
- [Try the two demo cases](#try-the-two-demo-cases)
- [What SilverFile does](#what-silverfile-does)
- [Architecture](#architecture)
- [Testing and evaluation](#testing-and-evaluation)
- [Repository layout](#repository-layout)
- [Team](#team)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)

## Quick start

SilverFile runs locally in a browser. It works in two modes:

| Mode | When | Documents are read by | Replies are understood by |
|---|---|---|---|
| **Live** | `ANTHROPIC_API_KEY` is set | Claude vision | Claude (plus deterministic guardrails) |
| **Offline** | no key | on-device OCR (RapidOCR) tuned to the IRS layouts | rule-based parser |

Every dollar amount is calculated by the same MCP tax-tool server in both modes.

### Option A: Docker (simplest)

```bash
cp .env.example .env            # optional: add ANTHROPIC_API_KEY for live mode
docker compose up --build       # first build takes a few minutes
```

Open **http://localhost:8501**. Cases, uploads and drafts are kept in the Docker volume `silverfile-data`, so
they survive `docker compose down` / `up`. Remove them with `docker compose down -v`. Run the checks inside the
container with `docker compose exec silverfile python run.py check`.

### Option B: Python on macOS or Linux

Requires **Python 3.11** (tested with 3.11.17).

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # or, for the exact tested set: pip install --no-deps -r requirements.lock
cp .env.example .env                     # optional: add ANTHROPIC_API_KEY for live mode
python run.py check                      # verifies form templates, the MCP tool server and (if set) the API key
python run.py ui                         # opens http://localhost:8501
```

### Live mode settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | (none) | enables live mode |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | model for every agent call (must support images and structured outputs) |
| `SILVERFILE_LLM_MODE` | `auto` | `auto`, `anthropic` or `offline` |
| `SILVERFILE_EFFORT` | `low` | model effort for agent calls |
| `SILVERFILE_CONTEXT_STRATEGY` | `true` | selective-recall context (set `false` to replay the full conversation) |
| `SILVERFILE_VAR_DIR` | `./var` | where cases, uploads and drafts are stored |

## Try the two demo cases

| | Walkthrough | What it shows |
|---|---|---|
| 1 | [demo/eval_case_1.md](demo/eval_case_1.md) | Clean run: single filer, W-2 image (`demo/w2_image_1.png`) -> filled draft 1040-SR (refund $1,443) |
| 2 | [demo/eval_case_2.md](demo/eval_case_2.md) | HITL: stated wages ($54,000) conflict with the W-2 ($45,200) -> follow-up -> interrupt -> reviewer resolves in the dashboard -> resume -> draft (refund $1,267) |

Each walkthrough lists every answer, the documents to upload, how to resolve the human-review event, and the
hand-worked expected line values. The same cases run from the command line:

```bash
python run.py demo eval_case_1
python run.py demo eval_case_2            # stops at the human-review event
python run.py demo eval_case_2 --review   # also plays the reviewer
```

**Your own W-2:** fill in a W-2 (for example the blank `data/reference_tax_forms/forms/2025_Form_W-2.pdf`, Copy B)
with fictional values and a 900-series SSN, save it as PNG/JPEG/PDF, and upload it at the document step. Live
mode reads photos and scans robustly. Offline OCR expects the official IRS layout and asks for a clearer copy
rather than guessing.

### The app

* **Taxpayer intake**: one question at a time in large type, with buttons for options plus *I'm not sure*, *Go back
  one question* and *Talk to a person*. Uploads (or typing in non-W-2 forms), a summary to confirm, the draft at a
  glance, and *Send it to Kushim for review*. Leave at any time and resume with the case number.
* **Employee dashboard**: counts and a filterable list of all cases (*in progress*, *needs human review*,
  *draft ready*, *submitted internally for review*, *referred*), a review queue, and per case: the human-review
  decision form, draft and provenance, conversation, documents, rule decisions and audit, review history and agent
  trace.
* **Draft & provenance**: download the filled official PDF (with Schedule 1-A when used) and the JSON audit record,
  and inspect any line: its MCP calculation trace, cited rules, and the document boxes and dated answers behind it.

## What SilverFile does

**In scope (assignment §3.3):** W-2, SSA-1099, 1099-R (code 7, IRA or pension, optional QCD), 1099-INT, 1099-DIV;
all five filing statuses; standard deduction with the line 12d boxes; the Schedule 1-A enhanced senior deduction;
Schedule 1/2/3 totals typed in directly; estimated payments and withholding.

**Lines produced (§3.1):** filing status, dependents, 1z, 2a/2b, 3a/3b, 4a/4b, 5a/5b, 6a/6b, 9, 10, 11a/11b, 12d,
12e, 13b, 14, 15, 16, 24, 25a-25d, 26, 33, 34/37 (plus the supporting lines 17-23, 31-32, 35a).

**Always escalates to a person (§4.4):** anything out of scope (itemizing, self-employment/1099-NEC, rental,
capital gains including capital gain distributions, digital assets, foreign income, amended/prior-year or state
returns, Standard Deduction Chart exceptions, not 1040-SR eligible); an unresolved statement/document conflict;
a 1099-R with box 2b checked (or a code other than 7); requests for tax advice; filing-status ambiguity
(especially a spouse who died in 2025); and signs of financial exploitation or third-party pressure.

**The four key rules (§3.2)** are implemented in `src/tools/tax_calculations.py` and `src/agents/eligibility_rules.py`:
1040-SR eligibility (born before January 2, 1961; one spouse is enough on a joint return), the Standard Deduction
Chart, the enhanced senior deduction (separate from the age addition, with a 6% per-person phaseout), and the
Social Security worksheet, computed after all other income because line 6b feeds AGI.

## Architecture

Seven roles (six functional agents plus the orchestrator), each with its own prompt, contract, graph node and
trace. They share one model account; distinct roles do not need distinct models.

| Agent | Responsibility | Key constraint |
|---|---|---|
| **Orchestrator** | Chooses the next hop from state; loop guard; termination; dashboard status | Never extracts, computes or converses (deterministic code) |
| **Intake** | The only agent that talks to the taxpayer; one plain-language question at a time; relays follow-ups; notices red flags | No arithmetic, no tax rules |
| **Document Extraction** | Reads each image into typed boxes (parallel); aggregator validates, removes duplicates, publishes source facts | Does not decide what a value means |
| **Eligibility & Rules** | Eligibility, filing status, boxes, scope, conflicts, document rules | Every decision cites `data/rule_registry.json` |
| **Computation** | Fills every derived line | Every number from an MCP tool call (32 per return) |
| **Review / Audit** | Tries to falsify the return: recomputes, checks provenance, sources, staleness, scope | Sends work back; never fixes (max 3 revision passes) |
| **Return Assembly & Provenance** | Final lineage gate; fills and verifies the official PDF; audit record | Cannot recalculate; returns gaps to the producer |

Orchestration requirements (§4.1), all tested:
* **conditional routing** from state (`src/agents/orchestrator.py`);
* a **parallel branch** (`Send` per document) with an **aggregation step and order-independent reducers**
  (`src/state.py`);
* a **bounded review -> revise cycle**;
* a **loop guard** (30 hand-offs per run, or 4 repeats of the same routing signature -> human review).

**Human-in-the-loop** uses real LangGraph `interrupt()` calls. The case is persisted in a SQLite checkpointer and
resumed with the reviewer's decision on the same thread. Reviewer actions are limited per reason (no "approve
everything") and recorded with name, time, rationale, evidence and changes.

**MCP tools** (`mcp_server/server.py`, stdio): `aggregate_amounts`, `compare_amounts`, `ira_distributions`,
`taxable_social_security`, `total_income`, `adjusted_gross_income`, `standard_deduction`,
`enhanced_senior_deduction`, `deductions_and_taxable_income`, `income_tax` (Tax Table / Tax Computation Worksheet /
Qualified Dividends worksheet), `total_tax`, `total_payments`, `refund_or_amount_owed`, `verify_return`.

More detail: [Implementation notes](docs/IMPLEMENTATION_NOTES.md) (design, every agent, loop guard, HITL,
provenance, accessibility and PII choices, failure modes) | [State contract](docs/STATE_CONTRACT.md) |
[Assumptions](docs/ASSUMPTIONS.md) | [Requirements matrix](docs/REQUIREMENTS_MATRIX.md) |
[Policy](data/policy.md) | [Rule registry](data/rule_registry.json) | [Graph (Mermaid)](docs/graph.mmd)

## Testing and evaluation

```bash
python -m pytest -q                       # unit + integration (real graph, real MCP server, offline model)
python -m pytest tests/live -q            # real Anthropic API checks (skipped without ANTHROPIC_API_KEY)
python run.py eval                        # all 18 evaluation cases vs hand-worked results; traces -> traces/
python run.py benchmark --no-context-strategy && python run.py benchmark && python run.py metrics   # §4.5 (live)
python scripts/ui_smoke.py OUT_DIR eval_case_2 review   # browser run through the real UI (needs playwright)
```

Latest recorded results are in [docs/ACCEPTANCE_RESULTS.md](docs/ACCEPTANCE_RESULTS.md). The tax function matches
every row of the printed 2025 IRS Tax Table. Expected results for each case are hand-worked in
`evals/expected_results/` and never loaded by the agents. Context-window measurements are in
[docs/metrics.md](docs/metrics.md); they require a live API run, and until one is recorded that file says so.

## Repository layout

```
README.md  run.py  streamlit_app.py  requirements.txt  requirements.lock  .env.example  Dockerfile  compose.yaml
src/
  config.py  state.py  graph.py  memory.py  hitl.py  provenance.py  contracts.py  llm.py  service.py  store.py  driver.py
  money.py  ssn.py
  agents/   orchestrator.py  intake.py  intake_script.py  document_extraction.py  eligibility_rules.py
            computation.py  review_audit.py  return_assembly.py  human_review.py  base.py
  tools/    tax_calculations.py (deterministic)  mcp_client.py  ocr_reader.py
  output/   pdf_fields.py  pdf_writer.py
  ui/       taxpayer.py  dashboard.py  provenance_view.py  components.py
mcp_server/server.py              MCP tax-tool server (stdio)
data/
  reference_tax_forms/            official blank forms + IRS instructions (identity-checked)
  source_manifest.json  rule_registry.json  policy.md
  generate_fixtures.py  fixtures/  19 fictional cases with document images
evals/  cases.json  expected_results/
tests/  unit/  integration/  live/  oracles/
traces/                           evaluation traces and benchmark runs
docs/   graph.png  graph.mmd  metrics.md  IMPLEMENTATION_NOTES.md  ASSUMPTIONS.md  REQUIREMENTS_MATRIX.md
        STATE_CONTRACT.md  ACCEPTANCE_RESULTS.md  AI_DISCLOSURE.md  CONTRIBUTIONS.md
demo/   eval_case_1.md  eval_case_2.md  w2_image_1.png  w2_image_2.png  ssa1099_case_2.png  w2_image_unseen.png
scripts/ context_benchmark.py  draw_graph.py  build_source_manifest.py  ui_smoke.py
```

## Team

| Focus area | Team member assigned |
|---|---|
| Agent memory | *Person 1 - to be filled in* |
| Inter agent communication | *Person 2 - to be filled in* |
| Task division and management | *Person 6 - to be filled in* |
| MLOps/DevOps | *Person 5 - to be filled in* |
| Guardrails and ethics | *Person 4 - to be filled in* |
| Security | *Person 3 - to be filled in* |

Who did what is recorded in [docs/CONTRIBUTIONS.md](docs/CONTRIBUTIONS.md). How AI was used is described in
[docs/AI_DISCLOSURE.md](docs/AI_DISCLOSURE.md).

## Known limitations

* **Live paths not yet run with a real key.** The build environment had no API key: live model calls were tested
  with a fake client only, and the §4.5 token measurements have not been recorded yet (see
  [metrics](docs/metrics.md)).
* **Offline OCR is strict.** It is tuned to the official IRS form layouts and rejects unclear images rather than
  guessing. Use live mode for photographed forms.
* **Simplified scope.** Lines 1b-1i, 7a, 13a, 25c and 27a-30 are not produced (anything needing them escalates).
  4a/5a are always filled with the gross amount (A-14). Credits for dependents are only a typed-in line 19.
* **No home address or bank numbers** are collected (minimum PII); a preparer adds them at signing.
* **No authentication.** This is a local prototype; the reviewer name is self-declared.
* **Not tax software.** It is accurate only within the assignment's scope and has not been reviewed by a tax
  professional.

## Troubleshooting

| Message | Fix |
|---|---|
| `MCP tax tools: FAILED` | Run from the project folder with the virtual environment active; `python -m mcp_server.server` should start without errors. |
| `Anthropic API key was rejected` / `Model ... was not found` | Check `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` in `.env`; or set `SILVERFILE_LLM_MODE=offline`. |
| `Port 8501 is already in use` | `python run.py ui --port 8502` (Docker: change the left side of `8501:8501` in `compose.yaml`). |
| A case shows *Error - needs attention* | Open it in the dashboard and click *Retry processing from the last checkpoint*. |
| The W-2 is not read offline | Upload a straight, well-lit scan of the official layout, or use live mode. |

Edited by Taylor
