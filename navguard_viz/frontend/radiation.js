'use strict';
/**
 * radiation.js — Section 4.1: MVDR beampattern computation engine.
 *
 * This module computes the full 3-D beampattern  B(θ,φ) = |wᴴ·a(θ,φ)|²  over the
 * upper hemisphere from the MVDR weights returned by POST /api/mvdr.  No Three.js
 * mesh is created here — Section 4.2 consumes the structured data this produces.
 *
 * IMPORTANT — steering-vector convention:
 *   The backend (core.py steering_vector) defines, for element position r=[x,y,0]:
 *       φ = (2π/λ) · r·û   with û = [cos(el)cos(az), cos(el)sin(az), sin(el)]
 *   i.e. the in-plane projection scales with cos(el) (NOT sin(el)), and the
 *   element order is ELEM_POS = (0,0),(d,0),(0,d),(d,d).
 *
 *   The beampattern |wᴴ a|² is only valid if `a` is expressed in the SAME basis
 *   that produced `w`.  Therefore steeringVector() below mirrors the backend
 *   exactly: cos(el) and the (0,0),(1,0),(0,1),(1,1) element order.  This is what
 *   makes GPS (az=0, el=90) the distortionless max (0 dB) and puts the nulls at
 *   the correct jammer azimuths.
 */

