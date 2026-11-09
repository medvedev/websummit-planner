# Companies in the Web Summit Planner — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the skill, the MCP service and the no-code web exports search and explain the 2,872 Web Summit Lisbon 2026 companies. Recommend companies (for example "seed-stage drone startups that are raising"), link companies to the sessions they host and the speakers they employ, and add "companies to meet" to plans and agendas.

**Architecture:**
- **Import.** The company data was fetched into `../websummit.db` (the parent directory, not under git) by `fetch_companies.py` and `fetch_profiles.py`. A new importer copies a sanitized subset into the bundled seed DB (`schema_version` 3).
- **Exports.** `export_text.py` emits `companies.json` plus Markdown, alongside the unchanged `schedule.json` shape. The one addition there is an optional `companies` field on official sessions.
- **Go service.** It loads `companies.json` next to `schedule.json` and adds two tools. Plan entries use the `company:<id>` ID prefix, so plan codes stay byte-compatible.
- **Untimed.** Companies have no booth location or exhibit day in the data, so they never take part in conflict checks or ICS export.

**Tech Stack:** Python 3.9+ stdlib (sqlite3, unittest), Go 1.27 + modelcontextprotocol/go-sdk, Docker/Cloud Run.

**Spec:** user decisions in session 2026-11-09 (recorded under Global Constraints).

## Global Constraints

**Data policy (user decision 2026-11-09)**
- Never ship `company_link` rows with `kind='pitch_deck'`. That applies to the seed DB, every export, the MCP and the ZIP.
- Never ship LinkedIn personal profiles. Drop `company_link` rows whose URL contains `linkedin.com/in/`. Company pages (`linkedin.com/company/…`) stay.
- Descriptions: replace email addresses with `[email removed]`, using the regex `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`. Founder names in descriptions stay.
- Keep `company_person` in full (person UUID, role, tier, industry, country). No names exist in that table, and none may be added except by joining the public schedule `person` table.
- Keep business facts and the founder-demographic facts (`Woman Founder`, `Black Founder`, `Indigenous Founder`). Expose all facts in search and filters.
- Keep `company_event`, `company_event_speaker` and `company_endorsement`.

**Data model and linking**
- Assume the user is logged into the Web Summit app or portal.
  - Company link: `https://attend.websummit.com/lis26/company/{id}` (singular `company`).
  - Person link: `https://attend.websummit.com/lis26/profiles/{uuid}`.
  - Never guess IDs from names.
- Join only on IDs:
  - `company_event.event_uuid = session.id`
  - `company_person.person_uuid = person.id`
  - `company_event_speaker.person_uuid = person.id`
  - Never match `person.company` text against company names.
- 24 of the 272 company events have only `time_text` and no date. List them as "activities"; never schedule them or invent a day.
- **One ID form for companies everywhere an agent sees an ID:** `"company:<n>"`, as a string. This covers search rows, details objects, the per-session `companies` field, `companies-compact.md` and `fetch`. The bare number appears only inside `url`. Inputs (`company`, `company_details`, `check_plan`, `agenda.py`) accept either `company:<n>` or a bare `<n>`.
- **Local persistence stays sessions-only.** `mark`, `shortlist`, `export`, `import` and the refresh guard reject or ignore `company:` IDs. Companies live in context-held plans and `agenda.py`, and SKILL.md says so.
- Plan entry IDs for companies are `company:<numeric id>`. Statuses are the same as for sessions (`maybe | must | skip | removed`). Companies are untimed: excluded from conflicts and ICS, listed in Markdown and PDF.
- Fact vocabulary (verbatim): `Actively Fundraising`, `No funding to date`, `Pre-seed`, `Seed`, `Series A`, `Series B & later`, `Not specified`, `Woman Founder`, `Black Founder`, `Indigenous Founder`, plus the prefixed families `Revenue: …`, `Amount Raised: …` and `Markets: …`.

