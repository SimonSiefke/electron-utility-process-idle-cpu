#!/usr/bin/env python3
"""External Linux/macOS sampler. No periodic callbacks are added to either workload."""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parent
DARWIN = platform.system() == 'Darwin'
if DARWIN:
    from macos_counters import snapshot


def thread_times(pid):
    """Nanoseconds of actual scheduled CPU execution, summed across threads."""
    result = {}
    for task in Path(f'/proc/{pid}/task').iterdir():
        try:
            result[task.name] = int((task / 'schedstat').read_text().split()[0])
        except FileNotFoundError:
            pass  # A thread can retire between listing and reading.
    if not result:
        raise RuntimeError(f'Process {pid} has no readable scheduler counters')
    return result


def bursts(rows, name, threshold_ms=0.02):
    events = []
    for row in rows:
        if row[f'{name}_cpu_ms'] >= threshold_ms:
            if events and row['seconds'] - events[-1]['end'] <= 0.3:
                events[-1]['end'] = row['seconds']
                events[-1]['cpu_ms'] += row[f'{name}_cpu_ms']
            else:
                events.append({'start': row['seconds'], 'end': row['seconds'],
                               'cpu_ms': row[f'{name}_cpu_ms']})
    return events


def analyze(rows):
    metrics = {}
    for name in ('electron', 'node'):
        events = bursts(rows, name)
        gaps = [b['start'] - a['start'] for a, b in zip(events, events[1:])]
        periodic = [gap for gap in gaps if 3.5 <= gap <= 4.5]
        metrics[name] = {
            'cpu_ms': sum(row[f'{name}_cpu_ms'] for row in rows),
            'active_samples': sum(row[f'{name}_cpu_ms'] >= 0.02 for row in rows),
            'bursts': events,
            'gaps_seconds': gaps,
            'four_second_intervals': len(periodic),
            'median_four_second_interval': statistics.median(periodic) if periodic else None,
        }
    # Require repeated four-second bursts across a substantial part of the window.
    # A nonzero Node result is reported literally, never rounded to "zero CPU".
    expected = rows[-1]['seconds'] / 4
    metrics['reproduced'] = (
        metrics['electron']['four_second_intervals'] >= max(3, math.floor(expected * 0.5))
        and metrics['electron']['cpu_ms'] > metrics['node']['cpu_ms'] + 0.1
        and metrics['node']['four_second_intervals'] == 0
    )
    return metrics


def instruction_count(path):
    counts = []
    for line in path.read_text().splitlines():
        fields = line.split(',')
        # perf -I -x,: timestamp,count,unit,event,...
        if len(fields) >= 4 and fields[3].strip() == 'instructions:u':
            try:
                counts.append(float(fields[1]))
            except ValueError:
                pass
    return int(sum(counts)) if counts else None


