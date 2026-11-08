package main

import (
	"fmt"
	"os"
	"strings"
	"testing"
)

// sess builds one snapshot session; extra is raw JSON members overriding defaults.
func sess(id, kind, day, start, end, extra string) string {
	m := map[string]string{
		"id": q(id), "day": q(day), "start": q(start), "end": q(end), "stage": `"Main"`, "track": `"T"`,
		"title": q("Title " + id), "description": "null", "speakers": "null", "kind": q(kind),
		"starts_utc": q(day + "T" + start + ":00Z"), "ends_utc": q(day + "T" + end + ":00Z"),
		"url": "null", "organizer": "null", "address": "null", "ticket_url": "null", "price": "null",
		"currency": "null", "is_free": "null", "online": "null", "end_known": "null",
	}
	if extra != "" {
		for _, kv := range splitMembers(extra) {
			k, v, _ := strings.Cut(kv, ":")
			m[strings.Trim(k, `"`)] = v
		}
	}
	keys := []string{"id", "day", "start", "end", "stage", "track", "title", "description", "speakers", "kind",
		"starts_utc", "ends_utc", "url", "organizer", "address", "ticket_url", "price", "currency", "is_free", "online", "end_known"}
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		parts = append(parts, q(k)+":"+m[k])
		delete(m, k)
	}
	for k, v := range m {
		parts = append(parts, q(k)+":"+v)
	}
	return "{" + strings.Join(parts, ",") + "}"
}

// splitMembers splits `"a":"x","b":null` at top-level commas (test helper; no nesting).
func splitMembers(s string) []string {
	var out []string
	inStr, esc, last := false, false, 0
	for i, c := range s {
		switch {
		case esc:
			esc = false
		case c == '\\':
			esc = true
		case c == '"':
			inStr = !inStr
		case c == ',' && !inStr:
			out = append(out, s[last:i])
			last = i + 1
		}
	}
	return append(out, s[last:])
}

func q(s string) string { return fmt.Sprintf("%q", s) }

func snapshot(sessions ...string) string {
	return `{"info":{"built_at":"2026-11-07T22:05:48Z","days":["2026-11-10"],"sessions":1,"notice":"Test notice."},"sessions":[` +
		strings.Join(sessions, ",") + `]}`
}

func mustParse(t testing.TB, s string) *Dataset {
	t.Helper()
	d, err := ParseDataset([]byte(s))
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func TestParseDatasetRejectsInvalidSnapshots(t *testing.T) {
	ok := sess("a", "official", "2026-11-10", "10:00", "11:00", "")
	cases := map[string]string{
		"not json":        `{`,
		"trailing data":   snapshot(ok) + `{}`,
		"no info":         `{"sessions":[` + ok + `]}`,
		"no notice":       `{"info":{"days":[]},"sessions":[` + ok + `]}`,
		"no sessions":     snapshot(),
		"duplicate ids":   snapshot(ok, ok),
		"empty id":        snapshot(sess("", "official", "2026-11-10", "10:00", "11:00", "")),
		"id too long":     snapshot(sess(strings.Repeat("x", MaxIDLen+1), "official", "2026-11-10", "10:00", "11:00", "")),
		"bad kind":        snapshot(sess("a", "party", "2026-11-10", "10:00", "11:00", "")),
		"bad day":         snapshot(sess("a", "official", "10/11/2026", "10:00", "11:00", "")),
		"bad timestamp":   snapshot(sess("a", "official", "2026-11-10", "10:00", "11:00", `"starts_utc":"yesterday"`)),
		"end before":      snapshot(sess("a", "official", "2026-11-10", "11:00", "10:00", "")),
		"missing title":   snapshot(sess("a", "official", "2026-11-10", "10:00", "11:00", `"title":null`)),
		"stage not str":   snapshot(sess("a", "official", "2026-11-10", "10:00", "11:00", `"stage":5`)),
		"session is null": snapshot("null"),
	}
	for name, body := range cases {
		if _, err := ParseDataset([]byte(body)); err == nil {
			t.Errorf("%s: accepted invalid snapshot", name)
		}
	}
	if _, err := ParseDataset([]byte(snapshot(ok))); err != nil {
		t.Fatalf("valid snapshot rejected: %v", err)
	}
}

func TestDatasetKeepsUnknownFieldsAndInfo(t *testing.T) {
	d := mustParse(t, `{"info":{"built_at":"x","notice":"N","future":{"a":1}},"sessions":[`+
		sess("a", "side", "2026-11-08", "10:00", "10:00", `"venue_map":"https://m"`)+`]}`)
	if d.Notice() != "N" {
		t.Errorf("notice = %q", d.Notice())
	}
	info := d.Info()
	if _, ok := info["future"]; !ok {
		t.Error("info dropped unknown field")
	}
	if info["snapshot_sha256"] == "" || info["notice"] != "N" {
		t.Errorf("info = %v", info)
	}
	if !strings.Contains(string(d.Details([]string{"a"})[0]), `"venue_map":"https://m"`) {
		t.Error("details dropped unknown session field")
	}
}

func TestFixtureAndRealSnapshotIDsFitSchema(t *testing.T) {
	paths := []string{"testdata/schedule.json"}
	if p := realSnapshotPath(); p != "" {
		paths = append(paths, p)
	}
	for _, p := range paths {
		d, err := LoadDataset(p)
		if err != nil {
			t.Fatalf("%s: %v", p, err)
		}
		long := 0
		for _, s := range d.sessions {
			if len(s.ID) > 64 {
				long++
			}
			if len(s.ID) > MaxIDLen {
				t.Errorf("%s: id %q exceeds schema bound", p, s.ID)
			}
		}
		t.Logf("%s: %d sessions, %d ids longer than the legacy 64-char bound", p, len(d.sessions), long)
	}
}

// realSnapshotPath returns SCHEDULE_PATH, or a known repo location, if present.
func realSnapshotPath() string {
	for _, p := range []string{os.Getenv("SCHEDULE_PATH"), "data/schedule.json", "../out/text/schedule.json", "../mcp-worker/src/schedule.json"} {
		if p == "" {
			continue
		}
		if st, err := os.Stat(p); err == nil && st.Size() > 0 {
			return p
		}
	}
	return ""
}
