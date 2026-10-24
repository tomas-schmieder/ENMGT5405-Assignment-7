"""SilverFile command line.

    python run.py ui [--port 8501]        start the local web app (taxpayer intake + dashboard)
    python run.py check                   verify configuration, MCP tools and (if configured) the Anthropic API
    python run.py demo eval_case_1        run a fixture case end to end and print the result
    python run.py demo eval_case_2 --review   ... also play the reviewer for the HITL event
    python run.py eval                    run every case in evals/cases.json and compare with expected results
    python run.py benchmark [--no-context-strategy] [--proxy]   context-window experiment (§4.5)
    python run.py metrics                 rebuild docs/metrics.md from recorded benchmark runs
    python run.py fixtures                regenerate fictional fixtures and demo images
    python run.py graph                   write docs/graph.mmd (orchestration diagram)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def cmd_ui(args) -> int:
    env = dict(os.environ)
    cmd = [sys.executable, "-m", "streamlit", "run", str(ROOT / "streamlit_app.py"), "--server.port", str(args.port),
           "--server.address", args.address]
    print(f"Starting SilverFile on http://localhost:{args.port}  (Ctrl+C to stop)")
    try:
        return subprocess.call(cmd, cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


def cmd_check(args) -> int:
    from src.config import FORMS_DIR, get_settings
    from src.tools.mcp_client import get_tax_tools

    s = get_settings()
    ok = True
    print(f"Python {sys.version.split()[0]} | data directory: {s.var_dir}")
    s.var_dir.mkdir(parents=True, exist_ok=True)
    for f in ["2025_Form_1040-SR.pdf", "2025_Schedule_1-A_Form_1040.pdf", "2025_Form_W-2.pdf"]:
        exists = (FORMS_DIR / f).exists()
        ok &= exists
        print(f"  form template {f}: {'ok' if exists else 'MISSING'}")
    tools = get_tax_tools()
    try:
        tools.start()
        res = tools.call("standard_deduction", {"filing_status": "single", "taxpayer_65_or_older": True,
                                                "taxpayer_blind": False, "spouse_65_or_older": False, "spouse_blind": False,
                                                "can_be_claimed_as_dependent": False, "spouse_itemizes_separately": False,
                                                "dual_status_alien": False})
        print(f"  MCP tax tools: ok ({len(tools.tool_names)} tools; test call {res['call_id']} -> 12e {res['outputs']['12e']})")
    except Exception as exc:
        ok = False
        print(f"  MCP tax tools: FAILED - {exc}")
    mode = s.resolved_llm_mode()
    print(f"  model mode: {mode}" + (f" (model {s.anthropic_model})" if mode == "anthropic" else
                                     " (no ANTHROPIC_API_KEY: OCR + rule-based parsing)"))
    if mode == "anthropic":
        from pydantic import BaseModel

        from src.llm import AnthropicLLM

        class Ping(BaseModel):
            ok: bool

        try:
            call = AnthropicLLM(s.anthropic_model, s.effort, s.use_fallbacks).structured(
                agent="check", system="Reply with ok=true.", messages=[{"role": "user", "content": "ping"}],
                schema=Ping, offline=lambda: Ping(ok=True), purpose="check", max_tokens=200)
            print(f"  Anthropic API: ok (model {call.record.get('model')}, {call.usage['input_tokens']} input tokens)")
        except Exception as exc:
            ok = False
            print(f"  Anthropic API: FAILED - {exc}")
    print("All checks passed." if ok else "Some checks failed (see above).")
    return 0 if ok else 1


def _service():
    from src.service import SilverFileService

    return SilverFileService()


def cmd_demo(args) -> int:
    from src.driver import load_case, run_case, summarize

    spec = load_case(args.case)
    if not args.review:
        spec = {**spec, "reviewer_actions": []}
    view = run_case(_service(), spec)
    out = summarize(view)
    print(json.dumps(out, indent=2))
    if view["pending"] and view["pending"]["kind"] == "human_review":
        e = view["pending"]["event"]
        print(f"\nPaused for human review: {e['reason_label']} - {e['summary']}")
        print("Open the Employee dashboard (python run.py ui) to resolve it, or rerun with --review.")
    return 0


def cmd_eval(args) -> int:
    from src.driver import load_case, run_case

    cat = json.loads((ROOT / "evals" / "cases.json").read_text())["cases"]
    svc = _service()
    traces = ROOT / "traces"
    traces.mkdir(exist_ok=True)
    results, failures = [], 0
    for c in cat:
        if c["expect"] == "benchmark" or (args.cases and c["id"] not in args.cases):
            continue
        view = run_case(svc, load_case(c["id"]))
        got_lines = {k: v["value"] for k, v in view["lines"].items()}
        ok, detail = True, ""
        if c["expect"] == "draft":
            exp = json.loads((ROOT / "evals" / "expected_results" / f"{c['id']}.json").read_text())
            mism = {k: (got_lines.get(k), v) for k, v in exp["lines"].items() if got_lines.get(k) != v}
            ok = view["status"] == "submitted_for_internal_review" and not mism
            detail = f"mismatches={mism}" if mism else f"status={view['status']}"
        else:
            reason = (view["pending"] or {}).get("event", {}).get("reason")
            ok = reason == c["reason"] and not view["assembly"]
            detail = f"escalated={reason}"
        failures += 0 if ok else 1
        results.append({"case": c["id"], "kind": c["kind"], "ok": ok, "detail": detail, "case_id": view["case_id"]})
        print(f"{'PASS' if ok else 'FAIL'}  {c['id']:28s} {detail}")
        (traces / f"{c['id']}.json").write_text(json.dumps({
            "case": c["id"], "case_id": view["case_id"], "status": view["status"], "mode": view["llm_mode"],
            "script": view.get("script_log"), "routing": view["routing"].get("history"), "trace": view["trace"],
            "human_events": view["human_events"], "metrics": view["metrics"], "lines": got_lines}, indent=2, default=str))
    (traces / "eval_results.json").write_text(json.dumps({"results": results, "failures": failures}, indent=2))
    print(f"\n{len(results) - failures}/{len(results)} cases passed; traces written to traces/")
    return 1 if failures else 0


def cmd_benchmark(args) -> int:
    argv = [sys.executable, str(ROOT / "scripts" / "context_benchmark.py")]
    if args.no_context_strategy:
        argv.append("--no-context-strategy")
    if args.proxy:
        argv.append("--proxy")
    return subprocess.call(argv, cwd=str(ROOT))


def cmd_metrics(args) -> int:
    return subprocess.call([sys.executable, str(ROOT / "scripts" / "context_benchmark.py"), "--report"], cwd=str(ROOT))


def cmd_fixtures(args) -> int:
    return subprocess.call([sys.executable, str(ROOT / "data" / "generate_fixtures.py")], cwd=str(ROOT))


def cmd_graph(args) -> int:
    from src.agents.base import Runtime
    from src.config import get_settings
    from src.graph import mermaid
    from src.llm import OfflineLLM

    text = mermaid(Runtime(llm=OfflineLLM(), tools=None, settings=get_settings()))
    (ROOT / "docs" / "graph.mmd").write_text(text)
    print("wrote docs/graph.mmd")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SilverFile - draft Form 1040-SR multi-agent prototype")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ui")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8501")))
    p.add_argument("--address", default=os.environ.get("SILVERFILE_ADDRESS", "localhost"))
    sub.add_parser("check")
    p = sub.add_parser("demo")
    p.add_argument("case", nargs="?", default="eval_case_1")
    p.add_argument("--review", action="store_true", help="play the fixture's reviewer decisions")
    p = sub.add_parser("eval")
    p.add_argument("--cases", nargs="*")
    p = sub.add_parser("benchmark")
    p.add_argument("--no-context-strategy", action="store_true")
    p.add_argument("--proxy", action="store_true")
    sub.add_parser("metrics")
    sub.add_parser("fixtures")
    sub.add_parser("graph")
    args = ap.parse_args()
    return {"ui": cmd_ui, "check": cmd_check, "demo": cmd_demo, "eval": cmd_eval, "benchmark": cmd_benchmark,
            "metrics": cmd_metrics, "fixtures": cmd_fixtures, "graph": cmd_graph}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
