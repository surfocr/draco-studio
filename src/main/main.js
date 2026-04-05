'use strict';
const { app, BrowserWindow, ipcMain, dialog, Menu, shell, session, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');
const { PythonManager } = require('./python-manager');
const { ModelManager } = require('./model-manager');
const { DatabaseManager } = require('./database');
const { Orchestrator } = require('./orchestrator');
const { BatchQueue } = require('./queue');

// ─── Globals ───────────────────────────────────────────
let mainWindow = null;
let pythonManager = null;
let modelManager = null;
let db = null;
let orchestrator = null;
let batchQueue = null;

const isDev = process.argv.includes('--dev');
const APP_DATA = path.join(app.getPath('userData'));
const MODELS_DIR = path.join(APP_DATA, 'models');
const PYTHON_ENV = path.join(APP_DATA, 'python-env');

// ─── Single Instance Lock ──────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) { app.quit(); }

// ─── Create Window ─────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1680,
    height: 980,
    minWidth: 900,
    minHeight: 600,
    title: 'Draco Dataset Studio v5',
    backgroundColor: '#060810',
    icon: path.join(__dirname, '..', '..', 'assets', 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webgl: true,
      webSecurity: true,
    },
    show: false,
    autoHideMenuBar: false,
  });

  // Load the v5 HTML directly — the preload injects the Electron bridge + setup wizard
  mainWindow.loadFile(path.join(__dirname, '..', '..', 'DRACO_Dataset_Studio_v5.html'));
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (isDev) mainWindow.webContents.openDevTools();
  });
  mainWindow.on('closed', () => { mainWindow = null; });

  // Log renderer console messages to main process stdout (dev only)
  if (isDev) {
    mainWindow.webContents.on('console-message', (e) => {
      const level = e.level !== undefined ? e.level : 0;
      const message = e.message || '';
      const prefix = ['LOG', 'WARN', 'ERR'][level] || 'LOG';
      if (message && !message.includes('Autofill') && !message.includes('electron/js2c')) {
        console.log(`[Renderer:${prefix}] ${message}`);
      }
    });
  }

  buildMenu();

  // ── CORS Allowlist ──────────────────────────────────
  // Allow renderer to fetch from AI API domains and localhost sidecar
  const allowedOrigins = [
    'http://127.0.0.1:18082', 'http://localhost:18082',  // Python sidecar
    'http://127.0.0.1:11434', 'http://localhost:11434',  // Ollama
    'http://127.0.0.1:1234', 'http://localhost:1234',    // LM Studio
    'http://127.0.0.1:5000', 'http://localhost:5000',    // DeepFace/InsightFace
    'http://127.0.0.1:8085', 'http://localhost:8085',    // InsightFace-REST
  ];
  const allowedAPIDomains = [
    'api.anthropic.com', 'api.openai.com', 'generativelanguage.googleapis.com',
    'openrouter.ai', 'api.groq.com', 'api.wavespeed.ai', 'api.fal.ai',
    'cdn.jsdelivr.net', 'unpkg.com', 'cdnjs.cloudflare.com',  // CDN fallbacks
  ];
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const url = new URL(details.url);
    const isAllowed = allowedOrigins.some(o => details.url.startsWith(o))
      || allowedAPIDomains.includes(url.hostname);
    if (isAllowed) {
      const headers = { ...details.responseHeaders };
      headers['Access-Control-Allow-Origin'] = ['*'];
      headers['Access-Control-Allow-Headers'] = ['*'];
      headers['Access-Control-Allow-Methods'] = ['GET, POST, OPTIONS'];
      callback({ responseHeaders: headers });
    } else {
      callback({ responseHeaders: details.responseHeaders });
    }
  });
}

