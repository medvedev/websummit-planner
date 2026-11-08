package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"regexp"
	"slices"
	"strings"
	"time"
)

const (
	// MaxIDLen bounds session IDs in tool schemas. The legacy worker used 64,
	// which made 59 real side-event IDs (up to 77 chars) unreachable.
	MaxIDLen     = 128
	defaultLimit = 30
	maxLimit     = 100
	maxDetails   = 20
	scheduleURL  = "https://websummit.com/schedule/"
)

var dayRe = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)

// Session is one immutable schedule row. raw keeps the snapshot JSON so
// details returns every field (address, ticket_url, future fields) verbatim.
type Session struct {
	ID, Day, Start, End, Title, Kind string
	Stage, Track                     *string
	URL                              *string
	raw                              json.RawMessage
	startMs, endMs                   int64
	lcTitle, lcDesc, lcSpeakers      string
}

// Dataset is built once at startup and only read afterwards (safe for concurrent use).
type Dataset struct {
	sessions  []*Session
	byID      map[string]int
	byKind    map[string][]int            // "official" | "side" | "all" -> snapshot order
	byKindDay map[string]map[string][]int // kind -> day -> snapshot order
	info      map[string]any
	notice    string
	sha       string
	firstDay  map[string]string
	lastDay   map[string]string
}

type snapshotSession struct {
	ID          *string `json:"id"`
	Day         *string `json:"day"`
	Start       *string `json:"start"`
	End         *string `json:"end"`
	Stage       *string `json:"stage"`
	Track       *string `json:"track"`
	Title       *string `json:"title"`
	Description *string `json:"description"`
	Speakers    *string `json:"speakers"`
	Kind        *string `json:"kind"`
	StartsUTC   *string `json:"starts_utc"`
	EndsUTC     *string `json:"ends_utc"`
	URL         *string `json:"url"`
}

// LoadDataset reads and validates a schedule snapshot (export_text.py format).
func LoadDataset(path string) (*Dataset, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	d, err := ParseDataset(b)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return d, nil
}

