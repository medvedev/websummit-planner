package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func newTestServer(t *testing.T) (*httptest.Server, *Dataset) {
	t.Helper()
	d := fixture(t).WithCompanies(companyFixture(t))
	ts := httptest.NewServer(NewHandler(d))
	t.Cleanup(ts.Close)
	return ts, d
}

func connect(t *testing.T, ts *httptest.Server) *mcp.ClientSession {
	t.Helper()
	c := mcp.NewClient(&mcp.Implementation{Name: "test", Version: "0"}, nil)
	cs, err := c.Connect(context.Background(), &mcp.StreamableClientTransport{Endpoint: ts.URL + "/mcp"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { cs.Close() })
	return cs
}

func callText(t *testing.T, cs *mcp.ClientSession, name string, args any) (string, bool) {
	t.Helper()
	res, err := cs.CallTool(context.Background(), &mcp.CallToolParams{Name: name, Arguments: args})
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	if len(res.Content) != 1 {
		t.Fatalf("%s: content items = %d", name, len(res.Content))
	}
	if res.StructuredContent != nil {
		t.Errorf("%s: unexpected structuredContent", name)
	}
	return res.Content[0].(*mcp.TextContent).Text, res.IsError
}

func TestMCPInitializeListAndAnnotations(t *testing.T) {
	ts, _ := newTestServer(t)
	cs := connect(t, ts)
	init := cs.InitializeResult()
	if init.ServerInfo.Name != "websummit-planner" || !strings.Contains(init.Instructions, "check_plan") ||
		!strings.Contains(init.Instructions, ".ics") || !strings.Contains(init.Instructions, "2026-11-07T22:05:48Z") {
		t.Errorf("initialize = %+v", init)
	}
	lt, err := cs.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]bool{"info": true, "search": true, "details": true, "check_plan": true, "encode_plan": true, "decode_plan": true, "fetch": true, "search_companies": true, "company_details": true}
	if len(lt.Tools) != len(want) {
		t.Errorf("tools = %d", len(lt.Tools))
	}
	for _, tool := range lt.Tools {
		if !want[tool.Name] {
			t.Errorf("unexpected tool %s", tool.Name)
		}
		a := tool.Annotations
		if a == nil || !a.ReadOnlyHint || a.OpenWorldHint == nil || *a.OpenWorldHint || a.DestructiveHint == nil || *a.DestructiveHint || !a.IdempotentHint {
			t.Errorf("%s annotations = %+v", tool.Name, a)
		}
		if tool.OutputSchema != nil {
			t.Errorf("%s has an output schema", tool.Name)
		}
		raw, _ := json.Marshal(tool.InputSchema)
		if tool.Name == "check_plan" && (!strings.Contains(string(raw), `"maxItems":200`) || !strings.Contains(string(raw), `"maxLength":128`)) {
			t.Errorf("check_plan schema lacks bounds: %s", raw)
		}
		if tool.Name == "search" && !strings.Contains(string(raw), `"enum":["official","side","all"]`) {
			t.Errorf("search schema lacks kind enum: %s", raw)
		}
	}
}

