'use strict';
/**
 * jammers.js — Section 3: interactive jammer placement, control, signal animation.
 *
 * Fixes applied:
 *   Fix 1 — ghost labels: label.element.remove() on jammer removal
 *   Fix 2 — numbering: _renumber() already correct; ghost fix eliminates visual confusion
 *
 * Enhancements:
 *   Enh 1 — type-specific physics params and label text (CW freq, FMCW sweep BW, Barrage BW)
 *   Enh 2 — drone altitude slider + per-jammer altitude slider with elevated stake/ray/elevLine
 *   Enh 3 — traveling signal dots (1/2/3 per type) animated along jammer→drone path
 *   Enh 4 — effective range rings (TorusGeometry) with km label
 */

window.JammersAPI = (function () {

  /* ── constants ───────────────────────────────────────────────── */
  const DRONE_POS  = new THREE.Vector3(0, 100, 0);  // kept in sync with sceneState
  const MAX_JAM    = 3;
  const JAM_Y      = 8;   // mesh height above ground for ground-level jammers

  const TYPE_CFG = {
    CW:      { hex: 0xff3300, css: '#ff3300', cls: 'cw'      },
    FMCW:    { hex: 0xff8800, css: '#ff8800', cls: 'fmcw'    },
    Barrage: { hex: 0xffcc00, css: '#ffcc00', cls: 'barrage' },
  };

  // Base range radius (scene units) and km equivalent at 30 dB
  const BASE_RANGE_UNITS = { CW: 300, FMCW: 200, Barrage: 120 };
  const BASE_RANGE_KM    = { CW: 50,  FMCW: 33,  Barrage: 20  };

  /* ── module state ─────────────────────────────────────────────── */
  let _scene, _camera, _renderer;
  let _raycaster   = null;
  let _groundPlane = null;
  let _debounce    = null;
  let _elapsed     = 0;
  let _clickStart  = { x: 0, y: 0 };
  let _hudBox      = null;

  // Direct reference to sceneState.jammers array (shared with other modules)
  const _jammers = window.sceneState.jammers;

  /* ── helpers ─────────────────────────────────────────────────── */

  function _jamY(jammer) {
    return JAM_Y + (jammer.altitude || 0);
  }

  function _droneAlt() {
    return window.sceneState.drone.altitude || 100;
  }

  function _labelText(j) {
    const n   = j.index + 1;
    const p   = j.power_db;
    const alt = j.altitude > 0 ? ` ${j.altitude}m` : '';
    let base;
    if (j.type === 'CW') {
      const off = j.freq_offset_mhz >= 0
        ? `+${j.freq_offset_mhz}` : `${j.freq_offset_mhz}`;
      base = `J${n} CW${alt} ${off}MHz ${p}dB`;
    } else if (j.type === 'FMCW') {
      base = `J${n} FMCW${alt} ±${j.sweep_bw_mhz}MHz ${p}dB`;
    } else {
      base = `J${n} Barrage${alt} ±${Math.round(j.bandwidth_mhz / 2)}MHz ${p}dB`;
    }
    if (j.onTerrain) base += ' [HLD]';        // placed on highland terrain
    if (j.inGpsCone) base += ' ⚠ GPS CONE';  // elevation inside GPS look cone
    return base;
  }

  /* ── 3D object factories ─────────────────────────────────────── */

  function _makeGeom(type) {
    if (type === 'CW')   return new THREE.OctahedronGeometry(12);
    if (type === 'FMCW') return new THREE.ConeGeometry(10, 25, 8);
    return new THREE.IcosahedronGeometry(12, 0);
  }

  function _makeMat(type) {
    return new THREE.MeshBasicMaterial({
      color:     TYPE_CFG[type].hex,
      wireframe: type === 'Barrage',
    });
  }

  function _makeStake(tx, tz, topY) {
    const pts = [new THREE.Vector3(tx, 0, tz), new THREE.Vector3(tx, topY, tz)];
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    return new THREE.Line(geo,
      new THREE.LineBasicMaterial({ color: 0x444444, opacity: 0.5, transparent: true }));
  }

  function _makeGroundRing(tx, tz, colorHex) {
    const mat  = new THREE.MeshBasicMaterial({
      color: colorHex, side: THREE.DoubleSide, opacity: 0.35, transparent: true,
    });
    const ring = new THREE.Mesh(new THREE.RingGeometry(18, 22, 32), mat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(tx, 0.5, tz);
    return ring;
  }

  function _makeRangeRing(tx, tz, type, power_db) {
    const base   = BASE_RANGE_UNITS[type] || 200;
    const radius = Math.max(40, base * Math.pow(10, (power_db - 30) / 20));
    const color  = TYPE_CFG[type].hex;
    const mat    = new THREE.MeshBasicMaterial({ color, opacity: 0.18, transparent: true });
    const torus  = new THREE.Mesh(new THREE.TorusGeometry(radius, 3, 8, 64), mat);
    torus.rotation.x = -Math.PI / 2;
    torus.position.set(tx, 0.8, tz);

    // Range label — added to scene in world space (not as child of torus)
    const kmBase = BASE_RANGE_KM[type] || 33;
    const km     = Math.round(kmBase * Math.pow(10, (power_db - 30) / 20));
    const div    = document.createElement('div');
    div.className       = 'scene-label range-ring-label';
    div.style.color     = TYPE_CFG[type].css;
    div.style.fontSize  = '10px';
    div.style.opacity   = '0.7';
    div.textContent     = `~${km}km effective`;
    const lbl = new THREE.CSS2DObject(div);
    lbl.position.set(tx + radius * 0.72, 1, tz + radius * 0.72);
    torus._rangeLabel = lbl;  // store ref for cleanup

    return torus;
  }

  function _makeLabel(jammer) {
    const cfg = TYPE_CFG[jammer.type];
    const div = document.createElement('div');
    div.className         = 'scene-label jammer';
    div.style.color       = cfg.css;
    div.style.borderColor = cfg.css;
    div.textContent       = _labelText(jammer);
    const obj = new THREE.CSS2DObject(div);
    obj.position.set(0, 20, 0);
    return obj;
  }

  /* ── signal ray factories ─────────────────────────────────────── */

  function _makeCWRays(jammer) {
    const pts = [
      new THREE.Vector3(jammer.threeX, jammer.threeY, jammer.threeZ),
      new THREE.Vector3(0, _droneAlt(), 0),
    ];
    console.log('CW RAY BUILD — jammer:', jammer.threeX, jammer.threeZ,
      'jammer Y (start):', jammer.threeY,
      'drone Y used (endpoint):', pts[1].y,
      'sceneState altitude:', window.sceneState.drone.altitude,
      'DRONE_POS.y:', typeof DRONE_POS !== 'undefined' ? DRONE_POS.y : 'NOT FOUND');
    const geo  = new THREE.BufferGeometry().setFromPoints(pts);
    const mat  = new THREE.LineDashedMaterial({
      color: 0xff3300, dashSize: 10, gapSize: 5, opacity: 0.8, transparent: true,
    });
    const line = new THREE.Line(geo, mat);
    line.computeLineDistances();
    return [line];
  }

  function _makeFMCWRays() {
    const rays = [];
    for (let i = 0; i < 3; i++) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
      rays.push(new THREE.Line(geo, new THREE.LineDashedMaterial({
        color: 0xff8800, dashSize: 12, gapSize: 3, opacity: 0.7, transparent: true,
      })));
    }
    return rays;
  }

  function _makeBarrageRays() {
    const rays = [];
    for (let i = 0; i < 6; i++) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
      rays.push(new THREE.Line(geo, new THREE.LineDashedMaterial({
        color: 0xffcc00, dashSize: 5, gapSize: 8, opacity: 0.5, transparent: true,
      })));
    }
    return rays;
  }

  function _makeRays(jammer) {
    if (jammer.type === 'CW')   return _makeCWRays(jammer);
    if (jammer.type === 'FMCW') return _makeFMCWRays();
    return _makeBarrageRays();
  }

  /* ── traveling dots ───────────────────────────────────────────── */

  function _makeDots(jammer) {
    const counts = { CW: 1, FMCW: 2, Barrage: 3 };
    const count  = counts[jammer.type] || 1;
    const color  = TYPE_CFG[jammer.type].hex;
    const dots   = [];
    for (let i = 0; i < count; i++) {
      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(2, 6, 6),
        new THREE.MeshBasicMaterial({ color })
      );
      _scene.add(mesh);
      dots.push({ mesh, phase: i / count });
    }
    return dots;
  }

  function _destroyDots(jammer) {
    (jammer.dots || []).forEach(d => {
      _scene.remove(d.mesh);
      d.mesh.geometry.dispose();
      d.mesh.material.dispose();
    });
    jammer.dots = [];
  }

  /* ── ray animation (every frame) ─────────────────────────────── */

  function _animCW(jammer, t) {
    // Fast pulse 0.4 → 1.0
    jammer.rays[0].material.opacity = 0.4 + (Math.sin(t * 8) * 0.5 + 0.5) * 0.6;
  }

  function _animFMCW(jammer, t) {
    const jamPos = new THREE.Vector3(jammer.threeX, jammer.threeY, jammer.threeZ);
    const drnPos = new THREE.Vector3(0, _droneAlt(), 0);
    const dir    = new THREE.Vector3().subVectors(drnPos, jamPos).normalize();
    const rayLen = jamPos.distanceTo(drnPos) * 1.05;

    // Sweep axis perpendicular to the jammer→drone vector in the horizontal plane
    const up       = new THREE.Vector3(0, 1, 0);
    const sweepAxis = new THREE.Vector3().crossVectors(dir, up);
    if (sweepAxis.lengthSq() < 0.0001) sweepAxis.set(1, 0, 0);
    sweepAxis.normalize();

    const sweepDeg = Math.sin(t * 3) * 20;   // ±20° animated sweep
    const baseOffs = [-5, 0, 5];             // ±5° static spread

    jammer.rays.forEach((ray, i) => {
      const anglRad = (sweepDeg + baseOffs[i]) * Math.PI / 180;
      const quat    = new THREE.Quaternion().setFromAxisAngle(sweepAxis, anglRad);
      const endPos  = jamPos.clone().addScaledVector(dir.clone().applyQuaternion(quat), rayLen);

      const pos = ray.geometry.attributes.position;
      pos.setXYZ(0, jamPos.x, jamPos.y, jamPos.z);
      pos.setXYZ(1, endPos.x, endPos.y, endPos.z);
      pos.needsUpdate = true;
      ray.computeLineDistances();
    });
  }

  function _animBarrage(jammer, t) {
    const jamPos = new THREE.Vector3(jammer.threeX, jammer.threeY, jammer.threeZ);
    const drnPos = new THREE.Vector3(0, _droneAlt(), 0);
    const dir    = new THREE.Vector3().subVectors(drnPos, jamPos).normalize();
    const rayLen = jamPos.distanceTo(drnPos) * 1.05;

    // Stable basis perpendicular to the jammer→drone direction. The spray fans
    // *within a cone around dir* so every ray still aims toward the drone instead
    // of swinging horizontal.
    const up = new THREE.Vector3(0, 1, 0);
    let perp1 = new THREE.Vector3().crossVectors(dir, up);
    if (perp1.lengthSq() < 1e-4) perp1.set(1, 0, 0);
    perp1.normalize();
    const perp2 = new THREE.Vector3().crossVectors(dir, perp1).normalize();

    jammer.rays.forEach((ray, i) => {
      // Axis sweeps around dir (in the perp plane) → cone direction varies per ray
      const phi  = t * (2 + i * 0.7) + i * 1.3;
      const axis = perp1.clone().multiplyScalar(Math.cos(phi))
                        .addScaledVector(perp2, Math.sin(phi));   // unit, ⊥ to dir
      // Cone half-angle 15°–35°: tilt is always off dir, never flat/backward
      const angle = (15 + 20 * Math.abs(Math.sin(t * (4 + i * 0.9) + i))) * Math.PI / 180;
      const quat   = new THREE.Quaternion().setFromAxisAngle(axis, angle);
      const endPos = jamPos.clone().addScaledVector(dir.clone().applyQuaternion(quat), rayLen);

      const pos = ray.geometry.attributes.position;
      pos.setXYZ(0, jamPos.x, jamPos.y, jamPos.z);
      pos.setXYZ(1, endPos.x, endPos.y, endPos.z);
      pos.needsUpdate = true;
      ray.material.opacity = 0.12 + Math.abs(Math.sin(t * 3.1 + i * 0.9)) * 0.28;
      ray.computeLineDistances();
    });
  }

  function _animRays(jammer, t) {
    if (jammer.type === 'CW')   return _animCW(jammer, t);
    if (jammer.type === 'FMCW') return _animFMCW(jammer, t);
    return _animBarrage(jammer, t);
  }

  function _animDots(jammer, t) {
    const period = 0.5;
    const start  = new THREE.Vector3(jammer.threeX, jammer.threeY, jammer.threeZ);
    const end    = new THREE.Vector3(0, _droneAlt(), 0);
    jammer.dots.forEach(dot => {
      const progress = ((t % period) / period + dot.phase) % 1;
      dot.mesh.position.lerpVectors(start, end, progress);
    });
  }

  /* ── HUD box ─────────────────────────────────────────────────── */

  function _ensureHudBox() {
    if (_hudBox) return;
    _hudBox = document.createElement('div');
    _hudBox.id = 'jammer-hud';

    // Drone altitude control
    const altCtrl = document.createElement('div');
    altCtrl.className = 'drone-altitude-ctrl';
    altCtrl.innerHTML = `
<div class="drone-alt-label">DRONE ALTITUDE</div>
<div style="display:flex;align-items:center;gap:6px;margin:4px 0">
  <span class="drone-alt-bound">50m</span>
  <input type="range" id="drone-alt-slider" class="drone-alt-slider" min="50" max="500" value="100">
  <span class="drone-alt-bound">500m</span>
</div>
<div id="drone-alt-val" class="drone-alt-val">100m</div>`;
    _hudBox.appendChild(altCtrl);

    // RUN PIPELINE button
    const btn = document.createElement('button');
    btn.id          = 'run-pipeline-btn';
    btn.textContent = 'RUN PIPELINE';
    btn.style.cssText = [
      'width:100%', 'padding:8px 0', 'margin-bottom:10px',
      'background:#001a00', 'border:1px solid #00ff88',
      'color:#00ff88', 'font-family:\'Courier New\',monospace',
      'font-size:12px', 'letter-spacing:3px', 'cursor:pointer',
    ].join(';');
    btn.addEventListener('click', _runPipeline);
    _hudBox.appendChild(btn);

    document.getElementById('hud-panel').insertBefore(_hudBox, document.getElementById('hud-panel').firstChild);

    document.getElementById('drone-alt-slider').addEventListener('input', function () {
      const alt = parseInt(this.value, 10);
      document.getElementById('drone-alt-val').textContent = `${alt}m`;
      _setDroneAltitude(alt);
    });
  }

  function _setDroneAltitude(alt) {
    DRONE_POS.y = alt;
    window.sceneState.drone.altitude = alt;
    if (window.SceneAPI && window.SceneAPI.setDroneAltitude) {
      window.SceneAPI.setDroneAltitude(alt);
    }
    // Rebuild CW static rays whose endpoint is baked at construction time
    _jammers.forEach(j => {
      if (j.type === 'CW') {
        _destroyRays(j);
        j.rays = _makeRays(j);
        j.rays.forEach(r => _scene.add(r));
      }
    });
    _debounceSync();
  }

  async function _runPipeline() {
    if (_jammers.length === 0) { _setStatus('PLACE JAMMERS FIRST'); return; }
    const t0 = performance.now();
    try {
      const results       = await NavguardAPI.runFullPipeline(_getPayload());
      const computeTimeMs  = Math.round(performance.now() - t0);
      if (window.RadiationAPI) await RadiationAPI.computeBeampattern(results.mvdr);
      if (window.HUDAPI) {
        HUDAPI.update({
          generate:      results.generate,
          music:         results.music,
          mvdr:          results.mvdr,
          hybrid:        results.hybrid,
          jammers:       _getPayload(),
          computeTimeMs,
        });
      }
      SceneAPI.clearHighlights();
      results.music.detected_angles.forEach(a => SceneAPI.highlightAngle(a.azimuth));
      SceneAPI.updateAntennaElements(results);
    } catch (e) {
      _setStatus(`ERR: ${String(e.message).slice(0, 40)}`);
      if (window.HUDAPI) HUDAPI.reset();
    }
  }

  /* ── jammer panel ─────────────────────────────────────────────── */

  function _createPanel(jammer) {
    _ensureHudBox();
    const el = document.createElement('div');
    el.className = `jammer-panel ${TYPE_CFG[jammer.type].cls}`;
    el.id        = `jammer-panel-${jammer.index}`;
    el.innerHTML = _panelHTML(jammer);
    _hudBox.appendChild(el);
    jammer.panelElement = el;
    _bindPanel(jammer);
  }

  function _physicsRowHTML(j) {
    if (j.type === 'CW') {
      return `<div class="physics-row">FREQ: <span class="phys-val">GPS L1 +${j.freq_offset_mhz}MHz</span></div>`;
    }
    if (j.type === 'FMCW') {
      return `<div class="physics-row">SWEEP: <span class="phys-val">±${j.sweep_bw_mhz}MHz &nbsp; ${j.sweep_rate}kHz/ms</span></div>`;
    }
    return `<div class="physics-row">BW: <span class="phys-val">±${Math.round(j.bandwidth_mhz / 2)}MHz broadband</span></div>`;
  }

  function _panelHTML(j) {
    const sel = t => j.type === t ? ' selected' : '';
    return `
<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px">
  <strong>JAMMER ${j.index + 1}</strong>
  <button class="jammer-remove-btn" title="Remove">&#x00d7;</button>
</div>
<div style="margin-bottom:5px">
  TYPE:
  <button class="jammer-type-btn${sel('CW')}" data-type="CW">CW</button>
  <button class="jammer-type-btn${sel('FMCW')}" data-type="FMCW">FMCW</button>
  <button class="jammer-type-btn${sel('Barrage')}" data-type="Barrage">BARRAGE</button>
</div>
<div style="margin-bottom:3px">
  POWER: <input type="range" class="jammer-power-slider" min="10" max="50" value="${j.power_db}">
  <span class="jam-power-val">${j.power_db}dB</span>
</div>
<div class="jammer-altitude-row">
  ALTITUDE: <input type="range" class="jammer-alt-slider" min="0" max="400" step="10" value="${j.altitude}">
  <span class="jam-alt-val">${j.altitude}m</span>
</div>
${_physicsRowHTML(j)}
<div class="jammer-info">
  X:<span class="jam-px">${Math.round(j.worldX)}</span>
  Y:<span class="jam-py">${Math.round(j.worldY)}</span>
  &nbsp;|&nbsp;AZ:<span class="jam-az">${j.azimuth !== null ? j.azimuth.toFixed(1) : '--'}</span>&deg;
  &nbsp;|&nbsp;DIST:<span class="jam-dist">${j.distance !== null ? Math.round(j.distance) : '--'}</span>m
</div>`;
  }

  function _bindPanel(jammer) {
    const el = jammer.panelElement;

    el.querySelector('.jammer-remove-btn').addEventListener('click', () => {
      _removeByIndex(jammer.index);
    });

    el.querySelectorAll('.jammer-type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.type === jammer.type) return;
        _setType(jammer, btn.dataset.type);
        _debounceSync();
      });
    });

    el.querySelector('.jammer-power-slider').addEventListener('input', function () {
      jammer.power_db = parseInt(this.value, 10);
      el.querySelector('.jam-power-val').textContent = `${jammer.power_db}dB`;
      _refreshLabel(jammer);
      _updateRangeRing(jammer);
      _debounceSync();
    });

    el.querySelector('.jammer-alt-slider').addEventListener('input', function () {
      _setJammerAltitude(jammer, parseInt(this.value, 10));
      el.querySelector('.jam-alt-val').textContent = `${jammer.altitude}m`;
    });
  }

  function _setJammerAltitude(jammer, alt) {
    jammer.altitude = alt;
    const newY = JAM_Y + alt;
    jammer.threeY = newY;   // keep altitude-aware Y in sync for ray/dot animations

    // Move mesh
    jammer.mesh.position.y = newY;

    // Rebuild stake
    _scene.remove(jammer.stakeLine);
    jammer.stakeLine.geometry.dispose();
    jammer.stakeLine = _makeStake(jammer.threeX, jammer.threeZ, newY);
    _scene.add(jammer.stakeLine);

    // Dashed elevation marker (visible only when alt > 50m)
    if (jammer.elevLine) {
      _scene.remove(jammer.elevLine);
      jammer.elevLine.geometry.dispose();
      jammer.elevLine.material.dispose();
      jammer.elevLine = null;
    }
    if (alt > 50) {
      const pts    = [new THREE.Vector3(jammer.threeX, 0, jammer.threeZ),
                      new THREE.Vector3(jammer.threeX, alt, jammer.threeZ)];
      const elevMat = new THREE.LineDashedMaterial({
        color:       TYPE_CFG[jammer.type].hex,
        dashSize:    8, gapSize: 5,
        opacity:     0.5, transparent: true,
      });
      jammer.elevLine = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts), elevMat);
      jammer.elevLine.computeLineDistances();
      _scene.add(jammer.elevLine);
    }

    // Rebuild CW static ray (start point changed)
    if (jammer.type === 'CW') {
      _destroyRays(jammer);
      jammer.rays = _makeRays(jammer);
      jammer.rays.forEach(r => _scene.add(r));
    }

    _refreshLabel(jammer);
    _debounceSync();
  }

  /* ── type switching ───────────────────────────────────────────── */

  function _setType(jammer, newType) {
    const cfg  = TYPE_CFG[newType];
    jammer.type = newType;
    if (newType === 'CW')      { jammer.freq_offset_mhz = 0; }
    if (newType === 'FMCW')    { jammer.sweep_bw_mhz = 10; jammer.sweep_rate = 50; }
    if (newType === 'Barrage') { jammer.bandwidth_mhz = 100; }

    // Swap geometry + material
    jammer.mesh.geometry.dispose();
    jammer.mesh.material.dispose();
    jammer.mesh.geometry = _makeGeom(newType);
    jammer.mesh.material = _makeMat(newType);

    // Ground ring colour
    jammer.groundRing.material.color.setHex(cfg.hex);

    // Rays + dots
    _destroyRays(jammer);
    jammer.rays = _makeRays(jammer);
    jammer.rays.forEach(r => _scene.add(r));

    _destroyDots(jammer);
    jammer.dots = _makeDots(jammer);

    // Range ring
    _updateRangeRing(jammer);

    // Elevation line colour
    if (jammer.elevLine) jammer.elevLine.material.color.setHex(cfg.hex);

    // Label + panel
    _refreshLabel(jammer);
    const el = jammer.panelElement;
    el.className = `jammer-panel ${cfg.cls}`;
    el.querySelectorAll('.jammer-type-btn').forEach(b => {
      b.classList.toggle('selected', b.dataset.type === newType);
    });
    const physRow = el.querySelector('.physics-row');
    if (physRow) physRow.outerHTML = _physicsRowHTML(jammer);
  }

  function _refreshLabel(jammer) {
    const cfg = TYPE_CFG[jammer.type];
    const div = jammer.label.element;
    div.textContent       = _labelText(jammer);
    div.style.color       = cfg.css;
    div.style.borderColor = cfg.css;
  }

  function _updateRangeRing(jammer) {
    if (jammer.rangeRing) {
      if (jammer.rangeRing._rangeLabel) {
        jammer.rangeRing._rangeLabel.element.remove();
        _scene.remove(jammer.rangeRing._rangeLabel);
      }
      _scene.remove(jammer.rangeRing);
      jammer.rangeRing.geometry.dispose();
      jammer.rangeRing.material.dispose();
    }
    jammer.rangeRing = _makeRangeRing(jammer.threeX, jammer.threeZ, jammer.type, jammer.power_db);
    _scene.add(jammer.rangeRing);
    if (jammer.rangeRing._rangeLabel) _scene.add(jammer.rangeRing._rangeLabel);
  }

  function _destroyRays(jammer) {
    jammer.rays.forEach(r => {
      _scene.remove(r);
      r.geometry.dispose();
      r.material.dispose();
    });
    jammer.rays = [];
  }

  /* ── placement ────────────────────────────────────────────────── */

  function _place(threeX, threeZ, type, power, opts) {
    if (_jammers.length >= MAX_JAM) {
      _setStatus(`MAX ${MAX_JAM} JAMMERS`);
      return;
    }

    opts = opts || {};
    const onTerrain = !!opts.onTerrain;
    const altitude  = opts.altitude != null ? opts.altitude : 0;
    // On terrain: sit the marker at the exact surface height. Else float JAM_Y above ground.
    const placedY   = (onTerrain && opts.threeY != null) ? opts.threeY : JAM_Y + altitude;

    const cfg    = TYPE_CFG[type];
    const idx    = _jammers.length;   // before push — gives correct 0-based index
    const worldX = threeX;
    const worldY = -threeZ;

    // Build jammer state before calling factories (they read jammer.altitude etc.)
    const jammer = {
      index: idx, type, power_db: power,
      altitude,
      onTerrain,
      worldX, worldY,
      threeX, threeZ, threeY: placedY,   // altitude-aware Three.js Y
      mesh: null, rays: [], dots: [], rangeRing: null,
      label: null, stakeLine: null, groundRing: null, elevLine: null,
      panelElement: null,
      azimuth: null, distance: null,
      // Physics defaults
      freq_offset_mhz: 0,
      sweep_bw_mhz: 10,
      sweep_rate: 50,
      bandwidth_mhz: 100,
    };

    jammer.mesh       = new THREE.Mesh(_makeGeom(type), _makeMat(type));
    jammer.mesh.position.set(threeX, placedY, threeZ);
    jammer.label      = _makeLabel(jammer);
    jammer.mesh.add(jammer.label);   // label is child → removed with mesh from scene graph

    jammer.stakeLine  = _makeStake(threeX, threeZ, placedY);
    jammer.groundRing = _makeGroundRing(threeX, threeZ, cfg.hex);
    jammer.rays       = _makeRays(jammer);
    jammer.dots       = _makeDots(jammer);
    jammer.rangeRing  = _makeRangeRing(threeX, threeZ, type, power);

    _scene.add(jammer.mesh);
    _scene.add(jammer.stakeLine);
    _scene.add(jammer.groundRing);
    jammer.rays.forEach(r => _scene.add(r));
    _scene.add(jammer.rangeRing);
    if (jammer.rangeRing._rangeLabel) _scene.add(jammer.rangeRing._rangeLabel);

    _jammers.push(jammer);
    _createPanel(jammer);
    if (window.HUDAPI && HUDAPI.updateJammers) HUDAPI.updateJammers(_getPayload());
    _debounceSync();
  }

  function _removeByIndex(targetIdx) {
    const pos = _jammers.findIndex(j => j.index === targetIdx);
    if (pos === -1) return;
    const j = _jammers[pos];

    // Fix 1: explicitly remove CSS2D label DOM element — prevents ghost label
    if (j.label && j.label.element) j.label.element.remove();

    _scene.remove(j.mesh);
    _scene.remove(j.stakeLine);
    _scene.remove(j.groundRing);
    _destroyRays(j);
    _destroyDots(j);

    if (j.rangeRing) {
      if (j.rangeRing._rangeLabel) {
        j.rangeRing._rangeLabel.element.remove();
        _scene.remove(j.rangeRing._rangeLabel);
      }
      _scene.remove(j.rangeRing);
      j.rangeRing.geometry.dispose();
      j.rangeRing.material.dispose();
    }
    if (j.elevLine) {
      _scene.remove(j.elevLine);
      j.elevLine.geometry.dispose();
      j.elevLine.material.dispose();
    }

    j.mesh.geometry.dispose();
    j.mesh.material.dispose();
    j.stakeLine.geometry.dispose();

    if (j.panelElement && j.panelElement.parentNode) {
      j.panelElement.parentNode.removeChild(j.panelElement);
    }

    _jammers.splice(pos, 1);
    _renumber();
    if (window.HUDAPI) {
      if (_jammers.length === 0 && HUDAPI.reset) HUDAPI.reset();
      else if (HUDAPI.updateJammers)             HUDAPI.updateJammers(_getPayload());
    }
    _debounceSync();
  }

  function _renumber() {
    _jammers.forEach((j, i) => {
      j.index = i;
      _refreshLabel(j);
      if (j.panelElement) {
        j.panelElement.id = `jammer-panel-${i}`;
        const hdr = j.panelElement.querySelector('strong');
        if (hdr) hdr.textContent = `JAMMER ${i + 1}`;
      }
    });
  }

  /* ── raycasting ──────────────────────────────────────────────── */

  function _ndcFromEvent(e) {
    const rect = _renderer.domElement.getBoundingClientRect();
    return new THREE.Vector2(
       ((e.clientX - rect.left) / rect.width)  * 2 - 1,
      -((e.clientY - rect.top)  / rect.height) * 2 + 1
    );
  }

  function _onPointerDown(e) { _clickStart = { x: e.clientX, y: e.clientY }; }

  // Raycast a click to a ground point. Prefers the highland terrain mesh (returning
  // its surface height) and falls back to the flat ground plane at y=0.
  function _getClickPosition(e) {
    _raycaster.setFromCamera(_ndcFromEvent(e), _camera);

    if (window._terrainMesh) {
      const terrainHits = _raycaster.intersectObject(window._terrainMesh, false);
      if (terrainHits.length > 0) {
        const hit = terrainHits[0].point;
        return { x: hit.x, y: hit.y, z: hit.z, onTerrain: true };
      }
    }
    const target = new THREE.Vector3();
    if (_raycaster.ray.intersectPlane(_groundPlane, target)) {
      return { x: target.x, y: 0, z: target.z, onTerrain: false };
    }
    return null;
  }

  function _onClick(e) {
    if (e.button !== 0) return;
    const dx = e.clientX - _clickStart.x;
    const dy = e.clientY - _clickStart.y;
    if (dx * dx + dy * dy > 25) return;   // ignore drag

    const clickPos = _getClickPosition(e);
    if (!clickPos) return;

    const opts = {};
    if (clickPos.onTerrain && clickPos.y > 5) {
      // Placed on highland terrain — auto-set altitude from the surface height.
      opts.altitude  = Math.round(clickPos.y);
      opts.threeY    = clickPos.y;
      opts.onTerrain = true;
    }
    _place(clickPos.x, clickPos.z, 'CW', 30, opts);
  }

  /* ── backend sync ─────────────────────────────────────────────── */

  function _setStatus(msg) {
    const el = document.getElementById('status-step');
    if (el) { el.textContent = msg; el.classList.remove('error'); }
  }

  function _debounceSync() {
    clearTimeout(_debounce);
    _debounce = setTimeout(syncWithBackend, 300);
  }

  function _getPayload() {
    return _jammers.map(j => ({
      x: j.worldX, y: j.worldY, z: j.altitude || 0,
      type: j.type, power_db: j.power_db,
    }));
  }

  async function syncWithBackend() {
    if (_jammers.length === 0) return;
    const droneAlt = _droneAlt();
    try {
      const result = await NavguardAPI.generate(_getPayload(), droneAlt);
      window.sceneState.scenario_id = result.scenario_id;

      let coneWarn = false;
      result.jammer_geometries.forEach((geo, i) => {
        const jammer = _jammers[i];
        if (!jammer) return;
        jammer.azimuth  = geo.azimuth;
        jammer.distance = geo.distance;

        // Fix 6 — GPS cone: |elevation| > 55° puts the jammer near the GPS look
        // direction, where null steering competes with the GPS main lobe.
        jammer.inGpsCone = (geo.elevation !== undefined && geo.elevation !== null)
          && Math.abs(geo.elevation) > 55;
        if (jammer.inGpsCone) coneWarn = true;

        _refreshLabel(jammer);   // _labelText now appends ⚠ GPS CONE when inGpsCone

        if (jammer.inGpsCone) {
          if (jammer.mesh && jammer.mesh.material) {
            jammer.mesh.material.color.setHex(0x9900ff);   // purple warning
          }
          if (jammer.label && jammer.label.element) {
            jammer.label.element.style.color       = '#9900ff';
            jammer.label.element.style.borderColor = '#9900ff';
          }
        } else if (jammer.mesh && jammer.mesh.material) {
          jammer.mesh.material.color.setHex(TYPE_CFG[jammer.type].hex);   // restore type colour
        }

        const p = jammer.panelElement;
        if (p) {
          const azEl   = p.querySelector('.jam-az');
          const distEl = p.querySelector('.jam-dist');
          if (azEl)   azEl.textContent   = geo.azimuth.toFixed(1);
          if (distEl) distEl.textContent = Math.round(geo.distance);
        }
      });

      if (window.setStep) window.setStep('generate');
      const scenEl = document.getElementById('status-scenario');
      if (scenEl) scenEl.textContent = `SCENARIO: ${result.scenario_id.slice(0, 8)}…`;
      // Cone warning takes priority in the status bar so it isn't clobbered.
      if (coneWarn) {
        _setStatus('WARNING: jammer in GPS cone — null steering limited');
      } else {
        _setStatus(`GENERATED: ${result.jammer_geometries.length} jammers`);
      }

    } catch (e) {
      _setStatus(`GEN ERR: ${String(e.message).slice(0, 38)}`);
    }
  }

  /* ── public API ──────────────────────────────────────────────── */

  return {

    init() {
      _scene    = SceneAPI.getScene();
      _camera   = SceneAPI.getCamera();
      _renderer = SceneAPI.getRenderer();

      _raycaster   = new THREE.Raycaster();
      _groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

      const canvas = _renderer.domElement;
      canvas.addEventListener('pointerdown', _onPointerDown);
      canvas.addEventListener('click',       _onClick);
    },

    addJammer(config) {
      _place(config.x || 0, -(config.y || 0), config.type || 'CW', config.power_db || 30);
    },

    removeJammer(index) { _removeByIndex(index); },

    clearAll() {
      for (let i = _jammers.length - 1; i >= 0; i--) {
        _removeByIndex(_jammers[i].index);
      }
    },

    getJammers() { return _getPayload(); },

    update(dt) {
      _elapsed += dt;
      _jammers.forEach(j => {
        _animRays(j, _elapsed);
        _animDots(j, _elapsed);
      });
    },

    syncWithBackend,
  };

})();
