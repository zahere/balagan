"""Run configuration, loaded from YAML with sane defaults."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import yaml


@dataclasses.dataclass
class Config:
    run_name: str = "demo"

    # --- Model / endpoint (an OpenAI-compatible vLLM Serverless Endpoint) ---
    model: str = "Qwen/Qwen2.5-7B-Instruct"
    endpoint_env: str = "NEBIUS_ENDPOINT_URL"  # e.g. http://<endpoint-ip>/v1
    api_key_env: str = "NEBIUS_API_KEY"  # the endpoint's --token value

    # --- Experiment matrix ---
    n_agents: int = 5
    topologies: list[str] = dataclasses.field(
        default_factory=lambda: ["flat", "hierarchical", "ring"]
    )
    faults: list[str] = dataclasses.field(
        default_factory=lambda: ["none", "crash", "byzantine"]
    )
    trials_per_cell: int = 8

    # --- Task ---
    # Generators are deliberately arithmetic/comparison only by default.
    # 'letter_count' is tokenization-hostile for small models and would drag
    # the fault-free baseline off the ceiling — which breaks the methodology
    # (degradation must be attributable to the FAULT, not to task difficulty).
    # Opt into it only if your model handles it: it becomes a harder task tier.
    claim_generators: list[str] = dataclasses.field(
        default_factory=lambda: ["arith_sum", "arith_product", "compare"]
    )
    claims_file: str = "data/claims_demo.jsonl"

    # --- Checkpoint store ---
    # On Nebius Serverless, ALWAYS set a bucket: the job VM's filesystem is
    # ephemeral and a local checkpoint dies with the job.
    s3_bucket: str = ""  # or env S3_BUCKET
    s3_prefix: str = "balagan"  # or env S3_PREFIX
    s3_endpoint_url: str = (
        ""  # or env S3_ENDPOINT_URL, e.g. https://storage.eu-north1.nebius.cloud:443
    )
    s3_region: str = ""  # or env AWS_DEFAULT_REGION, e.g. eu-north1
    results_dir: str = "results"  # local fallback + report output

    # --- Execution ---
    concurrency: int = 8
    seed: int = 7
    temperature: float = 0.0
    max_tokens: int = 220
    max_retries: int = 4

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        return cls(**raw)

    @property
    def report_dir(self) -> Path:
        return Path(self.results_dir) / self.run_name
