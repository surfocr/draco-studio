'use strict';
const path = require('path');
const fs = require('fs');

let safeStorage;
try {
  safeStorage = require('electron').safeStorage;
} catch {
  safeStorage = null;
}

class DatabaseManager {
  constructor(dbPath) {
    this.dbPath = dbPath;
    this.db = null;
    this._initPromise = this._init();
  }

  async _init() {
    try {
      const initSqlJs = require('sql.js');
      const SQL = await initSqlJs();
      // Load existing db file if it exists
      if (fs.existsSync(this.dbPath)) {
        const buf = fs.readFileSync(this.dbPath);
        this.db = new SQL.Database(buf);
      } else {
        this.db = new SQL.Database();
      }
      this._migrate();
      console.log('[DB] Initialized at', this.dbPath);
    } catch (e) {
      console.error('[DB] Failed to initialize:', e.message);
      this.db = null;
    }
  }

  _migrate() {
    if (!this.db) return;
    this.db.run(`
      CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        preset_id TEXT NOT NULL DEFAULT 'character',
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
      );

      CREATE TABLE IF NOT EXISTS images (
        id TEXT PRIMARY KEY,
        project_id TEXT REFERENCES projects(id),
        file_path TEXT,
        file_hash TEXT,
        original_name TEXT NOT NULL,
        width INTEGER,
        height INTEGER,
        file_size INTEGER,
        category TEXT DEFAULT 'uncategorized',
        detection_json TEXT,
        quality_json TEXT,
        caption TEXT,
        ai_review_json TEXT,
        phash_lo INTEGER,
        phash_hi INTEGER,
        sim_score REAL,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
      );

      CREATE TABLE IF NOT EXISTS face_embeddings (
        image_hash TEXT NOT NULL,
        model TEXT NOT NULL,
        embedding TEXT NOT NULL,
        bbox_json TEXT,
        det_score REAL,
        metadata_json TEXT,
        created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        PRIMARY KEY (image_hash, model)
      );

      CREATE TABLE IF NOT EXISTS api_keys (
        provider TEXT PRIMARY KEY,
        key_encrypted TEXT NOT NULL,
        updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
      );

      CREATE TABLE IF NOT EXISTS api_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        endpoint TEXT,
        task_type TEXT,
        tokens_in INTEGER DEFAULT 0,
        tokens_out INTEGER DEFAULT 0,
        cost_usd REAL DEFAULT 0,
        latency_ms INTEGER,
        timestamp INTEGER NOT NULL DEFAULT (strftime('%s','now'))
      );

      CREATE TABLE IF NOT EXISTS model_status (
        model_id TEXT PRIMARY KEY,
        status TEXT DEFAULT 'not_downloaded',
        path TEXT,
        size_bytes INTEGER,
        downloaded_at INTEGER
      );

      CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );
    `);
    this._save();
  }

  _save() {
    if (!this.db) return;
    try {
      const data = this.db.export();
      const buf = Buffer.from(data);
      fs.writeFileSync(this.dbPath, buf);
    } catch (e) {
      console.error('[DB] Save error:', e.message);
    }
  }

  // ── Generic Query ──────────────────────────────────
  query(sql, params) {
    if (!this.db) return [];
    try {
      const stmt = this.db.prepare(sql);
      if (params) stmt.bind(Array.isArray(params) ? params : [params]);
      const results = [];
      while (stmt.step()) {
        results.push(stmt.getAsObject());
      }
      stmt.free();
      return results;
    } catch (e) {
      console.error('[DB] Query error:', e.message);
      return [];
    }
  }

  run(sql, params) {
    if (!this.db) return null;
    try {
      if (params) {
        this.db.run(sql, Array.isArray(params) ? params : [params]);
      } else {
        this.db.run(sql);
      }
      this._save();
      return { changes: this.db.getRowsModified() };
    } catch (e) {
      console.error('[DB] Run error:', e.message);
      return null;
    }
  }

  // ── API Keys (safeStorage with XOR fallback) ───────
  getApiKeys() {
    if (!this.db) return {};
    const rows = this.query('SELECT provider, key_encrypted FROM api_keys');
    const keys = {};
    for (const row of rows) {
      keys[row.provider] = this._decrypt(row.key_encrypted);
    }
    return keys;
  }