**Compatibility**
- `schedule.json` gets additive optional fields only.
- The `SearchRow` fields, the `search`/`fetch` contract for session IDs and the existing goldens must not change. New Go fields use `omitempty`.
- **Session `companies` field (one definition, used by Tasks 3, 5 and 7):** `[{id: "company:<n>", name, relation: "host"|"speaker"}]`, ordered by relation (host first), then name, then id. It is omitted when empty, both in `planner.py details` and in `schedule.json`.
- **Company ordering everywhere:** tier rank (Partner, Growth, Beta, Alpha, Media Partner, null), then name, then numeric id.
- **Lowercasing:** SQLite `lower()` is ASCII-only while Go lowercases Unicode. Accept the difference for non-ASCII text, the same as session search does today, and keep `check_service.py` parity queries ASCII.
- **Root DB hazard:** the parent `build_db.py` writes a fresh DB and calls `os.replace`, which would drop every company table in `../websummit.db`, and raw profile pages aren't cached. Back up `../websummit.db` before anything else, and don't run the root `build_db.py` until Task 1 has landed the data in the seed DB.
- Bump `ServerVersion` to `2.1.0`.

**Refresh and runtime**
- Refresh cannot re-fetch companies, because that needs a portal cookie. Both refresh paths must carry company tables over unchanged.
- Container memory stays within `GOMEMLIMIT=64MiB`.

## Review Focus

1. A schedule `refresh` or a personal DB from an older snapshot silently loses the company tables. Tests in Task 2.
2. A pitch-deck link, a `linkedin.com/in/` link or an email address leaks through some company-derived output: the `company*` tables, the `companies*` files, the per-session `companies` field, or MCP responses. A leak scan in Task 5. The current schedule and side-event exports have 0 such hits as of 2026-11-09, so the scan stays scoped to company outputs.
3. `company:` entries in `check_plan`, `encode_plan` or `agenda.py` are reported as unknown or rejected, or they create conflicts or ICS events. Tests in Tasks 4 and 7.
4. Fact filters are case- or wording-sensitive in a way that makes "seed" find nothing. Search accepts a case-insensitive substring per fact filter (`fact: "seed"` matches `Seed` and `Pre-seed`, which is documented). Tests in Tasks 3 and 6.
5. The 24 undated company activities or the 4 event speakers who are absent from the schedule produce null-day rows or crashes. Tests in Tasks 1 and 3.

---

### Task 1: Seed DB company import

**Files:**
- Create: `skills/websummit-planner/scripts/import_companies.py`
- Modify: `skills/websummit-planner/scripts/build_db.py` (append the company DDL to `SCHEMA`; add `company_upgrade_sql()` next to `side_upgrade_sql()`; `schema_version` becomes `'3'`)
- Test: `tests/test_companies.py` (new)

**Interfaces:**
- Produces:
  - `build_db.COMPANY_SCHEMA: str`: DDL only, idempotent `CREATE TABLE IF NOT EXISTS` statements.
  - `build_db.company_upgrade_sql() -> str`
  - `import_companies.import_companies(source: Path, db: Path) -> dict` returns the per-table counts.
  - `import_companies.mask_emails(text: str|None) -> str|None`
  - CLI: `import_companies.py SOURCE_DB [--db assets/websummit.db]`
- Seed tables:
  - `company(id INTEGER PK, uuid, name NOT NULL, tier, industry, country, location, description, website, logo_url)`. This merges `company` and `company_profile`. `country` comes from the catalog card and `location` from the profile.
  - `company_tag(company_id, tag)`
  - `company_fact(company_id, position, fact)`
  - `company_link(company_id, kind, url)`: filtered.
  - `company_person(person_uuid, company_id, role, tier, industry, country)`
  - `company_event(company_id, event_uuid, session_id NULL REFERENCES session(id), title, time_text, location, type, description)`. `session_id` = `event_uuid` when that session exists, else NULL.
  - `company_event_speaker(company_id, event_uuid, person_uuid, role, org)`
  - `company_endorsement(company_id, endorsed_company_id, endorsed_name)`
- Indexes: on `company_tag(tag)`, `company_fact(fact)`, `company_person(company_id)`, `company_person(person_uuid)`, `company_event(session_id)`.
- Re-running replaces all company rows in one transaction (delete, then insert).

