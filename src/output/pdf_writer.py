"""Fill the official 2025 Form 1040-SR (and Schedule 1-A when line 13b > 0).

The writer only *places* values it is given; it performs no tax arithmetic.
After writing it verifies the result two ways:

1. logical: re-open the PDF and read every field back;
2. visual: flatten a copy (widgets baked into page content), extract the page
   text, and confirm each written value is actually visible.

Preview PNGs of each page are rendered for the dashboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import FORMS_DIR
from src.output.pdf_fields import (DIGITAL_ASSETS_NO, DRAFT_BANNER, F1040SR_CHECKBOX, F1040SR_TEXT,
                                   FILING_STATUS_WIDGETS, SCH1A_TEXT)


def _fmt(value: Any) -> str:
    """Whole-dollar line values with thousands separators, as printed forms show them."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _stamp(page) -> None:
    import pymupdf

    page.insert_text((150, 12), DRAFT_BANNER, fontsize=8, fontname="hebo", color=(0.8, 0, 0))
    page.insert_text((36, page.rect.height - 8), "Prepared by SilverFile (classroom prototype). Not filed. "
                     "A Kushim volunteer must review every value.", fontsize=6, fontname="helv", color=(0.8, 0, 0))
    page.draw_rect(pymupdf.Rect(2, 2, page.rect.width - 2, page.rect.height - 2), color=(0.8, 0, 0), width=0.8)


def _comb_ssn(ssn: str | None) -> str:
    """The 1040-SR SSN boxes are 9-character comb fields: digits only."""
    return "".join(ch for ch in (ssn or "") if ch.isdigit())


def build_field_values(facts: dict, lines: dict, boxes: dict, schedule_1a: dict, box_count: str | None) -> dict:
    """Return {'text': {short_name: str}, 'checks': [short_name], 'filing_status': fs, ...}."""
    text: dict[str, str] = {}
    checks: list[str] = []
    text[F1040SR_TEXT["tp_first"]] = facts.get("tp.first_name", "")
    text[F1040SR_TEXT["tp_last"]] = facts.get("tp.last_name", "")
    text[F1040SR_TEXT["tp_ssn"]] = _comb_ssn(facts.get("tp.ssn"))
    fs = facts.get("filing_status")
    if fs in {"mfj", "mfs"}:
        text[F1040SR_TEXT["sp_ssn"]] = _comb_ssn(facts.get("sp.ssn"))
    if fs == "mfj":
        text[F1040SR_TEXT["sp_first"]] = facts.get("sp.first_name", "")
        text[F1040SR_TEXT["sp_last"]] = facts.get("sp.last_name", "")
    if fs == "mfs":
        text[F1040SR_TEXT["mfs_spouse_name"]] = f"{facts.get('sp.first_name', '')} {facts.get('sp.last_name', '')}".strip()
    for i, dep in enumerate((facts.get("dependents") or [])[:4], start=1):
        text[F1040SR_TEXT[f"dep{i}_first"]] = dep.get("first", "")
        text[F1040SR_TEXT[f"dep{i}_last"]] = dep.get("last", "")
        text[F1040SR_TEXT[f"dep{i}_ssn"]] = _comb_ssn(dep.get("ssn"))
        text[F1040SR_TEXT[f"dep{i}_rel"]] = dep.get("relationship", "")
    for line, entry in lines.items():
        name = F1040SR_TEXT.get(line)
        if name and entry.get("value") not in (None, ""):
            text[name] = _fmt(entry["value"])
    if box_count is not None:
        text[F1040SR_TEXT["chart_box_count"]] = str(box_count)
    if boxes.get("tp_65"):
        checks.append(F1040SR_CHECKBOX["12d_tp_born_before"])
    if boxes.get("tp_blind"):
        checks.append(F1040SR_CHECKBOX["12d_tp_blind"])
    if boxes.get("sp_65"):
        checks.append(F1040SR_CHECKBOX["12d_sp_born_before"])
    if boxes.get("sp_blind"):
        checks.append(F1040SR_CHECKBOX["12d_sp_blind"])
    if facts.get("qcd.any") is True:
        checks.append(F1040SR_CHECKBOX["4c_qcd"])
    if fs == "mfs" and facts.get("mfs.lived_apart") is True:
        checks.append(F1040SR_CHECKBOX["6d_mfs_lived_apart"])
    sch = {}
    if schedule_1a and int(schedule_1a.get("sch1a_38") or 0) > 0:
        sch = {SCH1A_TEXT["name"]: f"{facts.get('tp.first_name', '')} {facts.get('tp.last_name', '')}".strip(),
               SCH1A_TEXT["ssn"]: facts.get("tp.ssn", ""),
               SCH1A_TEXT["sch1a_1"]: _fmt(schedule_1a.get("sch1a_31")),
               SCH1A_TEXT["sch1a_2e"]: "0", SCH1A_TEXT["sch1a_3"]: _fmt(schedule_1a.get("sch1a_31"))}
        for key in ["sch1a_31", "sch1a_32", "sch1a_33", "sch1a_34", "sch1a_35", "sch1a_36a", "sch1a_36b",
                    "sch1a_37", "sch1a_38"]:
            if key == "sch1a_36b" and fs != "mfj":
                continue
            sch[SCH1A_TEXT[key]] = _fmt(schedule_1a.get(key, "0"))
    return {"text": text, "checks": checks, "filing_status": fs,
            "digital_assets_no": facts.get("other_income.any") is False, "schedule_1a": sch}


