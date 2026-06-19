'use strict';
/**
 * scene.js — Three.js 3D scene for NAVGUARD anti-jam visualization.
 *
 * Coordinate system mapping (backend → Three.js):
 *   backend X  →  Three.js  X  (East)
 *   backend Y  →  Three.js -Z  (South becomes -Z so North is -Z direction)
 *   backend Z  →  Three.js  Y  (altitude = up)
 *
 * Scale: 1 unit ≈ 1 metre.  GPS satellite placed at Y=800 (real: 20,200 km).
 */

/* ── Shared scene state (read by all modules) ──────────────── */
window.sceneState = {
  drone:           { x: 0, y: 0, z: 0, altitude: 100 },
  jammers:         [],
  antennaElements: [],
  gpsObject:       null,
  droneObject:     null,
  beampatternMesh: null,
  scenario_id:     null,
  isRunning:       false,
  currentStep:     'idle',
};

/* ── SceneAPI IIFE ─────────────────────────────────────────── */
window.SceneAPI = (function () {

  /* module-level refs */
  let scene, camera, renderer, labelRenderer, controls;
  let animating = false;
  let gpsLine   = null;   // ref for altitude-update endpoint patching
  const highlights    = [];
  const jammerObjects = [];
  const clock         = new THREE.Clock();

  const DRONE_POS = new THREE.Vector3(0, 100, 0);
  const GPS_POS   = new THREE.Vector3(0, 800, 0);

  /* ── helpers ─────────────────────────────────────────────── */

  function makeLabel(text, cssClass) {
    const div       = document.createElement('div');
    div.textContent = text;
    div.className   = 'scene-label' + (cssClass ? ' ' + cssClass : '');
    return new THREE.CSS2DObject(div);
  }

  /* ── scene builders ──────────────────────────────────────── */

  function buildGrid() {
    // 2 km × 2 km ground grid, 40 divisions (50 m cells)
    const grid = new THREE.GridHelper(2000, 40, 0x1a3a1a, 0x1a3a1a);
    scene.add(grid);
  }

  function buildDrone() {
    // Main body — white sphere
    const body = new THREE.Mesh(
      new THREE.SphereGeometry(3, 12, 12),
      new THREE.MeshPhongMaterial({ color: 0xffffff })
    );
    body.position.copy(DRONE_POS);
    scene.add(body);
    window.sceneState.droneObject = body;

    // "DRONE" label
    const lbl = makeLabel('DRONE', '');
    lbl.position.set(0, 10, 0);
    body.add(lbl);

    // 2×2 URA antenna elements — cyan spheres
    // Spacing exaggerated ×100 for visibility (real: ~9.5 cm → 9.5 units)
    // Offsets in Three.js local space: (X = East, Z = South)
    const antMat  = new THREE.MeshPhongMaterial({ color: 0x00ccff, emissive: 0x003344 });
    const antGeom = new THREE.SphereGeometry(1.5, 8, 8);

    [[-5, 0, -5], [5, 0, -5], [-5, 0, 5], [5, 0, 5]].forEach(([ox, oy, oz]) => {
      const el = new THREE.Mesh(antGeom, antMat.clone());
      el.position.set(DRONE_POS.x + ox, DRONE_POS.y + oy, DRONE_POS.z + oz);
      scene.add(el);
      window.sceneState.antennaElements.push(el);
    });
  }

  function buildGPS() {
    // GPS satellite — cyan octahedron
    const gps = new THREE.Mesh(
      new THREE.OctahedronGeometry(8),
      new THREE.MeshPhongMaterial({ color: 0x00ccff })
    );
    gps.position.copy(GPS_POS);
    scene.add(gps);
    window.sceneState.gpsObject = gps;

    // Label
    const lbl = makeLabel('GPS SAT', 'cyan');
    lbl.position.set(0, 15, 0);
    gps.add(lbl);

    // Dashed line GPS → drone
    const geom = new THREE.BufferGeometry().setFromPoints([GPS_POS.clone(), DRONE_POS.clone()]);
    const mat  = new THREE.LineDashedMaterial({
      color:       0x00ccff,
      opacity:     0.3,
      transparent: true,
      dashSize:    15,
      gapSize:     10,
    });
    gpsLine = new THREE.Line(geom, mat);
    gpsLine.computeLineDistances();
    scene.add(gpsLine);
  }

  function buildTerrain() {
    const geo = new THREE.PlaneGeometry(800, 800, 40, 40);
    geo.rotateX(-Math.PI / 2);

    // Displace Y of each vertex to form natural hill shapes
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      const peak1 = 280 * Math.exp(-((x - 100) ** 2 + (z + 150) ** 2) / (2 * 120 ** 2));
      const peak2 = 180 * Math.exp(-((x + 80)  ** 2 + (z + 50)  ** 2) / (2 * 80  ** 2));
      const bump1 =  60 * Math.exp(-((x - 200) ** 2 + (z + 200) ** 2) / (2 * 60  ** 2));
      const bump2 =  40 * Math.exp(-((x - 50)  ** 2 + (z + 250) ** 2) / (2 * 50  ** 2));
      const noise =  15 * Math.sin(x * 0.05) * Math.cos(z * 0.04)
                  +   8 * Math.sin(x * 0.12) * Math.cos(z * 0.09);
      pos.setY(i, Math.max(0, peak1 + peak2 + bump1 + bump2 + noise));
    }
    geo.computeVertexNormals();

    // Height-based vertex colours
    const cols = new Float32Array(pos.count * 3);
    for (let i = 0; i < pos.count; i++) {
      const h  = pos.getY(i);
      const ci = i * 3;
      if      (h < 20)  { cols[ci] = 0.08; cols[ci+1] = 0.15; cols[ci+2] = 0.08; }
      else if (h < 100) { cols[ci] = 0.12; cols[ci+1] = 0.18; cols[ci+2] = 0.10; }
      else if (h < 200) { cols[ci] = 0.15; cols[ci+1] = 0.14; cols[ci+2] = 0.10; }
      else              { cols[ci] = 0.20; cols[ci+1] = 0.18; cols[ci+2] = 0.16; }
    }
    geo.setAttribute('color', new THREE.BufferAttribute(cols, 3));

    const terrain = new THREE.Mesh(geo,
      new THREE.MeshLambertMaterial({
        vertexColors: true,
        side:         THREE.FrontSide,
        transparent:  false,   // fully solid — jammers raycast against this
        opacity:      1.0,
      }));
    terrain.position.set(500, 0, -400);
    scene.add(terrain);

    // Expose for terrain raycasting in jammers.js (click-to-place at terrain height)
    window._terrainMesh = terrain;
    window._terrainMesh.userData.isGround = true;

    // Tactical wireframe overlay
    const wire = new THREE.Mesh(geo.clone(),
      new THREE.MeshBasicMaterial({ color: 0x2a4a2a, wireframe: true, opacity: 0.25, transparent: true }));
    wire.position.copy(terrain.position);
    scene.add(wire);

    // Highland label above the main peak
    const lbl = makeLabel('HIGHLAND 280m', 'compass');
    lbl.position.set(560, 285, -560);
    scene.add(lbl);
  }

  function buildAxesAndCompass() {
    // Small XYZ axes at ground origin
    scene.add(new THREE.AxesHelper(50));

    // Compass labels at 200 m radius on ground plane
    // North = -Z, East = +X, South = +Z, West = -X (in Three.js coords)
    [
      { text: 'N', x:    0, z: -200 },
      { text: 'E', x:  200, z:    0 },
      { text: 'S', x:    0, z:  200 },
      { text: 'W', x: -200, z:    0 },
    ].forEach(({ text, x, z }) => {
      const lbl = makeLabel(text, 'compass');
      lbl.position.set(x, 1, z);
      scene.add(lbl);
    });
  }

  /* ── public API ──────────────────────────────────────────── */
  return {

    /**
     * Initialise Three.js scene and attach to the given container element.
     * @param {string} containerId  id of the DOM element to mount into
     */
    init(containerId) {
      const container = document.getElementById(containerId);
      const W = container.clientWidth  || Math.round(window.innerWidth  * 0.7);
      const H = container.clientHeight || Math.round(window.innerHeight - 70);

      /* Scene */
      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0a0a0a);

      /* Camera */
      camera = new THREE.PerspectiveCamera(60, W / H, 1, 10000);
      camera.position.set(300, 400, 500);
      camera.lookAt(DRONE_POS);

      /* WebGL renderer */
      renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(W, H);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      container.appendChild(renderer.domElement);

      /* CSS2D label renderer (overlay div, no mouse events) */
      labelRenderer = new THREE.CSS2DRenderer();
      labelRenderer.setSize(W, H);
      Object.assign(labelRenderer.domElement.style, {
        position:      'absolute',
        top:           '0',
        left:          '0',
        pointerEvents: 'none',
      });
      container.appendChild(labelRenderer.domElement);

      /* OrbitControls */
      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.target.copy(DRONE_POS);
      controls.minDistance    = 50;
      controls.maxDistance    = 2000;
      controls.enableDamping  = true;
      controls.dampingFactor  = 0.05;
      controls.update();

      /* Lighting */
      scene.add(new THREE.AmbientLight(0xffffff, 0.4));
      const dir = new THREE.DirectionalLight(0xffffff, 0.8);
      dir.position.set(200, 500, 200);
      scene.add(dir);

      /* Content */
      buildGrid();
      buildDrone();
      buildGPS();
      buildAxesAndCompass();
      buildTerrain();

      /* Resize handler */
      window.addEventListener('resize', () => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        if (!w || !h) return;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
        labelRenderer.setSize(w, h);
      });

      this.animate();
    },

    /** Start the render loop (safe to call multiple times — only one loop runs). */
    animate() {
      if (animating) return;
      animating = true;

      const loop = () => {
        requestAnimationFrame(loop);
        const dt = clock.getDelta();

        if (controls) controls.update();

        // Spin GPS satellite
        if (window.sceneState.gpsObject) {
          window.sceneState.gpsObject.rotation.y += 0.005;
        }

        // Drive jammer signal-ray animations
        if (window.JammersAPI && window.JammersAPI.update) {
          window.JammersAPI.update(dt);
        }

        // Drive beampattern mesh rotation
        if (window.RadiationAPI && window.RadiationAPI.update) {
          window.RadiationAPI.update(dt);
        }

        renderer.render(scene, camera);
        if (labelRenderer) labelRenderer.render(scene, camera);
      };

      loop();
    },

    /**
     * Add a jammer marker to the scene.
     * @param {object} jammer  {x, y, z, type, power_db, …} in backend coordinates
     * @returns {number}       index of the added jammer object
     */
    addJammer(jammer) {
      // Coordinate mapping: backend (x, y, z_alt) → Three.js (x, z_alt, -y)
      const pos = new THREE.Vector3(
        jammer.x || 0,
        jammer.z || 0,       // altitude (0 for ground jammers)
        -(jammer.y || 0)     // backend Y → Three.js -Z
      );

      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(8, 8, 8),
        new THREE.MeshPhongMaterial({ color: 0xff3300, emissive: 0x220000 })
      );
      mesh.position.copy(pos);

      const lbl = makeLabel(`JAM${jammerObjects.length + 1}`, 'jammer');
      lbl.position.set(0, 14, 0);
      mesh.add(lbl);

      scene.add(mesh);
      jammerObjects.push(mesh);
      window.sceneState.jammers.push({ ...jammer, _mesh: mesh });

      return jammerObjects.length - 1;
    },

    /**
     * Remove a jammer marker from the scene by index.
     * @param {number} index
     */
    removeJammer(index) {
      if (index < 0 || index >= jammerObjects.length) return;
      scene.remove(jammerObjects[index]);
      jammerObjects.splice(index, 1);
      window.sceneState.jammers.splice(index, 1);
    },

    /**
     * Briefly pulse antenna elements to signal new data.
     * @param {object} _data  (reserved for future animation data)
     */
    updateAntennaElements(_data) {
      window.sceneState.antennaElements.forEach(el => {
        el.material.emissive.setHex(0x00ccff);
        el.material.emissiveIntensity = 1.0;
        setTimeout(() => { el.material.emissiveIntensity = 0.05; }, 450);
      });
    },

    /**
     * Draw a directional ray from drone at the given azimuth.
     * Azimuth convention matches backend: 0° = East (+X), 90° = North (-Z).
     * @param {number} angle_deg  azimuth in degrees
     */
    highlightAngle(angle_deg) {
      const az  = THREE.MathUtils.degToRad(angle_deg);
      const len = 420;
      const end = new THREE.Vector3(
        DRONE_POS.x + Math.cos(az) * len,
        DRONE_POS.y,
        DRONE_POS.z - Math.sin(az) * len   // -sin because North = -Z
      );
      const geom = new THREE.BufferGeometry().setFromPoints([DRONE_POS.clone(), end]);
      const mat  = new THREE.LineBasicMaterial({
        color:       0xffff00,
        opacity:     0.75,
        transparent: true,
      });
      const line = new THREE.Line(geom, mat);
      scene.add(line);
      highlights.push(line);
    },

    /** Remove all angle highlight rays. */
    clearHighlights() {
      highlights.forEach(h => scene.remove(h));
      highlights.length = 0;
    },

    /**
     * Move the drone, antennas, and GPS line endpoint to a new altitude.
     * Called by JammersAPI when the drone-altitude slider changes.
     * @param {number} alt  new altitude in metres (Three.js Y units)
     */
    setDroneAltitude(alt) {
      DRONE_POS.y = alt;
      window.sceneState.drone.altitude = alt;

      // Move drone body
      if (window.sceneState.droneObject) {
        window.sceneState.droneObject.position.y = alt;
      }

      // Move antenna elements (all have oy=0 so y=alt exactly)
      window.sceneState.antennaElements.forEach(el => {
        el.position.y = alt;
      });

      // Patch GPS dashed line endpoint (index 1 = drone end)
      if (gpsLine) {
        const pos = gpsLine.geometry.attributes.position;
        pos.setXYZ(1, 0, alt, 0);
        pos.needsUpdate = true;
        gpsLine.geometry.computeBoundingSphere();
        gpsLine.computeLineDistances();
      }
    },

    getScene()    { return scene;    },
    getCamera()   { return camera;   },
    getRenderer() { return renderer; },
  };

})();