- [ ] **Step 1: Write failing tests.** Build a tiny source DB in a temp dir that holds:
  - two companies;
  - one `pitch_deck` link, one `linkedin.com/in/x` link and one `linkedin.com/company/y` link;
  - a description containing `a.b@c.io`;
  - one event whose `event_uuid` exists in the seed and one that doesn't.

  Copy the seed to a temp file, run `import_companies`, then assert:
  - `test_import_drops_pitch_decks_and_personal_linkedin`: link kinds are exactly the expected set, and `linkedin.com/company/y` is kept.
  - `test_import_masks_emails`: the description contains `[email removed]` and no `@`.
  - `test_import_links_events_by_id_only`: `session_id` is set for the known UUID and NULL for the unknown one.
  - `test_import_idempotent`: running twice gives the same counts.
  - `test_schema_version_3`: `meta.schema_version == '3'` and `PRAGMA foreign_key_check` is empty.
- [ ] **Step 2:** Run `python3 -m unittest tests.test_companies -v`. Expected: FAIL (module not found).
- [ ] **Step 3: Implement.** Open the source with `?mode=ro`. Use `ATTACH` plus `INSERT … SELECT`, with Python only for `mask_emails`. Leave `company_endorsement_pending` and `logo_url` caching out.
- [ ] **Step 4:** Tests pass. Then import for real:
  - Run `python3 skills/websummit-planner/scripts/import_companies.py ../websummit.db`.
  - Expected counts: `company` 2872; links 7909 − 1428 − 34; `company_event` 272, of which 248 have `session_id`.
- [ ] **Step 5:** Commit: `feat: import sanitized company catalog into seed snapshot`.

### Task 2: Refresh and upgrade keep companies

**Files:**
- Modify: `skills/websummit-planner/scripts/build_db.py:build()`. Carry company tables over from `old` when they exist: `INSERT OR IGNORE … SELECT * FROM old.company*`. For `company_event.session_id`, keep the value only when the session still exists, else NULL.
- Modify: `skills/websummit-planner/scripts/planner.py:upgrade()`. When the `company` table is missing, run `company_upgrade_sql()` and copy all company tables from `seed`. This is independent of the existing side-event branch, so a schema-1 DB gets both.
- Modify: `build_db.py` `__main__`, which prints the company count.
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write failing tests.**
  - `test_refresh_keeps_companies`: modelled on `test_refresh_keeps_side_events_and_their_history`. After `refresh --json fixture`, `SELECT count(*) FROM company` equals the seed count.
  - `test_old_personal_database_gains_companies`: drop the company tables from a copied seed and set `schema_version` to 2. After any read command, the companies are present and `schema_version` is `'3'`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `python3 -m unittest discover -s tests -v`. Expected: all pass.
- [ ] **Step 5:** Commit: `fix: carry company tables through refresh and upgrade`.

### Task 3: CLI company search and details

**Files:**
- Create: `skills/websummit-planner/scripts/companies.py`. This is the single shared helper module used by `planner.py`, `export_text.py` and `agenda.py`.
- Modify: `skills/websummit-planner/scripts/planner.py`. Add subcommands `companies` and `company`, add a `companies` count to `info`, and add a `companies` field to `details`.
- Test: `tests/test_companies.py`

**Interfaces:**
- `companies.py` provides:
  - `search_companies(con, query='', industry=None, country=None, tier=None, tags=(), facts=(), limit=30) -> list[dict]`
  - `company_objects(con, ids=None) -> list[dict]`: details objects, all of them when `ids` is None.
  - `session_companies(con, session_id) -> list[dict]`
  - `parse_company_id(s) -> int|None`: accepts `company:<n>` or `<n>`.
  - `company_url(n) -> str`
- Search:
  - CLI: `planner.py companies [QUERY] [--industry X] [--country X] [--tier X] [--tag X]... [--fact X]... [--limit 30]`
  - `QUERY` is a case-insensitive literal substring over name, description, location and tags.
  - `--industry`, `--country` and `--tier` are exact matches.
  - `--tag` is an exact, case-insensitive match. `--fact` is a case-insensitive substring per value. Repeated filters combine with AND.
  - Order: tier rank (Partner, Growth, Beta, Alpha, others), then name.
