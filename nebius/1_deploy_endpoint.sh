#!/usr/bin/env bash
# Deploy the vLLM Serverless Endpoint that serves the agents' model.
# Follows the Nebius cookbook pattern: inference/vllm-endpoint.
#
# Usage:  ./nebius/1_deploy_endpoint.sh
# Then:   source nebius/endpoint.env   (written by this script)

set -euo pipefail

MODEL_ID="${MODEL_ID:-Qwen/Qwen2.5-7B-Instruct}"
ENDPOINT_NAME="${ENDPOINT_NAME:-balagan-vllm}"
VLLM_IMAGE="${VLLM_IMAGE:-vllm/vllm-openai:v0.18.0-cu130}"
PLATFORM="${JOB_PLATFORM:-gpu-l40s-a}"
PRESET="${JOB_PRESET:-1gpu-8vcpu-32gb}"

AUTH_TOKEN="${AUTH_TOKEN:-$(openssl rand -hex 32)}"
SUBNET_ID="${SUBNET_ID:-$(nebius vpc subnet list --format jsonpath='{.items[0].metadata.id}')}"
PARENT_ID="${PARENT_ID:-}"

echo "Deploying $MODEL_ID on $PLATFORM / $PRESET as '$ENDPOINT_NAME'..."

nebius ai endpoint create \
  --name "$ENDPOINT_NAME" \
  --image "$VLLM_IMAGE" \
  --container-command "python3 -m vllm.entrypoints.openai.api_server" \
  --args "--model $MODEL_ID --host 0.0.0.0 --port 8000" \
  --platform "$PLATFORM" \
  --preset "$PRESET" \
  --public \
  --container-port 8000 \
  --auth token \
  --token "$AUTH_TOKEN" \
  --shm-size 16Gi \
  --disk-size 450Gi \
  --subnet-id "$SUBNET_ID" \
  ${PARENT_ID:+--parent-id "$PARENT_ID"}

ENDPOINT_ID=$(nebius ai endpoint get-by-name --name "$ENDPOINT_NAME" \
  ${PARENT_ID:+--parent-id "$PARENT_ID"} \
  --format jsonpath='{.metadata.id}')

echo "Endpoint $ENDPOINT_ID created. Waiting for it to come up (model download takes a few minutes)..."
echo "  Follow with: nebius ai endpoint logs $ENDPOINT_ID --follow"

ENDPOINT_IP=""
for _ in $(seq 1 60); do
  ENDPOINT_IP=$(nebius ai endpoint get "$ENDPOINT_ID" --format json | jq -r '.status.public_endpoints[0] // empty')
  [ -n "$ENDPOINT_IP" ] && break
  sleep 10
done

if [ -z "$ENDPOINT_IP" ]; then
  echo "Endpoint IP not assigned yet. Check: nebius ai endpoint get $ENDPOINT_ID" >&2
  exit 1
fi

cat > nebius/endpoint.env <<ENVEOF
# Written by 1_deploy_endpoint.sh — DO NOT COMMIT (see .gitignore)
export ENDPOINT_ID="$ENDPOINT_ID"
export NEBIUS_ENDPOINT_URL="http://$ENDPOINT_IP/v1"
export NEBIUS_API_KEY="$AUTH_TOKEN"
export MODEL_ID="$MODEL_ID"
ENVEOF

echo
echo "  ENDPOINT_ID=$ENDPOINT_ID"
echo "  NEBIUS_ENDPOINT_URL=http://$ENDPOINT_IP/v1"
echo "  Wrote nebius/endpoint.env  ->  run: source nebius/endpoint.env"
echo
echo "Smoke test (vLLM answers only once the model has finished loading):"
echo "  curl -sS \"\$NEBIUS_ENDPOINT_URL/models\" -H \"Authorization: Bearer \$NEBIUS_API_KEY\" | jq"
