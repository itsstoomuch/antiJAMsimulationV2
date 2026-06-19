"""
core.py — Shared math utilities for NAVGUARD visualization backend.

All computation used by app.py endpoints. The existing simulation files
(generate_array_data.py, music_spectrum.py, etc.) have hardcoded geometries
and file-based I/O; this module provides parametric versions used by the API.
"""

import numpy as np
from scipy.linalg import eigh
from scipy.signal import find_peaks

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

FREQ_GPS = 1575.42e6                # GPS L1, Hz
LAMBDA = 3e8 / FREQ_GPS             # ≈ 0.1903 m
D_ELEMENT = LAMBDA / 2              # ≈ 0.09517 m  (half-wavelength URA spacing)
GPS_POWER_DBW = -165.5              # GPS L1 received power at surface, dBW
DRONE_ALT = 100                     # default drone altitude, m
ADC_FULLSCALE_DEFAULT = 5.0

# 2×2 URA element positions in the XY plane (z=0), half-wavelength spacing
# Layout:  [2]=(0,d)  [3]=(d,d)
#          [0]=(0,0)  [1]=(d,0)
ELEM_POS = np.array([
    [0.0,        0.0,        0.0],
    [D_ELEMENT,  0.0,        0.0],
    [0.0,        D_ELEMENT,  0.0],
    [D_ELEMENT,  D_ELEMENT,  0.0],
], dtype=float)

# Default jammer geometry used by hybrid curve (from generate_array_data.py scenario)
_JAM_AZIMUTHS_DEFAULT = np.array([ 30.96,  165.96, -71.57])
_JAM_ELEVS_DEFAULT    = np.array([ -9.73,   -6.93,  -4.53])


# ---------------------------------------------------------------------------
# Unit converters
# ---------------------------------------------------------------------------

def db_to_linear(db: float) -> float:
    """dB to amplitude ratio (20 dB = ×10 in amplitude)."""
    return 10.0 ** (db / 20.0)


def linear_to_db(linear: float) -> float:
    """Amplitude ratio to dB. Clamps to avoid log(0)."""
    return 20.0 * np.log10(max(abs(linear), 1e-100))


# ---------------------------------------------------------------------------
# Steering vector
# ---------------------------------------------------------------------------

def steering_vector(az_deg: float, el_deg: float) -> np.ndarray:
    """
    4-element 2×2 URA steering vector for a far-field source at (az, el).

    Phase at element with position r = [x, y, 0]:
        φ = (2π/λ) × r · û   where û = [cos(el)cos(az), cos(el)sin(az), sin(el)]

    Returns shape (4,) complex128, elements in ELEM_POS order:
        index 0 = (0,0),  index 1 = (d,0),  index 2 = (0,d),  index 3 = (d,d)

    Note: at el=0° (horizon scan) this reduces to the azimuth-only projection
    used by music_spectrum.py and mvdr_beamformer.py, ensuring consistency.
    """
    az = np.radians(az_deg)
    el = np.radians(el_deg)
    u = np.array([
        np.cos(el) * np.cos(az),
        np.cos(el) * np.sin(az),
        np.sin(el),
    ])
    phase = (2.0 * np.pi / LAMBDA) * (ELEM_POS @ u)
    return np.exp(1j * phase)


# ---------------------------------------------------------------------------
# Jammer geometry
# ---------------------------------------------------------------------------

def jammer_geometry(jammer_xyz, drone_xyz=None):
    """
    Compute geometry from drone to jammer.

    Parameters
    ----------
    jammer_xyz : [x, y, z] metres
    drone_xyz  : [x, y, z] metres (default [0, 0, DRONE_ALT])

    Returns
    -------
    (azimuth_deg, elevation_deg, distance_m, path_loss_db)

    Elevation convention: positive = jammer above drone, negative = below.
    For a ground jammer at z=0 and drone at z=100, elevation ≈ +10° (prompt
    formula uses -dz/distance where dz < 0, giving a positive arcsin result).
    """
    if drone_xyz is None:
        drone_xyz = [0.0, 0.0, float(DRONE_ALT)]
    j = np.asarray(jammer_xyz, dtype=float)
    d = np.asarray(drone_xyz,  dtype=float)

    dx = j[0] - d[0]
    dy = j[1] - d[1]
    dz = j[2] - d[2]
    distance = np.sqrt(dx**2 + dy**2 + dz**2)
    if distance < 1e-6:
        distance = 1e-6

    azimuth_deg   = float(np.degrees(np.arctan2(dy, dx)))
    elevation_deg = float(np.degrees(np.arcsin(np.clip(-dz / distance, -1.0, 1.0))))
    path_loss_db  = float(20.0 * np.log10(max(4.0 * np.pi * distance / LAMBDA, 1e-100)))

    return azimuth_deg, elevation_deg, float(distance), path_loss_db


