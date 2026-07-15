"""Balagan CLI.

balagan gen-claims --n 60 --seed 7 --out data/claims_demo.jsonl
balagan run        --config configs/demo.yaml [--mock] [--limit N]
balagan report     --config configs/demo.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json

from balagan import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="balagan", description="Chaos harness for agent meshes"
    )
    parser.add_argument("--version", action="version", version=f"balagan {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser(
        "gen-claims", help="Generate the deterministic synthetic claims dataset"
    )
    g.add_argument("--n", type=int, default=60)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--out", default="data/claims_demo.jsonl")
    g.add_argument("--generators", nargs="*", default=None)

    r = sub.add_parser("run", help="Run a checkpointed sweep (resumable)")
    r.add_argument("--config", required=True)
    r.add_argument(
        "--mock",
        action="store_true",
        help="Offline deterministic mode (no endpoint, no cost)",
    )
    r.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N trials (smoke test)",
    )

    p = sub.add_parser(
        "report",
        help="Pull trials from the store; write results.jsonl, summary.md, heatmap.png",
    )
    p.add_argument("--config", required=True)
    p.add_argument("--title", default=None)

    args = parser.parse_args()

    if args.cmd == "gen-claims":
        from balagan.claims import generate, save_jsonl

        claims = generate(args.n, args.seed, args.generators)
        save_jsonl(claims, args.out)
        print(f"[balagan] wrote {len(claims)} claims -> {args.out}")

    elif args.cmd == "run":
        from balagan.config import Config
        from balagan.runner import run_sweep

        cfg = Config.from_yaml(args.config)
        asyncio.run(run_sweep(cfg, mock=args.mock, limit=args.limit))

    elif args.cmd == "report":
        from balagan.config import Config
        from balagan.report import write_report
        from balagan.store import make_store

        cfg = Config.from_yaml(args.config)
        store = make_store(cfg)
        rows = store.fetch_all()
        src_desc = store.describe()
        if not rows:
            # No live store (e.g. a fresh clone): fall back to the committed
            # flattened results so anyone can regenerate every chart offline.
            committed = cfg.report_dir / "results.jsonl"
            if committed.exists():
                from balagan.report import load_rows

                rows = load_rows(committed)
                src_desc = str(committed)
                print(f"[balagan] store empty; using committed {committed}")
            else:
                raise SystemExit(f"[balagan] no trials found in {store.describe()}")

        out_dir = cfg.report_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        jsonl = out_dir / "results.jsonl"
        with jsonl.open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        print(f"[balagan] pulled {len(rows)} trials from {src_desc} -> {jsonl}")

        title = args.title or f"Balagan v0.1 — {cfg.run_name} ({cfg.model})"
        md, pngs = write_report(rows, out_dir, title)
        print("[balagan] wrote " + ", ".join(str(x) for x in [md, *pngs]))


if __name__ == "__main__":
    main()
