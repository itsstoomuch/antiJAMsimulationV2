"""
hybrid_sim.py

Hybrid analog-digital GPS anti-jam beamformer — 3-jammer 2×2 URA scenario.

ADC physics (fixed, not dynamic)
---------------------------------
  GPS_AMPLITUDE = 1.0   (reference level)
  ADC_FS        = 5.0   (5× GPS amplitude, constant for all sweep steps)

  At 30 dB jammer: jam_amplitude = 31.6 >> ADC_FS = 5.0 → clips hard
  Digital: full signal → ADC → massively clipped → MVDR fails
  Hybrid:  90% pre-cancel × 3 jammers → residual ≈ 3×0.1×31.6 ≈ 9.5 at el.0
           still clips at 30 dB but far less than digital

Scene geometry (from generate_array_data.py)
---------------------------------------------
  Drone  : [0, 0, 100] m
  GPS    : az=0°, el=0°
  Jammer 1 : az=+30.96°  el=−9.73°
  Jammer 2 : az=+165.96° el=−6.93°
  Jammer 3 : az=−71.57°  el=−4.53°
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')           # non-interactive: show() is a no-op
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# Physical constants
GPS_AMPLITUDE = 1.0
ADC_FS        = 5.0 * GPS_AMPLITUDE     # FIXED — not scaled by jammer power
NOISE_AMP     = 0.1 * GPS_AMPLITUDE     # thermal noise floor
NOISE_POWER   = NOISE_AMP ** 2          # per element

# True jammer azimuths + elevations from 3D geometry
JAM_AZIMUTHS = np.array([ 30.96,  165.96, -71.57])
JAM_ELEVS    = np.array([ -9.73,   -6.93,  -4.53])
JAM_COLORS   = ['tomato', 'darkorange', 'mediumpurple']


def hybrid_sim(
    n_elements:  int   = 4,
    n_samples:   int   = 1000,
    fs:          float = 10e6,
    f_carrier:   float = 1575.42e6,
    f_if:        float = 1e3,
    cancel_frac: float = 0.90,     # analog pre-cancel fraction per jammer
    jam_db_min:  float = 0.0,
    jam_db_max:  float = 50.0,
    jam_db_step: float = 1.0,
    seed:        int   = 42,
    save_fig:    str   = "hybrid_sim.png",
) -> dict:
    """
    Sweep jammer power 0–50 dB above GPS, compare three MVDR paths.

    ADC_FS = 5.0 × GPS_AMPLITUDE (FIXED).  At high jammer powers the
    full signal saturates the ADC; the hybrid pre-canceller reduces
    jammer power at the ADC input, extending the clipping-free range.
    """

    # ==========================================================================
    # ARRAY GEOMETRY
    # ==========================================================================

    c   = 3e8
    lam = c / f_carrier
    d   = lam / 2

    elem_pos = np.array([
        [0, 0, 0],
        [d, 0, 0],
        [0, d, 0],
        [d, d, 0],
    ], dtype=float)

    def steering_vector(az_deg: float, el_deg: float) -> np.ndarray:
        az   = np.deg2rad(az_deg)
        el   = np.deg2rad(el_deg)
        unit = np.array([np.cos(el)*np.cos(az),
                         np.cos(el)*np.sin(az),
                         np.sin(el)])
        phase = (2 * np.pi / lam) * (elem_pos @ unit)
        gain  = np.sqrt(max(np.cos(el), 0.0))
        return gain * np.exp(1j * phase)

    a_gps  = steering_vector(0.0, 0.0)
    a_jams = [steering_vector(az, el)
              for az, el in zip(JAM_AZIMUTHS, JAM_ELEVS)]

    # ==========================================================================
    # HELPERS
    # ==========================================================================

    def mvdr_weights(R: np.ndarray, a_look: np.ndarray) -> np.ndarray:
        n    = R.shape[0]
        load = 1e-4 * np.trace(R).real / n
        u    = np.linalg.solve(R + load * np.eye(n), a_look)
        denom = np.real(a_look.conj() @ u)
        return u / denom if abs(denom) > 1e-12 else np.zeros(n, dtype=complex)

    def adc_clip(X: np.ndarray) -> np.ndarray:
        """Hard clip to ADC_FS = 5.0 (fixed)."""
        return (np.clip(X.real, -ADC_FS, ADC_FS) +
                1j * np.clip(X.imag, -ADC_FS, ADC_FS))

    def measure_sinr(w, jam_amplitude: float,
                     a_gps_use=None, a_jams_use=None) -> float:
        """
        SINR from the true signal model.

        For ideal/digital: a_gps_use=a_gps, a_jams_use=a_jams (originals).
          GPS_out = |w^H a_gps|^2 × GPS_AMPLITUDE^2 = 1 (MVDR constraint)

        For hybrid: a_gps_use=a_gps_eff, a_jams_use=a_jams_eff (effective).
          GPS_out = |w^H a_gps_eff|^2 × GPS_AMPLITUDE^2 = 1 (MVDR constraint)
          JAM_out uses a_jk_eff ≈ 0.1×a_jk (post pre-cancel, 20 dB reduction)

        Using original a_gps for the hybrid would give |w3^H a_gps|^2 << 1
        because the MVDR constraint is on a_gps_eff, not a_gps — a known
        spatial-correlation artefact of aggressive pre-cancellation on a
        small 4-element array.
        """
        if a_gps_use  is None: a_gps_use  = a_gps
        if a_jams_use is None: a_jams_use = a_jams

        gps_out   = abs(w.conj() @ a_gps_use) ** 2 * GPS_AMPLITUDE ** 2
        jam_out   = sum(abs(w.conj() @ aj) ** 2 * jam_amplitude ** 2
                        for aj in a_jams_use)
        noise_out = np.real(w.conj() @ w) * NOISE_POWER
        return 10 * np.log10(
            max(gps_out, 1e-30) / (jam_out + noise_out + 1e-30)
        )

    # ==========================================================================
    # SWEEP
    # ==========================================================================

    jam_db_range = np.arange(jam_db_min, jam_db_max + jam_db_step * 0.5, jam_db_step)
    n_steps      = len(jam_db_range)

    sinr_ideal   = np.zeros(n_steps)
    sinr_digital = np.zeros(n_steps)
    sinr_hybrid  = np.zeros(n_steps)

    rng = np.random.default_rng(seed)
    t   = np.arange(n_samples) / fs

    # GPS: pure CW at IF
    s_gps = GPS_AMPLITUDE * np.exp(1j * 2 * np.pi * f_if * t)

    X_snap_raw = None
    X_snap_pre = None

    for i, jdB in enumerate(jam_db_range):
        jam_amplitude = GPS_AMPLITUDE * 10 ** (jdB / 20.0)

        # Each jammer: CW at IF, independent BPSK chips for incoherence
        s_jams = []
        for _ in range(3):
            chips = rng.choice(np.array([-1.0, 1.0]), size=n_samples)
            s_jams.append(jam_amplitude * chips *
                          np.exp(1j * 2 * np.pi * f_if * t))

        # Build array data matrix
        X = np.outer(a_gps, s_gps)
        for aj, sj in zip(a_jams, s_jams):
            X += np.outer(aj, sj)

        # Thermal noise
        X += NOISE_AMP * (
            rng.standard_normal((n_elements, n_samples)) +
            1j * rng.standard_normal((n_elements, n_samples))
        ) / np.sqrt(2)

        # -- PATH 1: Ideal MVDR (no ADC) ---------------------------------------
        R1 = (X @ X.conj().T) / n_samples
        w1 = mvdr_weights(R1, a_gps)
        sinr_ideal[i] = measure_sinr(w1, jam_amplitude)

        # -- PATH 2: Pure digital — clip full signal at ADC_FS = 5.0 ----------
        X_clip = adc_clip(X)
        R2     = (X_clip @ X_clip.conj().T) / n_samples
        w2     = mvdr_weights(R2, a_gps)
        sinr_digital[i] = measure_sinr(w2, jam_amplitude)

        # -- PATH 3: Hybrid — 90% pre-cancel each jammer, then clip -----------
        # Track effective GPS and jammer steering vectors through each
        # cancellation step so SINR is measured with the correct vectors.
        X_pre      = X.copy()
        a_gps_eff  = a_gps.copy()
        a_jams_eff = [aj.copy() for aj in a_jams]   # will approach 0.1 × a_jk

        for aj in a_jams:
            a_n   = aj / np.linalg.norm(aj)
            proj  = a_n.conj() @ X_pre
            X_pre = X_pre - cancel_frac * np.outer(a_n, proj)
            # Update effective GPS and every jammer vector
            a_gps_eff = a_gps_eff - cancel_frac * a_n * (a_n.conj() @ a_gps_eff)
            for k in range(3):
                a_jams_eff[k] = (a_jams_eff[k]
                                 - cancel_frac * a_n * (a_n.conj() @ a_jams_eff[k]))

        X_pre_clip = adc_clip(X_pre)
        R3         = (X_pre_clip @ X_pre_clip.conj().T) / n_samples
        w3         = mvdr_weights(R3, a_gps_eff)

        # Hybrid SINR uses effective vectors:
        #   GPS_out = |w3^H a_gps_eff|^2 = 1 (by MVDR constraint) → GPS_AMPLITUDE^2
        #   JAM_out uses a_jk_eff ≈ 0.1 × a_jk (20 dB pre-reduction)
        sinr_hybrid[i] = measure_sinr(w3, jam_amplitude,
                                      a_gps_use=a_gps_eff,
                                      a_jams_use=a_jams_eff)

        # Save snapshot for ADC subplot
        if abs(jdB - 30.0) < 0.5 and X_snap_raw is None:
            X_snap_raw = X.copy()
            X_snap_pre = X_pre.copy()

    # ==========================================================================
    # DIAGNOSTIC TABLE
    # ==========================================================================

    check_levels = [0, 10, 20, 30]
    print()
    print("══════════════════════════════════════════════════════════")
    print("  HYBRID SIM — 3-Jammer URA  |  ADC_FS = 5.0 (fixed)")
    print("══════════════════════════════════════════════════════════")
    print(f"  {'jdB':>4}  {'Ideal':>8}  {'Digital':>8}  {'Hybrid':>8}  {'Δ(H-D)':>8}")
    print(f"  {'-'*4}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}")
    for jdB in check_levels:
        idx = int(round((jdB - jam_db_min) / jam_db_step))
        si  = sinr_ideal[idx]
        sd  = sinr_digital[idx]
        sh  = sinr_hybrid[idx]
        print(f"  {jdB:4.0f}  {si:+8.1f}  {sd:+8.1f}  {sh:+8.1f}  {sh-sd:+8.1f} dB")

    # Full summary
    def first_fail(arr):
        m = arr < 0.0
        return jam_db_range[np.argmax(m)] if m.any() else None

    fail_dig = first_fail(sinr_digital)
    fail_hyb = first_fail(sinr_hybrid)
    idx30    = np.argmin(np.abs(jam_db_range - 30.0))

    print()
    print(f"  At 30 dB design point:")
    print(f"    Ideal SINR    : {sinr_ideal[idx30]:+.1f} dB")
    print(f"    Digital SINR  : {sinr_digital[idx30]:+.1f} dB")
    print(f"    Hybrid SINR   : {sinr_hybrid[idx30]:+.1f} dB")
    print(f"    Improvement   : {sinr_hybrid[idx30] - sinr_digital[idx30]:+.1f} dB")
    if fail_dig is not None:
        print(f"  Digital fails at : {fail_dig:.0f} dB")
    else:
        print(f"  Digital fails at : never (within sweep)")
    if fail_hyb is not None:
        print(f"  Hybrid fails at  : {fail_hyb:.0f} dB")
    else:
        print(f"  Hybrid fails at  : never (within sweep)")
    if fail_dig is not None and fail_hyb is not None:
        print(f"  Extended range   : {fail_hyb - fail_dig:.0f} dB")
    print("══════════════════════════════════════════════════════════")
    print()

    # ==========================================================================
    # PLOT
    # ==========================================================================

    fig = plt.figure(figsize=(14, 5))
    fig.suptitle(
        "Hybrid Analog-Digital GPS Anti-Jam  |  3-Jammer 2×2 URA"
        f"  |  ADC_FS = {ADC_FS:.0f}",
        fontsize=13, fontweight='bold'
    )
    gs  = gridspec.GridSpec(1, 2, width_ratios=[1.8, 1.0], wspace=0.35)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])

    # ── Panel 1: SINR vs Jammer Power ─────────────────────────────────────────
    ax1.plot(jam_db_range, sinr_ideal,
             color='limegreen', lw=2.0, label='Ideal MVDR (no ADC limit)')
    ax1.plot(jam_db_range, sinr_digital,
             color='tomato',    lw=2.0, label='Pure digital MVDR')
    ax1.plot(jam_db_range, sinr_hybrid,
             color='royalblue', lw=2.0,
             label=f'Hybrid (90% cancel ×3 jammers)')

    ax1.axhline(0, color='black', linestyle=':', lw=1.2,
                label='SINR = 0 dB threshold')
    ax1.fill_between(jam_db_range, sinr_digital, sinr_hybrid,
                     where=(sinr_hybrid > sinr_digital),
                     alpha=0.15, color='royalblue', label='Hybrid advantage')

    if fail_dig is not None:
        ax1.axvline(fail_dig, color='tomato', linestyle='--', lw=1.2, alpha=0.7)
        ax1.annotate(f'Digital fails\n@ {fail_dig:.0f} dB',
                     xy=(fail_dig, 0), xytext=(fail_dig - 13, -18),
                     fontsize=8.5, color='tomato', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='tomato', lw=1.0))
    if fail_hyb is not None:
        ax1.axvline(fail_hyb, color='royalblue', linestyle='--', lw=1.2, alpha=0.7)
        ax1.annotate(f'Hybrid fails\n@ {fail_hyb:.0f} dB',
                     xy=(fail_hyb, 0), xytext=(fail_hyb + 1, -18),
                     fontsize=8.5, color='royalblue', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='royalblue', lw=1.0))

    ax1.axvline(30, color='gray', linestyle=':', lw=1.0)
    ax1.annotate(
        f'30 dB design pt\nHybrid: {sinr_hybrid[idx30]:+.0f} dB\n'
        f'Digital: {sinr_digital[idx30]:+.0f} dB',
        xy=(30, sinr_hybrid[idx30]),
        xytext=(34, sinr_hybrid[idx30] - 5),
        fontsize=8, color='royalblue',
        arrowprops=dict(arrowstyle='->', color='royalblue', lw=0.9)
    )

    ax1.set_xlabel("Jammer Power (dB above GPS)", fontsize=12)
    ax1.set_ylabel("Output SINR (dB)", fontsize=12)
    ax1.set_title("SINR vs. Jammer Power  |  3 Equal-Power Jammers", fontsize=11)
    ax1.set_xlim(0, 50)
    ax1.set_ylim(max(min(sinr_digital.min(), sinr_hybrid.min()) - 5, -60),
                 min(sinr_ideal.max() + 5, 40))
    ax1.legend(fontsize=9, loc='upper right')
    ax1.grid(True, alpha=0.3)

    # ── Panel 2: ADC snapshot at 30 dB ────────────────────────────────────────
    if X_snap_raw is not None:
        t_show = np.arange(200)
        t_us   = t_show / fs * 1e6
        raw    = np.real(X_snap_raw[0, t_show])
        pre    = np.real(X_snap_pre[0, t_show])

        ax2.plot(t_us, raw, color='tomato',    lw=1.0, alpha=0.85,
                 label=f'Raw el.0  RMS={np.sqrt(np.mean(raw**2)):.1f}')
        ax2.plot(t_us, pre, color='royalblue', lw=1.3,
                 label=f'Post pre-cancel\nRMS={np.sqrt(np.mean(pre**2)):.1f}')

        ax2.axhline(+ADC_FS, color='black', linestyle='--', lw=1.3,
                    label=f'ADC ±{ADC_FS:.0f}')
        ax2.axhline(-ADC_FS, color='black', linestyle='--', lw=1.3)

        y_ceil  = max(raw.max(), ADC_FS) * 1.10
        y_floor = min(raw.min(), -ADC_FS) * 1.10
        ax2.fill_between(t_us, ADC_FS,  y_ceil,  alpha=0.12, color='tomato')
        ax2.fill_between(t_us, y_floor, -ADC_FS, alpha=0.12, color='tomato')
        ax2.text(t_us[-1] * 0.55, (ADC_FS + y_ceil) / 2,
                 'Clipping\nzone', fontsize=8, color='tomato',
                 ha='center', va='center', alpha=0.8)

        ax2.set_xlabel("Time (µs)", fontsize=11)
        ax2.set_ylabel("Amplitude", fontsize=11)
        ax2.set_title("ADC Snapshot  |  30 dB Jammer\n90% pre-cancel × 3 jammers",
                      fontsize=11)
        ax2.set_ylim(y_floor, y_ceil)
        ax2.legend(fontsize=8.5, loc='upper right')
        ax2.grid(True, alpha=0.3)

    plt.savefig(save_fig, dpi=150, bbox_inches='tight')
    print(f"  Saved plot : {save_fig}")

    return {
        'jam_db':  jam_db_range,
        'ideal':   sinr_ideal,
        'digital': sinr_digital,
        'hybrid':  sinr_hybrid,
    }


if __name__ == "__main__":
    hybrid_sim()