# ---------------------------------------------------------------------------
# IQ data generation (parametric, used by /api/generate)
# ---------------------------------------------------------------------------

def generate_iq_data(jammers, drone_pos=None, n_snapshots: int = 1000,
                     seed: int = 42) -> np.ndarray:
    """
    Generate 4×N complex IQ data for an arbitrary jammer scenario.

    The jammer steering vectors use the azimuth-only (el=0°) projection so that
    MUSIC at el=0° correctly recovers each jammer azimuth.  GPS uses el=90°
    (directly overhead) → steering vector [1,1,1,1].

    Parameters
    ----------
    jammers    : list of dicts  {x, y, z, type ('CW'|'FMCW'|'Barrage'), power_db}
    drone_pos  : [x, y, z] metres
    n_snapshots: IQ samples per channel

    Returns
    -------
    X : ndarray shape (4, n_snapshots) complex128
    """
    if drone_pos is None:
        drone_pos = [0.0, 0.0, float(DRONE_ALT)]
    drone_pos = np.asarray(drone_pos, dtype=float)

    rng  = np.random.default_rng(seed)
    fs   = 10e6          # ADC sample rate
    f_if = 1e3           # post-downconversion IF, Hz
    t    = np.arange(n_snapshots) / fs

    # GPS: directly overhead (el=90°) → a=[1,1,1,1], reference amplitude
    a_gps   = steering_vector(0.0, 90.0)   # = [1,1,1,1]
    gps_amp = 1.0
    chips   = rng.choice(np.array([-1.0, 1.0]), size=n_snapshots)
    s_gps   = gps_amp * chips * np.exp(1j * 2.0 * np.pi * f_if * t)
    X       = np.outer(a_gps, s_gps)

    for jammer in jammers:
        xyz = [float(jammer['x']), float(jammer['y']), float(jammer['z'])]
        az, _el, _dist, _ = jammer_geometry(xyz, drone_pos.tolist())

        # Use azimuth-only steering vector (el=0°) so MUSIC scan at el=0° matches
        a_jam     = steering_vector(az, 0.0)
        power_db  = float(jammer.get('power_db', 30))
        jam_amp   = gps_amp * db_to_linear(power_db)
        jtype     = jammer.get('type', 'CW')

        if jtype == 'FMCW':
            B, T_c   = 10e6, 1e-3
            chips_j  = rng.choice(np.array([-1.0, 1.0]), size=n_snapshots)
            chirp    = np.exp(1j * 2.0 * np.pi * (f_if + (B / (2.0 * T_c)) * t) * t)
            s_jam    = jam_amp * chips_j * chirp
        elif jtype == 'Barrage':
            raw   = ((rng.standard_normal(n_snapshots) +
                      1j * rng.standard_normal(n_snapshots)) / np.sqrt(2))
            raw  /= (np.std(raw) + 1e-12)
            s_jam = jam_amp * raw
        else:   # CW (default)
            chips_j = rng.choice(np.array([-1.0, 1.0]), size=n_snapshots)
            s_jam   = jam_amp * chips_j * np.exp(1j * 2.0 * np.pi * f_if * t)

        X += np.outer(a_jam, s_jam)

    # Thermal noise: −20 dB relative to GPS
    noise_amp = gps_amp * 0.1
    X += (noise_amp / np.sqrt(2)) * (
        rng.standard_normal((4, n_snapshots)) +
        1j * rng.standard_normal((4, n_snapshots))
    )

    return X


# ---------------------------------------------------------------------------
# Covariance matrix
# ---------------------------------------------------------------------------

def compute_covariance(X: np.ndarray, delta_loading: float = None) -> np.ndarray:
    """
    Sample covariance matrix  R = (1/N) X X^H  with optional diagonal loading.

    Parameters
    ----------
    X             : (4, N) complex IQ matrix
    delta_loading : if given, add delta_loading × I to R before returning

    Returns
    -------
    R : (4, 4) complex128 Hermitian matrix
    """
    n_elements, n_samples = X.shape
    R = (X @ X.conj().T) / n_samples
    if delta_loading is not None:
        R = R + delta_loading * np.eye(n_elements, dtype=complex)
    return R


