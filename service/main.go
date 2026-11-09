// Command service is the read-only Web Summit planner MCP server.
//
// It loads one schedule snapshot (SCHEDULE_PATH, default data/schedule.json) and
// the company catalog (COMPANIES_PATH, default data/companies.json)
// at startup, keeps it immutable in memory and serves stateless Streamable
// HTTP MCP at /mcp on PORT (default 8080). It logs startup and shutdown only.
package main

import (
	"context"
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"runtime/debug"
	"syscall"
	"time"
)

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func main() {
	log.SetFlags(0)
	path := env("SCHEDULE_PATH", "data/schedule.json")
	d, err := LoadDataset(path)
	if err != nil {
		log.Fatalf("load snapshot: %v", err)
	}
	companies, err := LoadCompanies(env("COMPANIES_PATH", "data/companies.json"))
	if err != nil {
		log.Fatalf("load companies: %v", err) // company tools are part of the contract
	}
	d.WithCompanies(companies)
	debug.FreeOSMemory() // return the transient load buffers (snapshot + catalog JSON) to the OS
	srv := &http.Server{
		Addr:              net.JoinHostPort("", env("PORT", "8080")),
		Handler:           NewHandler(d),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    16 << 10,
		ErrorLog:          log.New(discard{}, "", 0), // no per-request/client logging
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	errc := make(chan error, 1)
	go func() { errc <- srv.ListenAndServe() }()
	log.Printf("websummit-planner %s: %d sessions, %d companies, snapshot sha256 %.12s, listening on %s", ServerVersion, len(d.sessions), companies.Count(), d.sha, srv.Addr)

	select {
	case err := <-errc:
		if !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("serve: %v", err)
		}
	case <-ctx.Done():
		log.Print("shutting down")
		sctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := srv.Shutdown(sctx); err != nil {
			log.Printf("shutdown: %v", err)
		}
	}
}

type discard struct{}

func (discard) Write(p []byte) (int, error) { return len(p), nil }
