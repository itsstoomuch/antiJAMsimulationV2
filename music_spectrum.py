"""
music_spectrum.py

Direction-of-arrival (DOA) estimation using the MUSIC algorithm applied to
realistic IQ data from a 2×2 uniform rectangular array (URA).

MUSIC (MUltiple SIgnal Classification) exploits a fundamental property of the
array covariance matrix R:

    The steering vector a(θ) of a TRUE source lies in the signal subspace of R,
    which is ORTHOGONAL to the noise subspace by construction.

Scanning a(θ) across all azimuths and measuring how close it comes to
orthogonal with the noise subspace produces a pseudospectrum with sharp peaks
exactly at the source DOA azimuths.

Algorithm
---------
  1. Compute sample covariance  R = (1/N) X X^H        (4×4 Hermitian)
  2. Eigendecompose R = E Λ E^H                          (ascending λ order)
  3. Extract noise subspace  E_noise = E[:, :n_noise]    (n_elements - n_signals smallest)
  4. For each scan azimuth φ:  P(φ) = 1 / ‖E_noise^H a(φ)‖²
  5. Peaks in P(φ) → estimated DOA azimuths
  6. Plot spatial spectrum + eigenvalue diagram

Scenario (from generate_array_data.py)
---------------------------------------
  2 jammers:  az = +30.96° (NE), +165.96° (NW)
  Array:      2×2 URA, half-wavelength spacing in X and Y
  n_signals = 2  →  noise subspace has 2 eigenvectors

Input  : array_data.npy    (written by generate_array_data.py)
Output : music_spectrum.png
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from scipy.linalg import eigh
from scipy.signal import find_peaks as _scipy_find_peaks


def find_top_peaks(spectrum_db, angles_deg, n_signals, min_sep_deg=25):
    all_idx, _ = _scipy_find_peaks(spectrum_db, distance=5)
    if len(all_idx) == 0:
        return np.array([np.argmax(spectrum_db)])
    heights = spectrum_db[all_idx]
    order = np.argsort(heights)[::-1]
    sorted_idx = all_idx[order]
    chosen = []
    for idx in sorted_idx:
        az = angles_deg[idx]
        if all(abs(az - angles_deg[c]) >= min_sep_deg for c in chosen):
            chosen.append(idx)
        if len(chosen) == n_signals:
            break
    return np.sort(np.array(chosen))


# True jammer azimuths (degrees), derived from 3D geometry in generate_array_data.py
TRUE_AZIMUTHS = np.array([30.96, 165.96])


def music_spectrum(
    data_file:  str        = "array_data.npy",
    n_signals:  int        = 2,                               # two jammers
    f_carrier:  float      = 1575.42e6,                       # GPS L1, Hz
    theta_scan: np.ndarray = np.linspace(-180, 180, 7201),    # full 360°, 0.05° resolution
    save_fig:   str        = "music_spectrum.png",
) -> np.ndarray:
    """
    Estimate jammer azimuths using MUSIC and produce a 2-panel figure.

    Panel 1 — Spatial spectrum (dB) vs azimuth: peaks at both jammer directions.
    Panel 2 — Covariance eigenvalues: 2 large (signal) + 2 small (noise).

    Parameters
    ----------
    data_file  : path to the complex IQ array data (.npy)
    n_signals  : number of sources to resolve (default 2, one per jammer)
    f_carrier  : GPS L1 carrier frequency — sets wavelength and element spacing
    theta_scan : azimuth angles (degrees) over which to evaluate the spectrum
    save_fig   : output filename for the saved figure

    Returns
    -------
    spectrum_db : ndarray, shape (len(theta_scan),)
        Normalised MUSIC pseudospectrum in dB  (maximum = 0 dB).
    """

    # ==========================================================================
    # 1. LOAD DATA AND COMPUTE SAMPLE COVARIANCE MATRIX
    # ==========================================================================

    X = np.load(data_file)                         # shape (n_elements, n_samples)
    n_elements, n_samples = X.shape

    # R̂ = (1/N) · X · X^H   — 4×4 Hermitian, positive semi-definite.
    # Entry R̂[m, k] is the time-averaged cross-correlation between elements m and k.
    # For 2 jammers: R̂ ≈ Σ_i P_i · a_i·a_i^H + σ²·I  (rank-2 signal + scaled identity)
    R = (X @ X.conj().T) / n_samples               # shape (4, 4), complex128

    # ==========================================================================
    # 2. EIGENDECOMPOSE R  →  SIGNAL + NOISE SUBSPACES
    # ==========================================================================

    # eigh: eigendecomposition for Hermitian matrices, ascending order.
    eigenvalues, eigenvectors = eigh(R)
    # eigenvalues  : shape (4,), real, ascending (λ₁ ≤ λ₂ ≤ λ₃ ≤ λ₄)
    # eigenvectors : shape (4,4), columns are orthonormal eigenvectors

    # With 2 signals and 4 elements, the noise subspace has 4 - 2 = 2 eigenvectors —
    # the two eigenvectors corresponding to the two smallest eigenvalues.
    n_noise  = n_elements - n_signals               # = 1
    E_noise  = eigenvectors[:, :n_noise]            # shape (4, 1)

    # ==========================================================================
    # 3. 2×2 URA ARRAY GEOMETRY  (must match generate_array_data.py exactly)
    # ==========================================================================

    c   = 3e8
    lam = c / f_carrier                            # GPS L1 wavelength ≈ 0.1903 m
    d   = lam / 2                                  # half-wavelength spacing ≈ 0.0951 m

    # Four elements in the XY plane, mirroring the data generator layout:
    #   [2]=(0,d)   [3]=(d,d)
    #   [0]=(0,0)   [1]=(d,0)
    elem_pos = np.array([
        [0, 0, 0],
        [d, 0, 0],
        [0, d, 0],
        [d, d, 0],
    ], dtype=float)   # shape (4, 3)

    def steering_vector_ura(azimuth_deg: float) -> np.ndarray:
        """
        2×2 URA steering vector for a far-field source at the given azimuth,
        scanned at elevation = 0° (horizon plane).

        Phase at element m:
            φ_m = (2π/λ) · (elem_pos[m] · û)
        where û = [cos(az), sin(az), 0] is the unit direction vector in the
        horizontal plane.

        Elevation is fixed at 0° for the 1D azimuth scan.  The actual jammer
        elevations are −4° to −10°, giving cos(el) ≈ 0.985 – 0.993, so the
        phase mismatch vs the true steering vectors is < 1.5% — negligible for
        peak location but note that a full 2D MUSIC scan would be needed for
        precise elevation estimates.
        """
        az  = np.deg2rad(azimuth_deg)
        u   = np.array([np.cos(az), np.sin(az), 0.0])   # horizontal unit vector
        phase = (2 * np.pi / lam) * (elem_pos @ u)       # shape (4,)
        return np.exp(1j * phase)                         # shape (4,)

    # ==========================================================================
    # 4. MUSIC PSEUDOSPECTRUM SCAN  (full 360° azimuth)
    # ==========================================================================

    spectrum = np.zeros(len(theta_scan))

    for i, theta in enumerate(theta_scan):
        a    = steering_vector_ura(theta)            # candidate steering vector (4,)
        proj = E_noise.conj().T @ a                  # project onto noise subspace → (1,)
        denom = np.real(np.dot(proj.conj(), proj))   # ‖proj‖² — real scalar
        spectrum[i] = 1.0 / (denom + 1e-12)         # large where a ⊥ E_noise

    spectrum_db = 10 * np.log10(spectrum / spectrum.max())   # normalise, 0 dB at peak

    # ==========================================================================
    # 5. PEAK FINDING  →  ESTIMATED DOA AZIMUTHS
    # ==========================================================================

    peaks_idx   = find_top_peaks(spectrum_db, theta_scan, n_signals, min_sep_deg=25)
    peak_angles = theta_scan[peaks_idx]

    # ==========================================================================
    # 6. CONSOLE OUTPUT
    # ==========================================================================

    # Sort both detected and true angles so the comparison is unambiguous.
    detected_sorted = np.sort(peak_angles)
    true_sorted     = np.sort(TRUE_AZIMUTHS)

    print()
    print("=" * 60)
    print("  MUSIC — Direction-of-Arrival Estimation")
    print("=" * 60)
    print(f"  Array elements        : {n_elements}  (2×2 URA)")
    print(f"  Snapshots             : {n_samples}")
    print(f"  n_signals             : {n_signals}  (two jammers)")
    print(f"  Noise subspace dim    : {n_noise}")
    print()
    print(f"  Eigenvalues (descending):")
    sorted_ev = np.sort(eigenvalues.real)[::-1]
    for idx, ev in enumerate(sorted_ev):
        label = "signal" if idx < n_signals else "noise "
        print(f"    λ{idx+1} = {ev:.4e}   [{label}]")
    print()
    print(f"  Noise floor (avg of {n_noise} smallest λ) : "
          f"{eigenvalues.real[:n_noise].mean():.4e}")
    print()
    print(f"  {'Source':<10}  {'True az (°)':>12}  {'Detected (°)':>13}  {'Error (°)':>10}")
    print(f"  {'-'*10}  {'-'*12}  {'-'*13}  {'-'*10}")
    for k in range(min(len(detected_sorted), len(true_sorted))):
        err = detected_sorted[k] - true_sorted[k]
        print(f"  {'Jammer '+str(k+1):<10}  {true_sorted[k]:>12.2f}  "
              f"{detected_sorted[k]:>13.2f}  {err:>+10.2f}")
    if len(detected_sorted) != len(true_sorted):
        print(f"\n  WARNING: found {len(detected_sorted)} peaks, expected {len(true_sorted)}")
    print("=" * 60)
    print()

    # ==========================================================================
    # 7. PUBLICATION-QUALITY PLOT
    # ==========================================================================

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))
    fig.suptitle(
        "MUSIC Direction-of-Arrival  |  2×2 URA, GPS L1 (1575.42 MHz)  |  3 Jammers",
        fontsize=13, fontweight='bold'
    )

    # ---- Panel 1: Spatial Spectrum -------------------------------------------

    ax1.plot(theta_scan, spectrum_db,
             color='royalblue', linewidth=1.2, zorder=3)

    # Colour cycle for the three jammers
    jammer_colors = ['tomato', 'darkorange', 'mediumseagreen']

    # True azimuth vertical lines
    for k, az in enumerate(true_sorted):
        ax1.axvline(az, color=jammer_colors[k], linestyle='--',
                    linewidth=1.8, zorder=4, alpha=0.85)

    # Detected peak shading + annotation
    for ang in peak_angles:
        mask = np.abs(theta_scan - ang) < 4
        ax1.fill_between(theta_scan[mask], -65, spectrum_db[mask],
                         alpha=0.18, color='royalblue', zorder=2)

    for ang in peak_angles:
        idx_peak = np.argmin(np.abs(theta_scan - ang))
        y_peak   = spectrum_db[idx_peak]
        # Alternate annotation above/below to avoid overlap near 165°
        y_text   = y_peak - 8 if ang > 100 else y_peak - 6
        ax1.annotate(
            f'{ang:.2f}°',
            xy     = (ang, y_peak),
            xytext = (ang + 6, y_text),
            fontsize= 9, color='royalblue', fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='royalblue', lw=1.0),
        )

    # Legend
    legend_handles = [
        Line2D([0], [0], color='royalblue', lw=1.5,
               label='MUSIC pseudospectrum'),
    ]
    for k, az in enumerate(true_sorted):
        label = f'Jammer {k+1} true az ({az:.1f}°)'
        legend_handles.append(
            Line2D([0], [0], color=jammer_colors[k], lw=1.8,
                   linestyle='--', label=label)
        )

    ax1.legend(handles=legend_handles, fontsize=8.5, loc='upper left')
    ax1.set_xlabel("Azimuth Angle (degrees)", fontsize=12)
    ax1.set_ylabel("MUSIC Pseudospectrum (dB)", fontsize=12)
    ax1.set_title("Spatial Spectrum — Full 360° Azimuth Scan", fontsize=11)
    ax1.set_xlim(-180, 180)
    ax1.set_ylim(-65, 3)
    ax1.set_xticks(np.arange(-180, 181, 30))
    ax1.grid(True, alpha=0.3)

    # ---- Panel 2: Eigenvalue Diagram -----------------------------------------

    sorted_ev   = np.sort(eigenvalues.real)[::-1]
    ev_colors   = ['royalblue'] * n_signals + ['tomato'] * n_noise
    bars = ax2.bar(
        np.arange(1, n_elements + 1), sorted_ev,
        color=ev_colors, edgecolor='black', linewidth=0.8,
        zorder=3, width=0.55
    )
    ax2.set_yscale('log')

    noise_floor = eigenvalues.real[:n_noise].mean()
    ax2.axhline(noise_floor, color='gray', linestyle=':', linewidth=1.5,
                label=f'Noise floor = {noise_floor:.2e}')

    for bar, val in zip(bars, sorted_ev):
        label = f'{val:.2e}'
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            val * 1.6,
            label,
            ha='center', va='bottom', fontsize=9, fontweight='bold'
        )

    ax2.axvline(n_signals + 0.5, color='black', linestyle='-',
                linewidth=1.2, alpha=0.4)
    ax2.text(n_signals + 0.55, noise_floor * 5,
             '← signal | noise →', fontsize=8.5,
             va='center', color='dimgray', style='italic')

    sig_patch   = mpatches.Patch(color='royalblue',
                                 label=f'Signal eigenvectors ({n_signals} jammers)')
    noise_patch = mpatches.Patch(color='tomato',
                                 label=f'Noise eigenvector ({n_noise})')
    noise_line  = Line2D([0], [0], color='gray', linestyle=':', lw=1.5,
                         label=f'Noise floor = {noise_floor:.2e}')
    ax2.legend(handles=[sig_patch, noise_patch, noise_line], fontsize=9)

    ax2.set_xlabel("Eigenvalue Index  (1 = largest)", fontsize=12)
    ax2.set_ylabel("Eigenvalue Magnitude", fontsize=12)
    ax2.set_title(
        "Covariance Eigenvalues\n"
        f"3 signal (jammers)  +  1 noise  |  gap = {sorted_ev[n_signals-1]/sorted_ev[n_signals]:.0f}×",
        fontsize=11
    )
    ax2.set_xticks(np.arange(1, n_elements + 1))
    ax2.set_xticklabels([f"λ{i}" for i in range(1, n_elements + 1)], fontsize=11)
    ax2.grid(True, axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_fig, dpi=150, bbox_inches='tight')
    plt.show()
    print(f"  Saved plot : {save_fig}")
    print()

    return spectrum_db


# =============================================================================
# QUICK RUN  —  python music_spectrum.py
# =============================================================================
if __name__ == "__main__":
    music_spectrum()
