const { app, contentTracing, utilityProcess } = require('electron');
const { writeFileSync } = require('node:fs');
const path = require('node:path');

app.whenReady().then(() => {
  const child = utilityProcess.fork(path.join(__dirname, 'idle.cjs'), [], {
    stdio: 'pipe',
    serviceName: 'Idle CPU reproduction',
  });
  let output = '';
  child.stdout.on('data', (data) => {
    output += data.toString();
    if (output.includes('hello world\n')) {
      writeFileSync(process.env.REPRO_READY_FILE, JSON.stringify({
        pid: child.pid,
        hostPid: process.pid,
        versions: process.versions,
      }));
    }
  });
  child.stderr.pipe(process.stderr);
  child.on('exit', (code) => app.exit(code || 0));
});

// Triggered by the external sampler only after CPU measurement has finished.
// The idle utility program remains the unchanged two-line idle.cjs.
process.once('SIGUSR2', async () => {
  try {
    await contentTracing.startRecording({ included_categories: ['base'] });
    await new Promise((resolve) => setTimeout(resolve, Number(process.env.REPRO_TRACE_SECONDS) * 1000));
    await contentTracing.stopRecording(path.join(path.dirname(process.env.REPRO_READY_FILE), 'chromium-trace.json'));
    writeFileSync(path.join(path.dirname(process.env.REPRO_READY_FILE), 'trace-done'), 'done');
  } catch (error) {
    console.error(error);
    app.exit(1);
  }
});