func TestMCPToolCalls(t *testing.T) {
	ts, d := newTestServer(t)
	cs := connect(t, ts)

	txt, isErr := callText(t, cs, "info", map[string]any{})
	if isErr || !strings.Contains(txt, `"notice":"`) || !strings.Contains(txt, `"snapshot_sha256"`) {
		t.Errorf("info = %s", txt)
	}

	txt, _ = callText(t, cs, "search", map[string]any{"query": "AI", "kind": "all", "limit": 5})
	var sr struct {
		Results []map[string]any `json:"results"`
	}
	if err := json.Unmarshal([]byte(txt), &sr); err != nil || len(sr.Results) == 0 || len(sr.Results) > 5 {
		t.Fatalf("search = %s", txt)
	}
	for _, r := range sr.Results {
		for _, k := range []string{"id", "title", "url", "day", "start", "end", "stage", "track", "kind"} {
			if _, ok := r[k]; !ok {
				t.Errorf("search row lacks %s: %v", k, r)
			}
		}
	}
	if strings.Contains(txt, `\u00`) || !strings.Contains(txt, "&") {
		t.Errorf("expected raw & and no HTML escaping: %.200s", txt)
	}

	id := d.sessions[0].ID
	txt, _ = callText(t, cs, "details", map[string]any{"session_ids": []string{id, "nope"}})
	if !strings.HasPrefix(txt, `[{"id":"`+id) || !strings.Contains(txt, `"ticket_url":`) {
		t.Errorf("details = %.300s", txt)
	}

	txt, _ = callText(t, cs, "check_plan", map[string]any{"sessions": []map[string]string{{"id": id, "status": "must"}, {"id": "zzz", "status": "maybe"}}, "buffer_min": 10})
	if !strings.Contains(txt, `"unknown":["zzz"]`) || !strings.Contains(txt, `"status":"must"`) {
		t.Errorf("check_plan = %s", txt)
	}

	txt, _ = callText(t, cs, "encode_plan", map[string]any{"sessions": []map[string]string{{"id": "сесія-1", "status": "maybe"}}})
	var enc struct{ Code string }
	_ = json.Unmarshal([]byte(txt), &enc)
	txt, _ = callText(t, cs, "decode_plan", map[string]any{"code": enc.Code})
	if txt != `{"sessions":[{"id":"сесія-1","status":"maybe"}]}` {
		t.Errorf("decode_plan = %s", txt)
	}
	txt, isErr = callText(t, cs, "decode_plan", map[string]any{"code": "@@"})
	if !isErr || !strings.Contains(txt, "bad plan code") {
		t.Errorf("bad code = %s (isError %v)", txt, isErr)
	}

	txt, _ = callText(t, cs, "fetch", map[string]any{"id": id})
	var f map[string]any
	if err := json.Unmarshal([]byte(txt), &f); err != nil || f["id"] != id || f["text"] == nil || f["url"] == nil {
		t.Errorf("fetch = %s", txt)
	}
	txt, _ = callText(t, cs, "fetch", map[string]any{"id": "nope"})
	if txt != `{"error":"unknown session"}` {
		t.Errorf("fetch unknown = %s", txt)
	}
}

func TestMCPValidationFailures(t *testing.T) {
	ts, _ := newTestServer(t)
	cs := connect(t, ts)
	long := strings.Repeat("x", MaxIDLen+1)
	many := make([]map[string]string, 201)
	for i := range many {
		many[i] = map[string]string{"id": "x", "status": "must"}
	}
	bad := []struct {
		tool string
		args any
	}{
		{"search", map[string]any{"limit": 0}},
		{"search", map[string]any{"limit": 101}},
		{"search", map[string]any{"limit": 2.5}},
		{"search", map[string]any{"kind": "everything"}},
		{"search", map[string]any{"query": strings.Repeat("q", 201)}},
		{"search", map[string]any{"day": "2026-11-10T"}},
		{"search", map[string]any{"query": nil}},
		{"details", map[string]any{"session_ids": []string{}}},
		{"details", map[string]any{"session_ids": make([]string, 21)}},
		{"details", map[string]any{"session_ids": []string{long}}},
		{"details", map[string]any{}},
		{"check_plan", map[string]any{"sessions": []map[string]string{{"id": "x", "status": "later"}}}},
		{"check_plan", map[string]any{"sessions": many}},
		{"check_plan", map[string]any{"sessions": []map[string]string{}, "buffer_min": 121}},
		{"check_plan", map[string]any{"sessions": []map[string]any{{"id": "x"}}}},
		{"encode_plan", map[string]any{"sessions": many}},
		{"decode_plan", map[string]any{"code": strings.Repeat("A", 24001)}},
		{"fetch", map[string]any{"id": long}},
		{"fetch", map[string]any{}},
		{"search_companies", map[string]any{"facts": make([]string, 11)}},
		{"search_companies", map[string]any{"tags": make([]string, 11)}},
		{"search_companies", map[string]any{"limit": 101}},
		{"search_companies", map[string]any{"query": strings.Repeat("q", 201)}},
		{"company_details", map[string]any{"company_ids": []string{}}},
		{"company_details", map[string]any{"company_ids": make([]string, 21)}},
		{"company_details", map[string]any{}},
	}
	for _, c := range bad {
		res, err := cs.CallTool(context.Background(), &mcp.CallToolParams{Name: c.tool, Arguments: c.args})
		if err == nil && !res.IsError {
			b, _ := json.Marshal(c.args)
			t.Errorf("%s %.120s: accepted", c.tool, b)
		}
	}
	// Integral floats and unknown extra keys are accepted, as with zod.
	for _, args := range []map[string]any{{"limit": 3.0}, {"query": "ai", "extra": true}} {
		res, err := cs.CallTool(context.Background(), &mcp.CallToolParams{Name: "search", Arguments: args})
		if err != nil || res.IsError {
			t.Errorf("search %v rejected: %v %v", args, err, res)
		}
	}
}

