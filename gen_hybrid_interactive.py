"""
gen_hybrid_interactive.py — interactive hybrid dynamic-range explorer.

Standalone HTML (navguard_hybrid.html): the full Ideal / pure-digital / hybrid
SINR-vs-jammer-power curves, plus a slider you drag along the jammer-power axis.
At each setting a sweep line + three markers show the live SINR, and the readout
calls out where pure-digital has collapsed (ADC saturated) while hybrid still
holds — the project's novel result, made explorable.

Input  : (computes via hybrid_sim()).
Output : navguard_hybrid.html
"""
import numpy as np
import plotly.graph_objects as go
from hybrid_sim import hybrid_sim

res = hybrid_sim()
jam   = np.asarray(res["jam_db"], float)
ideal = np.asarray(res["ideal"], float)
dig   = np.asarray(res["digital"], float)
hyb   = np.asarray(res["hybrid"], float)


def first_fail(s):
    m = s < 0.0
    return float(jam[np.argmax(m)]) if m.any() else None


fd, fh = first_fail(dig), first_fail(hyb)
ymin = float(min(dig.min(), hyb.min())) - 4
ymax = float(ideal.max()) + 4

GREEN, RED, BLUE = "#28e07a", "#ff5a4d", "#4da6ff"
fig = go.Figure()
# full curves (static)
fig.add_trace(go.Scatter(x=jam, y=ideal, name="Ideal (no ADC)", line=dict(color=GREEN, width=2)))
fig.add_trace(go.Scatter(x=jam, y=dig,   name="Pure digital",   line=dict(color=RED, width=2)))
fig.add_trace(go.Scatter(x=jam, y=hyb,   name="Hybrid (pre-cancel)", line=dict(color=BLUE, width=2)))
fig.add_hline(y=0, line=dict(color="white", width=1, dash="dot"))
if fd is not None:
    fig.add_vline(x=fd, line=dict(color=RED, width=1, dash="dash"))
if fh is not None:
    fig.add_vline(x=fh, line=dict(color=BLUE, width=1, dash="dash"))

# subsample slider positions for a compact file
idx = np.linspace(0, len(jam) - 1, min(26, len(jam))).astype(int)


def readout(i):
    d_state = "FAIL" if dig[i] < 0 else "ok"
    h_state = "FAIL" if hyb[i] < 0 else "ok"
    return (f"J/S = {jam[i]:.0f} dB   |   Ideal {ideal[i]:+.0f}   "
            f"Digital {dig[i]:+.0f} ({d_state})   Hybrid {hyb[i]:+.0f} ({h_state})")


# initial sweep marker/line (traces 4,5)
i0 = idx[0]
fig.add_trace(go.Scatter(x=[jam[i0], jam[i0]], y=[ymin, ymax], mode="lines",
                         line=dict(color="white", width=1), showlegend=False))
fig.add_trace(go.Scatter(x=[jam[i0]] * 3, y=[ideal[i0], dig[i0], hyb[i0]], mode="markers",
                         marker=dict(size=12, color=[GREEN, RED, BLUE],
                                     line=dict(width=1, color="white")), showlegend=False))

frames = [go.Frame(name=str(int(i)),
                   data=[go.Scatter(x=[jam[i], jam[i]], y=[ymin, ymax]),
                         go.Scatter(x=[jam[i]] * 3, y=[ideal[i], dig[i], hyb[i]])],
                   traces=[4, 5],
                   layout=go.Layout(title=dict(text="NAVGUARD-4 Hybrid Dynamic Range   |   " + readout(i))))
          for i in idx]
fig.frames = frames

steps = [dict(method="animate", label=f"{jam[i]:.0f}",
              args=[[str(int(i))], dict(mode="immediate", frame=dict(duration=0, redraw=True),
                                        transition=dict(duration=0))]) for i in idx]

fig.update_layout(
    template="plotly_dark",
    title=dict(text="NAVGUARD-4 Hybrid Dynamic Range   |   " + readout(i0), x=0.5, font=dict(size=15)),
    xaxis_title="Jammer power (dB above GPS)", yaxis_title="Output SINR (dB)",
    xaxis=dict(range=[jam.min(), jam.max()]), yaxis=dict(range=[ymin, ymax]),
    legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
    sliders=[dict(active=0, currentvalue=dict(prefix="J/S = ", suffix=" dB"),
                  pad=dict(t=45), steps=steps, x=0.06, len=0.88)],
    updatemenus=[dict(type="buttons", x=0.0, y=-0.06, xanchor="left", showactive=False,
                      buttons=[dict(label="▶ play", method="animate",
                                    args=[None, dict(frame=dict(duration=350, redraw=True),
                                                     fromcurrent=True)]),
                               dict(label="❚❚", method="animate",
                                    args=[[None], dict(frame=dict(duration=0, redraw=False),
                                                       mode="immediate")])])],
    height=620, margin=dict(l=10, r=10, t=70, b=80),
)
OUT = "navguard_hybrid.html"
fig.write_html(OUT, include_plotlyjs="cdn", full_html=True)
print(f"wrote {OUT}  (digital fails @ {fd} dB, hybrid @ {fh} dB)")
