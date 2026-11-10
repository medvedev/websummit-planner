# Locally built Go MCP service on Cloud Run

Project: `websummit-mcp-unofficial`. Region: `us-central1` (Iowa, Tier 1 pricing).
Static distribution: https://medvedev.github.io/websummit-planner/

The read-only service uses a static Go executable, official MCP SDK and immutable
in-memory snapshot/indexes. No database server, personal persistence or runtime
network dependency is needed. Plans remain in agent context; agenda exports run there.

## Test and deploy

    python3 skills/websummit-planner/scripts/export_text.py --out service/data   # writes schedule.json and companies.json
    cd service
    go test -race ./...
    go vet ./...
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o server .
    cd ..
    python3 tools/check_service.py
    bash tools/deploy_gcp.sh websummit-mcp-unofficial us-central1

Deployment builds Docker on the invoking machine (or the GitHub runner), pushes only
the resulting image to the `websummit-images` Artifact Registry repository, and deploys
Cloud Run with an immutable image digest. It never submits source code to Cloud Build.
Docker credentials use a temporary directory removed on exit; access tokens pass through
stdin rather than command arguments. WS_IMAGE_TAG can override the timestamped build tag.
The final scratch image runs as UID 65532 without Python, Node or a shell.

Endpoints: GET /health, POST /mcp. Cloud Run intercepts /healthz, so use /health.
Each HTTP request accepts one JSON-RPC message; legacy batches are rejected before SDK
dispatch. PORT defaults to 8080; SCHEDULE_PATH defaults to data/schedule.json locally,
/data/schedule.json in the image; COMPANIES_PATH defaults to data/companies.json locally,
/data/companies.json in the image (a missing file is a startup error: company tools are part of the contract). The service does not log request bodies or personal notes.

## Configuration and permissions

Use explicit --project flags; the local gcloud default points to another project.
Billing must be enabled even when usage stays within free allowances. Enable only the
IAM, Cloud Run and Artifact Registry APIs needed for this deployment route. Cloud Build
is not required. The runtime identity is:
`websummit-runtime@websummit-mcp-unofficial.iam.gserviceaccount.com`, with no project roles.

An initial project owner can create the runtime identity and Docker repository. A CI
deployer needs Cloud Run deployment/IAM permissions on this service, permission to act
as the runtime identity, and Artifact Registry write access to websummit-images. It needs
no build service account, source-bucket access or Cloud Build permissions.

The deploy script uses request-based CPU allocation, gen1, 128 MiB, 2 CPUs, concurrency 128,
minimum 0 and maximum 3 instances, a 10-second request timeout and startup CPU boost.
The startup probe is TCP on 8080 with a 1 s period/timeout and 5 attempts (5 s budget). The server
listens only after the snapshot loads, so an open port means ready. Probe outcomes appear only in
Cloud Logging (textPayload "STARTUP TCP probe succeeded after N attempt"), not as a console chart.
GOMEMLIMIT=64MiB is a Go soft target. Measure production memory and latency before changing limits. Local measurements are in service-performance.md.

**Policy: never set min instances to 1 (or higher).** Keep `--min-instances 0` (scale to zero) at
both service and revision level, on every deploy and in the console. The owner has ruled out an
always-warm instance for cost reasons; accept the roughly 0.5-0.7 s cold start measured in
service-performance.md. Do not propose or apply min-instances as a fix for startup time.

## Optional GitHub deployment

service.yml verifies Go/race tests, HTTP/Python conflict parity and the Docker image.
Its opt-in deployment job executes the same local Docker build/push script on the runner.
Set WS_DEPLOY_GCP=true, GCP_PROJECT, GCP_REGION, GCP_WIF_PROVIDER and GCP_SERVICE_ACCOUNT
only after configuring repository-scoped Workload Identity Federation and the deployer
permissions above. No service-account key is stored. Static Pages deployment is independent.

## Public connector

After deployment, verify the actual HTTPS endpoint: initialize, tools/list, all seven
tools, real conflict detection, snapshot hash, and batch rejection. Set WS_MCP_URL to
that URL plus /mcp, then dispatch Web distribution. Never publish an unverified URL.
The shipped snapshot currently covers official sessions and community side events;
company fetcher data is separate until integrated into the portable snapshot.

Claude can use the custom connector or skill ZIP. ChatGPT can use custom MCP when
available, otherwise upload the data/instructions. Codex web uses the repository skill;
Gemini uses uploaded files in a chat/Gem. File-generation capabilities vary by host.
MCP verification does not prove any user account has added the connector.

## Cleanup of the earlier source deployment

Once the locally built image serves verified traffic, delete the old Cloud Run revision,
the cloud-run-source-deploy repository and run-sources source bucket. Remove the unused
websummit-build identity and its project role, then disable the Cloud Build API. Retain
the locally built image in websummit-images, which Cloud Run needs for deployment and
future rollbacks. Build history/audit records are operational records, not container artifacts.

## Verified live deployment (8 November 2026)

Connector: https://websummit-planner-380110762187.us-central1.run.app/mcp
Health: https://websummit-planner-380110762187.us-central1.run.app/health
Revision: `websummit-planner-00002-hwc`, server version 2.0.1, 100% of traffic.
Image built locally and deployed by digest:
`us-central1-docker.pkg.dev/websummit-mcp-unofficial/websummit-images/websummit-planner@sha256:5bec879e2fb4b1196935165c7e3ac7df83db6a286b5f3ee28f671d4ec0d62a18`.

Public verification passed: health, initialize, all seven read-only tools, exact snapshot
SHA-256 match, a real overlapping plan, plan-code roundtrip and batch rejection.
Snapshot contains 1,122 official sessions and 344 community side events.

Cleanup verified: old revision 00001-qsk deleted, cloud-run-source-deploy repository
and both uploaded source ZIPs/source bucket deleted, websummit-build identity and its
role removed, Cloud Build API disabled. Only websummit-images and the locally built
serving revision remain. Build history/audit metadata may remain as operational records.
