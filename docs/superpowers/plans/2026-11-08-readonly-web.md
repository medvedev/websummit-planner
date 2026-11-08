# Read-only web access implementation plan

Goal: use the published snapshot from web assistants while plans stay in agent context.
Architecture: retain the stateless MCP Worker and static files; add a local artifact renderer consuming context-held IDs. No user database or server storage.
Spec: user-approved design in this session, 8 November 2026.

- [x] Test then implement scripts/agenda.py: accept a JSON array of {id,status,note?}, resolve against a read-only snapshot, emit Markdown, RFC 5545 ICS, or PDF. Reject unknown IDs; deduplicate using latest status; omit skips/removals; preserve unknown end times. Escape calendar text, fold UTF-8 lines, use UTC and stable UIDs.
- [x] Update web instructions and distribution with context-only planning and artifact downloads; retain local CLI state commands as an explicit optional legacy workflow.
- [x] Exercise MCP transport and tools, Python tests, TypeScript and Worker tests; render and inspect sample PDF.
- [x] Build release artifacts and attempt free hosting deployment. Verify live endpoints if authenticated; otherwise document the precise account handoff.

Constraints: preserve company fetcher work and data; no paid services; no automatic calendar imports; no server persistence.
Review focus: Unicode and line injection; unknown event ends; duplicate IDs/statuses; absent PDF dependency; unsupported host features.

Verification: 29 Python tests, 9 Worker parity tests, TypeScript, Worker dry-run, MCP HTTP smoke, PDF rendered and inspected. Static Pages artifacts fetched successfully. MCP public deployment remains pending Cloudflare authentication.
Review correction: agenda --db now reads the exact refreshed planner snapshot read-only. Windows CI exposed an unclosed SQLite handle in the new test; explicitly close it.
