'use strict';

// ─── Default Fallback Chains ────────────────────────────
const DEFAULT_CHAINS = {
  face_detect:    ['insightface_local', 'blazeface_browser'],
  face_embed:     ['arcface_local', 'faceapi_browser', 'fingerprint_browser'],
  caption:        ['florence2_local', 'ollama_local', 'gemini_api', 'claude_api', 'openai_api', 'openrouter_api', 'groq_api'],
  aesthetic:      ['aesthetic_local', 'dracoflow_browser'],
  clustering:     ['clip_local', 'phash_browser'],
  deep_review:    ['ollama_local', 'gemini_api', 'claude_api', 'openai_api', 'openrouter_api', 'groq_api'],
  moderation:     ['local_classifier', 'openai_api'],
};

// ─── Cost Estimates (USD per image) ─────────────────────
const COST_PER_IMAGE = {
  gemini_api: 0.00013,
  claude_api: 0.003,
  openai_api: 0.005,
  openrouter_api: 0.0005,
  groq_api: 0.0001,
  wavespeed_api: 0.001,
  fal_api: 0.002,
  // Local = $0
  insightface_local: 0, arcface_local: 0, florence2_local: 0,
  aesthetic_local: 0, clip_local: 0, ollama_local: 0,
  blazeface_browser: 0, faceapi_browser: 0, fingerprint_browser: 0,
  dracoflow_browser: 0, phash_browser: 0,
};

class Orchestrator {
  constructor(pythonManager, db) {
    this.python = pythonManager;
    this.db = db;
    this.chains = { ...DEFAULT_CHAINS };
    this.latencyLog = {}; // provider -> [latencyMs, ...]
    this._loadConfig();
  }

  _loadConfig() {
    if (!this.db) return;
    const saved = this.db.getSetting('orchestrator_chains', null);
    if (saved) this.chains = saved;
  }

  getConfig() {
    return {
      chains: this.chains,
      costs: COST_PER_IMAGE,
      latency: this._getAverageLatencies(),
    };
  }

  setConfig(config) {
    if (config.chains) {
      this.chains = config.chains;
      this.db?.setSetting('orchestrator_chains', this.chains);
    }
  }

  // ─── Route a Task ────────────────────────────────────
  async route(task) {
    const { type, image, options } = task;
    const chain = this.chains[type] || [];

    for (const provider of chain) {
      if (!this._isAvailable(provider)) continue;

      const start = Date.now();
      try {
        const result = await this._execute(provider, type, image, options);
        const latency = Date.now() - start;
        this._recordLatency(provider, latency);
        this._recordCost(provider, type);
        return { provider, result, latency, cost: COST_PER_IMAGE[provider] || 0 };
      } catch (e) {
        console.warn(`[Orchestrator] ${provider} failed for ${type}:`, e.message);
        continue; // Fall through to next provider
      }
    }

    throw new Error(`No available provider for task: ${type}`);
  }

  // ─── Estimate Batch Cost ─────────────────────────────
  estimateBatchCost(taskType, imageCount) {
    const chain = this.chains[taskType] || [];
    for (const provider of chain) {
      if (this._isAvailable(provider)) {
        return {
          provider,
          costPerImage: COST_PER_IMAGE[provider] || 0,
          totalCost: (COST_PER_IMAGE[provider] || 0) * imageCount,
          isLocal: provider.endsWith('_local') || provider.endsWith('_browser'),
        };
      }
    }
    return { provider: null, costPerImage: 0, totalCost: 0, isLocal: true };
  }

  // ─── Provider Availability ───────────────────────────
  _isAvailable(provider) {
    // Browser providers are always available (handled by renderer)
    if (provider.endsWith('_browser')) return true;

    // Local Python providers need sidecar running
    if (provider.endsWith('_local')) {
      if (provider === 'ollama_local') return true; // Checked by renderer
      return this.python?.running || false;
    }

    // API providers need keys
    if (provider.endsWith('_api')) {
      const providerName = provider.replace('_api', '');
      const keys = this.db?.getApiKeys() || {};
      return !!(keys[providerName] && keys[providerName].length > 10);
    }

    return false;
  }

  // ─── Execute on Provider ─────────────────────────────
  async _execute(provider, taskType, image, options) {
    // Local Python sidecar
    if (provider.endsWith('_local') && provider !== 'ollama_local') {
      const endpoint = this._getEndpoint(provider, taskType);
      return this.python.callEndpoint(endpoint, { image, ...options });
    }

    // Browser and API providers return a descriptor for the renderer to execute
    // (The actual call happens in the renderer process)
    return { _executeInRenderer: true, provider, taskType, image, options };
  }

  _getEndpoint(provider, taskType) {
    const map = {
      'insightface_local:face_detect': '/detect-faces',
      'arcface_local:face_embed': '/batch-faces',
      'florence2_local:caption': '/caption',
      'aesthetic_local:aesthetic': '/aesthetic-score',
      'clip_local:clustering': '/clip-embed',
    };
    return map[`${provider}:${taskType}`] || `/${taskType}`;
  }

  // ─── Telemetry ───────────────────────────────────────
  _recordLatency(provider, ms) {
    if (!this.latencyLog[provider]) this.latencyLog[provider] = [];
    this.latencyLog[provider].push(ms);
    // Keep last 100
    if (this.latencyLog[provider].length > 100) this.latencyLog[provider].shift();
  }

  _recordCost(provider, taskType) {
    const cost = COST_PER_IMAGE[provider] || 0;
    if (cost > 0) {
      this.db?.logApiUsage(
        provider.replace('_api', ''), null, taskType, 0, 0, cost, 0
      );
    }
  }

  _getAverageLatencies() {
    const avg = {};
    for (const [provider, times] of Object.entries(this.latencyLog)) {
      avg[provider] = Math.round(times.reduce((a, b) => a + b, 0) / times.length);
    }
    return avg;
  }
}

module.exports = { Orchestrator, DEFAULT_CHAINS, COST_PER_IMAGE };
