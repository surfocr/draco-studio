'use strict';
const { spawn, execSync } = require('child_process');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const { createWriteStream, mkdirSync } = fs;

const SIDECAR_PORT = 18082;
const HEALTH_URL = `http://127.0.0.1:${SIDECAR_PORT}/health`;

// Python embeddable package — no admin install needed.
// Pinned SHA-256 digests: verify before executing any downloaded artifact.
const PYTHON_VERSION = '3.11.9';
const PYTHON_EMBED_URL = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip`;
const PYTHON_EMBED_SHA256 = 'b995374fc1b6576b90e8e5357d9a6cd96e2b34e9b4e67efa0d4d78c9f5ea8fd4';
const GET_PIP_URL = 'https://bootstrap.pypa.io/get-pip.py';
// get-pip.py is bootstrapped from a well-known source; we verify the downloaded zip
// separately. For get-pip we enforce HTTPS and check for a minimum size.
const GET_PIP_MIN_BYTES = 2_000_000; // get-pip.py is >2 MB; abort if suspiciously small

/**
 * Verify a downloaded file against an expected SHA-256 hex digest.
 * Throws if the file is missing or the hash does not match.
 */
function verifyFileHash(filePath, expectedHex) {
  const buf = fs.readFileSync(filePath);
  const actual = crypto.createHash('sha256').update(buf).digest('hex');
  if (actual !== expectedHex) {
    // Remove the corrupt/tampered file before throwing
    try { fs.unlinkSync(filePath); } catch {}
    throw new Error(
      `Integrity check failed for ${path.basename(filePath)}\n` +
      `  expected: ${expectedHex}\n` +
      `  got:      ${actual}\n` +
      'Aborting setup. Do not run downloaded code that fails verification.'
    );
  }
}

class PythonManager {
  constructor(envDir, modelsDir, emitEvent) {
    this.envDir = envDir;
    this.modelsDir = modelsDir;
    this.emit = emitEvent || (() => {});
    this.process = null;
    this.running = false;
    this.setupComplete = false;

    // Auto-restart state
    this._intentionalStop = false;
    this._restartCount = 0;
    this._maxRestarts = 3;
    this._restartBackoff = [2000, 5000, 15000]; // exponential backoff

    this._embeddedPythonDir = path.join(this.envDir, 'python');
    this._venvDir = path.join(this.envDir, 'venv');
  }

  // ═══════════════════════════════════════════════════════
  //  PYTHON DETECTION — checks embedded + system Python
  // ═══════════════════════════════════════════════════════

  checkPython() {
    // 1. Check our embedded Python first
    const embeddedPy = this._embeddedPython();
    if (fs.existsSync(embeddedPy)) {
      try {
        const result = execSync(`"${embeddedPy}" --version 2>&1`, {
          encoding: 'utf8', timeout: 5000, windowsHide: true,
        }).trim();
        const match = result.match(/Python (\d+)\.(\d+)\.(\d+)/);
        if (match && Number(match[1]) >= 3 && Number(match[2]) >= 10) {
          return { found: true, version: result, command: embeddedPy, args: [], source: 'embedded' };
        }
      } catch {}
    }

    // 2. Check system Python
    const candidates = process.platform === 'win32'
      ? ['python', 'python3', 'py -3']
      : ['python3', 'python'];

    for (const cmd of candidates) {
      try {
        const parts = cmd.split(' ');
        const result = execSync(`${cmd} --version 2>&1`, {
          encoding: 'utf8', timeout: 5000, windowsHide: true,
        }).trim();
        const match = result.match(/Python (\d+)\.(\d+)\.(\d+)/);
        if (match) {
          const [, major, minor] = match.map(Number);
          if (major >= 3 && minor >= 10) {
            return { found: true, version: result, command: parts[0], args: parts.slice(1), source: 'system' };
          }
        }
      } catch {}
    }

    // 3. Check common Windows install locations
    if (process.platform === 'win32') {
      const localAppData = process.env.LOCALAPPDATA || '';
      const commonPaths = [
        path.join(localAppData, 'Programs', 'Python'),
        'C:\\Python312', 'C:\\Python311', 'C:\\Python310',
      ];
      for (const base of commonPaths) {
        try {
          if (!fs.existsSync(base)) continue;
          const entries = fs.readdirSync(base);
          for (const entry of entries) {
            const pyExe = path.join(base, entry, 'python.exe');
            if (!fs.existsSync(pyExe)) continue;
            const result = execSync(`"${pyExe}" --version 2>&1`, {
              encoding: 'utf8', timeout: 5000, windowsHide: true,
            }).trim();
            const match = result.match(/Python (\d+)\.(\d+)/);
            if (match && Number(match[1]) >= 3 && Number(match[2]) >= 10) {
              return { found: true, version: result, command: pyExe, args: [], source: 'system' };
            }
          }
        } catch {}
      }
    }

    return { found: false, version: null, command: null, source: null };
  }

  // ═══════════════════════════════════════════════════════
  //  EMBEDDED PYTHON DOWNLOAD — fully automatic, no admin
  // ═══════════════════════════════════════════════════════

  async downloadPython() {
    if (process.platform !== 'win32') {
      throw new Error('Auto-download only supports Windows. Install Python 3.10+ manually on this platform.');
    }

    const targetDir = this._embeddedPythonDir;
    mkdirSync(targetDir, { recursive: true });

    // Download the embeddable zip
    this.emit('log', `Downloading Python ${PYTHON_VERSION} embeddable package...`);
    const zipPath = path.join(this.envDir, 'python-embed.zip');
    await this._downloadFile(PYTHON_EMBED_URL, zipPath);

    // Verify integrity before extracting — abort on mismatch
    this.emit('log', 'Verifying Python package integrity...');
    verifyFileHash(zipPath, PYTHON_EMBED_SHA256);

    // Extract
    this.emit('log', 'Extracting Python...');
    await this._extractZip(zipPath, targetDir);

    // Enable pip: edit the ._pth file to uncomment "import site"
    const pthFiles = fs.readdirSync(targetDir).filter(f => f.endsWith('._pth'));
    for (const pthFile of pthFiles) {
      const pthPath = path.join(targetDir, pthFile);
      let content = fs.readFileSync(pthPath, 'utf8');
      content = content.replace(/^#\s*import site/m, 'import site');
      if (!content.includes('Lib\\site-packages')) {
        content += '\nLib\\site-packages\n';
      }
      fs.writeFileSync(pthPath, content);
    }

    // Download and run get-pip.py
    this.emit('log', 'Installing pip...');
    const getPipPath = path.join(this.envDir, 'get-pip.py');
    await this._downloadFile(GET_PIP_URL, getPipPath);

    // Sanity-check get-pip.py size — a suspiciously small file likely indicates
    // a network error page or a tampered artifact
    const pipStat = fs.statSync(getPipPath);
    if (pipStat.size < GET_PIP_MIN_BYTES) {
      try { fs.unlinkSync(getPipPath); } catch {}
      throw new Error(
        `get-pip.py download appears corrupt or truncated (${pipStat.size} bytes, expected ≥${GET_PIP_MIN_BYTES}). ` +
        'Aborting setup.'
      );
    }

    const py = this._embeddedPython();
    await this._runProcess(py, [getPipPath, '--no-warn-script-location']);

    // Clean up temp files
    try { fs.unlinkSync(zipPath); } catch {}
    try { fs.unlinkSync(getPipPath); } catch {}

    this.emit('log', `Python ${PYTHON_VERSION} installed successfully.`);
    return { found: true, version: `Python ${PYTHON_VERSION}`, command: py, args: [], source: 'embedded' };
  }

  _embeddedPython() {
    return path.join(this._embeddedPythonDir, 'python.exe');
  }

  // ═══════════════════════════════════════════════════════
  //  VIRTUAL ENVIRONMENT
  // ═══════════════════════════════════════════════════════

  async createVenv() {
    const pyInfo = this.checkPython();
    if (!pyInfo.found) throw new Error('Python 3.10+ not found');

    if (pyInfo.source === 'embedded') {
      // Embedded Python installs packages directly — no venv needed
      this._venvDir = this._embeddedPythonDir;
      this.emit('log', 'Using embedded Python (packages install directly).');
      return true;
    }

    // System Python: create a real venv
    this.emit('log', `Creating virtual environment at ${this._venvDir}...`);
    const args = [...(pyInfo.args || []), '-m', 'venv', this._venvDir, '--clear'];
    await this._runProcess(pyInfo.command, args);
    this.emit('log', 'Virtual environment created.');
    return true;
  }

  _getActivePython() {
    // Venv python
    const venvPy = process.platform === 'win32'
      ? path.join(this._venvDir, 'Scripts', 'python.exe')
      : path.join(this._venvDir, 'bin', 'python');
    if (fs.existsSync(venvPy)) return venvPy;

    // Embedded python
    const embeddedPy = this._embeddedPython();
    if (fs.existsSync(embeddedPy)) return embeddedPy;

    // System python
    const pyInfo = this.checkPython();
    if (pyInfo.found) return pyInfo.command;

    throw new Error('No Python environment available');
  }

  // ═══════════════════════════════════════════════════════
  //  PACKAGE INSTALLATION
  // ═══════════════════════════════════════════════════════

  async installPackages() {
    const py = this._getActivePython();
    const requirementsPath = this._getRequirementsPath();

    this.emit('log', 'Upgrading pip...');
    await this._runProcess(py, ['-m', 'pip', 'install', '--upgrade', 'pip'], true);

    this.emit('log', 'Installing AI packages (this may take several minutes)...');
    await this._runProcess(py, [
      '-m', 'pip', 'install', '-r', requirementsPath, '--no-warn-script-location',
    ], true);

    this.emit('log', 'All packages installed successfully.');
    return true;
  }

  _getRequirementsPath() {
    const locations = [
      path.join(process.resourcesPath || '', 'python', 'requirements.txt'),
      path.join(__dirname, '..', '..', 'python', 'requirements.txt'),
    ];
    for (const loc of locations) {
      if (fs.existsSync(loc)) return loc;
    }
    throw new Error('requirements.txt not found');
  }

  // ═══════════════════════════════════════════════════════
  //  GPU CHECK
  // ═══════════════════════════════════════════════════════

  async checkGPU() {
    let py;
    try { py = this._getActivePython(); } catch { return { cuda: false, device: 'N/A' }; }

    const script = `