  setApiKey(provider, key) {
    if (!this.db) return;
    if (!key) {
      this.run('DELETE FROM api_keys WHERE provider = ?', [provider]);
    } else {
      this.run(
        "INSERT OR REPLACE INTO api_keys (provider, key_encrypted, updated_at) VALUES (?, ?, strftime('%s','now'))",
        [provider, this._encrypt(key)]
      );
    }
  }

  _encrypt(str) {
    // Use Electron safeStorage (OS credential store) when available
    if (safeStorage && safeStorage.isEncryptionAvailable()) {
      try {
        const encrypted = safeStorage.encryptString(str);
        return 'ss:' + encrypted.toString('base64');
      } catch {}
    }
    // Fallback to XOR obfuscation (better than plaintext)
    return 'xor:' + this._obfuscate(str);
  }

  _decrypt(encoded) {
    if (!encoded) return '';
    // safeStorage-encrypted keys are prefixed with 'ss:'
    if (encoded.startsWith('ss:')) {
      if (safeStorage && safeStorage.isEncryptionAvailable()) {
        try {
          const buf = Buffer.from(encoded.slice(3), 'base64');
          return safeStorage.decryptString(buf);
        } catch {}
      }
      return ''; // Can't decrypt without safeStorage
    }
    // XOR-obfuscated keys are prefixed with 'xor:' or unprefixed (legacy)
    if (encoded.startsWith('xor:')) {
      return this._deobfuscate(encoded.slice(4));
    }
    // Legacy unprefixed format
    return this._deobfuscate(encoded);
  }

  _obfuscate(str) {
    const key = 'DracoStudioV5';
    let result = '';
    for (let i = 0; i < str.length; i++) {
      result += String.fromCharCode(str.charCodeAt(i) ^ key.charCodeAt(i % key.length));
    }
    return Buffer.from(result).toString('base64');
  }

  _deobfuscate(encoded) {
    try {
      const decoded = Buffer.from(encoded, 'base64').toString();
      const key = 'DracoStudioV5';
      let result = '';
      for (let i = 0; i < decoded.length; i++) {
        result += String.fromCharCode(decoded.charCodeAt(i) ^ key.charCodeAt(i % key.length));
      }
      return result;
    } catch { return ''; }
  }

  // ── Face Embedding Cache ──────────────────────────
  getCachedEmbedding(imageHash, model) {
    const rows = this.query(
      'SELECT embedding, bbox_json, det_score, metadata_json FROM face_embeddings WHERE image_hash = ? AND model = ?',
      [imageHash, model]
    );
    if (!rows.length) return null;
    const row = rows[0];
    return {
      embedding: JSON.parse(row.embedding),
      bbox: row.bbox_json ? JSON.parse(row.bbox_json) : null,
      detScore: row.det_score,
      metadata: row.metadata_json ? JSON.parse(row.metadata_json) : null,
    };
  }

  cacheEmbedding(imageHash, model, embedding, bbox, detScore, metadata) {
    this.run(
      'INSERT OR REPLACE INTO face_embeddings (image_hash, model, embedding, bbox_json, det_score, metadata_json) VALUES (?, ?, ?, ?, ?, ?)',
      [imageHash, model, JSON.stringify(embedding), bbox ? JSON.stringify(bbox) : null, detScore, metadata ? JSON.stringify(metadata) : null]
    );
  }

  // ── API Usage Tracking ────────────────────────────
  logApiUsage(provider, endpoint, taskType, tokensIn, tokensOut, costUsd, latencyMs) {
    this.run(
      'INSERT INTO api_usage (provider, endpoint, task_type, tokens_in, tokens_out, cost_usd, latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?)',
      [provider, endpoint, taskType, tokensIn, tokensOut, costUsd, latencyMs]
    );
  }

  getApiUsageSummary() {
    return this.query(`
      SELECT provider,
             COUNT(*) as calls,
             SUM(tokens_in) as total_tokens_in,
             SUM(tokens_out) as total_tokens_out,
             SUM(cost_usd) as total_cost,
             AVG(latency_ms) as avg_latency
      FROM api_usage
      GROUP BY provider
    `);
  }

  // ── Settings ──────────────────────────────────────
  getSetting(key, defaultValue) {
    const rows = this.query('SELECT value FROM settings WHERE key = ?', [key]);
    return rows.length ? JSON.parse(rows[0].value) : defaultValue;
  }

  setSetting(key, value) {
    this.run('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', [key, JSON.stringify(value)]);
  }

  close() {
    if (this.db) {
      this._save();
      this.db.close();
      this.db = null;
    }
  }
}

module.exports = { DatabaseManager };
