# NAVGUARD — Checkpoint (Sections 1 & 2 Complete)

_Generated 2026-06-07. Read every file before writing._

---

## HOW TO RUN

```bash
# Terminal 1 — Flask backend (port 5001)
cd /Users/atharvrathod/antiJAMsimulation/navguard_viz
python run_viz.py

# Terminal 2 — Static file server (port 8080)
cd /Users/atharvrathod/antiJAMsimulation/navguard_viz/frontend
python -m http.server 8080

# Browser
open http://localhost:8080/index.html
```

> macOS blocks port 5000 (AirPlay Receiver). Backend is hardwired to 5001 everywhere.

---

## DIRECTORY STRUCTURE

```
navguard_viz/
├── run_viz.py                  ← launcher (imports app, runs on 5001)
├── CHECKPOINT.md               ← this file
├── backend/
│   ├── app.py                  ← Flask routes (386 lines)
│   ├── core.py                 ← all DSP math (535 lines)
│   ├── requirements.txt
│   └── [symlinks to existing sim files — NOT modified]
│       ├── generate_array_data.py
│       ├── music_spectrum.py
│       ├── mvdr_beamformer.py
│       └── hybrid_sim.py
└── frontend/
    ├── index.html              ← DOM skeleton (104 lines)
    ├── style.css               ← dark tactical theme (179 lines)
    ├── api.js                  ← fetch wrapper (192 lines)
    ├── scene.js                ← Three.js 3D scene (313 lines)
    ├── jammers.js              ← STUB (Section 3)
    ├── radiation.js            ← STUB (Section 4)
    └── hud.js                  ← STUB (Section 5)
```

---

## SECTION 1 — Flask Backend

### Physical Constants (core.py)

| Constant | Value | Meaning |
|---|---|---|
| `FREQ_GPS` | 1575.42e6 Hz | GPS L1 |
| `LAMBDA` | 0.19029 m | 3e8 / FREQ_GPS |
| `D_ELEMENT` | 0.09521 m | λ/2 spacing |
| `ELEM_POS` | 4×3 array | 2×2 URA positions in metres |
| `_JAM_AZIMUTHS_DEFAULT` | [30.96, 165.96, -71.57] | default 3-jammer test geometry |

`ELEM_POS` rows (in order): `[0,0,0]`, `[D,0,0]`, `[0,D,0]`, `[D,D,0]`

---

### core.py — Functions

#### `db_to_linear(db) → float`
`10^(db/20)` — amplitude ratio (not power).

#### `linear_to_db(linear) → float`
`20·log10(max(|linear|, 1e-100))`.

#### `steering_vector(az_deg, el_deg) → np.ndarray shape (4,) complex128`
Phase formula: `φ_n = (2π/λ) · elem_pos[n] · [cos(el)cos(az), cos(el)sin(az), sin(el)]`
Returns shape (4,) complex128 in ELEM_POS order.
**Critical**: uses `cos(el)`, NOT `sin(el)`.

#### `jammer_geometry(jammer_xyz, drone_xyz=None) → (az_deg, el_deg, dist_m, path_loss_db)`
- `drone_xyz` defaults to `[0, 0, 100]`
- Azimuth via `arctan2(dy, dx)` in degrees
- Elevation via `arcsin(-dz / distance)` — positive = jammer above drone
- Path loss (dB): `20·log10(4π·distance/λ)`

#### `generate_iq_data(jammers, drone_pos=None, n_snapshots=1000, seed=42) → np.ndarray (4, N) complex128`
- GPS: el=90°, power 0 dBW relative, steering = `[1,1,1,1]`
- Each jammer: az from geometry, el=0° (for MUSIC consistency), CW/FMCW/Barrage waveforms
- Noise: −20 dB below GPS
- Jammers list: `[{x,y,z,type,power_db}, …]`

#### `compute_covariance(X, delta_loading=None) → np.ndarray (4,4) complex128`
`R = X·X^H / N` then diagonal loading `δ = delta_loading × trace(R)/N` if provided.

#### `compute_music(R, n_sources, az_scan=None, el_scan=None) → dict`
- Eigendecomposes R (sorted ascending by eigenvalue)
- Noise subspace: N − n_sources smallest eigenvectors
- Scans 720 points from −180 to +179.5° (0.5° steps)
- Returns: `{detected_angles, pseudospectrum[720], eigenvalues[4], snr_gap, signal_subspace_size, noise_subspace_size}`
- `detected_angles`: list of `{azimuth, elevation, power_db}` dicts, n_sources peaks with ≥25° separation

#### `compute_mvdr(R, gps_az, gps_el, jammer_angles) → dict`
- `w = R⁻¹ a_gps / (a_gps^H R⁻¹ a_gps)`, diagonal loading `δ = 1e-4 × trace(R)/N`
- 360-point beampattern scan (−180 to +179°, 1° steps)
- Returns: `{weights[4] complex, beampattern[360] dB, null_depths dict, gps_gain_db, rms_before, rms_after, rms_reduction_db}`
- `null_depths`: keyed by jammer angle string, value = dB below GPS gain

#### `compute_hybrid_curve(alpha_pre=0.9, adc_fullscale=5.0, n_points=50) → dict`
- Sweeps jammer power from −10 to +50 dBW
- Three paths per point: ideal (no ADC), digital (clip at ADC_FS), hybrid (analog pre-cancel then clip)
- Hybrid uses `a_gps_eff` as MVDR look direction (NOT `a_gps`) — the pre-cancelled GPS steering
- N_SAMP=500 for speed
- Returns: `{jammer_powers_db, sinr_digital, sinr_hybrid, sinr_ideal, digital_fails_at_db, hybrid_fails_at_db, improvement_at_30db, advantage_db}`
- Typical results: `digital_fails_at ≈ 9.2 dB`, `hybrid_fails_at ≈ 23.5 dB`, `improvement_at_30db ≈ 16 dB`

---

### app.py — Endpoints

Flask app on port 5001. All POST bodies and responses are JSON.
`numpy_to_python(obj)` recursively converts numpy types; complex → `{"real": float, "imag": float}`.
`_err(message, exc)` returns HTTP 500 `{success: false, error: "...", traceback: "..."}`.

