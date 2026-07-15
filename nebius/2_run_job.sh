#!/usr/bin/env bash
# Submit the Balagan sweep as a Nebius Serverless AI Job.
#
# Prereqs:
#   source nebius/endpoint.env          # from 1_deploy_endpoint.sh
#   export S3_BUCKET=... S3_PREFIX=balagan S3_ENDPOINT_URL=... AWS_* ...
#   docker build -t $IMAGE . && docker push $IMAGE
#
# Usage:
#   ./nebius/2_run_job.sh                          # full sweep
#   ./nebius/2_run_job.sh "run --config configs/demo.yaml --limit 10"   # smoke test
#
# The sweep is CPU-only: the GPU work happens on the endpoint. The job's own
# filesystem is ephemeral, which is exactly why S3_* is mandatory here — the
# checkpoint must outlive the job VM for a cancelled job to resume.

set -euo pipefail

IMAGE="${IMAGE:?set IMAGE, e.g. export IMAGE=docker.io/<user>/balagan:0.1.0}"
ARGS="${1:-run --config configs/full.yaml}"

JOB_PLATFORM="${JOB_PLATFORM:-cpu-d3}"
JOB_PRESET="${JOB_PRESET:-4vcpu-16gb}"
JOB_TIMEOUT="${JOB_TIMEOUT:-2h}"
JOB_NAME="${JOB_NAME:-balagan-$(date +%Y%m%d%H%M%S)}"
SUBNET_ID="${SUBNET_ID:-}"
PARENT_ID="${PARENT_ID:-}"          # optional: multi-project tenants
PREEMPTIBLE="${PREEMPTIBLE:-false}" # safe here BY DESIGN: per-trial checkpoint
                                    # in Object Storage means a preempted job
                                    # resumes exactly like a cancelled one.

required=(NEBIUS_ENDPOINT_URL NEBIUS_API_KEY
          AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
          S3_BUCKET S3_PREFIX S3_ENDPOINT_URL)
missing=()
for v in "${required[@]}"; do
  [ -z "${!v:-}" ] && missing+=("$v")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "Missing required env vars: ${missing[*]}" >&2
  echo "Without the S3_* vars the checkpoint dies with the job VM and resume is impossible." >&2
  exit 1
fi

CREATE_CMD=(
  nebius ai job create
  --name "$JOB_NAME"
  --image "$IMAGE"
  --platform "$JOB_PLATFORM"
  --preset "$JOB_PRESET"
  --timeout "$JOB_TIMEOUT"
  --args "$ARGS"
)
for v in "${required[@]}"; do
  CREATE_CMD+=(--env "$v=${!v}")
done
[ -n "$SUBNET_ID" ] && CREATE_CMD+=(--subnet-id "$SUBNET_ID")
[ -n "$PARENT_ID" ] && CREATE_CMD+=(--parent-id "$PARENT_ID")
[ "$PREEMPTIBLE" = "true" ] && CREATE_CMD+=(--preemptible)

echo "Submitting '$JOB_NAME'  ($JOB_PLATFORM / $JOB_PRESET, preemptible=$PREEMPTIBLE)"
echo "  args:  $ARGS"
# `ai job create` prints a rich status block regardless of --format; grep the ID out.
CREATE_OUT=$("${CREATE_CMD[@]}" 2>&1) || { printf '%s\n' "$CREATE_OUT" >&2; exit 1; }
JOB_ID=$(grep -oE 'aijob-[a-z0-9]+' <<<"$CREATE_OUT" | head -1)

echo
echo "  JOB_ID=$JOB_ID"
echo "  Follow:  nebius ai logs $JOB_ID --follow"
echo "  Status:  nebius ai job get $JOB_ID"
echo "  Cancel:  nebius ai job delete $JOB_ID     <-- the kill-and-recover demo"
echo "  Resume:  re-run this exact script; watch the 'resume: N already complete' line"
