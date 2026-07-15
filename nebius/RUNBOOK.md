# Running Balagan on Nebius Serverless

Zero to published heatmap. Commands follow the patterns in the
[Nebius Serverless AI Cookbook](https://github.com/nebius/serverless-ai-cookbook)
(`quickstarts/first-job`, `quickstarts/first-endpoint`, `inference/vllm-endpoint`).

## 0. Prerequisites

- [Nebius CLI installed](https://docs.nebius.com/cli/install) and [configured](https://docs.nebius.com/cli/configure); `jq` available
- Quota (Administration -> Limits -> Quotas):
  - **Compute -> Number of virtual machines** (both the job and the endpoint need one)
  - **VPC -> Total number of allocations** (the public endpoint needs one)
- An **Object Storage bucket** + access key — [quickstart](https://docs.nebius.com/object-storage/quickstart), [AWS CLI interface](https://docs.nebius.com/object-storage/interfaces/aws-cli)
- A container registry you can push to (Docker Hub is fine)

### Why the bucket is not optional

A Serverless Job's local filesystem is released when the job VM goes away. A
checkpoint on local disk survives a crash *inside the process* but **not a job
cancellation** — which is the exact failure this harness is built to survive.
Object Storage is the checkpoint of record. Every trial is written as its own
object (S3 has no append), so resume is a LIST, and re-running a trial
overwrites only itself.

Create the bucket from the CLI if you don't have one (pattern from the cookbook's
`train-and-serve`):

```bash
nebius storage bucket create --name <globally-unique-name> \
  --format jsonpath='{.metadata.id}'
```

```bash
export AWS_ACCESS_KEY_ID="<object-storage-access-key>"
export AWS_SECRET_ACCESS_KEY="<object-storage-secret>"
export AWS_DEFAULT_REGION="eu-north1"
export S3_ENDPOINT_URL="https://storage.eu-north1.nebius.cloud:443"
export S3_BUCKET="<your-bucket>"
export S3_PREFIX="balagan"
```

## 1. Serve the model — Serverless Endpoint (GPU)

```bash
./nebius/1_deploy_endpoint.sh          # vLLM + Qwen2.5-7B-Instruct on gpu-l40s-a
source nebius/endpoint.env             # exports NEBIUS_ENDPOINT_URL + NEBIUS_API_KEY
```

Wait for the model to download (`nebius ai endpoint logs $ENDPOINT_ID --follow`), then:

```bash
curl -sS "$NEBIUS_ENDPOINT_URL/models" -H "Authorization: Bearer $NEBIUS_API_KEY" | jq
```

📸 **Evidence:** endpoint page in the console (URL visible) + this curl output.

> Tight on GPU quota? A smaller model still exercises the whole harness — but
> check the fault-free baseline first (step 4). The methodology needs baseline
> accuracy near the ceiling, or fault effects get confounded with task difficulty.

## 2. Build and push the sweep image

```bash
export IMAGE=docker.io/<your-user>/balagan:0.1.0
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

After the first push, prefer pinning by digest in job submissions
(`docker.io/<you>/balagan@sha256:...`) — the developer guide's recommendation,
and it makes the published run bit-exact.

> **If the vLLM endpoint later fails with `ERROR` and no container logs:** the
> multi-GB image pull exceeded the cold-start window. Mirror the image into your
> in-region **Nebius Container Registry** (`cr.<region>.nebius.cloud/...`) and
> deploy from there — the exact workaround documented in the cookbook's
> `nim-endpoint` example. Expect 8–12 min cold start for large images even when
> it works.

## 3. Smoke test — 10 trials (before anything else)

```bash
./nebius/2_run_job.sh "run --config configs/demo.yaml --limit 10"
nebius ai logs <JOB_ID> --follow
```

The job is **CPU-only** (`cpu-d3` / `4vcpu-16gb`) — the GPU work happens on the
endpoint. Cheapest way to catch endpoint auth, S3 credentials, and image
problems before spending GPU minutes.

## 4. Baseline check (methodology gate)

Run the demo profile and confirm the `none` (fault-free) row sits near the
ceiling. If it doesn't, the model is too weak for this task tier — fix that
before running `full`, or every downstream number is confounded.

```bash
./nebius/2_run_job.sh "run --config configs/demo.yaml"
./nebius/3_report.sh configs/demo.yaml
```

## 5. The full sweep — 225 trials

```bash
./nebius/2_run_job.sh                 # defaults to configs/full.yaml
```

## 6. ⭐ Kill-and-recover (record this)

Against a healthy endpoint the `full` sweep finishes in about a minute — too
fast to cancel convincingly. `configs/kill-demo.yaml` is the same 225-trial
matrix at deliberately low concurrency, sized to give you a kill window:

1. `./nebius/2_run_job.sh "run --config configs/kill-demo.yaml"`
2. Let it reach ~40% (watch progress lines in `nebius ai logs <JOB_ID> --follow`).
3. **Cancel it:** `nebius ai job delete <JOB_ID>`
4. **Resubmit the identical spec:** step 1 again, verbatim.
5. Read the log line:

```
[balagan] checkpoint store: s3://<bucket>/balagan/kill-demo/trials (endpoint=https://storage.eu-north1.nebius.cloud:443)
[balagan] run 'kill-demo': 225 trials total | resume: 93 already complete | 132 to run | mode: endpoint
```

Nothing re-ran, nothing was lost. 📸 **Evidence:** screen recording of
cancel -> resubmit -> resume line. This clip anchors the video and the blog.

## 7. Report

```bash
./nebius/3_report.sh configs/full.yaml
```

Pulls every trial object from the bucket and writes
`results/full/{results.jsonl, summary.md, heatmap.png}`. Commit those; update
the README numbers.

## 7.5 Optional patterns worth knowing

- **Preemptible sweep:** `PREEMPTIBLE=true ./nebius/2_run_job.sh`. Balagan is
  preemption-safe by construction — a preempted job resumes exactly like the
  cancelled one in step 6. This is the checkpoint design paying rent as
  economics, not just as a demo.
- **Bucket volume mounts:** jobs/endpoints can mount the bucket directly
  (`--volume "<BUCKET_ID>:/mnt/data:rw"`, per the cookbook's `train-and-serve`).
  Balagan deliberately uses the S3 API instead (atomic per-trial objects,
  portable to any S3), but mounts are handy for e.g. persisting the endpoint's
  HF model cache across restarts.
- **Emergency model fallback:** if GPU endpoint quota/startup fails outright,
  point `NEBIUS_ENDPOINT_URL` at an OpenAI-compatible **Nebius TokenFactory**
  model (key from the console; pattern: cookbook `agents/openclaw`). The sweep
  still runs entirely on Nebius via Serverless Jobs — weaker product-depth
  story, but it keeps the submission alive. Endpoint-first remains the plan.

## 8. Cost hygiene

The endpoint bills while it is up; the job bills only while it runs. Record GPU
type + endpoint hours, job runtime, and the total — those go in the README
table and the blog. Keep the endpoint alive (minimally sized) through judging:
it doubles as standing proof of execution.

```bash
nebius ai endpoint delete "$ENDPOINT_ID"   # when you are done
```
