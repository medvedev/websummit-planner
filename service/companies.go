package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"slices"
	"strconv"
	"strings"
)

// Companies is the immutable company catalog (companies.json from export_text.py).
// Companies are untimed: they never take part in conflict checks or calendar export.
type Companies struct {
	list   []*Company  // snapshot order (ascending id)
	byNum  map[int]int // numeric id -> index in list
	sorted []*Company  // tier rank, name, id (search order)
	notice string
	info   map[string]any
}

// Company is one catalog entry; raw keeps the exported details object verbatim.
type Company struct {
	Num                      int
	ID, Name, URL            string
	Tier, Industry, Location *string
	Country                  string
	Facts, Tags              []string
	raw                      json.RawMessage
	lcName, lcDesc, lcLoc    string
	lcTags, lcFacts          []string
	rank                     int
}

type companySnapshot struct {
	ID       *string  `json:"id"`
	Name     *string  `json:"name"`
	Tier     *string  `json:"tier"`
	Industry *string  `json:"industry"`
	Country  *string  `json:"country"`
	Location *string  `json:"location"`
	Desc     *string  `json:"description"`
	URL      *string  `json:"url"`
	Facts    []string `json:"facts"`
	Tags     []string `json:"tags"`
}

// CompanySearchArgs mirrors the search_companies tool input.
type CompanySearchArgs struct {
	Query    string   `json:"query,omitempty"`
	Industry string   `json:"industry,omitempty"`
	Country  string   `json:"country,omitempty"`
	Tier     string   `json:"tier,omitempty"`
	Tags     []string `json:"tags,omitempty"`
	Facts    []string `json:"facts,omitempty"`
	Limit    int      `json:"limit,omitempty"`
}

// CompanyRow is the compact search result.
type CompanyRow struct {
	ID       string   `json:"id"`
	Name     string   `json:"name"`
	Tier     *string  `json:"tier"`
	Industry *string  `json:"industry"`
	Location *string  `json:"location"`
	Facts    []string `json:"facts"`
	URL      string   `json:"url"`
}

// CompanyPlanID parses "company:<n>" (n > 0). A bare number is not a plan ID.
func CompanyPlanID(id string) (int, bool) {
	rest, ok := strings.CutPrefix(id, "company:")
	if !ok || rest == "" || rest[0] < '1' || rest[0] > '9' {
		return 0, false
	}
	n, err := strconv.Atoi(rest)
	if err != nil || n <= 0 || strconv.Itoa(n) != rest {
		return 0, false
	}
	return n, true
}

// parseCompanyRef accepts "company:<n>" or a bare "<n>".
func parseCompanyRef(s string) (int, bool) {
	if n, ok := CompanyPlanID(s); ok {
		return n, true
	}
	return CompanyPlanID("company:" + s)
}

func LoadCompanies(path string) (*Companies, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	c, err := ParseCompanies(b)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return c, nil
}

func tierRank(t *string) int {
	if t == nil {
		return 5
	}
	switch *t {
	case "Partner":
		return 0
	case "Growth":
		return 1
	case "Beta":
		return 2
	case "Alpha":
		return 3
	case "Media Partner":
		return 4
	}
	return 5
}

