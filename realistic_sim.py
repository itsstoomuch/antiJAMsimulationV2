"""
realistic_sim.py — Hardware-imperfect simulation layer
Adds Rahul's noise models to the ideal pipeline to simulate real hardware conditions.
Compares ideal vs realistic performance across all KPIs.
"""

import numpy as np
from scipy.linalg import eigh
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# ─── Constants ────────────────────────────────────────────────────────────────
FREQ     = 1575.42e6
C        = 3e8
LAMBDA   = C / FREQ          # 0.19029 m
D        = LAMBDA / 2        # 0.09517 m
NUM_ANT  = 4
ROWS     = 2
COLS     = 2

# 2×2 URA element positions (in units of D)
ELEM_POS = np.array([[r*D, c*D] for r in range(ROWS) for c in range(COLS)])

# ─── Steering Vector ──────────────────────────────────────────────────────────
def steering_vector(az_deg, el_deg):
    """
    2×2 URA steering vector matching Rahul's sign convention.
    phase = -2j * pi * (x * kx + y * ky)
    kx = cos(el)*cos(az), ky = cos(el)*sin(az)
    """
    az = np.radians(az_deg)
    el = np.radians(el_deg)
    kx = np.cos(el) * np.cos(az)
    ky = np.cos(el) * np.sin(az)
    a = np.array([
        np.exp(-2j * np.pi * (pos[0]*kx + pos[1]*ky) / LAMBDA)
        for pos in ELEM_POS
    ])
    return a

# ─── Jammer Geometry ─────────────────────────────────────────────────────────
def compute_jammer_geometry(jammer_xyz, drone_xyz):
    """
    Compute azimuth, elevation, distance from drone to jammer.
    jammer_xyz: [x, y, z] in meters
    drone_xyz:  [x, y, z] in meters
    Returns: (az_deg, el_deg, distance_m)
    """
    dx = jammer_xyz[0] - drone_xyz[0]
    dy = jammer_xyz[1] - drone_xyz[1]
    dz = jammer_xyz[2] - drone_xyz[2]
    dist = np.sqrt(dx**2 + dy**2 + dz**2)
    az   = np.degrees(np.arctan2(dy, dx))
    el   = np.degrees(np.arcsin(dz / dist))  # ground jammer below drone → negative el
    return az, el, dist

