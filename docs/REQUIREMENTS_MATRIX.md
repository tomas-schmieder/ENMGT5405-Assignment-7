# Requirements matrix

Status key: **Done** = implemented and checked by the evidence listed; **Done (unmeasured)** = implemented, but
the measurement needs a live API run; **Team** = needs action by the team. Owners follow the plan's
Person 1-6 mapping (replace with names in [CONTRIBUTIONS](CONTRIBUTIONS.md)).

| Assignment | Requirement | Implementation | Owner | Evidence | Status |
|---|---|---|---|---|---|
| §1.1 | Specialisation table (who does what) | README "Team" table, docs/CONTRIBUTIONS.md | P6 | - | **Team**: fill in names |
| §2 | Never file; output is a draft + audit record | no filing code path; DRAFT stamp; "submitted internally for human review" | P3/P6 | `pdf_writer.py`, `STATUS_LABELS`, screenshots | Done |
| §2 | Never give advice; explain scope and note the question | intake advice detection (model + patterns), note for volunteer, `advice_request` interrupt | P2/P4 | `test_offline_intents`, `test_mandatory_stops[stop_advice]` | Done |
| §2 | Never assert an unsourced amount | provenance on every line; assembly lineage gate | P3 | `test_draft_cases_match_hand_worked_results` (resolve every line) | Done |
| §2 | Always route to a human in §4.4 conditions | `human_review` interrupt | P2/P4 | §4.4 rows below | Done |
| §2.1 | Filled form + superuser dashboard; GitHub submission | official PDF; Streamlit dashboard | P3/P6 | browser smoke runs, `docs/ACCEPTANCE_RESULTS.md` | Done |
| §3.1 | Filing status, dependents (name, SSN, relationship) | intake questions; PDF fields | P2/P3 | `case_hoh_dependent`, `case_qss` | Done |
| §3.1 | 1z wages (W-2) | extraction + MCP `aggregate_amounts` | P3/P5 | eval cases 1, 2, unseen, two-W-2 case | Done |
| §3.1 | 2a/2b interest | 1099-INT box 1+3 -> 2b, box 8 (+DIV box 12) -> 2a | P5 | `case_single_retiree_mixed` | Done |
| §3.1 | 3a/3b dividends (3a a subset of 3b) | 1099-DIV 1b/1a; audit check 3a <= 3b | P5/P6 | `case_single_retiree_mixed`, `test_verify_return_detects_contradictions` | Done |
| §3.1 | 4a/4b IRA (code 7 / QCD) | `ira_distributions` tool; QCD age rule; 4c(2) checkbox | P4/P5 | `test_ira_with_qcd`, `test_qcd_requires_age_70_and_a_half` | Done |
| §3.1 | 5a/5b pensions | 1099-R without IRA box | P5 | `case_mfs_lived_apart`, `case_qss` | Done |
| §3.1 | 6a/6b Social Security + worksheet | `taxable_social_security` | P5 | grid vs independent oracle; eval case 2 | Done |
| §3.1 | 9, 10, 11a | MCP tools; line 10 from Schedule 1 line 26 | P5 | all draft cases | Done |
| §3.1 | 12d boxes, 12e standard deduction | `compute_boxes`, `standard_deduction` | P4/P5 | `test_line_12d_boxes`, chart tests | Done |
| §3.1 | 13b Schedule 1-A | `enhanced_senior_deduction`; Schedule 1-A pages filled | P5/P3 | phaseout boundary tests; MFJ high-income case | Done |
| §3.1 | 14, 15, 16, 24 | MCP tools (Tax Table, TCW, QDCG worksheet) | P5 | every printed Tax Table row; TCW oracle | Done |
| §3.1 | 25a-25d withholding | W-2 box 2; 1099 box 4 + SSA-1099 box 6; 25c $0 | P5 | retiree case (25b 4,200) | Done |
| §3.1 | 26, 33, 34/37 | direct input; payments; refund/owed tools | P5 | eval case 2 (26 = 400) | Done |
| §3.1 | Other values entered directly | Schedules 1/2/3 totals, line 19 | P2 | intake script | Done |
| §3.2(1) | 1040-SR eligibility; joint exception; no income limit | `R-ELIG-01` | P4 | decision table rows (1961-01-01 / 1961-01-02 / joint) | Done |
| §3.2(2) | Standard deduction chart and its three exceptions | `R-SD-01..03` | P4/P5 | chart tests; exception rows | Done |
| §3.2(3) | Enhanced senior deduction, separate from 12d addition, per-person phaseout | `R-ESD-01..03` | P5 | `test_enhanced_senior_deduction`, separation test | Done |
| §3.2(4) | Taxable SS and its ordering dependency | dependency order in computation; `R-SS-02` | P1/P5 | integration drafts; graph order | Done |
| §3.2 | Fictional SSNs only (900-999) | `src/ssn.py`, intake, document check | P3 | `test_fictional_ssn`, `stop_real_ssn_w2` | Done |
| §3.3 | Each exclusion escalates (Schedule A, C/1099-NEC, E, D, digital assets, foreign, amended/prior, state, box 2b) | `R-SCOPE-01`, `R-1099R-01`, intake patterns | P4 | decision table; stop cases; `test_negated_mentions_are_not_scope_signals` | Done |
| §3.3 | Provenance for every monetary value | §4.2 | P3 | as §4.2 | Done |
| §4 | Six distinct agents + orchestration; no merging | seven roles (ASSUMPTIONS A-01) with their own prompts, contracts, nodes, traces | P1 | `test_graph_nodes_and_edges` | Done |
| §4 | Orchestrator never extracts, computes or converses | `orchestrator.py` | P1 | code review; trace | Done |
| §4 | Intake only agent talking to taxpayer; no arithmetic/rules | follow-ups relayed verbatim | P2 | code; rules writes follow-ups | Done |
| §4 | Extraction tested on W-2; does not interpret | vision/OCR transcription; aggregator validation | P3 | `test_w2_image_*`, live test (key needed) | Done |
| §4 | Rules grounded and cited | registry with page citations | P4 | `test_every_rule_cites_a_source` | Done |
| §4 | Computation: every number from MCP | `computation.py` | P5 | `transport == mcp-stdio` assertion | Done |
| §4 | Review falsifies, sends back, never fixes | `review_audit.py` | P6 | review-cycle tests | Done |
| §4.1 | Conditional routing on state | `decide()` | P1 | trace and routing history | Done |
| §4.1 | Parallel branch + aggregation + reducer | `Send` fan-out, `merge_extractions` | P1/P3 | `test_parallel_extraction_and_aggregation`, `test_merge_order.py` | Done |
| §4.1 | Review/revise cycle with tested bound | `MAX_REVIEW_PASSES = 3` | P1/P6 | `test_review_bound_escalates`, `test_review_revise_cycle_is_bounded_and_recovers` | Done |
| §4.1 | Loop guard + test that triggers it | hand-off cap + signature repeats | P1 | `test_loop_guard_breaks_pathological_handoff_cycle`, `test_loop_guard_handoff_cap` | Done |
| §4.1 | Diagram in README | `docs/graph.png` | P1 | README | Done |
| §4.2 | See where each number came from (click) | dashboard line inspector; PDF previews; audit JSON | P3/P6 | browser screenshots | Done |
| §4.2 | Direct user input with date and who | `direct_input_record` | P2/P3 | `test_eval_case_1_w2_source_chain` | Done |
| §4.3 | At least 4 accessibility areas, demonstrated | all 6 (IMPLEMENTATION_NOTES section 7) | P2 | intake tests; keyboard and zoom runs | Done |
| §4.4(1)-(6) | Six interrupts | `human_review` node | P2/P4 | `test_mandatory_stops` (10 cases), `test_eval_case_2_hitl_round_trip` | Done |
| §4.4 | Successful permitted resume | dashboard decision -> same thread resumes | P2/P6 | eval case 2 (CLI, tests, browser) | Done |
| §4.5 | Context strategy + `--no-context-strategy` + per-item token table | selective recall; benchmark script | P1 | `docs/metrics.md` | **Done (unmeasured)**: needs a live run with an API key |
| §5.1 | Repository layout | as README "Repository layout" | P6 | - | Done |
| §5.2 | Two demo datasets + HITL resolution instructions | `demo/eval_case_1.md`, `demo/eval_case_2.md`, images | P3/P6 | eval tests | Done |
| §5.3 | Detailed AI-use disclosure | `docs/AI_DISCLOSURE.md` | all | - | **Team**: add each member's own AI use |
| §6 | README with detailed run instructions; Docker optional | README; Dockerfile; compose | P5/P6 | Docker build and run in ACCEPTANCE_RESULTS | Done |
| §6 D.5 | Grader-made clean run | same path as fixtures; `grader_style_unseen` | P3/P6 | eval | Done (live W-2 reading needs a key; offline OCR is tuned to the IRS layout) |
| §6 E | Demo video 5-10 min | - | P6 | - | Out of scope for this build (team request) |
| Bonus | HITL dashboard (list in-progress/submitted, click to resolve, neat) | `src/ui/dashboard.py` | P2/P6 | browser runs | Done |
| Bonus | Five-page report | - | all | - | Out of scope for this build (team request) |
| Bonus | Docker container | Dockerfile, compose.yaml, volume | P5 | ACCEPTANCE_RESULTS Docker section | Done |
| §6 | Git commits show who did what | contribution process in CONTRIBUTIONS.md | all | - | **Team** |
