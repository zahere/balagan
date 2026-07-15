"""Checkpointed experiment sweep.

Operational behavior (this is the part the harness itself is proud of):

- Each finished trial is written immediately to the trial store as its own
  object (see store.py). On Nebius that store is Object Storage, NOT the job's
  local disk — the job VM's filesystem dies with the job.
- On (re)start, completed trial IDs are listed and skipped — cancel the job at
  any point, resubmit the same spec, and the sweep resumes where it died.
- A semaphore bounds concurrency; every endpoint call carries exponential
  backoff retry (see llm.py).
- A failing trial records an error row and never takes the sweep down.
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
import time

from balagan.claims import load_jsonl
from balagan.config import Config
from balagan.faults import apply_fault, make_roster
from balagan.llm import make_client
from balagan.store import make_store
from balagan.topology import PROTOCOLS


@dataclasses.dataclass
class Trial:
    id: str
    topology: str
    fault: str
    claim: dict


def build_trials(cfg: Config, claims: list[dict]) -> list[Trial]:
    trials = []
    for topo in cfg.topologies:
        for fault in cfg.faults:
            for i in range(cfg.trials_per_cell):
                claim = claims[i % len(claims)]
                trials.append(
                    Trial(
                        id=f"{topo}__{fault}__{i:03d}",
                        topology=topo,
                        fault=fault,
                        claim=claim,
                    )
                )
    return trials


async def run_sweep(cfg: Config, mock: bool = False, limit: int | None = None) -> dict:
    claims = load_jsonl(cfg.claims_file)
    trials = build_trials(cfg, claims)
    if limit:
        trials = trials[:limit]

    if any(str(t).startswith("lg-") for t in cfg.topologies):
        try:
            from balagan import adapters  # noqa: F401 — registers lg-* protocols
        except ImportError as err:
            raise SystemExit(
                "lg-* topologies need the LangGraph extra: pip install 'balagan[langgraph]'"
            ) from err

    store = make_store(cfg)
    done = store.done()
    todo = [t for t in trials if t.id not in done]
    print(f"[balagan] checkpoint store: {store.describe()}", flush=True)
    print(
        f"[balagan] run '{cfg.run_name}': {len(trials)} trials total | "
        f"resume: {len(done)} already complete | {len(todo)} to run | "
        f"mode: {'MOCK' if mock else 'endpoint'}",
        flush=True,
    )

    client = make_client(cfg, mock=mock)
    sem = asyncio.Semaphore(cfg.concurrency)
    write_lock = asyncio.Lock()
    completed = 0
    t_start = time.monotonic()

    async def one(trial: Trial) -> None:
        nonlocal completed
        async with sem:
            rng = random.Random(f"{cfg.seed}:{trial.id}")
            roster = make_roster(cfg.n_agents)
            victim = apply_fault(roster, trial.fault, rng)
            t0 = time.monotonic()
            row = {
                "trial_id": trial.id,
                "topology": trial.topology,
                "fault": trial.fault,
                "claim_id": trial.claim["id"],
                "label": trial.claim["label"],
                "victim": victim,
            }
            try:
                proto = PROTOCOLS[trial.topology]
                result = await proto(client, trial.claim, roster)
                row.update(
                    {
                        "decision": result.decision,
                        "correct": result.decision == trial.claim["label"],
                        "llm_calls": result.llm_calls,
                        "tokens": result.tokens,
                        "latency_s": round(time.monotonic() - t0, 3),
                        "error": None,
                    }
                )
            except Exception as err:  # noqa: BLE001 — isolate trial failures
                row.update(
                    {
                        "decision": None,
                        "correct": False,
                        "llm_calls": 0,
                        "tokens": 0,
                        "latency_s": round(time.monotonic() - t0, 3),
                        "error": str(err)[:500],
                    }
                )
            async with write_lock:
                store.put(row)
                completed += 1
                if completed % 10 == 0 or completed == len(todo):
                    print(
                        f"[balagan] {completed}/{len(todo)} trials done "
                        f"({time.monotonic() - t_start:.0f}s elapsed)",
                        flush=True,
                    )

    await asyncio.gather(*[one(t) for t in todo])

    elapsed = time.monotonic() - t_start
    print(
        f"[balagan] sweep complete: {completed} new trials in {elapsed:.0f}s. "
        f"Checkpoint: {store.describe()}",
        flush=True,
    )
    return {"completed": completed, "elapsed_s": elapsed, "store": store.describe()}
