"""
run_all.py — COGNAV-4 master pipeline.

Runs all four simulation modules in sequence and generates one
publication-quality 4-panel figure saved as publication_figure.png.
"""

import matplotlib
matplotlib.use('Agg')   # must be before any other matplotlib import

import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D

from generate_array_data import generate_array_data
from music_spectrum      import music_spectrum, find_top_peaks
from mvdr_beamformer     import mvdr_beamformer
from hybrid_sim          import hybrid_sim


# ── Physical constants shared across subplots ────────────────────────────────
C         = 3e8
F_CARRIER = 1575.42e6
LAM       = C / F_CARRIER
D         = LAM / 2

ELEM_POS = np.array([[0, 0, 0], [D, 0, 0], [0, D, 0], [D, D, 0]], dtype=float)

# True jammer azimuths — J1, J2, J3 — from 3D geometry in generate_array_data.py
TRUE_AZ = np.array([30.96, 165.96, -71.57])
JCOL    = ['tomato', 'darkorange', 'mediumpurple']


def _sv(az_deg: float) -> np.ndarray:
    """2×2 URA steering vector at elevation = 0°."""
    az = np.deg2rad(az_deg)
    u  = np.array([np.cos(az), np.sin(az), 0.0])
    return np.exp(1j * (2 * np.pi / LAM) * (ELEM_POS @ u))


def _sv_matrix(az_arr: np.ndarray) -> np.ndarray:
    """Vectorised steering matrix, shape (4, len(az_arr))."""
    az  = np.deg2rad(az_arr)
    u   = np.vstack([np.cos(az), np.sin(az), np.zeros_like(az)])  # (3, N)
    phi = (2 * np.pi / LAM) * (ELEM_POS @ u)                      # (4, N)
    return np.exp(1j * phi)


def _first_fail(sinr_arr: np.ndarray, jam_db: np.ndarray):
    m = sinr_arr < 0.0
    return float(jam_db[np.argmax(m)]) if m.any() else None


t_start = time.time()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Generate scene
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "─" * 56)
print("  STEP 1 — Generating array data …")
print("─" * 56)
X = generate_array_data()
plt.close('all')

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — MUSIC DoA estimation
# ─────────────────────────────────────────────────────────────────────────────
print("─" * 56)
print("  STEP 2 — Running MUSIC algorithm …")
print("─" * 56)
theta_scan    = np.linspace(-180, 180, 7201)
music_results = music_spectrum(theta_scan=theta_scan)
plt.close('all')

# Re-extract detected peak angles from the returned pseudospectrum
peaks_idx   = find_top_peaks(music_results, theta_scan, n_signals=3, min_sep_deg=25)
peak_angles = theta_scan[peaks_idx]

# Nearest-neighbour match: each true jammer az → closest detected peak
detected   = np.array([
    peak_angles[np.argmin(np.abs(peak_angles - az))] for az in TRUE_AZ
])
doa_errors = detected - TRUE_AZ
max_error  = float(np.max(np.abs(doa_errors)))

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — MVDR beamformer
# ─────────────────────────────────────────────────────────────────────────────
print("─" * 56)
print("  STEP 3 — Running MVDR beamformer …")
print("─" * 56)
w = mvdr_beamformer()
plt.close('all')

# Recompute null depths from returned weight vector
a_gps_sv    = _sv(0.0)
a_jams_sv   = [_sv(az) for az in TRUE_AZ]
gps_gain_db = 10 * np.log10(abs(w.conj() @ a_gps_sv) ** 2 + 1e-30)
jam_gains   = [10 * np.log10(abs(w.conj() @ aj) ** 2 + 1e-30) for aj in a_jams_sv]
null_depths = [gps_gain_db - g for g in jam_gains]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Hybrid simulation
# ─────────────────────────────────────────────────────────────────────────────
print("─" * 56)
print("  STEP 4 — Running hybrid simulation …")
print("─" * 56)
hybrid_results = hybrid_sim()
plt.close('all')

jam_db_range = hybrid_results['jam_db']
sinr_ideal   = hybrid_results['ideal']
sinr_digital = hybrid_results['digital']
sinr_hybrid  = hybrid_results['hybrid']

fail_dig       = _first_fail(sinr_digital, jam_db_range)
fail_hyb       = _first_fail(sinr_hybrid,  jam_db_range)
idx30          = int(np.argmin(np.abs(jam_db_range - 30.0)))
improvement_30 = float(sinr_hybrid[idx30] - sinr_digital[idx30])
extended_range = (fail_hyb - fail_dig) if (fail_dig is not None and fail_hyb is not None) else None

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Console summary
# ─────────────────────────────────────────────────────────────────────────────
fd_str = f"{fail_dig:.0f} dB" if fail_dig is not None else ">50 dB"
fh_str = f"{fail_hyb:.0f} dB" if fail_hyb is not None else ">50 dB"
er_str = f"{extended_range:.0f} dB" if extended_range is not None else "N/A"
er_pass = extended_range is not None and extended_range > 10

