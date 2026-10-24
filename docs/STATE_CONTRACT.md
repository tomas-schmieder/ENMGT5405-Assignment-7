# State contract (`src/state.py`, schema version 1)

All values are JSON-serialisable so the SQLite checkpointer can persist them. Money is stored as strings: cents
for source values (`"46850.00"`), whole dollars for form lines (`"46850"`). Binary floats are never used for money.

| Field | Type | Owner (writer) | Reducer | Meaning / invalidation |
|---|---|---|---|---|
| `case_id`, `tax_year`, `schema_version`, `created_at` | str/int | service at creation | replace | identity; thread id = case id |
| `status` | str | orchestrator; human_review (`referred_out_of_scope`) | replace | dashboard status (see `STATUS_LABELS`) |
| `facts` | `{fact_id: Fact}` | intake (taxpayer answers), human_review (reviewer corrections) | key merge | `Fact = {value, status: confirmed, history[], source{kind, entered_by, at, question_id, question_text, raw_answer}}`. A fact that was never answered is absent: unknown is distinct from zero. |
| `facts_version` | int | intake, human_review | replace | +1 on every fact change; anything computed from an older version is stale |
| `intake` | dict | intake; rules/aggregator/human_review append `followups` | replace | asked question ids, `cursor_override` (go back), `followups[]`, `notes_for_volunteer[]`, dependent draft, `complete`, `submitted`, `hint`, `rejected_ssn_attempts` |
| `documents` | `{doc_id: Document}` | intake (new uploads), extraction (status, corrected type), review (re-queue), human_review | `merge_documents` | status moves forward only unless `revision` increases |
| `extractions` | `{doc_id: Extraction}` | extract_document (parallel), human_review (reviewer-corrected revision) | `merge_extractions` | by id; identical delivery is a no-op; higher revision wins; same revision with different content keeps both candidates and sets `conflict` (order-independent) |
| `source_facts` | `{doc:<id>:<box>: {...}}` | aggregate_extractions only | replace (full rebuild) | usable document values; rejected or duplicate documents are excluded |
| `extraction_summary` | dict | aggregator; human_review sets `stale` | replace | `stale` makes the orchestrator re-aggregate |
| `eligibility` | dict | rules | replace | `status` (screening / need_input / escalate / ok), `mode`, cited `decisions[]`, `boxes`, `conflict`, `facts_version`, `source_version` |
| `lines` | `{line: {value, calc_id, facts_version, status}}` | computation | key merge | stale when `facts_version` or source version changes |
| `provenance` | `{key: record}` | intake (direct input), aggregator (documents), computation (derived), human_review (corrections) | key merge | see IMPLEMENTATION_NOTES section 6 |
| `calc` | dict | computation | replace | `calc_id`, versions, MCP call ids, Schedule 1-A values, box count, tax method, run count |
| `review` | dict | review; human_review resets `passes` on retry | replace | `status`, `for_calc`, `passes`, `open_issues[]` (id, check, target, detail), `advisory[]`, `history[]` |
| `assembly` | dict | assembly | replace | `status` (ready / gaps / error), `version`, `calc`, PDF path, previews, checks, cover note |
| `escalation` | dict or null | any agent (request); human_review clears | replace | the single pending escalation request |
| `human_events` | list | human_review | `append_unique` by id | resolved events with the full audit record |
| `transcript` | list | intake, human_review | append | full conversation (SSNs removed or masked); never trimmed |
| `routing` | dict | orchestrator; human_review on retry | replace | `next`, `history[]` (last 60 hops), `handoffs_this_run`, `signature_counts`, run marker |
| `metrics` | list | all agents | append | model calls (agent, model, tokens incl. cache fields, latency, ok/error) and MCP tool calls (call id, latency) |
| `trace` | list | all agents | append | one line per agent action: agent, outcome, summary |
| `error` | dict or null | reserved | replace | processing errors are also stored in the case table by the service |

## Agent contract

Every agent node returns an `AgentResult` (`src/contracts.py`): `agent`, `outcome` (`success`, `need_more_input`,
`revision_request`, `escalation`, `error`), `summary`, `patch`, optional `escalation` and `revision_targets`. It
is converted to a state update with a trace entry. An agent writes only the fields it owns, as listed above.

## Statuses

`intake`, `awaiting_documents`, `processing`, `revising`, `needs_human_review`, `draft_ready`,
`submitted_for_internal_review`, `referred_out_of_scope`, `error` (service-level). Terminal: submitted, referred,
closed.
