'use strict';
/**
 * api.js — Fetch wrapper for NAVGUARD Flask backend (port 5001).
 *
 * All methods return parsed JSON or throw with a descriptive Error.
 * Side-effects: sets window.sceneState.isRunning and updates #status-* elements.
 */

const API_BASE = 'http://localhost:5001';

window.NavguardAPI = {

  /* ── internal fetch helper ─────────────────────────────────── */
  async _fetch(path, options = {}) {
    const url   = `${API_BASE}${path}`;
    const start = performance.now();

    if (window.sceneState) window.sceneState.isRunning = true;

    try {
      const res  = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });

      const data = await res.json();
      const ms   = Math.round(performance.now() - start);

      console.log(`[NavguardAPI] ${options.method || 'GET'} ${path} → ${res.status} (${ms}ms)`);

      const timingEl = document.getElementById('status-timing');
      if (timingEl) timingEl.textContent = `LAST CALL: ${ms}ms`;

      if (!res.ok || data.success === false) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }

      return data;

    } catch (err) {
      const stepEl = document.getElementById('status-step');
      if (stepEl) {
        stepEl.textContent = `ERR: ${String(err.message).slice(0, 55)}`;
        stepEl.classList.remove('active');
        stepEl.classList.add('error');
      }
      console.error(`[NavguardAPI] ${path} failed:`, err);
      throw err;

    } finally {
      if (window.sceneState) window.sceneState.isRunning = false;
    }
  },

  /* ── public endpoints ──────────────────────────────────────── */

  /** GET /api/config */
  async getConfig() {
    return this._fetch('/api/config');
  },

  /**
   * POST /api/generate
   * @param {Array}  jammers         [{x,y,z,type,power_db}, …]
   * @param {number} droneAltitude   metres (default 100)
   * @param {number} nSnapshots      IQ samples per channel (default 1000)
   */
  async generate(jammers, droneAltitude = 100, nSnapshots = 1000) {
    return this._fetch('/api/generate', {
      method: 'POST',
      body: JSON.stringify({
        jammers,
        drone_altitude: droneAltitude,
        n_snapshots:    nSnapshots,
      }),
    });
  },

  /**
   * POST /api/music
   * @param {string} scenarioId
   * @param {number} nJammers   (default 3)
   */
  async runMusic(scenarioId, nJammers = 3) {
    return this._fetch('/api/music', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId, n_jammers: nJammers }),
    });
  },

  /**
   * POST /api/mvdr
   * @param {string} scenarioId
   * @param {number[]} jammerAngles  azimuth array from MUSIC
   * @param {number}   gpsAz        degrees (default 0)
   * @param {number}   gpsEl        degrees (default 90 = overhead)
   */
  async runMVDR(scenarioId, jammerAngles, gpsAz = 0.0, gpsEl = 90.0) {
    return this._fetch('/api/mvdr', {
      method: 'POST',
      body: JSON.stringify({
        scenario_id:   scenarioId,
        jammer_angles: jammerAngles,
        gps_azimuth:   gpsAz,
        gps_elevation: gpsEl,
      }),
    });
  },

  /**
   * POST /api/hybrid
   * @param {string} scenarioId
   * @param {number} alphaPre      analog cancel fraction 0–1 (default 0.9)
   * @param {number} adcFullscale  clipping level (default 5.0)
   * @param {number} nPoints       sweep resolution (default 50)
   */
  async runHybrid(scenarioId, alphaPre = 0.9, adcFullscale = 5.0, nPoints = 50) {
    return this._fetch('/api/hybrid', {
      method: 'POST',
      body: JSON.stringify({
        scenario_id:   scenarioId,
        alpha_pre:     alphaPre,
        adc_fullscale: adcFullscale,
        n_points:      nPoints,
      }),
    });
  },

  /** POST /api/reset */
  async reset(scenarioId) {
    return this._fetch('/api/reset', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId }),
    });
  },

  /**
   * POST /api/realistic — ideal vs hardware-imperfect comparison.
   * @param {Array}  jammers        [{x,y,z,type,power_db}, …]
   * @param {number} droneAltitude  metres (default 100)
   * @param {object} options        { phaseMismatch, gainImbalance }
   */
  async runRealistic(jammers, droneAltitude = 100, options = {}) {
    const response = await fetch(`${API_BASE}/api/realistic`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jammers,
        drone_altitude: droneAltitude,
        phase_mismatch_std: options.phaseMismatch || 5.0,
        gain_imbalance_std: options.gainImbalance || 0.05,
      }),
    });
    return response.json();
  },

  /* ── pipeline helper ───────────────────────────────────────── */

  /**
   * Run the full 4-step pipeline: generate → music → mvdr → hybrid.
   *
   * @param {Array}  jammers  [{x,y,z,type,power_db}, …]
   * @param {object} options  { droneAltitude, nSnapshots, nJammers, alphaPre, adcFullscale }
   * @returns {object}        { generate, music, mvdr, hybrid, scenario_id }
   */
  async runFullPipeline(jammers, options = {}) {
    const {
      droneAltitude = 100,
      nSnapshots    = 1000,
      nJammers      = jammers.length,
      alphaPre      = 0.9,
      adcFullscale  = 5.0,
    } = options;

    const step = window.setStep || (() => {});
    const setStatusStep = txt => {
      const el = document.getElementById('status-step');
      if (el) { el.textContent = txt; el.classList.add('active'); el.classList.remove('error'); }
    };
    const results = {};

    // 1 — Generate
    step('generate');
    setStatusStep('STEP: GENERATING...');
    results.generate = await this.generate(jammers, droneAltitude, nSnapshots);
    const sid = results.generate.scenario_id;
    if (window.sceneState) window.sceneState.scenario_id = sid;
    const scenEl = document.getElementById('status-scenario');
    if (scenEl) scenEl.textContent = `SCENARIO: ${sid.slice(0, 8)}…`;

    // 2 — MUSIC DOA
    step('music');
    setStatusStep('STEP: MUSIC DOA…');
    results.music = await this.runMusic(sid, nJammers);
    const jamAngles = results.music.detected_angles.map(d => d.azimuth);

    // 3 — MVDR
    step('mvdr');
    setStatusStep('STEP: MVDR…');
    results.mvdr = await this.runMVDR(sid, jamAngles);

    // 4 — Hybrid
    step('hybrid');
    setStatusStep('STEP: HYBRID…');
    results.hybrid = await this.runHybrid(sid, alphaPre, adcFullscale);

    setStatusStep('STEP: COMPLETE');
    console.log('[Pipeline] All steps done:', results);
    return { ...results, scenario_id: sid };
  },
};
