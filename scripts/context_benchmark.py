"""Context-window experiment (assignment §4.5).

Interpretation (docs/ASSUMPTIONS.md A-04): the "10 invoices" are ten distinct
2025 tax documents (fixture ``bench_ten_docs``) processed sequentially by the
Document Extraction agent in ONE thread, in a fixed order, with the same model,
prompt and schema in both runs.

* ``--no-context-strategy``: every call replays the whole thread so far
  (all earlier document images and the agent's earlier JSON answers), as a
  naive chat thread would.
* default (strategy enabled, *selective recall*): each call sends only the
  current document plus a compact, deterministic summary of session decisions
  (documents processed and the key box values exactly as extracted).

Live mode records the real ``usage`` returned by the Anthropic API for every
call (input, cache creation, cache read, output tokens). The comparison total
is input + cache_creation + cache_read: all prompt tokens the model processed.
No cache_control is set, so cache fields are expected to be zero.

Without an API key, ``--proxy`` runs the identical harness and records a
*size proxy* (characters of text sent + number of images) instead of tokens.
Proxy runs are labelled as such everywhere and are never reported as token
measurements.

Usage:
    python scripts/context_benchmark.py                       # live, strategy on
    python scripts/context_benchmark.py --no-context-strategy # live, strategy off
    python scripts/context_benchmark.py --proxy [--no-context-strategy]
    python scripts/context_benchmark.py --report              # write docs/metrics.md + chart
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.document_extraction import SYSTEM_PROMPT, build_record  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.contracts import DocumentExtraction  # noqa: E402
from src.llm import image_block  # noqa: E402
from src.memory import build_document_context  # noqa: E402

CASE = "bench_ten_docs"
TRACES = ROOT / "traces"


def _summary(records: list[dict]) -> str:
    if not records:
        return "No documents processed yet in this session."
    lines = [f"{len(records)} document(s) processed so far in this session:"]
    for i, r in enumerate(records, 1):
        boxes = ", ".join(f"box {b}={f['raw'] or 'blank'}" for b, f in (r.get("fields") or {}).items() if f.get("raw"))
        lines.append(f"{i}. {r['doc_type']} from {r.get('payer')}: {boxes}")
    lines.append("Decisions: all documents above accepted; transcribe the next document independently.")
    return "\n".join(lines)


def run(strategy: bool, proxy: bool) -> Path:
    settings = get_settings()
    spec = json.loads((ROOT / "data" / "fixtures" / CASE / "case.json").read_text())
    docs = spec["documents"]
    if not proxy:
        if settings.resolved_llm_mode() != "anthropic":
            raise SystemExit("Live measurement needs ANTHROPIC_API_KEY (or use --proxy for a labelled dry run).")
        from src.llm import AnthropicLLM

        llm = AnthropicLLM(settings.anthropic_model, settings.effort, settings.use_fallbacks)
    run_id = f"bench-{'on' if strategy else 'off'}-{uuid.uuid4().hex[:6]}"
    prior: list[dict] = []
    records: list[dict] = []
    rows = []
    for i, d in enumerate(docs, 1):
        data = (ROOT / d["file"]).read_bytes()
        blocks = [image_block(data, "image/png"),
                  {"type": "text", "text": f"Document {i} of {len(docs)} in this session. This should be Form "
                                           f"{d['type']} for tax year 2025. Transcribe it."}]
        messages = build_document_context(prior, blocks, _summary(records), strategy_enabled=strategy)
        started = time.perf_counter()
        if proxy:
            from src.tools.ocr_reader import extract

            ex = extract(data, d["type"])
            text_chars = sum(len(b.get("text", "")) if isinstance(b, dict) else 0
                             for m in messages for b in (m["content"] if isinstance(m["content"], list) else
                                                         [{"text": m["content"]}]))
            images = sum(1 for m in messages if isinstance(m["content"], list)
                         for b in m["content"] if isinstance(b, dict) and b.get("type") == "image")
            usage = {"proxy_text_chars": text_chars + len(SYSTEM_PROMPT), "proxy_images": images}
            model = "proxy (no model call)"
        else:
            call = llm.structured(agent="document_extraction", system=SYSTEM_PROMPT, messages=messages,
                                  schema=DocumentExtraction, offline=lambda: None, purpose="benchmark",
                                  max_tokens=3000)
            ex = call.data
            usage = dict(call.usage)
            model = call.record.get("model")
        rec = build_record({"doc_id": f"b{i:02d}", "doc_type": d["type"], "revision": 0}, ex, "benchmark", None, "")
        records.append(rec)
        prior.append({"user": blocks, "assistant": ex.model_dump_json()})
        row = {"doc": i, "doc_type": d["type"], "file": Path(d["file"]).name, "messages_sent": len(messages),
               "latency_s": round(time.perf_counter() - started, 2), "model": model, **usage,
               "extracted": {b: f["value"] for b, f in rec["fields"].items() if not f.get("blank")},
               "issues": [x["code"] for x in rec["issues"]]}
        if not proxy:
            row["total_prompt_tokens"] = (usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0) \
                + (usage.get("cache_read_input_tokens") or 0)
        rows.append(row)
        print(json.dumps({k: row[k] for k in row if k not in {"extracted"}}))
    TRACES.mkdir(exist_ok=True)
    out = TRACES / f"benchmark_{'proxy_' if proxy else ''}{'strategy_on' if strategy else 'strategy_off'}.json"
    out.write_text(json.dumps({"run_id": run_id, "case": CASE, "strategy_enabled": strategy, "proxy": proxy,
                               "model": settings.anthropic_model if not proxy else None,
                               "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "rows": rows}, indent=2))
    print(f"wrote {out.relative_to(ROOT)}")
    return out


def report() -> None:
    """Build docs/metrics.md (and a chart) from whichever runs exist."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def load(name):
        p = TRACES / name
        return json.loads(p.read_text()) if p.exists() else None

    live_on, live_off = load("benchmark_strategy_on.json"), load("benchmark_strategy_off.json")
    prx_on, prx_off = load("benchmark_proxy_strategy_on.json"), load("benchmark_proxy_strategy_off.json")
    expected = json.loads((ROOT / "data" / "fixtures" / CASE / "case.json").read_text())["documents"]
    md = ["# Context-window metrics (assignment §4.5)", "",
          "Ten distinct 2025 tax documents (`data/fixtures/bench_ten_docs`) are processed sequentially by the "
          "Document Extraction agent in one thread, in the same fixed order, with the same model, prompt and "
          "schema. *Strategy off* replays the whole thread on every call; *strategy on* (selective recall) sends "
          "the current document plus a compact summary of session decisions. See `scripts/context_benchmark.py` "
          "and `src/memory.py`.", ""]
    if live_on and live_off:
        md += ["## Measured input tokens per document (Anthropic API `usage`)", "",
               f"Model: `{live_on['model']}`. Runs: `{live_off['run_id']}` (off, {live_off['run_at']}) and "
               f"`{live_on['run_id']}` (on, {live_on['run_at']}). Total = input + cache creation + cache read "
               "tokens.", "",
               "| Doc | Form | Strategy OFF total | OFF input | Strategy ON total | ON input | Saved |",
               "|---:|---|---:|---:|---:|---:|---:|"]
        for a, b in zip(live_off["rows"], live_on["rows"]):
            saved = 1 - b["total_prompt_tokens"] / a["total_prompt_tokens"] if a["total_prompt_tokens"] else 0
            md.append(f"| {a['doc']} | {a['doc_type']} | {a['total_prompt_tokens']:,} | {a['input_tokens']:,} | "
                      f"{b['total_prompt_tokens']:,} | {b['input_tokens']:,} | {saved:.0%} |")
        so = sum(r["total_prompt_tokens"] for r in live_off["rows"])
        sn = sum(r["total_prompt_tokens"] for r in live_on["rows"])
        md += ["", f"Totals: strategy off **{so:,}** tokens, strategy on **{sn:,}** tokens "
                   f"({1 - sn / so:.0%} fewer). First-to-last growth: off "
                   f"{live_off['rows'][0]['total_prompt_tokens']:,} -> {live_off['rows'][-1]['total_prompt_tokens']:,}; "
                   f"on {live_on['rows'][0]['total_prompt_tokens']:,} -> {live_on['rows'][-1]['total_prompt_tokens']:,}.", ""]
        md += _consistency(live_off, live_on, expected)
        _chart(plt, live_off, live_on, "total_prompt_tokens", "Prompt tokens per call", ROOT / "docs" / "metrics_chart.png")
        md += ["![Tokens per document](metrics_chart.png)", ""]
    else:
        md += ["## Measured token counts: NOT YET RUN", "",
               "No live run has been recorded in this repository yet, because it needs an Anthropic API key. "
               "Run on a machine with `ANTHROPIC_API_KEY` set:", "", "```bash",
               "python run.py benchmark --no-context-strategy", "python run.py benchmark", "python run.py metrics",
               "```", "", "This rewrites this file with the measured per-document table and chart. No token numbers "
               "are shown here until then.", ""]
    if prx_on and prx_off:
        md += ["## Harness dry run (size proxy, NOT tokens)", "",
               "The same harness run offline (OCR instead of a model call). It records what would be sent: "
               "characters of text and the number of images per call. This only checks that the harness and both "
               "context strategies behave as designed; it is not a token measurement.", "",
               "| Doc | Form | OFF images sent | OFF text chars | ON images sent | ON text chars |",
               "|---:|---|---:|---:|---:|---:|"]
        for a, b in zip(prx_off["rows"], prx_on["rows"]):
            md.append(f"| {a['doc']} | {a['doc_type']} | {a['proxy_images']} | {a['proxy_text_chars']:,} | "
                      f"{b['proxy_images']} | {b['proxy_text_chars']:,} |")
        md += [""] + _consistency(prx_off, prx_on, expected)
    (ROOT / "docs" / "metrics.md").write_text("\n".join(md) + "\n")
    print("wrote docs/metrics.md")