# ─── IQ Data Generation with Hardware Imperfections ──────────────────────────
def generate_realistic_iq(
    jammers,                    # list of dicts: {az_deg, el_deg, power_db}
    n_snapshots      = 1000,
    gps_power_dbw    = -165.5,
    phase_mismatch_std = 5.0,   # degrees std per element
    gain_imbalance_std = 0.05,  # fractional std (0.05 = 5%)
    impulsive_prob     = 0.03,  # probability of impulsive spike per sample
    impulsive_amp      = 3.0,   # amplitude of impulsive spikes
    phase_noise_std    = 0.02,  # radians std per sample (cumulative walk)
    multipath_depth    = 0.25,  # multipath fading depth
    multipath_period   = 80,    # multipath fading period in samples
    thermal_noise_amp  = 0.1,   # -20 dB below GPS (was 0.5)
    enable_phase_mismatch  = True,
    enable_gain_imbalance  = True,
    enable_impulsive_noise = True,
    enable_phase_noise     = True,
    enable_multipath       = True,
    shared_oscillator      = True,   # GPSDO: one drift shared by all channels
):
    """
    Generate 4×N complex IQ data with realistic hardware imperfections.
    Integrates Rahul's noise models with our steering vector convention.
    """
    t = np.arange(n_snapshots)
    X = np.zeros((NUM_ANT, n_snapshots), dtype=complex)

    # GPS signal (from overhead el=90)
    gps_amp = 1.0   # normalized: GPS = 0 dB reference
    a_gps = steering_vector(0, 90)
    gps_signal = gps_amp * np.exp(1j * 2 * np.pi * 0.001 * t)
    X += np.outer(a_gps, gps_signal)

    # Jammer signals
    for j in jammers:
        jammer_amp = 10 ** (j['power_db'] / 20) * gps_amp
        a_j = steering_vector(j['az_deg'], j['el_deg'])

        # Jammer type affects signal model
        if j.get('type') == 'CW':
            sig = jammer_amp * np.exp(1j * 2 * np.pi * 0.05 * t)
        elif j.get('type') == 'FMCW':
            # freq_sweep is in cycles/sample; phase is the running sum of
            # instantaneous frequency.  (The old "/ n_snapshots" divided the
            # sweep rate by 1000, collapsing the chirp to a near-DC tone.)
            freq_sweep = np.linspace(0.03, 0.07, n_snapshots)
            sig = jammer_amp * np.exp(1j * 2 * np.pi * np.cumsum(freq_sweep))
        else:  # Barrage
            sig = jammer_amp * (np.random.randn(n_snapshots) + 1j * np.random.randn(n_snapshots)) / np.sqrt(2)

        X += np.outer(a_j, sig)

    # ── Rahul's Noise Models ──────────────────────────────────────────────────

    # 1. Thermal noise
    thermal = thermal_noise_amp * (
        np.random.randn(NUM_ANT, n_snapshots) +
        1j * np.random.randn(NUM_ANT, n_snapshots)
    ) / np.sqrt(2)
    X += thermal

    # 2. Impulsive noise (Rahul's model)
    if enable_impulsive_noise:
        impulse = np.zeros((NUM_ANT, n_snapshots), dtype=complex)
        mask = np.random.rand(NUM_ANT, n_snapshots) < impulsive_prob
        n_spikes = np.sum(mask)
        impulse[mask] = impulsive_amp * (
            np.random.randn(n_spikes) + 1j * np.random.randn(n_spikes)
        )
        X += impulse

    # 3. Phase noise (cumulative random walk)
    if enable_phase_noise:
        if shared_oscillator:
            # All channels see the same phase drift — GPSDO behaviour.
            # A common per-snapshot phase cancels in the array manifold (phase
            # differences between channels are preserved), so it barely touches R.
            shared_drift = np.cumsum(phase_noise_std * np.random.randn(n_snapshots))
            X *= np.exp(1j * shared_drift)
        else:
            # Independent per-channel drift — no GPSDO. Decorrelates the manifold.
            for m in range(NUM_ANT):
                ph_noise = np.cumsum(phase_noise_std * np.random.randn(n_snapshots))
                X[m, :] *= np.exp(1j * ph_noise)

    # 4. Multipath fading (Rahul's sinusoidal + random model)
    if enable_multipath:
        fading = (
            1 +
            multipath_depth * np.sin(2 * np.pi * t / multipath_period) +
            0.10 * np.random.randn(n_snapshots)
        )
        X *= fading

    # ── Our Additional Hardware Imperfections ────────────────────────────────

    # 5. Per-element phase mismatch (hardware calibration error)
    if enable_phase_mismatch:
        phase_offsets = np.radians(
            np.random.randn(NUM_ANT) * phase_mismatch_std
        )
        X *= np.exp(1j * phase_offsets[:, np.newaxis])

    # 6. Per-element gain imbalance
    if enable_gain_imbalance:
        gain_factors = 1 + np.random.randn(NUM_ANT) * gain_imbalance_std
        X *= gain_factors[:, np.newaxis]

    return X

