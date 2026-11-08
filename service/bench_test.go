package main

import (
	"os"
	"testing"
)

// Benchmarks use the full snapshot (SCHEDULE_PATH or a repo build output) and
// fall back to the small fixture so they always run.
func benchData(b *testing.B) ([]byte, *Dataset) {
	b.Helper()
	p := realSnapshotPath()
	if p == "" {
		p = "testdata/schedule.json"
	}
	raw, err := os.ReadFile(p)
	if err != nil {
		b.Fatal(err)
	}
	d, err := ParseDataset(raw)
	if err != nil {
		b.Fatal(err)
	}
	b.Logf("%s: %d sessions", p, len(d.sessions))
	return raw, d
}

func BenchmarkSnapshotLoad(b *testing.B) {
	raw, _ := benchData(b)
	b.SetBytes(int64(len(raw)))
	b.ReportAllocs()
	for b.Loop() {
		if _, err := ParseDataset(raw); err != nil {
			b.Fatal(err)
		}
	}
}

func BenchmarkSearchQueryAll(b *testing.B) {
	_, d := benchData(b)
	b.ReportAllocs()
	for b.Loop() {
		d.Search(SearchArgs{Query: "artificial intelligence", Kind: "all", Limit: 100})
	}
}

func BenchmarkSearchDayFilter(b *testing.B) {
	_, d := benchData(b)
	b.ReportAllocs()
	for b.Loop() {
		d.Search(SearchArgs{Day: "2026-11-11", Query: "ai", Limit: 30})
	}
}

func BenchmarkCheckPlan200(b *testing.B) {
	_, d := benchData(b)
	plan := make([]PlanEntry, 0, 200)
	for i := 0; len(plan) < 200; i++ {
		plan = append(plan, PlanEntry{ID: d.sessions[(i*7)%len(d.sessions)].ID, Status: "must"})
	}
	b.ReportAllocs()
	for b.Loop() {
		d.CheckPlan(plan, 15)
	}
}

func BenchmarkPlanCodec200(b *testing.B) {
	_, d := benchData(b)
	plan := make([]PlanEntry, 200)
	for i := range plan {
		plan[i] = PlanEntry{ID: d.sessions[i%len(d.sessions)].ID, Status: "maybe"}
	}
	b.ReportAllocs()
	for b.Loop() {
		c, _ := EncodePlan(plan)
		if _, err := DecodePlan(c); err != nil {
			b.Fatal(err)
		}
	}
}
