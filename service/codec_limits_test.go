package main

import (
	"strings"
	"testing"
)

func TestMaxLengthPlanCodeRoundTrip(t *testing.T) {
	for _, char := range []string{"x", "\x01", "ї", "😀"} {
		plan := make([]PlanEntry, MaxPlan)
		for i := range plan {
			plan[i] = PlanEntry{ID: strings.Repeat(char, MaxIDLen), Status: "must"}
		}
		code, err := EncodePlan(plan)
		if err != nil {
			t.Fatal(err)
		}
		got, err := DecodePlan(code)
		if err != nil || len(got) != len(plan) || got[0] != plan[0] {
			t.Fatalf("max-length %q roundtrip failed: length=%d err=%v", char, len(code), err)
		}
	}
}