import json, sys
try:
    import torch
    info = {
        "cuda": torch.cuda.is_available(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        "vram_gb": round(torch.cuda.get_device_properties(0).total_mem / 1e9, 1) if torch.cuda.is_available() else 0,
        "torch_version": torch.__version__
    }
except Exception as e:
    info = {"cuda": False, "device": "torch not installed", "error": str(e)}
try:
    import onnxruntime as ort
    info["onnx_providers"] = ort.get_available_providers()
except:
    info["onnx_providers"] = []
print(json.dumps(info))
`;
    return new Promise((resolve) => {
      const proc = spawn(py, ['-c', script], { windowsHide: true });
      let out = '';
      proc.stdout.on('data', (d) => { out += d.toString(); });
      proc.on('close', () => {
        try { resolve(JSON.parse(out.trim())); }
        catch { resolve({ cuda: false, device: 'Unknown' }); }
      });
      proc.on('error', () => resolve({ cuda: false, device: 'Error' }));
    });
  }

  // ═══════════════════════════════════════════════════════
  //  FULL SETUP — one-click from the wizard
  // ═══════════════════════════════════════════════════════

  async fullSetup() {
    // Step 1: Python
    this.emit('setup:step', { step: 'python', status: 'running', message: 'Checking for Python...' });
    let pyInfo = this.checkPython();
    if (!pyInfo.found) {
      this.emit('setup:step', { step: 'python', status: 'running', message: 'Auto-downloading Python (no install needed)...' });
      try {
        pyInfo = await this.downloadPython();
      } catch (e) {
        this.emit('setup:step', { step: 'python', status: 'error', message: `Download failed: ${e.message}` });
        throw e;
      }
    }
    this.emit('setup:step', { step: 'python', status: 'done', message: `${pyInfo.version} (${pyInfo.source})` });

    // Step 2: Venv
    this.emit('setup:step', { step: 'venv', status: 'running', message: 'Setting up environment...' });
    await this.createVenv();
    this.emit('setup:step', { step: 'venv', status: 'done', message: 'Environment ready' });

    // Step 3: Packages
    this.emit('setup:step', { step: 'packages', status: 'running', message: 'Installing AI packages...' });
    await this.installPackages();
    this.emit('setup:step', { step: 'packages', status: 'done', message: 'All packages installed' });

    // Step 4: GPU
    this.emit('setup:step', { step: 'gpu', status: 'running', message: 'Detecting GPU...' });
    const gpuInfo = await this.checkGPU();
    this.emit('setup:step', {
      step: 'gpu', status: 'done',
      message: gpuInfo.cuda ? `${gpuInfo.device} (${gpuInfo.vram_gb}GB VRAM)` : 'CPU mode',
    });

    this.setupComplete = true;
    this._markSetupDone();

    // Step 5: Start sidecar
    this.emit('setup:step', { step: 'server', status: 'running', message: 'Starting AI server...' });
    await this.start();
    this.emit('setup:step', { step: 'server', status: 'done', message: `Running on port ${SIDECAR_PORT}` });

    return gpuInfo;
  }

  // ═══════════════════════════════════════════════════════
  //  SIDECAR LIFECYCLE
  // ═══════════════════════════════════════════════════════

  async start() {
    if (this.running) return true;
    this._intentionalStop = false;
    const py = this._getActivePython();
    const serverPath = this._getServerPath();
    this.emit('log', `Starting sidecar on port ${SIDECAR_PORT}...`);

    this.process = spawn(py, ['-u', serverPath, '--port', String(SIDECAR_PORT)], {
      windowsHide: true,
      env: {
        ...process.env,
        DRACO_MODELS_DIR: this.modelsDir,
        DRACO_PORT: String(SIDECAR_PORT),
      },
    });

    this.process.stdout.on('data', (d) => this.emit('log', d.toString().trim()));
    this.process.stderr.on('data', (d) => this.emit('log', d.toString().trim()));
    this.process.on('exit', (code) => {
      this.running = false;
      this.emit('status', { running: false, exitCode: code });
      // Auto-restart on unexpected exit
      if (!this._intentionalStop && this._restartCount < this._maxRestarts) {
        const delay = this._restartBackoff[this._restartCount] || 15000;
        this._restartCount++;
        this.emit('log', `Sidecar exited unexpectedly (code ${code}). Restarting in ${delay / 1000}s (attempt ${this._restartCount}/${this._maxRestarts})...`);
        setTimeout(() => {
          if (!this._intentionalStop) {
            this.start().catch((e) => {
              this.emit('log', `Auto-restart failed: ${e.message}`);
            });
          }
        }, delay);
      } else if (!this._intentionalStop) {
        this.emit('log', `Sidecar crashed ${this._maxRestarts} times. Not restarting. Use AI → Setup Wizard to restart manually.`);
      }
    });

    // Wait for health check (up to 90s for first-time model loading)
    for (let i = 0; i < 90; i++) {
      await new Promise(r => setTimeout(r, 1000));
      if (await this._healthCheck()) {
        this.running = true;
        this._restartCount = 0; // Reset on successful start
        this.emit('status', { running: true });
        this.emit('log', 'Sidecar ready.');
        return true;
      }
    }
    throw new Error('Sidecar failed to start within 90 seconds');
  }

  stop() {
    this._intentionalStop = true;
    if (this.process) {
      this.process.kill('SIGTERM');
      setTimeout(() => {
        try { this.process?.kill('SIGKILL'); } catch {}
      }, 5000);
      this.process = null;
      this.running = false;
    }
  }

  async _healthCheck() {
    return new Promise((resolve) => {
      const req = http.get(HEALTH_URL, { timeout: 2000 }, (res) => {
        resolve(res.statusCode === 200);
      });
      req.on('error', () => resolve(false));
      req.on('timeout', () => { req.destroy(); resolve(false); });
    });
  }

  _getServerPath() {
    const locations = [
      path.join(process.resourcesPath || '', 'python', 'draco_server.py'),
      path.join(__dirname, '..', '..', 'python', 'draco_server.py'),
    ];
    for (const loc of locations) {
      if (fs.existsSync(loc)) return loc;
    }
    throw new Error('draco_server.py not found');
  }

  // ═══════════════════════════════════════════════════════
  //  API CALLS TO SIDECAR
  // ═══════════════════════════════════════════════════════

  async callEndpoint(endpoint, data) {
    if (!this.running) throw new Error('Python sidecar not running');
    return new Promise((resolve, reject) => {
      const body = JSON.stringify(data || {});
      const req = http.request({
        hostname: '127.0.0.1',
        port: SIDECAR_PORT,
        path: endpoint,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
        timeout: 120000,
      }, (res) => {
        let chunks = [];
        res.on('data', (d) => chunks.push(d));
        res.on('end', () => {
          const raw = Buffer.concat(chunks).toString();
          let parsed;
          try { parsed = JSON.parse(raw); } catch { parsed = raw; }
          // Reject on non-2xx so callers (e.g. model-manager) cannot silently
          // treat a server error as success and mark state as ready.
          if (res.statusCode < 200 || res.statusCode >= 300) {
            const msg = (parsed && parsed.detail) || (parsed && parsed.error) || raw || `HTTP ${res.statusCode}`;
            return reject(new Error(`Sidecar ${endpoint} failed (${res.statusCode}): ${msg}`));
          }
          resolve(parsed);
        });
      });
      req.on('error', reject);
      req.on('timeout', () => { req.destroy(); reject(new Error('Sidecar request timeout')); });
      req.write(body);
      req.end();
    });
  }

  // ═══════════════════════════════════════════════════════
  //  PERSISTENCE
  // ═══════════════════════════════════════════════════════

  isSetUp() {
    const marker = path.join(this.envDir, '.draco-setup-complete');
    return fs.existsSync(marker);
  }

  _markSetupDone() {
    fs.writeFileSync(path.join(this.envDir, '.draco-setup-complete'), JSON.stringify({
      date: new Date().toISOString(),
      pythonVersion: PYTHON_VERSION,
      platform: process.platform,
    }));
  }

  getStatus() {
    if (this._statusCache === undefined) {
      const pyInfo = this.checkPython();
      this._statusCache = {
        pythonFound: pyInfo.found,
        pythonSource: pyInfo.source,
        pythonVersion: pyInfo.version,
      };
    }
    return {
      running: this.running,
      setupComplete: this.isSetUp(),
      ...this._statusCache,
      port: SIDECAR_PORT,
    };
  }

  // ═══════════════════════════════════════════════════════
  //  UTILITY — download, extract, run
  // ═══════════════════════════════════════════════════════

  _downloadFile(url, dest) {
    return new Promise((resolve, reject) => {
      const file = createWriteStream(dest);
      const doGet = (targetUrl) => {
        const get = targetUrl.startsWith('https') ? https.get : http.get;
        get(targetUrl, (res) => {
          // Follow redirects
          if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
            file.close();
            try { fs.unlinkSync(dest); } catch {}
            const newFile = createWriteStream(dest);
            const redirectUrl = res.headers.location;
            const redirectGet = redirectUrl.startsWith('https') ? https.get : http.get;
            redirectGet(redirectUrl, (res2) => {
              if (res2.statusCode !== 200) {
                newFile.close();
                reject(new Error(`Download failed: HTTP ${res2.statusCode}`));
                return;
              }
              const total = parseInt(res2.headers['content-length'] || '0', 10);
              let downloaded = 0;
              res2.on('data', (chunk) => {
                downloaded += chunk.length;
                if (total > 0) {
                  this.emit('download:progress', { downloaded, total, percent: Math.round((downloaded / total) * 100) });
                }
              });
              res2.pipe(newFile);
              newFile.on('finish', () => { newFile.close(); resolve(dest); });
            }).on('error', (e) => { newFile.close(); reject(e); });
            return;
          }

          if (res.statusCode !== 200) {
            file.close();
            reject(new Error(`Download failed: HTTP ${res.statusCode}`));
            return;
          }

          const total = parseInt(res.headers['content-length'] || '0', 10);
          let downloaded = 0;
          res.on('data', (chunk) => {
            downloaded += chunk.length;
            if (total > 0) {
              this.emit('download:progress', { downloaded, total, percent: Math.round((downloaded / total) * 100) });
            }
          });

          res.pipe(file);
          file.on('finish', () => { file.close(); resolve(dest); });
        }).on('error', (e) => { file.close(); reject(e); });
      };
      doGet(url);
    });
  }

  async _extractZip(zipPath, targetDir) {
    if (process.platform === 'win32') {
      await this._runProcess('powershell', [
        '-NoProfile', '-Command',
        `Expand-Archive -Path '${zipPath}' -DestinationPath '${targetDir}' -Force`,
      ]);
    } else {
      await this._runProcess('unzip', ['-o', zipPath, '-d', targetDir]);
    }
  }

  _runProcess(cmd, args, streamLogs = false) {
    return new Promise((resolve, reject) => {
      const proc = spawn(cmd, args, {
        windowsHide: true,
        env: { ...process.env, PIP_PROGRESS_BAR: 'off' },
      });
      let stderr = '';
      proc.stdout.on('data', (d) => {
        const line = d.toString().trim();
        if (streamLogs && line) this.emit('log', line);
      });
      proc.stderr.on('data', (d) => {
        const line = d.toString().trim();
        stderr += line + '\n';
        if (streamLogs && line && !line.includes('WARNING')) this.emit('log', line);
      });
      proc.on('close', (code) => {
        if (code === 0) resolve(true);
        else reject(new Error(`Process exited with code ${code}: ${stderr.slice(0, 500)}`));
      });
      proc.on('error', reject);
    });
  }
}

module.exports = { PythonManager };
