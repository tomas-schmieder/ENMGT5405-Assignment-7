"""Draw docs/graph.png: the implemented SilverFile orchestration.

The node and edge set mirrors src/graph.py (tests/unit/test_graph_shape.py checks
the compiled graph has exactly these nodes); the drawing adds what matters for
review: the parallel fan-out and reducer, the bounded review cycle, the two
interrupt points, the MCP tool server and the persistent checkpointer.

Run:  python scripts/draw_graph.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INK, ACCENT, HUMAN, TOOL, GREY = "#111827", "#1e3a8a", "#9a3412", "#065f46", "#6b7280"
FILL, HFILL, TFILL, NFILL = "#eef2ff", "#fff7ed", "#ecfdf5", "#f3f4f6"

fig, ax = plt.subplots(figsize=(14, 8.4), dpi=150)
ax.set_xlim(0, 14)
ax.set_ylim(0, 8.4)
ax.axis("off")


def box(x, y, w, h, title, sub="", color=ACCENT, fill=FILL, lw=1.6):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.1",
                                linewidth=lw, edgecolor=color, facecolor=fill))
    ax.text(x, y + (0.13 if sub else 0), title, ha="center", va="center", fontsize=10.5, fontweight="bold", color=INK)
    if sub:
        ax.text(x, y - 0.19, sub, ha="center", va="center", fontsize=7.8, color=GREY)


def arrow(a, b, color=GREY, style="-", rad=0.0, lw=1.3):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=11, color=color, linewidth=lw,
                                 linestyle=style, connectionstyle=f"arc3,rad={rad}"))


def label(x, y, text, color=GREY, size=7.8):
    ax.text(x, y, text, fontsize=size, color=color, ha="center", va="center",
            bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none"))


def spoke(x, top_y, bottom_y, route_label, color=ACCENT, down=True):
    """Dashed route from the hub and solid return to it, side by side."""
    if down:
        arrow((x - 0.18, top_y), (x - 0.18, bottom_y), color, "--")
        arrow((x + 0.18, bottom_y), (x + 0.18, top_y), GREY)
        label(x - 0.18, (top_y + bottom_y) / 2, route_label, color)
    else:
        arrow((x - 0.18, bottom_y), (x - 0.18, top_y), color, "--")
        arrow((x + 0.18, top_y), (x + 0.18, bottom_y), GREY)
        label(x - 0.18, (top_y + bottom_y) / 2, route_label, color)


ax.text(7, 8.1, "SilverFile orchestration (LangGraph)", ha="center", fontsize=15, fontweight="bold", color=ACCENT)
ax.text(7, 7.78, "Six functional agents + a deterministic orchestrator. Dashed: conditional route chosen from state. "
        "Solid grey: the agent returns control to the orchestrator.", ha="center", fontsize=8.6, color=GREY)

# hub
HUB_Y = 4.6
box(7, HUB_Y, 12.6, 0.8, "Orchestrator", "routes on state  |  loop guard  |  owns termination  |  never talks, "
    "extracts or computes", lw=2.2)

# top row: people-facing
box(1.4, 6.85, 1.3, 0.5, "START", color=GREY, fill=NFILL)
arrow((1.4, 6.6), (1.4, HUB_Y + 0.42), ACCENT)
box(4.4, 6.75, 2.6, 0.8, "Intake", "only agent that talks to the taxpayer", HUMAN, HFILL)
spoke(4.4, HUB_Y + 0.42, 6.33, "next question", down=False)
label(4.4, 7.33, "interrupt(): waits for the taxpayer", HUMAN)
box(9.0, 6.75, 2.6, 0.8, "Human review", "Kushim reviewer decision", HUMAN, HFILL)
spoke(9.0, HUB_Y + 0.42, 6.33, "escalation", HUMAN, down=False)
label(9.0, 7.33, "interrupt(): waits for the reviewer", HUMAN)
box(12.4, 6.85, 1.3, 0.5, "END", color=GREY, fill=NFILL)
arrow((12.4, HUB_Y + 0.42), (12.4, 6.6), GREY, "--")
label(12.4, 5.75, "submitted /\nreferred", GREY)

# bottom row: processing agents
ROW = 2.55
W, H = 2.05, 0.95
cols = {"extract": 1.35, "aggregate": 3.6, "rules": 5.85, "comp": 8.1, "review": 10.35, "asm": 12.6}
for i, dx in enumerate([0.12, 0.06, 0.0]):
    box(cols["extract"] + dx, ROW + dx, W, H, "extract_document" if i == 2 else "", "x N in parallel (Send)" if i == 2 else "")
box(cols["aggregate"], ROW, W, H, "Aggregate", "fan-in; reducer merges by doc id")
box(cols["rules"], ROW, W, H, "Eligibility & Rules", "cited rule corpus")
box(cols["comp"], ROW, W, H, "Computation", "every number from MCP")
box(cols["review"], ROW, W, H, "Review / Audit", "independent checks")
box(cols["asm"], ROW, W, H, "Return Assembly", "provenance gate + PDF")

top, bot = HUB_Y - 0.42, ROW + H / 2 + 0.02
arrow((cols["extract"], top), (cols["extract"], bot + 0.12), ACCENT, "--")
label(cols["extract"], (top + bot) / 2, "docs queued", ACCENT)
arrow((cols["extract"] + W / 2 + 0.1, ROW), (cols["aggregate"] - W / 2, ROW), ACCENT, lw=1.6)
arrow((cols["aggregate"], bot), (cols["aggregate"], top), GREY)
spoke(cols["rules"], top, bot, "facts changed")
spoke(cols["comp"], top, bot, "calc stale")
spoke(cols["review"], top, bot, "audit due")
spoke(cols["asm"], top, bot, "assemble")

# bounded review cycle
arrow((cols["review"] - 0.3, ROW - H / 2), (cols["comp"] + 0.3, ROW - H / 2), HUMAN, rad=-0.45, lw=1.8)
label(9.05, 1.52, "revise (max 3 passes)", HUMAN)

# MCP server
box(8.1, 0.55, 5.6, 0.62, "MCP tax-tool server (stdio)", "14 deterministic Decimal tools; every call has a call id",
    TOOL, TFILL)
for x in (cols["rules"], cols["comp"], cols["review"]):
    arrow((x, ROW - H / 2), (x if x == cols["comp"] else (x + 8.1) / 2, 0.88), TOOL, lw=1.4)
label(5.85, 1.45, "compare_amounts", TOOL)
label(7.45, 1.2, "32 calls per return", TOOL)
label(10.75, 1.2, "verify_return", TOOL)

ax.text(0.3, 1.05, "Persistence: SQLite checkpointer, one thread per case\n(pause on Tuesday, resume on Friday; "
        "survives restarts)", fontsize=8.2, color=INK, va="center")
ax.text(0.3, 0.35, "Loop guard: max 30 automated hand-offs per run, or 4 repeats\nof the same routing signature "
        "-> stop and escalate to a person", fontsize=8.2, color=INK, va="center")
fig.tight_layout()
out = ROOT / "docs" / "graph.png"
fig.savefig(out)
print(f"wrote {out.relative_to(ROOT)}")