# ─── 2D MUSIC with Variable Elevation (Rahul's algorithm + our elevation fix) ─
def music_2d(X, n_sources=3, el_deg=None, az_range=(-180, 180), az_step=1.0):
    """
    2D MUSIC DoA estimation.
    If el_deg is provided: scan azimuth only at that elevation (fast).
    If el_deg is None: scan both azimuth and elevation (slow, full 2D).

    Returns: list of {az_deg, el_deg, power_db} for each detected source
    """
    N, M = X.shape
    R = X @ X.conj().T / M

    # Diagonal loading for stability
    delta = np.real(np.min(np.linalg.eigvalsh(R))) * 1.0
    R_loaded = R + max(delta, 1e-12) * np.eye(N)

    eigenvalues, eigenvectors = eigh(R_loaded)
    # Sort descending
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    # Noise subspace: smallest N-n_sources eigenvectors
    En = eigenvectors[:, n_sources:]

    az_angles = np.arange(az_range[0], az_range[1], az_step)

    if el_deg is not None:
        # Fast 1D scan at fixed elevation (Rahul's approach with variable el)
        spectrum = []
        for az in az_angles:
            a = steering_vector(az, el_deg).reshape(-1, 1)
            denom = a.conj().T @ En @ En.conj().T @ a
            spectrum.append(float(np.real(1.0 / (np.abs(denom[0,0]) + 1e-12))))

        spectrum = np.array(spectrum)
        spectrum_db = 10 * np.log10(spectrum / np.max(spectrum) + 1e-10)

        # Find peaks
        from scipy.signal import find_peaks
        peaks, _ = find_peaks(spectrum, distance=int(25/az_step))
        top_peaks = peaks[np.argsort(spectrum[peaks])[::-1][:n_sources]]

        results = []
        for p in sorted(top_peaks):
            results.append({
                'az_deg':   float(az_angles[p]),
                'el_deg':   float(el_deg),
                'power_db': float(spectrum_db[p])
            })

        return {
            'sources':        results,
            'az_angles':      az_angles.tolist(),
            'spectrum_db':    spectrum_db.tolist(),
            'eigenvalues':    eigenvalues.tolist(),
            'snr_gap':        float(eigenvalues[0] / eigenvalues[n_sources])
        }

    else:
        # Full 2D scan (slower — azimuth + elevation)
        el_angles = np.arange(0, 90, 5.0)  # 5° elevation steps
        best_peaks = []

        for el in el_angles:
            spectrum_el = []
            for az in az_angles:
                a = steering_vector(az, el).reshape(-1, 1)
                denom = a.conj().T @ En @ En.conj().T @ a
                spectrum_el.append(float(np.real(1.0 / (np.abs(denom[0,0]) + 1e-12))))

            spectrum_el = np.array(spectrum_el)
            from scipy.signal import find_peaks
            peaks, props = find_peaks(spectrum_el, distance=int(20/az_step))
            for p in peaks:
                best_peaks.append({
                    'az_deg':   float(az_angles[p]),
                    'el_deg':   float(el),
                    'power':    float(spectrum_el[p])
                })

        # Sort by power, take top n_sources
        best_peaks.sort(key=lambda x: x['power'], reverse=True)
        top = best_peaks[:n_sources]

        # Compute spectrum at el=0 for display
        spectrum_0 = []
        for az in az_angles:
            a = steering_vector(az, 0).reshape(-1, 1)
            denom = a.conj().T @ En @ En.conj().T @ a
            spectrum_0.append(float(np.real(1.0 / (np.abs(denom[0,0]) + 1e-12))))
        spectrum_0 = np.array(spectrum_0)
        spectrum_db = 10 * np.log10(spectrum_0 / np.max(spectrum_0) + 1e-10)

        results = [{'az_deg': p['az_deg'], 'el_deg': p['el_deg'],
                    'power_db': 10*np.log10(p['power']/best_peaks[0]['power']+1e-10)}
                   for p in top]

        return {
            'sources':     results,
            'az_angles':   az_angles.tolist(),
            'spectrum_db': spectrum_db.tolist(),
            'eigenvalues': eigenvalues.tolist(),
            'snr_gap':     float(eigenvalues[0] / eigenvalues[n_sources])
        }

