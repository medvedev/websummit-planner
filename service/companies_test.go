package main

import (
	"encoding/json"
	"os"
	"slices"
	"strings"
	"testing"
)

func companyFixture(t testing.TB) *Companies {
	t.Helper()
	c, err := LoadCompanies("testdata/companies.json")
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func ids(rows []CompanyRow) []string {
	out := []string{}
	for _, r := range rows {
		out = append(out, r.ID)
	}
	return out
}

func TestCompanySearchFactSubstringAND(t *testing.T) {
	c := companyFixture(t)
	// "seed" matches Seed and Pre-seed; AND with "actively fundraising".
	got := ids(c.Search(CompanySearchArgs{Facts: []string{"seed", "ACTIVELY fundraising"}}))
	if want := []string{"company:3", "company:62217"}; !slices.Equal(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}

func TestCompanySearchTagExactCaseInsensitive(t *testing.T) {
	c := companyFixture(t)
	got := ids(c.Search(CompanySearchArgs{Tags: []string{"DRONE"}}))
	if want := []string{"company:62217", "company:4", "company:7"}; !slices.Equal(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
	if got := c.Search(CompanySearchArgs{Tags: []string{"dron"}}); len(got) != 0 {
		t.Fatalf("tag must be exact, got %v", ids(got))
	}
	// query is a substring over name, description, location and tags
	if got := ids(c.Search(CompanySearchArgs{Query: "dro"})); !slices.Contains(got, "company:4") || !slices.Contains(got, "company:62217") {
		t.Fatalf("query substring: %v", got)
	}
	if got := c.Search(CompanySearchArgs{Query: "kyiv"}); len(got) != 1 || got[0].ID != "company:62217" {
		t.Fatalf("location query: %v", ids(got))
	}
}

func TestCompanySearchOrderTierThenName(t *testing.T) {
	c := companyFixture(t)
	got := ids(c.Search(CompanySearchArgs{Limit: 100}))
	want := []string{"company:101575", "company:3", "company:8", "company:62217", "company:5", "company:4", "company:6", "company:7"}
	if !slices.Equal(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
	if got := c.Search(CompanySearchArgs{Limit: 2}); len(got) != 2 {
		t.Fatalf("limit: %d", len(got))
	}
	rows := c.Search(CompanySearchArgs{Tier: "Beta", Industry: "AI", Country: "Portugal"})
	if len(rows) != 1 || rows[0].ID != "company:8" || rows[0].URL != "https://attend.websummit.com/lis26/company/8" {
		t.Fatalf("exact filters: %+v", rows)
	}
	b, _ := json.Marshal(c.Search(CompanySearchArgs{Query: "NoTier"}))
	if !strings.Contains(string(b), `"facts":[]`) || !strings.Contains(string(b), `"tier":null`) {
		t.Fatalf("row json: %s", b)
	}
}

func TestCompanyDetailsPrefixDedupLimit(t *testing.T) {
	c := companyFixture(t)
	got := c.Details([]string{"company:62217", "62217", "999", "company:3", "nope"})
	if len(got) != 2 {
		t.Fatalf("want 2 got %d", len(got))
	}
	var first map[string]any
	if err := json.Unmarshal(got[0], &first); err != nil || first["id"] != "company:3" { // id order
		t.Fatalf("first: %v %v", first["id"], err)
	}
	many := make([]string, 0, 30)
	for i := 0; i < 30; i++ {
		many = append(many, "company:3")
	}
	many = append(many[:20], "company:62217")
	if got := c.Details(many); len(got) != 1 {
		t.Fatalf("cap at 20 inputs before dedupe: %d", len(got))
	}
	if n, ok := CompanyPlanID("company:12"); !ok || n != 12 {
		t.Fatal("CompanyPlanID")
	}
	for _, bad := range []string{"12", "company:", "company:0", "company:-1", "company:1x", "Company:1"} {
		if _, ok := CompanyPlanID(bad); ok {
			t.Fatalf("CompanyPlanID(%q) should fail", bad)
		}
	}
}

func TestCompanyFacets(t *testing.T) {
	f := companyFixture(t).Facets()
	if f["tiers"]["Beta"] != 2 || f["facts"]["Seed"] != 3 || f["industries"]["AI"] != 1 || f["countries"]["Portugal"] != 2 {
		t.Fatalf("facets: %v", f)
	}
}

func TestParseCompaniesRejectsInvalid(t *testing.T) {
	good, _ := os.ReadFile("testdata/companies.json")
	if _, err := ParseCompanies(good); err != nil {
		t.Fatal(err)
	}
	const notice = `"info":{"notice":"n"}`
	cases := map[string]string{
		"duplicate id":   `{` + notice + `,"companies":[{"id":"company:1","name":"A"},{"id":"company:1","name":"B"}]}`,
		"missing name":   `{` + notice + `,"companies":[{"id":"company:1"}]}`,
		"missing notice": `{"info":{},"companies":[{"id":"company:1","name":"A"}]}`,
		"trailing data":  `{` + notice + `,"companies":[{"id":"company:1","name":"A"}]} {}`,
		"empty":          `{` + notice + `,"companies":[]}`,
		"bad id":         `{` + notice + `,"companies":[{"id":"1","name":"A"}]}`,
		"not json":       `nope`,
	}
	for name, in := range cases {
		if _, err := ParseCompanies([]byte(in)); err == nil {
			t.Errorf("%s: want error", name)
		}
	}
	if _, err := ParseCompanies([]byte(`{` + notice + `,"companies":[{"id":"company:1","name":"A"}]}`)); err != nil {
		t.Fatalf("minimal valid: %v", err)
	}
}
