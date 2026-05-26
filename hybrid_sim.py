"""
hybrid_sim.py

Novel contribution: hybrid analog-digital GPS anti-jam beamformer.

Architecture comparison
-----------------------
Pure digital:  4 antennas → 4 ADCs (each ±adc_fs) → digital MVDR
Hybrid     :  4 antennas → analog pre-canceller → 4 ADCs → digital MVDR

The analog pre-canceller is a vector modulator: a hardware circuit that
multiplies an RF signal by a complex coefficient (amplitude × phase shift).
It performs a coarse spatial null toward the jammer direction BEFORE the ADC,
reducing the jammer amplitude that the ADC must accommodate.

Why does this matter?
---------------------
An ADC with full-scale FS can faithfully digitise signals up to ±FS.
If the jammer exceeds FS, the ADC clips: the output is a distorted square
wave instead of a sinusoid.  Clipping destroys the spatial phase information
that MVDR depends on — the covariance matrix becomes wrong, the null is lost.

The analog pre-canceller reduces the jammer by ~cancel_fraction (≈20 dB)
before the ADC, extending the jammer-free operating range by the same margin.

Key result
----------
SINR vs jammer power: hybrid curve stays above pure-digital by ~20 dB
in the clipping regime.  This is the extended dynamic range advantage.

Input  : (all signals generated internally — no external data file needed)
Output : hybrid_sim.png
"""

import numpy as np
import matplotlib.pyplot as plt


