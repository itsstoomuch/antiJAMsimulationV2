"""
gen_video.py — render a short, WhatsApp-friendly MP4 of the NAVGUARD anti-jam demo.

Story (legible on a phone): a moving jammer, and the 4-element CRPA's MVDR null
steers to track and block it, while the GPS direction stays at 0 dB (locked).
Square 1080x1080, dark, big fonts. Uses the same analytic MVDR as the playground.

Output: navguard_demo.mp4
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, FFMpegWriter

# ── analytic MVDR (half-wavelength 2x2 URA), same convention as the playground ──
def steer(az_deg):
    az = np.deg2rad(az_deg); c, s = np.cos(az), np.sin(az)
    return np.array([1, np.exp(1j*np.pi*c), np.exp(1j*np.pi*s), np.exp(1j*np.pi*(c+s))])

def mvdr(jam_az, js_db=30.0):
    P = 10**(js_db/10)
    aj = steer(jam_az)
    R = np.eye(4, dtype=complex) + P*np.outer(aj, aj.conj())
    ag = steer(0.0)
    u = np.linalg.solve(R, ag); w = u/(ag.conj() @ u)
    return w

AZ = np.linspace(-180, 180, 361)
FLOOR = -50.0

# jammer sweeps around the BACK arc (30°→330°) and back — never sits on GPS (0°)
sweep = np.concatenate([np.linspace(30, 330, 90), np.linspace(330, 30, 90)])

# precompute every frame
frames = []
for jam in sweep:
    w = mvdr(jam)
    b = np.array([abs(w.conj() @ steer(az))**2 for az in AZ])
    bdb = 10*np.log10(b + 1e-20)
    gps = 10*np.log10(abs(w.conj() @ steer(0))**2 + 1e-20)
    bdb -= gps                                   # GPS -> 0 dB reference
    null = -(10*np.log10(abs(w.conj() @ steer(jam))**2 + 1e-20) - gps)
    frames.append((jam, bdb, null))

# ── figure ────────────────────────────────────────────────────────────────────
plt.rcParams.update({"font.family": "DejaVu Sans"})
fig = plt.figure(figsize=(8, 8), dpi=135, facecolor="#0d1117")
ax = fig.add_subplot(111, projection="polar", facecolor="#0d1117")
fig.subplots_adjust(top=0.84, bottom=0.10, left=0.05, right=0.95)

fig.text(0.5, 0.945, "NAVGUARD-4  —  Adaptive Anti-Jamming CRPA",
         ha="center", color="white", fontsize=20, fontweight="bold")
fig.text(0.5, 0.905, "4-element GPS L1 array · the null steers to block the jammer · GPS stays locked",
         ha="center", color="#8b949e", fontsize=11.5)
readout = fig.text(0.5, 0.045, "", ha="center", color="white", fontsize=13, fontweight="bold")

theta = np.deg2rad(AZ)

def draw(i):
    ax.clear()
    ax.set_facecolor("#0d1117")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_rlim(0, -FLOOR)
    ax.set_rticks([]); ax.set_xticks(np.deg2rad(np.arange(0, 360, 45)))
    ax.set_xticklabels(["0°","45°","90°","135°","180°","-135°","-90°","-45°"],
                       color="#8b949e", fontsize=10)
    ax.grid(color="#30363d", alpha=0.6)

    jam, bdb, null = frames[i]
    r = np.clip(bdb - FLOOR, 0, None)
    ax.fill(theta, r, color="#4da6ff", alpha=0.18, zorder=2)
    ax.plot(theta, r, color="#4da6ff", lw=2, zorder=3)

    # GPS (locked, 0°)
    ax.plot([0, 0], [0, -FLOOR], color="#28e07a", lw=2.5, zorder=4)
    ax.plot(0, -FLOOR, marker="o", ms=11, color="#28e07a", zorder=6)
    ax.text(0, -FLOOR+3, "GPS", color="#28e07a", ha="center", fontsize=12, fontweight="bold")

    # jammer (moving) + its null
    jt = np.deg2rad(jam)
    ax.plot([jt, jt], [0, -FLOOR], color="#ff5a4d", lw=2.2, ls="--", zorder=4)
    ax.plot(jt, -FLOOR, marker="X", ms=14, color="#ff5a4d",
            markeredgecolor="white", markeredgewidth=1.2, zorder=6)
    ax.text(jt, -FLOOR+3, "JAMMER", color="#ff5a4d", ha="center", fontsize=12, fontweight="bold")

    readout.set_text(f"Jammer at {jam:+.0f}°   blocked −{null:.0f} dB        GPS kept at 0 dB ✓")
    return []

anim = FuncAnimation(fig, draw, frames=len(frames), interval=55, blit=False)
writer = FFMpegWriter(fps=22, bitrate=2600,
                      extra_args=["-pix_fmt", "yuv420p"])   # yuv420p = plays on phones
OUT = "navguard_demo.mp4"
anim.save(OUT, writer=writer)
plt.close(fig)
print(f"wrote {OUT}  ({len(frames)} frames)")