func post(t *testing.T, url, body string) *http.Response {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPost, url, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { resp.Body.Close() })
	return resp
}

func TestStatelessDirectCallAndLargeValidBodies(t *testing.T) {
	ts, d := newTestServer(t)
	resp := post(t, ts.URL+"/mcp", `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"info","arguments":{}}}`)
	b, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 || !strings.Contains(string(b), "snapshot_sha256") || resp.Header.Get("Mcp-Session-Id") != "" {
		t.Fatalf("direct call: %d %s", resp.StatusCode, b)
	}
	// Max-bound check_plan with the longest legal ids must fit within the body limit.
	id := strings.Repeat("x", MaxIDLen)
	entries := make([]string, 200)
	for i := range entries {
		entries[i] = fmt.Sprintf(`{"id":%q,"status":"maybe"}`, id)
	}
	_ = d
	body := `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"check_plan","arguments":{"sessions":[` + strings.Join(entries, ",") + `],"buffer_min":120}}}`
	resp = post(t, ts.URL+"/mcp", body)
	b, _ = io.ReadAll(resp.Body)
	if resp.StatusCode != 200 || strings.Contains(string(b), `"isError":true`) {
		t.Fatalf("max check_plan: %d %.300s", resp.StatusCode, b)
	}
	body = `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"decode_plan","arguments":{"code":"` + strings.Repeat("A", 24000) + `"}}}`
	resp = post(t, ts.URL+"/mcp", body)
	b, _ = io.ReadAll(resp.Body)
	if resp.StatusCode != 200 || !strings.Contains(string(b), "bad plan code") {
		t.Fatalf("max decode_plan: %d %.300s", resp.StatusCode, b)
	}
}

