#!/usr/bin/env bash
set -euo pipefail
project="${1:?Usage: deploy_gcp.sh PROJECT_ID [REGION]}"
region="${2:-us-central1}"
if [[ -z "$region" ]]; then region=us-central1; fi
cd "$(dirname "$0")/.."
gcloud run deploy websummit-planner --project "$project" --region "$region" \
  --source . --allow-unauthenticated --port 8080 \
  --build-service-account "projects/${project}/serviceAccounts/websummit-build@${project}.iam.gserviceaccount.com" \
  --service-account "websummit-runtime@${project}.iam.gserviceaccount.com" \
  --execution-environment gen1 --cpu 1 --memory 128Mi --concurrency 4 \
  --min-instances 0 --max-instances 2 --timeout 30 \
  --cpu-throttling --cpu-boost --quiet