// ─── App Menu ──────────────────────────────────────────
function buildMenu() {
  const template = [
    {
      label: 'File',
      submenu: [
        {
          label: 'Open Images...',
          accelerator: 'CmdOrCtrl+O',
          click: () => openImageDialog(),
        },
        {
          label: 'Open Folder...',
          accelerator: 'CmdOrCtrl+Shift+O',
          click: () => openFolderDialog(),
        },
        { type: 'separator' },
        {
          label: 'Save Project',
          accelerator: 'CmdOrCtrl+S',
          click: () => mainWindow?.webContents.send('menu:save-project'),
        },
        {
          label: 'Load Project...',
          accelerator: 'CmdOrCtrl+L',
          click: () => loadProjectDialog(),
        },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'AI',
      submenu: [
        {
          label: 'Setup Wizard...',
          click: () => mainWindow?.webContents.send('menu:setup-wizard'),
        },
        {
          label: 'Re-check Local Backends',
          click: () => mainWindow?.webContents.send('menu:recheck-backends'),
        },
        { type: 'separator' },
        {
          label: 'Model Manager...',
          click: () => mainWindow?.webContents.send('menu:model-manager'),
        },
      ],
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Keyboard Shortcuts',
          accelerator: 'F1',
          click: () => mainWindow?.webContents.send('menu:help'),
        },
        { type: 'separator' },
        {
          label: 'About Draco Dataset Studio',
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: 'Draco Dataset Studio v5',
              message: 'Draco Dataset Studio v5',
              detail: 'AI-powered LoRA training dataset curation platform.\n\nBlazeFace · InsightFace ArcFace 512-d · DracoFlow v2 · Florence-2 · CLIP · Lanczos-3\n\nElectron + Python sidecar architecture.',
            });
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ─── File Dialogs ──────────────────────────────────────
async function openImageDialog() {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Select Images',
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Images', extensions: ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tiff', 'heic', 'avif'] }],
  });
  if (!result.canceled && result.filePaths.length > 0) {
    mainWindow.webContents.send('files:opened', result.filePaths);
  }
}

async function openFolderDialog() {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Select Image Folder',
    properties: ['openDirectory'],
  });
  if (!result.canceled && result.filePaths.length > 0) {
    const folderPath = result.filePaths[0];
    const exts = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.heic', '.avif']);
    const files = [];
    try {
      const entries = fs.readdirSync(folderPath);
      for (const entry of entries) {
        if (exts.has(path.extname(entry).toLowerCase())) {
          files.push(path.join(folderPath, entry));
        }
      }
    } catch (e) { /* ignore read errors */ }
    if (files.length > 0) {
      mainWindow.webContents.send('files:opened', files);
    }
  }
}

async function loadProjectDialog() {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Load Project',
    properties: ['openFile'],
    filters: [{ name: 'Draco Project', extensions: ['draco'] }],
  });
  if (!result.canceled && result.filePaths.length > 0) {
    mainWindow.webContents.send('project:load', result.filePaths[0]);
  }
}

