'use strict';
const path = require('path');
const fs = require('fs');
const https = require('https');
const http = require('http');

// ─── Model Registry ────────────────────────────────────
const MODEL_REGISTRY = {
  insightface: {
    id: 'insightface',
    name: 'InsightFace buffalo_l',
    description: 'Face detection + ArcFace 512-d embeddings (99.83% LFW accuracy)',
    size: '~330MB',
    sizeBytes: 346_000_000,
    purpose: 'face_detection, face_similarity',
    installType: 'pip', // Downloaded automatically when insightface is imported
    priority: 1,
  },
  clip: {
    id: 'clip',
    name: 'CLIP ViT-L/14',
    description: 'Image embeddings for semantic clustering and similarity',
    size: '~890MB',
    sizeBytes: 933_000_000,
    purpose: 'clustering, similarity',
    installType: 'huggingface',
    hfRepo: 'openai/clip-vit-large-patch14',
    priority: 2,
  },
  aesthetic: {
    id: 'aesthetic',
    name: 'Aesthetic Predictor v2',
    description: 'LAION aesthetic scoring for image quality assessment',
    size: '~45MB',
    sizeBytes: 47_000_000,
    purpose: 'quality_scoring',
    installType: 'huggingface',
    hfRepo: 'shunk031/aesthetics-predictor-v2-sac-logos-ava1-l14-linearMSE',
    priority: 3,
  },
  florence2: {
    id: 'florence2',
    name: 'Florence-2-base',
    description: 'Local image captioning — no API key required',
    size: '~460MB',
    sizeBytes: 482_000_000,
    purpose: 'captioning',
    installType: 'huggingface',
    hfRepo: 'microsoft/Florence-2-base',
    priority: 4,
  },
  topiq: {
    id: 'topiq',
    name: 'TOPIQ (NeurIPS 2024)',
    description: 'State-of-the-art no-reference image quality assessment',
    size: '~120MB',
    sizeBytes: 126_000_000,
    purpose: 'quality_scoring',
    installType: 'pip', // Auto-downloaded by pyiqa on first use
    priority: 5,
  },
  rembg: {
    id: 'rembg',
    name: 'BRIA RMBG-2.0',
    description: 'Best-in-class background removal for portrait extraction',
    size: '~180MB',
    sizeBytes: 189_000_000,
    purpose: 'background_removal',
    installType: 'pip', // Auto-downloaded by rembg on first use
    priority: 6,
  },
};

class ModelManager {
  constructor(modelsDir, pythonManager, emitEvent) {
    this.modelsDir = modelsDir;
    this.python = pythonManager;
    this.emit = emitEvent || (() => {});
    this.statusCache = {};
    this._loadStatus();
  }

  _statusFile() { return path.join(this.modelsDir, 'model-status.json'); }

  _loadStatus() {
    try {
      if (fs.existsSync(this._statusFile())) {
        this.statusCache = JSON.parse(fs.readFileSync(this._statusFile(), 'utf8'));
      }
    } catch { this.statusCache = {}; }
  }

  _saveStatus() {
    try { fs.writeFileSync(this._statusFile(), JSON.stringify(this.statusCache, null, 2)); }
    catch {}
  }

  getAllStatus() {
    const result = {};
    for (const [id, def] of Object.entries(MODEL_REGISTRY)) {
      result[id] = {
        ...def,
        status: this.statusCache[id]?.status || 'not_downloaded',
        downloadedAt: this.statusCache[id]?.downloadedAt || null,
        error: this.statusCache[id]?.error || null,
      };
    }
    return result;
  }

  async downloadModel(modelId) {
    const def = MODEL_REGISTRY[modelId];
    if (!def) throw new Error(`Unknown model: ${modelId}`);

    this.statusCache[modelId] = { status: 'downloading', startedAt: Date.now() };
    this._saveStatus();
    this.emit('model:downloading', { modelId, name: def.name });

    try {
      if (def.installType === 'pip') {
        // InsightFace downloads its models on first import
        await this.python.callEndpoint('/models/ensure', { model: modelId });
      } else if (def.installType === 'huggingface') {
        // Use Python to download from HuggingFace
        await this.python.callEndpoint('/models/download', {
          model: modelId,
          repo: def.hfRepo,
          target_dir: path.join(this.modelsDir, modelId),
        });
      }

      this.statusCache[modelId] = { status: 'ready', downloadedAt: Date.now() };
      this._saveStatus();
      this.emit('model:ready', { modelId, name: def.name });
      return true;
    } catch (e) {
      this.statusCache[modelId] = { status: 'error', error: e.message };
      this._saveStatus();
      this.emit('model:error', { modelId, name: def.name, error: e.message });
      throw e;
    }
  }

  async downloadAll() {
    const models = Object.keys(MODEL_REGISTRY).sort(
      (a, b) => MODEL_REGISTRY[a].priority - MODEL_REGISTRY[b].priority
    );
    const results = {};
    for (const modelId of models) {
      try {
        await this.downloadModel(modelId);
        results[modelId] = 'ready';
      } catch (e) {
        results[modelId] = `error: ${e.message}`;
      }
    }
    return results;
  }

  isReady(modelId) {
    return this.statusCache[modelId]?.status === 'ready';
  }
}

module.exports = { ModelManager, MODEL_REGISTRY };
