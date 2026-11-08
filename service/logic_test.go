package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"net/url"
	"os"
	"reflect"
	"strings"
	"testing"
)

// golden holds captured outputs of the former TypeScript service (baseline da04b60).
type golden struct {
	Search []struct {
		Args    SearchArgs      `json:"args"`
		Results json.RawMessage `json:"results"`
	} `json:"search"`
	Details []struct {
		Args    []string        `json:"args"`
		Results json.RawMessage `json:"results"`
	} `json:"details"`
	CheckPlan []struct {
		Plan      []PlanEntry     `json:"plan"`
		BufferMin int             `json:"buffer_min"`
		Result    json.RawMessage `json:"result"`
	} `json:"check_plan"`
	Encode []struct {
		Plan    []PlanEntry `json:"plan"`
		Code    string      `json:"code"`
		Decoded []PlanEntry `json:"decoded"`
	} `json:"encode"`
	DecodeErrors  []string `json:"decode_errors"`
	DecodeLenient []struct {
		Code    string      `json:"code"`
		Decoded []PlanEntry `json:"decoded"`
	} `json:"decode_lenient"`
}

func loadGolden(t testing.TB) golden {
	t.Helper()
	b, err := os.ReadFile("testdata/golden.json")
	if err != nil {
		t.Fatal(err)
	}
	var g golden
	if err := json.Unmarshal(b, &g); err != nil {
		t.Fatal(err)
	}
	return g
}

func fixture(t testing.TB) *Dataset {
	t.Helper()
	d, err := LoadDataset("testdata/schedule.json")
	if err != nil {
		t.Fatal(err)
	}
	return d
}

// sameJSON compares semantically (key order and whitespace ignored).
func sameJSON(t *testing.T, label string, got any, want json.RawMessage) {
	t.Helper()
	gb, err := marshalJSON(got)
	if err != nil {
		t.Fatal(err)
	}
	var g, w any
	if err := json.Unmarshal(gb, &g); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(want, &w); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(g, w) {
		t.Errorf("%s mismatch\n got: %.600s\nwant: %.600s", label, gb, want)
	}
}

func TestGoldenSearchParity(t *testing.T) {
	d, g := fixture(t), loadGolden(t)
	for _, c := range g.Search {
		a, _ := json.Marshal(c.Args)
		sameJSON(t, "search "+string(a), map[string]any{"results": d.Search(c.Args)}, json.RawMessage(`{"results":`+string(c.Results)+`}`))
	}
}

func TestGoldenDetailsParity(t *testing.T) {
	d, g := fixture(t), loadGolden(t)
	for _, c := range g.Details {
		sameJSON(t, "details "+strings.Join(c.Args, ","), d.Details(c.Args), c.Results)
	}
}

func TestGoldenCheckPlanParity(t *testing.T) {
	d, g := fixture(t), loadGolden(t)
	if len(g.CheckPlan) < 50 {
		t.Fatalf("expected many check_plan goldens, got %d", len(g.CheckPlan))
	}
	for i, c := range g.CheckPlan {
		got := d.CheckPlan(c.Plan, c.BufferMin)
		gb, _ := marshalJSON(got)
		// Exact bytes too: key order and conflict order must match the worker.
		var w any
		_ = json.Unmarshal(c.Result, &w)
		wb, _ := marshalJSON(w)
		var gg any
		_ = json.Unmarshal(gb, &gg)
		gb2, _ := marshalJSON(gg)
		if !bytes.Equal(gb2, wb) {
			t.Errorf("check_plan case %d (buffer %d) mismatch\n got: %.800s\nwant: %.800s", i, c.BufferMin, gb, c.Result)
		}
	}
}

func TestGoldenPlanCodesByteExact(t *testing.T) {
	g := loadGolden(t)
	for _, c := range g.Encode {
		code, err := EncodePlan(c.Plan)
		if err != nil {
			t.Fatal(err)
		}
		if code != c.Code {
			t.Errorf("encode %v:\n got %s\nwant %s", c.Plan, code, c.Code)
		}
		dec, err := DecodePlan(c.Code)
		if err != nil {
			t.Fatalf("decode %s: %v", c.Code, err)
		}
		if !reflect.DeepEqual(norm(dec), norm(c.Decoded)) {
			t.Errorf("decode %s = %v want %v", c.Code, dec, c.Decoded)
		}
	}
	for _, code := range g.DecodeErrors {
		if _, err := DecodePlan(code); err == nil || err.Error() != "bad plan code" {
			t.Errorf("DecodePlan(%q) err = %v, want bad plan code", code, err)
		}
	}
	for _, c := range g.DecodeLenient {
		dec, err := DecodePlan(c.Code)
		if err != nil || !reflect.DeepEqual(dec, c.Decoded) {
			t.Errorf("lenient DecodePlan(%q) = %v, %v want %v", c.Code, dec, err, c.Decoded)
		}
	}
}