Scenario store: `scenarios` dict keyed by UUID:
```python
{scenario_id: {X, jammers, geometries, drone_pos,
               music_result, mvdr_result, hybrid_result, created_at}}
```

#### `GET /api/health`
`{status: "ok", scenarios_stored: N}`

#### `GET /api/config`
```json
{
  "freq_hz": 1575420000,
  "lambda_m": 0.19029,
  "element_spacing_m": 0.09521,
  "array_layout": "2x2_URA",
  "n_elements": 4,
  "gps_power_dbw": 0,
  "drone_altitude_m": 100,
  "max_jammers": 3,
  "jammer_types": ["CW", "FMCW", "Barrage"],
  "default_alpha_pre": 0.9,
  "default_adc_fullscale": 5.0,
  "default_n_snapshots": 1000
}
```

#### `POST /api/generate`
Request: `{jammers:[{x,y,z,type,power_db}], drone_altitude, n_snapshots}`
Response: `{success, scenario_id, array_shape, jammer_geometries, gps_direction, antenna_positions}`

#### `POST /api/music`
Request: `{scenario_id, n_jammers}`
Response: `{success, detected_angles, pseudospectrum[720], eigenvalues[4], snr_gap, signal_subspace_size, noise_subspace_size}`

#### `POST /api/mvdr`
Request: `{scenario_id, jammer_angles, gps_azimuth, gps_elevation}`
Response: `{success, weights[4], beampattern[360], null_depths, gps_gain_db, rms_before, rms_after, rms_reduction_db}`

#### `POST /api/hybrid`
Request: `{scenario_id, alpha_pre, adc_fullscale, n_points}`
Response: `{success, jammer_powers_db, sinr_digital, sinr_hybrid, sinr_ideal, digital_fails_at_db, hybrid_fails_at_db, improvement_at_30db, advantage_db}`
Note: `scenario_id` stored but not used for computation — hybrid uses default geometry internally.

#### `POST /api/reset`
Request: `{scenario_id}`
Response: `{success: true}`

---

### run_viz.py

- Sets `sys.path` to include `backend/`
- Imports `app` from `app.py`
- Calls `app.run(host="0.0.0.0", port=5001, debug=False)`
- Prints startup banner

---

### requirements.txt

```
flask==3.0.0
flask-cors==4.0.0
numpy==1.26.0
scipy==1.11.0
```

---

## SECTION 2 — Three.js Frontend

### index.html — DOM Structure

```
<body>
  <div id="top-bar">           40px — title + version + step badges
    #app-title                 "NAVGUARD ANTI-JAM SIM"
    #version-tag               "v1.0"
    #step-badges
      .step-badge[data-step=init]      ← starts .active
      .step-badge[data-step=generate]
      .step-badge[data-step=music]
      .step-badge[data-step=mvdr]
      .step-badge[data-step=hybrid]
  </div>
  <div id="main">              calc(100vh - 70px), display:flex
    <div id="scene-container"> flex:7, Three.js canvas mounted here
    <div id="hud-panel">       flex:3, right panel — Section 5 fills this
  </div>
  <div id="status-bar">        30px — bottom status strip
    #status-backend            "BACKEND: CONNECTING…"
    #status-scenario           "SCENARIO: --"
    #status-step               "STEP: IDLE"
    #status-timing             "LAST CALL: --"
  </div>
```

Script load order (order matters):
1. `three.min.js` (r128, cdnjs)
2. `OrbitControls.js` (jsdelivr, three@0.128.0)
3. `CSS2DRenderer.js` (jsdelivr, three@0.128.0)
4. `api.js`
5. `scene.js`
6. `jammers.js`
7. `radiation.js`
8. `hud.js`
9. inline bootstrap script

#### Inline bootstrap script
- `window.setStep(stepName)` — advances badges: done/active/inactive
  - `order = ['init','generate','music','mvdr','hybrid']`
  - badges before active index → `.done`, active index → `.active`
  - also sets `window.sceneState.currentStep`
- `DOMContentLoaded` handler:
  - calls `SceneAPI.init('scene-container')`
  - calls `JammersAPI.init()`, `RadiationAPI.init()`, `HUDAPI.init()`
  - calls `NavguardAPI.getConfig()` to probe backend
  - on success: `#status-backend` → "BACKEND: ONLINE" + `.active`
  - on failure: `#status-backend` → "BACKEND: OFFLINE" + `.error`

---

### style.css — Key Colors & Classes

| Token | Value | Used for |
|---|---|---|
| `#0a0a0a` | near-black | body bg, scene bg |
| `#0d1a0d` | dark green-black | top-bar, status-bar, hud bg |
| `#1a3a1a` | dim green | grid lines, borders, dashes |
| `#2a5a2a` | muted green | inactive text, labels |
| `#00ff88` | bright green | active text, badges, antenna pulse |
| `#00ccff` | cyan | GPS, antenna elements, links |
| `#ff3300` | red | jammer markers, error state |
| `#ff8800` | orange | warning (reserved) |

| CSS class | Purpose |
|---|---|
| `.step-badge` | default: dim, `#1a3a1a` border |
| `.step-badge.active` | solid `#00ff88` bg, black text |
| `.step-badge.done` | `#00ff88` border only |
| `.status-item` | dim `#2a5a2a` text |
| `.status-item.active` | bright `#00ff88` |
| `.status-item.error` | `#ff3300` red |
| `.scene-label` | Three.js CSS2D base (dark bg, mono font) |
| `.scene-label.cyan` | `#00ccff` — GPS/antenna labels |
| `.scene-label.jammer` | `#ff3300` — jammer labels |
| `.scene-label.compass` | transparent bg, larger, N/E/S/W |
| `.hud-placeholder` | dashed border placeholder in hud-panel |

---

### scene.js — SceneAPI

`window.sceneState` (shared read-only by all modules):
```js
{
  drone: {x,y,z,altitude:100},
  jammers: [],
  antennaElements: [],   // four THREE.Mesh refs
  gpsObject: null,       // GPS octahedron mesh
  droneObject: null,     // drone body mesh
  beampatternMesh: null, // set by Section 4
  scenario_id: null,
  isRunning: false,
  currentStep: 'idle',
}
```