# ─── MVDR with 2D Steering ────────────────────────────────────────────────────
def mvdr_2d(X, jammer_angles, gps_az=0.0, gps_el=90.0):
    """
    MVDR beamformer using 2D steering vectors.
    jammer_angles: list of {az_deg, el_deg}
    Returns weights, null depths, beampattern
    """
    N, M = X.shape
    R = X @ X.conj().T / M

    # Diagonal loading
    delta = float(np.real(np.min(np.linalg.eigvalsh(R))))
    R_loaded = R + max(delta, 1e-12) * np.eye(N)
    R_inv = np.linalg.inv(R_loaded)

    # GPS steering vector
    a_gps = steering_vector(gps_az, gps_el).reshape(-1, 1)

    # MVDR weights
    num = R_inv @ a_gps
    den = (a_gps.conj().T @ R_inv @ a_gps)[0, 0]
    w = num / den

    # GPS gain
    gps_gain = float(np.abs(w.conj().T @ a_gps)[0, 0])
    gps_gain_db = 20 * np.log10(gps_gain + 1e-12)

    # Null depths per jammer
    null_depths = []
    for i, j in enumerate(jammer_angles):
        a_j = steering_vector(j['az_deg'], j['el_deg']).reshape(-1, 1)
        null_gain = float(np.abs(w.conj().T @ a_j)[0, 0])
        null_db = 20 * np.log10(null_gain + 1e-12)
        null_depths.append({
            'jammer_index': i,
            'az_deg': j['az_deg'],
            'el_deg': j['el_deg'],
            'null_depth_db': null_db
        })

    # Beampattern 360°
    az_scan = np.arange(-180, 180, 1.0)
    beampattern = []
    for az in az_scan:
        a = steering_vector(az, 0).reshape(-1, 1)
        gain = float(np.abs(w.conj().T @ a)[0, 0])
        beampattern.append(20 * np.log10(gain + 1e-12))

    # RMS before/after
    y = w.conj().T @ X
    rms_before = float(np.sqrt(np.mean(np.abs(X[0])**2)))
    rms_after  = float(np.sqrt(np.mean(np.abs(y)**2)))

    return {
        'weights':      [{'index': i, 'real': float(w[i,0].real), 'imag': float(w[i,0].imag)}
                         for i in range(N)],
        'null_depths':  null_depths,
        'gps_gain_db':  gps_gain_db,
        'beampattern':  [{'angle': float(az_scan[i]), 'gain_db': beampattern[i]}
                         for i in range(len(az_scan))],
        'rms_before':   rms_before,
        'rms_after':    rms_after
    }

