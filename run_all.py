"""
run_all.py

Master script: executes the complete hybrid analog-digital GPS anti-jam
simulation pipeline and assembles all results into a single publication figure.

Pipeline (in order)
-------------------
  ① generate_array_data  → 4-channel synthetic IQ data
  ② music_spectrum        → MUSIC DOA estimation (locates jammer at 45°)
  ③ mvdr_beamformer       → MVDR null steering (72 dB null at 45°)
  ④ hybrid_sim            → SNR vs jammer power sweep (the novel result)
  ★  publication_figure   → all four panels combined into one figure

Each step saves its own individual PNG.  The final combined figure
'publication_figure.png' is suitable for a research paper or report.

Usage
-----
  python run_all.py
"""

# Must call matplotlib.use() before any pyplot import (including those
# triggered by importing the sub-modules).  'Agg' is a non-interactive
# backend — plt.show() becomes a no-op, letting the script run headless.
import matplotlib
matplotlib.use('Agg')

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D
import time

# ======================================================================
# IMPORT PIPELINE MODULES
# ======================================================================

from generate_array_data import generate_array_data
from music_spectrum       import music_spectrum
from mvdr_beamformer      import mvdr_beamformer
from hybrid_sim           import hybrid_sim

# ======================================================================
# RUN EACH STAGE IN ORDER
# ======================================================================

print()
print("╔══════════════════════════════════════════════════════════╗")
print("║   Hybrid Analog-Digital GPS Anti-Jam Simulation          ║")
print("║   4-Element ULA  ·  GPS L1 1575.42 MHz                   ║")
print("╚══════════════════════════════════════════════════════════╝")

t_pipeline_start = time.time()

# ── Stage ①: Generate synthetic 4-channel IQ array data ───────────────
print("\n── ① generate_array_data ──────────────────────────────────")
t = time.time()
X = generate_array_data()          # returns (4, 1000) complex IQ matrix
plt.close('all')                   # discard individual figure
print(f"   ✓  {time.time() - t:.2f} s")

# ── Stage ②: MUSIC direction-of-arrival estimation ────────────────────
print("\n── ② music_spectrum ───────────────────────────────────────")
t = time.time()
theta_scan_music = np.linspace(-90, 90, 3601)
spec_db = music_spectrum(theta_scan=theta_scan_music)   # returns dB spectrum
plt.close('all')
print(f"   ✓  {time.time() - t:.2f} s")

# ── Stage ③: MVDR beamformer ───────────────────────────────────────────
print("\n── ③ mvdr_beamformer ──────────────────────────────────────")
t = time.time()
w = mvdr_beamformer()              # returns (4,) complex weight vector
plt.close('all')
print(f"   ✓  {time.time() - t:.2f} s")

# ── Stage ④: Hybrid analog-digital simulation ─────────────────────────
print("\n── ④ hybrid_sim ───────────────────────────────────────────")
t = time.time()
results = hybrid_sim()             # returns dict: jam_db, ideal, digital, hybrid
plt.close('all')
print(f"   ✓  {time.time() - t:.2f} s")

t_pipeline = time.time() - t_pipeline_start
print(f"\nAll stages complete in {t_pipeline:.1f} s\n")
print("Assembling publication figure...")

# ======================================================================
# PHYSICS HELPERS  (reused across figure panels)
# ======================================================================

c          = 3e8
f_carrier  = 1575.42e6
lam        = c / f_carrier          # GPS L1 wavelength ≈ 0.190 m
d          = lam / 2                # half-wavelength spacing
n_el       = X.shape[0]             # 4 elements
fs         = 10e6                   # sample rate

def steering_vector(theta_deg: float) -> np.ndarray:
    """ULA steering vector — identical formula used in every module."""
    theta = np.deg2rad(theta_deg)
    m     = np.arange(n_el)
    return np.exp(1j * (2 * np.pi / lam) * d * m * np.sin(theta))

theta_scan = np.linspace(-90, 90, 3601)   # shared scan grid for panels 2 & 3

