"""
gen_skyview.py — interactive Sky-View + 3D scene with jammer count + type selection.

ONE standalone HTML (navguard_skyview.html). A dropdown lets you pick:
  • how many jammers (1 / 2 / 3), and
  • the jammer TYPE (CW tone / swept FMCW / barrage noise).
and the view updates live:
  • 3D MVDR radiation pattern — dents = nulls; one per jammer (markers show their bearings),
  • the jammer's spectral signature — CW line vs FMCW chirp-spread vs barrage band (the "effect"),
  • per-jammer null depth.

Each of the 9 scenarios is computed from real synthetic IQ (so the type genuinely shapes the
covariance), using the sim's azimuth-projected steering + cos(el) element pattern.

Output: navguard_skyview.html
"""
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

C, F = 3e8, 1575.42e6
LAM = C / F
D = LAM / 2
ELEM = np.array([[0, 0, 0], [D, 0, 0], [0, D, 0], [D, D, 0]], dtype=float)
JAZ = [30.96, 165.96, -71.57]          # jammer azimuths
JEL = [-9.73, -6.91, -4.52]            # jammer elevations
JCOL = ["#ff5a4d", "#ff9e2c", "#a06bff"]

fs, N = 10e6, 1024
t = np.arange(N) / fs
A_JAM = 10**(30/20)                     # 30 dB above GPS

def gpat(el):                          # element pattern amplitude
    return np.sqrt(max(np.cos(np.deg2rad(el)), 0.0))

def steer(az, el):
    a = np.deg2rad(az)
    u = np.array([np.cos(a), np.sin(a), 0.0])
    return gpat(el) * np.exp(1j * (2*np.pi/LAM) * (ELEM @ u))

def waveform(kind, j, rng):
    # j = jammer index — distinct carrier per jammer decorrelates independent emitters
    if kind == "CW":
        return np.exp(2j*np.pi*(1.0e6 + j*1.1e6)*t)                       # distinct tone
    if kind == "FMCW":
        B, f0, rate = 3e6, -3.2e6 + j*1.0e6, 3e6/(N/fs)
        return np.exp(2j*np.pi*(f0*t + 0.5*rate*t*t))                     # distinct chirp
    return (rng.standard_normal(N) + 1j*rng.standard_normal(N))/np.sqrt(2)   # barrage noise

EFFECT = {
    "CW":      "Continuous-wave tone — a sharp spectral line. Easiest to characterise; nulled by direction.",
    "FMCW":    "Swept chirp — spreads across the band and stresses the receiver front-end; still nulled by direction.",
    "Barrage": "Wideband noise — fills the band, hardest to filter in frequency; suppressed spatially by the null.",
}

# ── sky grid for the 3D radiation surface (kept modest so 9 scenarios stay light) ──
AZ = np.linspace(-180, 180, 97)
EL = np.linspace(-30, 90, 43)
AZg, ELg = np.meshgrid(AZ, EL)
FLOOR = -45.0
# sleek "energy glow" colorscale: deep navy nulls → electric blue → cyan → pale gold peaks
GLOW = [[0.0, "#0a1733"], [0.22, "#143a82"], [0.45, "#1f7bff"], [0.68, "#34d3ff"],
        [0.86, "#9bf0cf"], [1.0, "#f6ffd9"]]
LIGHT = dict(ambient=0.5, diffuse=0.85, specular=0.5, roughness=0.42, fresnel=0.25)
LIGHTPOS = dict(x=120, y=220, z=170)

