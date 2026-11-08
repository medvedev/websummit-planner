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
it is not a supported setting at this memory limit. Deployment concurrency is four.

The current deployment uses gen1 for its supported 128 MiB minimum, scale-to-zero,
maximum two instances and startup CPU boost. Recheck production latency and peak memory
with Cloud Monitoring after deployment, especially when integrating company data.
Do not infer zero hosting cost from these measurements.

Repeat benchmarks: generate service/data/schedule.json, then run
`go test -run "^$" -bench . -benchmem` from service/. Build the stripped binary and measure
process-to-health separately; exclude compiler time. Cloud scheduling, image retrieval,
TLS and web-assistant latency are not included in the local numbers.
