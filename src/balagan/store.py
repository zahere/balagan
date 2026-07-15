"""Trial store — where checkpoints actually live.

The important lesson from running this on Nebius: **a Serverless Job's local
filesystem is ephemeral**. When the job VM is released, anything under /app is
gone. So a checkpoint written to local disk survives a *crash inside the
process*, but not a job cancellation — which is precisely the failure the
harness needs to survive.

Hence Object Storage (S3-compatible, Nebius or any other) as the checkpoint of
record, with one important design consequence:

**S3 has no append.** Rewriting one big JSONL from many concurrent writers is a
lost-update race. So each trial is written as its own small object:

    {prefix}/{run_name}/trials/{trial_id}.json

Resume is then a LIST call, and each write is atomic and idempotent. This is
not a workaround — it is the more correct design. A re-run of the same trial
overwrites its own object and nothing else.

LocalStore mirrors the same layout on disk so `--mock` and laptop runs behave
identically to the real thing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol


class TrialStore(Protocol):
    def done(self) -> set[str]: ...
    def put(self, row: dict) -> None: ...
    def fetch_all(self) -> list[dict]: ...
    def describe(self) -> str: ...


class LocalStore:
    def __init__(self, root: str | Path, run_name: str) -> None:
        self.dir = Path(root) / run_name / "trials"
        self.dir.mkdir(parents=True, exist_ok=True)

    def done(self) -> set[str]:
        return {p.stem for p in self.dir.glob("*.json")}

    def put(self, row: dict) -> None:
        # Write-then-rename: a killed process can never leave a torn file.
        tmp = self.dir / f".{row['trial_id']}.tmp"
        final = self.dir / f"{row['trial_id']}.json"
        tmp.write_text(json.dumps(row))
        tmp.replace(final)

    def fetch_all(self) -> list[dict]:
        rows = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                rows.append(json.loads(p.read_text()))
            except json.JSONDecodeError:
                continue
        return rows

    def describe(self) -> str:
        return f"local:{self.dir}"


class S3Store:
    """S3-compatible object storage (Nebius Object Storage by default).

    Credentials and endpoint come from the standard env vars that Nebius
    Serverless Jobs pass through with `--env`:

        AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION,
        S3_BUCKET, S3_PREFIX, S3_ENDPOINT_URL
    """

    def __init__(
        self,
        bucket: str,
        prefix: str,
        run_name: str,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.run_prefix = (
            f"{prefix.rstrip('/')}/{run_name}/trials"
            if prefix
            else f"{run_name}/trials"
        )
        self.endpoint_url = endpoint_url
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            config=Config(
                region_name=region, retries={"max_attempts": 5, "mode": "standard"}
            ),
        )
        # Fail fast and loudly: a silent credential problem here would look
        # exactly like "no checkpoint yet" and quietly re-run the whole sweep.
        self._s3.head_bucket(Bucket=self.bucket)

    def _key(self, trial_id: str) -> str:
        return f"{self.run_prefix}/{trial_id}.json"

    def done(self) -> set[str]:
        ids: set[str] = set()
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.run_prefix):
            for obj in page.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1]
                if name.endswith(".json"):
                    ids.add(name[: -len(".json")])
        return ids

    def put(self, row: dict) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=self._key(row["trial_id"]),
            Body=json.dumps(row).encode(),
            ContentType="application/json",
        )

    def fetch_all(self) -> list[dict]:
        rows = []
        for trial_id in sorted(self.done()):
            obj = self._s3.get_object(Bucket=self.bucket, Key=self._key(trial_id))
            rows.append(json.loads(obj["Body"].read()))
        return rows

    def describe(self) -> str:
        return f"s3://{self.bucket}/{self.run_prefix} (endpoint={self.endpoint_url})"


def make_store(cfg) -> TrialStore:
    """S3 when a bucket is configured, local otherwise.

    Explicitly: on Nebius Serverless, run WITH a bucket. Without one, the
    checkpoint dies with the job VM and resume is impossible.
    """
    bucket = os.environ.get("S3_BUCKET", cfg.s3_bucket)
    if bucket:
        return S3Store(
            bucket=bucket,
            prefix=os.environ.get("S3_PREFIX", cfg.s3_prefix),
            run_name=cfg.run_name,
            endpoint_url=os.environ.get("S3_ENDPOINT_URL", cfg.s3_endpoint_url) or None,
            region=os.environ.get("AWS_DEFAULT_REGION", cfg.s3_region) or None,
        )
    return LocalStore(cfg.results_dir, cfg.run_name)
