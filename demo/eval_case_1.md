# Eval case 1: clean minimal run

**Goal:** a complete, problem-free run that ends with a filled draft Form 1040-SR (assignment §5.2, rubric D.1).
All data is fictional.

| Item | Value |
|---|---|
| Taxpayer | Eleanor Whitfield, born March 14, 1957, single, not blind |
| SSN (test number) | 900-55-1234 |
| Document | `demo/w2_image_1.png` - W-2 from Maple Grove Public Library: box 1 $46,850.00, box 2 $3,980.00 |
| Expected outcome | Draft ready, then "Submitted internally for human review" (nothing is filed) |

## Run it in the app

1. Start the app (`python run.py ui`, or `docker compose up --build`) and open http://localhost:8501.
2. In **Taxpayer intake**, click **Start**. Write down the case number shown at the top.
3. Answer each question as below. Type the answer and press Enter, or click the option button. Only one question appears at a time; the exact order can differ slightly from this table, so match by question.

| Question (short) | Answer |
|---|---|
| First name | `Eleanor` |
| Last name | `Whitfield` |
| Answering yourself or with help? | **I'm answering for myself** |
| New 2025 federal return? | **Yes** |
| Date of birth | `March 14, 1957` |
| Filing status | **Single** |
| Did your spouse pass away during 2025? | **No** |
| Social Security number | `900-55-1234` |
| Legally blind? | **No** |
| Can someone claim you as a dependent? | **No** |
| U.S. citizen or resident all year? | **Yes** |
| Claiming dependents? | **No** |
| How many W-2 forms? | `1` |
| Roughly how much in wages? | `about 46,000` |
| 1099-INT / 1099-DIV / 1099-R / SSA-1099 counts | `0` each |
| Other income (business, rental, sales, foreign)? | **No** |
| Planning to itemize? | **No** |
| Estimated tax payments? | **No** |
| Schedule 1, 2 or 3 amounts? | **No** |
| Refund method | **Paper check by mail** |

4. At **Please add a photo or scan...**: under *Add your forms*, choose `demo/w2_image_1.png`, keep the form type **W-2**, click **Add 'w2_image_1.png' as W-2**, then **Send these forms**.
5. Review the summary and answer **Yes**.
6. SilverFile reads the W-2 image, checks the rules, computes every line with MCP tools, audits the result and fills the official PDF. At **Your draft Form 1040-SR is ready** you see the headline numbers. Open *See the full draft...* to download the PDF and inspect any line. Then click **Send it to Kushim for review**.
7. In **Employee dashboard** the case shows as *Submitted internally for human review*. Pick it from the table to see the draft, the provenance of each line, the conversation and the agent trace.

## Expected results (hand-worked, `evals/expected_results/eval_case_1.json`)

| Line | Amount | How |
|---|---:|---|
| 1z | $46,850 | W-2 box 1 |
| 9 / 11a / 11b | $46,850 | total income = AGI |
| 12d | 1 box | born before January 2, 1961 |
| 12e | $17,750 | Single $15,750 + $2,000 |
| 13b | $6,000 | enhanced senior deduction (MAGI below $75,000) |
| 14 | $23,750 | 12e + 13b |
| 15 | $23,100 | 46,850 - 23,750 |
| 16 / 24 | $2,537 | 2025 Tax Table, Single, row 23,100-23,150 |
| 25a / 25d / 33 | $3,980 | W-2 box 2 |
| 34 | $1,443 | overpayment |

The stated wages (about $46,000) are within tolerance of the W-2 ($46,850), so no conflict is raised.

## Command-line alternative

```bash
python run.py demo eval_case_1      # same answers and image through the same service calls
```