// ParseCompanies validates companies.json and builds the indexes. Any defect fails.
func ParseCompanies(b []byte) (*Companies, error) {
	var top struct {
		Info      map[string]any    `json:"info"`
		Companies []json.RawMessage `json:"companies"`
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	if err := dec.Decode(&top); err != nil {
		return nil, fmt.Errorf("invalid companies JSON: %w", err)
	}
	if _, err := dec.Token(); err != io.EOF {
		return nil, errors.New("invalid companies JSON: trailing data")
	}
	notice, _ := top.Info["notice"].(string)
	if notice == "" {
		return nil, errors.New("companies: info.notice must be a non-empty string")
	}
	if len(top.Companies) == 0 {
		return nil, errors.New("companies: no companies")
	}
	c := &Companies{byNum: make(map[int]int, len(top.Companies)), notice: notice, info: top.Info}
	for i, raw := range top.Companies {
		var p companySnapshot
		if err := json.Unmarshal(raw, &p); err != nil {
			return nil, fmt.Errorf("company %d: %w", i, err)
		}
		if p.ID == nil {
			return nil, fmt.Errorf("company %d: missing id", i)
		}
		n, ok := CompanyPlanID(*p.ID)
		if !ok {
			return nil, fmt.Errorf("company %d: id %q must be company:<positive number>", i, *p.ID)
		}
		if p.Name == nil || *p.Name == "" {
			return nil, fmt.Errorf("%s: missing name", *p.ID)
		}
		if _, dup := c.byNum[n]; dup {
			return nil, fmt.Errorf("company %d: duplicate id %q", i, *p.ID)
		}
		var compact bytes.Buffer
		if err := json.Compact(&compact, raw); err != nil {
			return nil, err
		}
		co := &Company{
			Num: n, ID: *p.ID, Name: *p.Name, Tier: p.Tier, Industry: p.Industry, Location: p.Location,
			Country: deref(p.Country), Facts: p.Facts, Tags: p.Tags, raw: compact.Bytes(),
			URL:    "https://attend.websummit.com/lis26/company/" + strconv.Itoa(n),
			lcName: strings.ToLower(*p.Name), lcDesc: lower(p.Desc), lcLoc: lower(p.Location), rank: tierRank(p.Tier),
		}
		for _, t := range p.Tags {
			co.lcTags = append(co.lcTags, strings.ToLower(t))
		}
		for _, f := range p.Facts {
			co.lcFacts = append(co.lcFacts, strings.ToLower(f))
		}
		c.byNum[n] = i
		c.list = append(c.list, co)
	}
	c.sorted = slices.Clone(c.list)
	slices.SortFunc(c.sorted, func(a, b *Company) int {
		if a.rank != b.rank {
			return a.rank - b.rank
		}
		if r := strings.Compare(a.Name, b.Name); r != 0 {
			return r
		}
		return a.Num - b.Num
	})
	return c, nil
}

// Notice is the company data notice.
func (c *Companies) Notice() string { return c.notice }

// Count is the number of companies.
func (c *Companies) Count() int { return len(c.list) }

// Search applies the filters of planner.py companies: query is a case-insensitive
// substring over name, description, location and tags; industry/country/tier are
// exact; tags are exact case-insensitive; facts are case-insensitive substrings;
// all filters combine with AND. Order: tier rank, name, id.
func (c *Companies) Search(a CompanySearchArgs) []CompanyRow {
	limit := a.Limit
	if limit == 0 {
		limit = defaultLimit
	}
	limit = min(max(limit, 1), maxLimit)
	q := strings.ToLower(a.Query)
	tags := make([]string, len(a.Tags))
	for i, t := range a.Tags {
		tags[i] = strings.ToLower(t)
	}
	facts := make([]string, len(a.Facts))
	for i, f := range a.Facts {
		facts[i] = strings.ToLower(f)
	}
	out := make([]CompanyRow, 0, min(limit, 64))
next:
	for _, co := range c.sorted {
		if a.Industry != "" && deref(co.Industry) != a.Industry || a.Country != "" && co.Country != a.Country ||
			a.Tier != "" && deref(co.Tier) != a.Tier {
			continue
		}
		if q != "" && !strings.Contains(co.lcName, q) && !strings.Contains(co.lcDesc, q) && !strings.Contains(co.lcLoc, q) &&
			!slices.ContainsFunc(co.lcTags, func(t string) bool { return strings.Contains(t, q) }) {
			continue
		}
		for _, t := range tags {
			if !slices.Contains(co.lcTags, t) {
				continue next
			}
		}
		for _, f := range facts {
			if !slices.ContainsFunc(co.lcFacts, func(x string) bool { return strings.Contains(x, f) }) {
				continue next
			}
		}
		fs := co.Facts
		if fs == nil {
			fs = []string{}
		}
		out = append(out, CompanyRow{co.ID, co.Name, co.Tier, co.Industry, co.Location, fs, co.URL})
		if len(out) == limit {
			break
		}
	}
	return out
}

// Details returns the exported details objects for the first 20 refs
// ("company:<n>" or "<n>"), deduplicated, in id order; unknown refs are dropped.
func (c *Companies) Details(ids []string) []json.RawMessage {
	if len(ids) > maxDetails {
		ids = ids[:maxDetails]
	}
	idx := make([]int, 0, len(ids))
	for _, id := range ids {
		n, ok := parseCompanyRef(id)
		if !ok {
			continue
		}
		if i, ok := c.byNum[n]; ok && !slices.Contains(idx, i) {
			idx = append(idx, i)
		}
	}
	slices.Sort(idx)
	out := make([]json.RawMessage, len(idx))
	for n, i := range idx {
		out[n] = c.list[i].raw
	}
	return out
}

// Lookup returns a company by "company:<n>" or "<n>".
func (c *Companies) Lookup(id string) (*Company, bool) {
	n, ok := parseCompanyRef(id)
	if !ok {
		return nil, false
	}
	i, ok := c.byNum[n]
	if !ok {
		return nil, false
	}
	return c.list[i], true
}

// Facets counts companies per tier, industry, country and fact.
func (c *Companies) Facets() map[string]map[string]int {
	f := map[string]map[string]int{"tiers": {}, "industries": {}, "countries": {}, "facts": {}}
	for _, co := range c.list {
		if co.Tier != nil {
			f["tiers"][*co.Tier]++
		}
		if co.Industry != nil {
			f["industries"][*co.Industry]++
		}
		if co.Country != "" {
			f["countries"][co.Country]++
		}
		seen := map[string]bool{}
		for _, x := range co.Facts {
			if !seen[x] {
				seen[x] = true
				f["facts"][x]++
			}
		}
	}
	return f
}
