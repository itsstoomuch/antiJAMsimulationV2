"""
mvdr_beamformer.py

Minimum Variance Distortionless Response (MVDR) beamformer for GPS anti-jam.

The MVDR beamformer solves a constrained optimisation problem:

    minimise   w^H R w          (minimise output power → kills jammer)
    subject to w^H a_gps = 1   (GPS signal passes through undistorted)

The closed-form solution via Lagrange multipliers is:

    w_MVDR = R^{-1} a_gps / (a_gps^H R^{-1} a_gps)

Physical intuition
------------------
R contains the jammer's full spatial fingerprint.  R^{-1} inverts the
covariance structure, effectively de-emphasising the jammer direction
(high-power direction → de-weighted).  The GPS constraint then steers the
remaining degrees of freedom toward 0° — automatically placing a null at
the jammer angle (45°) without being told about the jammer at all.

Input  : array_data.npy     (from generate_array_data.py)
Outputs: mvdr_beampattern.png
         mvdr_weights.npy   (saved weights for hybrid_sim.py)
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec


def mvdr_beamformer(
    data_file:  str         = "array_data.npy",
    f_carrier:  float       = 1575.42e6,           # GPS L1, Hz
    theta_gps:  float       = 0.0,                 # GPS angle, degrees
    theta_jam:  float       = 45.0,                # jammer angle, degrees
    theta_scan: np.ndarray  = np.linspace(-90, 90, 3601),
    save_fig:   str         = "mvdr_beampattern.png",
    weights_file: str       = "mvdr_weights.npy",
) -> np.ndarray:
    """
    Compute MVDR beamformer weights and apply to the received array data.

    Steps
    -----
    1. Load array data, compute 4×4 sample covariance R.
    2. Solve R·u = a_gps  (avoids explicit inversion; more stable).
    3. Normalise to enforce distortionless constraint: w = u / (a_gps^H u).
    4. Compute beampattern B(θ) = |w^H a(θ)|²  across all scan angles.
    5. Apply w to time-domain data:  y(t) = w^H x(t).
    6. Plot beampattern + before/after signal comparison.

    Parameters
    ----------
    data_file    : path to the complex IQ array data
    f_carrier    : GPS L1 frequency for steering vector computation
    theta_gps    : look direction (GPS satellite angle)
    theta_jam    : expected jammer angle (used only for annotation)
    theta_scan   : angles at which to evaluate the beampattern
    save_fig     : output filename for the plot
    weights_file : filename to save the complex weight vector

    Returns
    -------
    w : np.ndarray, shape (n_elements,), dtype complex128
        MVDR weight vector.  Satisfies  w^H a_gps = 1  exactly.
    """

    # ==================================================================
    # 1. LOAD DATA + COVARIANCE
    # ==================================================================

    X = np.load(data_file)                         # (n_elements, n_samples)
    n_elements, n_samples = X.shape

    # Sample covariance:  R̂ = (1/N) X X^H
    # R̂ encodes the full spatial power distribution — GPS, jammer, noise.
    # Its dominant structure is the jammer's outer product
    #   ≈ 1000 · a_jam · a_jam^H,  since jammer is 30 dB above GPS.
    R = (X @ X.conj().T) / n_samples               # (4, 4) Hermitian

    # ==================================================================
    # 2. ARRAY GEOMETRY  (must match generate_array_data.py)
    # ==================================================================

    c   = 3e8
    lam = c / f_carrier                            # GPS L1 wavelength ≈ 0.190 m
    d   = lam / 2                                  # half-wavelength spacing

    def steering_vector(theta_deg: float) -> np.ndarray:
        """
        ULA steering vector a(θ).  Identical to all other scripts — must match.
        """
        theta = np.deg2rad(theta_deg)
        m     = np.arange(n_elements)
        phase = (2 * np.pi / lam) * d * m * np.sin(theta)
        return np.exp(1j * phase)                  # shape (n_elements,)

    a_gps = steering_vector(theta_gps)             # GPS constraint direction
    a_jam = steering_vector(theta_jam)             # jammer (annotation only)

    # ==================================================================
    # 3. MVDR WEIGHT VECTOR
    # ==================================================================

    # Step 3a: Solve  R · u = a_gps  for u = R^{-1} a_gps.
    # np.linalg.solve(R, b) computes R^{-1} b without explicitly inverting R.
    # This is the numerically preferred approach — avoids amplifying round-off
    # errors that explicit inversion introduces in near-singular matrices.
    u = np.linalg.solve(R, a_gps)                 # shape (4,), complex

    # Step 3b: Enforce the distortionless constraint w^H a_gps = 1.
    # Without normalisation, w^H a_gps = a_gps^H R^{-1} a_gps (a real scalar).
    # Dividing by that scalar makes the GPS passband exactly 0 dB.
    denominator = np.real(a_gps.conj() @ u)       # a_gps^H R^{-1} a_gps, real scalar
    w = u / denominator                            # MVDR weight vector, shape (4,)

    # Quick sanity check: the constraint should hold to machine precision
    gps_response = w.conj() @ a_gps               # should be ≈ 1.0 + 0j
    assert abs(gps_response - 1.0) < 1e-9, f"Constraint violated: {gps_response}"

    # ==================================================================
    # 4. BEAMPATTERN  B(θ) = |w^H a(θ)|²
    # ==================================================================

    # For each candidate angle θ, compute the complex gain of the beamformer.
    # The magnitude squared is the power gain — this is the "spatial filter"
    # frequency response, but in angle instead of time-frequency.
    pattern    = np.array([abs(w.conj() @ steering_vector(t))**2
                           for t in theta_scan])
    pattern_db = 10 * np.log10(pattern + 1e-20)   # convert to dB; +ε avoids log(0)

    # Key figures of merit
    gps_gain_db = 10 * np.log10(abs(w.conj() @ a_gps)**2)    # should be 0.00 dB
    jam_gain_db = 10 * np.log10(abs(w.conj() @ a_jam)**2)    # should be very negative
    null_depth  = gps_gain_db - jam_gain_db                   # dB of null below GPS

    # ==================================================================
    # 5. APPLY BEAMFORMER  y(t) = w^H x(t)
    # ==================================================================

    # Apply weight vector to all 1000 snapshots in one matrix–vector product.
    # w.conj() has shape (4,); X has shape (4, 1000).
    # The result y has shape (1000,) — the scalar beamformer output.
    y = w.conj() @ X                               # (1000,) complex

    # Power at output vs input (single element as baseline)
    p_in_el0  = np.mean(np.abs(X[0, :])**2)       # element 0 raw power
    p_out     = np.mean(np.abs(y)**2)             # beamformer output power
    p_in_db   = 10 * np.log10(p_in_el0)
    p_out_db  = 10 * np.log10(p_out)

    # Theoretical per-component output power
    p_gps_out  = abs(w.conj() @ a_gps)**2 * 1.0          # GPS power = 1 W
    p_jam_out  = abs(w.conj() @ a_jam)**2 * (10**(30/10)) # jammer: 30 dB above GPS
    p_noise_out = np.real(w.conj() @ np.eye(n_elements) @ w)  # noise: σ²=1 per element

    # ==================================================================
    # 6. PRINT RESULTS
    # ==================================================================

    print("=" * 55)
    print("MVDR Beamformer  —  weight vector and null steering")
    print("=" * 55)
    print(f"  GPS passband gain  : {gps_gain_db:+.4f} dB  (constraint → should be 0)")
    print(f"  Jammer null gain   : {jam_gain_db:+.2f} dB")
    print(f"  Null depth         : {null_depth:.1f} dB below GPS passband")
    print(f"  Input power (el 0) : {p_in_db:.1f} dBW  (jammer dominated)")
    print(f"  Output power       : {p_out_db:.1f} dBW  (after null steering)")
    print(f"  Output GPS power   : {10*np.log10(p_gps_out+1e-20):.2f} dBW")
    print(f"  Output jammer pwr  : {10*np.log10(p_jam_out+1e-20):.2f} dBW")
    print(f"  Weight vector  w   : {np.round(w, 4)}")

    # ==================================================================
    # 7. SAVE WEIGHTS
    # ==================================================================

    np.save(weights_file, w)
    print(f"\n  Saved weights : {weights_file}")

    # ==================================================================
    # 8. PUBLICATION-QUALITY PLOT
    # ==================================================================

    fig = plt.figure(figsize=(15, 5))
    fig.suptitle("MVDR Beamformer  |  4-Element ULA, GPS L1 (1575.42 MHz)",
                 fontsize=13, fontweight='bold')

    gs = gridspec.GridSpec(1, 3, width_ratios=[2.2, 1.5, 1.5], wspace=0.38)
    ax1 = fig.add_subplot(gs[0])   # beampattern (wider)
    ax2 = fig.add_subplot(gs[1])   # power breakdown bar chart
    ax3 = fig.add_subplot(gs[2])   # time-domain before/after

    # ---- Panel 1: Beampattern -------------------------------------------

    ax1.plot(theta_scan, pattern_db,
             color='royalblue', linewidth=1.8, zorder=3, label='MVDR beampattern')

    # GPS passband — distortionless at 0 dB
    ax1.axvline(theta_gps, color='limegreen', linestyle='--', linewidth=2.0,
                label=f'GPS look direction ({theta_gps}°)  0 dB passband', zorder=4)

    # Jammer null
    ax1.axvline(theta_jam, color='tomato', linestyle='--', linewidth=2.0,
                label=f'Jammer direction ({theta_jam}°)', zorder=4)

    # Shade the null region
    null_mask = (theta_scan > theta_jam - 6) & (theta_scan < theta_jam + 6)
    ax1.fill_between(theta_scan[null_mask], -80, pattern_db[null_mask],
                     alpha=0.2, color='tomato')

    # Annotate null depth
    null_angle_idx = np.argmin(np.abs(theta_scan - theta_jam))
    ax1.annotate(
        f'Null depth\n{null_depth:.0f} dB',
        xy=(theta_jam, pattern_db[null_angle_idx]),
        xytext=(theta_jam + 12, pattern_db[null_angle_idx] + 15),
        fontsize=9, color='tomato', fontweight='bold',
        arrowprops=dict(arrowstyle='->', color='tomato', lw=1.2)
    )

    ax1.set_xlabel("Angle of Arrival (degrees)", fontsize=12)
    ax1.set_ylabel("Beamformer Gain (dB)", fontsize=12)
    ax1.set_title("Beampattern  B(θ) = |w^H a(θ)|²", fontsize=12)
    ax1.set_xlim(-90, 90)
    ax1.set_ylim(-80, 10)
    ax1.set_xticks(np.arange(-90, 91, 15))
    ax1.axhline(0, color='gray', linestyle=':', linewidth=0.8, alpha=0.5)
    ax1.legend(fontsize=9, loc='lower right')
    ax1.grid(True, alpha=0.3)

    # ---- Panel 2: Power breakdown bar chart ----------------------------

    labels   = ['GPS', 'Jammer', 'Noise']
    p_before = [
        10 * np.log10(1.0),            # GPS element 0 power: |a_gps[0]|² · 1 = 1
        10 * np.log10(10**(30/10)),    # Jammer: 30 dB above GPS
        10 * np.log10(1.0),            # Noise: unit power
    ]
    p_after  = [
        10 * np.log10(p_gps_out  + 1e-20),
        10 * np.log10(p_jam_out  + 1e-20),
        10 * np.log10(p_noise_out + 1e-20),
    ]

    x      = np.arange(len(labels))
    width  = 0.35
    colors = ['limegreen', 'tomato', 'steelblue']

    bars_before = ax2.bar(x - width/2, p_before, width, label='Before MVDR',
                          color=colors, alpha=0.45, edgecolor='black', linewidth=0.8)
    bars_after  = ax2.bar(x + width/2, p_after,  width, label='After MVDR',
                          color=colors, alpha=0.95, edgecolor='black', linewidth=0.8)

    # Annotate bar values
    for bar, val in zip(bars_before, p_before):
        ax2.text(bar.get_x() + bar.get_width()/2, val + 0.5,
                 f'{val:.0f}', ha='center', va='bottom', fontsize=8, alpha=0.6)
    for bar, val in zip(bars_after, p_after):
        ax2.text(bar.get_x() + bar.get_width()/2, max(val, -75) + 0.5,
                 f'{val:.0f}', ha='center', va='bottom', fontsize=8, fontweight='bold')

    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=11)
    ax2.set_ylabel("Power (dBW)", fontsize=11)
    ax2.set_title("Signal Power\nBefore vs. After MVDR", fontsize=11)
    ax2.set_ylim(-80, 40)
    ax2.axhline(0, color='gray', linestyle=':', linewidth=0.8)
    ax2.legend(fontsize=9)
    ax2.grid(True, axis='y', alpha=0.3)

    # ---- Panel 3: Time domain before/after ----------------------------

    t_show  = np.arange(150)                       # show first 150 samples
    t_us    = t_show / 10e6 * 1e6                  # convert samples → microseconds

    ax3.plot(t_us, np.real(X[0, t_show]),
             color='tomato', linewidth=1.0, alpha=0.8,
             label=f'Element 0 (raw)\nRMS ≈ {np.sqrt(p_in_el0):.0f}')
    ax3.plot(t_us, np.real(y[t_show]),
             color='royalblue', linewidth=1.2,
             label=f'MVDR output\nRMS ≈ {np.sqrt(p_out):.2f}')

    ax3.set_xlabel("Time (µs)", fontsize=11)
    ax3.set_ylabel("Amplitude", fontsize=11)
    ax3.set_title("Time Domain\nRaw vs. Beamformer Output", fontsize=11)
    ax3.legend(fontsize=8.5, loc='upper right')
    ax3.grid(True, alpha=0.3)
    ax3.axhline(0, color='gray', linestyle=':', linewidth=0.8)

    plt.savefig(save_fig, dpi=150, bbox_inches='tight')
    plt.show()
    print(f"  Saved plot    : {save_fig}")

    return w


# ======================================================================
# QUICK RUN  —  python mvdr_beamformer.py
# ======================================================================
if __name__ == "__main__":
    mvdr_beamformer()