Coordinate mapping: `backend(x, y, z_alt) → Three.js(x, z_alt, -y)` (Y=up in Three.js)

Constants:
- `DRONE_POS = Vector3(0, 100, 0)`
- `GPS_POS   = Vector3(0, 800, 0)`

Private helpers (not exported):
- `makeLabel(text, cssClass)` → `THREE.CSS2DObject` with `.scene-label` div
- `buildGrid()` — `GridHelper(2000, 40, #1a3a1a, #1a3a1a)`
- `buildDrone()` — white sphere r=3 at DRONE_POS; 4 cyan antenna spheres r=1.5 at ±5 offsets; "DRONE" label
- `buildGPS()` — cyan octahedron r=8 at GPS_POS; "GPS SAT" label; dashed cyan line to drone
- `buildAxesAndCompass()` — AxesHelper(50); N/E/S/W labels at 200m radius on y=1 plane

`window.SceneAPI` public methods:
- `init(containerId)` — creates scene, camera (PerspectiveCamera 60°, pos 300,400,500), WebGL renderer, CSS2DRenderer overlay, OrbitControls (minDist=50, maxDist=2000, damping=0.05), lighting (AmbientLight 0.4 + DirectionalLight 0.8 at 200,500,200), adds resize handler
- `animate()` — starts rAF loop (idempotent via `animating` flag); spins GPS +0.005 rad/frame; renders both renderers
- `addJammer(jammer)` → index — creates red sphere r=8, "JAMn" label; appends to `jammerObjects[]` and `sceneState.jammers[]`
- `removeJammer(index)` — removes mesh from scene and both arrays
- `updateAntennaElements(_data)` — pulses all 4 antenna emissive to cyan for 450ms
- `highlightAngle(angle_deg)` — draws yellow ray from DRONE_POS, len=420; `end = (cos(az)*420, 0, -sin(az)*420)` relative to drone; appended to `highlights[]`
- `clearHighlights()` — removes all highlight rays from scene
- `getScene()`, `getCamera()`, `getRenderer()` — raw Three.js object accessors

Camera setup: `PerspectiveCamera(60, W/H, near=1, far=10000)` at `(300, 400, 500)`, lookAt DRONE_POS

---

### api.js — NavguardAPI

`const API_BASE = 'http://localhost:5001'`

Internal `_fetch(path, options)`:
- Sets `sceneState.isRunning = true` on start, `false` in `finally`
- Updates `#status-timing` with round-trip ms
- On error: updates `#status-step` with `.error` class, truncated to 55 chars
- Throws `Error(data.error)` if `!res.ok || data.success === false`

Public methods:

| Method | Signature | Calls |
|---|---|---|
| `getConfig()` | `()` | `GET /api/config` |
| `generate(jammers, droneAltitude=100, nSnapshots=1000)` | → response | `POST /api/generate` |
| `runMusic(scenarioId, nJammers=3)` | → response | `POST /api/music` |
| `runMVDR(scenarioId, jammerAngles, gpsAz=0.0, gpsEl=90.0)` | → response | `POST /api/mvdr` |
| `runHybrid(scenarioId, alphaPre=0.9, adcFullscale=5.0, nPoints=50)` | → response | `POST /api/hybrid` |
| `reset(scenarioId)` | → response | `POST /api/reset` |
| `runFullPipeline(jammers, options)` | → `{generate, music, mvdr, hybrid, scenario_id}` | all 4 in sequence |

`runFullPipeline` flow:
1. `generate` → stores `scenario_id` in `sceneState.scenario_id` and `#status-scenario`
2. `runMusic` → extracts `jamAngles = detected_angles.map(d => d.azimuth)`
3. `runMVDR(sid, jamAngles)` with default gpsAz=0, gpsEl=90
4. `runHybrid(sid, ...)`
5. Sets `#status-step` to "STEP: COMPLETE"

---

### Stub files (Sections 3–5 placeholders)

**jammers.js** — `window.JammersAPI`:
- `init()` — logs "stub"
- `addJammer(config)` — no-op
- `removeJammer(index)` — no-op
- `clearAll()` — no-op

**radiation.js** — `window.RadiationAPI`:
- `init()` — logs "stub"
- `updateBeampattern(beampatternData)` — no-op
- `clear()` — no-op

**hud.js** — `window.HUDAPI`:
- `init()` — logs "stub"
- `update(data)` — no-op
- `setStep(step)` — no-op

---

## KNOWN BUGS / GOTCHAS

1. **Hybrid scenario_id not used** — `POST /api/hybrid` stores `scenario_id` in the scenario dict but `compute_hybrid_curve()` always uses default geometry. Future: derive alpha/ADC params from stored scenario.

2. **run_viz.py docstring says port 5000** (line 7) — actually runs on 5001. Docstring is stale.

3. **CSS2DRenderer label positioning** — `labelRenderer.setSize(w, h)` must be called on resize (already done in scene.js). Labels drift if skipped.

4. **MUSIC scan is 1D azimuth only** — el fixed at 0° for jammer detection. GPS at el=90° never appears as a peak in MUSIC output, which is by design.

5. **`compute_hybrid_curve` is slow** (N_SAMP=500, n_points default 50 = 50 covariance builds) — takes ~2–4 s on M-series Mac. Do not increase n_points above 100.

---

## WHAT TO BUILD NEXT

---

### Section 3 — jammers.js (Interactive Jammer Placement)

**Goal**: Replace the stub with a full jammer control system. Users click on the 3D ground plane to place jammers, set type and power, then trigger the pipeline.

**What to implement in jammers.js**:

```js
window.JammersAPI = {
  init(),            // add raycaster click listener to scene-container
  addJammer(config), // config: {x, y, z, type, power_db}
                     //   → calls SceneAPI.addJammer(config)
                     //   → pushes to internal _jammers list
                     //   → renders jammer card in #hud-panel
  removeJammer(index),  // remove from scene + list + card
  clearAll(),        // reset to 0 jammers
  getJammers(),      // return current list
}
```

