'use strict';

// ─── Rate Limits (requests per minute) ──────────────────
const RATE_LIMITS = {
  gemini_api: 1500,
  claude_api: 40,
  openai_api: 60,
  openrouter_api: 200,
  groq_api: 30,
  wavespeed_api: 60,
  fal_api: 60,
  ollama_local: 999, // No real limit, but serialize GPU
  florence2_local: 999,
  insightface_local: 999,
  clip_local: 999,
};

// ─── Concurrency Limits ─────────────────────────────────
const CONCURRENCY = {
  _default_api: 3,
  _default_local: 1, // Serialize GPU tasks
  ollama_local: 1,
  florence2_local: 1,
  insightface_local: 2,
};

class BatchQueue {
  constructor(orchestrator, db, emitEvent) {
    this.orchestrator = orchestrator;
    this.db = db;
    this.emit = emitEvent || (() => {});
    this.jobs = [];
    this.active = new Map(); // jobId -> Promise
    this.paused = false;
    this.cancelled = false;
    this.results = {};
    this.stats = { completed: 0, failed: 0, total: 0, costSoFar: 0 };
    this._rateBuckets = {}; // provider -> { tokens, lastRefill }
  }

  // ─── Submit Jobs ──────────────────────────────────────
  submit(jobs) {
    this.cancelled = false;
    this.paused = false;
    this.stats = { completed: 0, failed: 0, total: jobs.length, costSoFar: 0 };

    this.jobs = jobs.map((job, i) => ({
      id: `job_${Date.now()}_${i}`,
      ...job,
      status: 'pending',
      retries: 0,
      maxRetries: 3,
      result: null,
      error: null,
    }));

    this.emit('queue:started', { total: jobs.length });
    this._processLoop();
    return this.jobs.map(j => j.id);
  }

  pause() {
    this.paused = true;
    this.emit('queue:paused', this._getPublicStatus());
  }

  resume() {
    this.paused = false;
    this.emit('queue:resumed', this._getPublicStatus());
    this._processLoop();
  }

  cancel() {
    this.cancelled = true;
    this.jobs.forEach(j => { if (j.status === 'pending') j.status = 'cancelled'; });
    this.emit('queue:cancelled', this._getPublicStatus());
  }

  getStatus() { return this._getPublicStatus(); }

  // ─── Processing Loop ──────────────────────────────────
  async _processLoop() {
    if (this.paused || this.cancelled) return;

    while (true) {
      if (this.paused || this.cancelled) break;

      const pending = this.jobs.filter(j => j.status === 'pending');
      if (pending.length === 0 && this.active.size === 0) {
        this.emit('queue:completed', this._getPublicStatus());
        break;
      }

      // Find next job that can run (respecting concurrency and rate limits)
      const nextJob = pending.find(j => this._canRun(j));
      if (!nextJob) {
        // Wait for an active job to complete or rate limit to refill
        await new Promise(r => setTimeout(r, 200));
        continue;
      }

      nextJob.status = 'processing';
      this.emit('queue:job-started', { jobId: nextJob.id, index: this.jobs.indexOf(nextJob) });

      const promise = this._executeJob(nextJob).then(() => {
        this.active.delete(nextJob.id);
      });
      this.active.set(nextJob.id, promise);
    }
  }

  async _executeJob(job) {
    try {
      const { provider, result, latency, cost } = await this.orchestrator.route({
        type: job.type,
        image: job.image,
        options: job.options,
      });

      job.status = 'completed';
      job.result = result;
      job.provider = provider;
      this.stats.completed++;
      this.stats.costSoFar += cost || 0;

      this.emit('queue:job-completed', {
        jobId: job.id,
        provider,
        latency,
        cost,
        result,
        progress: this._progress(),
      });
    } catch (e) {
      job.retries++;
      if (job.retries < job.maxRetries) {
        job.status = 'pending'; // Retry
        const backoff = Math.min(30000, 1000 * Math.pow(2, job.retries));
        this.emit('queue:job-retry', { jobId: job.id, retry: job.retries, backoffMs: backoff });
        await new Promise(r => setTimeout(r, backoff));
      } else {
        job.status = 'failed';
        job.error = e.message;
        this.stats.failed++;
        this.emit('queue:job-failed', { jobId: job.id, error: e.message, progress: this._progress() });
      }
    }
  }

  // ─── Concurrency & Rate Limiting ──────────────────────
  _canRun(job) {
    // Determine likely provider
    const chain = this.orchestrator.chains[job.type] || [];
    const provider = chain[0] || '_default';
    const isLocal = provider.endsWith('_local') || provider.endsWith('_browser');
    const maxConcurrency = CONCURRENCY[provider] || (isLocal ? CONCURRENCY._default_local : CONCURRENCY._default_api);

    // Count active jobs of same provider type
    const activeOfType = Array.from(this.active.keys()).filter(id => {
      const j = this.jobs.find(x => x.id === id);
      return j && j.type === job.type;
    }).length;

    if (activeOfType >= maxConcurrency) return false;

    // Rate limiting for API providers
    if (!isLocal) {
      return this._consumeRateToken(provider);
    }

    return true;
  }

  _consumeRateToken(provider) {
    const limit = RATE_LIMITS[provider] || 60;
    const now = Date.now();

    if (!this._rateBuckets[provider]) {
      this._rateBuckets[provider] = { tokens: limit, lastRefill: now };
    }

    const bucket = this._rateBuckets[provider];
    const elapsed = (now - bucket.lastRefill) / 60000; // minutes
    bucket.tokens = Math.min(limit, bucket.tokens + elapsed * limit);
    bucket.lastRefill = now;

    if (bucket.tokens >= 1) {
      bucket.tokens--;
      return true;
    }
    return false;
  }

  // ─── Status ───────────────────────────────────────────
  _progress() {
    return {
      completed: this.stats.completed,
      failed: this.stats.failed,
      pending: this.jobs.filter(j => j.status === 'pending').length,
      processing: this.active.size,
      total: this.stats.total,
      percent: Math.round(((this.stats.completed + this.stats.failed) / this.stats.total) * 100),
      costSoFar: this.stats.costSoFar,
    };
  }

  _getPublicStatus() {
    return {
      ...this._progress(),
      paused: this.paused,
      cancelled: this.cancelled,
      jobs: this.jobs.map(j => ({
        id: j.id, type: j.type, status: j.status,
        provider: j.provider, error: j.error, retries: j.retries,
      })),
    };
  }
}

module.exports = { BatchQueue };