func norm(p []PlanEntry) []PlanEntry {
	if p == nil {
		return []PlanEntry{}
	}
	return p
}

func TestDecodePlanRejectsGoOnlyTraps(t *testing.T) {
	enc := func(s string) string { return base64.RawURLEncoding.EncodeToString([]byte(s)) }
	for _, raw := range []string{
		`[["x","constructor"]]`, // truthy in the TS lookup table; must be rejected
		`[["x","toString"]]`,
		`[["x",["a"]]]`,
		`[["x",null]]`,
		`null`,
		"[[\"\xff\",\"a\"]]", // invalid UTF-8 must not be silently replaced
	} {
		if _, err := DecodePlan(enc(raw)); err == nil {
			t.Errorf("DecodePlan(%s) accepted", raw)
		}
	}
	if _, err := DecodePlan(strings.Repeat("A", 24001)); err == nil {
		t.Error("oversized code accepted")
	}
}

func TestEncodePlanLimit(t *testing.T) {
	p := make([]PlanEntry, 201)
	for i := range p {
		p[i] = PlanEntry{ID: "x", Status: "must"}
	}
	if _, err := EncodePlan(p); err == nil {
		t.Fatal("expected plan too long")
	}
	if _, err := EncodePlan([]PlanEntry{{ID: "x", Status: "bogus"}}); err == nil {
		t.Fatal("expected invalid status error")
	}
}

func TestUnicodeRoundTripAndSearch(t *testing.T) {
	p := []PlanEntry{{ID: "сесія-1", Status: "maybe"}, {ID: "🎉\u2028\"\\", Status: "must"}}
	code, err := EncodePlan(p)
	if err != nil {
		t.Fatal(err)
	}
	if strings.ContainsAny(code, "+/=") {
		t.Errorf("code not base64url: %s", code)
	}
	back, err := DecodePlan(code)
	if err != nil || !reflect.DeepEqual(back, p) {
		t.Fatalf("round trip = %v, %v", back, err)
	}

	d := mustParse(t, snapshot(
		sess("u1", "official", "2026-11-10", "10:00", "11:00", `"title":"Ética e IA na SAÚDE","description":"Розмова про ШІ"`),
		sess("u2", "official", "2026-11-10", "10:00", "11:00", `"title":"Party 🎉","speakers":"Zoë Ångström"`),
		sess("u3", "official", "2026-11-10", "10:00", "11:00", `"title":"abc","description":"def"`),
	))
	cases := map[string][]string{
		"saúde": {"u1"}, "ÉTICA": {"u1"}, "шІ": {"u1"}, "🎉": {"u2"}, "zoë ång": {"u2"},
		"cdef": nil, // fields are matched separately, never across a boundary
	}
	for q, want := range cases {
		var got []string
		for _, r := range d.Search(SearchArgs{Query: q}) {
			got = append(got, r.ID)
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("search %q = %v want %v", q, got, want)
		}
	}
}

func TestCheckPlanLatestStatusWinsAndUnknownOrder(t *testing.T) {
	d := mustParse(t, snapshot(
		sess("a", "official", "2026-11-10", "10:00", "11:00", `"stage":"S1"`),
		sess("b", "official", "2026-11-10", "10:30", "11:30", `"stage":"S2"`),
		sess("c", "official", "2026-11-10", "11:35", "12:00", `"stage":"S3"`),
	))
	r := d.CheckPlan([]PlanEntry{
		{"zzz", "must"}, {"a", "must"}, {"b", "maybe"}, {"b", "removed"}, {"zzz", "maybe"}, {"b", "must"}, {"q", "skip"},
	}, 0)
	if !reflect.DeepEqual(r.Unknown, []string{"zzz", "zzz", "q"}) {
		t.Errorf("unknown = %v", r.Unknown)
	}
	if len(r.Plan) != 2 || r.Plan[1].ID != "b" || r.Plan[1].Status != "must" {
		t.Errorf("plan = %+v", r.Plan)
	}
	if len(r.Conflicts) != 1 || r.Conflicts[0].Kind != "overlap" {
		t.Errorf("conflicts = %+v", r.Conflicts)
	}
	// Later skip removes it from the active plan.
	r = d.CheckPlan([]PlanEntry{{"a", "must"}, {"b", "must"}, {"b", "skip"}}, 0)
	if len(r.Plan) != 1 || len(r.Conflicts) != 0 {
		t.Errorf("skip not applied: %+v", r)
	}
	// 5-minute gap between b and c on different stages: tight only with buffer > 5.
	r = d.CheckPlan([]PlanEntry{{"b", "must"}, {"c", "must"}}, 5)
	if len(r.Conflicts) != 0 {
		t.Errorf("buffer 5 should not conflict: %+v", r.Conflicts)
	}
	r = d.CheckPlan([]PlanEntry{{"b", "must"}, {"c", "must"}}, 6)
	if len(r.Conflicts) != 1 || r.Conflicts[0].Kind != "tight-gap" {
		t.Errorf("buffer 6 should be tight-gap: %+v", r.Conflicts)
	}
	// Empty input still encodes [] not null.
	b, _ := marshalJSON(d.CheckPlan(nil, 0))
	if string(b) != `{"plan":[],"conflicts":[],"unknown":[]}` {
		t.Errorf("empty result = %s", b)
	}
}

