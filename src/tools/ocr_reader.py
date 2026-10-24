"""Offline document reader: OCR + layout rules (no model needed).

Used by the Document Extraction agent when no Anthropic API key is set and
by the automated tests. It genuinely reads the *image*: it never looks at
file names, PDF form fields, or fixture metadata.

Method: RapidOCR returns text boxes. For each box we need, we find the
printed label (e.g. "1 Wages, tips, other compensation") and take the
nearest amount printed below it inside the same column. Checkboxes are read
from pixel darkness inside the square next to their label.

It is tuned for the official IRS layouts (W-2, 1099-INT, 1099-DIV, 1099-R)
and the SSA-1099 box numbering. The live model path is more tolerant of
photos; this path is deliberately strict and reports unreadable boxes
rather than guessing.
"""

from __future__ import annotations

import io
import re
import threading
from dataclasses import dataclass

from src.contracts import DocumentExtraction, ExtractedField

_engine = None
_engine_lock = threading.Lock()


def _ocr():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        return _engine


@dataclass
class Token:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    score: float

    @property
    def norm(self) -> str:
        return re.sub(r"[\s’`]", "", self.text.lower().replace("’", "'"))

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


MONEY_RE = re.compile(r"^\$?\s*-?[0-9]{1,3}(,?[0-9]{3})*(\.[0-9]{2})$")
SSN_RE = re.compile(r"(?<!\d)(\d{3})-?(\d{2})-?(\d{4})(?!\d)")

# label keyword (spaces removed, lowercase) for each box, per form
LABELS = {
    "W-2": {"1": ["wages,tips", "wagestips"], "2": ["federalincometax"], "3": ["socialsecuritywages"],
            "4": ["socialsecuritytax"], "5": ["medicarewages"], "6": ["medicaretax"]},
    "1099-INT": {"1": ["1interestincome", "interestincome"], "3": ["interestonu.s", "savingsbonds"],
                 "4": ["federalincometaxwithheld"], "8": ["tax-exemptinterest", "taxexemptinterest"]},
    "1099-DIV": {"1a": ["totalordinarydividends", "ordinarydividends"], "1b": ["qualifieddividends"],
                 "2a": ["totalcapitalgain"], "4": ["federalincometaxwithheld"],
                 "12": ["exempt-interestdividends", "exemptinterestdividends"]},
    "1099-R": {"1": ["grossdistribution"], "2a": ["2ataxableamount", "2a"], "4": ["federalincometax"]},
    "SSA-1099": {"3": ["box3.benefitspaid", "benefitspaid"], "4": ["box4.benefitsrepaid", "benefitsrepaid"],
                 "5": ["box5.netbenefits", "netbenefits"], "6": ["box6.voluntary", "voluntaryfederal"]},
}
FORM_MARKERS = {
    "W-2": ["wageandtaxstatement", "w-2"],
    "1099-INT": ["1099-int"],
    "1099-DIV": ["1099-div"],
    "1099-R": ["1099-r"],
    "SSA-1099": ["ssa-1099"],
}


def read_tokens(image_bytes: bytes) -> tuple[list[Token], object]:
    from PIL import Image
    import numpy as np

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    result, _ = _ocr()(np.array(img))
    tokens = []
    for box, text, score in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        tokens.append(Token(min(xs), min(ys), max(xs), max(ys), str(text), float(score)))
    return tokens, img


def _find_label(tokens: list[Token], keys: list[str]) -> Token | None:
    for key in keys:
        cands = [t for t in tokens if key in t.norm]
        if cands:
            return min(cands, key=lambda t: (t.y0, t.x0))
    return None


