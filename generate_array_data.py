"""
generate_array_data.py

Synthesise 4-channel complex IQ data for a 4-element uniform linear array
(ULA) receiving a GPS satellite and a single continuous-wave (CW) jammer.

Physical scenario
-----------------
  GPS L1 satellite  : 0° (broadside, directly above array), unit amplitude
  CW jammer         : 45°, 30 dB stronger than GPS (amplitude factor ≈ 31.6×)
  Thermal noise     : complex AWGN, unit power per antenna element

This file is the data-generation front-end of the anti-jam pipeline.
Every downstream script (MUSIC, MVDR, hybrid) loads array_data.npy.
"""

import numpy as np


def generate_array_data(
    n_elements: int   = 4,             # number of antenna elements in the ULA
    n_samples:  int   = 1000,          # IQ samples recorded per channel
    fs:         float = 10e6,          # ADC sample rate, Hz (10 MHz)
    f_carrier:  float = 1575.42e6,     # GPS L1 carrier frequency, Hz
    f_if:       float = 1e3,           # post-downconversion IF, Hz (1 kHz)
    theta_gps:  float = 0.0,           # GPS angle of arrival, degrees
    theta_jam:  float = 45.0,          # jammer angle of arrival, degrees
    jam_db:     float = 30.0,          # jammer power above GPS, dB
    seed:       int   = 42,            # random seed for reproducibility
) -> np.ndarray:
    """
    Generate synthetic 4×1000 complex IQ array data.

    Narrowband ULA signal model
    ---------------------------
    The received data matrix X has shape (n_elements, n_samples).
    Each column is one time snapshot:

        x(t) = a(θ_gps)·s_gps(t)  +  a(θ_jam)·s_jam(t)  +  n(t)

    where
        a(θ) = steering vector — the spatial phase gradient across elements
               for a plane wave arriving from angle θ
        s(t) = complex sinusoid at the IF frequency (the signal waveform)
        n(t) = complex AWGN (thermal noise)

    Parameters
    ----------
    n_elements : int   — number of antenna elements (default 4)
    n_samples  : int   — IQ samples per channel (default 1000)
    fs         : float — ADC sample rate in Hz (default 10 MHz)
    f_carrier  : float — GPS L1 frequency used to compute wavelength / spacing
    f_if       : float — IF frequency of the digitised signal (1 kHz)
    theta_gps  : float — angle of GPS satellite, degrees from broadside
    theta_jam  : float — angle of jammer, degrees from broadside
    jam_db     : float — jammer-to-signal power ratio in dB
    seed       : int   — NumPy RNG seed

    Returns
    -------
    X : np.ndarray, shape (n_elements, n_samples), dtype complex128
        Row m holds the complex IQ time series recorded by antenna m (0-indexed).

    Side effect
    -----------
    Saves X to 'array_data.npy' in the working directory.
    """

    # --- reproducible random number generator ----------------------------
    rng = np.random.default_rng(seed)

    # =====================================================================
    # 1. PHYSICAL CONSTANTS AND ARRAY GEOMETRY
    # =====================================================================

    c   = 3e8                   # speed of light in vacuum, m/s
    lam = c / f_carrier         # GPS L1 wavelength: 3e8 / 1575.42e6 ≈ 0.1903 m
    d   = lam / 2               # half-wavelength element spacing ≈ 0.0951 m
    #
    # Why half-wavelength?  It is the largest spacing that avoids spatial
    # aliasing (grating lobes) — just like Nyquist in time-domain sampling.

    # =====================================================================
    # 2. TIME VECTOR  (discrete samples after downconversion to IF)
    # =====================================================================

    t = np.arange(n_samples) / fs
    # t[k] = k / fs  gives the physical time of the k-th sample in seconds.
    # With fs = 10 MHz and n_samples = 1000, the recording spans 100 µs.

    # =====================================================================
    # 3. SIGNAL WAVEFORMS  (complex baseband / IF)
    # =====================================================================

    # GPS signal — BPSK-modulated carrier: random ±1 chips on the IF tone.
    # Real GPS L1 C/A code is a 1023-chip BPSK sequence; random ±1 chips
    # capture the key statistical property: zero cross-correlation with any
    # deterministic signal (like the CW jammer).  Without this, GPS and jammer
    # would be perfectly coherent → rank-1 covariance → MUSIC fails.
    chips = rng.choice(np.array([-1.0, 1.0]), size=n_samples)   # ±1 BPSK symbols
    s_gps = chips * np.exp(1j * 2 * np.pi * f_if * t)
    # Unit average power: E[|chip|²] = 1,  |e^jφ|² = 1  →  E[|s_gps|²] = 1
    # Shape: (n_samples,) = (1000,)

    # Jammer — same frequency as GPS (worst case: coherent CW jammer on L1).
    # Convert the dB power advantage to a linear amplitude ratio:
    #   Power  dB = 10 · log10(P_jam / P_gps)
    #   Amplitude dB = 20 · log10(A_jam / A_gps)   [power ∝ amplitude²]
    #   → A_jam = 10^(jam_db / 20)
    A_jam = 10 ** (jam_db / 20)             # 30 dB → amplitude factor ≈ 31.62
    s_jam = A_jam * np.exp(1j * 2 * np.pi * f_if * t)
    # Shape: (n_samples,) = (1000,)

    # =====================================================================
    # 4. STEERING VECTORS  (spatial fingerprints of each source direction)
    # =====================================================================

    def steering_vector(theta_deg: float) -> np.ndarray:
        """
        Return the ULA steering vector for a plane wave from angle theta_deg.

        A plane wave hitting a ULA at angle θ (measured from broadside) takes
        extra time to reach each successive element.  That extra path length
        for element m is:  Δr_m = d · m · sin(θ)
        Converting path length to phase shift:
            φ_m = (2π / λ) · d · m · sin(θ)
                = π · m · sin(θ)      [substituting d = λ/2]

        The steering vector a(θ) packs all these phases into one array:
            a(θ) = [e^(j·0), e^(j·φ_1), e^(j·φ_2), e^(j·φ_3)]
                 = [1,  e^(jπsinθ),  e^(j2πsinθ),  e^(j3πsinθ)]

        Shape: (n_elements,) = (4,)
        """
        theta = np.deg2rad(theta_deg)           # convert degrees → radians
        m     = np.arange(n_elements)           # element indices: [0, 1, 2, 3]
        phase = (2 * np.pi / lam) * d * m * np.sin(theta)
        return np.exp(1j * phase)               # complex phasor per element

    a_gps = steering_vector(theta_gps)   # GPS spatial fingerprint
    a_jam = steering_vector(theta_jam)   # jammer spatial fingerprint

    # =====================================================================
    # 5. RECEIVED SIGNAL MATRIX  (combine spatial + temporal structure)
    # =====================================================================

    # np.outer(a, s) produces an (n_elements, n_samples) matrix where
    # entry [m, k] = a[m] * s[k].
    # Think of it as: element m's amplitude/phase × the signal waveform
    # at time k.  Two outer products, one per source, then add.

    X  = np.outer(a_gps, s_gps)    # GPS contribution:    shape (4, 1000)
    X += np.outer(a_jam, s_jam)    # jammer contribution: shape (4, 1000)

    # =====================================================================
    # 6. ADDITIVE WHITE GAUSSIAN NOISE  (thermal noise floor)
    # =====================================================================

    # Complex AWGN with unit total power per sample:
    #   real part  ~ N(0, 1/√2)
    #   imag part  ~ N(0, 1/√2)
    #   total power = 1/2 + 1/2 = 1  (unit noise power)
    #
    # At unit noise power and unit GPS amplitude (A_gps = 1), the GPS SNR
    # is 0 dB — GPS is barely at the noise floor, jammer is 30 dB above it.
    # This reflects the real-world GPS anti-jam challenge.
    noise  = (rng.standard_normal((n_elements, n_samples))
            + 1j * rng.standard_normal((n_elements, n_samples))) / np.sqrt(2)
    # Build real + j·imag in one expression so NumPy creates a complex128
    # array from the start — avoids an in-place cast error.

    X += noise                      # final received signal = signal + noise

    # =====================================================================
    # 7. SAVE  +  DIAGNOSTIC SUMMARY
    # =====================================================================

    np.save("array_data.npy", X)

    print("=" * 50)
    print("generate_array_data  — done")
    print("=" * 50)
    print(f"  Array shape     : {X.shape}  (elements × samples)")
    print(f"  Data type       : {X.dtype}")
    print(f"  GPS angle       : {theta_gps}°")
    print(f"  GPS steering    : {np.round(a_gps, 3)}")
    print(f"  Jammer angle    : {theta_jam}°")
    print(f"  Jammer steering : {np.round(a_jam, 3)}")
    print(f"  Jammer amplitude: {A_jam:.2f}×  ({jam_db} dB above GPS)")
    print(f"  Wavelength      : {lam*100:.2f} cm  |  spacing d: {d*100:.2f} cm")
    print(f"  Saved to        : array_data.npy")

    return X


# =========================================================================
# QUICK-RUN  —  python generate_array_data.py
# =========================================================================
if __name__ == "__main__":
    X = generate_array_data()

    # Show a tiny slice of the raw IQ data so you can see it's working
    print("\nFirst 3 samples of element 0 (antenna 1):")
    print(f"  {X[0, :3]}")
    print("First 3 samples of element 1 (antenna 2):")
    print(f"  {X[1, :3]}")
    print("(Notice the different phases — that's the steering vector at work)")
