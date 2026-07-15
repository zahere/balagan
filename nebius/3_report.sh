#!/usr/bin/env bash
# Pull every trial object out of Object Storage and build results.jsonl,
# summary.md, and heatmap.png locally.
#
#   source nebius/endpoint.env   # not strictly needed here
#   export S3_BUCKET=... S3_PREFIX=balagan S3_ENDPOINT_URL=... AWS_* ...
#   ./nebius/3_report.sh configs/full.yaml

set -euo pipefail
CONFIG="${1:-configs/full.yaml}"
balagan report --config "$CONFIG"
echo "Commit results/<run>/{results.jsonl,summary.md,heatmap.png} to the repo."