func TestSearchDefaultsAndBounds(t *testing.T) {
	d := fixture(t)
	if n := len(d.Search(SearchArgs{})); n != 30 {
		t.Errorf("default limit gave %d rows", n)
	}
	for _, r := range d.Search(SearchArgs{Limit: 100}) {
		if r.Kind != "official" {
			t.Fatalf("default kind returned %s", r.Kind)
		}
	}
	side := d.Search(SearchArgs{Kind: "side", Limit: 100})
	if len(side) == 0 {
		t.Fatal("no side events")
	}
	for _, r := range side {
		if !strings.HasPrefix(r.ID, "side:") || r.URL == "https://websummit.com/schedule/" {
			t.Errorf("bad side row %+v", r)
		}
	}
	if n := len(d.Search(SearchArgs{Limit: 1000})); n > 100 {
		t.Errorf("limit not clamped: %d", n)
	}
	if n := len(d.Search(SearchArgs{Day: "2099-01-01"})); n != 0 {
		t.Errorf("unknown day returned %d", n)
	}
}

func TestDetailsKeepsAllFields(t *testing.T) {
	d := fixture(t)
	var long string
	for _, s := range d.sessions {
		if len(s.ID) > 64 {
			long = s.ID
			break
		}
	}
	if long == "" {
		t.Fatal("fixture lacks a >64 char side id")
	}
	rows := d.Details([]string{long, "nope"})
	if len(rows) != 1 {
		t.Fatalf("details rows = %d", len(rows))
	}
	var m map[string]any
	_ = json.Unmarshal(rows[0], &m)
	for _, k := range []string{"address", "ticket_url", "organizer", "price", "currency", "is_free", "online", "end_known", "url"} {
		if _, ok := m[k]; !ok {
			t.Errorf("details lost %s", k)
		}
	}
	// More than 20 ids: only the first 20 are considered.
	ids := make([]string, 0, 25)
	for _, s := range d.sessions[:25] {
		ids = append(ids, s.ID)
	}
	if n := len(d.Details(ids)); n != 20 {
		t.Errorf("details over cap = %d", n)
	}
}

func TestFetchShape(t *testing.T) {
	d := fixture(t)
	s := d.sessions[0]
	f := d.Fetch(s.ID)
	if f["id"] != s.ID || f["title"] != s.Title || f["url"] == "" || f["text"] == "" {
		t.Errorf("fetch = %v", f)
	}
	md := f["metadata"].(map[string]any)
	if md["day"] != s.Day || md["kind"] != s.Kind {
		t.Errorf("metadata = %v", md)
	}
	if !strings.HasPrefix(f["text"].(string), s.Day+" "+s.Start+"-"+s.End+" ") {
		t.Errorf("text = %q", f["text"])
	}
	if e := d.Fetch("nope"); e["error"] != "unknown session" {
		t.Errorf("unknown fetch = %v", e)
	}
}

func TestOfficialAppLinks(t *testing.T) {
	d := fixture(t)
	results := d.Search(SearchArgs{Limit: 1})
	s := results[0]
	want := "https://link.websummit.com/?url=" + url.QueryEscape("https://attend.websummit.com/dl/lis26/event?id="+s.ID+"&mobile=true")
	if s.URL != want || d.Fetch(s.ID)["url"] != want {
		t.Fatal("search/fetch must use app links")
	}
	var detail map[string]any
	if err := json.Unmarshal(d.Details([]string{s.ID})[0], &detail); err != nil {
		t.Fatal(err)
	}
	if detail["url"] != want {
		t.Fatal("details must use app links")
	}
	side := d.Search(SearchArgs{Kind: "side", Limit: 1})[0]
	if strings.HasPrefix(side.URL, "https://link.websummit.com/") {
		t.Fatal("side event URL replaced")
	}
}
