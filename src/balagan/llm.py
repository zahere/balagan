"""LLM client layer.

Two implementations behind one interface:

- EndpointClient: any OpenAI-compatible endpoint (a vLLM Serverless Endpoint
  on Nebius is exactly this). Exponential-backoff retry on every call so a
  transient endpoint hiccup never kills a sweep.
- MockClient: deterministic offline stand-in. Lets anyone verify the entire
  pipeline (topologies, fault injection, checkpointing, scoring, reporting)
  in seconds with zero cost, and lets CI run without secrets.

`meta` carries trial context (claim id, agent role, ground-truth label). The
real client ignores it entirely; only the mock uses it to simulate behavior.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import random
import time


@dataclasses.dataclass
class ChatResult:
    text: str
    tokens: int = 0
    latency_s: float = 0.0


class EndpointClient:
    def __init__(
        self,
        model: str,
        endpoint_env: str,
        api_key_env: str,
        temperature: float = 0.0,
        max_tokens: int = 220,
        max_retries: int = 4,
    ) -> None:
        from openai import AsyncOpenAI  # imported lazily so mock mode needs no key

        base_url = os.environ.get(endpoint_env)
        if not base_url:
            raise RuntimeError(
                f"Env var {endpoint_env} is not set. "
                f"Point it at your OpenAI-compatible endpoint, e.g. "
                f"https://<endpoint-host>/v1"
            )
        api_key = os.environ.get(api_key_env, "EMPTY")
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries

    async def complete(
        self, system: str, prompt: str, meta: dict | None = None
    ) -> ChatResult:
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            t0 = time.monotonic()
            try:
                resp = await self._client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                )
                text = resp.choices[0].message.content or ""
                tokens = resp.usage.total_tokens if resp.usage else 0
                return ChatResult(
                    text=text, tokens=tokens, latency_s=time.monotonic() - t0
                )
            except Exception as err:  # noqa: BLE001 — retry any transient failure
                last_err = err
                if attempt == self.max_retries - 1:
                    break
                delay = (2**attempt) + random.random()
                await asyncio.sleep(delay)
        raise RuntimeError(
            f"Endpoint call failed after {self.max_retries} attempts: {last_err}"
        )


class MockClient:
    """Deterministic simulator for offline runs (`balagan run --mock`).

    Honest agents answer correctly with probability `honest_accuracy`;
    saboteurs argue the wrong verdict with probability `saboteur_flip`.
    Numbers produced under mock mode validate the *pipeline*, never the
    research claim — real results must come from a real endpoint.
    """

    def __init__(
        self, seed: int, honest_accuracy: float = 0.9, saboteur_flip: float = 0.95
    ):
        self.seed = seed
        self.honest_accuracy = honest_accuracy
        self.saboteur_flip = saboteur_flip

    async def complete(
        self, system: str, prompt: str, meta: dict | None = None
    ) -> ChatResult:
        meta = meta or {}
        label = bool(meta.get("label", True))
        key = f"{self.seed}:{meta.get('claim_id')}:{meta.get('agent_id')}:{meta.get('turn')}"
        rng = random.Random(key)
        if meta.get("role") == "saboteur":
            verdict = (not label) if rng.random() < self.saboteur_flip else label
            body = "After careful review, the statement does not hold up."
        else:
            verdict = label if rng.random() < self.honest_accuracy else (not label)
            body = "Checked the statement step by step."
        text = f"{body} VERDICT: {'TRUE' if verdict else 'FALSE'}"
        return ChatResult(text=text, tokens=42, latency_s=0.0)


def make_client(cfg, mock: bool):
    if mock:
        return MockClient(seed=cfg.seed)
    return EndpointClient(
        model=cfg.model,
        endpoint_env=cfg.endpoint_env,
        api_key_env=cfg.api_key_env,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        max_retries=cfg.max_retries,
    )
