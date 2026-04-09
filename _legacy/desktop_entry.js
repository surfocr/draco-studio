const { spawn } = require('child_process');

function run(command, args) {
  const child = spawn(command, args, {
    stdio: 'inherit',
    shell: process.platform === 'win32',
  });
  child.on('exit', (code) => process.exit(code ?? 0));
  child.on('error', (error) => {
    console.error(`[desktop] Failed to start ${command}: ${error.message}`);
    process.exit(1);
  });
}

const mode = process.argv[2];
const enabled = process.env.ENABLE_LEGACY_DESKTOP === '1';

if (!enabled) {
  console.error(
    'The Electron desktop shell is still a legacy surface and is blocked by default.\n' +
      'Use the web app via "npm run dev" for supported development.\n' +
      'If you intentionally need the legacy desktop shell, rerun with ENABLE_LEGACY_DESKTOP=1.'
  );
  process.exit(1);
}

switch (mode) {
  case 'start':
    run('electron', ['.']);
    break;
  case 'dev':
    run('electron', ['.', '--dev']);
    break;
  case 'build':
    run('electron-builder', []);
    break;
  case 'build:win':
    run('electron-builder', ['--win']);
    break;
  default:
    console.error(`Unknown desktop mode: ${mode}`);
    process.exit(1);
}
