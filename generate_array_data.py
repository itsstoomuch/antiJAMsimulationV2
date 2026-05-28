"""
generate_array_data.py

Realistic 4-channel complex IQ data for a 2×2 uniform rectangular array (URA)
receiving a GPS satellite and three spatially separated jammers.

Upgrades over the toy ULA model
--------------------------------
  • 3D coordinate-based geometry   (positions → azimuth / elevation)
  • 2×2 planar (URA) array         (replaces 4-element ULA)
  • Cosine element radiation pattern
  • Free-space path loss with realistic transmit powers
  • Three jammer waveform types    (CW, FMCW, Barrage)
  • Full scene summary printed to console

Physical scenario
-----------------
  Drone (array platform) : [0, 0, 100] m  (100 m altitude AGL)
  GPS satellite          : [0, 0, 20 200 000] m  (L1 MEO orbit)
  Jammer 1               : [500, 300, 0] m   (NE, ground level)  → az = +30.96°
  Jammer 2               : [-800, 200, 0] m  (NW, ground level)  → az = +165.96°

Output format is unchanged — downstream scripts load array_data.npy
(shape 4 × n_samples, dtype complex128) without modification.
"""

import sys
import numpy as np
from scipy.signal import butter, lfilter


def generate_array_data(
    n_samples:   int   = 1000,        # IQ snapshots per channel
    fs:          float = 10e6,        # ADC sample rate, Hz
    f0:          float = 1575.42e6,   # GPS L1 carrier frequency, Hz
    f_if:        float = 1e3,         # post-downconversion IF, Hz
    jammer_type: str   = 'CW',        # 'CW' | 'FMCW' | 'Barrage'
    seed:        int   = 42,          # RNG seed
) -> np.ndarray:
    """
    Generate synthetic 4 × n_samples complex IQ data for a 2×2 URA.

    Signal model (narrowband per-snapshot)
    ----------------------------------------
        x(t) = Σ_k  a_k · α_k · s_k(t)  +  n(t)

    where
        a_k  = URA steering vector for source k (includes element pattern)
        α_k  = free-space path-loss amplitude for source k
        s_k  = complex waveform of source k
        n(t) = complex AWGN thermal noise

    Parameters
    ----------
    n_samples   : IQ snapshots per channel
    fs          : ADC sample rate, Hz
    f0          : GPS L1 carrier (sets wavelength and path-loss)
    f_if        : IF frequency after analogue downconversion
    jammer_type : 'CW', 'FMCW', or 'Barrage'
    seed        : NumPy RNG seed for reproducibility

    Returns
    -------
    X : ndarray, shape (4, n_samples), dtype complex128
        Row m = complex IQ time series of antenna element m.

    Side effects
    ------------
    Writes X to 'array_data.npy'.  Prints a full scene geometry summary.
    """

    rng = np.random.default_rng(seed)

    # =========================================================================
    # 1. PHYSICAL CONSTANTS
    # =========================================================================

    c   = 3e8               # speed of light in vacuum, m/s
    lam = c / f0            # GPS L1 wavelength ≈ 0.1903 m
    d   = lam / 2           # half-wavelength URA spacing ≈ 0.0951 m
    #
    # Half-wavelength spacing is the spatial analogue of Nyquist sampling:
    # it is the largest element pitch that avoids grating lobes (spatial aliasing).

    # =========================================================================
    # 2. 3D SCENE POSITIONS  (all in metres, ECEF-like local frame)
    # =========================================================================

    drone_pos   = np.array([0.0,    0.0,    100.0],        dtype=float)
    gps_pos     = np.array([0.0,    0.0,    20_200_000.0], dtype=float)
    jammer1_pos = np.array([ 500.0,  300.0,  0.0],         dtype=float)
    jammer2_pos = np.array([-800.0,  200.0,  0.0],         dtype=float)

    # =========================================================================
    # 3. GEOMETRY: AZIMUTH, ELEVATION, DISTANCE  (from drone to each source)
    # =========================================================================

    def compute_geometry(target_pos: np.ndarray, ref_pos: np.ndarray):
        """
        Return (azimuth_rad, elevation_rad, distance_m, unit_vector) for the
        direction from ref_pos to target_pos.

        Azimuth  = angle in the horizontal (XY) plane, measured from +X axis.
        Elevation = angle above the horizontal plane.
        """
        diff = target_pos - ref_pos                                  # displacement
        dist = np.linalg.norm(diff)                                  # straight-line range
        az   = np.arctan2(diff[1], diff[0])                         # horizontal angle
        el   = np.arctan2(diff[2], np.sqrt(diff[0]**2 + diff[1]**2))# above horizon
        unit = diff / dist                                           # unit direction vector
        return az, el, dist, unit

    az_gps,  el_gps,  dist_gps,  uhat_gps  = compute_geometry(gps_pos,     drone_pos)
    az_jam1, el_jam1, dist_jam1, uhat_jam1 = compute_geometry(jammer1_pos, drone_pos)
    az_jam2, el_jam2, dist_jam2, uhat_jam2 = compute_geometry(jammer2_pos, drone_pos)

    # =========================================================================
    # 4. 2×2 UNIFORM RECTANGULAR ARRAY  (URA) ELEMENT POSITIONS
    # =========================================================================

    # Four elements in the XY plane, half-wavelength spacing in both X and Y:
    #
    #   [2]=(0,d)   [3]=(d,d)
    #   [0]=(0,0)   [1]=(d,0)
    #
    elem_pos = np.array([
        [0, 0, 0],   # element 0 — origin
        [d, 0, 0],   # element 1 — shifted one step in X
        [0, d, 0],   # element 2 — shifted one step in Y
        [d, d, 0],   # element 3 — shifted one step in both X and Y
    ], dtype=float)  # shape (4, 3)

    # =========================================================================
    # 5. COSINE ELEMENT RADIATION PATTERN
    # =========================================================================

    def element_pattern(elevation_rad: float) -> float:
        """
        Amplitude response of a single patch/dipole element vs elevation.

        A flush-mounted patch has a cos(elevation) *power* pattern:
            G_power(el) = max(cos(el), 0)

        Steering vectors multiply *amplitude*, so we take the square root:
            G_amplitude(el) = sqrt(max(cos(el), 0))

        Signals arriving from below the horizon (el < 0) are blocked by the
        ground plane and return zero amplitude.
        """
        gain_power = max(np.cos(elevation_rad), 0.0)
        return np.sqrt(gain_power)

    # =========================================================================
    # 6. URA STEERING VECTORS WITH ELEMENT PATTERN
    # =========================================================================

    def steering_vector(unit_vec: np.ndarray, elevation_rad: float) -> np.ndarray:
        """
        4-element URA steering vector for a far-field source.

        Inter-element phase uses the AZIMUTH-PROJECTED unit vector (horizontal
        plane only).  Because all URA elements have z = 0, the z-component of
        unit_vec contributes nothing to phase — but leaving cos(el) in the XY
        components introduces a systematic scale factor (~0.985 at el = -10°)
        that shifts MUSIC nulls to wrong azimuths when the 1D azimuth scan
        assumes el = 0°.  Projecting onto the horizontal plane makes the data
        model exactly consistent with the 1D scan in music_spectrum.py.

        Elevation still enters through the element_pattern amplitude gain, which
        correctly reduces sensitivity for signals arriving near/below the horizon.
        """
        g   = element_pattern(elevation_rad)             # scalar amplitude gain
        az  = np.arctan2(unit_vec[1], unit_vec[0])       # azimuth from full 3D direction
        u_az = np.array([np.cos(az), np.sin(az), 0.0])  # horizontal unit vector
        phase = (2 * np.pi / lam) * (elem_pos @ u_az)   # phase uses azimuth only
        return g * np.exp(1j * phase)                    # complex steering vector

    a_gps  = steering_vector(uhat_gps,  el_gps)
    a_jam1 = steering_vector(uhat_jam1, el_jam1)
    a_jam2 = steering_vector(uhat_jam2, el_jam2)

    # =========================================================================
    # 7. FREE-SPACE PATH LOSS  (amplitude factor)
    # =========================================================================

    def path_loss_amplitude(distance: float, frequency: float) -> float:
        """
        Friis free-space transmission formula, amplitude form.

        Friis power ratio:      P_rx / P_tx = (λ / 4πR)²
        Amplitude equivalent:   A_rx / A_tx =  λ / (4πR)

        Multiplying sqrt(P_tx) by this factor gives the received amplitude,
        naturally accounting for the vast power difference between a 10 W
        ground jammer at ~1 km and a 50 W GPS satellite at 20,200 km.
        """
        wavelength = c / frequency
        return wavelength / (4 * np.pi * distance)

    P_gps_tx = 50.0   # GPS satellite EIRP, Watts
    P_jam_tx = 10.0   # each jammer transmit power, Watts

    # Received signal amplitude = sqrt(transmit power) × path-loss factor
    amp_gps  = np.sqrt(P_gps_tx) * path_loss_amplitude(dist_gps,  f0)
    amp_jam1 = np.sqrt(P_jam_tx) * path_loss_amplitude(dist_jam1, f0)
    amp_jam2 = np.sqrt(P_jam_tx) * path_loss_amplitude(dist_jam2, f0)

    def to_dBW(amplitude: float) -> float:
        """Convert amplitude to received power in dBW  (P = A², then 10·log10)."""
        return 10 * np.log10(amplitude**2 + 1e-300)

    # =========================================================================
    # 8. TIME VECTOR
    # =========================================================================

    t = np.arange(n_samples) / fs   # shape (n_samples,)
    # t[k] = k/fs : physical time of sample k.  At 10 MHz, 1000 samples = 100 µs.

    # =========================================================================
    # 9. SIGNAL WAVEFORMS
    # =========================================================================

    # GPS — BPSK-modulated IF tone.
    # Random ±1 chips decorrelate GPS from the jammers: without this, GPS and
    # any deterministic jammer at the same frequency would be coherent, causing
    # the covariance matrix to be rank-1 and MUSIC to fail.
    chips = rng.choice(np.array([-1.0, 1.0]), size=n_samples)
    s_gps = chips * np.exp(1j * 2 * np.pi * f_if * t)   # unit average power

    # --- Jammer base waveform (same type for all three spatial jammers) ------

    def _chips() -> np.ndarray:
        """Independent ±1 BPSK chip sequence — one call per jammer."""
        return rng.choice(np.array([-1.0, 1.0]), size=n_samples)

    if jammer_type == 'CW':
        # Continuous-wave: pure tone on the GPS IF, ×independent BPSK chips.
        # Without chips, three CW jammers at the same frequency are perfectly
        # coherent (rank-1 covariance) and MUSIC cannot resolve three directions.
        # Independent chips represent separate oscillator phase-noise histories
        # and make the three spatial jammers mutually uncorrelated.
        cw = np.exp(1j * 2 * np.pi * f_if * t)
        s_jam1 = _chips() * cw
        s_jam2 = _chips() * cw

    elif jammer_type == 'FMCW':
        # Linear chirp sweeps B = 10 MHz in T = 1 ms, spread across bandwidth.
        # Independent chips per jammer ensure three incoherent covariance ranks.
        B  = 10e6   # sweep bandwidth, Hz
        T  = 1e-3   # one sweep period, s
        chirp = np.exp(1j * 2 * np.pi * (f_if + (B / (2 * T)) * t) * t)
        s_jam1 = _chips() * chirp
        s_jam2 = _chips() * chirp

    elif jammer_type == 'Barrage':
        # Three independent bandpass noise realizations — each jammer transmits
        # its own noise-like waveform, ensuring full statistical independence.
        f_nyq = fs / 2
        f_lo  = max((f_if - 1e6) / f_nyq, 1e-4)
        f_hi  = min((f_if + 1e6) / f_nyq, 0.9999)
        b, a  = butter(4, [f_lo, f_hi], btype='band')

        def _barrage() -> np.ndarray:
            raw = (rng.standard_normal(n_samples)
                   + 1j * rng.standard_normal(n_samples)) / np.sqrt(2)
            out = lfilter(b, a, raw)
            return out / (np.std(out) + 1e-12)

        s_jam1 = _barrage()
        s_jam2 = _barrage()

    else:
        raise ValueError(
            f"Unknown jammer_type='{jammer_type}'. Choose 'CW', 'FMCW', or 'Barrage'."
        )

    # =========================================================================
    # 10. RECEIVED SIGNAL MATRIX
    # =========================================================================

    # np.outer(a, s)[m, k] = a[m] * s[k]
    # Combines the spatial fingerprint (steering vector) with the temporal
    # waveform.  Multiplying by the amplitude applies path loss + transmit power.
    X  = np.outer(a_gps,  amp_gps  * s_gps)
    X += np.outer(a_jam1, amp_jam1 * s_jam1)
    X += np.outer(a_jam2, amp_jam2 * s_jam2)

    # =========================================================================
    # 11. ADDITIVE WHITE GAUSSIAN NOISE  (thermal noise floor)
    # =========================================================================

    # Noise amplitude is set to half the GPS signal amplitude, placing the
    # thermal noise floor ≈ 6 dB below the (already very weak) GPS signal.
    # Real kTB at 290 K in 10 MHz is ≈ −134 dBW — similar to GPS received power.
    noise_amplitude = amp_gps * 0.5
    noise = noise_amplitude * (
        rng.standard_normal((4, n_samples))
        + 1j * rng.standard_normal((4, n_samples))
    ) / np.sqrt(2)
    X += noise    # X is now (4, n_samples) complex128

    # =========================================================================
    # 12. SAVE
    # =========================================================================

    np.save("array_data.npy", X)

    # =========================================================================
    # 13. CONSOLE OUTPUT — FULL SCENE SUMMARY
    # =========================================================================

    def deg(r: float) -> str:
        """Format radians as a signed degree string with 2 decimal places."""
        return f"{np.rad2deg(r):+.2f}°"

    print()
    print("=" * 65)
    print("  SCENE GEOMETRY")
    print("=" * 65)
    print(f"  Drone position       : {drone_pos.tolist()} m")
    print()
    print(f"  GPS satellite        : azimuth={deg(az_gps)}, elevation={deg(el_gps)}")
    print(f"                         distance={dist_gps/1e3:.1f} km, "
          f"received power={to_dBW(amp_gps):.1f} dBW")
    print()
    print(f"  Jammer 1 ({jammer_type:<7s})  : position={jammer1_pos.tolist()}")
    print(f"                         azimuth={deg(az_jam1)}, elevation={deg(el_jam1)}")
    print(f"                         distance={dist_jam1:.1f} m, "
          f"received power={to_dBW(amp_jam1):.1f} dBW")
    print()
    print(f"  Jammer 2 ({jammer_type:<7s})  : position={jammer2_pos.tolist()}")
    print(f"                         azimuth={deg(az_jam2)}, elevation={deg(el_jam2)}")
    print(f"                         distance={dist_jam2:.1f} m, "
          f"received power={to_dBW(amp_jam2):.1f} dBW")
    print()
    print("-" * 65)
    print(f"  Array geometry       : 2×2 URA, spacing d = {d*100:.2f} cm")
    print(f"  Wavelength λ         : {lam*100:.2f} cm  (GPS L1 = {f0/1e6:.2f} MHz)")
    print(f"  Jammer waveform      : {jammer_type}")
    print(f"  Output shape         : {X.shape}  (elements × samples)")
    print(f"  Data type            : {X.dtype}")
    print(f"  Saved to             : array_data.npy")
    print("=" * 65)
    print()

    return X


# =============================================================================
# QUICK-RUN  —  python generate_array_data.py [CW|FMCW|Barrage]
# =============================================================================
if __name__ == "__main__":
    jammer_type = sys.argv[1] if len(sys.argv) > 1 else 'CW'
    X = generate_array_data(jammer_type=jammer_type)

    print("First 3 samples of element 0  [position (0, 0)]:")
    print(f"  {X[0, :3]}")
    print("First 3 samples of element 3  [position (d, d)]:")
    print(f"  {X[3, :3]}")
    print("(Phase difference between elements encodes the 2D angle of arrival)")
