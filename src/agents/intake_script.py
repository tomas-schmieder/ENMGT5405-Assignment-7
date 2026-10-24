"""The intake question plan: one plain-language question at a time.

Each :class:`Question` fills exactly one fact. ``applies`` decides whether a
question is relevant given the facts collected so far, so the conversation
adapts (e.g. spouse questions only for joint or separate returns). Wording
was written for an older audience: short sentences, no jargon, and a short
explanation ("gloss") for unavoidable terms.

Validation is deterministic. The Intake agent may use a model to understand
free-text replies, but the value stored for a fact always passes the
validator below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from src.money import MoneyParseError, parse_money, to_cents_str
from src.ssn import validate_fictional_ssn

Facts = dict[str, Any]

FILING_STATUS_OPTIONS = [
    ("single", "Single"),
    ("mfj", "Married filing jointly"),
    ("mfs", "Married filing separately"),
    ("hoh", "Head of household"),
    ("qss", "Qualifying surviving spouse"),
]


class Invalid(ValueError):
    """The reply does not answer the question; message is shown to the taxpayer."""


# ---------------------------------------------------------------------------
# validators: text -> normalised value (or raise Invalid with a kind hint)
# ---------------------------------------------------------------------------

_YES = {"yes", "y", "yeah", "yep", "correct", "true", "i did", "i was", "i am", "i do", "sure", "right", "that's right",
        "it is", "they are", "we did", "we were", "affirmative"}
_NO = {"no", "n", "nope", "none", "false", "i did not", "i didn't", "i was not", "i wasn't", "i am not",
       "i'm not", "i do not", "i don't", "not", "never", "nothing", "no i didn't", "we did not", "we didn't", "neither"}


def v_yes_no(text: str) -> bool:
    t = re.sub(r"[.!,]", "", (text or "").strip().lower())
    if t in _YES or t.startswith(("yes", "yeah", "yep")):
        return True
    if t in _NO or t.startswith(("no ", "no,", "nope", "none")) or t == "no":
        return False
    raise Invalid("Please answer yes or no.")


def v_name(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(r"^(my name is|it's|it is|i'm|i am)\s+", "", t, flags=re.I).strip(" .")
    if not t or len(t) > 40 or not re.fullmatch(r"[A-Za-z][A-Za-z .'\-]*", t):
        raise Invalid("Please type the name using letters only.")
    return t[0].upper() + t[1:]


_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9


def v_date(text: str) -> str:
    t = (text or "").strip().lower().replace(",", " ")
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    parts = None
    if m:
        parts = (int(m[1]), int(m[2]), int(m[3]))
    m = m or re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", t)
    if m and parts is None:
        parts = (int(m[3]), int(m[1]), int(m[2]))
    if parts is None:
        m = re.fullmatch(r"([a-z]+)\.?\s+(\d{1,2})\s+(\d{4})", re.sub(r"\s+", " ", t))
        if m and m[1] in _MONTHS:
            parts = (int(m[3]), _MONTHS[m[1]], int(m[2]))
    if parts is None:
        m = re.fullmatch(r"(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})", re.sub(r"\s+", " ", t))
        if m and m[2] in _MONTHS:
            parts = (int(m[3]), _MONTHS[m[2]], int(m[1]))
    if parts is None:
        raise Invalid("Please give the full date, for example: March 5, 1955.")
    try:
        d = date(*parts)
    except ValueError as exc:
        raise Invalid("That date doesn't exist. Please check the month and day.") from exc
    if not date(1900, 1, 1) <= d <= date(2025, 12, 31):
        raise Invalid("Please check the year. It should be a date in the past.")
    return d.isoformat()


def v_ssn(text: str) -> str:
    check = validate_fictional_ssn(text)
    if not check.ok:
        raise Invalid(check.reason)
    return check.normalized  # type: ignore[return-value]


def v_money(text: str) -> str:
    t = (text or "").strip().lower()
    if t in {"none", "zero", "nothing", "no", "0"}:
        return "0.00"
    t = re.sub(r"^(about|around|roughly|approximately|approx\.?|maybe)\s+", "", t)
    t = t.replace("dollars", "").replace("usd", "").strip()
    m = re.fullmatch(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(k|thousand)?", t)
    if not m:
        raise Invalid("Please type the amount as a number, for example 1,250.00.")
    try:
        amount = parse_money(m[1])
    except MoneyParseError as exc:
        raise Invalid("Please type the amount as a number, for example 1,250.00.") from exc
    if m[2]:
        amount = amount * 1000
    return to_cents_str(amount)


def v_count(text: str) -> int:
    words = {"zero": 0, "none": 0, "no": 0, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4,
             "five": 5, "six": 6}
    t = (text or "").strip().lower().strip(".")
    if t in words:
        return words[t]
    m = re.match(r"^(\d{1,2})\b", t)
    if m:
        return int(m[1])
    first = t.split()[0] if t.split() else ""
    if first in words:
        return words[first]
    raise Invalid("Please type a number, like 1 or 2.")


def make_choice(options: list[tuple[str, str]], synonyms: dict[str, str] | None = None) -> Callable[[str], str]:
    syn = {k.lower(): v for k, v in (synonyms or {}).items()}

    def v_choice(text: str) -> str:
        t = re.sub(r"[.!]", "", (text or "").strip().lower())
        for value, label in options:
            if t in {value, label.lower()}:
                return value
        for key in sorted(syn, key=len, reverse=True):
            if key in t:
                return syn[key]
        if re.fullmatch(r"\d", t) and 1 <= int(t) <= len(options):
            return options[int(t) - 1][0]
        raise Invalid("Please choose one of: " + "; ".join(lbl for _, lbl in options) + ".")

    return v_choice


V_FILING_STATUS = make_choice(FILING_STATUS_OPTIONS, {
    "married filing jointly": "mfj", "jointly": "mfj", "joint": "mfj", "together": "mfj",
    "married filing separately": "mfs", "separately": "mfs", "separate": "mfs",
    "head of household": "hoh", "head of house": "hoh",
    "qualifying surviving spouse": "qss", "surviving spouse": "qss", "widow": "qss",
    "single": "single", "unmarried": "single",
})

V_ANSWERER = make_choice([("self", "I'm answering for myself"), ("helper", "Someone is helping me answer")], {
    "myself": "self", "me": "self", "just me": "self", "i am": "self", "i'm": "self", "self": "self",
    "helping": "helper", "my son": "helper", "my daughter": "helper", "someone": "helper",
    "for my": "helper", "on behalf": "helper", "helper": "helper",
})

V_REFUND = make_choice([("check", "Paper check by mail"), ("direct_deposit", "Direct deposit to a bank account")], {
    "check": "check", "mail": "check", "paper": "check", "deposit": "direct_deposit", "bank": "direct_deposit",
    "account": "direct_deposit", "direct": "direct_deposit",
})

V_SPOUSE_DEATH_YEAR = make_choice([("2023", "2023"), ("2024", "2024"), ("2025", "2025"), ("other", "Another year")], {
    "2023": "2023", "2024": "2024", "2025": "2025", "this year": "2025", "last year": "2024",
})


def v_upload_done(text: str) -> str:
    return (text or "").strip() or "done"


def v_short_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        raise Invalid("Please describe it in a few words.")
    return t[:200]


# ---------------------------------------------------------------------------
# question plan
# ---------------------------------------------------------------------------


@dataclass
class Question:
    id: str
    fact: str
    text: str
    kind: str
    validator: Callable[[str], Any]
    section: str
    gloss: str = ""
    options: list[tuple[str, str]] = field(default_factory=list)
    applies: Callable[[Facts], bool] = lambda f: True
    label: str = ""
    sensitive: bool = False

    def payload(self, facts: Facts) -> dict:
        return {"question_id": self.id, "fact": self.fact, "text": self.render(facts), "gloss": self.gloss,
                "kind": self.kind, "options": [{"value": v, "label": l} for v, l in self.options],
                "section": self.section, "sensitive": self.sensitive}

    def render(self, facts: Facts) -> str:
        return self.text


def _v(f: Facts, key: str, default: Any = None) -> Any:
    return f.get(key, default)


def _married_status(f: Facts) -> bool:
    return _v(f, "filing_status") in {"mfj", "mfs"}


def _has(f: Facts, key: str) -> bool:
    return bool(_v(f, key))


QUESTIONS: list[Question] = [
    Question("tp_first_name", "tp.first_name", "What is your first name?", "text", v_name, "About you",
             label="Your first name"),
    Question("tp_last_name", "tp.last_name", "What is your last name?", "text", v_name, "About you",
             label="Your last name"),
    Question("answerer", "answerer", "Are you answering these questions yourself, or is someone helping you?",
             "choice", V_ANSWERER, "About you",
             options=[("self", "I'm answering for myself"), ("helper", "Someone is helping me answer")],
             label="Who is answering"),
    Question("helper_authority", "helper.authority",
             "Thank you. Does the person helping you have legal authority to act for you, such as a power of attorney?",
             "yes_no", v_yes_no, "About you",
             gloss="A power of attorney is a legal paper that lets someone act for you.",
             applies=lambda f: _v(f, "answerer") == "helper", label="Helper has legal authority"),
    Question("return_type_ok", "return_type_ok",
             "Is this your federal return for the year 2025, and the first one you are filing for 2025?",
             "yes_no", v_yes_no, "About you",
             gloss="SilverFile prepares only a new 2025 federal return. It does not do state returns, "
                   "corrections to returns already filed, or earlier years.",
             label="New 2025 federal return"),
    Question("tp_dob", "tp.dob", "What is your date of birth? For example: March 5, 1955.", "date", v_date,
             "About you", label="Your date of birth"),
    Question("filing_status", "filing_status",
             "Which filing status will you use? If you're not sure, that's fine, just say so.",
             "choice", V_FILING_STATUS, "Filing status",
             gloss="Your filing status depends on whether you were married at the end of 2025 and who lives with you.",
             options=FILING_STATUS_OPTIONS, label="Filing status"),
    Question("spouse_died_2025", "spouse_died_2025",
             "Just to make sure we use the right status: did your husband or wife pass away during 2025?",
             "yes_no", v_yes_no, "Filing status",
             applies=lambda f: _v(f, "filing_status") in {"single", "mfj", "mfs", "hoh"},
             label="Spouse passed away in 2025"),
    Question("qss_death_year", "qss.spouse_death_year", "In what year did your spouse pass away?",
             "choice", V_SPOUSE_DEATH_YEAR, "Filing status",
             options=[("2023", "2023"), ("2024", "2024"), ("2025", "2025"), ("other", "Another year")],
             applies=lambda f: _v(f, "filing_status") == "qss", label="Year spouse passed away"),
    Question("qss_child", "qss.dependent_child",
             "Do you have a child or stepchild who lived with you and whom you can claim as a dependent?",
             "yes_no", v_yes_no, "Filing status",
             applies=lambda f: _v(f, "filing_status") == "qss", label="Dependent child lives with you"),
    Question("hoh_person", "hoh.qualifying_person",
             "Did you pay more than half the cost of keeping up a home for a relative who lived with you for more than half of 2025?",
             "yes_no", v_yes_no, "Filing status",
             gloss="This is what usually lets someone use head of household.",
             applies=lambda f: _v(f, "filing_status") == "hoh", label="Kept up a home for a qualifying relative"),
    Question("tp_ssn", "tp.ssn",
             "What is your Social Security number? For this classroom demo, please use a test number "
             "that starts with 9, like 900-12-3456.",
             "ssn", v_ssn, "About you", gloss="It goes on the top of the form. Real numbers are refused.",
             label="Your SSN", sensitive=True),
    Question("tp_blind", "tp.blind", "Were you legally blind at the end of 2025?", "yes_no", v_yes_no,
             "About you",
             gloss="Legally blind means you can't see better than 20/200 in your better eye with glasses, "
                   "or your field of vision is 20 degrees or less.", label="You are legally blind"),
    Question("tp_claimable", "tp.claimable_dependent",
             "Can someone else, such as a son or daughter, claim you as a dependent on their tax return?",
             "yes_no", v_yes_no, "About you",
             gloss="A dependent is a person someone else supports and lists on their own return.",
             label="Someone can claim you as a dependent"),
    Question("us_resident", "us_resident_all_year",
             "Were you a U.S. citizen or U.S. resident for all of 2025?", "yes_no", v_yes_no, "About you",
             label="U.S. citizen or resident all year"),
    # spouse
    Question("sp_first_name", "sp.first_name", "What is your spouse's first name?", "text", v_name, "Your spouse",
             applies=_married_status, label="Spouse's first name"),
    Question("sp_last_name", "sp.last_name", "What is your spouse's last name?", "text", v_name, "Your spouse",
             applies=_married_status, label="Spouse's last name"),
    Question("sp_dob", "sp.dob", "What is your spouse's date of birth?", "date", v_date, "Your spouse",
             applies=lambda f: _v(f, "filing_status") == "mfj", label="Spouse's date of birth"),
    Question("sp_ssn", "sp.ssn",
             "What is your spouse's Social Security number? Please use a test number starting with 9.",
             "ssn", v_ssn, "Your spouse", applies=_married_status, label="Spouse's SSN", sensitive=True),
    Question("sp_blind", "sp.blind", "Was your spouse legally blind at the end of 2025?", "yes_no", v_yes_no,
             "Your spouse", applies=lambda f: _v(f, "filing_status") == "mfj", label="Spouse is legally blind"),
    Question("sp_claimable", "sp.claimable_dependent",
             "Can someone else claim your spouse as a dependent on their tax return?", "yes_no", v_yes_no,
             "Your spouse", applies=lambda f: _v(f, "filing_status") == "mfj",
             label="Someone can claim your spouse"),
    Question("mfs_itemizes", "mfs.spouse_itemizes",
             "Is your spouse listing their deductions one by one (itemizing) on their own return?",
             "yes_no", v_yes_no, "Your spouse",
             gloss="Itemizing means listing costs like mortgage interest or medical bills instead of taking the standard amount.",
             applies=lambda f: _v(f, "filing_status") == "mfs", label="Spouse itemizes"),
    Question("mfs_apart", "mfs.lived_apart",
             "Did you and your spouse live apart for all of 2025?", "yes_no", v_yes_no, "Your spouse",
             applies=lambda f: _v(f, "filing_status") == "mfs", label="Lived apart from spouse all year"),
    Question("mfs_spouse_no_income", "mfs.spouse_no_income",
             "Did your spouse have no income at all in 2025 and not file a return?", "yes_no", v_yes_no,
             "Your spouse", applies=lambda f: _v(f, "filing_status") == "mfs",
             label="Spouse had no income and is not filing"),
    Question("mfs_sp_dob", "sp.dob", "What is your spouse's date of birth?", "date", v_date, "Your spouse",
             applies=lambda f: _v(f, "filing_status") == "mfs" and _v(f, "mfs.spouse_no_income") is True,
             label="Spouse's date of birth"),
    Question("mfs_sp_blind", "sp.blind", "Was your spouse legally blind at the end of 2025?", "yes_no", v_yes_no,
             "Your spouse", applies=lambda f: _v(f, "filing_status") == "mfs" and _v(f, "mfs.spouse_no_income") is True,
             label="Spouse is legally blind"),
    # dependents (details handled by the dependent loop in the intake agent)
    Question("dependents_any", "dependents.any",
             "Will you claim anyone as a dependent, such as a child or a relative you support?",
             "yes_no", v_yes_no, "Dependents", label="Claiming dependents"),
    # documents and income
    Question("has_w2", "docs.w2.count",
             "How many W-2 forms did you get from employers for 2025? Type 0 if none.",
             "count", v_count, "Your forms",
             gloss="A W-2 is the form an employer sends showing your pay and the tax taken out.",
             label="Number of W-2 forms"),
    Question("stated_wages", "stated_wages",
             "Roughly how much did you earn in total wages from those jobs in 2025? A rough number is fine.",
             "money", v_money, "Your forms",
             gloss="We only use this to double-check the W-2 form you upload.",
             applies=lambda f: (_v(f, "docs.w2.count") or 0) > 0, label="Wages you told us about"),
    Question("has_1099int", "docs.1099int.count",
             "How many forms did you get for bank or bond interest (Form 1099-INT)? Type 0 if none.",
             "count", v_count, "Your forms", label="Number of 1099-INT forms"),
    Question("has_1099div", "docs.1099div.count",
             "How many forms did you get for dividends from stocks or funds (Form 1099-DIV)? Type 0 if none.",
             "count", v_count, "Your forms", label="Number of 1099-DIV forms"),
    Question("has_1099r", "docs.1099r.count",
             "How many forms did you get for pension, annuity, or IRA payments (Form 1099-R)? Type 0 if none.",
             "count", v_count, "Your forms",
             gloss="An IRA is an individual retirement account.", label="Number of 1099-R forms"),
    Question("qcd_any", "qcd.any",
             "Was any part of an IRA payment sent straight from the IRA to a charity?", "yes_no", v_yes_no,
             "Your forms",
             gloss="This is called a qualified charitable distribution. Most people say no.",
             applies=lambda f: (_v(f, "docs.1099r.count") or 0) > 0, label="IRA money sent to charity"),
    Question("qcd_amount", "qcd.amount", "How much of the IRA payment went straight to charity?", "money",
             v_money, "Your forms", applies=lambda f: _v(f, "qcd.any") is True,
             label="Amount sent to charity from IRA"),
    Question("has_ssa1099", "docs.ssa1099.count",
             "How many Social Security benefit statements (Form SSA-1099) did you get? Type 0 if none.",
             "count", v_count, "Your forms",
             gloss="The SSA-1099 arrives each January and shows your Social Security benefits.",
             label="Number of SSA-1099 forms"),
    Question("other_income", "other_income.any",
             "Did you have any other income in 2025, such as your own business or side work, rent from a property, "
             "selling stocks or cryptocurrency, or income from another country?",
             "yes_no", v_yes_no, "Your forms", label="Other income (business, rental, sales, foreign)"),
    Question("other_income_kind", "other_income.kinds", "What kind of other income was it? A few words is fine.",
             "text", v_short_text, "Your forms", applies=lambda f: _v(f, "other_income.any") is True, label="Kind of other income"),
    Question("itemize", "itemize",
             "SilverFile uses the standard deduction, a set amount that most people take. "
             "Were you planning to list your deductions one by one instead?",
             "yes_no", v_yes_no, "Deductions",
             gloss="Listing deductions one by one is called itemizing, for example medical bills or mortgage interest.",
             label="Wants to itemize"),
    # payments and schedules
    Question("est_any", "est.any",
             "Did you send the IRS any estimated tax payments for 2025, or apply last year's refund to this year?",
             "yes_no", v_yes_no, "Payments",
             gloss="Estimated payments are amounts some people pay during the year, often four times a year.",
             label="Made estimated payments"),
    Question("est_amount", "est.amount", "What was the total of those estimated payments for 2025?", "money",
             v_money, "Payments", applies=lambda f: _v(f, "est.any") is True, label="Total estimated payments"),
    Question("sched_any", "sched.any",
             "Do you have any amounts to enter from Schedule 1, 2, or 3? Most people don't.",
             "yes_no", v_yes_no, "Payments",
             gloss="These are extra pages for things like alimony, an IRA deduction, or extra taxes. "
                   "A preparer or last year's return can tell you.",
             label="Has Schedule 1, 2 or 3 amounts"),
    Question("s1_l10", "s1.l10", "What is the amount on Schedule 1, line 10 (additional income)? Type 0 if none.",
             "money", v_money, "Payments", applies=lambda f: _v(f, "sched.any") is True,
             label="Schedule 1, line 10"),
    Question("s1_l26", "s1.l26", "What is the amount on Schedule 1, line 26 (adjustments to income)? Type 0 if none.",
             "money", v_money, "Payments", applies=lambda f: _v(f, "sched.any") is True,
             label="Schedule 1, line 26"),
    Question("s1_l21", "s1.l21",
             "Of that, how much is student loan interest (Schedule 1, line 21)? Type 0 if none.", "money", v_money,
             "Payments", applies=lambda f: _v(f, "sched.any") is True and _v(f, "s1.l26") not in (None, "0.00"),
             label="Schedule 1, line 21"),
    Question("s2_l3", "s2.l3", "What is the amount on Schedule 2, line 3? Type 0 if none.", "money", v_money,
             "Payments", applies=lambda f: _v(f, "sched.any") is True, label="Schedule 2, line 3"),
    Question("s2_l21", "s2.l21", "What is the amount on Schedule 2, line 21? Type 0 if none.", "money", v_money,
             "Payments", applies=lambda f: _v(f, "sched.any") is True, label="Schedule 2, line 21"),
    Question("s3_l8", "s3.l8", "What is the amount on Schedule 3, line 8? Type 0 if none.", "money", v_money,
             "Payments", applies=lambda f: _v(f, "sched.any") is True, label="Schedule 3, line 8"),
    Question("s3_l15", "s3.l15", "What is the amount on Schedule 3, line 15? Type 0 if none.", "money", v_money,
             "Payments", applies=lambda f: _v(f, "sched.any") is True, label="Schedule 3, line 15"),
    Question("line19", "line19.amount",
             "If a preparer worked out a credit for your dependents (Schedule 8812), what is the amount? Type 0 if none.",
             "money", v_money, "Payments", applies=lambda f: _v(f, "dependents.any") is True,
             label="Credit for dependents (line 19)"),
    Question("refund_method", "refund.method",
             "If you get a refund, how would you like to receive it?", "choice", V_REFUND, "Refund",
             options=[("check", "Paper check by mail"), ("direct_deposit", "Direct deposit to a bank account")],
             label="Refund method"),
    Question("refund_account_own", "refund.account_own",
             "Is that bank account in your own name (or your and your spouse's names)?", "yes_no", v_yes_no,
             "Refund", gloss="We don't need the account number now; a preparer adds it later.",
             applies=lambda f: _v(f, "refund.method") == "direct_deposit", label="Refund account is in your name"),
]

QUESTIONS_BY_ID = {q.id: q for q in QUESTIONS}

DEPENDENT_FIELDS = [
    ("first", "What is this dependent's first name?", "text", v_name),
    ("last", "What is this dependent's last name?", "text", v_name),
    ("ssn", "What is this dependent's Social Security number? Please use a test number starting with 9.", "ssn", v_ssn),
    ("relationship", "How is this person related to you? For example: son, daughter, grandchild, parent.", "text", v_name),
]

UPLOAD_QUESTION_ID = "upload_docs"
CONFIRM_QUESTION_ID = "confirm_summary"

FACT_LABELS: dict[str, str] = {q.fact: q.label or q.fact for q in QUESTIONS}
FACT_LABELS.update({"dependents": "Dependents", "docs.uploaded_done": "Documents uploaded",
                    "summary_confirmed": "Summary confirmed"})

DOC_COUNT_FACTS = {
    "W-2": "docs.w2.count",
    "1099-INT": "docs.1099int.count",
    "1099-DIV": "docs.1099div.count",
    "1099-R": "docs.1099r.count",
    "SSA-1099": "docs.ssa1099.count",
}