def scene(n, kind):
    rng = np.random.default_rng(hash((n, kind)) % 2**32)
    X = (0.05*(rng.standard_normal((4, N)) + 1j*rng.standard_normal((4, N))))   # noise floor
    for k in range(n):
        X += A_JAM * steer(JAZ[k], JEL[k])[:, None] * waveform(kind, k, rng)[None, :]
    R = (X @ X.conj().T) / N
    R += (1e-3*np.trace(R).real/4) * np.eye(4)
    ag = steer(0, 0)
    w = np.linalg.solve(R, ag); w = w/(ag.conj() @ w)
    gps = 10*np.log10(abs(w.conj() @ ag)**2 + 1e-20)
    nulls = [gps - 10*np.log10(abs(w.conj() @ steer(JAZ[k], JEL[k]))**2 + 1e-20) for k in range(n)]
    # radiation surface
    gain = np.empty_like(AZg)
    for i in range(AZg.shape[0]):
        for j in range(AZg.shape[1]):
            gain[i, j] = 10*np.log10(abs(w.conj() @ steer(AZg[i, j], ELg[i, j]))**2 + 1e-20)
    gain -= gain.max()
    r = np.clip((gain - FLOOR)/(0 - FLOOR), 0, 1)
    azr, elr = np.deg2rad(AZg), np.deg2rad(ELg)
    Xs, Ys, Zs = r*np.cos(elr)*np.cos(azr), r*np.cos(elr)*np.sin(azr), r*np.sin(elr)
    # jammer markers + rays from the origin
    jx, jy, jz, jt = [], [], [], []
    rx, ry, rz = [], [], []
    for k in range(n):
        a, e = np.deg2rad(JAZ[k]), np.deg2rad(JEL[k])
        mx, my, mz = 1.2*np.cos(e)*np.cos(a), 1.2*np.cos(e)*np.sin(a), 1.2*np.sin(e)
        jx.append(mx); jy.append(my); jz.append(mz); jt.append(f"J{k+1}")
        rx += [0, mx, None]; ry += [0, my, None]; rz += [0, mz, None]
    # combined spectrum of all active jammers (multiple lines = multiple jammers)
    wf = np.zeros(N, complex)
    for k in range(n):
        wf += waveform(kind, k, np.random.default_rng(7+k))
    psd = 20*np.log10(np.abs(np.fft.fftshift(np.fft.fft(wf*np.hanning(N)))) + 1e-9)
    psd -= psd.max()
    freq = np.fft.fftshift(np.fft.fftfreq(N, 1/fs))/1e6   # MHz
    return dict(Xs=Xs, Ys=Ys, Zs=Zs, gain=gain, jx=jx, jy=jy, jz=jz, jt=jt,
                rx=rx, ry=ry, rz=rz, nulls=nulls, gps=gps, freq=freq, psd=psd)

COUNTS, TYPES = [1, 2, 3], ["CW", "FMCW", "Barrage"]
combos = [(n, k) for k in TYPES for n in COUNTS]
data = {(n, k): scene(n, k) for (n, k) in combos}

def readout(n, k, d):
    nd = "  ".join(f"J{i+1} −{d['nulls'][i]:.0f}dB" for i in range(n))
    return f"{n} jammer{'s' if n>1 else ''} · {k}    |    nulls: {nd}    |    GPS held 0 dB"

# ── figure ────────────────────────────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=2, column_widths=[0.58, 0.42], row_heights=[0.55, 0.45],
    specs=[[{"type": "scene", "rowspan": 2}, {"type": "xy"}],
           [None, {"type": "xy"}]],
    subplot_titles=("3D antenna pattern — dents = nulls on the jammers",
                    "Jammer spectral signature", "Null depth per jammer"),
    horizontal_spacing=0.06, vertical_spacing=0.12)

def surf(d):
    return go.Surface(x=d["Xs"], y=d["Ys"], z=d["Zs"], surfacecolor=d["gain"],
                      colorscale=GLOW, cmin=FLOOR, cmax=0, showscale=False, opacity=1.0,
                      lighting=LIGHT, lightposition=LIGHTPOS,
                      hovertemplate="gain %{surfacecolor:.0f} dB<extra></extra>")
def rays(d):
    return go.Scatter3d(x=d["rx"], y=d["ry"], z=d["rz"], mode="lines",
                        line=dict(color="#ff5a4d", width=4), hoverinfo="skip", showlegend=False)
def marks(d):
    return go.Scatter3d(x=d["jx"], y=d["jy"], z=d["jz"], mode="markers+text",
                        marker=dict(size=7, color="#ff5a4d", line=dict(color="white", width=1)),
                        text=d["jt"], textposition="top center",
                        textfont=dict(color="#ff9a90", size=12), name="jammers")

