'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// ─── Draco Bridge ─────────────────────────────────────
// Exposes a safe API to the renderer process via window.draco
contextBridge.exposeInMainWorld('draco', {
  // ── File System ──
  fs: {
    openImages: () => ipcRenderer.invoke('fs:open-images'),
    openFolder: () => ipcRenderer.invoke('fs:open-folder'),
    readFileBase64: (filePath) => ipcRenderer.invoke('fs:read-file-base64', filePath),
    getFileInfo: (filePath) => ipcRenderer.invoke('fs:get-file-info', filePath),
    saveFile: (opts) => ipcRenderer.invoke('fs:save-file', opts),
  },

  // ── Python Sidecar ──
  python: {
    status: () => ipcRenderer.invoke('python:status'),
    start: () => ipcRenderer.invoke('python:start'),
    stop: () => ipcRenderer.invoke('python:stop'),
    call: (endpoint, data) => ipcRenderer.invoke('python:call', { endpoint, data }),
    onEvent: (callback) => {
      const handler = (_, payload) => callback(payload);
      ipcRenderer.on('python:event', handler);
      return () => ipcRenderer.removeListener('python:event', handler);
    },
  },

  // ── Model Manager ──
  models: {
    status: () => ipcRenderer.invoke('models:status'),
    download: (modelId) => ipcRenderer.invoke('models:download', modelId),
    downloadAll: () => ipcRenderer.invoke('models:download-all'),
    onEvent: (callback) => {
      const handler = (_, payload) => callback(payload);
      ipcRenderer.on('models:event', handler);
      return () => ipcRenderer.removeListener('models:event', handler);
    },
  },

  // ── Setup Wizard ──
  setup: {
    checkPython: () => ipcRenderer.invoke('setup:check-python'),
    downloadPython: () => ipcRenderer.invoke('setup:download-python'),
    createVenv: () => ipcRenderer.invoke('setup:create-venv'),
    installPackages: () => ipcRenderer.invoke('setup:install-packages'),
    checkGPU: () => ipcRenderer.invoke('setup:check-gpu'),
    fullSetup: () => ipcRenderer.invoke('setup:full-setup'),
    onDownloadProgress: (callback) => {
      const handler = (_, data) => callback(data);
      ipcRenderer.on('python:download-progress', handler);
      return () => ipcRenderer.removeListener('python:download-progress', handler);
    },
  },

  // ── Database ──
  db: {
    query: (sql, params) => ipcRenderer.invoke('db:query', { sql, params }),
    run: (sql, params) => ipcRenderer.invoke('db:run', { sql, params }),
    getApiKeys: () => ipcRenderer.invoke('db:get-api-keys'),
    setApiKey: (provider, key) => ipcRenderer.invoke('db:set-api-key', { provider, key }),
  },

  // ── Dataset Analysis ──
  analysis: {
    dataset: (data) => ipcRenderer.invoke('analysis:dataset', data),
    quality: (data) => ipcRenderer.invoke('analysis:quality', data),
    buckets: (data) => ipcRenderer.invoke('analysis:buckets', data),
    duplicates: (data) => ipcRenderer.invoke('analysis:duplicates', data),
    caption: (data) => ipcRenderer.invoke('analysis:caption', data),
    topiq: (data) => ipcRenderer.invoke('analysis:topiq', data),
    removeBg: (data) => ipcRenderer.invoke('analysis:remove-bg', data),
    duplicatesAdvanced: (data) => ipcRenderer.invoke('analysis:duplicates-advanced', data),
    alignFace: (data) => ipcRenderer.invoke('analysis:align-face', data),
    detectWatermark: (data) => ipcRenderer.invoke('analysis:detect-watermark', data),
    enhancedQuality: (data) => ipcRenderer.invoke('analysis:enhanced-quality', data),
    latentQuality: (data) => ipcRenderer.invoke('analysis:latent-quality', data),
    scoreCaption: (data) => ipcRenderer.invoke('analysis:score-caption', data),
    clipDiversity: (data) => ipcRenderer.invoke('analysis:clip-diversity', data),
    augment: (data) => ipcRenderer.invoke('analysis:augment', data),
    detectBorders: (data) => ipcRenderer.invoke('analysis:detect-borders', data),
  },

  // ── Orchestrator ──
  orchestrator: {
    route: (task) => ipcRenderer.invoke('orchestrator:route', task),
    getConfig: () => ipcRenderer.invoke('orchestrator:get-config'),
    setConfig: (config) => ipcRenderer.invoke('orchestrator:set-config', config),
  },

  // ── Batch Queue ──
  queue: {
    submit: (jobs) => ipcRenderer.invoke('queue:submit', jobs),
    pause: () => ipcRenderer.invoke('queue:pause'),
    resume: () => ipcRenderer.invoke('queue:resume'),
    cancel: () => ipcRenderer.invoke('queue:cancel'),
    status: () => ipcRenderer.invoke('queue:status'),
    onEvent: (callback) => {
      const handler = (_, payload) => callback(payload);
      ipcRenderer.on('queue:event', handler);
      return () => ipcRenderer.removeListener('queue:event', handler);
    },
  },

  // ── App ──
  app: {
    getPaths: () => ipcRenderer.invoke('app:get-paths'),
    getVersion: () => ipcRenderer.invoke('app:get-version'),
    readV4Html: () => ipcRenderer.invoke('app:read-v4-html'),
    safeStorageAvailable: () => ipcRenderer.invoke('app:safe-storage-available'),
    openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
    openPath: (p) => ipcRenderer.invoke('shell:open-path', p),
  },

  // ── Menu Events ──
  on: (channel, callback) => {
    const validChannels = [
      'files:opened', 'menu:save-project', 'menu:setup-wizard',
      'menu:recheck-backends', 'menu:model-manager', 'menu:help',
      'project:load',
    ];
    if (validChannels.includes(channel)) {
      const handler = (_, ...args) => callback(...args);
      ipcRenderer.on(channel, handler);
      return () => ipcRenderer.removeListener(channel, handler);
    }
  },

  // ── Platform Info ──
  platform: process.platform,
  isElectron: true,
});

