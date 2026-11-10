# Local service measurements

Measured 8 November 2026 on Linux amd64, Intel i7-8750H, Go 1.27.3. Dataset:
1,466 records (1,122 official sessions and 344 community side events), JSON 1,205,532 bytes.
These are local measurements, not Cloud Run cold-start guarantees.

- Stripped static executable: 8,982,688 bytes before the final bounds-only patch.
- Scratch container image: 10,188,220 bytes before that patch; UID/GID 65532.
- Process launch to successful /healthz: median 48.3 ms over 10 trials (45.5-51.9 ms).
- Startup RSS: 18.2-19.2 MiB with GOMEMLIMIT=64MiB.
- Snapshot decode/index build: approximately 45.9 ms, 9.2 MB allocated transiently.
- Full-text substring search: approximately 0.69 ms; day-filtered search: 0.011 ms.
- 200-item plan check: approximately 1.94 ms (benchmark fixture; response serialization excluded).

Container test used read-only filesystem, no capabilities, 1 CPU and a 128 MiB hard
memory limit. A deliberately heavy 200-selection plan with a 120-minute travel buffer
returned a 7,257,796-byte JSON response. Sixteen requests at concurrency four all passed;
maximum observed request time was 1.704 seconds, and memory after the run was 61.23 MiB.
The earlier concurrency-20 test closed connections and the ephemeral container exited;
it is not a supported setting at this memory limit. Deployment concurrency was raised
to 32 at the user's request; 32 concurrent heavy requests have not been tested.

The current deployment uses gen1 (gen2 requires at least 512 MiB), scale-to-zero,
maximum three instances and startup CPU boost. Recheck production latency and peak memory
with Cloud Monitoring after deployment, especially when integrating company data.
Do not infer zero hosting cost from these measurements.

Repeat benchmarks: generate service/data/schedule.json, then run
`go test -run "^$" -bench . -benchmem` from service/. Build the stripped binary and measure
process-to-health separately; exclude compiler time. Cloud scheduling, image retrieval,
TLS and web-assistant latency are not included in the local numbers.

## Cloud Run startup experiment (10 Nov 2026, us-central1, 2 CPUs, CPU boost)

Container startup latency (run.googleapis.com/container/startup_latencies), three fresh revisions each:
gen1 128 MiB TCP probe 645 ms mean (497-749); gen1 128 MiB HTTP /health probe 1048 ms; gen1 512 MiB TCP 1131 ms
(one 2061 ms outlier); gen2 512 MiB TCP 606 ms; gen2 512 MiB HTTP 1022 ms. Gen2 rejects 128 MiB.
Gen1 and gen2 are equal within noise. An HTTP startup probe always succeeded on its second attempt,
adding about 400 ms with a 1 s period; the TCP probe succeeds on the first. Hence gen1 plus TCP.
Concurrency 128 at 128 MiB is untested: see the concurrency-20 note above.

Second matrix (10 Nov 2026, gen1, TCP probe, 3 fresh revisions each, mean startup ms): 1 CPU/128 MiB 616;
1 CPU/256 MiB 593; 2 CPU/128 MiB 598; 2 CPU/256 MiB 537; 4 CPU/2 GiB 821 and 806 plus a 4408 outlier
(gen1 needs 2 GiB for 4 CPUs). Previous image (with debug.FreeOSMemory) at 2 CPU/128 MiB: 685.
Differences between 1-2 CPUs and 128-256 MiB are within run-to-run noise (about +/-150 ms); more CPU does not help
because startup is dominated by sandbox and image setup. debug.FreeOSMemory() was removed from main.go.

Gen2 matrix (10 Nov 2026, new image, TCP probe, 3 fresh revisions each, startup ms): 1 CPU/512 MiB 2014, 701, 789;
2 CPU/512 MiB 968, 521, 699; 4 CPU/2 GiB (minimum for 4 CPUs) 5933, 9373, 4847. Gen2 never beat gen1 at 2 CPUs.
