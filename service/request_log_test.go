package main

import (
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRequestLogMetadata(t *testing.T) {
	r := httptest.NewRequest("POST", "/mcp", nil)
	r.Header.Set("Accept", "application/json, text/event-stream")
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Mcp-Protocol-Version", "2025-06-18")
	r.Header.Set("Authorization", "secret-token")
	r.Header.Set("Mcp-Session-Id", "secret-session")
	got := requestLogMetadata(r)
	for _, want := range []string{"application/json, text/event-stream", "2025-06-18", "session=true"} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q in %q", want, got)
		}
	}
	if strings.Contains(got, "secret") {
		t.Fatalf("sensitive value logged: %q", got)
	}
}