- Search result rows: `{id, name, tier, industry, location, facts: [str], url}`, where `url = https://attend.websummit.com/lis26/company/{id}`.
- Details:
  - CLI: `planner.py company ID [ID...]`. IDs may be given with or without the `company:` prefix. Unknown IDs give an error, the same as for sessions.
  - Returns, per company: all company columns, `url`, `tags`, `facts`, `links`, and `sessions` (from `company_event` joined to the session: `{id, day, start, end, stage, title, kind, url, type}`).
  - `activities`: undated events, `{title, time_text, location, type, description}`.
  - `speakers`: `company_person ⋈ person`, `{id, name, job_title, role, url, sessions: [id]}`.
  - `team`: `company_person` rows not in `person`, `{person_uuid, role, tier, industry, country, url}`.
  - `endorses`: `{id, name, url}`. `id` is set only when the endorsed company is in the catalog.
- `details SESSION_ID` adds the session `companies` field as defined in Global Constraints:
  - `host` comes from `company_event.session_id`.
  - `speaker` comes from session speakers' `company_person`.
  - Each `(id, relation)` appears once.
- `info` adds `companies`, `company_tiers`, `company_industries` and `company_facts`, each as `{value: count}`.

- [ ] **Step 1: Write failing tests** against the seed:
  - `test_companies_fact_filter`: `--fact seed --fact "actively fundraising"` returns only rows whose facts contain both. Assert every row.
  - `test_companies_query_matches_tags`: `companies drone` includes 62217 (MakeLocal).
  - `test_company_details_sections`: for a company that has a session, an activity and an endorsement, all three sections are non-empty. No row has a `null` day, and `team` has no `name` key.
  - `test_session_details_lists_companies`: `details` of a session that `company_event` maps gives a `host` entry.
  - `test_company_prefix_and_unknown`: `company company:62217` works; `company 1` fails with a non-zero exit.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement using parameterized SQL, the same way as `search`.
- [ ] **Step 4:** Run the full suite. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: company search and details in planner CLI`.

### Task 4: Companies in agendas

**Files:**
- Modify: `skills/websummit-planner/scripts/agenda.py`
- Test: `tests/test_agenda.py`

**Interfaces:**
- `resolve(rows, plan, companies=None) -> (sessions: list, companies: list)`. This is a breaking internal change, so update `main` and the tests.
  - IDs starting with `company:` resolve against `companies`, a list of `{id, name, tier, industry, location, url}`.
  - Unknown company IDs raise `unknown company ID: …`.
- Source of company rows:
  - With `--db` or the seed: the `company` table.
  - With `--schedule`: an optional `--companies companies.json`. A `company:` entry without that file raises a clear error.
- Markdown and PDF: append `## Companies to meet` with name, tier, industry, location, link, status and note, ordered must before maybe, then by name.
- ICS: companies are omitted, and the output is unchanged when the plan holds only companies plus sessions.

- [ ] **Step 1: Write failing tests.**
  - `test_company_entries_markdown`: the section is present with the link.
  - `test_company_entries_not_in_ics`: no `VEVENT` for a company.
  - `test_unknown_company_rejected`.
  - `test_schedule_json_without_companies_file_errors`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Steps 4–5 are the same as in earlier tasks. Commit: `feat: companies-to-meet section in agenda exports`.

### Task 5: Text exports and web distribution

**Files:**
- Modify: `skills/websummit-planner/scripts/export_text.py`
- Modify: `tools/build_web.py`: copy the new files into `dist/`, add them to the `LLMS` text and the index cards, and add them to the ZIP through the seed DB, which happens automatically.
- Test: `tests/test_web_build.py`

**Interfaces:**
- `export(out, db=SEED)` also writes:
  - `companies.json`: `{"info": {built_at, companies, notice}, "companies": [<company details object from Task 3>]}`, ordered by id. This is the file the Go service and `agenda.py --companies` read.
  - `companies-compact.md`, one line per company: `company:<id> | name | tier | industry | location | facts; joined | tags; joined | url`.
  - `companies.md`: full blocks with the description, sessions and speakers.
- Each official session in `schedule.json` gains `"companies": [{id, name, relation}]`, omitted when empty.
- The return dict gains `companies`.
- The `HEADER`/notice mentions that company data comes from the Web Summit attendee portal.

- [ ] **Step 1: Write failing tests.**
  - Extend `test_build`: the files exist, and `companies.json` parses with 2872 rows.
  - `test_exports_have_no_restricted_links`: over `companies*` in `dist/`, the `company*` tables of the seed DB inside the ZIP, and every session `companies` field in `schedule.json`, assert that `rails/active_storage`, `linkedin.com/in/` and `pitch_deck` are absent and that no email matches the Task 1 regex.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement with `companies.company_objects` and `companies.session_companies` from Task 3. Don't duplicate SQL.