init = data[(3, "CW")]
fig.add_trace(surf(init), row=1, col=1)                                    # 0
fig.add_trace(rays(init), row=1, col=1)                                    # 1
fig.add_trace(marks(init), row=1, col=1)                                   # 2
fig.add_trace(go.Scatter3d(x=[0, 0], y=[0, 0], z=[0, 1.35], mode="lines+markers+text",  # 3
              line=dict(color="#28e07a", width=5), marker=dict(size=[0, 6], color="#28e07a"),
              text=["", "GPS (zenith)"], textposition="top center",
              textfont=dict(color="#7df0b0", size=12), name="GPS"), row=1, col=1)
fig.add_trace(go.Scatter(x=init["freq"], y=init["psd"], line=dict(color="#ff9e2c", width=1.6),  # 4
              showlegend=False), row=1, col=2)
fig.add_trace(go.Bar(x=[f"J{i+1}" for i in range(3)], y=init["nulls"], marker_color=JCOL[:3],   # 5
              text=[f"{v:.0f}" for v in init["nulls"]], textposition="outside",
              showlegend=False), row=2, col=2)

frames = []
for (n, k) in combos:
    d = data[(n, k)]
    frames.append(go.Frame(name=f"{n}|{k}", traces=[0, 1, 2, 4, 5],
        data=[surf(d), rays(d), marks(d),
              go.Scatter(x=d["freq"], y=d["psd"], line=dict(color="#ff9e2c", width=1.6)),
              go.Bar(x=[f"J{i+1}" for i in range(n)], y=d["nulls"], marker_color=JCOL[:n],
                     text=[f"{v:.0f}" for v in d["nulls"]], textposition="outside")],
        layout=go.Layout(title=dict(text="NAVGUARD-4 Sky-View   |   " + readout(n, k, d) +
                                         "<br><span style='font-size:12px;color:#8b949e'>" +
                                         EFFECT[k] + "</span>"))))
fig.frames = frames

buttons = [dict(method="animate", label=f"{n} · {k}",
                args=[[f"{n}|{k}"], dict(mode="immediate", frame=dict(duration=0, redraw=True),
                                         transition=dict(duration=0))]) for (n, k) in combos]

fig.update_layout(
    template="plotly_dark",
    title=dict(text="NAVGUARD-4 Sky-View   |   " + readout(3, "CW", init) +
                    "<br><span style='font-size:12px;color:#8b949e'>" + EFFECT["CW"] + "</span>",
               x=0.5, font=dict(size=15)),
    updatemenus=[dict(buttons=buttons, direction="down", showactive=True,
                      x=0.0, y=1.13, xanchor="left", bgcolor="#161b22",
                      font=dict(size=12.5), pad=dict(t=4, b=4))],
    scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False), zaxis=dict(visible=False),
               bgcolor="#06080f", aspectmode="cube",
               camera=dict(eye=dict(x=1.45, y=1.45, z=0.75),
                           up=dict(x=0, y=0, z=1), center=dict(x=0, y=0, z=-0.05))),
    annotations=[dict(text="◀ choose jammers × type", x=0.18, y=1.105, xref="paper",
                      yref="paper", showarrow=False, font=dict(color="#8b949e", size=12))],
    margin=dict(l=6, r=6, t=96, b=10), height=720)
fig.update_xaxes(title_text="frequency (MHz)", row=1, col=2)
fig.update_yaxes(title_text="power (dB)", range=[-60, 3], row=1, col=2)
fig.update_yaxes(title_text="null depth (dB)", range=[0, max(60, init["nulls"][0]+10)], row=2, col=2)

OUT = "navguard_skyview.html"
fig.write_html(OUT, include_plotlyjs="cdn", full_html=True)
print(f"wrote {OUT}  ({len(combos)} scenarios)")
for (n, k) in combos:
    d = data[(n, k)]
    print(f"  {n} x {k:8s}  nulls {[round(x) for x in d['nulls']]}")