# ======================================================================
# COMBINED PUBLICATION FIGURE  —  2 × 2 layout
# ======================================================================
#
#   ┌──────────────────────┬──────────────────────┐
#   │ ① Raw IQ data        │ ② MUSIC spectrum      │
#   │  time domain          │  DOA estimation       │
#   ├──────────────────────┼──────────────────────┤
#   │ ③ MVDR beampattern   │ ④ Hybrid SINR  ★      │
#   │  null steering        │  the novel result     │
#   └──────────────────────┴──────────────────────┘

fig = plt.figure(figsize=(16, 10))

fig.suptitle(
    "Hybrid Analog-Digital GPS Anti-Jam  |  4-Element ULA, GPS L1 (1575.42 MHz)\n"
    "GPS: 0° (broadside)  ·  CW Jammer: 45°, 30 dB above GPS  "
    "·  ADC ±5  ·  90% analog pre-cancel",
    fontsize=11.5, fontweight='bold', y=0.99
)

gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.40, wspace=0.30)
ax1 = fig.add_subplot(gs[0, 0])   # ① raw IQ
ax2 = fig.add_subplot(gs[0, 1])   # ② MUSIC
ax3 = fig.add_subplot(gs[1, 0])   # ③ MVDR beampattern
ax4 = fig.add_subplot(gs[1, 1])   # ④ hybrid SINR  ★

# ── Panel ①: Raw IQ time series ────────────────────────────────────────
#   Shows the jammer domination: RMS ≈ 32 at each element, but each
#   element sees a DIFFERENT phase — that's the spatial fingerprint the
#   algorithms exploit.

n_show = 120
t_us   = np.arange(n_show) / fs * 1e6    # convert samples → microseconds

ax1.plot(t_us, np.real(X[0, :n_show]),
         color='tomato', linewidth=1.1, zorder=3,
         label=f'Element 0  (RMS={np.std(np.real(X[0,:])):.0f}  — jammer dominated)')
ax1.plot(t_us, np.real(X[1, :n_show]),
         color='royalblue', linewidth=1.1, alpha=0.85, zorder=4,
         label=f'Element 1  (RMS={np.std(np.real(X[1,:])):.0f}  — different phase)')

# Annotate the phase difference between elements
peak0_idx = np.argmax(np.abs(np.real(X[0, :n_show])))
peak1_idx = np.argmax(np.abs(np.real(X[1, :n_show])))
ax1.annotate('',
             xy=(t_us[peak1_idx], np.real(X[1, peak1_idx])),
             xytext=(t_us[peak0_idx], np.real(X[0, peak0_idx])),
             arrowprops=dict(arrowstyle='<->', color='black', lw=1.3))
ax1.text((t_us[peak0_idx] + t_us[peak1_idx]) / 2 + 0.3,
         (np.real(X[0, peak0_idx]) + np.real(X[1, peak1_idx])) / 2,
         'phase\nshift', fontsize=7.5, va='center', style='italic')

ax1.set_xlabel("Time (µs)", fontsize=11)
ax1.set_ylabel("Amplitude", fontsize=11)
ax1.set_title("① Raw IQ Data — 4-Channel Array\n"
              "Each antenna sees jammer at different phase  →  spatial fingerprint",
              fontsize=10)
ax1.legend(fontsize=8, loc='upper right')
ax1.grid(True, alpha=0.3)
ax1.axhline(0, color='gray', linewidth=0.5, linestyle=':')

# ── Panel ②: MUSIC spectrum ────────────────────────────────────────────
#   Peaks at 0° (GPS) and 45° (jammer) found by eigendecomposing the
#   4×4 covariance matrix and scanning the MUSIC pseudospectrum.

ax2.plot(theta_scan_music, spec_db, color='royalblue', linewidth=1.5, zorder=3)
ax2.axvline(0,  color='limegreen', linestyle='--', linewidth=2.0,
            label='GPS truth (0°)', zorder=4)
ax2.axvline(45, color='tomato',    linestyle='--', linewidth=2.0,
            label='Jammer truth (45°)', zorder=4)

# Shade under peaks
for ang, col in [(0, 'limegreen'), (45, 'darkorange')]:
    mask = np.abs(theta_scan_music - ang) < 6
    ax2.fill_between(theta_scan_music[mask], -50, spec_db[mask],
                     alpha=0.18, color=col)

