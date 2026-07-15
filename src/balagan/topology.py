"""Mesh topologies as message-passing protocols.

Each protocol takes a claim and a (possibly fault-injected) roster, runs its
message-passing pattern against the LLM client, and returns a collective
decision plus call statistics.

- flat:          all-to-all debate. Round 1 independent takes, round 2 each
                 agent revises after reading everyone else, decision by
                 strict majority of final verdicts.
- hierarchical:  star. Workers answer independently; a single aggregator
                 reads all worker answers and issues the final verdict. The
                 aggregator is a deliberate single point of failure.
- ring:          sequential refinement. Each agent sees only its predecessor's
                 message; the last live agent's verdict is the decision.
"""

from __future__ import annotations

import dataclasses

from balagan.faults import Agent
from balagan.scoring import majority, parse_verdict


@dataclasses.dataclass
class ProtocolResult:
    decision: bool | None
    llm_calls: int = 0
    tokens: int = 0


def _meta(claim: dict, agent: Agent, turn: str) -> dict:
    return {
        "claim_id": claim["id"],
        "label": claim["label"],
        "agent_id": agent.idx,
        "role": agent.role,
        "turn": turn,
    }


async def run_flat(client, claim: dict, roster: list[Agent]) -> ProtocolResult:
    n = len(roster)
    live = [a for a in roster if a.alive]
    res = ProtocolResult(decision=None)
    if not live:
        return res

    # Round 1 — independent analyses (concurrent).
    import asyncio

    prompt1 = (
        f'Claim: "{claim["claim"]}"\n\n'
        "Round 1: give your independent analysis and verdict."
    )
    r1 = await asyncio.gather(
        *[client.complete(a.system(n), prompt1, _meta(claim, a, "r1")) for a in live]
    )
    res.llm_calls += len(r1)
    res.tokens += sum(r.tokens for r in r1)

    # Round 2 — each live agent reads all other round-1 statements, then
    # issues a final verdict (concurrent).
    async def revise(i: int, agent: Agent):
        others = "\n\n".join(
            f"Agent {b.idx} said: {r1[j].text}" for j, b in enumerate(live) if j != i
        )
        prompt2 = (
            f'Claim: "{claim["claim"]}"\n\n'
            f"Round 1 statements from the other agents:\n{others}\n\n"
            "Round 2: weigh their arguments against your own analysis and give "
            "your FINAL verdict."
        )
        return await client.complete(
            agent.system(n), prompt2, _meta(claim, agent, "r2")
        )

    r2 = await asyncio.gather(*[revise(i, a) for i, a in enumerate(live)])
    res.llm_calls += len(r2)
    res.tokens += sum(r.tokens for r in r2)

    res.decision = majority([parse_verdict(r.text) for r in r2])
    return res


async def run_hierarchical(client, claim: dict, roster: list[Agent]) -> ProtocolResult:
    n = len(roster)
    res = ProtocolResult(decision=None)
    workers = [a for a in roster[:-1] if a.alive]
    leader = roster[-1]

    import asyncio

    prompt = (
        f'Claim: "{claim["claim"]}"\n\n'
        "You are a worker agent. Give your independent analysis and verdict."
    )
    answers = await asyncio.gather(
        *[
            client.complete(a.system(n), prompt, _meta(claim, a, "worker"))
            for a in workers
        ]
    )
    res.llm_calls += len(answers)
    res.tokens += sum(r.tokens for r in answers)

    if not leader.alive:
        # The single point of failure fired: no aggregator, no decision.
        return res

    joined = (
        "\n\n".join(f"Worker {a.idx} said: {r.text}" for a, r in zip(workers, answers))
        or "(no worker answers were received)"
    )
    agg_prompt = (
        f'Claim: "{claim["claim"]}"\n\n'
        f"You are the aggregator. Worker reports:\n{joined}\n\n"
        "Weigh the reports, verify the reasoning yourself, and give the "
        "panel's FINAL verdict."
    )
    final = await client.complete(
        leader.system(n), agg_prompt, _meta(claim, leader, "agg")
    )
    res.llm_calls += 1
    res.tokens += final.tokens
    res.decision = parse_verdict(final.text)
    return res


async def run_ring(client, claim: dict, roster: list[Agent]) -> ProtocolResult:
    n = len(roster)
    res = ProtocolResult(decision=None)
    chain = [a for a in roster if a.alive]
    if not chain:
        return res

    prev_text: str | None = None
    last_text: str | None = None
    for agent in chain:
        if prev_text is None:
            prompt = (
                f'Claim: "{claim["claim"]}"\n\n'
                "You are the first agent in a relay. Give your analysis and verdict."
            )
        else:
            prompt = (
                f'Claim: "{claim["claim"]}"\n\n'
                f"The previous agent's message:\n{prev_text}\n\n"
                "Refine or correct their reasoning, then give your verdict."
            )
        out = await client.complete(
            agent.system(n), prompt, _meta(claim, agent, "ring")
        )
        res.llm_calls += 1
        res.tokens += out.tokens
        prev_text = out.text
        last_text = out.text

    res.decision = parse_verdict(last_text)
    return res


PROTOCOLS = {
    "flat": run_flat,
    "hierarchical": run_hierarchical,
    "ring": run_ring,
}
