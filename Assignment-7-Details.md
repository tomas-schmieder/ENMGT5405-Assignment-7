# Assignment 7: Implement a multi agent tax system

**Due:** 10/31/2026
**Points:** 70 Points Possible
**Attempts:** Unlimited Attempts Allowed

---

## Details

*You may not be interested in taxes, but taxes are interested in you*

### Before we start:

An important attribute of a manager is the ability to convert uncertainty to certainty. In college, you operate in a world where most things are fairly predictable, but in general that is not how much of business operates. Sales are unpredictable, design specifications are unclear. As a manager, it is helpful to your staff if you can take in uncertainty, and pass on certainty. You are just not going to get everything handed to you nicely. In my courses I try to give you some exposure to this, and this exercise is such an example. Yes, I appreciate that can be annoying, but it is how much of business functions.

During class on Tuesday October 20 we will have an open Q&A session where you can discuss any aspects of this project. I role play the client and answer all questions. This will be your ONLY chance to ask questions about this project. (And this means that you need to have arranged into teams by then. Please do so here: [https://docs.google.com/spreadsheets/d/1CEm8dzx7DpiSzE9mVLGNmN5-HrUOehdgC2DmI3Swgyw/edit?usp=sharing](https://docs.google.com/spreadsheets/d/1CEm8dzx7DpiSzE9mVLGNmN5-HrUOehdgC2DmI3Swgyw/edit?usp=sharing))

Finally, a project like this is something that will look great on your resume if you execute it well. That is part of the reason for choosing it as a project.

**This is a TEAM project - 6 person teams**

This assignment is for 70 points. There are an additional 30 points in "stretch" goals (ie: a lot). In other words you can score over 100% and recover points lost elsewhere in the course.

---

## Kushim 'SilverFile'

**The main idea:** Create a multi agent system to assist with preparation of form [1040-SR](https://www.irs.gov/pub/irs-pdf/f1040s.pdf). Note that it is possible to score more than 100% for this assignment - in effect recovering points lost elsewhere. These opportunities are noted as "stretch".

This is a team assignment, six person teams. You may not be on the team with a person you have been on a team with before - form new teams. You should expect to spend 18-22 hours per person on this project.

You will learn basic MAS (multi agent system) techniques, like control transfer, orchestration, HITL, design and how to incorporate ethical considerations.

## 1. Introduction

Kushim, a financial services company, would like to explore a new business avenue, assisting with tax form preparation. Intuit, the makers of Turbo Tax, have been moving into automated financial advice and access to 'human experts'. The board believe this is a threat to financial services companies like Kushim. As a proof of concept, a feasibility team have identified the form 1040-SR as a good candidate. This is something that a lot of clients already have to fill in, and many dislike filing taxes, so it could be a valuable service to provide. In addition, it will prevent core customers being exposed to other services offered via tax filing software.

Your job is to implement a system to collect the information and assist with the filing of this form. The board are very interested in your overall experience, and they expect this project will give them insight into how easy creating solutions like this will be in future.

They have chosen the name "SilverFile" ... because silver haired clientele, and the association with money.

You may implement this in either LangGraph (recommended) or a mix of LangGraph and n8n.

### 1.1 Roles

In addition to working on the project as a whole, each person in the team needs to take on a specialization, chosen from the list below. The aspects of the project which people select will be graded as 'individual work' - so it is possible for members of the same team to receive different grades. You won't be separately graded on the aspects which are unassigned, so can ignore them (at least to some extent, you can't ignore some aspects completely, because your project won't work if you do)

- Agent memory
- Inter agent communication
- Task division and management
- MLOps/DevOps
- Guardrails and ethics
- Security

This means that not all of the above will be addressed in your project. That is fine. When you submit your project, you need to include a table showing who is doing what. He is an example table with some [made up names](https://en.wikipedia.org/wiki/Alice_and_Bob):

| Focus area | Team member assigned |
|---|---|
| Agent memory | Alice |
| Inter agent communication | Unassigned |
| Task division and management | Unassigned |
| MLOps/DevOps | Bob |
| Guardrails and ethics | Charlie |
| Security | Unassigned |

You should immediately notice that while you can completely skip some aspects, others (such as devops or inter-agent communication) can't be completely skipped, even if no person focuses on them, because they are needed to complete the project.

When choosing, start thinking about what you want to focus on for your final project. The goal here is to give you more time to develop an AI specialty, if that is something you want to do (being a generalist is fine too, especially if you want to go into something like product management).

## 2. Briefing

Kushim want a system, SilverFile, that does the intake and preparation work and delivers a draft return plus a reviewable record of where every number came from.

Form 1040-SR, U.S. Income Tax Return for Seniors, carries the same line numbering and computations as Form 1040 but is laid out in larger type over four pages, and — usefully for you — prints the Standard Deduction Chart on the form itself.

SilverFile is a preparation aid, not a preparer, and not an advisor - they already have advising services. Your system must:

- **Never file anything.** The output is a draft plus an audit record for a human.
- **Never give tax advice.** "Should I convert my IRA to a Roth?" / "Would I pay less if we filed separately?" / "Can I deduct my medications?" are all out of scope. The system explains its scope and offers to note the question for the volunteer preparer. Optimisation and planning are advice; transcription and arithmetic are not.
- **Never assert a dollar amount it cannot source.** See §4.3.
- **Always route to a human** in the escalation conditions of §4.5.
- **Handle only the in-scope return profile of §3.3.** Anything else escalates.
- Breaching these is not a bug you lose a couple of marks for. It is the assignment.

### 2.1 Deliverables

You are delivering a system which fills in a tax form, and a report about this system.

The deliverables of the system are a filled out form, and a "superuser" dashboard used by Kushim employees.

Submission is via a GitHub repository.

## 3. Specification

You are not expected to become a tax expert, and you will not be graded on tax knowledge beyond what is written here.

### 3.1 Information your system must populate

Your system must produce a completed draft tax form covering the following subset of Form 1040-SR (2025):

| Line | Content | Source |
|---|---|---|
| — | Filing status | Intake dialogue |
| — | Dependents (name, SSN, relationship) | Intake dialogue |
| 1z | Total wages | W-2 |
| 2a / 2b | Tax-exempt / taxable interest | 1099-INT |
| 3a / 3b | Qualified / ordinary dividends | 1099-DIV |
| 4a / 4b | IRA distributions, total and taxable | 1099-R (code 7 / QCD flag) |
| 5a / 5b | Pensions and annuities, total and taxable | 1099-R |
| 6a / 6b | Social Security benefits, total and taxable | SSA-1099 + worksheet |
| 9 | Total income | Computed |
| 10 | Adjustments to income (Schedule 1, line 26) | Intake — limited set |
| 11a | Adjusted gross income | Computed |
| 12d | Age / blindness boxes (self and spouse) | Intake |
| 12e | Standard deduction | Standard Deduction Chart |
| 13b | Additional deductions from Schedule 1-A | Computed (see 3.2) |
| 14 | Total deductions | Computed |
| 15 | Taxable income | Computed |
| 16 | Tax | Rate schedule |
| 24 | Total tax | Computed |
| 25a–25d | Federal income tax withheld | W-2 / 1099 forms |
| 26 | Estimated tax payments | Intake |
| 33 | Total payments | Computed |
| 34 / 37 | Overpayment / amount owed | Computed |

Other values not listed above are just entered directly. it is also fine to ask the user about things like 1b etc. (But see section 4, document extraction agent for W2 information).

### 3.2 Rules your system must get right

Four rules carry most of the reasoning weight, and are easy to get a wrong answer.

1. **1040-SR eligibility.** For tax year 2025 the taxpayer must have been born before 2 January 1961. On a joint return, only one spouse needs to meet this. There is no income restriction.
2. **Standard deduction.** Count the boxes checked on line 12d — one each for taxpayer 65+, taxpayer blind, spouse 65+, spouse blind — then read the Standard Deduction Chart. The 2025 base amounts are $15,750 (Single, MFS), $31,500 (MFJ, QSS) and $23,625 (HOH); each checked box adds $2,000 if unmarried and not a surviving spouse, otherwise $1,600. The chart does not apply if the taxpayer can be claimed as a dependent, if a separately-filing spouse itemises, or if the taxpayer was a dual-status alien — all three are escalation conditions.
3. **Enhanced senior deduction (new for 2025).** An additional $6,000 per qualifying person aged 65+ ($12,000 if both spouses on a joint return qualify), claimed on Schedule 1-A and carried to line 13b. It phases out above $75,000 MAGI ($150,000 joint) at 6% of the excess, applied per qualifying individual. It is in addition to the additional standard deduction in (b) — a very common conflation. Applies to tax years 2025–2028.
4. **Taxable Social Security.** Only a portion of benefits is taxable, determined by a worksheet over provisional income (AGI excluding benefits, plus tax-exempt interest, plus half of benefits) against base amounts of $25,000 / $32,000 and second-tier amounts of $34,000 / $44,000. Implemented for you, and it has an ordering dependency — it needs the rest of income before it can run, and line 6b feeds AGI. Getting that dependency right in your graph is part of the exercise.

In addition to this, because we are creating a fake application at Cornell, not a real in-use system:

Your system must check any social security number on entry by the user. The US government has set aside the 900 Series for testing. Any SSN starting with a number from 900 through 999 (e.g., 901-XX-XXXX) is acceptable. Your form may ONLY accept these fake social security numbers. (In other words you block a person from accidentally entering their actual social security number).

### 3.3 Scope

**In scope:** Amounts from W-2, SSA-1099, 1099-R, 1099-INT, 1099-DIV; all five filing statuses; standard deduction only; Schedule 1-A senior deduction; Schedules 1, 2 and 3 - user just directly inputs values.

**Out of scope — your system must escalate to a human, not attempt:**
(This is a great chance for Kushim to have a client call with an upsell)

- Itemized deductions (Schedule A);
- self-employment or business income (Schedule C), including 1099-NEC nonemployee compensation; rental income (Schedule E);
- capital gains requiring Schedule D; digital assets; foreign income or accounts; amended or prior-year returns; state returns; any 1099-R with "taxable amount not determined" checked;
- Note on that last 1099-R case: where box 2b is checked, deriving the taxable portion needs the Simplified Method or the General Rule. Neither is in scope and neither is in `tax_math`, so these escalate regardless of what other information is available.

**Central requirement:**

Every monetary value that reaches the draft return must carry a provenance record where a person can see how the amount was calculated - see section 4.2.

## 4. What you are building

Implement at least six distinct agents plus orchestration. You may add more; you may not merge these into fewer - this is a business rule. [What we mean by that is the yes, I am sure you can use fewer agents from a technology or efficiency point of view, but there are business reasons for keeping it like this. Business needs should drive technology decisions, not the other way around].

| Agent | Responsibility | Notable Constraint |
|---|---|---|
| Orchestrator | Decides which agent acts next; owns termination. May be involved with dashboard | May not itself extract, compute, or converse with the user |
| Intake | The only agent that talks to the taxpayer. Elicits filing status, age, blindness, dependents, document inventory, estimated payments | Must not perform arithmetic or interpret tax rules |
| Document Extraction | Turns supplied tax documents into typed, structured records. This will be tested on the submission of a W2 form only | Must not decide what a value means for the return |
| Eligibility & Rules | 1040-SR eligibility, filing status validation, box counts, which schedules apply, in-scope/out-of-scope determination | Grounded in the supplied reference corpus; must cite |
| Computation | Populates every derived line | Must not do arithmetic itself — every number comes from a deterministic MCP tool call |
| Review / Audit | Adversarially checks the assembled return before any human sees it | Must be able to send work back; must not fix things itself. The point here is that it loops around again to the other agents |

Do not underestimate the review agent. It should independently attempt to falsify the return: check each line against its provenance record, recompute totals, look for internal contradictions (e.g. line 6b > line 6a), and check that nothing out-of-scope slipped through.

Finally, it is not a coincidence that there are six people in a team and there are six agents, but these are not all the same amount of work.

### 4.1 Orchestration

Choose a topology and justify it. At minimum your graph must demonstrate:

- **Conditional routing** — the orchestrator's next hop depends on state, not on a fixed sequence (you're not in n8n land anymore).
- **At least one genuine parallel branch with an aggregation step**, and a state reducer that handles concurrent writes correctly. (Extraction across multiple documents is the obvious candidate; there are others.)
- **At least one cycle** — a review→revise loop — with an explicit, tested bound on iterations.
- **You must also implement a loop guard:** your report must describe how your system detects and breaks a pathological handoff cycle, and your test suite must contain a case that triggers it.

Include a diagram of your orchestration in the repo readme.

### 4.2 Provenance

Your final product should sample filled out tax form. It should be possible to see where each number came from (either with on-mouseover, or clicking on the number - whatever you like, so long as it is possible to see the calculation and sources.

As a last resort, if you don't calculate a dollar value, when the user inputs the value you can record it as "direct user input" with a date and who entered it.

### 4.3 Accessibility and dignity in the intake dialog

Your Intake agent is talking to someone who may be tired, hard of hearing, using a screen reader (partially sighted), anxious about money, or embarrassed not to understand taxes or any one of a number of things. Your report must document deliberate design choices in at least four of these areas, and your demo must show them working:

- **One question at a time.** Never a compound question with multiple clauses.
- **Plain language.** Try to think about clear communications. eg: "Modified adjusted gross income" gets a gloss the first time it appears; ideally it never appears.
- **Tolerance of repetition and drift.** The user may re-answer, contradict themselves, wander, or ask you to go back. Losing their previous answers is a failure.
- **No unnecessary PII** (Personally identifiable information). Do not ask for an SSN you do not need. If one is volunteered where it was not requested, handle it deliberately — your report should say how and why you made the choices you did.
- **Resumability.** A session abandoned on Tuesday and resumed on Friday must continue where it left off, with a summary of what was already covered.
- **Honest uncertainty.** "I'm not sure — let me flag this for a volunteer" is a correct answer from your system, and should be reachable from the agent.

### 4.4 Escalation to a human

Implement human-in-the-loop escalation, using a LangGraph interrupt, for at least these conditions:

1. Any out-of-scope item from §3.3.
2. Any unresolved conflict between a user statement and a document.
3. Any 1099-R with box 2b "taxable amount not determined" checked.
4. A request for tax advice, planning, or optimisation.
5. Filing-status ambiguity — most importantly a spouse who died during the tax year (MFJ vs QSS vs Single).
6. Any indication of financial exploitation or third-party pressure — for example, a refund routed to an account the taxpayer cannot describe, or a third party answering on the taxpayer's behalf without a stated authority.

Condition 6 is not decoration. Elder financial abuse frequently travels through tax refunds, and a system deployed to this population that has no notion of whether or not is is fit for purpose. You are not asked to adjudicate — you are asked to notice and stop.

### 4.5 Context-window strategy

The batch scenario (§4.2) processes 10 invoices sequentially in one thread. Without intervention, the model-calling agents' context grows with every invoice. Implement one of: message trimming, rolling summarization, or selective recall (only the current invoice + a summary of session decisions so far). Then measure: run batch with the strategy disabled and enabled (a `--no-context-strategy` flag), and record per-invoice input-token counts for both runs in a table in `docs/metrics.md`. The strategy must produce a materially flatter curve; the numbers are the grade, not the prose.

## 5. Deliverables

### 5.1 Repository layout (does not need to be exact)

```
your-repo/
├── README.md
├── requirements.txt
├── .env.example
├── run.py
├── src/
│   ├── state.py
│   ├── graph.py
│   ├── memory.py
│   └── agents/ (call them whatever you like)
├── data/
│   ├── generate_fixtures.py
│   ├── policy.md
│   └── fixtures/
├── evals/cases.json
├── tests/ (test_merge_order.py, test_decision_table.py)
├── traces/
├── docs/   (graph.png, metrics.md, IMPLEMENTATION_NOTES.md, AI_DISCLOSURE.md)
└── demo/   (eval_case_1.md, eval_case_2.md, w2_image_1.jpg, w2_image_1.jpg, demo_video.mp4)
```

### 5.2 Eval cases (given — your fixtures must realize these properties)

In `/demo` provide two sets of data which you know will result in a working run. The first should be a clean minimal run, everything works. The second should trigger a HITL event which is successfully resolved (so include instructions on how to resolve it).

### 5.3 AI-use disclosure

Write one paragraph on how you used AI in this assignment in detail. A simple "we used AI" is not sufficient. Missing disclosure caps the assignment at 60/70.

## 6. Grading rubric (70 pts)

**Notes:**

Graders will use Github commits to assess who did what.

Your readme must include detailed instructions as to how to run this code. If you want to submit a docker container where everything just works, that is fine too.

**A. Memory and state — 15 pts**

**B. Orchestration — 15 pts**

**C. Engineering quality & reproducibility — 15 pts**

**D. Evaluation — 20 pts**

1. Grader will attempt to fill in information for a "clean run" from your eval_case_1 data
   1. Everything works as expected.
   2. A filled in 1040-SR form is created
2. Dashboard exists
3. W2 amounts can be read from image of W2 form
4. Grader will use your eval_case_2 information to trigger a HITL event, and resolve it
   1. A filled in 1040-SR form is created
5. Grader will attempt to fill in information for a "clean run" fusing data they make up
   1. Everything works as expected.
   2. A filled in 1040-SR form is created
6. Evaluation of stretch goals

**E. Demo — 5 pts**

1. Provide a demo video of the system between 5 and 10 minutes long.

### Bonus points

Bonus points are available for a well designed dashboard, container and report:

- **HITL links in dashboard: 15 points**
  - It should be possible for the Kushim employee to see a list of all the forms which are in progress, and which have been submitted. If an agent has triggered a human in the loop event, it should be possible to see this is needed, click on it and resolve it in the dashboard.
  - Dashboard is thoughtfully designed.
    - I don't mind how it looks, but it needs to look neat. Things should line up, fonts should be consistent and easy to read, etc.
- **Five page report: 10 points**
  - Detail how the system was designed, include a neat diagram and explain each agent in detail.
  - List some failure modes and what is out of scope.
  - Explain team roles in detail any who did what.
- **Submit a Docker container where everything just works, with instructions on how to use it: 5 points**
  - This is to make graders life easier

-- fin --