func TestHTTPRoutesAndLimits(t *testing.T) {
	ts, _ := newTestServer(t)
	get := func(path string) (*http.Response, string) {
		resp, err := http.Get(ts.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		b, _ := io.ReadAll(resp.Body)
		return resp, string(b)
	}
	if r, b := get("/"); r.StatusCode != 200 || !strings.Contains(b, "Unofficial") || !strings.Contains(b, "/mcp") {
		t.Errorf("/ = %d %s", r.StatusCode, b)
	}
	if r, b := get("/health"); r.StatusCode != 200 || !strings.Contains(b, "ok") {
		t.Errorf("/health = %d %s", r.StatusCode, b)
	}
	if r, _ := get("/nope"); r.StatusCode != 404 {
		t.Errorf("/nope = %d", r.StatusCode)
	}
	if r, _ := get("/mcp"); r.StatusCode != 405 || r.Header.Get("Allow") != "POST" {
		t.Errorf("GET /mcp = %d allow=%q", r.StatusCode, r.Header.Get("Allow"))
	}
	if r := post(t, ts.URL+"/mcp", strings.Repeat(" ", MaxBodyBytes+1)); r.StatusCode != 413 {
		t.Errorf("oversized body = %d", r.StatusCode)
	}
	// Chunked (no Content-Length) oversized body is also rejected.
	req, _ := http.NewRequest(http.MethodPost, ts.URL+"/mcp", io.MultiReader(strings.NewReader(strings.Repeat(" ", MaxBodyBytes)), strings.NewReader("  ")))
	req.ContentLength = -1
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 413 {
		t.Errorf("chunked oversized body = %d", resp.StatusCode)
	}
}

func TestSameHostProxyWithPublicHostIsAllowed(t *testing.T) {
	ts, _ := newTestServer(t)
	req, _ := http.NewRequest(http.MethodPost, ts.URL+"/mcp", strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"info","arguments":{}}}`))
	req.Host = "planner.example.com"
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Errorf("public Host via loopback = %d", resp.StatusCode)
	}
}

// The SDK validates raw JSON then unmarshals; guard against a case-insensitive
// decoder letting e.g. "Sessions" or "LIMIT" bypass schema bounds after an upgrade.
func TestMixedCaseKeysCannotBypassBounds(t *testing.T) {
	ts, _ := newTestServer(t)
	cs := connect(t, ts)
	call := func(name string, args any) string {
		t.Helper()
		txt, _ := callText(t, cs, name, args)
		return txt
	}
	if n := strings.Count(call("search", map[string]any{"LIMIT": 2}), `"id"`); n != defaultLimit {
		t.Errorf("LIMIT key changed result count to %d", n)
	}
	many := make([]map[string]string, 300)
	for i := range many {
		many[i] = map[string]string{"id": "x", "status": "must"}
	}
	if txt := call("check_plan", map[string]any{"sessions": []any{}, "Sessions": many, "BUFFER_MIN": 1e300}); txt != `{"plan":[],"conflicts":[],"unknown":[]}` {
		t.Errorf("mixed-case check_plan keys were used: %.200s", txt)
	}
	if txt := call("check_plan", map[string]any{"sessions": []any{map[string]any{"id": "a", "status": "must", "ID": strings.Repeat("z", 500)}}}); txt != `{"plan":[],"conflicts":[],"unknown":["a"]}` {
		t.Errorf("mixed-case entry key was used: %.200s", txt)
	}
}

func TestInitializeWithOlderProtocolVersions(t *testing.T) {
	ts, _ := newTestServer(t)
	for _, v := range []string{"2025-03-26", "2025-06-18", "2025-11-25"} {
		resp := post(t, ts.URL+"/mcp", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"`+v+
			`","capabilities":{},"clientInfo":{"name":"host","version":"1"}}}`)
		b, _ := io.ReadAll(resp.Body)
		var r struct {
			Result struct {
				ProtocolVersion string `json:"protocolVersion"`
				ServerInfo      struct{ Name string }
				Instructions    string
			}
		}
		if err := json.Unmarshal(b, &r); err != nil || resp.StatusCode != 200 || r.Result.ProtocolVersion != v ||
			r.Result.ServerInfo.Name != "websummit-planner" || !strings.Contains(r.Result.Instructions, "check_plan") {
			t.Errorf("initialize %s: %d %.300s", v, resp.StatusCode, b)
			continue
		}
		req, _ := http.NewRequest(http.MethodPost, ts.URL+"/mcp", strings.NewReader(`{"jsonrpc":"2.0","id":2,"method":"tools/list"}`))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "application/json, text/event-stream")
		req.Header.Set("MCP-Protocol-Version", v)
		lr, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		lb, _ := io.ReadAll(lr.Body)
		lr.Body.Close()
		if lr.StatusCode != 200 || !strings.Contains(string(lb), `"name":"fetch"`) || !strings.Contains(string(lb), `"readOnlyHint":true`) {
			t.Errorf("tools/list %s: %d %.300s", v, lr.StatusCode, lb)
		}
	}
}

func TestHTTPRejectsLegacyBatchRequests(t *testing.T) {
	ts, _ := newTestServer(t)
	body := `[{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"info","arguments":{}}}]`
	req, err := http.NewRequest(http.MethodPost, ts.URL+"/mcp", strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	resp, err := ts.Client().Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("batch status=%d, want400", resp.StatusCode)
	}
}