# ---------------------------------------------------------------------------
# MUSIC DOA estimation
# ---------------------------------------------------------------------------

def compute_music(R: np.ndarray, n_sources: int,
                  az_scan: np.ndarray = None,
                  el_scan=None) -> dict:
    """
    MUSIC pseudospectrum and DOA estimation.

    Scans azimuth −180 to +179.5° in 0.5° steps (720 points exactly) at
    elevation = 0°, consistent with music_spectrum.py.

    Parameters
    ----------
    R         : (4, 4) sample covariance matrix
    n_sources : number of signal sources (jammers) to locate
    az_scan   : optional custom azimuth scan array (degrees)
    el_scan   : reserved for future 2-D scan (currently ignored)

    Returns
    -------
    dict with keys:
        detected_angles, pseudospectrum, eigenvalues, snr_gap,
        signal_subspace_size, noise_subspace_size
    """
    n_elements = R.shape[0]
    n_noise    = n_elements - n_sources

    if az_scan is None:
        az_scan = np.arange(-180.0, 180.0, 0.5)   # exactly 720 points

    eigenvalues, eigenvectors = eigh(R)
    # eigh returns ascending order; noise subspace = lowest n_noise eigenvectors
    E_noise = eigenvectors[:, :n_noise]            # (4, n_noise)

    spectrum = np.zeros(len(az_scan))
    for i, az in enumerate(az_scan):
        a     = steering_vector(az, 0.0)            # 1-D azimuth scan at el=0°
        proj  = E_noise.conj().T @ a                # projection onto noise subspace
        denom = float(np.real(np.dot(proj.conj(), proj)))
        spectrum[i] = 1.0 / (denom + 1e-12)

    max_val     = spectrum.max() + 1e-100
    spectrum_db = 10.0 * np.log10(spectrum / max_val)

    # Peak finding: top n_sources peaks with ≥25° separation
    peaks_idx, _ = find_peaks(spectrum_db, distance=10)
    if len(peaks_idx) == 0:
        peaks_idx = np.array([int(np.argmax(spectrum_db))])

    heights      = spectrum_db[peaks_idx]
    order        = np.argsort(heights)[::-1]
    sorted_peaks = peaks_idx[order]

    chosen   = []
    min_sep  = 25.0
    for idx in sorted_peaks:
        az_val = az_scan[idx]
        if all(abs(az_val - az_scan[c]) >= min_sep for c in chosen):
            chosen.append(int(idx))
        if len(chosen) == n_sources:
            break

    if not chosen:
        chosen = [int(np.argmax(spectrum_db))]
    peak_indices = sorted(chosen)

    detected_angles = [
        {"index": k, "azimuth": float(az_scan[idx]), "power_db": float(spectrum_db[idx])}
        for k, idx in enumerate(peak_indices)
    ]

    sorted_ev = np.sort(eigenvalues.real)[::-1]
    if n_noise > 0:
        snr_gap = float(sorted_ev[n_sources - 1] / max(sorted_ev[n_sources], 1e-100))
    else:
        snr_gap = 0.0

    pseudospectrum = [
        {"angle": float(az_scan[i]), "power_db": float(spectrum_db[i])}
        for i in range(len(az_scan))
    ]

    return {
        "detected_angles":      detected_angles,
        "pseudospectrum":       pseudospectrum,
        "eigenvalues":          sorted_ev.tolist(),
        "snr_gap":              snr_gap,
        "signal_subspace_size": int(n_sources),
        "noise_subspace_size":  int(n_noise),
    }


# ---------------------------------------------------------------------------
# MVDR beamformer
# ---------------------------------------------------------------------------