SEP = "═" * 50
print()
print(SEP)
print("  COGNAV-4 SIMULATION — COMPLETE PIPELINE RESULTS")
print(SEP)
print(f"  Array         : 2x2 URA, 4 elements, d=9.52 cm")
print(f"  Frequency     : GPS L1 1575.42 MHz")
print(f"  Jammers       : 3 simultaneous CW")
print()
print(f"  SCENE GEOMETRY:")
print(f"  Jammer 1 (CW) : [500,300,0]m    az=+30.96°  -81.8 dBW")
print(f"  Jammer 2 (CW) : [-800,200,0]m   az=+165.96° -84.8 dBW")
print(f"  Jammer 3 (CW) : [200,-600,50]m  az=-71.57°  -82.4 dBW")
print()
print(f"  MUSIC DoA RESULTS:")
for k in range(3):
    print(f"  Jammer {k+1} detected : {detected[k]:+.2f}° (error {doa_errors[k]:+.2f}°)")
print()
print(f"  MVDR NULL STEERING:")
print(f"  Null at J1 (+30.96°)  : {null_depths[0]:.1f} dB")
print(f"  Null at J2 (+165.96°) : {null_depths[1]:.1f} dB")
print(f"  Null at J3 (-71.57°)  : {null_depths[2]:.1f} dB")
print(f"  GPS passband gain     : {gps_gain_db:+.2f} dB")
print()
print(f"  HYBRID SYSTEM:")
print(f"  Digital fails at   : {fd_str}")
print(f"  Hybrid fails at    : {fh_str}")
print(f"  Extended range     : {er_str}")
print(f"  Improvement at 30dB: {improvement_30:.1f} dB")
print()
print(f"  COGNAV-4 TARGET COMPLIANCE:")
print(f"  DoA accuracy < 1°   : {'PASS' if max_error < 1.0 else 'FAIL'} ({max_error:.2f}°)")
print(f"  Null depth > 40 dB  : {'PASS' if min(null_depths) > 40 else 'FAIL'} ({min(null_depths):.0f} dB min)")
print(f"  Hybrid range > 10 dB: {'PASS' if er_pass else 'FAIL'} ({er_str})")
print(f"  GPS gain = 0 dB     : {'PASS' if abs(gps_gain_db) < 0.01 else 'FAIL'} ({gps_gain_db:+.2f} dB)")
print(SEP)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Publication figure: 4 subplots, 14×9 in, dark style
# ─────────────────────────────────────────────────────────────────────────────

# Beampattern B(θ) = |w^H a(θ)|² for subplot 2
theta_bp   = np.linspace(-180, 180, 7201)
A_bp       = _sv_matrix(theta_bp)           # (4, 7201)
pattern    = np.abs(w.conj() @ A_bp) ** 2  # (7201,)
pattern_db = 10 * np.log10(pattern + 1e-20)
pattern_db = pattern_db - pattern_db.max()  # normalise: 0 dB at peak

