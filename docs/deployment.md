# Go MCP service on Google Cloud Run

Static distribution: https://medvedev.github.io/websummit-planner/

The MCP service is a static Go executable, the official MCP SDK and an immutable
schedule JSON snapshot. Each instance loads data/indexes once; there is no SQL server,
network database, runtime dependency download or persistent personal state. Relationship
lookups use IDs and indexes. Snapshot updates create new container revisions. Agenda
Markdown/PDF/ICS generation remains in the agent environment.

## Local verification

    python3 skills/websummit-planner/scripts/export_text.py --out service/data
    cd service
    go test -race ./...
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o server .
    cd ..
    python3 tools/check_service.py
    docker build -t websummit-mcp .
    docker run --rm -p 8080:8080 --memory 128m --read-only --cap-drop ALL websummit-mcp

Endpoints: GET /healthz, POST /mcp. Each request accepts one JSON-RPC message; legacy batches are rejected before SDK dispatch. PORT defaults to 8080; SCHEDULE_PATH defaults to
 data/schedule.json when run locally, /data/schedule.json in the image. Only tool
metadata and public data are returned; the service does not log request bodies or notes.

## Initial project setup

The owner is creating a dedicated project separately. Do not deploy to the unrelated
project selected in the local gcloud configuration. Use an explicit project ID in every
command. Billing must be enabled; free allowances do not guarantee a zero bill.

    project=YOUR_PROJECT_ID
    gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project "$project"
    gcloud iam service-accounts create websummit-runtime --display-name="Web Summit read-only runtime" --project "$project"

The runtime identity needs no project IAM roles: it reads only the bundled snapshot.
The deploying identity needs the Cloud Run source deployment permissions and permission
to act as the runtime identity. The project's Cloud Build identity needs the documented
Cloud Run Builder permissions. See the official source deployment guide for the exact
roles for your organization's build identity policy:
https://cloud.google.com/run/docs/deploying-source-code
Do not grant broad roles to the runtime identity to fix build permissions.

## Deploy

    bash tools/deploy_gcp.sh YOUR_PROJECT_ID europe-west1

This uses request-based CPU allocation, gen1 (required for the selected 128 MiB limit),
1 CPU, concurrency 4, minimum 0 and maximum 2 instances, 30-second request timeout
and startup CPU boost. The scratch image runs as UID 65532. GOMEMLIMIT=64MiB is a
Go runtime soft target, not a container hard limit. Increase limits only after measurement.
The configured image contains no shell, Python or Node runtime. Local startup measurements
exclude image retrieval, Cloud Run scheduling and TLS; measure production cold starts separately.

Take the returned HTTPS service URL and append /mcp. Verify initialize, tools/list,
info, search, details and check_plan. Cloud Run terminates HTTPS; the container speaks HTTP.
Set GitHub variable WS_MCP_URL to the full endpoint and dispatch the Web distribution
workflow to publish its connector link. Keep the service unauthenticated because the data
is public and the supported web clients must reach it without Google IAM credentials.
The service snapshot includes the bundled schedule/side events. Company fetcher data
remains outside the build until curated into the portable snapshot.

## Optional GitHub deployment

The service.yml workflow always tests Go, race detection, HTTP/Python conflict parity
and the Docker build. Deployment is opt-in: set WS_DEPLOY_GCP=true, GCP_PROJECT,
GCP_REGION, GCP_WIF_PROVIDER and GCP_SERVICE_ACCOUNT repository variables after
configuring Workload Identity Federation for this repository. No service-account key
is stored. The deployer needs the same source deployment permissions described above.
Static Pages deployment remains independent of GCP.

## Web clients

Follow web-instructions.md. Claude uses a custom connector or the skill ZIP. ChatGPT
uses custom MCP when available, otherwise uploaded JSON/instructions. Codex web uses
the repository skill. Gemini uses uploaded files in a chat/Gem; remote MCP support is
not assumed. Shared GPT/Gem links are optional. Agent plans stay in context; agenda
exports do not modify calendars or create Teams meetings. Host UI verification remains
separate from service tests; do not claim a connector is added until checked in that UI.
