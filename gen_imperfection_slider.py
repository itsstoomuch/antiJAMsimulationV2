"""
gen_imperfection_slider.py — interactive "ideal → realistic" degradation viewer.

ONE standalone HTML (navguard_imperfection_slider.html) with a slider for the
per-channel hardware-mismatch level (σ_phase, with proportional gain error).
Drag it and watch, live:
  • the MVDR beam-pattern sky map blur and its nulls DRIFT OFF the jammer marks,
  • the per-jammer null-depth bars COLLAPSE from ~62/50/64 dB toward single digits,
  • the readout: σ_phase, min null depth, max MUSIC DoA error.

This is the visual case for calibration + the closed-loop trim: the only thing
that changes across the slider is channel mismatch — exactly what cal/trim removes.

Physics is sim-exact (azimuth-projected steering).  A single fixed random error
pattern is SCALED by σ so the degradation is smooth and monotone, not noisy.

Input  : array_data.npy (ideal scene).
Output : navguard_imperfection_slider.html
"""
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.linalg import eigh

C, F = 3e8, 1575.42e6
LAM  = C / F
D    = LAM / 2
ELEM_POS = np.array([[0, 0, 0], [D, 0, 0], [0, D, 0], [D, D, 0]], dtype=float)
TRUE_AZ  = np.array([30.96, 165.96, -71.57])
JLAB     = ["J1", "J2", "J3"]
JCOL     = ["#ff5a4d", "#ff9e2c", "#a06bff"]


def a_ideal(az_deg):
    """Az-only unit-gain steering vector (matches run_all.py's null-depth metric)."""
    az = np.deg2rad(az_deg)
    u  = np.array([np.cos(az), np.sin(az), 0.0])
    return np.exp(1j * (2 * np.pi / LAM) * (ELEM_POS @ u))


# ── Load ideal data; build a fixed unit error pattern (seeded) ───────────────
X0 = np.load("array_data.npy")             # (4, N) ideal scene
N  = X0.shape[1]
rng = np.random.default_rng(7)
phi_unit  = rng.standard_normal(4)         # per-channel phase error shape
gain_unit = rng.standard_normal(4)         # per-channel gain  error shape

AZ_SCAN = np.linspace(-180, 180, 361)      # 1° azimuth grid
A_SCAN  = np.stack([a_ideal(az) for az in AZ_SCAN], axis=1)   # (4, 361)
a_gps   = a_ideal(0.0)
a_jams  = [a_ideal(az) for az in TRUE_AZ]

EL = np.linspace(-30, 60, 46)
env_db = 10 * np.log10(np.clip(np.cos(np.deg2rad(EL)), 1e-3, None))   # elevation envelope

SIGMAS = [0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0]   # σ_phase in degrees
FLOOR  = -55.0


def solve_scene(sig_deg):
    """Return (beam_db over AZ_SCAN, null_depths[3], max_doa_err, gps_gain)."""
    sig_phi = np.deg2rad(sig_deg)
    sig_g   = sig_deg / 100.0                       # 5° -> 0.05 (5%) gain, etc.
    E = (1.0 + sig_g * gain_unit) * np.exp(1j * sig_phi * phi_unit)   # (4,)
    X = E[:, None] * X0                             # apply channel mismatch
    R = (X @ X.conj().T) / N
    load = 1e-4 * np.trace(R).real / 4
    Rl   = R + load * np.eye(4)

    # MVDR (weights from imperfect R, assumed-ideal a_gps)
    u = np.linalg.solve(Rl, a_gps)
    w = u / (a_gps.conj() @ u)

    beam = 10 * np.log10(np.abs(w.conj() @ A_SCAN) ** 2 + 1e-20)
    beam -= beam.max()
    gps_g = 10 * np.log10(abs(w.conj() @ a_gps) ** 2 + 1e-30)
    nulls = [gps_g - 10 * np.log10(abs(w.conj() @ aj) ** 2 + 1e-30) for aj in a_jams]

    # MUSIC DoA (imperfect R) → max error vs the 3 true jammers
    evals, evecs = eigh(R)
    En = evecs[:, :1]
    proj = En.conj().T @ A_SCAN
    P = 1.0 / (np.sum(np.abs(proj) ** 2, axis=0) + 1e-12)
    pk = np.argsort(P)[::-1]
    chosen = []
    for idx in pk:
        if all(abs(AZ_SCAN[idx] - AZ_SCAN[c]) > 20 for c in chosen):
            chosen.append(idx)
        if len(chosen) == 3:
            break
    det = AZ_SCAN[chosen]
    derr = max(abs(det[np.argmin(abs(det - az))] - az) for az in TRUE_AZ)
    return beam, nulls, derr, gps_g


# ── Precompute every frame ───────────────────────────────────────────────────
frames_data = [solve_scene(s) for s in SIGMAS]


def sky_z(beam_db):
    """Broadcast the azimuth beam over elevation with the cos(el) envelope."""
    z = beam_db[None, :] + env_db[:, None]
    return np.clip(z, FLOOR, 0)