// ParseDataset validates the snapshot and builds the indexes. Any defect fails.
func ParseDataset(b []byte) (*Dataset, error) {
	var top struct {
		Info     map[string]any    `json:"info"`
		Sessions []json.RawMessage `json:"sessions"`
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	if err := dec.Decode(&top); err != nil {
		return nil, fmt.Errorf("invalid snapshot JSON: %w", err)
	}
	if _, err := dec.Token(); err != io.EOF {
		return nil, errors.New("invalid snapshot JSON: trailing data")
	}
	if top.Info == nil {
		return nil, errors.New("snapshot: missing info")
	}
	notice, _ := top.Info["notice"].(string)
	if notice == "" {
		return nil, errors.New("snapshot: info.notice must be a non-empty string")
	}
	if len(top.Sessions) == 0 {
		return nil, errors.New("snapshot: no sessions")
	}
	sum := sha256.Sum256(b)
	d := &Dataset{
		sessions:  make([]*Session, 0, len(top.Sessions)),
		byID:      make(map[string]int, len(top.Sessions)),
		byKind:    map[string][]int{},
		byKindDay: map[string]map[string][]int{},
		info:      top.Info,
		notice:    notice,
		sha:       hex.EncodeToString(sum[:]),
		firstDay:  map[string]string{},
		lastDay:   map[string]string{},
	}
	for i, raw := range top.Sessions {
		s, err := parseSession(raw)
		if err != nil {
			return nil, fmt.Errorf("snapshot session %d: %w", i, err)
		}
		if _, dup := d.byID[s.ID]; dup {
			return nil, fmt.Errorf("snapshot session %d: duplicate id %q", i, s.ID)
		}
		d.byID[s.ID] = i
		d.sessions = append(d.sessions, s)
		for _, k := range []string{s.Kind, "all"} {
			d.byKind[k] = append(d.byKind[k], i)
			if d.byKindDay[k] == nil {
				d.byKindDay[k] = map[string][]int{}
			}
			d.byKindDay[k][s.Day] = append(d.byKindDay[k][s.Day], i)
			if f := d.firstDay[k]; f == "" || s.Day < f {
				d.firstDay[k] = s.Day
			}
			if s.Day > d.lastDay[k] {
				d.lastDay[k] = s.Day
			}
		}
	}
	return d, nil
}

func parseSession(raw json.RawMessage) (*Session, error) {
	var p snapshotSession
	if err := json.Unmarshal(raw, &p); err != nil {
		return nil, err
	}
	if p.ID == nil {
		return nil, errors.New("not an object with an id")
	}
	id := *p.ID
	if id == "" || len(id) > MaxIDLen {
		return nil, fmt.Errorf("id %q must be 1..%d bytes", id, MaxIDLen)
	}
	for name, v := range map[string]*string{"day": p.Day, "start": p.Start, "end": p.End, "title": p.Title, "kind": p.Kind, "starts_utc": p.StartsUTC, "ends_utc": p.EndsUTC} {
		if v == nil {
			return nil, fmt.Errorf("%q: missing %s", id, name)
		}
	}
	if *p.Kind != "official" && *p.Kind != "side" {
		return nil, fmt.Errorf("%q: kind %q", id, *p.Kind)
	}
	if !dayRe.MatchString(*p.Day) {
		return nil, fmt.Errorf("%q: day %q", id, *p.Day)
	}
	st, err := time.Parse(time.RFC3339, *p.StartsUTC)
	if err != nil {
		return nil, fmt.Errorf("%q: starts_utc: %w", id, err)
	}
	en, err := time.Parse(time.RFC3339, *p.EndsUTC)
	if err != nil {
		return nil, fmt.Errorf("%q: ends_utc: %w", id, err)
	}
	if en.Before(st) {
		return nil, fmt.Errorf("%q: ends before it starts", id)
	}
	if *p.Kind == "official" {
		var fields map[string]json.RawMessage
		_ = json.Unmarshal(raw, &fields)
		fields["url"], _ = json.Marshal("https://attend.websummit.com/lis26/events/" + id)
		raw, _ = json.Marshal(fields)
	}
	var compact bytes.Buffer
	if err := json.Compact(&compact, raw); err != nil {
		return nil, err
	}
	return &Session{
		ID: id, Day: *p.Day, Start: *p.Start, End: *p.End, Title: *p.Title, Kind: *p.Kind,
		Stage: p.Stage, Track: p.Track, URL: p.URL, raw: compact.Bytes(),
		startMs: st.UnixMilli(), endMs: en.UnixMilli(),
		lcTitle: strings.ToLower(*p.Title), lcDesc: lower(p.Description), lcSpeakers: lower(p.Speakers),
	}, nil
}

func lower(s *string) string {
	if s == nil {
		return ""
	}
	return strings.ToLower(*s)
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// Notice is the snapshot's data notice.
func (d *Dataset) Notice() string { return d.notice }

// Info returns snapshot info plus server/snapshot version fields (a fresh map).
func (d *Dataset) Info() map[string]any {
	m := make(map[string]any, len(d.info)+4)
	for k, v := range d.info {
		m[k] = v
	}
	m["notice"] = d.notice
	m["snapshot_sha256"] = d.sha
	m["server_version"] = ServerVersion
	m["dates_notice"] = d.datesNotice()
	return m
}

func (d *Dataset) datesNotice() string {
	s := fmt.Sprintf("Official sessions run %s to %s", d.firstDay["official"], d.lastDay["official"])
	if d.firstDay["side"] != "" {
		s += fmt.Sprintf("; community side events run %s to %s", d.firstDay["side"], d.lastDay["side"])
	}
	return s + ". Times are Europe/Lisbon local (UTC+0 in November); *_utc fields are UTC. The schedule may have changed after the snapshot date."
}

func (d *Dataset) urlFor(s *Session) string {
	if s.Kind == "official" {
		return "https://attend.websummit.com/lis26/events/" + s.ID
	}
	if s.URL != nil && *s.URL != "" {
		return *s.URL
	}
	return scheduleURL
}

// SearchArgs mirrors the search tool input. Empty strings mean "no filter".
type SearchArgs struct {
	Query string `json:"query,omitempty"`
	Day   string `json:"day,omitempty"`
	Track string `json:"track,omitempty"`
	Stage string `json:"stage,omitempty"`
	Limit int    `json:"limit,omitempty"`
	Kind  string `json:"kind,omitempty"`
}

// SearchRow is the compact search result; id/title/url satisfy ChatGPT's search contract.
type SearchRow struct {
	ID    string  `json:"id"`
	Day   string  `json:"day"`
	Start string  `json:"start"`
	End   string  `json:"end"`
	Stage *string `json:"stage"`
	Track *string `json:"track"`
	Title string  `json:"title"`
	Kind  string  `json:"kind"`
	URL   string  `json:"url"`
}

// Search does case-insensitive literal substring matching over title,
// description and speakers (each field separately), in snapshot order.
// Lowercasing is Go's simple Unicode mapping; it differs from JS toLowerCase
// only for rare special cases (final sigma, dotted capital I).
func (d *Dataset) Search(a SearchArgs) []SearchRow {
	limit := a.Limit
	if limit == 0 {
		limit = defaultLimit
	}
	limit = min(max(limit, 1), maxLimit)
	kind := a.Kind
	if kind == "" {
		kind = "official"
	}
	cands := d.byKind[kind]
	if a.Day != "" {
		cands = d.byKindDay[kind][a.Day]
	}
	q := strings.ToLower(a.Query)
	out := make([]SearchRow, 0, min(limit, len(cands)))
	for _, i := range cands {
		s := d.sessions[i]
		if a.Track != "" && (s.Track == nil || *s.Track != a.Track) ||
			a.Stage != "" && (s.Stage == nil || *s.Stage != a.Stage) ||
			q != "" && !strings.Contains(s.lcTitle, q) && !strings.Contains(s.lcDesc, q) && !strings.Contains(s.lcSpeakers, q) {
			continue
		}
		out = append(out, SearchRow{s.ID, s.Day, s.Start, s.End, s.Stage, s.Track, s.Title, s.Kind, d.urlFor(s)})
		if len(out) == limit {
			break
		}
	}
	return out
}

// Details returns full snapshot rows for the first 20 IDs, deduplicated, in
// snapshot order; unknown IDs are silently dropped (legacy behaviour).
func (d *Dataset) Details(ids []string) []json.RawMessage {
	if len(ids) > maxDetails {
		ids = ids[:maxDetails]
	}
	idx := make([]int, 0, len(ids))
	for _, id := range ids {
		if i, ok := d.byID[id]; ok && !slices.Contains(idx, i) {
			idx = append(idx, i)
		}
	}
	slices.Sort(idx)
	out := make([]json.RawMessage, len(idx))
	for n, i := range idx {
		out[n] = d.sessions[i].raw
	}
	return out
}

// Fetch implements ChatGPT's fetch contract: {id,title,text,url,metadata}.
func (d *Dataset) Fetch(id string) map[string]any {
	i, ok := d.byID[id]
	if !ok {
		return map[string]any{"error": "unknown session"}
	}
	s := d.sessions[i]
	var full map[string]any
	_ = json.Unmarshal(s.raw, &full) // validated at load
	str := func(k string) string { v, _ := full[k].(string); return v }
	md := map[string]any{"day": s.Day, "kind": s.Kind}
	for _, k := range []string{"start", "end", "stage", "track", "starts_utc", "ends_utc", "organizer", "address", "ticket_url", "price", "currency", "is_free", "online", "end_known"} {
		if v, ok := full[k]; ok && v != nil {
			md[k] = v
		}
	}
	return map[string]any{
		"id":       s.ID,
		"title":    s.Title,
		"text":     fmt.Sprintf("%s %s-%s %s\n%s\n%s", s.Day, s.Start, s.End, deref(s.Stage), str("speakers"), str("description")),
		"url":      d.urlFor(s),
		"metadata": md,
	}
}

// PlanEntry is one client-held shortlist item.
type PlanEntry struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}

type PlanRow struct {
	ID     string  `json:"id"`
	Title  string  `json:"title"`
	Day    string  `json:"day"`
	Start  string  `json:"start"`
	End    string  `json:"end"`
	Stage  *string `json:"stage"`
	Status string  `json:"status,omitempty"`
}

type Conflict struct {
	Kind string  `json:"kind"`
	A    PlanRow `json:"a"`
	B    PlanRow `json:"b"`
}

type PlanResult struct {
	Plan      []PlanRow  `json:"plan"`
	Conflicts []Conflict `json:"conflicts"`
	Unknown   []string   `json:"unknown"`
}

func row(s *Session) PlanRow {
	return PlanRow{ID: s.ID, Title: s.Title, Day: s.Day, Start: s.Start, End: s.End, Stage: s.Stage}
}

// CheckPlan mirrors planner.py's v_conflicts: the latest status per ID wins;
// maybe/must are active; two active sessions conflict on overlap, or (buffer > 0,
// different stages) when the gap between them is smaller than the buffer.
func (d *Dataset) CheckPlan(plan []PlanEntry, bufferMin int) PlanResult {
	res := PlanResult{Plan: []PlanRow{}, Conflicts: []Conflict{}, Unknown: []string{}}
	latest := make(map[int]string, len(plan))
	for _, p := range plan {
		if i, ok := d.byID[p.ID]; ok {
			latest[i] = p.Status
		} else {
			res.Unknown = append(res.Unknown, p.ID)
		}
	}
	active := make([]*Session, 0, len(latest))
	for i, st := range latest {
		if st == "maybe" || st == "must" {
			active = append(active, d.sessions[i])
		}
	}
	slices.SortFunc(active, func(a, b *Session) int {
		if a.startMs != b.startMs {
			return cmpInt(a.startMs, b.startMs)
		}
		return strings.Compare(a.ID, b.ID)
	})
	buf := int64(bufferMin) * 60_000
	type keyed struct {
		c        Conflict
		aSt, bSt int64
	}
	var cs []keyed
	for i := range active {
		for j := i + 1; j < len(active); j++ {
			a, b := active[i], active[j]
			if a.ID > b.ID {
				a, b = b, a
			}
			overlap := a.startMs < b.endMs && b.startMs < a.endMs
			tight := bufferMin > 0 && deref(a.Stage) != deref(b.Stage) && a.startMs < b.endMs+buf && b.startMs < a.endMs+buf
			if overlap || tight {
				k := "tight-gap"
				if overlap {
					k = "overlap"
				}
				cs = append(cs, keyed{Conflict{k, row(a), row(b)}, a.startMs, b.startMs})
			}
		}
	}
	slices.SortStableFunc(cs, func(x, y keyed) int {
		if x.aSt != y.aSt {
			return cmpInt(x.aSt, y.aSt)
		}
		return cmpInt(x.bSt, y.bSt)
	})
	for _, k := range cs {
		res.Conflicts = append(res.Conflicts, k.c)
	}
	for _, s := range active {
		r := row(s)
		r.Status = latest[d.byID[s.ID]]
		res.Plan = append(res.Plan, r)
	}
	return res
}

func cmpInt(a, b int64) int {
	switch {
	case a < b:
		return -1
	case a > b:
		return 1
	}
	return 0
}