// ─── Inject Setup Wizard + Electron Bridge into the v4 page ───
window.addEventListener('DOMContentLoaded', () => {
  // Patch version badge
  const versionBadge = document.querySelector('.ver');
  if (versionBadge && versionBadge.textContent.includes('v4')) {
    versionBadge.textContent = 'v5';
  }

  // Inject setup wizard overlay
  const overlay = document.createElement('div');
  overlay.id = 'setup-overlay';
  overlay.className = 'hidden';
  overlay.innerHTML = `
    <style>
      #setup-overlay{position:fixed;inset:0;background:rgba(6,8,16,0.97);z-index:100000;display:flex;align-items:center;justify-content:center;font-family:'Segoe UI',system-ui,sans-serif;color:#C8D8F5}
      #setup-overlay.hidden{display:none}
      .setup-card{background:#0D1222;border:1px solid #1A2440;border-radius:16px;padding:32px;max-width:640px;width:92%;box-shadow:0 0 60px rgba(0,220,255,0.08)}
      .setup-title{font-size:24px;font-weight:900;color:#fff;margin-bottom:4px;display:flex;align-items:center;gap:12px}
      .setup-title .logo{width:44px;height:44px;border-radius:9px;background:linear-gradient(135deg,#00DCFF,#B44FFF);display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:900;color:#fff;box-shadow:0 0 14px rgba(0,220,255,0.4)}
      .setup-sub{font-size:12px;color:#607AAB;margin-bottom:20px}
      .setup-welcome{font-size:13px;color:#8899BB;line-height:1.6;margin-bottom:20px;padding:12px 14px;background:#090D1A;border:1px solid #1A2440;border-radius:8px}
      .setup-welcome b{color:#fff}
      .setup-step{display:flex;align-items:center;gap:12px;padding:12px 14px;background:#090D1A;border:1px solid #1A2440;border-radius:8px;margin-bottom:8px;transition:all 0.2s}
      .setup-step.active{border-color:#00DCFF;background:rgba(0,220,255,0.06)}
      .setup-step.done{border-color:#00FF9D;background:rgba(0,255,157,0.04)}
      .setup-step.error{border-color:#FF3E50;background:rgba(255,62,80,0.04)}
      .step-icon{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}
      .step-icon.pending{background:#12172A;color:#607AAB;border:1px solid #2A3B5E}
      .step-icon.running{background:rgba(0,220,255,0.15);color:#00DCFF;border:1px solid #00DCFF;animation:draco-spin 1.2s linear infinite}
      .step-icon.done{background:rgba(0,255,157,0.15);color:#00FF9D;border:1px solid #00FF9D}
      .step-icon.error{background:rgba(255,62,80,0.15);color:#FF3E50;border:1px solid #FF3E50}
      @keyframes draco-spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
      .step-text{flex:1;min-width:0}
      .step-name{font-size:13px;font-weight:700;color:#fff}
      .step-detail{font-size:10px;color:#607AAB;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .step-progress{width:100%;height:4px;background:#12172A;border-radius:2px;margin-top:6px;overflow:hidden;display:none}
      .step-progress.show{display:block}
      .step-progress-bar{height:100%;background:linear-gradient(90deg,#00DCFF,#B44FFF);border-radius:2px;transition:width 0.3s;width:0%}
      .setup-actions{display:flex;gap:8px;margin-top:18px;flex-wrap:wrap}
      .setup-btn{border:none;border-radius:8px;padding:10px 20px;cursor:pointer;font-size:12px;font-weight:700;font-family:inherit;transition:all 0.15s}
      .setup-btn.primary{background:rgba(0,220,255,0.2);color:#00DCFF;border:1px solid #00DCFF}.setup-btn.primary:hover{background:#00DCFF;color:#000}
      .setup-btn.primary:disabled{opacity:.4;cursor:not-allowed}
      .setup-btn.secondary{background:#12172A;color:#607AAB;border:1px solid #2A3B5E}.setup-btn.secondary:hover{border-color:#00DCFF;color:#00DCFF}
      .setup-btn.success{background:rgba(0,255,157,0.15);color:#00FF9D;border:1px solid #00FF9D}
      .setup-log{background:#040610;border:1px solid #1A2440;border-radius:6px;padding:8px;max-height:140px;overflow-y:auto;font-family:'Cascadia Code','Consolas',monospace;font-size:10px;line-height:1.7;color:#00FF9D;margin-top:12px;display:none}
      .setup-log.show{display:block}
    </style>
    <div class="setup-card">
      <div class="setup-title">
        <div class="logo">D</div>
        <div>DRACO <span style="color:#00DCFF">Dataset Studio</span> <span style="font-size:11px;color:#B44FFF;background:rgba(180,79,255,0.12);border:1px solid #B44FFF;border-radius:3px;padding:1px 6px;margin-left:4px">v5</span></div>
      </div>
      <div class="setup-sub">AI-powered dataset curation for LoRA training</div>
      <div class="setup-welcome" id="setup-welcome">
        Welcome! This wizard sets up the <b>local AI pipeline</b> — face detection, captioning, quality scoring, and more. Everything runs privately on your machine.<br><br>
        <b>No Python install needed</b> — we'll download a portable Python automatically.<br>
        Or click <b>Browser-Only Mode</b> to skip AI features and use the app immediately.
      </div>
      <div id="setup-steps" style="display:none">
        <div class="setup-step" id="step-python"><div class="step-icon pending" id="icon-python">1</div><div class="step-text"><div class="step-name">Python Runtime</div><div class="step-detail" id="detail-python">Auto-download portable Python 3.11</div><div class="step-progress" id="progress-python"><div class="step-progress-bar" id="pbar-python"></div></div></div></div>
        <div class="setup-step" id="step-venv"><div class="step-icon pending" id="icon-venv">2</div><div class="step-text"><div class="step-name">Environment</div><div class="step-detail" id="detail-venv">Configure isolated Python environment</div></div></div>
        <div class="setup-step" id="step-packages"><div class="step-icon pending" id="icon-packages">3</div><div class="step-text"><div class="step-name">AI Packages</div><div class="step-detail" id="detail-packages">PyTorch, InsightFace, CLIP, Florence-2</div><div class="step-progress" id="progress-packages"><div class="step-progress-bar" id="pbar-packages"></div></div></div></div>
        <div class="setup-step" id="step-gpu"><div class="step-icon pending" id="icon-gpu">4</div><div class="step-text"><div class="step-name">GPU Detection</div><div class="step-detail" id="detail-gpu">Check for CUDA / RTX acceleration</div></div></div>
        <div class="setup-step" id="step-server"><div class="step-icon pending" id="icon-server">5</div><div class="step-text"><div class="step-name">AI Server</div><div class="step-detail" id="detail-server">Start local analysis engine</div></div></div>
      </div>
      <div id="setup-log" class="setup-log"></div>
      <div class="setup-actions">
        <button class="setup-btn primary" id="setup-start-btn">Install AI Pipeline</button>
        <button class="setup-btn secondary" id="setup-skip-btn">Browser-Only Mode</button>
        <button class="setup-btn secondary" id="setup-log-toggle" style="margin-left:auto;display:none">Show Log</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  // Inject the bridge + setup wizard logic as a script in the renderer world
  const script = document.createElement('script');
  script.textContent = `
(function(){
  'use strict';
  var D = window.draco;
  if (!D || !D.isElectron) return;
  console.log('[DRACO] Electron bridge active');

  // ── Setup Wizard Logic ─────────────────────────────────
  var setupRunning = false;

  function updateStep(stepId, state, detail) {
    var icon = document.getElementById('icon-' + stepId);
    var detailEl = document.getElementById('detail-' + stepId);
    var step = document.getElementById('step-' + stepId);
    if (!icon) return;
    icon.className = 'step-icon ' + state;
    step.className = 'setup-step ' + (state === 'running' ? 'active' : state === 'done' ? 'done' : state === 'error' ? 'error' : '');
    icon.textContent = state === 'done' ? '\\u2713' : state === 'error' ? '\\u2717' : state === 'running' ? '\\u25ce' : icon.textContent;
    if (detail) detailEl.textContent = detail;
  }

  function showProgress(stepId, percent) {
    var container = document.getElementById('progress-' + stepId);
    var bar = document.getElementById('pbar-' + stepId);
    if (container) { container.classList.add('show'); }
    if (bar) { bar.style.width = percent + '%'; }
  }

  function hideProgress(stepId) {
    var container = document.getElementById('progress-' + stepId);
    if (container) { container.classList.remove('show'); }
  }

  function appendLog(msg) {
    var log = document.getElementById('setup-log');
    if (log) { log.innerHTML += '<div>' + msg + '</div>'; log.scrollTop = log.scrollHeight; }
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(0) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  document.getElementById('setup-start-btn').onclick = async function() {
    if (setupRunning) return;
    setupRunning = true;
    var btn = document.getElementById('setup-start-btn');
    btn.disabled = true;
    btn.textContent = 'Setting up...';

    // Show step list, hide welcome
    document.getElementById('setup-steps').style.display = 'block';
    document.getElementById('setup-welcome').style.display = 'none';
    document.getElementById('setup-log-toggle').style.display = 'block';

    // Listen for events
    D.python.onEvent(function(payload) {
      if (payload.event === 'log') appendLog(payload.data);
      if (payload.event === 'setup:step') {
        var d = payload.data;
        updateStep(d.step, d.status, d.message);
        if (d.status === 'done' || d.status === 'error') hideProgress(d.step);
      }
      if (payload.event === 'download:progress') {
        var p = payload.data;
        showProgress('python', p.percent);
        updateStep('python', 'running', 'Downloading Python... ' + formatBytes(p.downloaded) + ' / ' + formatBytes(p.total) + ' (' + p.percent + '%)');
      }
    });

    // Also listen on the dedicated download progress channel
    D.setup.onDownloadProgress(function(data) {
      showProgress('python', data.percent);
      updateStep('python', 'running', 'Downloading... ' + formatBytes(data.downloaded) + ' / ' + formatBytes(data.total) + ' (' + data.percent + '%)');
    });

    try {
      // Use fullSetup — it handles everything including auto-download
      await D.setup.fullSetup();

      btn.textContent = '\\u2713 Setup Complete!';
      btn.className = 'setup-btn success';
      btn.disabled = true;
      setTimeout(function() { document.getElementById('setup-overlay').classList.add('hidden'); }, 2000);
    } catch(e) {
      appendLog('\\u2717 Error: ' + (e.message || e));
      btn.textContent = 'Retry Setup';
      btn.className = 'setup-btn primary';
      btn.disabled = false;
      // Show log automatically on error
      document.getElementById('setup-log').classList.add('show');
    }
    setupRunning = false;
  };

  document.getElementById('setup-skip-btn').onclick = function() {
    document.getElementById('setup-overlay').classList.add('hidden');
  };
  document.getElementById('setup-log-toggle').onclick = function() {
    var log = document.getElementById('setup-log');
    log.classList.toggle('show');
    document.getElementById('setup-log-toggle').textContent = log.classList.contains('show') ? 'Hide Log' : 'Show Log';
  };

  // Auto-check if setup needed
  (async function() {
    try {
      var status = await D.python.status();
      if (!status.setupComplete) document.getElementById('setup-overlay').classList.remove('hidden');
    } catch(e) {
      document.getElementById('setup-overlay').classList.remove('hidden');
    }
  })();

  // ── File Opening (from File menu) ─────────────────────
  D.on('files:opened', async function(filePaths) {
    if (!filePaths || !filePaths.length) return;
    console.log('[DRACO Bridge] Received', filePaths.length, 'files');
    var loaded = 0, failed = 0;
    for (var i = 0; i < filePaths.length; i++) {
      try {
        var dataUrl = await D.fs.readFileBase64(filePaths[i]);
        var info = await D.fs.getFileInfo(filePaths[i]);
        if (typeof images !== 'undefined') {
          images.push({
            id: Math.random().toString(36).slice(2, 10),
            url: dataUrl,
            name: info ? info.name : filePaths[i].split(/[\\\\/]/).pop(),
            size: info ? info.size : 0,
            filePath: filePaths[i],
            cat: 'uncategorized',
            detResult: null,
            selected: false
          });
          loaded++;
        }
      } catch(e) { failed++; }
    }
    if (loaded > 0) {
      if (typeof afterLoad === 'function') afterLoad(loaded, 0, failed);
      else if (typeof renderAll === 'function') {
        var upz = document.getElementById('upz'); if (upz) upz.style.display = 'none';
        var appEl = document.getElementById('app'); if (appEl) appEl.style.display = 'grid';
        var hdr = document.getElementById('hdr-r'); if (hdr) hdr.style.display = 'flex';
        renderAll();
      }
      if (typeof showToast === 'function') showToast('\\u25c8 Loaded ' + loaded + ' images');
      if (typeof modelReady !== 'undefined' && modelReady && typeof runAll === 'function') runAll();
    }
  });

  // ── Python Sidecar Helpers ─────────────────────────────
  window._dracoEnhancedAnalysis = async function(imageB64) {
    try { return await D.python.call('/quality-assess', {image: imageB64}); }
    catch(e) { return null; }
  };

  window._dracoGetFaceEmbedding = async function(imageB64) {
    try {
      var r = await D.python.call('/batch-faces', {images: [imageB64]});
      return (r && r.results && r.results[0] && r.results[0].embedding) ? r.results[0] : null;
    } catch(e) { return null; }
  };

  window._dracoCaption = async function(imageB64) {
    try { var r = await D.python.call('/caption', {image: imageB64}); return r ? r.caption : null; }
    catch(e) { return null; }
  };

  // NOTE: Sidecar status badge is created by v5 bridge (DRACO_Dataset_Studio_v5.html)
  // to avoid duplicate badges and double-polling.

  // ── Dataset Analysis Panel ──────────────────────────────
  // Exposes comprehensive dataset analysis from all training guides
  window._dracoAnalyzeDataset = async function(opts) {
    if (!D || !D.analysis) return null;
    try {
      return await D.analysis.dataset(opts);
    } catch(e) { console.warn('[DRACO] Dataset analysis failed:', e); return null; }
  };

  window._dracoCalculateBuckets = async function(widths, heights, targetRes) {
    if (!D || !D.analysis) return null;
    try {
      return await D.analysis.buckets({widths: widths, heights: heights, target_resolution: targetRes || 1024});
    } catch(e) { return null; }
  };

  window._dracoFindDuplicates = async function(imageB64s, threshold) {
    if (!D || !D.analysis) return null;
    try {
      return await D.analysis.duplicates({images: imageB64s, threshold: threshold || 9});
    } catch(e) { return null; }
  };

  window._dracoCaptionWithMode = async function(imageB64, mode, triggerWord) {
    if (!D || !D.analysis) return null;
    try {
      return await D.analysis.caption({image: imageB64, mode: mode || 'detailed', trigger_word: triggerWord || null});
    } catch(e) { return null; }
  };

  // ── New v5.1 helpers (from research improvements) ──
  window._dracoDetectWatermark = async function(imageB64) {
    if (!D || !D.analysis) return null;
    try { return await D.analysis.detectWatermark({image: imageB64}); }
    catch(e) { return null; }
  };

  window._dracoAlignFace = async function(imageB64) {
    if (!D || !D.analysis) return null;
    try { return await D.analysis.alignFace({image: imageB64}); }
    catch(e) { return null; }
  };

  window._dracoEnhancedQuality = async function(imageB64) {
    if (!D || !D.analysis) return null;
    try { return await D.analysis.enhancedQuality({image: imageB64}); }
    catch(e) { return null; }
  };

  window._dracoLatentQuality = async function(imageB64) {
    if (!D || !D.analysis) return null;
    try { return await D.analysis.latentQuality({image: imageB64}); }
    catch(e) { return null; }
  };

  window._dracoScoreCaption = async function(caption, targetModel, triggerWord, hasFace) {
    if (!D || !D.analysis) return null;
    try { return await D.analysis.scoreCaption({caption: caption, target_model: targetModel || 'z_image_turbo', trigger_word: triggerWord || null, has_face: hasFace !== false}); }
    catch(e) { return null; }
  };

  window._dracoClipDiversity = async function(imageB64s) {
    if (!D || !D.analysis) return null;
    try { return await D.analysis.clipDiversity({images: imageB64s}); }
    catch(e) { return null; }
  };

  window._dracoAugment = async function(imageB64, opts) {
    if (!D || !D.analysis) return null;
    try { return await D.analysis.augment(Object.assign({image: imageB64, horizontal_flip: true}, opts || {})); }
    catch(e) { return null; }
  };

  window._dracoDetectBorders = async function(imageB64) {
    if (!D || !D.analysis) return null;
    try { return await D.analysis.detectBorders({image: imageB64}); }
    catch(e) { return null; }
  };

  // Inject Dataset Report button into the sidebar
  setTimeout(function() {
    var sidebar = document.querySelector('.sb') || document.querySelector('[class*=sidebar]');
    if (!sidebar) return;

    var reportBtn = document.createElement('button');
    reportBtn.id = 'draco-report-btn';
    reportBtn.textContent = '\\u25c8 Dataset Report';
    reportBtn.title = 'Analyze dataset quality, composition, and training readiness';
    reportBtn.style.cssText = 'width:100%;padding:8px 10px;margin-top:6px;background:rgba(180,79,255,0.08);color:#B44FFF;border:1px solid rgba(180,79,255,0.3);border-radius:6px;cursor:pointer;font-size:10px;font-weight:700;font-family:inherit;transition:all 0.15s;text-align:left';
    reportBtn.onmouseenter = function() { this.style.background = 'rgba(180,79,255,0.18)'; };
    reportBtn.onmouseleave = function() { this.style.background = 'rgba(180,79,255,0.08)'; };
    reportBtn.onclick = function() { window._dracoShowReportPanel(); };

    // Find a good place to insert
    var actionArea = sidebar.querySelector('.sb-actions') || sidebar;
    actionArea.appendChild(reportBtn);
  }, 3000);

  // Dataset report panel overlay
  window._dracoShowReportPanel = function() {
    var existing = document.getElementById('draco-report-overlay');
    if (existing) { existing.remove(); return; }

    var ov = document.createElement('div');
    ov.id = 'draco-report-overlay';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(6,8,16,0.95);z-index:99999;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;color:#C8D8F5';
    ov.innerHTML = '<div style=\"background:#0D1222;border:1px solid #1A2440;border-radius:16px;padding:28px;max-width:800px;width:95%;max-height:85vh;overflow-y:auto;box-shadow:0 0 60px rgba(180,79,255,0.08)\">'
      + '<div style=\"display:flex;justify-content:space-between;align-items:center;margin-bottom:16px\">'
      + '<div style=\"font-size:18px;font-weight:900;color:#fff\">\\u25c8 Dataset Analysis Report</div>'
      + '<button id=\"draco-report-close\" style=\"background:none;border:1px solid #2A3B5E;color:#607AAB;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:11px\">&times; Close</button>'
      + '</div>'
      + '<div style=\"display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px\">'
      + '<div><label style=\"font-size:9px;color:#607AAB;text-transform:uppercase;letter-spacing:0.1em\">Target Model</label>'
      + '<select id=\"draco-rpt-model\" style=\"width:100%;background:#090D1A;color:#C8D8F5;border:1px solid #1A2440;border-radius:4px;padding:6px;font-size:11px;margin-top:4px\">'
      + '<option value=\"z_image_turbo\">Z Image Turbo</option><option value=\"z_image_base\">Z Image Base</option>'
      + '<option value=\"flux_dev\">Flux.1 Dev</option><option value=\"flux_klein_9b\">Flux.2 Klein 9B</option>'
      + '<option value=\"qwen_2512\">Qwen Image 2512</option></select></div>'
      + '<div><label style=\"font-size:9px;color:#607AAB;text-transform:uppercase;letter-spacing:0.1em\">LoRA Type</label>'
      + '<select id=\"draco-rpt-type\" style=\"width:100%;background:#090D1A;color:#C8D8F5;border:1px solid #1A2440;border-radius:4px;padding:6px;font-size:11px;margin-top:4px\">'
      + '<option value=\"character\">Character LoRA</option><option value=\"style\">Style LoRA</option></select></div>'
      + '</div>'
      + '<button id=\"draco-rpt-run\" style=\"width:100%;padding:10px;background:rgba(180,79,255,0.2);color:#B44FFF;border:1px solid #B44FFF;border-radius:8px;cursor:pointer;font-size:12px;font-weight:700;margin-bottom:16px;transition:all 0.15s\">Run Full Analysis</button>'
      + '<div id=\"draco-rpt-results\" style=\"font-size:11px\"><div style=\"color:#607AAB;text-align:center;padding:20px\">Load images, then click Run Full Analysis</div></div>'
      + '</div>';
    document.body.appendChild(ov);

    document.getElementById('draco-report-close').onclick = function() { ov.remove(); };
    ov.onclick = function(e) { if (e.target === ov) ov.remove(); };

    document.getElementById('draco-rpt-run').onclick = async function() {
      var btn = this;
      btn.disabled = true; btn.textContent = 'Analyzing...';
      var resultsDiv = document.getElementById('draco-rpt-results');
      resultsDiv.innerHTML = '<div style=\"color:#00DCFF;text-align:center;padding:20px\">\\u25ce Analyzing dataset with InsightFace + DracoFlow v3...</div>';

      try {
        if (typeof images === 'undefined' || !images || images.length === 0) {
          resultsDiv.innerHTML = '<div style=\"color:#FF3E50;padding:20px;text-align:center\">No images loaded. Load images first.</div>';
          btn.disabled = false; btn.textContent = 'Run Full Analysis'; return;
        }

        var model = document.getElementById('draco-rpt-model').value;
        var loraType = document.getElementById('draco-rpt-type').value;

        // Send images for analysis
        var imgB64s = images.slice(0, 100).map(function(img) { return img.url; });
        var result = await window._dracoAnalyzeDataset({
          images: imgB64s,
          target_model: model,
          target_resolution: 1024,
          lora_type: loraType,
        });

        if (!result) { resultsDiv.innerHTML = '<div style=\"color:#FF3E50\">Analysis failed. Is the sidecar running?</div>'; btn.disabled = false; btn.textContent = 'Run Full Analysis'; return; }

        // Render results
        var gradeColor = {A:'#00FF9D',B:'#00DCFF',C:'#FFB830',D:'#FF8A50',F:'#FF3E50'}[result.dataset_grade] || '#607AAB';
        var html = '<div style=\"display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px\">'
          + '<div style=\"background:#090D1A;border:1px solid #1A2440;border-radius:8px;padding:12px;text-align:center\"><div style=\"font-size:9px;color:#607AAB;text-transform:uppercase;margin-bottom:4px\">Grade</div><div style=\"font-size:28px;font-weight:900;color:'+gradeColor+'\">'+result.dataset_grade+'</div></div>'
          + '<div style=\"background:#090D1A;border:1px solid #1A2440;border-radius:8px;padding:12px;text-align:center\"><div style=\"font-size:9px;color:#607AAB;text-transform:uppercase;margin-bottom:4px\">Score</div><div style=\"font-size:28px;font-weight:900;color:#fff\">'+result.dataset_score+'</div></div>'
          + '<div style=\"background:#090D1A;border:1px solid #1A2440;border-radius:8px;padding:12px;text-align:center\"><div style=\"font-size:9px;color:#607AAB;text-transform:uppercase;margin-bottom:4px\">Images</div><div style=\"font-size:28px;font-weight:900;color:#fff\">'+result.image_count+'</div></div>'
          + '<div style=\"background:#090D1A;border:1px solid #1A2440;border-radius:8px;padding:12px;text-align:center\"><div style=\"font-size:9px;color:#607AAB;text-transform:uppercase;margin-bottom:4px\">Ideal Range</div><div style=\"font-size:16px;font-weight:700;color:'+(result.size_recommendation.ok?'#00FF9D':'#FF3E50')+'\">'+result.size_recommendation.min+'-'+result.size_recommendation.max+'</div></div>'
          + '</div>';

        // Shot distribution
        if (result.shot_distribution && Object.keys(result.shot_distribution).length > 0) {
          html += '<div style=\"margin-bottom:12px\"><div style=\"font-size:10px;font-weight:700;color:#B44FFF;text-transform:uppercase;margin-bottom:8px\">Shot Distribution</div>';
          var shots = result.shot_distribution;
          ['close_up','mid_shot','full_body'].forEach(function(st) {
            if (!shots[st]) return;
            var s = shots[st];
            var barColor = s.in_range ? '#00FF9D' : '#FF8A50';
            html += '<div style=\"display:flex;align-items:center;gap:8px;margin-bottom:4px\">'
              + '<div style=\"width:70px;font-size:10px;color:#607AAB\">'+st.replace('_',' ')+'</div>'
              + '<div style=\"flex:1;height:6px;background:#12172A;border-radius:3px;overflow:hidden\"><div style=\"height:100%;width:'+Math.min(100,s.percent)+'%;background:'+barColor+';border-radius:3px\"></div></div>'
              + '<div style=\"width:80px;font-size:10px;color:'+barColor+';text-align:right\">'+s.percent+'% ('+s.ideal_range+')</div></div>';
          });
          html += '</div>';
        }

        // Recommendations
        if (result.recommendations && result.recommendations.length > 0) {
          html += '<div style=\"margin-bottom:12px\"><div style=\"font-size:10px;font-weight:700;color:#FF8A50;text-transform:uppercase;margin-bottom:8px\">Recommendations</div>';
          result.recommendations.forEach(function(r) {
            var sevColor = r.severity === 'high' ? '#FF3E50' : r.severity === 'medium' ? '#FFB830' : '#00DCFF';
            html += '<div style=\"padding:8px 10px;background:#090D1A;border-left:3px solid '+sevColor+';border-radius:0 4px 4px 0;margin-bottom:4px;font-size:10px;color:#C8D8F5\">'+r.message+'</div>';
          });
          html += '</div>';
        }

        // Identity consistency
        if (result.identity_consistency) {
          var ic = result.identity_consistency;
          html += '<div style=\"margin-bottom:12px\"><div style=\"font-size:10px;font-weight:700;color:#00DCFF;text-transform:uppercase;margin-bottom:8px\">Identity Consistency (ArcFace 512-d)</div>'
            + '<div style=\"display:grid;grid-template-columns:repeat(3,1fr);gap:6px\">'
            + '<div style=\"background:#090D1A;padding:8px;border-radius:4px;text-align:center\"><div style=\"font-size:8px;color:#607AAB\">Mean Sim</div><div style=\"font-size:14px;font-weight:700;color:#fff\">'+(ic.mean_similarity*100).toFixed(1)+'%</div></div>'
            + '<div style=\"background:#090D1A;padding:8px;border-radius:4px;text-align:center\"><div style=\"font-size:8px;color:#607AAB\">Min Sim</div><div style=\"font-size:14px;font-weight:700;color:'+(ic.min_similarity<0.3?'#FF3E50':'#fff')+'\">'+(ic.min_similarity*100).toFixed(1)+'%</div></div>'
            + '<div style=\"background:#090D1A;padding:8px;border-radius:4px;text-align:center\"><div style=\"font-size:8px;color:#607AAB\">Outliers</div><div style=\"font-size:14px;font-weight:700;color:'+(ic.outlier_count>0?'#FF3E50':'#00FF9D')+'\">'+ic.outlier_count+'</div></div>'
            + '</div></div>';
        }

        // Caption style hint
        html += '<div style=\"padding:10px;background:rgba(0,220,255,0.06);border:1px solid rgba(0,220,255,0.15);border-radius:6px;font-size:10px;color:#00DCFF\">'
          + '<strong>Captioning tip for '+model.replace(/_/g,' ')+':</strong> '
          + (result.caption_style === 'minimal' ? 'Use MINIMAL captions. Describe pose + clothing + background only. Silence forces the LoRA to learn facial features (gradient zeroing principle).'
             : result.caption_style === 'rich' ? 'Use RICH captions with more detail. This model benefits from detailed descriptions.'
             : 'Use MODERATE captions. Include key visual elements but avoid over-describing facial features.')
          + '</div>';

        resultsDiv.innerHTML = html;
      } catch(e) {
        resultsDiv.innerHTML = '<div style=\"color:#FF3E50\">Error: '+e.message+'</div>';
      }
      btn.disabled = false; btn.textContent = 'Run Full Analysis';
    };
  };

  // ── Menu Event Handlers ────────────────────────────────
  D.on('menu:help', function() { if (typeof showHelpOverlay === 'function') showHelpOverlay(); });
  D.on('menu:setup-wizard', function() {
    document.getElementById('setup-overlay').classList.remove('hidden');
  });

  console.log('[DRACO] Bridge initialization complete');
})();
  `;
  document.body.appendChild(script);
});