# ─── Run Realistic vs Ideal Comparison ────────────────────────────────────────
def run_realistic_comparison(
    jammers_xyz,        # list of [x,y,z] jammer positions
    jammer_types,       # list of 'CW'/'FMCW'/'Barrage'
    jammer_powers_db,   # list of power values
    drone_xyz = [0, 0, 100],
    n_snapshots = 1000,
    phase_mismatch_std = 5.0,
    gain_imbalance_std = 0.05,
    shared_oscillator = True
):
    """
    Run full pipeline comparison: ideal vs realistic.
    Returns dict with both sets of results.
    """
    print("\n" + "="*60)
    print("REALISTIC SIMULATION — Hardware Imperfection Analysis")
    print(f"GPSDO shared oscillator: {'ON' if shared_oscillator else 'OFF'}")
    print("="*60)

    # Compute jammer geometries
    jammer_configs = []
    for xyz, jtype, pdb in zip(jammers_xyz, jammer_types, jammer_powers_db):
        az, el, dist = compute_jammer_geometry(xyz, drone_xyz)
        jammer_configs.append({
            'az_deg':   az,
            'el_deg':   el,
            'power_db': pdb,
            'type':     jtype,
            'distance': dist
        })
        print(f"Jammer: az={az:.1f}° el={el:.1f}° dist={dist:.0f}m type={jtype} power={pdb}dB")

    results = {}

    for mode in ['ideal', 'realistic']:
        print(f"\n--- {mode.upper()} ---")
        if mode == 'ideal':
            X = generate_realistic_iq(
                jammer_configs, n_snapshots,
                enable_phase_mismatch=False,
                enable_gain_imbalance=False,
                enable_impulsive_noise=False,
                enable_phase_noise=False,
                enable_multipath=False
            )
        else:
            X = generate_realistic_iq(
                jammer_configs, n_snapshots,
                phase_mismatch_std=phase_mismatch_std,
                gain_imbalance_std=gain_imbalance_std,
                enable_phase_mismatch=True,
                enable_gain_imbalance=True,
                enable_impulsive_noise=True,
                enable_phase_noise=True,
                enable_multipath=True,
                shared_oscillator=shared_oscillator
            )

        # MUSIC with elevation from geometry
        el_estimate = np.mean([j['el_deg'] for j in jammer_configs])
        music_result = music_2d(X, n_sources=len(jammer_configs),
                                el_deg=el_estimate)

        print(f"MUSIC detected: {[(s['az_deg'], s['el_deg']) for s in music_result['sources']]}")
        print(f"Eigenvalue gap: {music_result['snr_gap']:.0f}×")

        # MVDR
        mvdr_result = mvdr_2d(X, music_result['sources'])

        print("Null depths:")
        for n in mvdr_result['null_depths']:
            target = ">40 dB"
            status = "PASS" if abs(n['null_depth_db']) >= 40 else "FAIL"
            print(f"  J{n['jammer_index']+1} az={n['az_deg']:.1f}°: "
                  f"{n['null_depth_db']:.1f} dB [{status}]")
        print(f"GPS gain: {mvdr_result['gps_gain_db']:.2f} dB")

        results[mode] = {
            'music':  music_result,
            'mvdr':   mvdr_result,
            'X':      X
        }

    print("\n" + "="*60)
    print("COMPARISON SUMMARY")
    print("="*60)
    print(f"{'Metric':<25} {'Ideal':>10} {'Realistic':>10} {'Target':>10} {'Pass':>6}")
    print("-"*65)

    ideal_nulls    = results['ideal']['mvdr']['null_depths']
    real_nulls     = results['realistic']['mvdr']['null_depths']
    ideal_gap      = results['ideal']['music']['snr_gap']
    real_gap       = results['realistic']['music']['snr_gap']

    for i in range(len(ideal_nulls)):
        ideal_d = abs(ideal_nulls[i]['null_depth_db'])
        real_d  = abs(real_nulls[i]['null_depth_db'])
        status  = "YES" if real_d >= 40 else "NO ⚠"
        print(f"  Null J{i+1} depth       {ideal_d:>9.1f}  {real_d:>9.1f}       >40  {status:>6}")

    print(f"  Eigenvalue gap     {ideal_gap:>9.0f}  {real_gap:>9.0f}         --      --")
    print(f"  GPS gain (ideal)   {results['ideal']['mvdr']['gps_gain_db']:>9.2f}")
    print(f"  GPS gain (real)    {results['realistic']['mvdr']['gps_gain_db']:>9.2f}      ~0.0")
    print("="*60)

    return results


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Test with standard 3-jammer scenario
    jammers_xyz = [
        [500,  200, 0],   # J1 NE ground
        [-300, 400, 0],   # J2 NW ground
        [100, -600, 0],   # J3 S  ground
    ]
    common = dict(
        jammers_xyz      = jammers_xyz,
        jammer_types     = ['CW', 'FMCW', 'Barrage'],
        jammer_powers_db = [30, 25, 20],
        drone_xyz        = [0, 0, 100],
        n_snapshots      = 1000,
        phase_mismatch_std = 5.0,
        gain_imbalance_std = 0.05,
    )

    print("\n################  MODE A — REALISTIC, NO GPSDO  ################")
    print("################  (independent per-channel drift)  ############")
    run_realistic_comparison(**common, shared_oscillator=False)

    print("\n################  MODE B — REALISTIC, WITH GPSDO  ##############")
    print("################  (shared oscillator drift)  ##################")
    run_realistic_comparison(**common, shared_oscillator=True)
