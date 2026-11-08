# Go Cloud Run migration

User authorization: replace Cloudflare with GCP, use Opus subagent and an efficient service language with low footprint and fast startup. Preserve read-only data/context-held plans and agenda exports.

Decision: Go, official MCP SDK, a single immutable in-memory snapshot with ID/day/kind indexes and precomputed search fields. Explicit relationship lookups rather than an arbitrary query interpreter; no separate SQL service. Cloud Run request-based billing, min instances 0, max instances 2, 1 CPU, 128 MiB initially, concurrency 4. Measure local startup/RSS and validate Cloud Run settings before release; no claim of zero cost or production cold-start latency from local tests.

- [x] Opus implements service/ and tests, preserving seven tools and plan-code interoperability.
- [x] Parent builds small static non-root container, snapshot generation and Cloud Run deployment runbook/CI; no stored service account key.
- [x] Run Python tests, Go/race/HTTP/parity tests and footprint benchmarks. Remove old Worker source/workflow after proof.
- [ ] Deploy only to user-selected project, verify public MCP and health endpoint, then update Pages connector URL. If account/project blocks deployment, retain tested build and exact handoff.

Boundary: do not touch parent company fetcher, private cookies, or unrelated GCP workloads. Snapshot updates are immutable service revisions. No personal persistence or server-side PDF generation.

Execution record: implementation and independent review used Claude Code with --model opus.
The owner will create a dedicated GCP project separately; no existing project was modified.
Go race/vet tests, legacy golden fixtures, Python conflict parity over real HTTP, Python tests,
actionlint and the scratch container build pass. govulncheck reports no reachable vulnerabilities.
Local measurements are in docs/service-performance.md. Concurrency was reduced to four after
maximum-plan load testing at 128 MiB. Review fixes: reject legacy JSON-RPC batches before the
SDK (with a failing-then-passing regression), quote the deployment condition correctly, include
deployment files in CI triggers, pin builder digests. Additional regression covers 200 maximally
escaped IDs through both the codec and the real MCP HTTP client.