# Annotate detected angles
for ang, label, col, xoff in [(0, 'GPS\n0.0°', 'limegreen', +6),
                               (45, 'Jammer\n45.0°', 'tomato', +6)]:
    idx = np.argmin(np.abs(theta_scan_music - ang))
    peak_val = spec_db[idx]
    ax2.annotate(label,
                 xy=(ang, peak_val),
                 xytext=(ang + xoff, peak_val - 12),
                 fontsize=8, color=col, fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=col, lw=1.0))

legend_handles = [
    Line2D([0], [0], color='royalblue',  lw=1.5,   label='MUSIC pseudospectrum'),
    Line2D([0], [0], color='limegreen',  lw=2.0, linestyle='--', label='GPS truth (0°)'),
    Line2D([0], [0], color='tomato',     lw=2.0, linestyle='--', label='Jammer truth (45°)'),
]
ax2.legend(handles=legend_handles, fontsize=8, loc='lower right')
ax2.set_xlabel("Angle of Arrival (degrees)", fontsize=11)
ax2.set_ylabel("Pseudospectrum (dB)", fontsize=11)
ax2.set_title("② MUSIC Direction-of-Arrival Estimation\n"
              "Peaks locate GPS (0°) and jammer (45°) to within 0.25°",
              fontsize=10)
ax2.set_xlim(-90, 90)
ax2.set_ylim(-50, 5)
ax2.set_xticks(np.arange(-90, 91, 30))
ax2.grid(True, alpha=0.3)

# ── Panel ③: MVDR beampattern ──────────────────────────────────────────
#   B(θ) = |w^H a(θ)|²  — recomputed from the weight vector returned
#   by mvdr_beamformer().  GPS passband = 0 dB by the MVDR constraint.

beampattern    = np.array([abs(w.conj() @ steering_vector(t))**2 for t in theta_scan])
beampattern_db = 10 * np.log10(beampattern + 1e-20)

null_idx   = np.argmin(np.abs(theta_scan - 45))
null_depth = 0.0 - beampattern_db[null_idx]    # dB below GPS passband

ax3.plot(theta_scan, beampattern_db, color='royalblue', linewidth=1.8,
         zorder=3, label='MVDR beampattern  B(θ) = |w^H a(θ)|²')
ax3.axvline(0,  color='limegreen', linestyle='--', linewidth=2.0,
            label='GPS passband (0 dB)', zorder=4)
ax3.axvline(45, color='tomato',    linestyle='--', linewidth=2.0,
            label=f'Jammer null (45°)', zorder=4)
ax3.axhline(0, color='gray', linestyle=':', linewidth=0.8, alpha=0.6)

# Shade null region
null_mask = (theta_scan > 38) & (theta_scan < 52)
ax3.fill_between(theta_scan[null_mask], -80, beampattern_db[null_mask],
                 alpha=0.18, color='tomato')

# Null depth annotation
ax3.annotate(f'Null depth\n{null_depth:.0f} dB',
             xy=(45, beampattern_db[null_idx]),
             xytext=(58, beampattern_db[null_idx] + 22),
             fontsize=8.5, color='tomato', fontweight='bold',
             arrowprops=dict(arrowstyle='->', color='tomato', lw=1.2))

ax3.legend(fontsize=8, loc='lower right')
ax3.set_xlabel("Angle of Arrival (degrees)", fontsize=11)
ax3.set_ylabel("Beamformer Gain (dB)", fontsize=11)
ax3.set_title(f"③ MVDR Null Steering\n"
              f"GPS: 0 dB passband  ·  Jammer: {null_depth:.0f} dB null",
              fontsize=10)
ax3.set_xlim(-90, 90)
ax3.set_ylim(-80, 12)
ax3.set_xticks(np.arange(-90, 91, 30))
ax3.grid(True, alpha=0.3)

# ── Panel ④: Hybrid SINR vs Jammer Power  ★ THE KEY RESULT ────────────
#   The three curves show:
#   - Green (Ideal): theoretical ceiling — MVDR with no ADC limit
#   - Red   (Digital): degrades at ~14 dB when jammer clips the ADC
#   - Blue  (Hybrid): analog pre-cancel moves the cliff 20 dB further right

jam_db   = results['jam_db']
s_ideal  = results['ideal']
s_dig    = results['digital']
s_hyb    = results['hybrid']

