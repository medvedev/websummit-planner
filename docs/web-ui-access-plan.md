# Web UI access

The original hosting proposal is superseded by the user-approved Go/Cloud Run migration.
See [deployment.md](deployment.md) for runtime, build, permissions, deployment and CI;
see [web-instructions.md](web-instructions.md) for assistant setup and agenda exports.

The data source is read-only. Personal plans remain in agent context. No database server
or shared personal state is required. The static Pages distribution works independently
of MCP hosting and provides a file-upload route for Claude, ChatGPT and Gemini.
