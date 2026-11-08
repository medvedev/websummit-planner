package main

import (
	"fmt"
	"net/http"
)

// Limit untrusted header values and quote them to prevent multiline log entries.
func logHeader(r *http.Request, name string) string {
	v := r.Header.Get(name)
	if len(v) > 256 {
		v = v[:256]
	}
	return v
}

func requestLogMetadata(r *http.Request) string {
	return fmt.Sprintf("mcp request method=%q accept=%q content_type=%q protocol_version=%q user_agent=%q session=%t last_event_id=%t",
		r.Method, logHeader(r, "Accept"), logHeader(r, "Content-Type"),
		logHeader(r, "Mcp-Protocol-Version"), logHeader(r, "User-Agent"),
		r.Header.Get("Mcp-Session-Id") != "", r.Header.Get("Last-Event-Id") != "")
}
