# Web distribution deployment

Static landing page: https://medvedev.github.io/websummit-planner/

GitHub Pages uses the web.yml workflow on main. It builds a skill ZIP, schedule JSON,
per-day Markdown, web-instructions.md and agenda.py. The web-latest release carries
those downloadable artifacts. Only dist/ is published; internal docs and credentials
are excluded. The company fetcher's work is outside this build; this release contains
the bundled schedule and side-event snapshot. Regenerate after its curated data is integrated.

## MCP on free Cloudflare Workers

No paid bindings, model APIs or personal storage are used. From mcp-worker:

    npm ci
    npx wrangler login
    npm run deploy

Use the printed workers.dev URL plus /mcp as the connector URL. Test initialize,
tools/list, info, search, details and check_plan before announcing it as live.
For CI, save a Workers deployment-scoped CLOUDFLARE_API_TOKEN repository secret,
and set the WS_DEPLOY_WORKER repository variable to true. Until explicitly enabled,
CI tests and bundles the Worker without attempting an unauthenticated deployment.
Set WS_MCP_URL to the full /mcp URL and rerun Web distribution to publish the link.
WS_GPT_URL and WS_GEM_URL are optional links to independently created shared assistants.
Neither is needed for the file-upload route.

## User setup

Read web-instructions.md. In Claude add the public MCP URL as a custom connector
without authentication, or upload the skill ZIP. In ChatGPT use a custom MCP app
if the account offers it; otherwise attach schedule.json and the instructions in a
file-capable chat. Codex web runs the repository skill in its task sandbox. Gemini
uses uploaded data/instructions in a chat or Gem; remote MCP is not assumed.

All formats depend on the assistant's file creation capabilities. The local agenda.py
helper works independently of those capabilities; PDF needs ReportLab and a Unicode
TrueType font. No calendar service is modified automatically. End-to-end host UI tests
must be recorded separately from server and build tests; a passing MCP smoke test does
not prove any host's connector has been added to the user's account.