def write_draft(values: dict, out_path: Path) -> dict:
    """Write the filled draft PDF and return verification results."""
    import pymupdf

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(FORMS_DIR / "2025_Form_1040-SR.pdf"))
    written: dict[str, str] = {}
    for page in doc:
        for w in page.widgets():
            short = w.field_name.split(".")[-1]
            if w.field_type == pymupdf.PDF_WIDGET_TYPE_TEXT and short in values["text"]:
                w.field_value = values["text"][short]
                w.update()
                written[f"p{page.number + 1}:{short}"] = values["text"][short]
            elif w.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                pos = (round(w.rect.x0), round(w.rect.y0))
                hit = False
                if page.number == 0 and short.startswith("c1_8"):
                    target = FILING_STATUS_WIDGETS.get(values["filing_status"])
                    hit = target is not None and abs(pos[0] - target[0]) <= 2 and abs(pos[1] - target[1]) <= 2
                elif page.number == 0 and short.startswith(DIGITAL_ASSETS_NO[0]):
                    hit = values.get("digital_assets_no") and abs(pos[0] - DIGITAL_ASSETS_NO[1][0]) <= 2
                elif page.number == 1 and short in values["checks"]:
                    hit = True
                if hit:
                    w.field_value = w.on_state()
                    w.update()
                    written[f"p{page.number + 1}:{short}@{pos[0]},{pos[1]}"] = "checked"
        _stamp(page)
    if values.get("schedule_1a"):
        sch = pymupdf.open(str(FORMS_DIR / "2025_Schedule_1-A_Form_1040.pdf"))
        for page in sch:
            for w in page.widgets():
                short = w.field_name.split(".")[-1]
                if w.field_type == pymupdf.PDF_WIDGET_TYPE_TEXT and short in values["schedule_1a"]:
                    w.field_value = values["schedule_1a"][short]
                    w.update()
                    written[f"s1a_p{page.number + 1}:{short}"] = values["schedule_1a"][short]
            _stamp(page)
        doc.insert_pdf(sch)
    doc.save(str(out_path), garbage=3, deflate=True)
    doc.close()
    return {"written": written, **verify_pdf(out_path, written)}


def verify_pdf(path: Path, written: dict[str, str]) -> dict:
    """Read fields back and check visible text on a flattened copy."""
    import pymupdf

    doc = pymupdf.open(str(path))
    logical_missing = []
    readback: dict[str, str] = {}
    for page in doc:
        prefix = f"p{page.number + 1}" if page.number < 4 else f"s1a_p{page.number - 3}"
        for w in page.widgets():
            short = w.field_name.split(".")[-1]
            readback.setdefault(f"{prefix}:{short}", str(w.field_value))
    for key, value in written.items():
        if value == "checked":
            continue
        if readback.get(key) != value:
            logical_missing.append(key)
    flat = pymupdf.open(str(path))
    flat.bake()
    page_text = ["".join(p.get_text().split()) for p in flat]  # comb fields space their characters
    visible_missing = []
    for key, value in written.items():
        if value == "checked" or not value:
            continue
        prefix = key.split(":")[0]
        pno = int(prefix[1:]) - 1 if prefix.startswith("p") else 4 + int(prefix.split("_p")[1]) - 1
        if "".join(value.split()) not in page_text[pno]:
            visible_missing.append(key)
    pages = len(doc)
    doc.close()
    flat.close()
    return {"pages": pages, "logical_ok": not logical_missing, "logical_missing": logical_missing,
            "visible_ok": not visible_missing, "visible_missing": visible_missing}


def render_previews(pdf_path: Path, out_dir: Path, dpi: int = 90) -> list[str]:
    import pymupdf

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(pdf_path))
    paths = []
    for page in doc:
        p = out_dir / f"{pdf_path.stem}_page{page.number + 1}.png"
        page.get_pixmap(dpi=dpi).save(str(p))
        paths.append(str(p))
    doc.close()
    return paths