with plt.style.context('dark_background'):
    fig = plt.figure(figsize=(14, 9))
    fig.suptitle(
        "COGNAV-4 Hybrid Analog-Digital Anti-Jamming\n"
        "Pre-Hardware Simulation | 4-Element 2×2 URA | GPS L1",
        fontsize=14, fontweight='bold', y=0.98,
    )

    gs = gridspec.GridSpec(2, 2, hspace=0.46, wspace=0.37,
                           left=0.07, right=0.97, top=0.90, bottom=0.07)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, 0])
    ax4 = fig.add_subplot(gs[1, 1])

    # ── SP1: MUSIC spatial spectrum ───────────────────────────────────────────
    ax1.plot(theta_scan, music_results, color='royalblue', lw=1.2, zorder=3)

    for k, az in enumerate(TRUE_AZ):
        ax1.axvline(az, color=JCOL[k], linestyle='--', lw=1.6, alpha=0.85, zorder=4)

    for ang in peak_angles:
        mask = np.abs(theta_scan - ang) < 4
        ax1.fill_between(theta_scan[mask], -65, music_results[mask],
                         alpha=0.22, color='royalblue', zorder=2)
        i_p  = np.argmin(np.abs(theta_scan - ang))
        y_pk = music_results[i_p]
        dy   = -9 if ang > 100 else -6
        ax1.annotate(f'{ang:.2f}°',
                     xy=(ang, y_pk),
                     xytext=(ang + 6, y_pk + dy),
                     fontsize=8.5, color='cyan', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='cyan', lw=0.8))

    h1 = [Line2D([0], [0], color='royalblue', lw=1.4, label='MUSIC spectrum')]
    for k, az in enumerate(TRUE_AZ):
        h1.append(Line2D([0], [0], color=JCOL[k], lw=1.5, linestyle='--',
                         label=f'J{k+1} true {az:+.1f}°'))
    ax1.legend(handles=h1, fontsize=7.5, loc='upper left')
    ax1.set_xlabel("Azimuth (deg)", fontsize=10)
    ax1.set_ylabel("Pseudospectrum (dB)", fontsize=10)
    ax1.set_title("MUSIC DoA — 3 jammers detected", fontsize=11, fontweight='bold')
    ax1.set_xlim(-180, 180)
    ax1.set_ylim(-65, 3)
    ax1.set_xticks(np.arange(-180, 181, 45))
    ax1.grid(True, alpha=0.2)

    # ── SP2: MVDR beam pattern ────────────────────────────────────────────────
    ax2.plot(theta_bp, pattern_db, color='royalblue', lw=1.3, zorder=3)
    ax2.axvline(0.0, color='limegreen', linestyle='--', lw=2.0, zorder=5)

    # Fixed text positions inside [-80, 5] axes — arrows point down to the nulls
    ann_text_pos = [
        (30.96  + 20, -32),   # J1
        (165.96 - 48, -45),   # J2 (shifted left to stay in frame)
        (-71.57 + 20, -57),   # J3
    ]
    for k, (az, col) in enumerate(zip(TRUE_AZ, JCOL)):
        ax2.axvline(az, color=col, linestyle=':', lw=1.8, alpha=0.9, zorder=4)
        mask = np.abs(theta_bp - az) < 5
        ax2.fill_between(theta_bp[mask], -80, pattern_db[mask], alpha=0.18, color=col)
        i_p = np.argmin(np.abs(theta_bp - az))
        ax2.annotate(f'{az:+.1f}°\n{null_depths[k]:.0f} dB',
                     xy=(az, pattern_db[i_p]),
                     xytext=ann_text_pos[k],
                     fontsize=7.5, color=col, fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color=col, lw=0.8))

    h2 = [Line2D([0], [0], color='royalblue', lw=1.4, label='MVDR pattern'),
          Line2D([0], [0], color='limegreen', lw=2.0, linestyle='--', label='GPS (0°)')]
    for k, (az, col) in enumerate(zip(TRUE_AZ, JCOL)):
        h2.append(Line2D([0], [0], color=col, lw=1.8, linestyle=':',
                         label=f'J{k+1} {null_depths[k]:.0f} dB null'))
    ax2.legend(handles=h2, fontsize=7.5, loc='lower center', ncol=2)
    ax2.set_xlabel("Azimuth (deg)", fontsize=10)
    ax2.set_ylabel("Gain (dB)", fontsize=10)
    ax2.set_title("MVDR null steering — 3 simultaneous nulls", fontsize=11, fontweight='bold')
    ax2.set_xlim(-180, 180)
    ax2.set_ylim(-80, 5)
    ax2.set_xticks(np.arange(-180, 181, 45))
    ax2.axhline(0, color='gray', linestyle=':', lw=0.8, alpha=0.5)
    ax2.grid(True, alpha=0.2)

    # ── SP3: Hybrid SINR curve ────────────────────────────────────────────────
    ax3.plot(jam_db_range, sinr_ideal,   color='limegreen',  lw=2.0,
             label='Ideal MVDR (no ADC)')
    ax3.plot(jam_db_range, sinr_digital, color='tomato',     lw=2.0,
             label='Pure digital MVDR')
    ax3.plot(jam_db_range, sinr_hybrid,  color='royalblue',  lw=2.0,
             label='Hybrid (90% pre-cancel)')
    ax3.axhline(0, color='white', linestyle=':', lw=1.0, alpha=0.7,
                label='SINR = 0 dB')
    ax3.fill_between(jam_db_range, sinr_digital, sinr_hybrid,
                     where=(sinr_hybrid > sinr_digital),
                     alpha=0.15, color='royalblue', label='Hybrid advantage')

    ymin_s3 = max(min(sinr_digital.min(), sinr_hybrid.min()) - 5, -60)
    ymax_s3 = min(sinr_ideal.max() + 5, 40)
    ann_y   = ymin_s3 + 14   # text y safely inside axes

    if fail_dig is not None:
        ax3.axvline(fail_dig, color='tomato', linestyle='--', lw=1.3, alpha=0.8)
        ax3.annotate(f'Digital\nfails\n@ {fail_dig:.0f} dB',
                     xy=(fail_dig, 0),
                     xytext=(fail_dig - 12, ann_y),
                     fontsize=7.5, color='tomato', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='tomato', lw=0.9))
    if fail_hyb is not None:
        ax3.axvline(fail_hyb, color='royalblue', linestyle='--', lw=1.3, alpha=0.8)
        ax3.annotate(f'Hybrid\nfails\n@ {fail_hyb:.0f} dB',
                     xy=(fail_hyb, 0),
                     xytext=(fail_hyb + 1.5, ann_y),
                     fontsize=7.5, color='royalblue', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='royalblue', lw=0.9))

    ax3.axvline(30, color='gray', linestyle=':', lw=1.0, alpha=0.7)
    ax3.plot(30, sinr_hybrid[idx30], '*', markersize=14, color='yellow', zorder=7)
    ax3.annotate(
        f'30 dB design pt\nH:{sinr_hybrid[idx30]:+.0f} dB\nD:{sinr_digital[idx30]:+.0f} dB',
        xy=(30, sinr_hybrid[idx30]),
        xytext=(35, sinr_hybrid[idx30] - 4),
        fontsize=7.5, color='yellow',
        arrowprops=dict(arrowstyle='->', color='yellow', lw=0.9))

    ax3.set_xlabel("Jammer Power (dB above GPS)", fontsize=10)
    ax3.set_ylabel("Output SINR (dB)", fontsize=10)
    ax3.set_title("Hybrid vs digital — extended dynamic range", fontsize=11, fontweight='bold')
    ax3.set_xlim(0, 50)
    ax3.set_ylim(ymin_s3, ymax_s3)
    ax3.legend(fontsize=8, loc='upper right')
    ax3.grid(True, alpha=0.2)

    # ── SP4: Results summary text panel ──────────────────────────────────────
    ax4.axis('off')

    er_disp     = f"{extended_range:.0f} dB" if extended_range is not None else ">50 dB"
    er_pass_str = "YES" if er_pass else "NO"
    impr_pass   = "YES" if improvement_30 > 15 else "NO"
    fd_disp     = f"{fail_dig:.0f} dB" if fail_dig is not None else ">50 dB"

    table_rows = [
        ("DoA accuracy",  "< 1.0°",  f"{max_error:.2f}°",        "YES" if max_error < 1.0    else "NO"),
        ("Null depth J1", "> 40 dB", f"{null_depths[0]:.0f} dB", "YES" if null_depths[0] > 40 else "NO"),
        ("Null depth J2", "> 40 dB", f"{null_depths[1]:.0f} dB", "YES" if null_depths[1] > 40 else "NO"),
        ("Null depth J3", "> 40 dB", f"{null_depths[2]:.0f} dB", "YES" if null_depths[2] > 40 else "NO"),
        ("GPS passband",  "0.00 dB", f"{gps_gain_db:+.2f} dB",   "YES" if abs(gps_gain_db) < 0.01 else "NO"),
        ("Digital range", "—",       fd_disp,                     "—"),
        ("Hybrid range",  "> 10 dB", er_disp,                     er_pass_str),
        ("Improv.@30dB",  "> 15 dB", f"{improvement_30:.1f} dB",  impr_pass),
    ]
    hdr = "─" * 43
    lines = [
        "  COGNAV-4 SIMULATION SUMMARY",
        f"  {hdr}",
        f"  {'Parameter':<16}  {'Target':>8}  {'Result':>8}  {'Pass':>4}",
        f"  {hdr}",
    ]
    for param, target, result, passed in table_rows:
        lines.append(f"  {param:<16}  {target:>8}  {result:>8}  {passed:>4}")
    lines += [
        f"  {hdr}",
        "  Array: 2×2 URA  |  GPS L1 1575.42 MHz",
        "  Jammers: 3 CW from real coordinates",
        "  Pre-hardware simulation — TRL-3",
    ]

    ax4.text(0.03, 0.97, "\n".join(lines),
             transform=ax4.transAxes,
             fontsize=9.5, family='monospace',
             va='top', color='white', linespacing=1.65)

    save_path = "publication_figure.png"
    fig.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close('all')

t_end   = time.time()
runtime = t_end - t_start

print(f"\n  Pipeline runtime: {runtime:.1f} seconds")
print(f"  Figure saved to : {save_path}")
print("  run_all.py complete")