def compute_mvdr(R: np.ndarray, gps_az: float, gps_el: float,
                 jammer_angles: list) -> dict:
    """
    MVDR weight vector:  w = R⁻¹ a_gps / (a_gps^H R⁻¹ a_gps)

    Diagonal loading: δ = 1e-4 × trace(R)/N to prevent near-singularity.
    Beampattern scanned at elevation=0° to show null locations.

    Parameters
    ----------
    R             : (4, 4) sample covariance matrix
    gps_az        : GPS azimuth, degrees
    gps_el        : GPS elevation, degrees (90° = directly overhead)
    jammer_angles : list of jammer azimuth angles, degrees

    Returns
    -------
    dict with keys:
        weights, beampattern (360 pts), null_depths, gps_gain_db,
        rms_before, rms_after, rms_reduction_db
    """
    n_elements = R.shape[0]
    a_gps = steering_vector(gps_az, gps_el)

    load     = 1e-4 * float(np.trace(R).real) / n_elements
    R_loaded = R + load * np.eye(n_elements, dtype=complex)

    u     = np.linalg.solve(R_loaded, a_gps)
    denom = float(np.real(a_gps.conj() @ u))
    w     = u / max(denom, 1e-12)

    # Beampattern: exactly 360 points from −180 to +179 (1° steps)
    theta_scan = np.arange(-180.0, 180.0, 1.0)    # 360 points
    pattern    = np.array([
        float(abs(w.conj() @ steering_vector(az, 0.0))**2)
        for az in theta_scan
    ])
    pattern_db = 10.0 * np.log10(pattern + 1e-20)
    pattern_db -= pattern_db.max()

    gps_gain    = float(abs(w.conj() @ a_gps)**2)
    gps_gain_db = 10.0 * np.log10(max(gps_gain, 1e-20))

    # Null depth at each jammer azimuth
    null_depths = []
    for k, jaz in enumerate(jammer_angles):
        a_jam       = steering_vector(float(jaz), 0.0)
        jam_gain_db = 10.0 * np.log10(float(abs(w.conj() @ a_jam)**2) + 1e-20)
        null_depths.append({
            "jammer_index":  k,
            "angle":         float(jaz),
            "null_depth_db": float(gps_gain_db - jam_gain_db),
        })

    # RMS estimates from the covariance matrix (no raw X needed)
    rms_before      = float(np.sqrt(max(float(np.real(R[0, 0])), 0.0)))
    rms_after       = float(np.sqrt(max(float(np.real(w.conj() @ R @ w)), 0.0)))
    rms_reduction_db = float(linear_to_db(rms_before / max(rms_after, 1e-100)))

    weights = [
        {"index": i, "real": float(w[i].real), "imag": float(w[i].imag)}
        for i in range(len(w))
    ]
    beampattern = [
        {"angle": float(theta_scan[i]), "gain_db": float(pattern_db[i])}
        for i in range(len(theta_scan))
    ]

    return {
        "weights":          weights,
        "beampattern":      beampattern,
        "null_depths":      null_depths,
        "gps_gain_db":      float(gps_gain_db),
        "rms_before":       rms_before,
        "rms_after":        rms_after,
        "rms_reduction_db": rms_reduction_db,
    }


# ---------------------------------------------------------------------------
# Hybrid analog-digital curve
# ---------------------------------------------------------------------------

