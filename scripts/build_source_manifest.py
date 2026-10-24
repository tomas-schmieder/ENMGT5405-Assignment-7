"""Build data/source_manifest.json: hashes and identity checks for every
reference document SilverFile cites.

The files in data/reference_tax_forms were assembled by a team member with
AI help and were not supplied by the professor. This script records what was
actually verified about each one (PDF title, tax year text on a cited page)
rather than asserting provenance. Source URLs are recorded only where the
assignment itself gives one.

Run:  python scripts/build_source_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference_tax_forms"

SOURCES = [
    # id, relative path, expected title, page to check (1-based), required text on that page, use, url
    ("irs-f1040sr-2025", "forms/2025_Form_1040-SR.pdf", "2025 Form 1040-SR", 1, "1040-SR",
     "Draft output template; Standard Deduction Chart (p. 4)", "https://www.irs.gov/pub/irs-pdf/f1040s.pdf"),
    ("irs-sch1a-2025", "forms/2025_Schedule_1-A_Form_1040.pdf", "2025 Schedule 1-A (Form 1040)", 2,
     "Enhanced Deduction for Seniors", "Line 13b support schedule (Part V)", None),
    ("irs-sch1-2025", "forms/2025_Schedule_1_Form_1040.pdf", "2025 Schedule 1 (Form 1040)", 1, "2025",
     "Reference for direct-input lines", None),
    ("irs-sch2-2025", "forms/2025_Schedule_2_Form_1040.pdf", "2025 Schedule 2 (Form 1040)", 1, "2025",
     "Reference for direct-input lines", None),
    ("irs-sch3-2025", "forms/2025_Schedule_3_Form_1040.pdf", "2025 Schedule 3 (Form 1040)", 1, "2025",
     "Reference for direct-input lines", None),
    ("irs-fw2-2025", "forms/2025_Form_W-2.pdf", "2025 Form W-2", 4, "2025",
     "Template for fictional W-2 fixtures (Copy B, p. 4)", None),
    ("irs-f1099r-2025", "forms/2025_Form_1099-R.pdf", "2025 Form 1099-R", 4, "2025",
     "Template for fictional 1099-R fixtures (Copy B)", None),
    ("irs-f1099int-2024rev", "forms/Form_1099-INT_Rev_Jan_2024.pdf", "Form 1099-INT (Rev. January 2024)", 4,
     "calendar year", "Template for fictional 1099-INT fixtures; continuous-use revision with a calendar-year field set to 2025", None),
    ("irs-f1099div-2024rev", "forms/Form_1099-DIV_Rev_Jan_2024.pdf", "Form 1099-DIV (Rev. January 2024)", 4,
     "calendar year", "Template for fictional 1099-DIV fixtures; continuous-use revision with a calendar-year field set to 2025", None),
    ("irs-i1040-2025", "reference/2025_Instructions_Form_1040_and_1040-SR.pdf", "2025 Instruction 1040", 32,
     "Social Security Benefits Worksheet", "Rules corpus: worksheets, tax table, line instructions", None),
    ("irs-i1099r-2025", "reference/2025_Instructions_1099-R_5498.pdf", "2025 Instructions for Forms 1099-R and 5498",
     13, "Box 2b", "Rules corpus: 1099-R box 2b and distribution codes", None),
    ("irs-iw2w3-2025", "reference/2025_General_Instructions_W-2_W-3.pdf", "2025 General Instructions for Forms W-2 and W-3",
     17, "Box 1", "Rules corpus: W-2 box meanings", None),
    ("irs-p915-2025", "reference/2025_Publication_915_Social_Security_Benefits.pdf", "2025 Publication 915", 4,
     "base amount", "Rules corpus: Social Security background and exceptions", None),
]

SSA_SAMPLES = [
    ("ssa-sample-2002-retro", "ssa_samples/SSA-1099_Example_1_Retroactive_Payments.gif"),
    ("ssa-sample-2012-overpay", "ssa_samples/SSA-1099_Example_2_Overpayment.gif"),
    ("ssa-sample-2002-wc", "ssa_samples/SSA-1099_Example_3_Workers_Comp.gif"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    import pymupdf

    entries = []
    failures = 0
    for sid, rel, title, page, needle, use, url in SOURCES:
        path = REF / rel
        doc = pymupdf.open(str(path))
        actual_title = doc.metadata.get("title") or ""
        page_text = doc[page - 1].get_text()
        checks = {
            "title_matches": actual_title.strip() == title,
            f"page_{page}_contains_{needle!r}": needle in page_text,
        }
        ok = all(checks.values())
        failures += 0 if ok else 1
        entries.append({
            "id": sid, "path": f"data/reference_tax_forms/{rel}", "sha256": sha256(path),
            "bytes": path.stat().st_size, "pages": len(doc), "pdf_title": actual_title,
            "permitted_use": use, "source_url": url,
            "source_url_note": "given in the assignment" if url else "not verified in this environment; not invented",
            "identity_checks": checks, "verified": ok,
        })
    for sid, rel in SSA_SAMPLES:
        path = REF / rel
        entries.append({
            "id": sid, "path": f"data/reference_tax_forms/{rel}", "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "permitted_use": "Historical layout reference only (2002/2012 statements). Not used as 2025 demo data.",
            "source_url": None, "verified": None,
        })
    manifest = {
        "generated": date.today().isoformat(),
        "note": ("Reference documents were collected by the team with AI assistance and were not supplied "
                 "by the professor. 'verified' records only the identity checks listed."),
        "assignment": {"id": "assignment", "path": "Assignment-7-Details.md",
                       "sha256": sha256(ROOT / "Assignment-7-Details.md"),
                       "note": "Authoritative for scope and grading."},
        "sources": entries,
    }
    out = ROOT / "data" / "source_manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {out.relative_to(ROOT)}: {len(entries)} sources, {failures} failed identity checks")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