- [ ] **Step 4:** Run `python3 tools/build_web.py` and the full suite. Expected: PASS. Note the sizes of `companies.json` and `companies.md`; target under 6 MB in total.
- [ ] **Step 5:** Commit: `feat: export companies for no-code hosts and web dist`.

### Task 6: Go company dataset

**Files:**
- Create: `service/companies.go`, `service/companies_test.go`
- Create: `service/testdata/companies.json`, a curated slice of about 8 companies. Include a Unicode name, one company with sessions present in `testdata/schedule.json`, one with only an activity, and one with no facts.
- Modify: `service/dataset.go`: `Dataset` gets `companies *Companies`.

**Interfaces:**
- `LoadCompanies(path string) (*Companies, error)` and `ParseCompanies(b []byte) (*Companies, error)`.
  - They validate: non-empty, unique positive ids, a name for every company, and an `info.notice`.
  - They keep the raw JSON per company, the same pattern as `Session.raw`.
- `type CompanySearchArgs struct { Query, Industry, Country, Tier string; Tags, Facts []string; Limit int }`
- `type CompanyRow struct { ID string; Name string; Tier, Industry, Location *string; Facts []string; URL string }`. JSON keys are lowercase snake case, and `id` is `"company:<n>"`.
- `(*Companies).Search(a CompanySearchArgs) []CompanyRow`. Semantics are identical to Task 3, including the ordering. Limit defaults to 30, capped at 100.
- `(*Companies).Details(ids []string) []json.RawMessage`. Accepts `"62217"` or `"company:62217"`; at most 20 IDs; unknown IDs are silently dropped, as in session `Details`.
- `(*Companies).Facets() map[string]map[string]int`, keyed by `tiers`, `industries`, `facts` and `countries`.
- `CompanyPlanID(id string) (int, bool)` parses the `company:<n>` prefix.

- [ ] **Step 1: Write failing tests.**
  - `TestCompanySearchFactSubstringAND`
  - `TestCompanySearchTagExactCaseInsensitive`
  - `TestCompanySearchOrderTierThenName`
  - `TestCompanyDetailsPrefixDedupLimit`
  - `TestParseCompaniesRejectsInvalid`: duplicate id, missing name, missing notice, trailing data.