def _value_below(tokens: list[Token], label: Token, pattern: re.Pattern, max_dy_factor: float = 4.5,
                 right_span: float = 26.0) -> Token | None:
    """Nearest matching token printed below ``label`` within its column.

    A value must end to the right of where the label starts, may not start far
    to its left, and may not start beyond the next box label on the same row,
    so a neighbouring box's amount is never borrowed."""
    h = max(label.h, 10)
    limit = label.y1 + max_dy_factor * h
    right_bound = label.x0 + right_span * h
    for n in tokens:
        if n is not label and abs(n.cy - label.cy) < 0.6 * h and n.x0 > label.x1 + 0.5 * h \
                and re.match(r"^(box)?\d{1,2}[a-z]?(\.|\b|[a-z])", n.norm):
            right_bound = min(right_bound, n.x0 - 0.2 * h)
    cands = [t for t in tokens if t is not label and t.y0 >= label.cy and t.y0 <= limit
             and t.x1 >= label.x0 and t.x0 >= label.x0 - 3 * h and t.x0 <= right_bound
             and pattern.search(t.text.replace(" ", ""))]
    if not cands:
        return None
    return min(cands, key=lambda t: (round((t.y0 - label.y1) / h), abs(t.x0 - label.x0)))


def _checkbox_checked(img, label: Token, direction: str) -> bool | None:
    """Is the square next to ``label`` (to its right, or below it) marked?

    Locates the checkbox outline as a square contour (OpenCV), then measures
    darkness inside it only, so cell borders and the empty outline never
    count as a mark."""
    import cv2
    import numpy as np

    gray = np.asarray(img.convert("L"))
    h = max(label.h, 10)
    if direction == "right":
        x0, x1 = int(label.x1), int(label.x1 + 3.0 * h)
        y0, y1 = int(label.y0 - 0.8 * h), int(label.y1 + 0.8 * h)
    else:
        x0, x1 = int(label.x0 - 0.8 * h), int(label.x1 + 0.8 * h)
        y0, y1 = int(label.y1), int(label.y1 + 2.5 * h)
    y0, x0 = max(0, y0), max(0, x0)
    region = gray[y0:y1, x0:x1]
    if region.size == 0:
        return None
    _, binary = cv2.threshold(region, 140, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in contours:
        bx, by, bw, bh = cv2.boundingRect(c)
        if 0.45 * h <= bw <= 1.6 * h and 0.45 * h <= bh <= 1.6 * h and 0.75 <= bw / max(bh, 1) <= 1.33:
            if best is None or bw * bh > best[2] * best[3]:
                best = (bx, by, bw, bh)
    if best is None:
        return None
    bx, by, bw, bh = best
    pad_x, pad_y = max(2, int(0.2 * bw)), max(2, int(0.2 * bh))
    interior = binary[by + pad_y:by + bh - pad_y, bx + pad_x:bx + bw - pad_x]
    if interior.size == 0:
        return None
    return float((interior > 0).mean()) > 0.06


def _year(tokens: list[Token], form: str) -> str | None:
    if form in {"1099-INT", "1099-DIV"}:
        label = _find_label(tokens, ["calendaryear"])
        if label:
            val = _value_below(tokens, label, re.compile(r"^(20)?\d{2}$"), max_dy_factor=3.0)
            if val:
                digits = re.sub(r"\D", "", val.text)
                return digits if len(digits) == 4 else "20" + digits
    years = [t for t in tokens if re.fullmatch(r"20\d{2}", t.text.strip()) and t.h >= 0]
    if years:
        return max(years, key=lambda t: t.h).text.strip()
    return None


def _form_seen(tokens: list[Token]) -> str:
    joined = " ".join(t.norm for t in tokens)
    for form in ["SSA-1099", "1099-INT", "1099-DIV", "1099-R", "W-2"]:
        if any(m in joined for m in FORM_MARKERS[form]):
            return form
    return "other"


def _text_below(tokens: list[Token], keys: list[str]) -> str | None:
    label = _find_label(tokens, keys)
    if not label:
        return None
    cands = [t for t in tokens if t.y0 > label.cy and t.y0 <= label.y1 + 3 * label.h
             and abs(t.x0 - label.x0) <= 3 * label.h and not MONEY_RE.match(t.text.replace(" ", ""))]
    return min(cands, key=lambda t: t.y0).text.strip() if cands else None


def extract(image_bytes: bytes, expected_type: str) -> DocumentExtraction:
    tokens, img = read_tokens(image_bytes)
    if not tokens:
        return DocumentExtraction(form_type_seen="unreadable", tax_year=None, recipient_name=None,
                                  recipient_ssn=None, payer_name=None, fields=[], checkboxes=[],
                                  distribution_code=None, notes="No text could be read from the image.")
    form = _form_seen(tokens)
    labels = LABELS.get(expected_type if form == "other" else form, {})
    fields: list[ExtractedField] = []
    for box, keys in labels.items():
        label = _find_label(tokens, keys)
        if expected_type == "1099-R" and box == "2a":
            label = next((t for t in tokens if t.norm.startswith("2a") and "taxable" in t.norm), None) or \
                next((t for t in tokens if t.norm.startswith("2a")), None)
        if label is None:
            continue
        val = _value_below(tokens, label, MONEY_RE)
        if val is None:
            fields.append(ExtractedField(box=box, text=None, readable=True))
        else:
            fields.append(ExtractedField(box=box, text=val.text.replace(" ", "").lstrip("$"),
                                         readable=val.score >= 0.8))
    ssn = None
    ssn_label = _find_label(tokens, ["socialsecuritynumber", "recipient'stin", "recipientstin", "tin"])
    if ssn_label:
        v = _value_below(tokens, ssn_label, SSN_RE, max_dy_factor=3.5)
        if v:
            m = SSN_RE.search(v.text.replace(" ", ""))
            ssn = f"{m[1]}-{m[2]}-{m[3]}" if m else None
    checkboxes: list[str] = []
    code = None
    if (form if form != "other" else expected_type) == "1099-R":
        lbl = _find_label(tokens, ["notdetermined"])
        if lbl and _checkbox_checked(img, lbl, "right"):
            checkboxes.append("Taxable amount not determined")
        lbl = next((t for t in tokens if t.norm in {"simple", "sep/simple"} or t.norm.endswith("simple")), None)
        if lbl and _checkbox_checked(img, lbl, "below"):
            checkboxes.append("IRA/SEP/SIMPLE")
        lbl = _find_label(tokens, ["distribution", "code(s)"])
        lbl = _find_label(tokens, ["code(s)"]) or lbl
        if lbl:
            v = _value_below(tokens, lbl, re.compile(r"^[0-9A-Z]{1,2}$"), max_dy_factor=3.0, right_span=8)
            code = v.text.strip() if v else None
    if (form if form != "other" else expected_type) == "W-2":
        employer = _text_below(tokens, ["employer'sname", "employersname"])
        first = _text_below(tokens, ["employee'sfirstname", "employeesfirstname"])
        last = _text_below(tokens, ["lastname"])
        name = " ".join(x for x in [first, last] if x) or None
    elif form == "SSA-1099" or expected_type == "SSA-1099":
        employer = "Social Security Administration"
        name = _text_below(tokens, ["box1.name"])
        lbl = _find_label(tokens, ["box2.beneficiary"])
        if lbl:
            v = _value_below(tokens, lbl, SSN_RE, max_dy_factor=3.5)
            if v:
                m = SSN_RE.search(v.text.replace(" ", ""))
                ssn = f"{m[1]}-{m[2]}-{m[3]}" if m else ssn
    else:
        lbl = _find_label(tokens, ["payer'sname", "payersname"])
        employer = None
        if lbl:
            below = [t for t in tokens if t.y0 > lbl.y1 and t.y0 < lbl.y1 + 6 * lbl.h and abs(t.x0 - lbl.x0) < 4 * lbl.h
                     and "postal" not in t.norm and "telephone" not in t.norm]
            employer = min(below, key=lambda t: t.y0).text.strip() if below else None
        name = _text_below(tokens, ["recipient'sname", "recipientsname"])
    low = [t.text for t in tokens if MONEY_RE.match(t.text.replace(" ", "")) and t.score < 0.8]
    notes = "Low-confidence amounts: " + ", ".join(low) if low else ""
    return DocumentExtraction(form_type_seen=form if form != "other" else "other", tax_year=_year(tokens, form),
                              recipient_name=name, recipient_ssn=ssn, payer_name=employer, fields=fields,
                              checkboxes=checkboxes, distribution_code=code, notes=notes)