def hybrid_sim(
    n_elements:   int   = 4,           # antenna elements
    n_samples:    int   = 1000,        # IQ samples per trial
    fs:           float = 10e6,        # sample rate, Hz
    f_carrier:    float = 1575.42e6,   # GPS L1, Hz
    f_if:         float = 1e3,         # IF after downconversion, Hz
    theta_gps:    float = 0.0,         # GPS angle, degrees
    theta_jam:    float = 45.0,        # jammer angle, degrees
    adc_fs:       float = 5.0,         # ADC full-scale amplitude (±adc_fs)
    cancel_frac:  float = 0.90,        # analog cancellation fraction (0–1)
    jam_db_min:   float = 0.0,         # sweep start, dB above GPS
    jam_db_max:   float = 50.0,        # sweep end
    jam_db_step:  float = 1.0,         # sweep step
    seed:         int   = 42,          # base RNG seed
    save_fig:     str   = "hybrid_sim.png",
) -> dict:
    """
    Sweep jammer power from jam_db_min to jam_db_max dB above GPS.
    At each step compute output SINR for three beamforming strategies:

      1. Ideal MVDR        — infinite ADC dynamic range (theoretical ceiling)
      2. Pure digital MVDR — standard ADC with hard clipping at ±adc_fs
      3. Hybrid MVDR       — analog pre-cancel fraction → ADC → digital MVDR

    Parameters
    ----------
    adc_fs       : ADC saturation level.  Signals above this are clipped.
                   Set to match the expected GPS + noise RMS (≈1.4), giving
                   ~10 dB headroom.  Pure digital clips when jammer ≈ adc_fs.
    cancel_frac  : fraction of the jammer removed in the analog stage.
                   0.9 → 10% residual → 20 dB reduction before ADC.
                   In hardware this is limited by vector-modulator bit depth.

    Returns
    -------
    dict with keys 'jam_db', 'ideal', 'digital', 'hybrid' — SINR in dB.
    """

    # ==================================================================
    # ARRAY GEOMETRY  (identical in all scripts)
    # ==================================================================

    c   = 3e8
    lam = c / f_carrier                           # GPS L1 wavelength ≈ 0.190 m
    d   = lam / 2                                 # half-wavelength spacing

    def steering_vector(theta_deg: float) -> np.ndarray:
        """ULA steering vector for a plane wave from theta_deg."""
        theta = np.deg2rad(theta_deg)
        m     = np.arange(n_elements)
        return np.exp(1j * (2 * np.pi / lam) * d * m * np.sin(theta))

    a_gps = steering_vector(theta_gps)            # GPS look direction
    a_jam = steering_vector(theta_jam)            # jammer direction

    # ==================================================================
    # HELPER: DATA GENERATION
    # ==================================================================

    def generate_data(jam_db: float, rng_seed: int):
        """
        Generate 4-channel IQ array data for a given jammer power.

        Mirrors generate_array_data.py exactly:
          GPS  : BPSK chips × carrier (uncorrelated with jammer)
          Jammer: CW at IF with amplitude 10^(jam_db/20)
          Noise : complex AWGN, unit power per element
        """
        rng   = np.random.default_rng(rng_seed)
        t     = np.arange(n_samples) / fs

        chips = rng.choice(np.array([-1.0, 1.0]), size=n_samples)
        s_gps = chips * np.exp(1j * 2 * np.pi * f_if * t)          # BPSK GPS

        A_jam = 10 ** (jam_db / 20)
        s_jam = A_jam * np.exp(1j * 2 * np.pi * f_if * t)          # CW jammer

        X  = np.outer(a_gps, s_gps) + np.outer(a_jam, s_jam)
        X += (rng.standard_normal((n_elements, n_samples)) +
              1j * rng.standard_normal((n_elements, n_samples))) / np.sqrt(2)

        return X, A_jam

    # ==================================================================
    # HELPER: ADC HARD CLIPPING
    # ==================================================================

    def adc_clip(X: np.ndarray, fs_val: float) -> np.ndarray:
        """
        Hard-clip signal to ±fs_val on real and imaginary parts independently.

        This models ADC saturation: any input exceeding the converter's
        full-scale range is clamped to ±fs_val.  The resulting waveform is
        non-sinusoidal — it contains harmonics that corrupt the covariance.
        """
        return (np.clip(X.real, -fs_val, fs_val) +
                1j * np.clip(X.imag, -fs_val, fs_val))

    # ==================================================================
    # HELPER: ANALOG PRE-CANCELLATION
    # ==================================================================

    def analog_precancel(X: np.ndarray, a_null: np.ndarray,
                         fraction: float) -> np.ndarray:
        """
        Remove 'fraction' of the jammer component from every element before ADC.

        A vector modulator taps the signal from each antenna, shifts it in
        phase and amplitude to match the jammer's phase front, and subtracts
        it from the main signal path.  The subtraction happens in the analog
        (RF) domain — before the ADC sees it.

        Math: the jammer component across the array lies in the 1-D subspace
        spanned by a_null.  Project X onto that subspace and subtract:

            X_pre = X  −  fraction · a_null_unit (a_null_unit^H X)

        where a_null_unit = a_null / ‖a_null‖ has unit norm.

        Parameters
        ----------
        fraction : 0 = no cancellation, 1 = perfect cancellation
                   Real hardware: 0.85–0.93 (limited by vector-modulator bits)
        """
        # Normalise to unit magnitude so the projection has the right scaling
        a_n   = a_null / np.sqrt(np.real(a_null.conj() @ a_null))  # shape (4,)

        # Jammer projection: row = inner product of a_n^H with each time column
        # a_n.conj() @ X has shape (1000,); outer product restores (4, 1000)
        proj  = np.outer(a_n, a_n.conj() @ X)                      # (4, 1000)

        return X - fraction * proj

    # ==================================================================
    # HELPER: MVDR WEIGHT VECTOR
    # ==================================================================

    def compute_mvdr(R: np.ndarray, a_look: np.ndarray) -> np.ndarray:
        """
        MVDR weights:  w = R^{-1} a_look / (a_look^H R^{-1} a_look)

        Uses numpy.linalg.solve for numerical stability (avoids explicit R^{-1}).
        Falls back to matched-filter (w ∝ a_look) if R is singular.
        """
        try:
            u     = np.linalg.solve(R, a_look)            # R^{-1} a_look
            denom = np.real(a_look.conj() @ u)             # a^H R^{-1} a (real)
            if abs(denom) < 1e-14:
                raise np.linalg.LinAlgError("near-zero denominator")
            return u / denom
        except np.linalg.LinAlgError:
            # Degenerate: covariance too distorted → fall back to matched filter
            norm2 = np.real(a_look.conj() @ a_look)
            return a_look / norm2

    # ==================================================================
    # HELPER: ANALYTICAL SINR
    # ==================================================================

    def sinr_db(w: np.ndarray, a_s: np.ndarray,
                a_j: np.ndarray, A_j: float, sigma2: float = 1.0) -> float:
        """
        Signal-to-interference-plus-noise ratio at beamformer output.

            SINR = |w^H a_s|² · P_s  /  (|w^H a_j|² · P_j  +  σ² · ‖w‖²)

        where P_s = 1 (unit GPS power), P_j = A_j² (jammer power), σ² = noise.

        This formula is exact when the covariance used to compute w matches
        the true signal model.  When ADC clipping distorts the covariance,
        w is suboptimal — the formula still gives the correct output SINR
        for that (suboptimal) w.
        """
        P_signal  = abs(w.conj() @ a_s) ** 2                  # GPS gain (dimensionless)
        P_jammer  = abs(w.conj() @ a_j) ** 2 * A_j ** 2      # jammer power at output
        P_noise   = np.real(w.conj() @ w) * sigma2            # noise amplification
        sinr      = P_signal / (P_jammer + P_noise + 1e-20)
        return 10 * np.log10(sinr)

    # ==================================================================
    # PRE-COMPUTE EFFECTIVE GPS STEERING AFTER ANALOG PRE-CANCEL
    # ==================================================================

    # The analog pre-canceller projects out cancel_frac of the jammer direction.
    # Any signal with a component in the a_jam direction loses cancel_frac of it.
    # GPS (at 0°) is not orthogonal to jammer (45°), so it loses a small fraction.
    #
    # a_gps_eff = a_gps - cancel_frac * P_jam @ a_gps
    # where P_jam = a_n @ a_n^H is the jammer projection operator.
    #
    # This is the spatial fingerprint that GPS has in the PRE-CANCELLED signal.
    # The hybrid MVDR must use a_gps_eff as its look direction (not a_gps) to
    # correctly steer a unit-gain beam toward GPS in the pre-cancelled domain.
    a_n         = a_jam / np.sqrt(np.real(a_jam.conj() @ a_jam))   # unit-norm a_jam
    a_gps_eff   = a_gps - cancel_frac * a_n * (a_n.conj() @ a_gps) # shape (4,)

    # Pre-cancel also modifies the noise covariance (reduces noise in jammer direction).
    # R_noise_pre = sigma^2 * (I  -  cancel_frac*(2-cancel_frac) * P_jam)
    # For the SINR noise term: P_n = w^H R_noise_pre w
    #   = sigma^2 * (||w||^2  -  cancel_frac*(2-cancel_frac) * |w^H a_n|^2)
    cancel_sq   = cancel_frac * (2.0 - cancel_frac)   # = 0.9*1.1 = 0.99 for f=0.9

    # ==================================================================
    # MAIN SWEEP
    # ==================================================================

    jam_db_range = np.arange(jam_db_min, jam_db_max + jam_db_step / 2, jam_db_step)
    N = len(jam_db_range)

    sinr_ideal   = np.zeros(N)
    sinr_digital = np.zeros(N)
    sinr_hybrid  = np.zeros(N)

    for i, jam_db in enumerate(jam_db_range):

        # Fresh data for each jammer level (different seed per step)
        X, A_jam = generate_data(jam_db, rng_seed=seed + i)

        # ---- PATH 1: Ideal MVDR (no ADC, infinite dynamic range) --------
        # Upper-bound baseline: what MVDR achieves without any hardware limit.
        R_ideal        = (X @ X.conj().T) / n_samples
        w_ideal        = compute_mvdr(R_ideal, a_gps)
        sinr_ideal[i]  = sinr_db(w_ideal, a_gps, a_jam, A_jam)

        # ---- PATH 2: Pure digital MVDR (ADC clipping before processing) --
        # All 4 channels digitised at ±adc_fs before any processing.
        # When jammer amplitude > adc_fs, the ADC output is clipped → wrong R.
        X_dig          = adc_clip(X, adc_fs)
        R_dig          = (X_dig @ X_dig.conj().T) / n_samples
        w_dig          = compute_mvdr(R_dig, a_gps)
        sinr_digital[i] = sinr_db(w_dig, a_gps, a_jam, A_jam)

        # ---- PATH 3: Hybrid (analog pre-cancel → ADC → digital MVDR) -----

        # Step A — Analog domain: vector modulator removes cancel_frac of jammer
        # BEFORE the ADC.  The jammer direction (45°) was found by MUSIC in
        # the previous script.  No digitisation has happened yet.
        X_pre         = analog_precancel(X, a_jam, cancel_frac)
        # Residual jammer amplitude after analog stage
        A_jam_residual = (1.0 - cancel_frac) * A_jam

        # Step B — ADC: digitise the pre-cancelled signal.
        # Because the jammer was reduced by 20 dB, the ADC input is well
        # within ±adc_fs for a much wider range of jammer powers.
        X_hyb         = adc_clip(X_pre, adc_fs)

        # Step C — Digital MVDR on the reduced-jammer digitised data.
        # KEY: use a_gps_eff as the look direction — GPS appears at that spatial
        # fingerprint in the pre-cancelled signal, not at the original a_gps.
        # Using the wrong look direction causes the weights to steer into the
        # low-noise jammer null, producing very large ||w||² and terrible SINR.
        R_hyb         = (X_hyb @ X_hyb.conj().T) / n_samples
        w_hyb         = compute_mvdr(R_hyb, a_gps_eff)

        # Hybrid SINR: correct for (1) effective GPS direction, (2) modified noise.
        # P_signal = |w^H a_gps_eff|²  — GPS power (= 1 by MVDR constraint)
        # P_jammer = |w^H a_jam|²  ×  A_jam_residual²
        # P_noise  = sigma^2 × (||w||² − cancel_sq × |w^H a_n|²)
        #            ↑ noise is reduced in the jammer direction by the pre-cancel
        P_s = abs(w_hyb.conj() @ a_gps_eff) ** 2
        P_j = abs(w_hyb.conj() @ a_jam) ** 2 * A_jam_residual ** 2
        P_n = (np.real(w_hyb.conj() @ w_hyb)
               - cancel_sq * abs(w_hyb.conj() @ a_n) ** 2)   # sigma²=1 absorbed
        sinr_hybrid[i] = 10 * np.log10(P_s / (P_j + max(P_n, 1e-12) + 1e-20))

    # ==================================================================
    # PRINT SUMMARY TABLE
    # ==================================================================

    analog_reduction_db = -20 * np.log10(1 - cancel_frac)   # positive dB
    adc_clip_db_digital = 20 * np.log10(adc_fs)             # jammer hits FS
    adc_clip_db_hybrid  = adc_clip_db_digital + analog_reduction_db

    print("=" * 65)
    print("Hybrid Anti-Jam Sim  —  SINR vs Jammer Power Sweep")
    print("=" * 65)
    print(f"  ADC full-scale       : ±{adc_fs:.1f}  "
          f"(digital clips at >{adc_clip_db_digital:.0f} dB jammer)")
    print(f"  Analog cancel        : {cancel_frac*100:.0f}%  "
          f"({analog_reduction_db:.1f} dB jammer reduction before ADC)")
    print(f"  Hybrid clips at      : >{adc_clip_db_hybrid:.0f} dB jammer")
    print(f"  Extended headroom    : +{analog_reduction_db:.0f} dB\n")

    # Print every 5 dB
    step5 = max(1, int(5.0 / jam_db_step))
    header = f"  {'Jam(dB)':>8}  {'Ideal':>8}  {'Digital':>8}  {'Hybrid':>8}  {'Δ(dB)':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for j in range(0, N, step5):
        gap = sinr_hybrid[j] - sinr_digital[j]
        print(f"  {jam_db_range[j]:8.0f}  "
              f"{sinr_ideal[j]:8.1f}  "
              f"{sinr_digital[j]:8.1f}  "
              f"{sinr_hybrid[j]:8.1f}  "
              f"{gap:8.1f}")

    # Crossover: first point where SINR drops below 0 dB
    threshold = 0.0
    dig_mask  = sinr_digital < threshold
    hyb_mask  = sinr_hybrid  < threshold
    dig_cross = (jam_db_range[np.argmax(dig_mask)]
                 if dig_mask.any() else jam_db_max)
    hyb_cross = (jam_db_range[np.argmax(hyb_mask)]
                 if hyb_mask.any() else jam_db_max)

    print(f"\n  Pure digital SINR < {threshold} dB at jammer: {dig_cross:.0f} dB")
    print(f"  Hybrid SINR       < {threshold} dB at jammer: {hyb_cross:.0f} dB")
    print(f"  Hybrid advantage  : +{hyb_cross - dig_cross:.0f} dB dynamic range extension")

    # ==================================================================
    # PLOT  — two panels
    # ==================================================================

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
    fig.suptitle(
        "Hybrid Analog-Digital Anti-Jam  |  4-Element ULA, GPS L1 (1575.42 MHz)",
        fontsize=13, fontweight='bold'
    )

    # ---- Panel 1: SINR vs Jammer Power  (THE main result) ---------------

    ax1.plot(jam_db_range, sinr_ideal,
             color='limegreen', linewidth=2.2, linestyle='-',
             label='Ideal MVDR (no ADC limit)', zorder=4)
    ax1.plot(jam_db_range, sinr_digital,
             color='tomato',    linewidth=2.2, linestyle='-',
             label=f'Pure digital MVDR  (ADC ±{adc_fs:.0f})', zorder=3)
    ax1.plot(jam_db_range, sinr_hybrid,
             color='royalblue', linewidth=2.5, linestyle='-',
             label=f'Hybrid ({int(cancel_frac*100)}% analog cancel + digital MVDR)', zorder=5)

    # 0 dB SINR threshold line
    ax1.axhline(0, color='black', linestyle=':', linewidth=1.0, alpha=0.5,
                label='SINR = 0 dB threshold')

    # Vertical markers at crossover points
    ax1.axvline(dig_cross, color='tomato',    linestyle='--',
                linewidth=1.4, alpha=0.75,
                label=f'Digital fails: {dig_cross:.0f} dB')
    ax1.axvline(hyb_cross, color='royalblue', linestyle='--',
                linewidth=1.4, alpha=0.75,
                label=f'Hybrid fails:  {hyb_cross:.0f} dB')

    # Shade the hybrid advantage window
    if hyb_cross > dig_cross:
        ax1.axvspan(dig_cross, hyb_cross, alpha=0.07, color='royalblue',
                    label=f'Hybrid gain: +{hyb_cross-dig_cross:.0f} dB headroom')

    # ADC onset annotations
    ax1.axvline(adc_clip_db_digital, color='tomato', linestyle=':',
                linewidth=1.0, alpha=0.5)
    ax1.text(adc_clip_db_digital + 0.3, sinr_ideal.max() * 0.88,
             f'ADC clips\n(digital >{adc_clip_db_digital:.0f} dB)',
             fontsize=8, color='tomato', style='italic')

    ax1.axvline(adc_clip_db_hybrid, color='steelblue', linestyle=':',
                linewidth=1.0, alpha=0.5)
    ax1.text(adc_clip_db_hybrid + 0.3, sinr_ideal.max() * 0.62,
             f'ADC clips\n(hybrid >{adc_clip_db_hybrid:.0f} dB)',
             fontsize=8, color='steelblue', style='italic')

    ax1.set_xlabel("Jammer Power (dB above GPS)", fontsize=12)
    ax1.set_ylabel("Output SINR (dB)", fontsize=12)
    ax1.set_title("Output SINR vs Jammer Power\n(novel result: hybrid stays high ~20 dB longer)",
                  fontsize=11)
    ax1.set_xlim(jam_db_min, jam_db_max)
    ax1.legend(fontsize=8.5, loc='lower left')
    ax1.grid(True, alpha=0.3)

    # ---- Panel 2: Waveform snapshot at high jammer power -----------------
    # Show what the ADC input looks like at jam_db = 30 dB:
    # — without analog cancel: clips heavily
    # — with analog cancel: fits within ADC range

    snapshot_db = 30.0
    X_snap, _ = generate_data(snapshot_db, rng_seed=seed + 999)
    X_pre_snap = analog_precancel(X_snap, a_jam, cancel_frac)

    n_show  = 100                                      # samples to display
    t_us    = np.arange(n_show) / fs * 1e6            # time axis in µs
    ch      = 0                                        # display element 0

    x_raw   = np.real(X_snap[ch,    :n_show])
    x_pre   = np.real(X_pre_snap[ch, :n_show])

    rms_raw = np.std(np.real(X_snap[ch, :]))
    rms_pre = np.std(np.real(X_pre_snap[ch, :]))

    ax2.plot(t_us, x_raw, color='tomato',    linewidth=1.1, alpha=0.9,
             label=f'Before analog cancel  (RMS = {rms_raw:.1f})')
    ax2.plot(t_us, x_pre, color='royalblue', linewidth=1.2,
             label=f'After  analog cancel  (RMS = {rms_pre:.2f})')

    # ADC full-scale lines
    ax2.axhline(+adc_fs, color='black', linestyle='--', linewidth=1.0, alpha=0.7,
                label=f'ADC full-scale ±{adc_fs}')
    ax2.axhline(-adc_fs, color='black', linestyle='--', linewidth=1.0, alpha=0.7)

    # Shade the clipping zones (above +FS and below -FS)
    y_ceil = max(x_raw.max() + 1, adc_fs + 1)
    y_floor = min(x_raw.min() - 1, -adc_fs - 1)
    ax2.fill_between(t_us,  adc_fs, y_ceil,  alpha=0.12, color='tomato',
                     label='Clipping zone (digital)')
    ax2.fill_between(t_us, y_floor, -adc_fs, alpha=0.12, color='tomato')

    ax2.set_xlabel("Time (µs)", fontsize=12)
    ax2.set_ylabel("Amplitude", fontsize=12)
    ax2.set_title(f"ADC Input at {snapshot_db:.0f} dB Jammer (Element 0)\n"
                  f"Red clips the ADC — blue (analog-cancelled) fits within ±{adc_fs}",
                  fontsize=11)
    ax2.set_ylim(y_floor * 0.9, y_ceil * 0.9)
    ax2.legend(fontsize=9, loc='upper right')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_fig, dpi=150, bbox_inches='tight')
    plt.show()
    print(f"\n  Saved plot : {save_fig}")

    return {
        'jam_db':  jam_db_range,
        'ideal':   sinr_ideal,
        'digital': sinr_digital,
        'hybrid':  sinr_hybrid,
    }


# ======================================================================
# QUICK RUN  —  python hybrid_sim.py
# ======================================================================
if __name__ == "__main__":
    results = hybrid_sim()
