# Eval case 2: human-in-the-loop event, resolved

**Goal:** a run that triggers a human-review interrupt (assignment §4.4 condition 2, *unresolved conflict between a
user statement and a document*), which a Kushim reviewer resolves in the dashboard, after which the same case
resumes and produces a filled draft (rubric D.4). All data is fictional.

| Item | Value |
|---|---|
| Taxpayers | Harold Benson (born November 2, 1958) and Margaret Benson (born April 20, 1962), married filing jointly |
| SSNs (test numbers) | Harold 900-71-4402, Margaret 900-71-4403 |
| Documents | `demo/w2_image_2.png` - W-2 from Fingerlakes Hardware Co.: box 1 **$45,200.00**, box 2 $3,100.00. `demo/ssa1099_case_2.png` - SSA-1099: box 5 $21,600.00 |
| The conflict | Harold says he earned **about $54,000**; the W-2 shows $45,200.00 (a difference of $8,800, above the tolerance) |

Only Harold meets the 1040-SR age rule. On a joint return that is enough (assignment §3.2(1)).

## Part A - taxpayer (Taxpayer intake view)

1. Click **Start** and note the case number.
2. Answer:

| Question (short) | Answer |
|---|---|
| First name / last name | `Harold` / `Benson` |
| Answering yourself or with help? | **I'm answering for myself** |
| New 2025 federal return? | **Yes** |
| Date of birth | `November 2, 1958` |
| Filing status | **Married filing jointly** |
| Did your spouse pass away during 2025? | **No** |
| Your SSN | `900-71-4402` |
| Legally blind? / Can someone claim you? | **No** / **No** |
| U.S. citizen or resident all year? | **Yes** |
| Spouse's first name / last name | `Margaret` / `Benson` |
| Spouse's date of birth | `April 20, 1962` |
| Spouse's SSN | `900-71-4403` |
| Spouse legally blind? / Can someone claim your spouse? | **No** / **No** |
| Claiming dependents? | **No** |
| How many W-2 forms? | `1` |
| Roughly how much in wages? | `about 54,000` |
| 1099-INT / 1099-DIV / 1099-R counts | `0` each |
| SSA-1099 count | `1` |
| Other income? / Itemize? | **No** / **No** |
| Estimated tax payments? | **Yes**, total `400` |
| Schedule 1, 2 or 3 amounts? | **No** |
| Refund method | **Direct deposit to a bank account**, account in own name: **Yes** |

3. At the upload step add `demo/w2_image_2.png` as **W-2** and `demo/ssa1099_case_2.png` as **SSA-1099**, then click **Send these forms**. (If a form type is picked wrongly, SilverFile recognises the form and corrects it.)
4. Confirm the summary with **Yes**.
5. SilverFile reads both documents and the Rules agent compares the stated wages with the W-2 using the MCP `compare_amounts` tool. It asks: *"Your W-2 form shows wages of $45,200.00, but earlier you said about $54,000.00. Which is right?"* Click **My number is right**.
6. The conflict is still unresolved, so the graph pauses with a LangGraph `interrupt`. The taxpayer sees *"A Kushim volunteer is looking at your case."* The answers are saved; you can close the browser.

## Part B - reviewer (Employee dashboard view)

7. Switch to **Employee dashboard** and type a reviewer name in the sidebar (for example `J. Rivera`).
8. The case appears under **Needs human review** and in the **Review queue**, reason *Taxpayer statement conflicts with a document*. Click **Open**.
9. In the **Human review** tab, read the evidence: the MCP comparison trace and the taxpayer's answer. Choose **Confirm the document value is correct (evidence required)** and fill in:
   - Rationale: `Spoke with the taxpayer; the W-2 amount is correct.`
   - Evidence: `Phone call with Harold Benson: he confirmed W-2 box 1 shows $45,200.00. His estimate of $54,000 included his Social Security.`
10. Click **Record decision and resume the case**. The decision is recorded (who, when, rationale, evidence, change) and the same graph thread resumes. Rules, computation, audit and assembly run, and the case becomes **Draft ready**.
11. Back in **Taxpayer intake** (enter the case number under *Continue a saved return* if needed), the draft is ready. Click **Send it to Kushim for review**.

Actions the dashboard does **not** allow here include "note and continue". Every escalation reason has its own short list of permitted actions (`src/hitl.py`), and there is no generic override.

## Expected results (hand-worked, `evals/expected_results/eval_case_2.json`)

| Line | Amount | How |
|---|---:|---|
| 1z | $45,200 | W-2 box 1 (confirmed by the reviewer) |
| 6a | $21,600 | SSA-1099 box 5 |
| 6b | $16,200 | Social Security Benefits Worksheet, MFJ ($32,000 / $44,000 amounts) |
| 9 / 11b | $61,400 | 45,200 + 16,200 |
| 12d | 1 box | Harold only (Margaret born 1962) |
| 12e | $33,100 | MFJ $31,500 + $1,600 |
| 13b | $6,000 | enhanced senior deduction for Harold only |
| 15 | $22,300 | 61,400 - 39,100 |
| 16 / 24 | $2,233 | Tax Table, MFJ, row 22,300-22,350 |
| 25a | $3,100 | W-2 box 2 |
| 26 | $400 | estimated payments (direct input) |
| 33 | $3,500 | 3,100 + 400 |
| 34 | $1,267 | overpayment |

## Command-line alternative

```bash
python run.py demo eval_case_2            # stops at the human-review event
python run.py demo eval_case_2 --review   # also plays the reviewer decision above
```
