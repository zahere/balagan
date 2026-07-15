"""Aggregate results into the resilience matrix, a markdown summary, and the
topology x fault-model heatmap."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

FAULT_ORDER = ["none", "crash", "byzantine"]


def load_rows(path: str | Path) -> list[dict]:
    rows = []
    with Path(path).open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        raise ValueError(f"No result rows in {path}")
    return rows


def build_matrix(rows: list[dict]):
    cells = defaultdict(list)
    for r in rows:
        cells[(r["topology"], r["fault"])].append(bool(r.get("correct")))
    topologies = sorted({t for t, _ in cells})
    faults = [f for f in FAULT_ORDER if any(k[1] == f for k in cells)]
    faults += sorted({k[1] for k in cells} - set(faults))
    acc = {(t, f): (sum(v) / len(v), len(v)) for (t, f), v in cells.items()}
    return topologies, faults, acc


def markdown_summary(rows: list[dict]) -> str:
    topologies, faults, acc = build_matrix(rows)
    n_err = sum(1 for r in rows if r.get("error"))
    calls = sum(r.get("llm_calls", 0) for r in rows)
    tokens = sum(r.get("tokens", 0) for r in rows)

    lines = ["# Balagan resilience summary", ""]
    header = "| Topology | " + " | ".join(faults) + " |"
    sep = "|" + "---|" * (len(faults) + 1)
    lines += [header, sep]
    for t in topologies:
        cells = []
        for f in faults:
            if (t, f) in acc:
                a, n = acc[(t, f)]
                cells.append(f"{a:.0%} (n={n})")
            else:
                cells.append("—")
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    lines += [
        "",
        f"- Trials: {len(rows)} | trial-level errors: {n_err}",
        f"- LLM calls: {calls} | total tokens: {tokens}",
        "",
        "Accuracy = share of trials where the mesh's collective decision "
        "matched ground truth. An undecided mesh scores as incorrect.",
    ]
    return "\n".join(lines)


def heatmap(rows: list[dict], out_png: str | Path, title: str) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    topologies, faults, acc = build_matrix(rows)
    data = [[acc.get((t, f), (float("nan"), 0))[0] for f in faults] for t in topologies]

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    im = ax.imshow(data, cmap="RdYlGn", vmin=0.0, vmax=1.0, aspect="auto")
    ax.set_xticks(range(len(faults)), labels=[f.capitalize() for f in faults])
    ax.set_yticks(range(len(topologies)), labels=[t.capitalize() for t in topologies])
    ax.set_xlabel("Fault model")
    ax.set_ylabel("Topology")
    ax.set_title(title)
    for i, t in enumerate(topologies):
        for j, f in enumerate(faults):
            if (t, f) in acc:
                a, n = acc[(t, f)]
                ax.text(
                    j,
                    i,
                    f"{a:.0%}\nn={n}",
                    ha="center",
                    va="center",
                    fontsize=10,
                    color="black",
                )
    fig.colorbar(im, ax=ax, label="Decision accuracy")
    fig.tight_layout()
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


FAULT_COLORS = {"none": "#4caf50", "crash": "#fb8c00", "byzantine": "#e53935"}


def latency_chart(rows: list[dict], out_png: str | Path) -> Path | None:
    """Per-cell trial-latency boxplots. Skipped for mock data (latency ~ 0)."""
    lats: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r.get("latency_s"):
            lats[(r["topology"], r["fault"])].append(r["latency_s"])
    if not lats or max(max(v) for v in lats.values()) < 0.05:
        return None

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    topologies, faults, _ = build_matrix(rows)
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    for ti, t in enumerate(topologies):
        for fi, f in enumerate(faults):
            data = lats.get((t, f))
            if not data:
                continue
            pos = ti * (len(faults) + 1) + fi
            bp = ax.boxplot(
                data, positions=[pos], widths=0.75, patch_artist=True, showfliers=False
            )
            bp["boxes"][0].set_facecolor(FAULT_COLORS.get(f, "#90a4ae"))
            bp["boxes"][0].set_alpha(0.85)
    centers = [
        ti * (len(faults) + 1) + (len(faults) - 1) / 2 for ti in range(len(topologies))
    ]
    ax.set_xticks(centers, labels=[t.capitalize() for t in topologies])
    ax.set_ylabel("Trial latency (s)")
    ax.set_title("Consensus latency under fault")
    ax.legend(
        handles=[
            Patch(facecolor=FAULT_COLORS[f], label=f.capitalize())
            for f in faults
            if f in FAULT_COLORS
        ],
        frameon=False,
        ncols=len(faults),
        loc="upper left",
    )
    fig.tight_layout()
    out = Path(out_png)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def price_chart(rows: list[dict], out_png: str | Path) -> Path | None:
    """The price of resilience: tokens/trial vs accuracy, baseline -> worst fault.

    One vertical drop-line per topology: hollow circle = fault-free accuracy,
    filled square = worst-case accuracy under fault. Distance fallen = fragility;
    x position = what you pay per decision.
    """
    topologies, faults, acc = build_matrix(rows)
    fault_faults = [f for f in faults if f != "none"]
    if "none" not in faults or not fault_faults:
        return None
    tok: dict[str, list] = defaultdict(list)
    for r in rows:
        tok[r["topology"]].append(r.get("tokens", 0))
    if not any(sum(v) for v in tok.values()):
        return None

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for t in topologies:
        x = sum(tok[t]) / max(len(tok[t]), 1)
        base = acc.get((t, "none"), (None, 0))[0]
        worst_f, worst = min(
            ((f, acc[(t, f)][0]) for f in fault_faults if (t, f) in acc),
            key=lambda kv: kv[1],
        )
        ax.plot([x, x], [base, worst], color="#90a4ae", lw=1.5, zorder=1)
        ax.scatter(
            [x], [base], s=70, facecolors="none", edgecolors="#1565c0", lw=2, zorder=2
        )
        ax.scatter([x], [worst], s=70, marker="s", color="#e53935", zorder=2)
        ax.annotate(
            f"{t}\n(worst: {worst_f})",
            (x, worst),
            textcoords="offset points",
            xytext=(10, -4),
            fontsize=9,
        )
    ax.set_xlabel("Tokens per trial (cost proxy)")
    ax.set_ylabel("Decision accuracy")
    ax.set_ylim(0.45, 1.04)
    ax.set_title("The price of resilience — cost vs worst-case accuracy")
    ax.scatter(
        [], [], facecolors="none", edgecolors="#1565c0", lw=2, label="fault-free"
    )
    ax.scatter([], [], marker="s", color="#e53935", label="worst fault")
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    out = Path(out_png)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def write_report(
    rows: list[dict], out_dir: str | Path, title: str
) -> tuple[Path, list[Path]]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "summary.md"
    md_path.write_text(markdown_summary(rows) + "\n")
    pngs = [heatmap(rows, out_dir / "heatmap.png", title)]
    lat = latency_chart(rows, out_dir / "latency_under_fault.png")
    if lat:
        pngs.append(lat)
    price = price_chart(rows, out_dir / "price_of_resilience.png")
    if price:
        pngs.append(price)
    return md_path, pngs
