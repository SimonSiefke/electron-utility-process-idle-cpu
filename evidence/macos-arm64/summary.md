## Idle CPU comparison (arm64)

Electron 44.9.1 (embedded Node 24.22.0); standalone Node v24.22.0.

70s warmup, 64s measurement, 0.1s sampling.

| Process | CPU time (ms) | ~4s intervals | Retired instructions |
| --- | ---: | ---: | ---: |
| electron | 2.875209 | 12 | Unavailable |
| node | 0.000000 | 0 | Unavailable |

**Four-second idle CPU reproduction: OBSERVED.**

Burst threshold: 0.02ms per sample; adjacent activity within 0.3s is merged. Intervals in [3.5s, 4.5s] count toward the four-second cadence.

macOS instructions/cycles use proc_pid_rusage V4 across all process threads, in the same sampling window. No user/kernel privilege filter is applied.

Primary CPU samples establish activity and timing. The following, separate Chromium trace identifies allocator reclaim events for the utility PID; it does not measure their share of primary CPU time.

### Separate utility-process allocator trace

4 MemoryReclaimer::Reclaim events; intervals in seconds: 4.036861, 4.075228, 4.010774.
