# Electron utility process idle CPU reproduction

Compare an idle Electron **utility process** with standalone Node.js on native Linux ARM64. Both execute exactly the same [`idle.cjs`](idle.cjs):

```js
console.log('hello world');
setTimeout(() => {}, 2147483647);
```

The timeout is about 24.9 days. A delay of `9999999999` exceeds Node's signed 32-bit limit and becomes 1ms, so it is unsuitable as a keepalive ([Node timer documentation](https://nodejs.org/api/timers.html#settimeoutcallback-delay-args)). There are no periodic JavaScript callbacks, allocation loops, or polling in either workload.

## Run the ARM64 comparison

Pushes run [ARM64 idle CPU comparison](../../actions/workflows/idle-cpu.yml) on `ubuntu-24.04-arm`. Use **Run workflow** to repeat it. The repository is public because [standard ARM64 hosted runners require a public repository](https://github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available/).

Electron is pinned in `package-lock.json`. CI selects the exact standalone Node version embedded in that Electron release. The job:

1. Starts standalone Node and an Electron app that calls [`utilityProcess.fork`](https://www.electronjs.org/docs/latest/api/utility-process) on the same file. It waits for both hello-world messages.
2. Excludes 12 seconds of startup activity, then samples each target PID's **entire thread group** every 100ms for 64 seconds. CPU execution comes from nanosecond Linux `/proc/PID/task/TID/schedstat` counters; Electron's host, GPU and other processes are excluded.
3. Probes hardware `instructions:u` with a busy control to reject unavailable or nonfunctional counters. If the probe works, concurrent `perf stat -I 100 -p PID` recordings compare retired user instructions across each target's threads. Raw interval counts and totals are saved. Kernel instructions are excluded. This is a different quantity from elapsed time or CPU milliseconds.
4. Records a separate 16-second `strace` phase for both processes, including `madvise`, futex and event-loop waits. Tracing happens **after** CPU sampling to keep ptrace overhead out of the comparison.
5. Publishes the measured table in the Actions summary and uploads the `arm64-idle-cpu-comparison` artifact, including `cpu.svg`, `samples.csv`, `summary.json`, environment/versions, instruction counters and syscall traces. Artifacts are uploaded even when the check fails.

ARM64 does **not** guarantee access to a PMU inside a hosted VM. The [runner-images report](https://github.com/actions/runner-images/issues/11689) documents hardware-counter limitations on ARM runners. If the busy probe cannot obtain positive instruction counts, the result says **Unavailable**, and the CPU-time comparison still runs. Select `require_instructions` in the manual workflow to fail when counters are unavailable. A machine exposing working hardware counters is needed for an actual instruction-count comparison; software CPU time is never presented as an instruction count.

## What counts as reproducing the bug?

The check groups CPU samples of at least 0.02ms into bursts (activity within 0.3s is merged). It requires at least half the expected four-second intervals to fall in `[3.5s, 4.5s]`, with a minimum of three matches, more total Electron CPU than Node by at least 0.1ms, and no matching four-second cadence in Node. It fails if these conditions are absent. Raw times and counts are retained so a green result can be checked against the timeline. The thresholds tolerate scheduler jitter but are a heuristic, not a statistical proof.

Node's actual CPU time is reported, including occasional runtime work; it is not assumed to be exactly zero. The measurement is intended to show recurring Electron activity against an otherwise sleeping baseline. CPU samples establish **when** work happened, not its native function. `strace` can reveal memory-discard syscalls, but a native profile is needed to prove attribution to a particular cleanup function.

A source-level candidate is Chromium PartitionAlloc's memory reclaimer, whose recommended default interval is [four seconds](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/base/allocator/partition_allocator/src/partition_alloc/memory_reclaimer.cc). This is allocator housekeeping, not necessarily cleanup of JavaScript `Buffer` objects. Runtime versions and feature settings can change that behavior; the benchmark does not enable a four-second timer or force the result.

## Run locally (Linux)

Requires Node.js, Python 3, Electron's system libraries, Xvfb and optionally `perf`/`strace`.

```sh
npm ci
# Match this version with your Node version manager for a fair comparison:
ELECTRON_RUN_AS_NODE=1 node_modules/.bin/electron -p process.versions.node
sudo sysctl kernel.sched_schedstats=1
# For optional perf / strace attachments on your own test machine:
sudo sysctl kernel.perf_event_paranoid=-1 kernel.yama.ptrace_scope=0
xvfb-run -a python3 measure.py --require-reproduction
npm test
```

The workflow installs its own tools and configures these kernel settings on the ephemeral runner. Electron uses `--no-sandbox` for this minimal local reproduction. No browser windows or external pages are loaded.

Use `--duration`, `--warmup`, `--interval`, `--trace-seconds 0`, or `--require-instructions` to adjust a local experiment. Keep the 100ms sampling interval for the documented classification thresholds. Scheduler accounting can miss the final unsampled runtime of a thread that exits; transient thread creation/exit should be considered when interpreting the raw data. `perf` totals cover approximately 0.5s longer than the scheduler window and have their own interval clock.