def _consistency(off: dict, on: dict, expected: list[dict]) -> list[str]:
    """Both runs must extract the same values; otherwise the strategy fails even if cheaper."""
    same = sum(1 for a, b in zip(off["rows"], on["rows"]) if a["extracted"] == b["extracted"])
    diffs = [a["doc"] for a, b in zip(off["rows"], on["rows"]) if a["extracted"] != b["extracted"]]
    note = "" if not diffs else f" Documents that differ: {diffs}."
    return [f"Result consistency: {same}/{len(off['rows'])} documents extracted identically in both runs.{note}", ""]


def _chart(plt, off: dict, on: dict, key: str, ylabel: str, path: Path) -> None:
    xs = [r["doc"] for r in off["rows"]]
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
    ax.plot(xs, [r[key] for r in off["rows"]], marker="o", color="#b91c1c", label="Strategy off (full thread)")
    ax.plot(xs, [r[key] for r in on["rows"]], marker="o", color="#1e3a8a", label="Strategy on (selective recall)")
    ax.set_xlabel("Document number in the thread")
    ax.set_ylabel(ylabel)
    ax.set_xticks(xs)
    ax.grid(alpha=0.3)
    ax.legend(frameon=False)
    ax.set_title("Context growth across ten documents in one thread")
    fig.tight_layout()
    fig.savefig(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-context-strategy", action="store_true", help="replay the full thread on every call")
    ap.add_argument("--proxy", action="store_true", help="offline dry run recording a size proxy, not tokens")
    ap.add_argument("--report", action="store_true", help="write docs/metrics.md from recorded runs")
    args = ap.parse_args()
    if args.report:
        report()
        return
    run(strategy=not args.no_context_strategy, proxy=args.proxy)


if __name__ == "__main__":
    main()