// ─── IPC Handlers ──────────────────────────────────────
function registerIPC() {
  // File system
  ipcMain.handle('fs:read-file-base64', async (_, filePath) => {
    const buf = fs.readFileSync(filePath);
    const ext = path.extname(filePath).toLowerCase();
    const mime = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp', '.tiff': 'image/tiff', '.tif': 'image/tiff', '.heic': 'image/heic', '.avif': 'image/avif' }[ext] || 'image/jpeg';
    return `data:${mime};base64,${buf.toString('base64')}`;
  });

  ipcMain.handle('fs:open-images', () => openImageDialog());
  ipcMain.handle('fs:open-folder', () => openFolderDialog());
  ipcMain.handle('fs:get-file-info', (_, filePath) => {
    try {
      const stat = fs.statSync(filePath);
      return { name: path.basename(filePath), size: stat.size, path: filePath };
    } catch { return null; }
  });

  ipcMain.handle('fs:save-file', async (_, { defaultName, filters, data }) => {
    const result = await dialog.showSaveDialog(mainWindow, {
      defaultPath: defaultName,
      filters: filters || [{ name: 'All Files', extensions: ['*'] }],
    });
    if (!result.canceled && result.filePath) {
      fs.writeFileSync(result.filePath, Buffer.from(data));
      return result.filePath;
    }
    return null;
  });

  // Python sidecar
  ipcMain.handle('python:status', () => pythonManager?.getStatus() || { running: false });
  ipcMain.handle('python:start', () => pythonManager?.start());
  ipcMain.handle('python:stop', () => pythonManager?.stop());
  ipcMain.handle('python:call', async (_, { endpoint, data }) => {
    return pythonManager?.callEndpoint(endpoint, data);
  });

  // Models
  ipcMain.handle('models:status', () => modelManager?.getAllStatus() || {});
  ipcMain.handle('models:download', (_, modelId) => modelManager?.downloadModel(modelId));
  ipcMain.handle('models:download-all', () => modelManager?.downloadAll());

  // Setup wizard
  ipcMain.handle('setup:check-python', () => pythonManager?.checkPython());
  ipcMain.handle('setup:download-python', () => pythonManager?.downloadPython());
  ipcMain.handle('setup:create-venv', () => pythonManager?.createVenv());
  ipcMain.handle('setup:install-packages', () => pythonManager?.installPackages());
  ipcMain.handle('setup:check-gpu', () => pythonManager?.checkGPU());
  ipcMain.handle('setup:full-setup', () => pythonManager?.fullSetup());

  // Database
  ipcMain.handle('db:query', (_, { sql, params }) => db?.query(sql, params));
  ipcMain.handle('db:run', (_, { sql, params }) => db?.run(sql, params));
  ipcMain.handle('db:get-api-keys', () => db?.getApiKeys());
  ipcMain.handle('db:set-api-key', (_, { provider, key }) => db?.setApiKey(provider, key));

  // Orchestrator
  ipcMain.handle('orchestrator:route', async (_, task) => orchestrator?.route(task));
  ipcMain.handle('orchestrator:get-config', () => orchestrator?.getConfig());
  ipcMain.handle('orchestrator:set-config', (_, config) => orchestrator?.setConfig(config));

  // Batch queue
  ipcMain.handle('queue:submit', (_, jobs) => batchQueue?.submit(jobs));
  ipcMain.handle('queue:pause', () => batchQueue?.pause());
  ipcMain.handle('queue:resume', () => batchQueue?.resume());
  ipcMain.handle('queue:cancel', () => batchQueue?.cancel());
  ipcMain.handle('queue:status', () => batchQueue?.getStatus());

  // Dataset analysis (calls Python sidecar endpoints)
  ipcMain.handle('analysis:dataset', async (_, data) => {
    return pythonManager?.callEndpoint('/analyze-dataset', data);
  });
  ipcMain.handle('analysis:quality', async (_, data) => {
    return pythonManager?.callEndpoint('/quality-assess', data);
  });
  ipcMain.handle('analysis:buckets', async (_, data) => {
    return pythonManager?.callEndpoint('/calculate-buckets', data);
  });
  ipcMain.handle('analysis:duplicates', async (_, data) => {
    return pythonManager?.callEndpoint('/find-duplicates', data);
  });
  ipcMain.handle('analysis:caption', async (_, data) => {
    return pythonManager?.callEndpoint('/caption', data);
  });
  ipcMain.handle('analysis:topiq', async (_, data) => {
    return pythonManager?.callEndpoint('/topiq-score', data);
  });
  ipcMain.handle('analysis:remove-bg', async (_, data) => {
    return pythonManager?.callEndpoint('/remove-background', data);
  });
  ipcMain.handle('analysis:duplicates-advanced', async (_, data) => {
    return pythonManager?.callEndpoint('/find-duplicates-advanced', data);
  });
  ipcMain.handle('analysis:align-face', async (_, data) => {
    return pythonManager?.callEndpoint('/align-face', data);
  });
  ipcMain.handle('analysis:detect-watermark', async (_, data) => {
    return pythonManager?.callEndpoint('/detect-watermark', data);
  });
  ipcMain.handle('analysis:enhanced-quality', async (_, data) => {
    return pythonManager?.callEndpoint('/enhanced-quality', data);
  });
  ipcMain.handle('analysis:latent-quality', async (_, data) => {
    return pythonManager?.callEndpoint('/latent-quality', data);
  });
  ipcMain.handle('analysis:score-caption', async (_, data) => {
    return pythonManager?.callEndpoint('/score-caption', data);
  });
  ipcMain.handle('analysis:clip-diversity', async (_, data) => {
    return pythonManager?.callEndpoint('/clip-diversity', data);
  });
  ipcMain.handle('analysis:augment', async (_, data) => {
    return pythonManager?.callEndpoint('/augment', data);
  });
  ipcMain.handle('analysis:detect-borders', async (_, data) => {
    return pythonManager?.callEndpoint('/detect-borders', data);
  });

  // App info
  ipcMain.handle('app:get-paths', () => ({
    appData: APP_DATA,
    models: MODELS_DIR,
    pythonEnv: PYTHON_ENV,
    resources: process.resourcesPath || path.join(__dirname, '..', '..'),
  }));
  ipcMain.handle('app:get-version', () => app.getVersion());

  // Read v5 HTML (for potential iframe fallback loading)
  ipcMain.handle('app:read-v4-html', () => {
    const locations = [
      path.join(__dirname, '..', '..', 'DRACO_Dataset_Studio_v5.html'),
      path.join(process.resourcesPath || '', 'DRACO_Dataset_Studio_v5.html'),
      // fallback to v4 if v5 not found
      path.join(__dirname, '..', '..', 'DRACO_Dataset_Studio_v4.html'),
      path.join(process.resourcesPath || '', 'DRACO_Dataset_Studio_v4.html'),
    ];
    for (const loc of locations) {
      try { if (fs.existsSync(loc)) return fs.readFileSync(loc, 'utf8'); } catch {}
    }
    return null;
  });

  // safeStorage availability check
  ipcMain.handle('app:safe-storage-available', () => {
    return safeStorage.isEncryptionAvailable();
  });

  // Shell
  ipcMain.handle('shell:open-external', (_, url) => shell.openExternal(url));
  ipcMain.handle('shell:open-path', (_, p) => shell.openPath(p));
}