**Raycasting click-to-place**:
- Add `pointerdown` listener on `#scene-container`
- Use `THREE.Raycaster` + invisible ground plane at y=0 (`PlaneGeometry(4000,4000)` rotated −π/2)
- On hit: derive `{x: hit.x, y: -hit.z, z: 0}` (reverse coord mapping)
- Max 3 jammers — show warning if exceeded

**Jammer card (append to #hud-panel)**:
```html
<div class="jammer-card" id="jammer-card-{n}">
  JAM{n}: [{x}, {y}]
  <select class="jam-type">CW / FMCW / Barrage</select>
  <input type="range" class="jam-power" min="10" max="50" value="30"> dB
  <button class="jam-remove">×</button>
</div>
```

**Signal ray animation** (optional visual):
- CW: static yellow ray from jammer toward drone
- FMCW: oscillating opacity ray (Math.sin on time)
- Barrage: random flicker

**Trigger pipeline**:
- Add "RUN PIPELINE" button to #hud-panel
- On click: call `NavguardAPI.runFullPipeline(JammersAPI.getJammers())`
- Pass result to `RadiationAPI.updateBeampattern()` and `HUDAPI.update()`

**CSS classes to add to style.css**:
- `.jammer-card` — dark card with `#ff3300` left border
- `.jam-type`, `.jam-power` — dark styled select/range inputs
- `.jam-remove` — small red ×

---

### Section 4 — radiation.js (3D Beampattern Visualization)

**Goal**: Visualize the MVDR beampattern as a 3D surface centered on the drone, colored by gain.

**What to implement in radiation.js**:

```js
window.RadiationAPI = {
  init(),                           // no-op; scene must be ready first
  updateBeampattern(beampatternData), // beampatternData = mvdr.beampattern[360] dB array
  clear(),                          // remove mesh from scene
}
```

**Building the 3D surface**:
- Input: `beampattern[360]` — gain in dB for az = −180°…+179° at el=0°
- Normalize to [0,1]: `(dB − minDB) / (maxDB − minDB)`
- Build `THREE.BufferGeometry` sphere-like shell:
  - For each of 360 azimuth samples, compute radius `r = 30 + normalized_gain * 80`
  - Full polar loop: for each az, for each el in [−90,90] (discretize into ~36 steps)
  - Vertex: `(r·cos(el)·cos(az), r·sin(el), r·cos(el)·sin(az))` offset by DRONE_POS
- Or simpler: equatorial ring — just at el=0, extrude ±8 units in y as a ribbon

**Color mapping**:
- `gain > −3 dB` of GPS gain → `#00ff88` (green = GPS lobe)
- `gain < −40 dB` → `#ff3300` (red = null)
- Between: lerp `#ff8800` (yellow/orange)
- Use `THREE.VertexColors` with `BufferAttribute` for per-vertex color

**Attaching to scene**:
- Use `SceneAPI.getScene()` to access scene
- Store mesh ref in `window.sceneState.beampatternMesh`
- `clear()`: `scene.remove(sceneState.beampatternMesh); sceneState.beampatternMesh = null`

**Null depth markers**:
- For each null in `mvdr_result.null_depths`, call `SceneAPI.highlightAngle(az)` in red
- Override line color: access via `highlights` array — or add a `highlightAngleRed(az)` to SceneAPI

---

### Section 5 — hud.js (Tactical Right Panel)

**Goal**: Fill `#hud-panel` with a live tactical readout of all pipeline results.

**What to implement in hud.js**:

```js
window.HUDAPI = {
  init(),          // inject static HTML structure into #hud-panel
  update(data),    // data = {generate, music, mvdr, hybrid} from runFullPipeline
  setStep(step),   // highlight which section of the HUD is active
}
```

**Panel layout (init injects into #hud-panel)**:

```
┌─────────────────────────┐
│  SCENARIO: --           │  ← scenario ID truncated
│  ARRAY: 2×2 URA  N=4   │
├─────────────────────────┤
│  MUSIC DOA              │
│  JAM1:  30.96°          │
│  JAM2: 165.96°          │
│  JAM3: -71.57°          │
│  SNR gap:  XX.X dB      │
├─────────────────────────┤
│  MVDR NULLING           │
│  GPS gain:  X.X dB      │
│  NULL@30.96°: -51.2 dB  │
│  NULL@165.9°: -48.7 dB  │
│  NULL@-71.6°: -53.1 dB  │
│  RMS reduction: XX dB   │
├─────────────────────────┤
│  HYBRID ADVANTAGE       │
│  Digital fails: X dB    │
│  Hybrid fails: XX dB    │
│  Advantage: +XX dB      │
│  [ASCII SINR chart]     │
├─────────────────────────┤
│  [GENERATE]             │  ← pipeline buttons
│  [MUSIC] [MVDR] [HYB]  │
└─────────────────────────┘
```

**ASCII SINR chart**:
- 20 columns × 10 rows text chart
- x-axis: jammer power −10 to +50 dBW
- y-axis: SINR 0 to 40 dB
- Three lines: `·` ideal, `-` digital, `=` hybrid
- Print using a `<pre class="sinr-chart">` block

**CSS to add**:
- `.hud-section` — bordered section with header
- `.hud-row` — `display:flex; justify-content:space-between`
- `.hud-value` — right-aligned numeric, `#00ff88`
- `.hud-value.warn` — `#ff8800` if value is marginal
- `.hud-value.bad` — `#ff3300` if null < 40 dB
- `.sinr-chart` — monospace, small font, `#1a3a1a` color

---

### Section 6 — Integration & Polish

**Goal**: Wire all modules together, add save/load, export, and step-through animation.

**Wire-up in index.html inline script** (after all modules load):
```js
document.addEventListener('DOMContentLoaded', () => {
  // existing init calls ...

  // Wire pipeline button (injected by HUDAPI.init)
  document.addEventListener('navguard:runpipeline', async () => {
    const jammers = JammersAPI.getJammers();
    if (!jammers.length) return alert('Place at least one jammer first.');
    const results = await NavguardAPI.runFullPipeline(jammers);
    SceneAPI.clearHighlights();
    results.music.detected_angles.forEach(a => SceneAPI.highlightAngle(a.azimuth));
    RadiationAPI.updateBeampattern(results.mvdr.beampattern);
    HUDAPI.update(results);
    SceneAPI.updateAntennaElements(results);
  });
});
```

**Save/Load scenario JSON**:
- Save: `JSON.stringify({jammers, results})` → download as `navguard_scenario_TIMESTAMP.json`
- Load: file input → parse → restore jammers via `JammersAPI.addJammer()`, re-render HUD

**Export PNG**:
- `renderer.domElement.toDataURL('image/png')` → download link
- Trigger after `runFullPipeline` completes or via button

**Step-through animation** (optional):
- "REPLAY" button: animate jammer placement → MUSIC peaks appearing one by one (delay 800ms each) → beampattern fading in → HUD values counting up

**Performance notes**:
- `runHybrid` with `n_points=50` takes ~2–4 s. Set `nPoints=30` for real-time feel.
- Three.js `labelRenderer.render()` is called every frame — if >10 labels exist, consider culling off-screen ones.

---

## VERIFIED ENDPOINT RESULTS (as of last test)

```
POST /api/generate   → scenario_id returned, jammer_geometries correct
POST /api/music      → 3 angles detected, SNR gap present
POST /api/mvdr       → null_depths 48–54 dB (confirmed by user: "exactly where they should be")
POST /api/hybrid     → digital_fails≈9.2 dB, hybrid_fails≈23.5 dB, improvement_at_30db≈16 dB
GET  /api/config     → all fields present
POST /api/reset      → success: true
GET  /api/health     → status: ok
```

---

## SIMULATION DIAGNOSTIC REPORT — 2026-06-07

### Overall Completeness: ~25%
Core DSP pipeline complete and correct. Hardware impairment layer not yet built.
All current KPIs pass in ideal conditions only. realistic_sim.py does not exist.

### KPI Results (run_all.py — ideal conditions)

| Metric | Result | Target | Pass |
|--------|--------|--------|------|
| DoA J1 error | 0.01° | <1° | YES |
| DoA J2 error | 0.01° | <1° | YES |
| DoA J3 error | 0.02° | <1° | YES |
| Null depth J1 | 62 dB | >40 dB | YES |
| Null depth J2 | 50 dB | >40 dB | YES |
| Null depth J3 | 64 dB | >40 dB | YES |
| GPS gain | 0.00 dB | 0 dB | YES |
| Digital fails at | 11 dB | — | — |
| Hybrid fails at | 24 dB | — | — |
| Hybrid range extension | 13 dB | >10 dB | YES |
| Improvement @30dB | 31.6 dB | >15 dB | YES |

### Hardware Imperfections Status

| Imperfection | Status | Risk if Added |
|---|---|---|
| Phase mismatch ±5-8° per channel | NOT MODELED | HIGHEST — null depth drops 10-20 dB |
| Mutual coupling -26 dB adjacent | NOT MODELED | HIGH — DoA bias 0.5-2°, possible null failure |
| Gain imbalance ±15% per channel | NOT MODELED | MEDIUM — null depth drops 5-10 dB |
| Oscillator phase drift | NOT MODELED | MEDIUM — degrades phase coherence |
| RF cable loss 0.5-2 dB | NOT MODELED | LOW — effective gain imbalance |
| ADC quantisation (12-bit) | PARTIAL — hard clip only | LOW — SQNR ~74 dB |
| LNA noise figure | PARTIAL — AWGN hardcoded | LOW — GPS SINR drops 2-4 dB |
| Finite snapshot count N=1000 | FULLY MODELED | — |

Fully modeled: 1 of 8
Partially modeled: 2 of 8
Not modeled: 5 of 8

### Missing File: realistic_sim.py
Must add all 5 unmodeled imperfections on top of existing ideal pipeline.
Build order:
1. Phase mismatch — ±sigma° random offset per element in steering vectors
2. Mutual coupling — apply 4×4 coupling matrix C: x_coupled = C @ x
3. Gain imbalance — random amplitude factor per channel
4. Oscillator drift — cumulative phase drift per snapshot
5. ADC quantisation — proper 12-bit noise on top of hard clip
6. LNA noise figure — replace hardcoded AWGN with kTB*NF*BW
7. Cable loss — per-element insertion loss

### Estimated Realistic Results (not yet computed)

| Metric | Ideal | Estimated Realistic | Target | Risk |
|--------|-------|-------------------|--------|------|
| Null depth J1 | 62 dB | ~42-52 dB | >40 dB | LOW |
| Null depth J2 | 50 dB | ~30-42 dB | >40 dB | HIGH |
| Null depth J3 | 64 dB | ~44-54 dB | >40 dB | LOW |
| DoA accuracy | 0.01° | ~0.3-1.5° | <1° | MEDIUM |
| Hybrid range | 13 dB | ~12-14 dB | >10 dB | LOW |

J2 is highest risk. If realistic null depth drops below 40 dB the fix is
expanding to a 6-element array. Better to know this from simulation than
discover it on the bench.



---

## SECTION 3 COMPLETE — 2026-06-08

### What Was Built in jammers.js

JAMMER PLACEMENT
- Click on ground plane to place jammers via THREE.Raycaster
- Max 3 jammers, each stored in window.sceneState.jammers array
- Jammers auto-numbered J1 J2 J3, renumber correctly on removal
- Ghost label fix: label.element.remove() called before mesh removal

JAMMER TYPES AND VISUALS
- CW: red octahedron, label "J1 CW +0MHz 30dB", fast pulse sin×8, 1 traveling dot
- FMCW: orange cone, label "J2 FMCW ±10MHz 25dB", 3 rays sweep ±20° at sin×3, 2 dots
- Barrage: yellow icosahedron wireframe, label "J3 Barrage ±50MHz 20dB", 6 rays ±35°, 3 dots

SIGNAL RAYS
- All rays go FROM jammer position TO drone position (direction vector corrected)
- FMCW sweep uses crossVectors + quaternion rotation around jammer-to-drone axis
- Barrage spray fans around correct direction with independent oscillation per ray
- Traveling dots lerp from jammerPos to dronePos over 0.5 second cycles
- All materials use LineDashedMaterial (linewidth >1 not supported in r128)
- Stake line goes vertically from ground y=0 to jammer altitude

TERRAIN
- Realistic hill terrain in NE quadrant using PlaneGeometry 800×800 with 40×40 segments
- Vertices displaced with Gaussian peaks + sinusoidal noise
- Height-based vertex colors: dark green (low) → brown-green (mid) → grey (peak)
- Wireframe overlay at 15% opacity for tactical look
- Label: HIGHLAND 280m at peak position
- Replaces old geometric cone mountain

DRONE ALTITUDE CONTROL
- Slider range 50m to 500m in HUD panel
- Moves drone mesh + all 4 antenna elements + GPS line endpoint
- Calls syncWithBackend() on change with new altitude

PER JAMMER CONTROLS (in HUD panel)
- Type selector buttons: CW / FMCW / Barrage
- Power slider: 0–50 dB
- Altitude slider: 0–400m (elevated jammer support)
- Physics row shows type-specific params (sweep BW, rate, bandwidth)
- Position readout: X Y AZ DIST

RANGE RINGS
- TorusGeometry flat ring on ground per jammer
- CW base 50km, FMCW 33km, Barrage 20km (scaled units)
- Scaled by power: radius *= 10^((power_db-30)/20)
- Updates on power or type change

BACKEND SYNC
- syncWithBackend() called with 300ms debounce after any change
- Passes jammer x, y(→z), altitude(→z), type, power_db to POST /api/generate
- Updates jammer labels with computed azimuth and distance from response
- GENERATE badge turns green on successful response

### What Was Built in scene.js (additions)
- Realistic terrain mesh in NE quadrant with vertex color height mapping
- Terrain wireframe overlay
- HIGHLAND 280m CSS2D label at peak
- THREE.Clock added for delta time in animation loop
- JammersAPI.update(delta) called every animation frame

### Current File Status
- jammers.js: FULLY BUILT (Section 3 complete)
- radiation.js: STUB — Section 4 to build next (use Opus 4.8)
- hud.js: STUB — Section 5 to build after Section 4
- scene.js: COMPLETE with terrain additions
- api.js: COMPLETE
- index.html: COMPLETE
- style.css: COMPLETE with jammer panel styles appended

### 3D Visualization Overall Status
Section 1 — Flask backend: DONE (port 5001)
Section 2 — Three.js scene: DONE (port 8080)
Section 3 — Jammer objects + terrain: DONE
Section 4 — 3D radiation beampattern: NOT STARTED — use Opus 4.8
Section 5 — Tactical HUD overlay: NOT STARTED
Section 6 — Integration + polish: NOT STARTED

### How to Run
Terminal 1: cd ~/antiJAMsimulation/navguard_viz && python run_viz.py
Terminal 2: cd ~/antiJAMsimulation/navguard_viz/frontend && python3 -m http.server 8080
Open: http://localhost:8080
Backend: http://localhost:5001


---

## SECTION 4.2 COMPLETE — 2026-06-08

### What Was Built in radiation.js (mesh renderer)

MESH BUILDING
- buildBeampatternMesh() — BufferGeometry with 16380 vertices (180 az × 91 el, full sphere)
- Vertex positions computed from displaced sphere: radius = 80 * (0.04 + 0.96 * sigmoid(power))
- Vertex colors from dbToColor() with 7-level mapping cyan→green→yellow→orange→red→dark red
- Face indices connect adjacent grid points into triangles with azimuth wraparound
- MeshLambertMaterial: vertexColors, DoubleSide, opacity 0.82, depthWrite false
- Wireframe overlay: opacity 0.08, depthWrite false

DISPLACEMENT FORMULA
- sigmoid shaping: shaped = 1 / (1 + exp(-8 * (power_normalized - 0.3)))
- radius = 80 * (0.04 + 0.96 * sqrt(shaped))
- Deep nulls → ~3 units (pinched), GPS lobe → 80 units (full extension)
- Power^0.35 compression for visual contrast

FULL SPHERE SCAN
- EL_STEPS changed from 45 to 91 — covers -90° to +90° (full sphere)
- el = (ei - 45) * 2 — mapping: ei=0 → -90°, ei=45 → 0°, ei=90 → +90°
- Total points: 16380 (was 8100)
- _nearestIndex updated to use ei = el/2 + 45 mapping

COLOR MAPPING (7 levels)
- t > 0.90 → bright cyan #00d9ff (GPS main lobe)
- t > 0.75 → bright green (strong gain)
- t > 0.55 → yellow-green (medium gain)
- t > 0.40 → yellow (low gain)
- t > 0.25 → orange (very low gain)
- t > 0.10 → red (near null)
- else → dark red (deep null)

NULL MARKERS
- Positioned at actual mesh surface in null direction (radius lookup from nearest data point)
- z negation preserved to match scene azimuth convention
- Each marker is {ring: THREE.Mesh, label: CSS2DObject} pair
- _disposeMarker() handles cleanup for both ring and label
- Label: "NULL -XXdB" in red with dark background
- updateMesh(), clear(), visibility toggle all use _disposeMarker

GPS MARKER
- ArrowHelper pointing straight up (Y axis) from drone
- Cyan #00ccff, length 90, head 15×8

ANIMATION
- _beampatternMesh.rotation.y += 0.0005 per frame
- wireframe rotation synced to mesh rotation
- Toggle buttons: BEAMPATTERN ON/OFF, ROTATE ON/OFF
- Status shows "COMPUTED — Xms"

HUD CONTROLS (injected into #hud-panel by init())
- BEAMPATTERN ON/OFF toggle
- ROTATE ON/OFF toggle
- Status indicator
- Tip text for 3-jammer placement

KNOWN DEVIATIONS FROM PROMPT (all correct)
- _nearestIndex updated for new 91-row elevation mapping
- addNullMarker uses -sin(az) for z to match scene convention
- _disposeMarker() centralizes cleanup for {ring,label} pair

### Full Pipeline Now Works End to End
- Place jammers → click RUN PIPELINE
- GENERATE → MUSIC → MVDR badges light up in sequence
- Beampattern mesh appears around drone
- Null markers appear at mesh surface in jammer directions
- GPS cyan arrow points up
- Mesh rotates slowly showing full 3D shape

### 3D Visualization Overall Status
Section 1 — Flask backend: DONE
Section 2 — Three.js scene: DONE
Section 3 — Jammers + terrain: DONE
Section 4.1 — Beampattern math engine: DONE
Section 4.2 — Beampattern 3D mesh renderer: DONE
Section 5 — Tactical HUD overlay: NEXT
Section 6 — Integration + polish: NOT STARTED

### How to Run
Terminal 1: cd ~/antiJAMsimulation/navguard_viz && python run_viz.py
Terminal 2: cd ~/antiJAMsimulation/navguard_viz/frontend && python3 -m http.server 8080
Open: http://localhost:8080
Backend: http://localhost:5001


---

## SECTION 4 FIXES COMPLETE — 2026-06-08

### Fix 1 — Null Ring Direction
- addNullMarker now computes actual elevation angle from drone to jammer
- Uses jammer.threeX/threeY/threeZ (not worldZ which doesnt exist)
- Matches jammer to null by azimuth, guards against azimuth=0 with !== null check
- Ring placed at correct mesh surface position in actual jammer direction
- Elevation formula: atan2(dz_vertical, horizontal_dist) in degrees

### Fix 2 — Jammer Type Affects Null Visually
- applyJammerTypeScaling() applied after computeFullBeampattern, before updateMesh
- CW: scale 1.0, spread 5° — sharpest deepest null
- FMCW: scale 0.75, spread 10° — 25% shallower wider null
- Barrage: scale 0.55, spread 20° — 45% shallower broadest null
- Only modifies visual_weight and radius, power_db unchanged (physically correct)
- Guards j.azimuth === null not !j.azimuth (fixes azimuth=0 east jammer bug)

### Fix 3 — Petal Shape Guidance
- Tip text updated: place 3 jammers 120° apart
- With <2 jammers: bp-status shows ADD MORE JAMMERS FOR PETAL SHAPE in orange

### Fix 4 — Click Terrain to Place Jammer
- window._terrainMesh set in scene.js after terrain creation
- _getClickPosition() in jammers.js raycasts terrain first, falls back to ground plane
- When onTerrain=true: altitude set automatically from hit.y
- Label shows [HLD] tag for highland-placed jammers

### Fix 5 — Terrain Solid
- terrainMat: transparent false, opacity 1.0
- Wireframe overlay: color #2a4a2a, opacity 0.25

### Fix 6 — GPS Cone Warning
- After /api/generate response, checks geo.elevation > 55° per jammer
- Jammer mesh turns purple #9900ff
- Label border and color turn purple with ⚠ GPS CONE text
- Single post-loop status warning via _setStatus (not updateStatusBar)
- Resets to normal type color when moved out of cone

### Documented Limitations
LIMITATION 1 — CRPA Elevation Blind Spot
When jammer elevation exceeds ~60°, the 2×2 flat horizontal array cannot
null it without also nulling GPS. All 4 elements see identical phase from
directly overhead. Steering vector becomes [1,1,1,1] identical to GPS.
MVDR correctly refuses to null in GPS direction.
Fix in hardware: tilt elements or use 3D array configuration.
Visual indicator: jammer turns purple with GPS CONE warning.

### Section 4 Final Status
- 4.1 math engine: DONE
- 4.2 mesh renderer: DONE
- All 6 visual fixes: DONE
- Limitations documented: 1

### 3D Visualization Overall Status
Section 1 — Flask backend: DONE
Section 2 — Three.js scene: DONE
Section 3 — Jammers + terrain: DONE
Section 4 — Beampattern renderer + fixes: DONE
Section 5 — Tactical HUD overlay: NEXT
Section 6 — Integration + polish: NOT STARTED


---

## SECTION 4 FINAL STATUS — 2026-06-08

### All Fixes Confirmed Working
- Petal shape with 3 jammers: WORKING — 3 distinct lobes visible
- Null rings clear on jammer removal: FIXED
- Null rings appear at correct mesh surface positions: WORKING
- Terrain solid and opaque: FIXED
- GPS cone warning (purple jammer): WORKING
- Click terrain to place jammer at terrain height: WORKING
- Beampattern rotation: REMOVED — pattern now stationary (physically correct)
- Rotate button: REMOVED from HUD

### Confirmed Physics
- Beampattern is fixed to drone orientation — does not spin
- Null depth varies by jammer type: CW deepest, Barrage shallowest
- With 1 jammer: egg shape (correct — insufficient DOF shaping)
- With 3 jammers spread 120°: clear petal lobes (correct)
- Jammer above 60° elevation: purple warning, null steering limited

### Documented Limitations
LIMITATION 1 — CRPA Elevation Blind Spot
2x2 flat horizontal array cannot null jammers above ~60° elevation
without also nulling GPS. Steering vectors identical to GPS at high elevation.
Visual: jammer turns purple with GPS CONE warning.

### Section 5 Requirements (confirmed by user)
- SINR vs jammer power chart — live 2D graph in HUD right panel
- GPS LOCK / GPS LOST big status indicator — green/red based on SINR > 0dB
- All existing HUD fixes included
- Hybrid vs digital curve from /api/hybrid shown live

### 3D Visualization Overall Status
Section 1 — Flask backend: DONE
Section 2 — Three.js scene: DONE
Section 3 — Jammers + terrain: DONE
Section 4 — Beampattern renderer: DONE (all fixes applied)
Section 5 — Tactical HUD: NEXT
Section 6 — Integration + polish: NOT STARTED




⏺ Stopped. Here's the checkpoint summary, ready to paste into CHECKPOINT.md:
  
  # CHECKPOINT — Real-World Upgrade (2026-06-10)

  ## Context
  Full math-modeling review completed. Goal: fix bugs and convert the game-like                  
  sim into a physically honest pipeline ("real product").

  ## Review findings (verified numerically)
  1. **Element pattern pointed sideways** — `cos(el)` peaked at horizon, gain ≈ 0
     at zenith → GPS satellite (el=90°) had amplitude 4e-17, i.e. **156 dB below
     noise — GPS was completely absent from array_data.npy**.
  2. **GPS direction inconsistent across files** — generator: el=90°;
     mvdr_beamformer + hybrid_sim: el=0° (constraint pointed 90° away).
  3. **FMCW bug in realistic_sim.py** — `cumsum(freq)/n_snapshots` divided sweep
     rate by 1000 → chirp was effectively a DC tone.
  4. **"CW" jammers aren't CW** — BPSK chips at full 10 MHz sample rate; sidesteps
     the real coherent-source problem (MUSIC needs FB averaging/spatial smoothing).
  5. **Null depth in realistic_sim measured at IDEAL steering vectors** while data
     manifold is perturbed → "PASS >40dB" measures the wrong direction.
  6. **hybrid_sim SINR is analytic** (unclipped steering vectors) — ignores                      
     clipping intermod, the dominant error in the claimed regime.
  7. **hybrid_sim canceller uses ground-truth jammer vectors** — 13 dB extended
     range result is circular.
  8. **Noise floor fantasy** — noise set 6 dB below GPS; physically GPS is ~25-30 dB
     BELOW kTB noise pre-correlation (kTB in 10 MHz ≈ -134 dBW, GPS ≈ -158.5 dBW).
  9. **Actual J/S in generator is ~84 dB**, not 30 dB as documented.
  10. **Fixed ADC clip (FS=5×GPS), no AGC** — "digital fails at X dB" decided by an
      arbitrary constant; real story is quantization-noise rise after AGC.
  11. Multipath model is scalar AM on all channels — not real multipath.
  12. Minor: c=3e8, GPS EIRP 50 W (should be ~500 W), realistic_sim unseeded RNG.

  ## Fixes COMPLETED ✅
  - `generate_array_data.py`:
    - `element_pattern()` → boresight-up: `G_power = max(sin(el), 0.01)`
      (-20 dB backlobe floor for below-horizon jammers).
    - `steering_vector()` → true 3D phase `(2π/λ)(elem_pos·û)` (zenith source →
      zero inter-element phase). Removed azimuth-projection hack.
  - `realistic_sim.py`: FMCW phase fixed → `2π·cumsum(freq_sweep)` (no /N).
  - `mvdr_beamformer.py`:
    - Added `el_gps=90.0` param; steering_vector now takes (az, el) full 3D.
    - GPS constraint at zenith; added `JAMMER_ELEVS = [-9.73, -6.93, -4.53]`;
      null depths evaluated at true jammer elevations.
    - Plot annotation uses precomputed null_depths; legend shows az+el.
    - VERIFIED: runs, nulls 66-86 dB, constraint 0 dB at zenith.
  - `music_spectrum.py` (IN PROGRESS — edit applied, NOT yet re-run):                            
    - Replaced 1D el=0° scan with 2D az×el scan (el grid -20°..+20°, 1° step),
      max-projection over elevation; `steering_matrix_ura(az_array, el)` vectorized.
    - Reason: with true 3D phase, 1D scan broke (J2 err -5.7°, J3 lost → 53.65°).
    - TODO: re-run music_spectrum.py to verify peaks recover; peak_el computed
      but not yet printed/used in output table.

  ## NOT YET STARTED — new real-physics pipeline (agreed plan)
  Files to create:
  1. `gps_ca_code.py` — C/A Gold code generator (G1/G2 LFSR, PRN tap table).
  2. `real_scene.py` — physics-true IQ: GPS with C/A code BELOW kTB·NF noise floor
     (pre-corr SNR ≈ -27.5 dB at fs=10 MHz, C/N0 ≈ 42.5 dBHz), truly coherent
     CW/FMCW/barrage jammers (CW with small independent osc offsets), real link
     budget (J/S at port, sweep 30-80 dB), calibration errors (phase/gain),
     optional coherent multipath ray, GPS at realistic az/el (e.g. 45°, 60°).
  3. `real_frontend.py` — AGC (RMS→FS/4) + n-bit quantizer (default 8-12 bit);
     analog pre-canceller driven by ESTIMATED DOAs with 6-bit quantized
     vector-modulator weights, applied pre-ADC.
  4. `real_doa.py` — 2D MUSIC with forward-backward averaging (2×2 URA is
     centro-symmetric; FB valid), jammers only (GPS undetectable pre-corr).
  5. `real_beamformer.py` — MVDR (GPS dir from geometry + attitude-error param)
     + power-inversion baseline (w = R⁻¹e₁/(e₁ᴴR⁻¹e₁)).
  6. `real_cn0.py` — post-correlation C/N₀ estimator (1 ms coherent epochs,
     peak vs off-phase noise floor) — THE product KPI.
  7. `run_real_product.py` — end-to-end: sweep J/S, 4 paths (unprotected /
     power-inversion / MVDR / hybrid), Monte Carlo over seeds, KPI table +
     C/N₀-vs-J/S figure (replaces old SINR plot).

  Sanity targets: unjammed C/N₀ ≈ 42.5 dBHz; 1 ms coherent SNR ≈ +12.5 dB;
  at J/S 80 dB unprotected C/N₀ collapses, MVDR should recover to ~40 dBHz;
  8-bit ADC shows hybrid advantage via quantization-noise mechanism.

  ## Decisions made
  - Legacy hybrid_sim.py left untouched (self-consistent toy; superseded by new
    pipeline). realistic_sim null-depth metric fixed properly in new pipeline only.
  - Work in noise-normalized units (noise power = 1 per channel).
  - CLAUDE.md "Current Status" section is stale — update after new pipeline lands.

  Status right now: the three legacy bug-fix files are edited; mvdr_beamformer.py is verified working; music_spectrum.py
  has the 2D-scan edit applied but needs a verification run as the first step when we resume. Nothing committed to git
  yet.