def graph(rows, path):
    width, height = 1100, 440
    duration = rows[-1]['seconds']
    peak = max(0.05, max(row[f'{name}_cpu_ms'] for row in rows for name in ('electron', 'node')))
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
           '<rect width="1100" height="440" fill="white"/>',
           '<g font-family="sans-serif" font-size="14" fill="#222">',
           '<text x="65" y="25">CPU milliseconds per sample (all threads; startup excluded)</text>']
    for i in range(6):
        y = 350 - i * 60
        svg += [f'<path d="M65 {y}H1070" stroke="#ddd"/>',
                f'<text x="5" y="{y + 5}">{peak * i / 5:.3f}</text>']
    for second in range(0, math.ceil(duration), 4):
        x = 65 + 1005 * second / duration
        svg += [f'<path d="M{x} 50V350" stroke="#eee"/>',
                f'<text x="{x - 5}" y="375">{second}</text>']
    for name, color, x in [('electron', '#d54b27', 65), ('node', '#166db2', 310)]:
        points = ' '.join(f'{65 + 1005*r["seconds"]/duration:.2f},{350 - 300*r[f"{name}_cpu_ms"]/peak:.2f}' for r in rows)
        svg += [f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.5"/>',
                f'<text x="{x}" y="415" fill="{color}">{name}</text>']
    svg += ['<text x="930" y="415">Elapsed seconds</text></g></svg>']
    path.write_text('\n'.join(svg))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=float, default=64)
    parser.add_argument('--warmup', type=float, default=70)
    parser.add_argument('--interval', type=float, default=0.1)
    parser.add_argument('--trace-seconds', type=float, default=16)
    parser.add_argument('--require-reproduction', action='store_true')
    parser.add_argument('--require-instructions', action='store_true')
    args = parser.parse_args()
    if args.duration <= 0 or args.interval <= 0 or args.warmup < 0 or args.trace_seconds < 0:
        parser.error('duration/interval must be positive; warmup/trace-seconds must be nonnegative')
    out = ROOT / 'results'
    out.mkdir(exist_ok=True)
    ready = out / 'ready.json'
    ready.unlink(missing_ok=True)
    (out / 'trace-done').unlink(missing_ok=True)
    children, files = [], []

    def launch(command, log, **kwargs):
        handle = (out / log).open('w')
        files.append(handle)
        proc = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                start_new_session=True, **kwargs)
        children.append(proc)
        return proc

    def wait_for(predicate, proc):
        deadline = time.monotonic() + 30
        while not predicate():
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Workload did not become ready; see results/*.log')
            time.sleep(0.05)

    try:
        node = launch(['node', str(ROOT / 'idle.cjs')], 'node.log')
        wait_for(lambda: 'hello world\n' in (out / 'node.log').read_text(), node)
        env = {**os.environ, 'REPRO_READY_FILE': str(ready),
               'REPRO_TRACE_SECONDS': str(args.trace_seconds)}
        env.pop('ELECTRON_RUN_AS_NODE', None)
        electron = launch([str(ROOT / 'node_modules/.bin/electron'), '--no-sandbox', str(ROOT)],
                          'electron.log', env=env)
        wait_for(ready.exists, electron)
        metadata = json.loads(ready.read_text())
        pids = {'electron': metadata['pid'], 'node': node.pid}
        environment = {'platform': platform.platform(), 'architecture': platform.machine(),
                       'node': subprocess.check_output(['node', '--version'], text=True).strip(),
                       'electron_versions': metadata['versions'], 'pids': pids,
                       'arguments': vars(args)}
        (out / 'environment.json').write_text(json.dumps(environment, indent=2))
        print(f'Warming up for {args.warmup}s; PIDs {pids}', flush=True)
        time.sleep(args.warmup)
        perf_processes = {}
        if not DARWIN and shutil.which('perf'):
            # Check that this VM exposes working PMU counters, not just event names.
            probe = subprocess.run(['perf', 'stat', '-x,', '-e', 'instructions:u', '--',
                                    'python3', '-c', 'sum(range(3000000))'],
                                   capture_output=True, text=True, timeout=15)
            (out / 'perf-probe.txt').write_text(probe.stdout + probe.stderr)
            probe_count = None
            for line in probe.stderr.splitlines():
                fields = line.split(',')
                if len(fields) >= 3 and fields[2] == 'instructions:u':
                    try:
                        probe_count = float(fields[0])
                    except ValueError:
                        pass
            if probe.returncode == 0 and probe_count and probe_count > 10000:
                for name, pid in pids.items():
                    perf_processes[name] = launch([
                        'perf', 'stat', '-I', '100', '-x,', '-e', 'instructions:u',
                        '-p', str(pid), '-o', str(out / f'{name}-instructions.csv'),
                        '--', 'sleep', str(args.duration + 0.5)], f'{name}-perf.log')
        previous = {name: (snapshot(pid) if DARWIN else thread_times(pid)) for name, pid in pids.items()}
        initial = {name: dict(values) for name, values in previous.items()}
        if not DARWIN and any(sum(times.values()) == 0 for times in previous.values()):
            raise RuntimeError('Scheduler accounting is disabled; enable kernel.sched_schedstats=1')
        rows = []
        start = time.monotonic()
        deadline = start + args.interval
        while time.monotonic() < start + args.duration:
            time.sleep(max(0, deadline - time.monotonic()))
            row = {'seconds': time.monotonic() - start}
            for name, pid in pids.items():
                if node.poll() is not None or electron.poll() is not None:
                    raise RuntimeError('Workload exited during measurement')
                if DARWIN:
                    current = snapshot(pid)
                    row[f'{name}_cpu_ms'] = (current['cpu_ns'] - previous[name]['cpu_ns']) / 1e6
                    for counter in ('instructions', 'cycles', 'idle_wakeups'):
                        row[f'{name}_{counter}'] = current[counter] - previous[name][counter]
                else:
                    current = thread_times(pid)
                    row[f'{name}_cpu_ms'] = sum(max(0, runtime - previous[name].get(tid, runtime))
                                                 for tid, runtime in current.items()) / 1e6
                previous[name] = current
            rows.append(row)
            deadline += args.interval
        with (out / 'samples.csv').open('w') as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        metrics = analyze(rows)
        for proc in perf_processes.values():
            proc.wait(timeout=10)
        instructions = {name: instruction_count(out / f'{name}-instructions.csv')
                        if name in perf_processes and perf_processes[name].returncode == 0 else None
                        for name in pids}
        if DARWIN:
            # Startup must have retired instructions: zero lifetime counts mean no PMU access.
            instructions = {name: sum(row[f'{name}_instructions'] for row in rows)
                            if initial[name]['instructions'] > 0 else None for name in pids}
        metrics['instructions'] = instructions
        metrics['instruction_counters_available'] = all(value is not None for value in instructions.values())
        (out / 'summary.json').write_text(json.dumps(metrics, indent=2))
        graph(rows, out / 'cpu.svg')
        summary = [f'## Idle CPU comparison ({environment["architecture"]})', '',
                   f'Electron {metadata["versions"]["electron"]} (embedded Node {metadata["versions"]["node"]}); '
                   f'standalone Node {environment["node"]}.', '',
                   f'{args.warmup:g}s warmup, {args.duration:g}s measurement, {args.interval:g}s sampling.', '',
                   '| Process | CPU time (ms) | ~4s intervals | Retired instructions |',
                   '| --- | ---: | ---: | ---: |']
        for name in pids:
            summary.append(f'| {name} | {metrics[name]["cpu_ms"]:.6f} | '
                           f'{metrics[name]["four_second_intervals"]} | '
                           f'{instructions[name] if instructions[name] is not None else "Unavailable"} |')
        summary += ['', f'**Four-second idle CPU reproduction: {"OBSERVED" if metrics["reproduced"] else "NOT OBSERVED"}.**', '',
                    'Burst threshold: 0.02ms per sample; adjacent activity within 0.3s is merged. '
                    'Intervals in [3.5s, 4.5s] count toward the four-second cadence.', '',
                    ('macOS instructions/cycles use proc_pid_rusage V4 across all process threads, in the same sampling window. '
                     'No user/kernel privilege filter is applied.' if DARWIN else
                     'Linux user instruction totals use a separate perf clock/window (approximately measurement + 0.5s); '
                     'see raw interval files. Missing/unsupported counters are not zero instructions.'), '',
                    'Primary CPU samples establish activity and timing. The following, separate Chromium trace '
                    'identifies allocator reclaim events for the utility PID; it does not measure their share of primary CPU time.']
        report = '\n'.join(summary) + '\n'
        (out / 'summary.md').write_text(report)
        print(report, flush=True)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
                handle.write(report)
        # Separate phase: trace the actual allocator events without perturbing primary samples.
        if args.trace_seconds:
            os.kill(metadata['hostPid'], signal.SIGUSR2)
            deadline = time.monotonic() + args.trace_seconds + 30
            while not (out / 'trace-done').exists():
                if electron.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Chromium tracing failed; see electron.log')
                time.sleep(0.1)
            trace = json.loads((out / 'chromium-trace.json').read_text())
            events = [event for event in trace['traceEvents']
                      if event.get('pid') == pids['electron']
                      and 'MemoryReclaimer::Reclaim' in event.get('name', '')
                      and event.get('ph') in ('X', 'B')]
            times = sorted(event['ts'] / 1e6 for event in events)
            evidence = {'utility_pid': pids['electron'], 'reclaim_events': events,
                        'intervals_seconds': [b - a for a, b in zip(times, times[1:])]}
            (out / 'reclaimer-events.json').write_text(json.dumps(evidence, indent=2))
            metrics['allocator_reclaim'] = evidence
            (out / 'summary.json').write_text(json.dumps(metrics, indent=2))
            trace_report = (f"\n### Separate utility-process allocator trace\n\n"
                            f"{len(events)} MemoryReclaimer::Reclaim events; intervals in seconds: "
                            f"{', '.join(f'{gap:.6f}' for gap in evidence['intervals_seconds']) or 'none'}.\n")
            with (out / 'summary.md').open('a') as handle:
                handle.write(trace_report)
            if os.environ.get('GITHUB_STEP_SUMMARY'):
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
                    handle.write(trace_report)
            print(trace_report, flush=True)
        # Separate phase: ptrace must not contaminate the primary CPU comparison.
        if not DARWIN and args.trace_seconds and shutil.which('strace'):
            traces = []
            for name, pid in pids.items():
                traces.append(launch(['timeout', '--signal=INT', str(args.trace_seconds),
                                     'strace', '-f', '-ttt', '-T', '-e',
                                     'trace=madvise,futex,epoll_wait,epoll_pwait,clock_nanosleep',
                                     '-p', str(pid), '-o', str(out / f'{name}-syscalls.txt')],
                                    f'{name}-strace.log'))
            for proc in traces:
                proc.wait(timeout=args.trace_seconds + 10)
        if DARWIN:
            # Native stacks are a separate diagnostic phase, after primary sampling.
            for name, pid in pids.items():
                if args.trace_seconds:
                    subprocess.run(['sample', str(pid), str(int(args.trace_seconds)), '1',
                                    '-file', str(out / f'{name}-stacks.txt')],
                                   capture_output=True, text=True, timeout=args.trace_seconds + 20)
        if args.require_instructions and not metrics['instruction_counters_available']:
            raise SystemExit('Hardware instruction counters unavailable; see perf-probe.txt')
        if args.require_reproduction and not metrics['reproduced']:
            raise SystemExit('Four-second cadence was not reproduced; inspect the artifacts')
    finally:
        for proc in reversed(children):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in reversed(children):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        for handle in files:
            handle.close()


if __name__ == '__main__':
    main()
