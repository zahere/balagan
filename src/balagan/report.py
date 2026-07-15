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


def write_report(
    rows: list[dict], out_dir: str | Path, title: str
) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "summary.md"
    md_path.write_text(markdown_summary(rows) + "\n")
    png_path = heatmap(rows, out_dir / "heatmap.png", title)
    return md_path, png_path
