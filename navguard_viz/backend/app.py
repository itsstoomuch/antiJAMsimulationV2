"""
app.py — NAVGUARD visualization Flask backend.

Six REST endpoints that drive the 3-D interactive front-end:
  POST /api/generate  — generate IQ data for a jammer scenario
  POST /api/music     — MUSIC DOA estimation
  POST /api/mvdr      — MVDR null-steering beamformer
  POST /api/hybrid    — hybrid analog-digital SINR sweep
  GET  /api/config    — static system configuration
  POST /api/reset     — clear a stored scenario

Existing simulation files (generate_array_data.py, music_spectrum.py, …) are
imported opportunistically.  If their signatures do not match the parametric
API expected here, or if import fails for any reason, app.py falls back to
core.py transparently.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import numpy as np
import uuid
import os
import sys
import time
import traceback as _tb

# Add backend directory to path so existing simulation files are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core

# ---------------------------------------------------------------------------
# Opportunistic imports of existing simulation files
# ---------------------------------------------------------------------------

_existing_gen   = None
_existing_music = None
_existing_mvdr  = None
_existing_hyb   = None

try:
    from generate_array_data import generate_array_data as _existing_gen
    print("[navguard] Loaded: generate_array_data.generate_array_data")
except Exception as _e:
    print(f"[navguard] Warning – could not import generate_array_data: {_e}")

try:
    from music_spectrum import music_spectrum as _existing_music
    print("[navguard] Loaded: music_spectrum.music_spectrum")
except Exception as _e:
    print(f"[navguard] Warning – could not import music_spectrum: {_e}")

try:
    from mvdr_beamformer import mvdr_beamformer as _existing_mvdr
    print("[navguard] Loaded: mvdr_beamformer.mvdr_beamformer")
except Exception as _e:
    print(f"[navguard] Warning – could not import mvdr_beamformer: {_e}")

try:
    from hybrid_sim import hybrid_sim as _existing_hyb
    print("[navguard] Loaded: hybrid_sim.hybrid_sim")
except Exception as _e:
    print(f"[navguard] Warning – could not import hybrid_sim: {_e}")

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)
CORS(app)

# In-memory scenario store  {scenario_id: {...}}
scenarios: dict = {}


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def numpy_to_python(obj):
    """Recursively convert numpy scalars / arrays to plain Python types."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.complexfloating):
        return {"real": float(obj.real), "imag": float(obj.imag)}
    if isinstance(obj, np.ndarray):
        return [numpy_to_python(i) for i in obj]
    if isinstance(obj, dict):
        return {k: numpy_to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [numpy_to_python(i) for i in obj]
    return obj


def _err(message: str, exc: Exception = None) -> tuple:
    body = {
        "success":   False,
        "error":     message,
        "traceback": _tb.format_exc() if exc is not None else "",
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Endpoint 1 — POST /api/generate
# ---------------------------------------------------------------------------

@app.route("/api/generate", methods=["POST"])
def api_generate():
    """
    Generate IQ data for a user-defined jammer scenario.

    Request JSON
    ------------
    jammers        : list of {x, y, z, type, power_db}
    drone_altitude : metres (default 100)
    n_snapshots    : IQ samples per channel (default 1000)
    """
    try:
        data         = request.get_json(force=True)
        jammers      = data.get("jammers", [])
        drone_alt    = float(data.get("drone_altitude", core.DRONE_ALT))
        n_snapshots  = int(data.get("n_snapshots", 1000))
        drone_pos    = [0.0, 0.0, drone_alt]

        # Compute geometry for each jammer
        geometries = []
        for k, jammer in enumerate(jammers):
            xyz = [float(jammer["x"]), float(jammer["y"]), float(jammer["z"])]
            az, el, dist, pl = core.jammer_geometry(xyz, drone_pos)
            geometries.append({
                "index":        k,
                "azimuth":      az,
                "elevation":    el,
                "distance":     dist,
                "path_loss_db": pl,
                "type":         jammer.get("type", "CW"),
                "power_db":     float(jammer.get("power_db", 30)),
            })

        # Generate IQ matrix using core.py (existing generate_array_data.py
        # has hardcoded geometry so we use our parametric version here)
        X = core.generate_iq_data(jammers, drone_pos=drone_pos,
                                  n_snapshots=n_snapshots)

        scenario_id = str(uuid.uuid4())
        scenarios[scenario_id] = {
            "X":             X,
            "jammers":       jammers,
            "geometries":    geometries,
            "drone_pos":     drone_pos,
            "music_result":  None,
            "mvdr_result":   None,
            "hybrid_result": None,
            "created_at":    time.time(),
        }

        antenna_positions = [
            {
                "index": i,
                "x": float(core.ELEM_POS[i, 0]),
                "y": float(core.ELEM_POS[i, 1]),
                "z": float(core.ELEM_POS[i, 2]),
            }
            for i in range(4)
        ]

        response = {
            "success":           True,
            "scenario_id":       scenario_id,
            "array_shape":       list(X.shape),
            "jammer_geometries": geometries,
            "gps_direction":     {"azimuth": 0.0, "elevation": 90.0},
            "antenna_positions": antenna_positions,
        }
        return jsonify(numpy_to_python(response))

    except Exception as exc:
        return _err(f"generate failed: {exc}", exc)


# ---------------------------------------------------------------------------
# Endpoint 2 — POST /api/music
# ---------------------------------------------------------------------------

@app.route("/api/music", methods=["POST"])
def api_music():
    """
    Run MUSIC DOA estimation on a stored scenario.

    Request JSON
    ------------
    scenario_id : string
    n_jammers   : number of jammers to locate (default 3)
    """
    try:
        data        = request.get_json(force=True)
        sid         = data.get("scenario_id", "")
        n_jammers   = int(data.get("n_jammers", 3))

        if sid not in scenarios:
            return _err(f"scenario_id '{sid}' not found – call /api/generate first")

        X = scenarios[sid]["X"]
        R = core.compute_covariance(X)
        result = core.compute_music(R, n_sources=n_jammers)

        scenarios[sid]["music_result"] = result

        response = {
            "success":              True,
            "detected_angles":      result["detected_angles"],
            "pseudospectrum":       result["pseudospectrum"],
            "eigenvalues":          result["eigenvalues"],
            "snr_gap":              result["snr_gap"],
            "signal_subspace_size": result["signal_subspace_size"],
            "noise_subspace_size":  result["noise_subspace_size"],
        }
        return jsonify(numpy_to_python(response))

    except Exception as exc:
        return _err(f"music failed: {exc}", exc)


# ---------------------------------------------------------------------------
# Endpoint 3 — POST /api/mvdr
# ---------------------------------------------------------------------------

@app.route("/api/mvdr", methods=["POST"])
def api_mvdr():
    """
    Run MVDR null-steering beamformer on a stored scenario.

    Request JSON
    ------------
    scenario_id   : string
    jammer_angles : list of azimuth degrees (from MUSIC output)
    gps_azimuth   : degrees (default 0.0)
    gps_elevation : degrees (default 90.0 = directly overhead)
    """
    try:
        data          = request.get_json(force=True)
        sid           = data.get("scenario_id", "")
        jammer_angles = data.get("jammer_angles", [])
        gps_az        = float(data.get("gps_azimuth",   0.0))
        gps_el        = float(data.get("gps_elevation", 90.0))

        if sid not in scenarios:
            return _err(f"scenario_id '{sid}' not found – call /api/generate first")

        X = scenarios[sid]["X"]
        R = core.compute_covariance(X)
        result = core.compute_mvdr(R, gps_az=gps_az, gps_el=gps_el,
                                   jammer_angles=jammer_angles)

        # Compute rms_reduction_db from rms_before / rms_after
        rms_before = result["rms_before"]
        rms_after  = result["rms_after"]
        rms_red_db = float(core.linear_to_db(rms_before / max(rms_after, 1e-100)))

        scenarios[sid]["mvdr_result"] = result

        response = {
            "success":          True,
            "weights":          result["weights"],
            "beampattern":      result["beampattern"],
            "null_depths":      result["null_depths"],
            "gps_gain_db":      result["gps_gain_db"],
            "rms_before":       rms_before,
            "rms_after":        rms_after,
            "rms_reduction_db": rms_red_db,
        }
        return jsonify(numpy_to_python(response))

    except Exception as exc:
        return _err(f"mvdr failed: {exc}", exc)


# ---------------------------------------------------------------------------
# Endpoint 4 — POST /api/hybrid
# ---------------------------------------------------------------------------

@app.route("/api/hybrid", methods=["POST"])
def api_hybrid():
    """
    Sweep jammer power and compare digital vs hybrid MVDR SINR curves.

    Request JSON
    ------------
    scenario_id   : string (stored, but hybrid uses its own fixed geometry)
    alpha_pre     : analog pre-cancel fraction, 0–1 (default 0.9)
    adc_fullscale : ADC clipping level (default 5.0)
    n_points      : sweep resolution, 0–50 dB (default 50)
    """
    try:
        data          = request.get_json(force=True)
        sid           = data.get("scenario_id", "")
        alpha_pre     = float(data.get("alpha_pre",     0.9))
        adc_fullscale = float(data.get("adc_fullscale", core.ADC_FULLSCALE_DEFAULT))
        n_points      = int(data.get("n_points",        50))

        result = core.compute_hybrid_curve(
            alpha_pre=alpha_pre,
            adc_fullscale=adc_fullscale,
            n_points=n_points,
        )

        if sid in scenarios:
            scenarios[sid]["hybrid_result"] = result

        response = {
            "success":             True,
            "jammer_powers_db":    result["jammer_powers_db"],
            "sinr_digital":        result["sinr_digital"],
            "sinr_hybrid":         result["sinr_hybrid"],
            "sinr_ideal":          result["sinr_ideal"],
            "digital_fails_at_db": result["digital_fails_at_db"],
            "hybrid_fails_at_db":  result["hybrid_fails_at_db"],
            "improvement_at_30db": result["improvement_at_30db"],
            "advantage_db":        result["advantage_db"],
        }
        return jsonify(numpy_to_python(response))

    except Exception as exc:
        return _err(f"hybrid failed: {exc}", exc)


# ---------------------------------------------------------------------------
# Endpoint 5 — GET /api/config
# ---------------------------------------------------------------------------

@app.route("/api/config", methods=["GET"])
def api_config():
    """Return static system configuration for the front-end."""
    return jsonify({
        "freq_hz":               int(core.FREQ_GPS),
        "lambda_m":              round(core.LAMBDA, 4),
        "element_spacing_m":     round(core.D_ELEMENT, 5),
        "array_layout":          "2x2_URA",
        "n_elements":            4,
        "gps_power_dbw":         core.GPS_POWER_DBW,
        "drone_altitude_m":      core.DRONE_ALT,
        "max_jammers":           3,
        "jammer_types":          ["CW", "FMCW", "Barrage"],
        "default_alpha_pre":     0.9,
        "default_adc_fullscale": core.ADC_FULLSCALE_DEFAULT,
        "default_n_snapshots":   1000,
    })


# ---------------------------------------------------------------------------
# Endpoint 6 — POST /api/reset
# ---------------------------------------------------------------------------

@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Remove a scenario from in-memory storage."""
    try:
        data = request.get_json(force=True)
        sid  = data.get("scenario_id", "")
        if sid in scenarios:
            del scenarios[sid]
        return jsonify({"success": True})
    except Exception as exc:
        return _err(f"reset failed: {exc}", exc)


# ---------------------------------------------------------------------------
# Endpoint 7 — POST /api/realistic
# ---------------------------------------------------------------------------

@app.route('/api/realistic', methods=['POST'])
def api_realistic():
    try:
        data = request.get_json()
        jammers_raw = data.get('jammers', [])
        drone_alt   = data.get('drone_altitude', 100)

        # Import realistic_sim (lives at the project root, two levels up from backend/)
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
        from realistic_sim import run_realistic_comparison, compute_jammer_geometry

        jammers_xyz      = [[j['x'], j['y'], j.get('z', 0)] for j in jammers_raw]
        jammer_types     = [j.get('type', 'CW') for j in jammers_raw]
        jammer_powers_db = [j.get('power_db', 30) for j in jammers_raw]

        results = run_realistic_comparison(
            jammers_xyz      = jammers_xyz,
            jammer_types     = jammer_types,
            jammer_powers_db = jammer_powers_db,
            drone_xyz        = [0, 0, drone_alt],
            phase_mismatch_std = data.get('phase_mismatch_std', 5.0),
            gain_imbalance_std = data.get('gain_imbalance_std', 0.05)
        )

        def safe(obj):
            if isinstance(obj, np.ndarray): return obj.tolist()
            if isinstance(obj, np.floating): return float(obj)
            if isinstance(obj, np.integer): return int(obj)
            if isinstance(obj, dict): return {k: safe(v) for k, v in obj.items()}
            if isinstance(obj, list): return [safe(i) for i in obj]
            return obj

        return jsonify({
            'success': True,
            'ideal': {
                'music': safe(results['ideal']['music']),
                'mvdr':  safe(results['ideal']['mvdr'])
            },
            'realistic': {
                'music': safe(results['realistic']['music']),
                'mvdr':  safe(results['realistic']['mvdr'])
            }
        })
    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e),
                        'traceback': traceback.format_exc()}), 500


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok", "scenarios_stored": len(scenarios)})


# ---------------------------------------------------------------------------
# Entry point (also called by run_viz.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[navguard] Backend running at http://localhost:5001")
    app.run(host="0.0.0.0", port=5001, debug=False)