def compute_hybrid_curve(alpha_pre: float = 0.9,
                         adc_fullscale: float = 5.0,
                         n_points: int = 50) -> dict:
    """
    Sweep jammer power 0–50 dB above GPS; compare ideal / digital / hybrid MVDR.

    Mirrors hybrid_sim.py logic with parameterized alpha_pre and adc_fullscale.
    Uses the default 3-jammer geometry from generate_array_data.py.

    Parameters
    ----------
    alpha_pre     : analog pre-cancellation fraction per jammer (0–1)
    adc_fullscale : ADC clipping level (signal units)
    n_points      : sweep points across 0–50 dB

    Returns
    -------
    dict with keys:
        jammer_powers_db, sinr_digital, sinr_hybrid, sinr_ideal,
        digital_fails_at_db, hybrid_fails_at_db, improvement_at_30db, advantage_db
    """
    GPS_AMP    = 1.0
    NOISE_AMP  = 0.1 * GPS_AMP
    NOISE_PWR  = NOISE_AMP ** 2
    N_EL       = 4
    N_SAMP     = 500       # smaller batch for API speed
    SEED       = 42
    F_IF       = 1e3
    FS         = 10e6

    rng  = np.random.default_rng(SEED)
    t    = np.arange(N_SAMP) / FS

    # Use fixed 3-jammer geometry (el=0° for azimuth consistency)
    a_gps  = steering_vector(0.0, 0.0)
    a_jams = [steering_vector(float(az), 0.0) for az in _JAM_AZIMUTHS_DEFAULT]

    jam_db_range = np.linspace(0.0, 50.0, n_points)

    sinr_ideal   = np.zeros(n_points)
    sinr_digital = np.zeros(n_points)
    sinr_hybrid  = np.zeros(n_points)

    def _mvdr(R_in, a_look=None):
        """MVDR weights for look direction a_look (defaults to a_gps)."""
        if a_look is None:
            a_look = a_gps
        load  = 1e-4 * float(np.trace(R_in).real) / N_EL
        R_l   = R_in + load * np.eye(N_EL, dtype=complex)
        u     = np.linalg.solve(R_l, a_look)
        denom = float(np.real(a_look.conj() @ u))
        return u / max(denom, 1e-12)

    def _clip(X_in):
        return (np.clip(X_in.real, -adc_fullscale, adc_fullscale) +
                1j * np.clip(X_in.imag, -adc_fullscale, adc_fullscale))

    def _sinr(w, jam_amp, a_g=None, a_js=None):
        if a_g  is None: a_g  = a_gps
        if a_js is None: a_js = a_jams
        gps_out   = float(abs(w.conj() @ a_g)**2) * GPS_AMP**2
        jam_out   = sum(float(abs(w.conj() @ aj)**2) * jam_amp**2 for aj in a_js)
        noise_out = float(np.real(w.conj() @ w)) * NOISE_PWR
        return 10.0 * np.log10(max(gps_out, 1e-30) / (jam_out + noise_out + 1e-30))

    s_gps = GPS_AMP * np.exp(1j * 2.0 * np.pi * F_IF * t)

    for i, jdB in enumerate(jam_db_range):
        jam_amp = GPS_AMP * 10.0 ** (jdB / 20.0)

        s_jams = []
        for _ in range(3):
            chips = rng.choice(np.array([-1.0, 1.0]), size=N_SAMP)
            s_jams.append(jam_amp * chips * np.exp(1j * 2.0 * np.pi * F_IF * t))

        X = np.outer(a_gps, s_gps)
        for aj, sj in zip(a_jams, s_jams):
            X += np.outer(aj, sj)
        X += NOISE_AMP * (
            rng.standard_normal((N_EL, N_SAMP)) +
            1j * rng.standard_normal((N_EL, N_SAMP))
        ) / np.sqrt(2)

        # Path 1: Ideal MVDR (no ADC limit)
        R1 = (X @ X.conj().T) / N_SAMP
        w1 = _mvdr(R1)
        sinr_ideal[i] = _sinr(w1, jam_amp)

        # Path 2: Pure digital — full signal clipped at adc_fullscale
        X_clip = _clip(X)
        R2     = (X_clip @ X_clip.conj().T) / N_SAMP
        w2     = _mvdr(R2)
        sinr_digital[i] = _sinr(w2, jam_amp)

        # Path 3: Hybrid — analog pre-cancel then clip
        X_pre      = X.copy()
        a_gps_eff  = a_gps.copy()
        a_jams_eff = [aj.copy() for aj in a_jams]

        for aj in a_jams:
            norm = float(np.linalg.norm(aj))
            a_n  = aj / max(norm, 1e-12)
            proj = a_n.conj() @ X_pre
            X_pre -= alpha_pre * np.outer(a_n, proj)
            a_gps_eff -= alpha_pre * a_n * complex(a_n.conj() @ a_gps_eff)
            for k in range(3):
                a_jams_eff[k] -= alpha_pre * a_n * complex(a_n.conj() @ a_jams_eff[k])

        X_pc = _clip(X_pre)
        R3   = (X_pc @ X_pc.conj().T) / N_SAMP
        # Use effective GPS steering vector as the look direction (mirrors hybrid_sim.py)
        w3   = _mvdr(R3, a_look=a_gps_eff)
        sinr_hybrid[i] = _sinr(w3, jam_amp, a_g=a_gps_eff, a_js=a_jams_eff)

    def _first_fail(arr):
        mask = arr < 0.0
        return float(jam_db_range[np.argmax(mask)]) if mask.any() else None

    fail_dig = _first_fail(sinr_digital)
    fail_hyb = _first_fail(sinr_hybrid)
    idx30    = int(np.argmin(np.abs(jam_db_range - 30.0)))
    impr30   = float(sinr_hybrid[idx30] - sinr_digital[idx30])
    adv_db   = float(np.mean(sinr_hybrid - sinr_digital))

    return {
        "jammer_powers_db":    jam_db_range.tolist(),
        "sinr_digital":        sinr_digital.tolist(),
        "sinr_hybrid":         sinr_hybrid.tolist(),
        "sinr_ideal":          sinr_ideal.tolist(),
        "digital_fails_at_db": fail_dig,
        "hybrid_fails_at_db":  fail_hyb,
        "improvement_at_30db": impr30,
        "advantage_db":        adv_db,
    }
