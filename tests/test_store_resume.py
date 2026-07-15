"""The behavior the whole harness rests on: a cancelled job resumes.

Uses moto to exercise the real S3 API surface, because the Nebius job VM's
local filesystem does not survive a cancellation — Object Storage is the
checkpoint of record.
"""

import asyncio

import boto3
import pytest
from moto import mock_aws

from balagan.config import Config
from balagan.runner import run_sweep
from balagan.store import make_store

BUCKET = "balagan-test"


@pytest.fixture
def s3_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-north1")
    with mock_aws():
        boto3.client("s3", region_name="eu-north1").create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "eu-north1"},
        )
        yield


def _cfg(tmp_path):
    return Config(
        run_name="test",
        trials_per_cell=4,
        claims_file="data/claims_demo.jsonl",
        s3_bucket=BUCKET,
        s3_prefix="balagan",
        s3_region="eu-north1",
        results_dir=str(tmp_path),
    )


def test_cancelled_job_resumes_without_losing_or_duplicating_trials(s3_env, tmp_path):
    cfg = _cfg(tmp_path)
    total = len(cfg.topologies) * len(cfg.faults) * cfg.trials_per_cell

    # 1. Job runs partway, then is cancelled.
    asyncio.run(run_sweep(cfg, mock=True, limit=15))
    assert len(make_store(cfg).done()) == 15

    # 2. Identical spec resubmitted onto a fresh VM: only S3 carries state.
    asyncio.run(run_sweep(cfg, mock=True))

    # 3. Every trial present exactly once.
    rows = make_store(cfg).fetch_all()
    assert len(rows) == total
    assert len({r["trial_id"] for r in rows}) == total


def test_rerun_is_idempotent(s3_env, tmp_path):
    cfg = _cfg(tmp_path)
    asyncio.run(run_sweep(cfg, mock=True))
    before = len(make_store(cfg).done())
    asyncio.run(run_sweep(cfg, mock=True))
    assert len(make_store(cfg).done()) == before