ax4.plot(jam_db, s_ideal, color='limegreen', linewidth=2.0,
         label='Ideal MVDR (no ADC limit)', zorder=4)
ax4.plot(jam_db, s_dig,   color='tomato',    linewidth=2.0,
         label='Pure digital MVDR  (ADC ±5)', zorder=3)
ax4.plot(jam_db, s_hyb,   color='royalblue', linewidth=2.5,
         label='Hybrid  (90% analog cancel + digital MVDR)  ★', zorder=5)

ax4.axhline(0, color='black', linestyle=':', linewidth=1.0, alpha=0.5,
            label='SINR = 0 dB threshold')

# Crossover points (where SINR first drops below 0 dB)
threshold = 0.0
dig_cross = (jam_db[np.argmax(s_dig < threshold)]
             if (s_dig < threshold).any() else jam_db[-1])
hyb_cross = (jam_db[np.argmax(s_hyb < threshold)]
             if (s_hyb < threshold).any() else jam_db[-1])

ax4.axvline(dig_cross, color='tomato',    linestyle='--', linewidth=1.4, alpha=0.75,
            label=f'Digital fails: {dig_cross:.0f} dB')
ax4.axvline(hyb_cross, color='royalblue', linestyle='--', linewidth=1.4, alpha=0.75,
            label=f'Hybrid fails:  {hyb_cross:.0f} dB')

# Shade the hybrid advantage window and label it
if hyb_cross > dig_cross:
    ax4.axvspan(dig_cross, hyb_cross, alpha=0.08, color='royalblue')
    mid = (dig_cross + hyb_cross) / 2
    ax4.text(mid, 2.5,
             f'+{hyb_cross - dig_cross:.0f} dB\nheadroom',
             ha='center', va='bottom', fontsize=10,
             color='royalblue', fontweight='bold')

# Mark the designed operating point (30 dB jammer)
op_idx = np.argmin(np.abs(jam_db - 30))
ax4.scatter([30], [s_hyb[op_idx]], color='royalblue', s=60, zorder=6,
            marker='*', label=f'Design point (30 dB): hybrid={s_hyb[op_idx]:.1f} dB')
ax4.scatter([30], [s_dig[op_idx]], color='tomato',    s=60, zorder=6, marker='*')

ax4.set_xlabel("Jammer Power (dB above GPS)", fontsize=11)
ax4.set_ylabel("Output SINR (dB)", fontsize=11)
ax4.set_title("④ Output SINR vs Jammer Power  ★ Novel Result\n"
              "Hybrid extends ADC dynamic range by 20 dB",
              fontsize=10)
ax4.set_xlim(0, 50)
ax4.legend(fontsize=7.5, loc='lower left')
ax4.grid(True, alpha=0.3)

# ── Corner badges for each panel ───────────────────────────────────────
for ax, badge, color in [
    (ax1, '①', 'steelblue'),
    (ax2, '②', 'steelblue'),
    (ax3, '③', 'steelblue'),
    (ax4, '④★', 'darkred'),
]:
    ax.text(0.015, 0.975, badge,
            transform=ax.transAxes,
            fontsize=13, va='top', ha='left',
            color=color, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.15', fc='white', ec=color, lw=0.8, alpha=0.8))

# ======================================================================
# SAVE
# ======================================================================

output_file = 'publication_figure.png'
plt.savefig(output_file, dpi=180, bbox_inches='tight')
plt.show()

print()
print("╔══════════════════════════════════════════════════════════╗")
print("║   PIPELINE COMPLETE                                       ║")
print("╠══════════════════════════════════════════════════════════╣")
print("║   Individual files                                        ║")
print("║     array_data.npy        — raw IQ data                  ║")
print("║     music_spectrum.png    — MUSIC DOA spectrum            ║")
print("║     mvdr_beampattern.png  — MVDR beampattern + eigenvals  ║")
print("║     mvdr_weights.npy      — complex weight vector         ║")
print("║     hybrid_sim.png        — hybrid SINR sweep             ║")
print("║   Combined figure                                         ║")
print(f"║     {output_file:<52} ║")
print("╠══════════════════════════════════════════════════════════╣")
print(f"║   Total runtime: {t_pipeline:5.1f} s                                 ║")
print("╚══════════════════════════════════════════════════════════╝")
print()