// ─── App Lifecycle ─────────────────────────────────────
app.whenReady().then(async () => {
  // Ensure directories exist
  for (const dir of [APP_DATA, MODELS_DIR, PYTHON_ENV]) {
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  }

  try {
    // Initialize subsystems
    db = new DatabaseManager(path.join(APP_DATA, 'draco.db'));
    await db._initPromise;
  } catch (e) {
    console.error('[DRACO] Database init failed:', e);
    dialog.showErrorBox('Database Error', `Failed to initialize database: ${e.message}\n\nThe app will start in limited mode.`);
  }

  try {
    pythonManager = new PythonManager(PYTHON_ENV, MODELS_DIR, (event, data) => {
      mainWindow?.webContents.send('python:event', { event, data });
      if (event === 'download:progress') {
        mainWindow?.webContents.send('python:download-progress', data);
      }
    });
    modelManager = new ModelManager(MODELS_DIR, pythonManager, (event, data) => {
      mainWindow?.webContents.send('models:event', { event, data });
    });
    orchestrator = new Orchestrator(pythonManager, db);
    batchQueue = new BatchQueue(orchestrator, db, (event, data) => {
      mainWindow?.webContents.send('queue:event', { event, data });
    });
  } catch (e) {
    console.error('[DRACO] Subsystem init failed:', e);
    // Non-fatal: app still opens, just without Python features
  }

  registerIPC();
  createWindow();

  // Auto-start Python sidecar if previously set up
  if (pythonManager?.isSetUp()) {
    pythonManager.start().catch((e) => {
      console.warn('[DRACO] Auto-start sidecar failed:', e.message);
    });
  }
});

app.on('before-quit', () => {
  // Ensure Python sidecar is stopped before quitting
  if (pythonManager) {
    try { pythonManager.stop(); } catch {}
  }
  if (db) {
    try { db.close(); } catch {}
  }
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});
