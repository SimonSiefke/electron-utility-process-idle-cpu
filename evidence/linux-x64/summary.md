# Local Linux x86_64 verification

This is local evidence, not an ARM64 CI result. Standalone and embedded Node versions differ in this local run; CI matches them exactly.

## Idle CPU comparison (x86_64)

Electron 44.9.1 (embedded Node 24.22.0); standalone Node v24.15.0.

70s warmup, 32s measurement, 0.1s sampling.

| Process | CPU time (ms) | ~4s intervals | Retired instructions |
| --- | ---: | ---: | ---: |
| electron | 1.939537 | 5 | 758562 |
| node | 0.000000 | 0 | Unavailable |

**Four-second idle CPU reproduction: OBSERVED.**

Burst threshold: 0.02ms per sample; adjacent activity within 0.3s is merged. Intervals in [3.5s, 4.5s] count toward the four-second cadence.

Linux user instruction totals use a separate perf clock/window (approximately measurement + 0.5s); see raw interval files. Missing/unsupported counters are not zero instructions.

Scheduler CPU samples establish activity and timing, not its native call stack. The separate syscall traces can show madvise calls; allocator attribution remains a hypothesis unless profiled.

## Separate Chromium trace

Four utility-process MemoryReclaimer::Reclaim events; intervals: 4.000287s, 4.000309s, 4.000375s. See [raw events](reclaimer-events.json) and [CPU timeline](cpu.svg).
