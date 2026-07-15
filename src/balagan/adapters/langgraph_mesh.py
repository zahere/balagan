"""LangGraph adapter — chaos-test a *compiled LangGraph* instead of the
hand-rolled asyncio mesh.

Why this exists: Balagan's fault models inject at the *agent* level (a crashed
agent is silent; a Byzantine agent gets a saboteur system prompt), so nothing
about them is specific to how the mesh is wired. This module proves it by
expressing the same three topologies as LangGraph ``StateGraph``s — parallel
fan-out/fan-in supersteps, reducer-merged state, one compiled graph per trial
— while reusing Balagan's client, fault injector, and scoring unchanged.

Mapping to graphs you may already run in production:

- supervisor / orchestrator pattern  ->  ``lg-hierarchical``
- sequential chain / pipeline        ->  ``lg-ring``
- debate / swarm with a vote         ->  ``lg-flat``

Enable with ``pip install -e ".[langgraph]"`` and list ``lg-*`` names in the
config's ``topologies``. Registered on import (see ``balagan.adapters``).
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from balagan.faults import Agent
from balagan.scoring import majority, parse_verdict
from balagan.topology import PROTOCOLS, ProtocolResult, _meta


class _FlatState(TypedDict):
    r1: Annotated[list, operator.add]
    r2: Annotated[list, operator.add]
    calls: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]


async def run_lg_flat(client, claim: dict, roster: list[Agent]) -> ProtocolResult:
    n = len(roster)
    live = [a for a in roster if a.alive]
    if not live:
        return ProtocolResult(decision=None)

    g = StateGraph(_FlatState)

    def make_r1(agent: Agent):
        async def node(state: _FlatState):
            prompt = (
                f'Claim: "{claim["claim"]}"\n\n'
                "Round 1: give your independent analysis and verdict."
            )
            out = await client.complete(
                agent.system(n), prompt, _meta(claim, agent, "r1")
            )
            return {"r1": [(agent.idx, out.text)], "calls": 1, "tokens": out.tokens}

        return node

    def make_r2(agent: Agent):
        async def node(state: _FlatState):
            others = "\n\n".join(
                f"Agent {j} said: {txt}"
                for j, txt in sorted(state["r1"])
                if j != agent.idx
            )
            prompt = (
                f'Claim: "{claim["claim"]}"\n\n'
                f"Round 1 statements from the other agents:\n{others}\n\n"
                "Round 2: weigh their arguments against your own analysis and give "
                "your FINAL verdict."
            )
            out = await client.complete(
                agent.system(n), prompt, _meta(claim, agent, "r2")
            )
            return {"r2": [(agent.idx, out.text)], "calls": 1, "tokens": out.tokens}

        return node

    async def barrier(state: _FlatState):
        return {}

    g.add_node("barrier", barrier)
    for a in live:
        g.add_node(f"r1_{a.idx}", make_r1(a))
        g.add_edge(START, f"r1_{a.idx}")
        g.add_edge(f"r1_{a.idx}", "barrier")
        g.add_node(f"r2_{a.idx}", make_r2(a))
        g.add_edge("barrier", f"r2_{a.idx}")
        g.add_edge(f"r2_{a.idx}", END)

    out = await g.compile().ainvoke({"r1": [], "r2": [], "calls": 0, "tokens": 0})
    decision = majority([parse_verdict(txt) for _, txt in out["r2"]])
    return ProtocolResult(
        decision=decision, llm_calls=out["calls"], tokens=out["tokens"]
    )


class _HierState(TypedDict):
    answers: Annotated[list, operator.add]
    final: str
    calls: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]


async def run_lg_hierarchical(
    client, claim: dict, roster: list[Agent]
) -> ProtocolResult:
    n = len(roster)
    workers = [a for a in roster[:-1] if a.alive]
    leader = roster[-1]

    g = StateGraph(_HierState)

    def make_worker(agent: Agent):
        async def node(state: _HierState):
            prompt = (
                f'Claim: "{claim["claim"]}"\n\n'
                "You are a worker agent. Give your independent analysis and verdict."
            )
            out = await client.complete(
                agent.system(n), prompt, _meta(claim, agent, "worker")
            )
            return {
                "answers": [(agent.idx, out.text)],
                "calls": 1,
                "tokens": out.tokens,
            }

        return node

    async def aggregate(state: _HierState):
        joined = (
            "\n\n".join(
                f"Worker {j} said: {txt}" for j, txt in sorted(state["answers"])
            )
            or "(no worker answers were received)"
        )
        prompt = (
            f'Claim: "{claim["claim"]}"\n\n'
            f"You are the aggregator. Worker reports:\n{joined}\n\n"
            "Weigh the reports, verify the reasoning yourself, and give the "
            "panel's FINAL verdict."
        )
        out = await client.complete(
            leader.system(n), prompt, _meta(claim, leader, "agg")
        )
        return {"final": out.text, "calls": 1, "tokens": out.tokens}

    for a in workers:
        g.add_node(f"w_{a.idx}", make_worker(a))
        g.add_edge(START, f"w_{a.idx}")

    if leader.alive:
        g.add_node("aggregate", aggregate)
        if workers:
            for a in workers:
                g.add_edge(f"w_{a.idx}", "aggregate")
        else:
            g.add_edge(START, "aggregate")
        g.add_edge("aggregate", END)
    else:
        # The single point of failure fired: workers still burn tokens,
        # but there is nobody to decide — same semantics as the core protocol.
        if not workers:
            return ProtocolResult(decision=None)
        for a in workers:
            g.add_edge(f"w_{a.idx}", END)

    out = await g.compile().ainvoke(
        {"answers": [], "final": "", "calls": 0, "tokens": 0}
    )
    decision = parse_verdict(out["final"]) if leader.alive else None
    return ProtocolResult(
        decision=decision, llm_calls=out["calls"], tokens=out["tokens"]
    )


class _RingState(TypedDict):
    last: str
    calls: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]


async def run_lg_ring(client, claim: dict, roster: list[Agent]) -> ProtocolResult:
    n = len(roster)
    chain = [a for a in roster if a.alive]
    if not chain:
        return ProtocolResult(decision=None)

    g = StateGraph(_RingState)

    def make_link(agent: Agent):
        async def node(state: _RingState):
            if not state["last"]:
                prompt = (
                    f'Claim: "{claim["claim"]}"\n\n'
                    "You are the first agent in a relay. Give your analysis and verdict."
                )
            else:
                prompt = (
                    f'Claim: "{claim["claim"]}"\n\n'
                    f"The previous agent's message:\n{state['last']}\n\n"
                    "Refine or correct their reasoning, then give your verdict."
                )
            out = await client.complete(
                agent.system(n), prompt, _meta(claim, agent, "ring")
            )
            return {"last": out.text, "calls": 1, "tokens": out.tokens}

        return node

    prev = START
    for a in chain:
        name = f"link_{a.idx}"
        g.add_node(name, make_link(a))
        g.add_edge(prev, name)
        prev = name
    g.add_edge(prev, END)

    out = await g.compile().ainvoke({"last": "", "calls": 0, "tokens": 0})
    return ProtocolResult(
        decision=parse_verdict(out["last"]),
        llm_calls=out["calls"],
        tokens=out["tokens"],
    )


PROTOCOLS.update(
    {
        "lg-flat": run_lg_flat,
        "lg-hierarchical": run_lg_hierarchical,
        "lg-ring": run_lg_ring,
    }
)