window.RadiationAPI = (function () {

  /* ── physical constants ──────────────────────────────────────── */
  const FREQ   = 1575.42e6;      // GPS L1, Hz
  const C      = 3e8;           // speed of light, m/s
  const LAMBDA = C / FREQ;      // ≈ 0.19029 m
  const D      = LAMBDA / 2;    // ≈ 0.09517 m — half-wavelength URA spacing
  const K_D    = 2 * Math.PI * D / LAMBDA;   // = π for half-wavelength spacing

  /* ── scan resolution ─────────────────────────────────────────── */
  const AZ_STEPS = 180;   // 0 … 358° in 2° steps
  const EL_STEPS = 45;    // 0 … 88° in 2° steps  (upper hemisphere only; 180×45 = 8100 pts)
  const AZ_RES   = 2;
  const EL_RES   = 2;
  const MIN_DB   = -80;   // dB floor for nulls
  const BASE_RADIUS = 80; // scene units — radius of the GPS-lobe peak

  /* ── module state ────────────────────────────────────────────── */
  let _beampatternData = null;
  let _mvdrWeights     = null;
  let _jammerAngles    = [];
  let _gpsGain         = null;
  let _gpsGainDb       = 0.0;
  let _nullDepths      = [];
  let _isComputed      = false;

  /* ── 4.2 mesh state ──────────────────────────────────────────── */
  let _beampatternMesh = null;
  let _nullMarkers     = [];
  let _gpsMarker       = null;
  let _patternLight    = null;   // point light near drone for rainbow visibility
  let _isVisible       = true;
  let _isRotating      = false;  // ROTATE control removed — beampattern is static

  /* ── math primitives ─────────────────────────────────────────── */

  /**
   * 2×2 URA steering vector — matches backend core.py steering_vector exactly.
   * @returns {Array<{re,im}>} 4 complex elements in ELEM_POS order
   *          (0,0),(d,0),(0,d),(d,d)
   */
  function steeringVector(az_deg, el_deg) {
    const az = az_deg * Math.PI / 180;
    const el = el_deg * Math.PI / 180;
    // Backend uses cos(el) for the in-plane projection (NOT sin(el)).
    const phase_x = K_D * Math.cos(el) * Math.cos(az);   // contribution of an x=d element
    const phase_y = K_D * Math.cos(el) * Math.sin(az);   // contribution of a  y=d element

    // ELEM_POS order: (0,0),(d,0),(0,d),(d,d) → (mx,ny) multipliers of (phase_x,phase_y)
    const mult = [[0, 0], [1, 0], [0, 1], [1, 1]];
    const out  = [];
    for (let i = 0; i < 4; i++) {
      const phase = mult[i][0] * phase_x + mult[i][1] * phase_y;
      out.push({ re: Math.cos(phase), im: Math.sin(phase) });
    }
    return out;
  }

  /**
   * Complex dot product  wᴴ · a  (conjugate on the weights).
   * weights come from the backend as [{index, real, imag}, …].
   */
  function complexDot(weights, steering) {
    let re = 0, im = 0;
    for (let i = 0; i < 4; i++) {
      // (w_re - j·w_im) · (a_re + j·a_im)
      re += weights[i].real * steering[i].re + weights[i].imag * steering[i].im;
      im += weights[i].real * steering[i].im - weights[i].imag * steering[i].re;
    }
    return { re, im };
  }

  /** Beampattern power |wᴴ a|² at one direction. */
  function beampatternValue(weights, az_deg, el_deg) {
    const a   = steeringVector(az_deg, el_deg);
    const dot = complexDot(weights, a);
    return dot.re * dot.re + dot.im * dot.im;   // power, not amplitude
  }

  /** Spherical → Cartesian (Three.js: Y is up, elevation maps to Y). */
  function toCartesian(az_deg, el_deg, radius) {
    const az = az_deg * Math.PI / 180;
    const el = el_deg * Math.PI / 180;
    return {
      x: radius * Math.cos(el) * Math.cos(az),
      y: radius * Math.sin(el),
      z: radius * Math.cos(el) * Math.sin(az),
    };
  }

  /**
   * Rainbow colormap — red = max gain, blue = deep null (real CRPA pattern look).
   * @returns {{r,g,b}} components in 0..1
   */
  function dbToColor(power_db, power_normalized) {
    if (Math.random() < 0.001) {
      console.log('dbToColor sample:', power_db, power_normalized,
        'hue:', (1 - Math.pow(Math.max(0, Math.min(1, power_normalized)), 0.6)) * 240);
    }
    const t = Math.pow(Math.max(0, Math.min(1, power_normalized)), 0.6);
    // Hue: 0 = red (max gain), 240 = blue (deep null)
    const hue = (1 - t) * 240;
    const s = 0.95;
    const l = 0.35 + t * 0.20;

    // HSL to RGB
    const h = hue / 360;
    function hue2rgb(p, q, t) {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1/6) return p + (q - p) * 6 * t;
      if (t < 1/2) return q;
      if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
      return p;
    }
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    return {
      r: hue2rgb(p, q, h + 1/3),
      g: hue2rgb(p, q, h),
      b: hue2rgb(p, q, h - 1/3),
    };
  }

  /* ── full sphere scan ────────────────────────────────────────── */

  function computeFullBeampattern(weights) {
    const data = [];
    let maxPower = 0;

    // Pass 1 — raw powers over the upper hemisphere + find max.
    // ei=0→el=0, ei=44→el=88.  Total: 180 × 45 = 8100 points.
    for (let ei = 0; ei < EL_STEPS; ei++) {
      const el = ei * EL_RES;          // 0 … 88 (upper hemisphere)
      for (let ai = 0; ai < AZ_STEPS; ai++) {
        const az    = ai * AZ_RES;     // 0 … 358
        const power = beampatternValue(weights, az, el);
        data.push({ az, el, power });
        if (power > maxPower) maxPower = power;
      }
    }

    // Pass 2 — normalize, dB, colour
    const invMax = 1 / (maxPower + 1e-100);
    data.forEach(d => {
      d.power_normalized = d.power * invMax;                         // 0 … 1
      let db = 10 * Math.log10(d.power * invMax + 1e-10);
      d.power_db = Math.max(db, MIN_DB);                             // clamp to floor
      d.color = dbToColor(d.power_db, d.power_normalized);
    });

    // Pass 3 — visual contrast shaping (purely visual; does NOT touch power_db).
    // A sigmoid centered at 0.3 pushes near-null values toward 0 and lobe values
    // toward 1, so lobes extend to full radius and nulls collapse to a sharp pinch.
    data.forEach(d => {
      const shaped = 1 / (1 + Math.exp(-8 * (d.power_normalized - 0.3)));
      d.visual_weight = shaped;                                      // used for radius only
      d.radius = BASE_RADIUS * (0.04 + 0.96 * Math.pow(d.visual_weight, 0.5));
      // nulls → ~0.04*80 ≈ 3 units (near-invisible pinch); lobe → ~80 units (full extension)
      const c = toCartesian(d.az, d.el, d.radius);
      d.x = c.x; d.y = c.y; d.z = c.z;
    });

    return {
      data,
      maxPower,
      az_steps:      AZ_STEPS,
      el_steps:      EL_STEPS,
      az_resolution: AZ_RES,
      el_resolution: EL_RES,
    };
  }

  /** GPS lobe power — directly overhead (az=0, el=90). */
  function gpsGain(weights) {
    return beampatternValue(weights, 0, 90);
  }

  /**
   * Verify null depth at each jammer azimuth.
   * Uses el=0° to match the backend's own null definition (core.py compute_mvdr
   * evaluates jammer steering at el=0°), so these reproduce the reported null_depths.
   */
  function verifyNullDepths(weights, jammerAngles, maxPower) {
    const invMax = 1 / (maxPower + 1e-100);
    return jammerAngles.map(j => {
      const power = beampatternValue(weights, j.angle, 0);
      const null_depth_db = 10 * Math.log10(power * invMax + 1e-10);
      return {
        angle:                j.angle,
        null_depth_db,                          // negative dB below the GPS peak
        null_depth_magnitude: Math.abs(null_depth_db),
      };
    });
  }

  /**
   * Visually bias the null depth by jammer type — purely a rendering effect on
   * radius (does NOT change power_db). CW reads as the sharpest/deepest pinch,
   * Barrage as the widest/shallowest dip, FMCW in between.
   */
  function applyJammerTypeScaling(beampatternData) {
    if (!window.sceneState.jammers || window.sceneState.jammers.length === 0) return;

    window.sceneState.jammers.forEach(j => {
      if (j.azimuth === null || j.azimuth === undefined) return;

      // How much to lift the null (1.0 = no lift = deepest); larger spread = wider dip.
      const typeScale = { CW: 1.0, FMCW: 0.75, Barrage: 0.55 };
      const scale     = typeScale[j.type] || 1.0;
      const spreadDeg = j.type === 'Barrage' ? 20 : j.type === 'FMCW' ? 10 : 5;

      const jamAz = ((j.azimuth % 360) + 360) % 360;
      beampatternData.data.forEach(pt => {
        const azDiff = Math.abs(pt.az - jamAz);
        const normalizedAzDiff = Math.min(azDiff, 360 - azDiff);
        if (normalizedAzDiff < spreadDeg) {
          const proximity = 1 - normalizedAzDiff / spreadDeg;
          pt.visual_weight = Math.min(1, pt.visual_weight + (1 - scale) * proximity * 0.4);
          pt.radius = BASE_RADIUS * (0.04 + 0.96 * Math.pow(pt.visual_weight, 0.5));
          const cart = toCartesian(pt.az, pt.el, pt.radius);
          pt.x = cart.x; pt.y = cart.y; pt.z = cart.z;
        }
      });
    });
  }

  /* ── grid lookup ─────────────────────────────────────────────── */

  function _nearestIndex(az_deg, el_deg) {
    const ai = Math.round(((az_deg % 360) + 360) % 360 / 2) % AZ_STEPS;
    const ei = Math.max(0, Math.min(EL_STEPS - 1, Math.round(el_deg / 2)));
    return ei * AZ_STEPS + ai;
  }

  /* ── 4.2 mesh builders ───────────────────────────────────────── */

  /**
   * Build a rainbow polar surface — gain as HEIGHT over a flat azimuth plane,
   * with a flat dark-blue base disc at the el=0 ring. Red peak = max gain (GPS
   * lobe overhead), blue dips = nulls.
   */
  function buildPolarSurfaceMesh(data, dronePosition) {
    const AZ_STEPS = 180;
    const EL_STEPS = 45;
    const MAX_RADIUS = 100;   // max XZ spread at el=0
    const MAX_HEIGHT = 160;   // max Y height at el=90 (GPS lobe)

    console.log('First 5 data points:', data.data.slice(0, 5).map(d => ({ az: d.az, el: d.el, power_normalized: d.power_normalized, power_db: d.power_db })));
    console.log('Max el value:', Math.max(...data.data.map(d => d.el)));
    console.log('Max power_normalized:', Math.max(...data.data.map(d => d.power_normalized)));

    const vertices = new Float32Array(AZ_STEPS * EL_STEPS * 3);
    const colors   = new Float32Array(AZ_STEPS * EL_STEPS * 3);

    data.data.forEach((pt, i) => {
      const az = pt.az * Math.PI / 180;
      const el = pt.el * Math.PI / 180;
      const g  = 0.05 + 0.95 * pt.power_normalized;  // gain scale 0.05–1.0

      // Polar surface: radius in XZ scales with cos(el)*gain
      // Height Y scales with sin(el)*gain + base elevation component
      const xzR = MAX_RADIUS * Math.cos(el) * g;
      const yH  = MAX_HEIGHT * (Math.sin(el) * g + 0.15 * g);

      vertices[i*3]     = dronePosition.x + xzR * Math.cos(az);
      vertices[i*3 + 1] = dronePosition.y + yH;
      vertices[i*3 + 2] = dronePosition.z - xzR * Math.sin(az);

      const c = dbToColor(pt.power_db, pt.power_normalized);
      colors[i*3]     = c.r;
      colors[i*3 + 1] = c.g;
      colors[i*3 + 2] = c.b;
    });

    // Triangulate the grid
    const indices = [];
    for (let ei = 0; ei < EL_STEPS - 1; ei++) {
      for (let ai = 0; ai < AZ_STEPS; ai++) {
        const next_ai = (ai + 1) % AZ_STEPS;
        const i00 = ei * AZ_STEPS + ai;
        const i10 = ei * AZ_STEPS + next_ai;
        const i01 = (ei + 1) * AZ_STEPS + ai;
        const i11 = (ei + 1) * AZ_STEPS + next_ai;
        indices.push(i00, i10, i01);
        indices.push(i10, i11, i01);
      }
    }

    // Flat base disc at el=0 plane — add center vertex at drone position
    const centerIdx = AZ_STEPS * EL_STEPS;
    const baseVertices = new Float32Array((AZ_STEPS * EL_STEPS + 1) * 3);
    const baseColors   = new Float32Array((AZ_STEPS * EL_STEPS + 1) * 3);
    baseVertices.set(vertices);
    baseColors.set(colors);

    // Center point
    baseVertices[centerIdx*3]     = dronePosition.x;
    baseVertices[centerIdx*3 + 1] = dronePosition.y;
    baseVertices[centerIdx*3 + 2] = dronePosition.z;
    baseColors[centerIdx*3]       = 0.0;
    baseColors[centerIdx*3 + 1]   = 0.0;
    baseColors[centerIdx*3 + 2]   = 0.5;  // dark blue center

    // Base disc triangles connecting el=0 ring to center
    const baseIndices = [...indices];
    for (let ai = 0; ai < AZ_STEPS; ai++) {
      const next_ai = (ai + 1) % AZ_STEPS;
      baseIndices.push(ai, next_ai, centerIdx);
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(baseVertices, 3));
    geo.setAttribute('color',    new THREE.BufferAttribute(baseColors, 3));
    geo.setIndex(baseIndices);
    geo.computeVertexNormals();

    const mat = new THREE.MeshBasicMaterial({
      vertexColors: true,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.90,
      depthWrite: false,
    });

    return new THREE.Mesh(geo, mat);
  }

  /**
   * Red ring marker placed AT the beampattern surface in the null direction, with
   * a dB label. The radius is looked up from the nearest computed grid point (the
   * null's actual pinch radius) instead of a fixed 60 units, so markers sit on the
   * mesh near each jammer rather than clustering by the drone.
   * @returns {{ring: THREE.Mesh, label: THREE.CSS2DObject}}
   */
  function addNullMarker(null_info, dronePosition, scene, beampatternData) {
    // Step 1 — find the matching jammer by azimuth and read its true elevation.
    // Ground jammers sit below the drone, so the null must tilt DOWN, not stay at el=0.
    let jammerElevation = 0;   // default ground level
    let bestMatch = null;      // hoisted so the debug block below can read it
    if (window.sceneState.jammers && window.sceneState.jammers.length > 0) {
      let bestDiff  = Infinity;
      window.sceneState.jammers.forEach(j => {
        if (j.azimuth !== null && j.azimuth !== undefined) {
          const diff = Math.abs(j.azimuth - null_info.angle);
          if (diff < bestDiff) { bestDiff = diff; bestMatch = j; }
        }
      });
      if (bestMatch) {
        // Jammer Three.js position: (threeX, threeY, threeZ). worldX === threeX,
        // threeZ === -worldY. Compute elevation jammer→drone in scene space.
        const jx = bestMatch.threeX !== undefined ? bestMatch.threeX : (bestMatch.worldX || 0);
        const jz = bestMatch.threeZ !== undefined ? bestMatch.threeZ : -(bestMatch.worldY || 0);
        const jy = bestMatch.threeY !== undefined ? bestMatch.threeY : 0;
        const dx = jx - (dronePosition.x || 0);
        const dz = jz - (dronePosition.z || 0);
        const dy = jy - dronePosition.y;
        const horizontalDist = Math.sqrt(dx * dx + dz * dz);
        jammerElevation = Math.atan2(dy, horizontalDist) * 180 / Math.PI;
      }
    }

    // Step 2 — find the radius at this az/el from the beampattern grid.
    let bestPt   = null;
    let bestDist = Infinity;
    const azNorm = ((null_info.angle % 360) + 360) % 360;
    beampatternData.data.forEach(pt => {
      const dAz = Math.abs(pt.az - azNorm);
      const dEl = Math.abs(pt.el - 0);   // MVDR null is steered at el=0
      const d   = dAz + dEl * 2;   // weight elevation so the right ring is picked
      if (d < bestDist) { bestDist = d; bestPt = pt; }
    });
    const nullRadius = bestPt ? bestPt.radius + 8 : 50;

    // Step 3 — place the ring on the MVDR null plane (el=0, where the pinch renders).
    const az = null_info.angle * Math.PI / 180;
    const el = 0;   // MVDR nulls are steered at el=0
    // z negated → scene azimuth convention, matching buildPolarSurfaceMesh.
    const dir = new THREE.Vector3(
      Math.cos(el) * Math.cos(az),
      Math.sin(el),
      -Math.cos(el) * Math.sin(az),
    ).normalize();

    const ringPos = new THREE.Vector3().copy(dronePosition).addScaledVector(dir, nullRadius);

    // Ring facing the drone. TorusGeometry lies flat in the XZ plane, so calling
    // lookAt on the torus directly only aims its Z axis and the hole shows edge-on
    // (a line). Instead: stand the torus upright (rotate.x = 90°) inside a group,
    // then lookAt the GROUP so the hole axis points at the drone.
    const ringGroup = new THREE.Group();
    ringGroup.position.copy(ringPos);

    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(5, 1.2, 8, 24),
      new THREE.MeshBasicMaterial({ color: 0xff2200, transparent: true, opacity: 0.9 })
    );
    ring.rotation.x = Math.PI / 2;     // stand the torus upright first
    ringGroup.add(ring);
    ringGroup.lookAt(dronePosition);   // aim the group at the drone
    scene.add(ringGroup);

    // CSS2D label — offset UP by 8 units so it clears the DRONE label
    const labelDiv = document.createElement('div');
    labelDiv.style.cssText = `
      color: #ff2200;
      font-family: 'Courier New', monospace;
      font-size: 10px;
      font-weight: bold;
      background: rgba(8,0,0,0.85);
      padding: 2px 5px;
      border: 1px solid #ff2200;
      pointer-events: none;
      white-space: nowrap;
      margin-bottom: 4px;
    `;
    labelDiv.textContent = `NULL ${null_info.null_depth_db.toFixed(0)}dB`;
    const labelPos = ringPos.clone();
    labelPos.y += 8;
    const label = new THREE.CSS2DObject(labelDiv);
    label.position.copy(labelPos);
    scene.add(label);

    return { ring: ringGroup, label };
  }

  /** Cyan arrow up from the drone = GPS satellite direction. */
  function addGPSMarker(dronePosition, _gpsGainDb, scene) {
    const arrow = new THREE.ArrowHelper(
      new THREE.Vector3(0, 1, 0),
      dronePosition.clone(),
      90,        // length
      0x00ccff,  // cyan
      15,        // head length
      8          // head width
    );
    scene.add(arrow);
    return arrow;
  }

  /** Remove a {ring,label} null marker, disposing its label DOM, geometry, material. */
  function _disposeMarker(scene, m) {
    if (m.label) {
      if (m.label.element) m.label.element.remove();
      scene.remove(m.label);
    }
    if (m.ring) {
      scene.remove(m.ring);   // m.ring is now a THREE.Group
      m.ring.traverse(o => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) o.material.dispose();
      });
    }
  }

  /* ── public API ──────────────────────────────────────────────── */

  return {

    /** Reset compute state and inject beampattern HUD controls. */
    init() {
      _beampatternData = null;
      _mvdrWeights     = null;
      _jammerAngles    = [];
      _gpsGain         = null;
      _gpsGainDb       = 0.0;
      _nullDepths      = [];
      _isComputed      = false;

      const hudPanel = document.getElementById('hud-panel');
      if (hudPanel && !document.getElementById('beampattern-controls')) {
        const controls = document.createElement('div');
        controls.id = 'beampattern-controls';
        controls.innerHTML = `
          <button class="bp-toggle-btn" id="bp-vis-toggle">◉ BEAMPATTERN: ON</button>
          <span class="bp-status" id="bp-status">NOT COMPUTED</span>
        `;
        controls.innerHTML += '<div style="font-size:10px;color:#1a5a1a;margin-top:4px;padding:0 4px;">TIP: Place 3 jammers 120° apart at ground level for best petal visualization</div>';
        hudPanel.insertBefore(controls, hudPanel.firstChild);

        document.getElementById('bp-vis-toggle').onclick = () => {
          _isVisible = !_isVisible;
          if (_beampatternMesh) _beampatternMesh.visible = _isVisible;
          _nullMarkers.forEach(m => { m.ring.visible = _isVisible; m.label.visible = _isVisible; });
          if (_gpsMarker) _gpsMarker.visible = _isVisible;
          const btn = document.getElementById('bp-vis-toggle');
          btn.textContent = `◉ BEAMPATTERN: ${_isVisible ? 'ON' : 'OFF'}`;
          btn.classList.toggle('off', !_isVisible);
        };
      }

      console.log('RadiationAPI 4.2 initialized');
    },

    /**
     * Compute the full 3-D beampattern from an /api/mvdr response.
     * @param {object} mvdrResponse  full object from NavguardAPI.runMVDR()
     * @returns {object} beampattern data (also retrievable via getBeampatternData)
     */
    async computeBeampattern(mvdrResponse) {
      // 1 — extract weights + jammer angles
      _mvdrWeights  = mvdrResponse.weights;
      _jammerAngles = (mvdrResponse.null_depths || []).map(n => ({ angle: n.angle }));

      // 2 — full sphere scan
      console.time('beampattern_compute');
      const result = computeFullBeampattern(_mvdrWeights);
      console.timeEnd('beampattern_compute');

      // 3 — GPS lobe info
      _gpsGain = gpsGain(_mvdrWeights);
      _gpsGainDb = 10 * Math.log10(_gpsGain / (result.maxPower + 1e-100) + 1e-10);
      result.gps_gain_linear = _gpsGain;
      result.gps_gain_db     = _gpsGainDb;

      // 4 — verify nulls
      _nullDepths = verifyNullDepths(_mvdrWeights, _jammerAngles, result.maxPower);
      result.verified_nulls = _nullDepths;

      // 5 — store
      _beampatternData = result;
      _isComputed = true;

      // 5b — bias null radius by jammer type (visual only)
      applyJammerTypeScaling(result);

      // 6 — hand off to mesh renderer
      this.updateMesh(result);

      // 7 — console summary
      this.printSummary();

      return result;
    },

    /** Last computed beampattern, or null. */
    getBeampatternData() {
      return _beampatternData;
    },

    /**
     * Value at the nearest grid point to (az, el).
     * @returns {{az,el,power_db,power_normalized,color,x,y,z}|null}
     */
    getValueAt(az_deg, el_deg) {
      if (!_isComputed) return null;
      const d = _beampatternData.data[_nearestIndex(az_deg, el_deg)];
      if (!d) return null;
      return {
        az: d.az, el: d.el,
        power_db:         d.power_db,
        power_normalized: d.power_normalized,
        color:            d.color,
        x: d.x, y: d.y, z: d.z,
      };
    },

    /** GPS lobe direction + gain. */
    getGPSLobe() {
      return { az: 0, el: 90, gain_db: _gpsGainDb };
    },

    /** Verified null depths per jammer. */
    getNullDepths() {
      return _nullDepths;
    },

    /** Build/refresh the 3-D beampattern mesh, wireframe, null + GPS markers. */
    updateMesh(beampatternData) {
      const t0       = performance.now();
      const scene    = SceneAPI.getScene();
      const dronePos = new THREE.Vector3(
        window.sceneState.drone.x || 0,
        window.sceneState.drone.altitude || 100,
        window.sceneState.drone.z || 0
      );

      // Remove previous mesh
      if (_beampatternMesh) {
        scene.remove(_beampatternMesh);
        _beampatternMesh.geometry.dispose();
        _beampatternMesh.material.dispose();
        _beampatternMesh = null;
      }
      // Remove previous markers
      _nullMarkers.forEach(m => _disposeMarker(scene, m));
      _nullMarkers = [];
      if (_gpsMarker) { scene.remove(_gpsMarker); _gpsMarker = null; }

      // Build new rainbow polar surface (no wireframe)
      _beampatternMesh = buildPolarSurfaceMesh(beampatternData, dronePos);
      _beampatternMesh.visible = _isVisible;
      scene.add(_beampatternMesh);
      window.sceneState.beampatternMesh = _beampatternMesh;

      // Point light near the drone so the rainbow colors read clearly
      if (!_patternLight) {
        _patternLight = new THREE.PointLight(0xffffff, 0.6, 500);
        scene.add(_patternLight);
      }
      _patternLight.position.copy(dronePos);

      // Null markers — positioned at the mesh surface in each null direction
      (beampatternData.verified_nulls || []).forEach(n => {
        const marker = addNullMarker(n, dronePos, scene, beampatternData);
        if (marker) {
          marker.ring.visible  = _isVisible;
          marker.label.visible = _isVisible;
          _nullMarkers.push(marker);
        }
      });

      // GPS marker
      _gpsMarker = addGPSMarker(dronePos, beampatternData.gps_gain_db, scene);
      _gpsMarker.visible = _isVisible;

      // Share with other modules
      window.sceneState.beampatternMesh = _beampatternMesh;

      const ms = Math.round(performance.now() - t0);
      const st = document.getElementById('bp-status');
      if (st) {
        st.textContent = `COMPUTED — ${ms}ms`;
        st.classList.add('computed');
        // Petal shape needs ≥2 jammers to form distinct lobes between nulls.
        if (window.sceneState.jammers && window.sceneState.jammers.length < 2) {
          st.textContent  = 'ADD MORE JAMMERS FOR PETAL SHAPE';
          st.style.color  = '#ff8800';
        } else {
          st.style.color  = '';
        }
      }
      console.log(`Beampattern mesh updated: ${beampatternData.data.length} vertices`);
    },

    /** Per-frame hook (driven by scene.js loop). Beampattern is static — no rotation. */
    update(_delta) {
      // ROTATE control removed — the beampattern does not rotate.
    },

    /** Text summary for console verification. */
    printSummary() {
      if (!_isComputed) { console.log('No beampattern computed yet.'); return; }
      const d        = _beampatternData;
      const inLobe   = d.data.filter(p => p.power_db > -3).length;
      const inNull   = d.data.filter(p => p.power_db < -40).length;
      const minDb    = Math.min(...d.data.map(p => p.power_db));
      const maxDb    = Math.max(...d.data.map(p => p.power_db));

      const lines = [];
      lines.push('=== BEAMPATTERN COMPUTED ===');
      lines.push(`Total points: ${d.data.length} (${d.az_steps} az × ${d.el_steps} el)`);
      lines.push(`Max power: ${d.maxPower.toExponential(4)} (linear)`);
      lines.push(`GPS lobe gain: ${d.gps_gain_db.toFixed(2)} dB (at az=0, el=90)`);
      lines.push('Null depths verified:');
      _nullDepths.forEach((n, i) => {
        lines.push(`  J${i + 1} at ${n.angle.toFixed(1)}°: ${n.null_depth_db.toFixed(1)} dB`);
      });
      lines.push(`Power range: ${minDb.toFixed(1)} dB to ${maxDb.toFixed(1)} dB`);
      lines.push(`Points in GPS lobe (>-3dB): ${inLobe}`);
      lines.push(`Points in null region (<-40dB): ${inNull}`);
      lines.push('Data ready for 4.2 mesh renderer');
      lines.push('===========================');
      console.log(lines.join('\n'));
    },

    /* ── legacy compatibility shims (used by jammers.js until Section 6) ── */

    /** Deprecated: old stub signature. Real entry point is computeBeampattern(). */
    updateBeampattern(_beampattern) {
      console.warn('RadiationAPI.updateBeampattern() is legacy — use computeBeampattern(mvdrResponse).');
    },

    /** Clear stored data and remove all 3-D objects from the scene. */
    clear() {
      const scene = (window.SceneAPI && SceneAPI.getScene) ? SceneAPI.getScene() : null;
      if (scene) {
        if (_beampatternMesh) {
          scene.remove(_beampatternMesh);
          _beampatternMesh.geometry.dispose();
          _beampatternMesh.material.dispose();
        }
        _nullMarkers.forEach(m => _disposeMarker(scene, m));
        if (_gpsMarker) scene.remove(_gpsMarker);
        if (_patternLight) { scene.remove(_patternLight); _patternLight = null; }
      }
      _beampatternMesh = null;
      _nullMarkers     = [];
      _gpsMarker       = null;
      window.sceneState.beampatternMesh = null;
      _beampatternData = null;
      _isComputed      = false;
    },
  };

})();

/* ── console test harness — call testRadiation() in the browser ──── */
window.testRadiation = async function () {
  console.log('Testing radiation computation with hardcoded weights...');

  const testMVDRResponse = {
    weights: [
      { index: 0, real: 0.245, imag: -0.112 },
      { index: 1, real: 0.198, imag:  0.087 },
      { index: 2, real: 0.231, imag: -0.054 },
      { index: 3, real: 0.201, imag:  0.043 },
    ],
    null_depths: [
      { jammer_index: 0, angle:  31.0, null_depth_db: 62.3 },
      { jammer_index: 1, angle: 127.0, null_depth_db: 50.1 },
      { jammer_index: 2, angle: -71.6, null_depth_db: 64.7 },
    ],
    gps_gain_db: 0.0,
  };

  const data = await RadiationAPI.computeBeampattern(testMVDRResponse);
  console.log('Sample at az=0  el=90 (GPS direction):', RadiationAPI.getValueAt(0, 90));
  console.log('Sample at az=31 el=10 (J1 direction):',  RadiationAPI.getValueAt(31, 10));
  return data;
};
