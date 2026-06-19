'use strict';
/**
 * hud.js — Section 5: tactical right-panel HUD.
 *
 * Fills the bottom of #hud-panel (replacing the Section-1 placeholder) with a
 * live readout of the full pipeline:
 *   • GPS LOCK / LOST indicator + SINR (derived from the hybrid SINR curve)
 *   • Array status — MVDR null depths, GPS gain, RMS reduction
 *   • Jammer threat table — type / azimuth / distance / power
 *   • SINR-vs-jammer-power chart (HTML5 canvas: ideal / digital / hybrid)
 *   • Pipeline info — detected DoA, eigenvalue (SNR) gap, compute time
 *
 * Backend response conventions this module relies on (verified against the API):
 *   mvdr.null_depths[i] = { angle, jammer_index, null_depth_db }  — null_depth_db
 *     is a POSITIVE magnitude (dB below the GPS peak).
 *   mvdr.rms_reduction_db is provided directly.
 *   music.detected_angles[i] = { azimuth, index, power_db };  music.snr_gap (dB).
 *   hybrid.{jammer_powers_db, sinr_ideal, sinr_digital, sinr_hybrid,
 *           digital_fails_at_db, hybrid_fails_at_db, advantage_db}.
 */

window.HUDAPI = (function () {

  /* ── GPS lock indicator ──────────────────────────────────────── */

  /**
   * Paint the GPS status pill + SINR value.
   * @param {number|null} sinr_db  null/undefined → STANDBY; >0 → LOCK; ≤0 → LOST
   */
  function _updateGPSIndicator(sinr_db) {
    const statusEl = document.getElementById('hud-gps-status');
    const sinrEl   = document.getElementById('hud-sinr-value');
    if (!statusEl) return;

    if (sinr_db === null || sinr_db === undefined || !isFinite(sinr_db)) {
      // STANDBY — no pipeline run yet
      statusEl.style.background  = '#050f05';
      statusEl.style.borderColor = '#1a3a1a';
      statusEl.style.color       = '#2a5a2a';
      statusEl.innerHTML         = '&#9646;&#9646; STANDBY';
      statusEl.classList.remove('gps-lost', 'gps-lock');
      if (sinrEl) { sinrEl.textContent = 'SINR: --'; sinrEl.style.color = '#2a5a2a'; }
      return;
    }

    if (sinr_db > 0) {
      // GPS LOCK — green
      statusEl.style.background  = '#003300';
      statusEl.style.borderColor = '#00ff88';
      statusEl.style.color       = '#00ff88';
      statusEl.innerHTML         = '&#9646;&#9646; GPS LOCK';
      statusEl.classList.remove('gps-lost');
      statusEl.classList.add('gps-lock');
    } else {
      // GPS LOST — red flashing
      statusEl.style.background  = '#330000';
      statusEl.style.borderColor = '#ff3300';
      statusEl.style.color       = '#ff3300';
      statusEl.innerHTML         = '&#9646;&#9646; GPS LOST';
      statusEl.classList.remove('gps-lock');
      statusEl.classList.add('gps-lost');
    }

    if (sinrEl) {
      sinrEl.textContent = `SINR: ${sinr_db > 0 ? '+' : ''}${sinr_db.toFixed(1)}dB`;
      sinrEl.style.color = sinr_db > 0 ? '#00ff88' : '#ff3300';
    }
  }

  /**
   * Derive a meaningful GPS-lock SINR. mvdr.gps_gain_db is ~0 by design, so we
   * read the hybrid SINR at the current max jammer power instead.
   */
  function updateGPSStatus(mvdrResult, hybridResult, currentJammerPowerDb) {
    let sinr_db = null;

    if (hybridResult && currentJammerPowerDb !== undefined &&
        currentJammerPowerDb !== null && isFinite(currentJammerPowerDb)) {
      const powers = hybridResult.jammer_powers_db;
      const idx = powers.findIndex(p => p >= currentJammerPowerDb);
      // idx < 0 → jammer power exceeds the swept range; use the deepest (last) point.
      sinr_db = idx >= 0
        ? hybridResult.sinr_hybrid[idx]
        : hybridResult.sinr_hybrid[hybridResult.sinr_hybrid.length - 1];
    } else if (mvdrResult) {
      sinr_db = mvdrResult.gps_gain_db || 0;
    }

    _updateGPSIndicator(sinr_db);
  }

  /* ── array status (MVDR) ─────────────────────────────────────── */

  /** Colour a null by its depth magnitude (positive dB below GPS). */
  function getNullColor(depth_db) {
    if (depth_db > 50) return '#00ff88';   // excellent
    if (depth_db > 40) return '#ffcc00';   // good — above the 40 dB target
    if (depth_db > 30) return '#ff8800';   // marginal
    return '#ff3300';                      // poor — below target
  }

  function updateArrayStatus(mvdrResult) {
    const nullsEl = document.getElementById('hud-null-depths');
    if (mvdrResult.null_depths && nullsEl) {
      nullsEl.innerHTML = mvdrResult.null_depths.map((n, i) => {
        const jn = (n.jammer_index !== undefined ? n.jammer_index : i) + 1;
        // null_depth_db is a positive magnitude → show as "-58dB" (below GPS).
        return `<span class="null-item" style="color:${getNullColor(n.null_depth_db)}">` +
               `J${jn} -${Math.round(n.null_depth_db)}dB</span>`;
      }).join('  ');
    }

    const gpsGainEl = document.getElementById('hud-gps-gain');
    if (gpsGainEl) gpsGainEl.textContent = `GPS gain: ${mvdrResult.gps_gain_db.toFixed(2)} dB`;

    const rmsEl = document.getElementById('hud-rms-reduction');
    if (rmsEl) {
      let reduction = mvdrResult.rms_reduction_db;
      if (reduction === undefined && mvdrResult.rms_before && mvdrResult.rms_after) {
        reduction = 20 * Math.log10(mvdrResult.rms_before / mvdrResult.rms_after);
      }
      rmsEl.textContent = `RMS reduction: ${reduction !== undefined ? reduction.toFixed(1) : '--'} dB`;
    }
  }

  /* ── jammer threat table ─────────────────────────────────────── */

  function updateJammerThreats(jammers, geometries) {
    const tableEl = document.getElementById('hud-jammer-table');
    if (!tableEl) return;

    if (!jammers || jammers.length === 0) {
      tableEl.innerHTML = '<div class="hud-empty">NO JAMMERS PLACED</div>';
      return;
    }

    tableEl.innerHTML = jammers.map((j, i) => {
      const geo       = geometries && geometries[i] ? geometries[i] : {};
      const typeShort = { CW: 'CW  ', FMCW: 'FMCW', Barrage: 'BAR ' }[j.type] || j.type;
      const az = geo.azimuth !== undefined
        ? `${geo.azimuth.toFixed(1)}°`
        : `${(j.azimuth !== null && j.azimuth !== undefined) ? j.azimuth.toFixed(1) : '--'}°`;
      const dist = geo.distance !== undefined ? `${Math.round(geo.distance)}m` : '--';
      const threatLevel = j.power_db > 40 ? '#ff3300' : j.power_db > 25 ? '#ff8800' : '#ffcc00';

      return `<div class="jammer-threat-row" style="border-left:3px solid ${threatLevel}">
        <span class="jt-index" style="color:${threatLevel}">J${i + 1}</span>
        <span class="jt-type">${typeShort}</span>
        <span class="jt-az">AZ:${az}</span>
        <span class="jt-dist">${dist}</span>
        <span class="jt-power" style="color:${threatLevel}">${j.power_db}dB</span>
      </div>`;
    }).join('');
  }

  /* ── SINR chart (canvas) ─────────────────────────────────────── */

  function drawSINRChart(hybridResult) {
    const canvas = document.getElementById('hud-sinr-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const W = canvas.width;
    const H = canvas.height;

    // Background
    ctx.fillStyle = '#050f05';
    ctx.fillRect(0, 0, W, H);

    const yZero  = H * 0.35;   // 0 dB line at 35% from top
    const yScale = H / 60;     // ~60 dB vertical range

    // 0 dB gridline
    ctx.strokeStyle = '#0a2a0a';
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.moveTo(0, yZero); ctx.lineTo(W, yZero);
    ctx.stroke();

    // Axis labels
    ctx.fillStyle = '#1a4a1a';
    ctx.font      = '9px Courier New';
    ctx.fillText('0dB', 2, yZero - 2);
    ctx.fillText('0', 30, H - 2);
    ctx.fillText('25', W / 2 - 6, H - 2);
    ctx.fillText('50dB', W - 30, H - 2);

    const powers = hybridResult.jammer_powers_db;
    const n      = powers.length;
    const xPos   = i    => 30 + (i / (n - 1)) * (W - 40);
    const yPos   = sinr => yZero - sinr * yScale;

    const drawLine = (series, color, width, dash) => {
      if (!series) return;
      ctx.setLineDash(dash || []);
      ctx.strokeStyle = color;
      ctx.lineWidth   = width;
      ctx.beginPath();
      series.forEach((s, i) => {
        const x = xPos(i), y = yPos(s);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.stroke();
    };

    drawLine(hybridResult.sinr_ideal,   '#00aa44', 1,   [4, 4]);  // ideal — green dashed
    drawLine(hybridResult.sinr_digital, '#ff3300', 1.5, []);      // digital — red
    drawLine(hybridResult.sinr_hybrid,  '#00ccff', 2,   []);      // hybrid — cyan

    // Failure-point vertical markers (powers span 0..50 over n points)
    const step = 50 / (n - 1);
    const dFailX = xPos(Math.round(hybridResult.digital_fails_at_db / step));
    const hFailX = xPos(Math.round(hybridResult.hybrid_fails_at_db / step));

    ctx.lineWidth = 1;
    ctx.setLineDash([2, 2]);
    ctx.strokeStyle = '#ff3300';
    ctx.beginPath(); ctx.moveTo(dFailX, 0); ctx.lineTo(dFailX, H); ctx.stroke();
    ctx.strokeStyle = '#00ccff';
    ctx.beginPath(); ctx.moveTo(hFailX, 0); ctx.lineTo(hFailX, H); ctx.stroke();
    ctx.setLineDash([]);

    // Legend
    ctx.font = '9px Courier New';
    ctx.fillStyle = '#00aa44'; ctx.fillText('— Ideal',   W - 60, 12);
    ctx.fillStyle = '#ff3300'; ctx.fillText('— Digital', W - 60, 24);
    ctx.fillStyle = '#00ccff'; ctx.fillText('— Hybrid',  W - 60, 36);

    // Stats line (DOM, not canvas)
    const statsEl = document.getElementById('hud-sinr-stats');
    if (statsEl) {
      statsEl.innerHTML =
        `<span style="color:#ff3300">Digital fails: ${Math.round(hybridResult.digital_fails_at_db)}dB</span>` +
        `<span style="color:#00ccff">Hybrid fails: ${Math.round(hybridResult.hybrid_fails_at_db)}dB</span>` +
        `<span style="color:#00ff88">Advantage: +${hybridResult.advantage_db.toFixed(1)}dB</span>`;
    }
  }

  /* ── pipeline info (MUSIC) ───────────────────────────────────── */

  function updatePipelineInfo(musicResult, computeTimeMs) {
    const doaEl  = document.getElementById('hud-doa-accuracy');
    const gapEl  = document.getElementById('hud-eigen-gap');
    const timeEl = document.getElementById('hud-compute-time');

    if (musicResult && doaEl) {
      const angles = musicResult.detected_angles || [];
      doaEl.textContent = `DoA: ${angles.map(a => a.azimuth.toFixed(1) + '°').join('  ')}`;
    }
    if (musicResult && gapEl) {
      gapEl.textContent = `Eigenvalue gap: ${musicResult.snr_gap !== undefined ? musicResult.snr_gap.toFixed(0) : '--'}×`;
    }
    if (timeEl) {
      timeEl.textContent = `Pipeline time: ${computeTimeMs}ms`;
    }
  }

  /* ── HUD markup ──────────────────────────────────────────────── */

  function _buildHUDHTML() {
    return `
<div id="hud-section5" style="border-top:1px solid #1a3a1a; margin-top:8px; padding-top:8px;">

  <!-- GPS Status -->
  <div id="hud-gps-row" style="display:flex;justify-content:space-between;align-items:center;
    padding:8px 10px;border:1px solid #1a3a1a;margin-bottom:8px;background:#050f05;">
    <div id="hud-gps-status" style="font-size:14px;font-weight:bold;font-family:'Courier New';
      padding:4px 12px;border:1px solid #1a3a1a;letter-spacing:2px;">
      &#9646;&#9646; STANDBY
    </div>
    <div id="hud-sinr-value" style="font-family:'Courier New';font-size:12px;color:#2a5a2a;">
      SINR: --
    </div>
  </div>

  <!-- Array Status -->
  <div class="hud-panel-block">
    <div class="hud-block-title">ARRAY STATUS</div>
    <div id="hud-null-depths" class="hud-data-row">NULLS: --</div>
    <div id="hud-gps-gain" class="hud-data-row">GPS gain: --</div>
    <div id="hud-rms-reduction" class="hud-data-row">RMS reduction: --</div>
  </div>

  <!-- Jammer Threats -->
  <div class="hud-panel-block">
    <div class="hud-block-title">JAMMER THREATS</div>
    <div id="hud-jammer-table">
      <div class="hud-empty">NO JAMMERS PLACED</div>
    </div>
  </div>

  <!-- SINR Chart -->
  <div class="hud-panel-block">
    <div class="hud-block-title">SINR vs JAMMER POWER</div>
    <canvas id="hud-sinr-chart" width="300" height="150"
      style="width:100%;background:#050f05;display:block;margin:4px 0;"></canvas>
    <div id="hud-sinr-stats" style="display:flex;justify-content:space-between;
      font-size:10px;font-family:'Courier New';padding:2px 0;"></div>
  </div>

  <!-- Pipeline Info -->
  <div class="hud-panel-block">
    <div class="hud-block-title">PIPELINE</div>
    <div id="hud-doa-accuracy" class="hud-data-row">DoA: --</div>
    <div id="hud-eigen-gap" class="hud-data-row">Eigenvalue gap: --</div>
    <div id="hud-compute-time" class="hud-data-row">Pipeline time: --</div>
  </div>

</div>
    `;
  }

  /* ── public API ──────────────────────────────────────────────── */

  return {

    /** Inject the HUD section, removing the Section-1 placeholder (id-independent). */
    init() {
      // Remove any existing section5 to avoid duplicates (safe re-init / console call)
      const existing = document.getElementById('hud-section5');
      if (existing) existing.remove();

      // Find the hud-panel
      const hudPanel = document.getElementById('hud-panel');
      if (!hudPanel) {
        console.error('HUDAPI: hud-panel not found');
        return;
      }

      // Remove the placeholder text element entirely — match by text, not id,
      // so a stale cached index.html (no id) can't leave the placeholder behind.
      Array.from(hudPanel.querySelectorAll('*')).forEach(el => {
        if (el.textContent.trim().includes('Section 5 will fill this')) {
          el.remove();
        }
      });

      // Append the HUD HTML
      const wrapper = document.createElement('div');
      wrapper.innerHTML = _buildHUDHTML();
      hudPanel.appendChild(wrapper.firstElementChild);

      // Paint the standby state. (This panel has no interactive controls, so there
      // are no event listeners to attach — reset() is what init needs here.)
      this.reset();

      console.log('HUDAPI Section 5 initialized successfully');
    },

    /**
     * Update every readout after a full pipeline run.
     * @param {object} data {generate, music, mvdr, hybrid, jammers, computeTimeMs}
     */
    update(data) {
      const jammers = data.jammers || [];
      const maxJammerPower = jammers.length
        ? Math.max(...jammers.map(j => j.power_db))
        : undefined;

      updateGPSStatus(data.mvdr || null, data.hybrid || null, maxJammerPower);
      if (data.mvdr) updateArrayStatus(data.mvdr);
      updateJammerThreats(jammers, data.generate ? data.generate.jammer_geometries : []);
      if (data.hybrid) drawSINRChart(data.hybrid);
      if (data.music)  updatePipelineInfo(data.music, data.computeTimeMs || 0);
    },

    /** Refresh just the threat table when jammers change (pre-pipeline). */
    updateJammers(jammers) {
      updateJammerThreats(jammers, []);
    },

    /** Reset all readouts to standby. */
    reset() {
      _updateGPSIndicator(null);

      const set = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
      set('hud-null-depths',   'NULLS: --');
      set('hud-gps-gain',      'GPS gain: --');
      set('hud-rms-reduction', 'RMS reduction: --');
      set('hud-doa-accuracy',  'DoA: --');
      set('hud-eigen-gap',     'Eigenvalue gap: --');
      set('hud-compute-time',  'Pipeline time: --');

      const table = document.getElementById('hud-jammer-table');
      if (table) table.innerHTML = '<div class="hud-empty">NO JAMMERS PLACED</div>';

      const stats = document.getElementById('hud-sinr-stats');
      if (stats) stats.innerHTML = '';

      const canvas = document.getElementById('hud-sinr-chart');
      if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#050f05';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      }
    },

    /** Kept for backward-compat with the old stub signature; no-op. */
    setStep(_step) {},
  };

})();
