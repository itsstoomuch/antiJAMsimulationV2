"""
gen_subspace.py — "why the true-3D model broke MUSIC", made visible.

Standalone HTML (navguard_subspace.html) with a slider for GPS amplitude at zenith.
As you raise it, GPS enters the data as a 4th source ([1,1,1,1] broadside vector)
and you watch, live:
  • the covariance eigenvalues — a 4th eigenvalue lifts off the noise floor, so
    the noise subspace (which MUSIC needs) collapses from 1-D toward 0-D;
  • the MUSIC azimuth spectrum — a SPURIOUS ridge grows and competes with the
    true jammer peaks.
That is exactly why the 3D-phase steering model (which keeps zenith GPS present)
was reverted: 3 jammers + GPS = 4 sources in a 4-element array = no margin.

Input  : array_data.npy (ideal 3-jammer scene).
Output : navguard_subspace.html
"""
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.linalg import eigh

C, F = 3e8, 1575.42e6
LAM, = (C / F,)
D = LAM / 2
ELEM_POS = np.array([[0, 0, 0], [D, 0, 0], [0, D, 0], [D, D, 0]], dtype=float)
TRUE_AZ = [30.96, 165.96, -71.57]


def a_ideal(az):
    az = np.deg2rad(az)
    u = np.array([np.cos(az), np.sin(az), 0.0])
    return np.exp(1j * (2 * np.pi / LAM) * (ELEM_POS @ u))


X0 = np.load("array_data.npy")                 # (4, N) — 3 jammers, ideal
N = X0.shape[1]
# reference jammer amplitude scale (so GPS amplitude is comparable)
scale = np.sqrt(np.mean(np.abs(X0) ** 2))

# GPS at zenith with the (reverted) 3D model: u=[0,0,1] -> phase 0 -> [1,1,1,1]
a_gps_zenith = np.ones(4, dtype=complex)
rng = np.random.default_rng(3)
s_gps = (rng.standard_normal(N) + 1j * rng.standard_normal(N)) / np.sqrt(2)

AZ = np.linspace(-180, 180, 361)
A = np.stack([a_ideal(az) for az in AZ], axis=1)   # (4, 361)

GPS_AMP = [0.0, 0.25]                          # two states: OFF (realistic) vs forced ON
GLABEL = {0.0: "GPS OFF  (realistic — invisible)", 0.25: "GPS forced ON  (the stress test)"}


def scene(gain):
    X = X0 + gain * scale * np.outer(a_gps_zenith, s_gps)
    R = (X @ X.conj().T) / N
    ev, evec = eigh(R)                          # ascending
    ev = ev[::-1]                               # descending: λ1..λ4
    En = evec[:, :1]                            # assume 1-D noise subspace (n_signals=3)
    proj = En.conj().T @ A
    P = 1.0 / (np.sum(np.abs(proj) ** 2, axis=0) + 1e-12)
    Pdb = 10 * np.log10(P / P.max())
    gap = ev[2] / max(ev[3], 1e-30)             # 3rd/4th eigenvalue ratio (signal/noise margin)
    return ev, Pdb, gap


data = [scene(g) for g in GPS_AMP]
EVcol = ["#4da6ff", "#4da6ff", "#4da6ff", "#ff5a4d"]   # λ4 (the intruder) in red


def readout(g, ev, gap):
    if g == 0.0:
        return "GPS OFF — MUSIC sees 3 jammers cleanly, finds them all (no ghost)"
    return "GPS forced ON — a 4th signal overloads the 4-antenna array → MUSIC errors (ghost peak appears)"


fig = make_subplots(rows=1, cols=2, column_widths=[0.4, 0.6],
                    specs=[[{"type": "xy"}, {"type": "xy"}]],
                    subplot_titles=("Signals the math sees (4th bar = GPS intruding)",
                                    "Jammer-finder output (a fake 'ghost' peak appears)"))

ev0, P0, gap0 = data[0]
fig.add_trace(go.Bar(x=["λ1", "λ2", "λ3", "λ4"], y=ev0, marker_color=EVcol,
                     showlegend=False), row=1, col=1)
fig.add_trace(go.Scatter(x=AZ, y=P0, line=dict(color="#ff8c42", width=1.6),
                         showlegend=False), row=1, col=2)
for az in TRUE_AZ:
    fig.add_trace(go.Scatter(x=[az, az], y=[-60, 2], mode="lines",
                             line=dict(color="#28e07a", width=1, dash="dash"),
                             showlegend=False), row=1, col=2)

TITLE = "Why a 4-antenna array must keep GPS out of the jammer-finder"

frames = [go.Frame(name=f"{g:.2f}",
                   data=[go.Bar(x=["#1", "#2", "#3", "#4"], y=ev, marker_color=EVcol),
                         go.Scatter(x=AZ, y=Pdb, line=dict(color="#ff8c42", width=1.6))],
                   traces=[0, 1],
                   layout=go.Layout(title=dict(text=TITLE + "<br><span style='font-size:13px;"
                                                    "color:#8b949e'>" + readout(g, ev, gap) + "</span>")))
          for g, (ev, Pdb, gap) in zip(GPS_AMP, data)]
fig.frames = frames

buttons = [dict(method="animate", label=GLABEL[g],
                args=[[f"{g:.2f}"], dict(mode="immediate", frame=dict(duration=0, redraw=True),
                                         transition=dict(duration=0))]) for g in GPS_AMP]

fig.update_layout(
    template="plotly_dark",
    title=dict(text=TITLE + "<br><span style='font-size:13px;color:#8b949e'>"
                    + readout(GPS_AMP[0], ev0, gap0) + "</span>", x=0.5, font=dict(size=16)),
    updatemenus=[dict(type="buttons", direction="right", showactive=True, x=0.5, y=1.14,
                      xanchor="center", buttons=buttons, bgcolor="#161b22",
                      font=dict(size=13), pad=dict(t=2, b=2))],
    annotations=[dict(
        text=("<b>What this is:</b> a deliberate \"what if GPS weren't invisible?\" stress test. "
              "Rule: 4 antennas can separate at most 3 signals. With 3 jammers + a strong GPS = "
              "4 signals, the jammer-finder breaks. Real GPS is far too weak to do this "
              "(it sits below the noise) — which is exactly why the design works."),
        x=0.5, y=-0.16, xref="paper", yref="paper", showarrow=False, align="center",
        font=dict(color="#8b949e", size=12.5))],
    height=580, margin=dict(l=10, r=10, t=92, b=86),
)
fig.update_yaxes(type="log", title_text="eigenvalue", row=1, col=1)
fig.update_xaxes(title_text="azimuth (deg)", tickvals=np.arange(-180, 181, 45), row=1, col=2)
fig.update_yaxes(title_text="MUSIC (dB)", range=[-60, 3], row=1, col=2)

OUT = "navguard_subspace.html"
fig.write_html(OUT, include_plotlyjs="cdn", full_html=True)
print(f"wrote {OUT}")
for g, (ev, Pdb, gap) in zip(GPS_AMP, data):
    print(f"  GPS amp {g:.2f}×  λ3/λ4 margin {gap:,.0f}×")
