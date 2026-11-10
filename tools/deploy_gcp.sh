#!/usr/bin/env bash
set -euo pipefail
project="${1:?Usage: deploy_gcp.sh PROJECT_ID [REGION]}"
region="${2:-us-central1}"
if [[ -z "$region" ]]; then region=us-central1; fi
cd "$(dirname "$0")/.."
repository="${region}-docker.pkg.dev/${project}/websummit-images"
tag="${WS_IMAGE_TAG:-$(git rev-parse --short=12 HEAD)-$(date -u +%Y%m%dT%H%M%SZ)}"
image="${repository}/websummit-planner:${tag}"
# Build on this machine (or the GitHub runner), never through Cloud Build.
docker build --platform linux/amd64 -t "$image" .
if ! gcloud artifacts repositories describe websummit-images --project "$project" --location "$region" >/dev/null 2>&1; then
  gcloud artifacts repositories create websummit-images --project "$project" --location "$region" --repository-format docker --description="Locally built Web Summit images" --quiet
fi
docker_config="$(mktemp -d "${TMPDIR:-/tmp}/websummit-docker.XXXXXX")"
trap 'rm -rf "$docker_config"' EXIT
gcloud auth print-access-token --project "$project" | docker --config "$docker_config" login -u oauth2accesstoken --password-stdin "https://${region}-docker.pkg.dev"
docker --config "$docker_config" push "$image"
digest="$(docker image inspect "$image" --format '{{index .RepoDigests 0}}')"
if [[ "$digest" != "${repository}/websummit-planner@sha256:"* ]]; then
  echo "Unexpected pushed image digest" >&2
  exit 1
fi
gcloud run deploy websummit-planner --project "$project" --region "$region" \
  --image "$digest" --allow-unauthenticated --port 8080 \
  --service-account "websummit-runtime@${project}.iam.gserviceaccount.com" \
  --execution-environment gen1 --cpu 2 --memory 128Mi --concurrency 128 \
  --min-instances 0 --max-instances 3 --timeout 10 \
  --cpu-throttling --cpu-boost \
  --startup-probe 'tcpSocket.port=8080,timeoutSeconds=1,periodSeconds=1,failureThreshold=5' \
  --quiet