- [ ] **Step 2:** Run `cd service && go test ./...`. Expected: FAIL.
- [ ] **Step 3:** Implement. Precompute lowercase strings at load time.
- [ ] **Step 4:** Run `go test -race ./... && go vet ./...`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(service): company dataset with search and details`.

### Task 7: MCP tools, plans, deployment and parity

**Files:**
- Modify: `service/server.go`, `service/main.go`, `service/dataset.go` (`CheckPlan`, `Fetch`, `Info`), `service/http_test.go`, `service/logic_test.go`, `Dockerfile`, `tools/check_service.py`.

**Interfaces:**
- New tools, read-only with the same annotations as the existing ones:
  - `search_companies`: `{query?, industry?, country?, tier?, tags?: string[≤10], facts?: string[≤10], limit?: 1..100}` returns `{results: CompanyRow[]}`.
  - `company_details`: `{company_ids: string[1..20]}` returns the raw objects.
- `fetch`: an id with the `company:` prefix returns `{id, title: name, text: "<tier> · <industry> · <location>\n<facts>\n<description>", url, metadata: {tier, industry, location, facts}}`.
- `check_plan`:
  - `PlanResult` gains `Companies []CompanyPlanRow` with `json:"companies"`. `CompanyPlanRow = {id: "company:<n>", name, url, status}` and holds only `maybe`/`must`, latest status wins.
  - Known company IDs never land in `unknown`.
  - Conflicts are unchanged.
  - The field is `omitempty`, so the existing goldens pass unchanged.
  - A bare-number company entry is also accepted and reported as `company:<n>`.
- `info` adds `companies` (count) and `company_facets`.
- `main.go`: `COMPANIES_PATH` defaults to `data/companies.json`. A missing file is a startup error, because company tools are part of the contract.
- `Dockerfile`: the snapshot stage must `COPY` the whole `skills/websummit-planner/scripts/` directory, because `export_text.py` now imports `companies.py`. Copy `/snapshot/companies.json` to `/data/companies.json` and set `ENV COMPANIES_PATH`.
- `.github/workflows/service.yml` and `web.yml` both reference `schedule.json`/`export_text`. Make them produce and ship `companies.json` as well.
- `baseInstructions`:
  - Replace "The snapshot has no company IDs." with company guidance: use `search_companies` for "which companies…" questions, then `company_details` to justify; facts are self-reported by the company; put `company:<id>` into `check_plan` plans as untimed "companies to meet"; company/team links need a logged-in Web Summit app or portal; never infer people's names from team UUIDs.
  - Bump `ServerVersion` to `"2.1.0"`.
- `check_service.py`:
  - The expected tool set includes the 2 new tools.
  - Add parity cases comparing `search_companies` against `planner.py companies` for 3 queries (a query, a fact filter, tier plus industry), plus `company_details` against `planner.py company` for 2 ids.

- [ ] **Step 1: Write failing tests.**
  - `TestMCPCompanyTools`: list includes both tools; a search call returns rows; details returns objects.
  - `TestCheckPlanCompaniesUntimed`: a company plus two overlapping sessions gives one conflict, `companies` has length 1, and `unknown` is empty.
  - `TestEncodePlanCompanyIDsRoundTrip`.
  - `TestFetchCompany`.
  - `TestMCPValidationFailures`: add a case with 11 facts.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4: Verify.**
  - Run `python3 skills/websummit-planner/scripts/export_text.py --out service/data`.
  - Run `cd service && go test -race ./... && go vet ./... && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o server .`.
  - Run `cd .. && python3 tools/check_service.py`. Expected: PASS.
  - Measure RSS with the real data (`/usr/bin/time -v ./server`). It must stay well under 64 MiB.
- [ ] **Step 5:** Commit: `feat(service): search_companies, company_details, untimed companies in plans`.

### Task 8: Instructions, notices and release

**Files:**
- `skills/websummit-planner/SKILL.md`:
  - Replace the "no company IDs" sentence on line 8.
  - Add a `## Companies` section covering the `companies` and `company` commands, the fact vocabulary and substring rule, the "facts are self-reported by companies" caveat, the `company:<id>` plan entries, and the untimed rule.
  - Say when to proactively suggest companies: when the user names a sector, stage or investor intent, or picks a session whose `companies` field is non-empty.
- `skills/websummit-planner/references/schema.md`: the new tables and `schema_version` 3.
- `DATA_NOTICE.md` and `skills/websummit-planner/DATA_NOTICE.md`: a new "Company data" paragraph.
  - Source: the Web Summit attendee portal, collected 8 November 2026.
  - Fields and exclusions: pitch decks, personal LinkedIn links, masked emails.
  - People are present only as profile UUIDs plus role, tier, industry and country.
  - Links require a logged-in Web Summit app or portal.
  - Facts are self-reported by companies.
- `docs/web-instructions.md` (copied to `dist/`): how to use `companies*.md` when there's no MCP.
- `README.md`, `INSTALL.md`, `UPDATE.md`: step 6 also requires `planner.py companies --limit 1` to return a row; step 7 mentions the companies feature.
- `docs/deployment.md`: `COMPANIES_PATH`, and the export step now writes `companies.json` too.
- `mcp-worker/` is legacy. Leave it untouched and say so in the README.

- [ ] **Step 1:** Make the edits.
- [ ] **Step 2:** Rebuild: `python3 tools/build_web.py`, then run the full Python suite, `go test ./...` and `tools/check_service.py`. Expected: all PASS.
- [ ] **Step 3: Manual acceptance against the local skill CLI and a locally running server.** Each must answer from the data, with IDs and links:
  - "seed-stage defence or drone startups that are actively fundraising";
  - "which companies host sessions on 11 Nov";
  - "who from company X speaks, and when";
  - "add 3 companies to my plan and give me the agenda (md + ics)".
- [ ] **Step 4:** Commit: `docs: company support in skill, MCP instructions and data notice`. Deployment (`tools/deploy_gcp.sh`) happens only on the user's go-ahead.
