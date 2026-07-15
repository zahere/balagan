"""Deterministic synthetic claims with objective ground truth.

Why synthetic? Two reasons:
1. Reproducibility — the dataset regenerates byte-identically from a seed,
   with zero downloads and zero licensing questions.
2. Methodology — for a *fault-tolerance* benchmark the task must be one that
   agents reliably solve in the fault-free condition, so that accuracy loss
   under faults is attributable to the fault model, not task difficulty.

Each claim is a natural-language statement that is objectively TRUE or FALSE.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

WORDS = [
    "chaos",
    "balagan",
    "resilience",
    "topology",
    "byzantine",
    "quorum",
    "gossip",
    "consensus",
    "mesh",
    "orchestra",
    "fault",
    "protocol",
]


def _arith_sum(rng: random.Random) -> tuple[str, bool]:
    a, b = rng.randint(102, 987), rng.randint(102, 987)
    truth = rng.random() < 0.5
    shown = a + b if truth else a + b + rng.choice([-30, -20, -10, 10, 20, 30])
    return f"The sum of {a} and {b} is {shown}.", truth


def _arith_product(rng: random.Random) -> tuple[str, bool]:
    a, b = rng.randint(12, 39), rng.randint(12, 39)
    truth = rng.random() < 0.5
    shown = a * b if truth else a * b + rng.choice([-24, -12, 12, 24, 36])
    return f"{a} multiplied by {b} equals {shown}.", truth


def _compare(rng: random.Random) -> tuple[str, bool]:
    a, b = rng.sample(range(1000, 9999), 2)
    truth = rng.random() < 0.5
    hi, lo = max(a, b), min(a, b)
    if truth:
        return f"{hi} is greater than {lo}.", True
    return f"{lo} is greater than {hi}.", False


def _letter_count(rng: random.Random) -> tuple[str, bool]:
    word = rng.choice(WORDS)
    letter = rng.choice(sorted(set(word)))
    true_n = word.count(letter)
    truth = rng.random() < 0.5
    shown = true_n if truth else true_n + rng.choice([1, 2])
    return (
        f"The letter '{letter}' appears exactly {shown} time(s) in the word '{word}'.",
        truth,
    )


GENERATORS = {
    "arith_sum": _arith_sum,
    "arith_product": _arith_product,
    "compare": _compare,
    # Tokenization-hostile for small models: including it drags the fault-free
    # baseline off the ceiling, which would confound fault effects with task
    # difficulty. Opt in deliberately, as a harder task tier.
    "letter_count": _letter_count,
}

DEFAULT_GENERATORS = ["arith_sum", "arith_product", "compare"]


def generate(n: int, seed: int, generators: list[str] | None = None) -> list[dict]:
    names = generators or DEFAULT_GENERATORS
    unknown = set(names) - set(GENERATORS)
    if unknown:
        raise ValueError(f"Unknown claim generators: {sorted(unknown)}")
    rng = random.Random(seed)
    claims = []
    for i in range(n):
        gen = GENERATORS[names[i % len(names)]]
        text, label = gen(rng)
        claims.append({"id": f"c{i:03d}", "claim": text, "label": label})
    return claims


def save_jsonl(claims: list[dict], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        for c in claims:
            f.write(json.dumps(c) + "\n")


def load_jsonl(path: str | Path) -> list[dict]:
    claims = []
    with Path(path).open() as f:
        for line in f:
            line = line.strip()
            if line:
                claims.append(json.loads(line))
    if not claims:
        raise ValueError(f"No claims found in {path}")
    return claims