def readout(sig, nulls, derr):
    return (f"σ_phase = {sig:.1f}°   |   min null = {min(nulls):.0f} dB   "
            f"|   max DoA error = {derr:.1f}°"
            + ("   ✓ calibrated-class" if min(nulls) > 40 else
               "   ✗ below 40 dB target"))


# ── Figure: sky heatmap (left) + null-depth bars (right) ─────────────────────
fig = make_subplots(
    rows=1, cols=2, column_widths=[0.62, 0.38],
    specs=[[{"type": "xy"}, {"type": "xy"}]],
    subplot_titles=("MVDR beam pattern — sky map (nulls drift off ✕ as mismatch rises)",
                    "Null depth per jammer"),
    horizontal_spacing=0.10,
)

b0, n0, d0, g0 = frames_data[0]

# trace 0: sky heatmap
fig.add_trace(go.Heatmap(
    x=AZ_SCAN, y=EL, z=sky_z(b0), colorscale="Viridis", zmin=FLOOR, zmax=0,
    colorbar=dict(title="dB", x=0.565, len=0.9),
    hovertemplate="az %{x:.0f}° el %{y:.0f}°<br>%{z:.1f} dB<extra></extra>",
), row=1, col=1)
# trace 1: null-depth bars
fig.add_trace(go.Bar(
    x=JLAB, y=n0, marker_color=JCOL, text=[f"{v:.0f}" for v in n0],
    textposition="outside", showlegend=False,
), row=1, col=2)

# static: jammer azimuth markers on the sky map (✕ at true az/el)
JEL = [-9.73, -6.91, -4.52]
for k in range(3):
    fig.add_trace(go.Scatter(
        x=[TRUE_AZ[k]], y=[JEL[k]], mode="markers+text",
        marker=dict(symbol="x", size=12, color=JCOL[k], line=dict(width=2, color="white")),
        text=[JLAB[k]], textposition="top center", textfont=dict(color="white", size=11),
        showlegend=False), row=1, col=1)
# static: 40 dB target line on the bar chart
fig.add_trace(go.Scatter(x=[-0.5, 2.5], y=[40, 40], mode="lines",
                         line=dict(color="white", width=1.2, dash="dot"),
                         showlegend=False), row=1, col=2)

# ── Frames (update traces 0 and 1 only) ──────────────────────────────────────
frames = []
for s, (b, n, d, g) in zip(SIGMAS, frames_data):
    frames.append(go.Frame(
        name=f"{s:.1f}",
        data=[go.Heatmap(x=AZ_SCAN, y=EL, z=sky_z(b), colorscale="Viridis",
                         zmin=FLOOR, zmax=0),
              go.Bar(x=JLAB, y=n, marker_color=JCOL,
                     text=[f"{v:.0f}" for v in n], textposition="outside")],
        traces=[0, 1],
        layout=go.Layout(title=dict(text="NAVGUARD-4 — Hardware-mismatch degradation   |   "
                                         + readout(s, n, d))),
    ))
fig.frames = frames

# ── Slider + play/pause ──────────────────────────────────────────────────────
steps = [dict(method="animate", label=f"{s:.1f}°",
              args=[[f"{s:.1f}"], dict(mode="immediate",
                    frame=dict(duration=0, redraw=True), transition=dict(duration=0))])
         for s in SIGMAS]

fig.update_layout(
    template="plotly_dark",
    title=dict(text="NAVGUARD-4 — Hardware-mismatch degradation   |   " + readout(SIGMAS[0], n0, d0),
               x=0.5, font=dict(size=15)),
    sliders=[dict(active=0, currentvalue=dict(prefix="σ_phase = ", font=dict(size=14)),
                  pad=dict(t=40), steps=steps, x=0.08, len=0.84)],
    updatemenus=[dict(type="buttons", showactive=False, x=0.02, y=-0.02, xanchor="left",
                      buttons=[
                          dict(label="▶ play", method="animate",
                               args=[None, dict(frame=dict(duration=700, redraw=True),
                                                fromcurrent=True, mode="immediate")]),
                          dict(label="❚❚ pause", method="animate",
                               args=[[None], dict(frame=dict(duration=0, redraw=False),
                                                  mode="immediate")]),
                      ])],
    height=620, margin=dict(l=10, r=10, t=70, b=70),
)
fig.update_xaxes(title_text="Azimuth (deg)", row=1, col=1,
                 tickvals=np.arange(-180, 181, 45))
fig.update_yaxes(title_text="Elevation (deg)", row=1, col=1)
fig.update_yaxes(title_text="Null depth (dB)", range=[0, 70], row=1, col=2)

OUT = "navguard_imperfection_slider.html"
fig.write_html(OUT, include_plotlyjs="cdn", full_html=True)
print(f"wrote {OUT}")
print(f"{'σ_phase':>8}{'min null':>10}{'max DoA err':>13}")
for s, (b, n, d, g) in zip(SIGMAS, frames_data):
    print(f"{s:>7.1f}°{min(n):>9.0f}dB{d:>11.1f}°")
