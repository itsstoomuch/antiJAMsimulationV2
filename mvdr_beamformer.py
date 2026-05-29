"""
mvdr_beamformer.py

Minimum Variance Distortionless Response (MVDR) beamformer for the
realistic 3-jammer GPS anti-jam scenario.

Array : 2×2 URA, half-wavelength spacing (matches generate_array_data.py)
Sources:
  GPS satellite  : azimuth ≈ 0°    — distortionless passband
  Jammer 1 (CW)  : azimuth ≈ +30.96°   [500,  300,  0] m NE
  Jammer 2 (CW)  : azimuth ≈ +165.96°  [-800, 200,  0] m NW
  Jammer 3 (CW)  : azimuth ≈ −71.57°   [200, -600, 50] m SE

MVDR solves the constrained optimisation problem:
    minimise   w^H R w          (suppress all interference)
    subject to w^H a_gps = 1   (GPS passes through undistorted)

Closed-form solution (Lagrange multipliers):
    w = R^{-1} a_gps / (a_gps^H R^{-1} a_gps)

With 4 elements and 1 GPS constraint, three unconstrained degrees of
freedom are exactly consumed placing nulls at all three jammer azimuths.

Diagonal loading (R_loaded = R + δI) is applied before inversion to
prevent near-singularity when 3 jammers nearly fill the signal subspace
of a 4-element array.

Input  : array_data.npy     (written by generate_array_data.py)
Outputs: mvdr_beampattern.png
         mvdr_weights.npy   (saved weight vector for hybrid_sim.py)
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D

# True jammer azimuths computed from 3D geometry in generate_array_data.py
JAMMER_AZIMUTHS = np.array([30.96, 165.96, -71.57])
JAMMER_COLORS   = ['tomato', 'darkorange', 'mediumpurple']
JAMMER_LABELS   = [
    'Jammer 1  (+30.96°)  NE',
    'Jammer 2  (+165.96°) NW',
    'Jammer 3  (−71.57°)  SE',
]


def mvdr_beamformer(
    data_file:    str        = "array_data.npy",
    f_carrier:    float      = 1575.42e6,
    theta_gps:    float      = 0.0,
    theta_scan:   np.ndarray = np.linspace(-180, 180, 7201),
    diag_load:    float      = 1e-4,
    save_fig:     str        = "mvdr_beampattern.png",
    weights_file: str        = "mvdr_weights.npy",
) -> np.ndarray:
    """
    Compute MVDR weight vector for GPS L1 with 3 simultaneous jammers.

    Steps
    -----
    1. Load array data, form 4×4 sample covariance R with diagonal loading.
    2. Solve R_loaded · u = a_gps  for u = R_loaded^{-1} a_gps.
    3. Normalise to distortionless constraint: w = u / (a_gps^H u).
    4. Compute beampattern B(θ) = |w^H a(θ)|² across full 360° azimuth.
    5. Apply w to time-domain data:  y(t) = w^H x(t).
    6. Plot beampattern + null-depth chart + time-domain comparison.

    Parameters
    ----------
    data_file    : path to (4, n_samples) complex IQ array data
    f_carrier    : GPS L1 frequency for steering vector computation
    theta_gps    : GPS look direction in azimuth degrees
    theta_scan   : azimuth scan angles for beampattern evaluation
    diag_load    : diagonal loading as a fraction of trace(R)/N
    save_fig     : output filename for the beampattern figure
    weights_file : filename to save the 4-element complex weight vector

    Returns
    -------
    w : ndarray, shape (4,), dtype complex128
        MVDR weight vector satisfying w^H a_gps = 1 exactly.
    """

    # ==================================================================
    # 1. LOAD DATA AND COMPUTE SAMPLE COVARIANCE
    # ==================================================================

    X = np.load(data_file)                          # (n_elements, n_samples)
    n_elements, n_samples = X.shape

    # R̂ = (1/N) X X^H — 4×4 Hermitian, positive semi-definite.
    # Dominant structure: outer products of the three jammer steering vectors
    # scaled by their (large) received powers.
    R = (X @ X.conj().T) / n_samples               # (4, 4), complex128

    # Diagonal loading prevents near-singularity when 3 jammers consume
    # 3 of the 4 available signal-subspace dimensions.  The load is
    # proportional to the average eigenvalue so it stays signal-independent.
    load     = diag_load * np.trace(R).real / n_elements
    R_loaded = R + load * np.eye(n_elements)

    # ==================================================================
    # 2. URA ARRAY GEOMETRY  (must match generate_array_data.py exactly)
    # ==================================================================

    c   = 3e8
    lam = c / f_carrier                             # GPS L1 wavelength ≈ 0.1903 m
    d   = lam / 2                                   # half-wavelength URA spacing

    # 2×2 URA element positions in the horizontal (XY) plane:
    #   [2]=(0,d)   [3]=(d,d)
    #   [0]=(0,0)   [1]=(d,0)
    elem_pos = np.array([
        [0, 0, 0],
        [d, 0, 0],
        [0, d, 0],
        [d, d, 0],
    ], dtype=float)   # shape (4, 3)

    def steering_vector(azimuth_deg: float) -> np.ndarray:
        """
        URA steering vector scanned at elevation = 0°.
        Phase at element m: φ_m = (2π/λ) · elem_pos[m] · û_az
        where û_az = [cos(az), sin(az), 0].
        """
        az = np.deg2rad(azimuth_deg)
        u  = np.array([np.cos(az), np.sin(az), 0.0])
        return np.exp(1j * (2 * np.pi / lam) * (elem_pos @ u))   # shape (4,)

    def steering_matrix(azimuths_deg: np.ndarray) -> np.ndarray:
        """Vectorised steering vectors for an array of azimuth angles."""
        az  = np.deg2rad(azimuths_deg)                           # (n_angles,)
        u   = np.vstack([np.cos(az), np.sin(az),
                         np.zeros_like(az)])                      # (3, n_angles)
        phi = (2 * np.pi / lam) * (elem_pos @ u)                # (4, n_angles)
        return np.exp(1j * phi)                                   # (4, n_angles)

    a_gps  = steering_vector(theta_gps)
    a_jams = [steering_vector(az) for az in JAMMER_AZIMUTHS]

    # ==================================================================
    # 3. MVDR WEIGHT VECTOR
    # ==================================================================

    # Solve R_loaded · u = a_gps  (avoids explicit matrix inversion).
    # This computes u = R_loaded^{-1} a_gps stably via LU decomposition.
    u = np.linalg.solve(R_loaded, a_gps)            # shape (4,), complex

    # Enforce the distortionless constraint: w^H a_gps = 1.
    # Without this normalisation, w^H a_gps = a_gps^H R^{-1} a_gps ≠ 1.
    w = u / np.real(a_gps.conj() @ u)               # shape (4,), complex

    gps_response = w.conj() @ a_gps
    assert abs(gps_response - 1.0) < 1e-6, (
        f"GPS distortionless constraint violated: {gps_response:.6f}"
    )

    # ==================================================================
    # 4. BEAMPATTERN  B(θ) = |w^H a(θ)|²
    # ==================================================================

    A_scan     = steering_matrix(theta_scan)        # (4, n_angles)
    pattern    = np.abs(w.conj() @ A_scan) ** 2    # (n_angles,)
    pattern_db = 10 * np.log10(pattern + 1e-20)
    pattern_db -= pattern_db.max()                  # normalise: 0 dB at peak

    # Gain figures of merit
    gps_gain_db = 10 * np.log10(abs(w.conj() @ a_gps) ** 2)
    jam_gains   = [10 * np.log10(abs(w.conj() @ a_j) ** 2)
                   for a_j in a_jams]
    null_depths = [gps_gain_db - g for g in jam_gains]

    # ==================================================================
    # 5. APPLY BEAMFORMER  y(t) = w^H x(t)
    # ==================================================================

    y = w.conj() @ X                                # (n_samples,) complex

    p_in_el0 = np.mean(np.abs(X[0, :]) ** 2)
    p_out    = np.mean(np.abs(y) ** 2)

    # ==================================================================
    # 6. PRINT RESULTS
    # ==================================================================

    print()
    print("=" * 62)
    print("  MVDR Beamformer  —  2×2 URA, 3-Jammer Scenario")
    print("=" * 62)
    print(f"  Array elements        : {n_elements}  (2×2 URA)")
    print(f"  Snapshots             : {n_samples}")
    print(f"  Diagonal load (δ)     : {load:.2e}")
    print()
    print(f"  GPS passband gain     : {gps_gain_db:+.4f} dB  (constraint → 0 dB)")
    print()
    for k, (az, g_db, nd) in enumerate(
            zip(JAMMER_AZIMUTHS, jam_gains, null_depths)):
        print(f"  Jammer {k+1}  az={az:+.2f}°  :  "
              f"null gain = {g_db:.1f} dB,  depth = {nd:.0f} dB")
    print()
    print(f"  Input power  (el 0)   : {10*np.log10(p_in_el0+1e-20):.1f} dBW")
    print(f"  Output power          : {10*np.log10(p_out+1e-20):.1f} dBW")
    print(f"  Power reduction       : {10*np.log10(p_in_el0/(p_out+1e-20)):.1f} dB")
    print()
    print(f"  Weight vector w  =  {np.round(w, 4)}")
    print("=" * 62)
    print()

    # ==================================================================
    # 7. SAVE WEIGHTS
    # ==================================================================

    np.save(weights_file, w)
    print(f"  Saved weights : {weights_file}")

    # ==================================================================
    # 8. PUBLICATION-QUALITY PLOT
    # ==================================================================

    fig = plt.figure(figsize=(16, 5))
    fig.suptitle(
        "MVDR Beamformer  |  2×2 URA, GPS L1 (1575.42 MHz)  |  3 Simultaneous Jammers",
        fontsize=13, fontweight='bold'
    )

    gs  = gridspec.GridSpec(1, 3, width_ratios=[2.5, 1.4, 1.4], wspace=0.40)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    ax3 = fig.add_subplot(gs[2])

    # ── Panel 1: Beampattern (full 360°) ──────────────────────────────

    ax1.plot(theta_scan, pattern_db,
             color='royalblue', linewidth=1.4, zorder=3)

    # GPS passband
    ax1.axvline(theta_gps, color='limegreen', linestyle='--',
                linewidth=2.0, zorder=5)

    # Jammer nulls + shading + annotations
    # Annotation offsets chosen to avoid overlap at the crowded +166° edge
    ann_offsets = [(+18, -20), (-45, -32), (+18, -45)]

    for az, color, label, (dx, dy) in zip(
            JAMMER_AZIMUTHS, JAMMER_COLORS, JAMMER_LABELS, ann_offsets):

        ax1.axvline(az, color=color, linestyle=':', linewidth=1.8,
                    zorder=4, alpha=0.9)

        mask = np.abs(theta_scan - az) < 5
        ax1.fill_between(theta_scan[mask], -80, pattern_db[mask],
                         alpha=0.18, color=color)

        idx   = np.argmin(np.abs(theta_scan - az))
        y_val = pattern_db[idx]
        nd    = gps_gain_db - (10 * np.log10(abs(w.conj() @ steering_vector(az)) ** 2))
        ax1.annotate(
            f'{az:+.1f}°\n{nd:.0f} dB null',
            xy=(az, y_val),
            xytext=(az + dx, y_val + dy),
            fontsize=8.5, color=color, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color=color, lw=1.0),
        )

    # Legend
    legend_handles = [
        Line2D([0], [0], color='royalblue', lw=1.4,
               label='MVDR beampattern'),
        Line2D([0], [0], color='limegreen', lw=2.0, linestyle='--',
               label=f'GPS look dir ({theta_gps:.0f}°)  0 dB'),
    ]
    for color, label in zip(JAMMER_COLORS, JAMMER_LABELS):
        legend_handles.append(
            Line2D([0], [0], color=color, lw=1.8, linestyle=':',
                   label=label)
        )

    ax1.legend(handles=legend_handles, fontsize=8, loc='lower center', ncol=2)
    ax1.set_xlabel("Azimuth Angle (degrees)", fontsize=12)
    ax1.set_ylabel("Beamformer Gain (dB)", fontsize=12)
    ax1.set_title("Beampattern  B(θ) = |w^H a(θ)|²  |  Full 360° Azimuth Scan",
                  fontsize=11)
    ax1.set_xlim(-180, 180)
    ax1.set_ylim(-80, 5)
    ax1.set_xticks(np.arange(-180, 181, 30))
    ax1.axhline(0, color='gray', linestyle=':', linewidth=0.8, alpha=0.5)
    ax1.grid(True, alpha=0.3)

    # ── Panel 2: Null-depth bar chart ─────────────────────────────────

    x_labels = [f'J{k+1}\n{az:+.0f}°'
                for k, az in enumerate(JAMMER_AZIMUTHS)]
    bars = ax2.bar(
        x_labels, null_depths,
        color=JAMMER_COLORS, edgecolor='black', linewidth=0.8,
        zorder=3, width=0.55
    )
    for bar, nd in zip(bars, null_depths):
        ax2.text(bar.get_x() + bar.get_width() / 2, nd + 0.8,
                 f'{nd:.0f} dB', ha='center', va='bottom',
                 fontsize=11, fontweight='bold')

    ax2.axhline(30, color='gray', linestyle=':', linewidth=1.2,
                label='30 dB reference')
    ax2.set_ylabel("Null Depth (dB below GPS passband)", fontsize=10)
    ax2.set_title("Null Depth\nper Jammer", fontsize=11)
    ax2.set_ylim(0, max(null_depths) * 1.30)
    ax2.legend(fontsize=9)
    ax2.grid(True, axis='y', alpha=0.3)

    # ── Panel 3: Time-domain before / after ───────────────────────────

    t_show  = np.arange(150)
    t_us    = t_show / 10e6 * 1e6
    rms_in  = np.sqrt(np.mean(np.abs(X[0, t_show]) ** 2))
    rms_out = np.sqrt(np.mean(np.abs(y[t_show]) ** 2))

    ax3.plot(t_us, np.real(X[0, t_show]),
             color='tomato', linewidth=1.0, alpha=0.85,
             label=f'Element 0 (raw)\nRMS = {rms_in:.2e}')
    ax3.plot(t_us, np.real(y[t_show]),
             color='royalblue', linewidth=1.3,
             label=f'MVDR output\nRMS = {rms_out:.2e}')

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