func TestMCPMaximumEscapedPlanCodeRoundTrip(t *testing.T) {
	ts, _ := newTestServer(t)
	cs := connect(t, ts)
	plan := make([]PlanEntry, MaxPlan)
	for i := range plan {
		plan[i] = PlanEntry{ID: strings.Repeat("\x01", MaxIDLen), Status: "must"}
	}
	text, bad := callText(t, cs, "encode_plan", map[string]any{"sessions": plan})
	if bad {
		t.Fatal(text)
	}
	var encoded struct {
		Code string `json:"code"`
	}
	if err := json.Unmarshal([]byte(text), &encoded); err != nil {
		t.Fatal(err)
	}
	text, bad = callText(t, cs, "decode_plan", map[string]any{"code": encoded.Code})
	if bad {
		t.Fatal(text)
	}
	var decoded struct {
		Sessions []PlanEntry `json:"sessions"`
	}
	if err := json.Unmarshal([]byte(text), &decoded); err != nil {
		t.Fatal(err)
	}
	if len(decoded.Sessions) != len(plan) || decoded.Sessions[0] != plan[0] {
		t.Fatal("maximum escaped plan failed HTTP roundtrip")
	}
}

func TestMCPCompanyTools(t *testing.T) {
	ts, _ := newTestServer(t)
	cs := connect(t, ts)
	lt, err := cs.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	have := map[string]bool{}
	for _, tool := range lt.Tools {
		have[tool.Name] = true
	}
	if !have["search_companies"] || !have["company_details"] {
		t.Fatalf("tools: %v", have)
	}
	txt, isErr := callText(t, cs, "search_companies", map[string]any{"facts": []string{"seed", "actively fundraising"}, "tags": []string{"drone"}})
	var sr struct {
		Results []map[string]any `json:"results"`
	}
	if err := json.Unmarshal([]byte(txt), &sr); err != nil || isErr || len(sr.Results) != 1 || sr.Results[0]["id"] != "company:62217" {
		t.Fatalf("search_companies = %s", txt)
	}
	for _, k := range []string{"id", "name", "tier", "industry", "location", "facts", "url"} {
		if _, ok := sr.Results[0][k]; !ok {
			t.Errorf("row lacks %s", k)
		}
	}
	txt, _ = callText(t, cs, "company_details", map[string]any{"company_ids": []string{"company:62217", "101575", "company:999"}})
	var objs []map[string]any
	if err := json.Unmarshal([]byte(txt), &objs); err != nil || len(objs) != 2 || objs[0]["id"] != "company:62217" || objs[1]["id"] != "company:101575" {
		t.Fatalf("company_details = %.300s", txt)
	}
	txt, _ = callText(t, cs, "info", map[string]any{})
	if !strings.Contains(txt, `"companies":8`) || !strings.Contains(txt, `"company_facets"`) {
		t.Errorf("info lacks companies: %.300s", txt)
	}
	if init := cs.InitializeResult(); !strings.Contains(init.Instructions, "search_companies") || strings.Contains(init.Instructions, "no company IDs") {
		t.Errorf("instructions: %s", init.Instructions)
	}
	if ServerVersion != "2.1.0" {
		t.Errorf("version %s", ServerVersion)
	}
}

func TestFetchCompany(t *testing.T) {
	ts, _ := newTestServer(t)
	cs := connect(t, ts)
	txt, _ := callText(t, cs, "fetch", map[string]any{"id": "company:62217"})
	var f struct {
		ID, Title, Text, URL string
		Metadata             map[string]any
	}
	if err := json.Unmarshal([]byte(txt), &f); err != nil || f.ID != "company:62217" || f.Title != "MakeLocal" ||
		f.URL != "https://attend.websummit.com/lis26/company/62217" ||
		!strings.HasPrefix(f.Text, "Beta · Defence & security · Kyiv, Ukraine\nSeed; Actively Fundraising; Markets: Europe\nDrone manufacturing hubs.") ||
		f.Metadata["tier"] != "Beta" || f.Metadata["location"] != "Kyiv, Ukraine" {
		t.Fatalf("fetch company = %s", txt)
	}
	txt, _ = callText(t, cs, "fetch", map[string]any{"id": "company:424242"})
	if txt != `{"error":"unknown company"}` {
		t.Errorf("unknown company = %s", txt)
	}
}
