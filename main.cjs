const { app, utilityProcess } = require('electron');
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
        versions: process.versions,
      }));
    }
  });
  child.stderr.pipe(process.stderr);
  child.on('exit', (code) => app.exit(code || 0));
});
