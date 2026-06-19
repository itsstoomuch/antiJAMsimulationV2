"""
build_viz.py — one command builds EVERY NAVGUARD-4 visualization at once.

Runs the simulation pipeline (static matplotlib figures) AND all the interactive
Plotly dashboards, collects everything into ./viz/, and writes viz/index.html —
a single gallery page linking the interactive HTMLs and showing the static PNGs.

Usage:
    python build_viz.py        # build everything, then open viz/index.html

This is independent of the Flask/Three.js app in navguard_viz/ (that one is a
separate server-based effort).
"""
import os
import shutil
import subprocess
import sys
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(ROOT, "viz")
PY   = sys.executable

# (script, [artifacts it produces])  — run in order; each is independently runnable
STEPS = [
    ("run_all.py", [
        "publication_figure.png", "music_spectrum.png", "mvdr_beampattern.png",
        "hybrid_sim.png", "realistic_comparison.png",
    ]),
    ("gen_skyview.py",             ["navguard_skyview.html"]),
    ("gen_imperfection_slider.py", ["navguard_imperfection_slider.html"]),
    ("gen_hybrid_interactive.py",  ["navguard_hybrid.html"]),
]

# Hand-written client-side HTML (not produced by a gen_*.py — just copied in)
STATIC_FILES = ["navguard_playground.html"]

# Gallery metadata: file -> (title, blurb, kind)
META = {
    "navguard_playground.html": (
        "Jammer Playground (live)",
        "Pick 1–3 jammers and drag their azimuths — the MVDR nulls re-steer live in your "
        "browser. The interactive 'what if' tool.", "html"),
    "navguard_skyview.html": (
        "Interactive Sky-View + 3D Scene",
        "Rotatable 3D radiation pattern (dents = nulls point at jammer rays) plus "
        "az×el sky maps for MVDR and MUSIC and a polar azimuth cut.", "html"),
    "navguard_imperfection_slider.html": (
        "Ideal → Realistic Degradation Slider",
        "Drag the channel-mismatch slider and watch the nulls drift off the jammers "
        "and collapse from ~50 dB to ~5 dB — the case for calibration + trim.", "html"),
    "navguard_hybrid.html": (
        "Hybrid Dynamic-Range Explorer",
        "Drag along the jammer-power axis: in this simulation pure-digital collapses as the ADC "
        "saturates, while the hybrid pre-canceller holds longer.", "html"),
    "publication_figure.png": (
        "Publication Figure (4-panel)",
        "MUSIC DoA, MVDR null steering, hybrid SINR vs jammer power, KPI summary.", "png"),
    "realistic_comparison.png": (
        "Ideal vs Realistic Comparison",
        "MUSIC pseudospectrum and per-jammer null depth, ideal vs hardware-imperfect.", "png"),
    "music_spectrum.png": (
        "MUSIC Pseudospectrum",
        "Spatial spectrum + covariance eigenvalues (3 signal + 1 noise).", "png"),
    "mvdr_beampattern.png": (
        "MVDR Beam Pattern",
        "Beam pattern with three simultaneous nulls + null-depth chart.", "png"),
    "hybrid_sim.png": (
        "Hybrid Dynamic-Range Sweep",
        "Ideal / pure-digital / hybrid SINR vs jammer power — the novel result.", "png"),
}


def run_steps():
    produced = []
    for script, artifacts in STEPS:
        print(f"\n=== running {script} ===")
        r = subprocess.run([PY, script], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  [FAIL] {script} exited {r.returncode}")
            print(r.stderr[-1500:])
            continue
        # tail of stdout for a sign of life
        tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-3:]
        for ln in tail:
            print("  " + ln)
        for art in artifacts:
            if os.path.exists(os.path.join(ROOT, art)):
                produced.append(art)
            else:
                print(f"  [warn] expected artifact missing: {art}")
    return produced


def collect(produced):
    os.makedirs(OUT, exist_ok=True)
    for art in produced:
        shutil.copy2(os.path.join(ROOT, art), os.path.join(OUT, art))
    return [a for a in produced if a in META]


# the hero panels rendered big; everything else small
HERO = ["navguard_playground.html", "navguard_skyview.html", "navguard_imperfection_slider.html"]

HERO_CARD = """      <div class="card hero {kind}">
        <div class="card-head"><span class="tag {kind}">{tag}</span><h3>{title}</h3>
          <a class="open" href="{f}" target="_blank">open full ↗</a></div>
        <p>{blurb}</p>
        <iframe class="hero-frame" src="{f}" loading="lazy"></iframe>
      </div>"""

SMALL_HTML = """      <div class="scard html">
        <div class="card-head"><span class="tag html">INTERACTIVE</span><h4>{title}</h4></div>
        <iframe class="thumb-frame" src="{f}" loading="lazy" scrolling="no"></iframe>
        <a class="open" href="{f}" target="_blank">open interactive ↗</a>
      </div>"""

SMALL_PNG = """      <div class="scard png">
        <div class="card-head"><span class="tag png">FIGURE</span><h4>{title}</h4></div>
        <a href="{f}" target="_blank"><img src="{f}" loading="lazy"></a>
      </div>"""


ROAD = [
    ("01", "Simulate &amp; learn the algorithms", "next",
     "Getting MUSIC, MVDR and the hybrid idea working and properly understood in software. "
     "This is where we are right now — <b>this page.</b>"),
    ("02", "Write a clean C version", "next",
     "Rewrite the working simulation as tidy fixed-point C that an FPGA can actually run, with "
     "test vectors so we can check it still matches the Python."),
    ("03", "Put it on an FPGA", "plan",
     "Run it on a Zynq board — the heavy covariance maths in the FPGA fabric, MUSIC and MVDR on "
     "the ARM cores, and the computed weights sent out to the RF parts."),
    ("04", "Small drone-mounted prototype", "plan",
     "A little board with four patch antennas, under about 8 W, that outputs clean GPS plus some "
     "telemetry about where the jammers are."),
]
KPIS = [
    ("3 nulls", "50–64 dB", "jammers suppressed (in simulation)"),
    ("0.02°", "DoA accuracy", "jammer bearing, strong-signal"),
    ("0 dB", "GPS passband", "satellite signal kept at full strength"),
    ("+13 dB", "extra jam range", "hybrid vs pure-digital, in sim"),
    ("+31.6 dB", "SINR @ 30 dB J/S", "hybrid vs digital, at design point"),
    ("&le;8 W", "power target", "for the planned drone module"),
]

# signal at every step — how I understand the chain
SIGNAL_STEPS = [
    ("1", "All four antennas hear everything",
     "Each of the four little antennas picks up the same mix of very weak GPS and very loud jammers. "
     "The useful clue is that a signal coming from one direction reaches the four antennas at slightly "
     "different moments — and that tiny timing difference is basically the signal's direction fingerprint."),
    ("2", "Amplify gently (one LNA per antenna)",
     "GPS is unbelievably weak — about 10⁻¹⁶ watts, actually below the background noise. So each antenna "
     "gets its own amplifier straight away that boosts the signal without adding much noise of its own."),
    ("3", "Keep only the GPS band (SAW filter)",
     "A sharp filter passes only the GPS L1 band around 1575 MHz and throws the rest away, so nearby "
     "signals can't swamp the electronics."),
    ("4", "Give each channel a 'weight' (vector modulator)",
     "Each channel gets multiplied by a weight — think of it as a volume knob plus a phase-shift knob. "
     "Choosing the four weights cleverly is really the heart of the whole thing."),
    ("5", "Add the four together (Wilkinson combiner)",
     "All four weighted signals are summed. If the weights are right, the jammer copies line up out of "
     "phase and <b>cancel out</b> (that's the 'null'), while GPS adds up. The jamming actually gets "
     "removed here, in the analog stage, before anything is digitized."),
    ("6", "Digitize and work out the weights (FPGA)",
     "A tap digitizes the raw signals so the FPGA can run <b>MUSIC</b> to find where the jammers are and "
     "<b>MVDR</b> to compute the best weights — then it sets those knobs, with a little feedback loop to "
     "keep the null sharp."),
    ("7", "Clean GPS comes out",
     "What comes out the other end is ordinary GPS again, so a normal receiver locks on and finds "
     "position like nothing happened."),
]

# the math, plain-but-technical
MATH_ROWS = [
    ("a(θ) — steering vector",
     "This is that 'direction fingerprint' written as numbers — the pattern of phases a signal from "
     "direction θ makes across the four antennas. It's how we turn a direction into something the maths "
     "can work with."),
    ("R = (1/N) · X·Xᴴ — covariance",
     "A little 4×4 summary of how the four antenna signals relate to each other over N samples. "
     "Because jammers are strong, they leave obvious patterns in it."),
    ("P(θ) = 1 / ‖Uₙᴴ·a(θ)‖² — MUSIC",
     "We sweep through every possible direction θ, and this formula shoots up wherever there's actually "
     "a jammer. That's how the directions get found."),
    ("w = R⁻¹a&#8347; / (a&#8347;ᴴR⁻¹a&#8347;) — MVDR",
     "Solve for the weights that make the leftover output power as small as possible <i>while keeping "
     "GPS at full strength</i>. Making the power small is exactly what forces the nulls onto the jammers."),
    ("null = 20·log₁₀|wᴴa<sub>j</sub>| — null depth",
     "Just a number for how deep the blind-spot is toward a jammer (in dB). A bigger negative number "
     "means the jammer is more thoroughly blocked."),
]

# hardware / components
HW_ROWS = [
    ("RF front end ×4", "antenna · SAW · LNA · coupler", "Each channel's analog chain — see the four rows below."),
    ("· Antenna ×4", "RHCP patch array", "Catch the GPS + jammer signals; spaced a half-wavelength apart."),
    ("· Filter ×4", "SAW band-pass", "Keep only the GPS L1 band; reject out-of-band interference."),
    ("· LNA ×4", "Qorvo QPL9547", "Amplify the faint signal with minimal added noise."),
    ("· Directional coupler ×4", "RF sensing tap", "Split off a copy of each channel for the FPGA to analyse, without disturbing the main path."),
    ("Vector modulator ×4", "Analog Devices AD8341", "Apply the gain + phase weight to each channel (the analog nulling)."),
    ("Combiner", "Wilkinson 4-way", "Sum the channels — the jammers cancel here."),
    ("Down-converter + ADC", "NT1065 / AD9361 class", "RF front end for the digital side: mix GPS L1 down and digitize all four channels for the FPGA."),
    ("FPGA / SoC", "Xilinx Zynq-7020 class", "Run MUSIC + MVDR + the control/trim loop."),
    ("DAC", "Analog Devices AD5676", "Convert the computed weights to control voltages for the modulators."),
    ("Power detector", "Analog Devices AD8314", "Measure leftover jammer power to fine-tune the null."),
    ("Reference clock", "Shared TCXO", "Keep all four channels phase-synchronised."),
    ("GPS receiver", "u-blox M-series", "Compute position from the cleaned signal."),
]


def build_index(items):
    heroes = [f for f in HERO if f in items]
    rest   = [f for f in items if f not in heroes]
    rest   = [f for f in rest if META[f][2] == "html"] + \
             [f for f in rest if META[f][2] == "png"]
    hero_cards = [HERO_CARD.format(kind="html", tag="INTERACTIVE",
                                   title=META[f][0], blurb=META[f][1], f=f) for f in heroes]
    small_cards = []
    for f in rest:
        title, blurb, kind = META[f]
        tmpl = SMALL_HTML if kind == "html" else SMALL_PNG
        small_cards.append(tmpl.format(title=title, f=f))

    road = "".join(
        f'<div class="step {st}"><div class="num">{n}</div><div class="sbody">'
        f'<h4>{ttl}{" ✓" if st=="done" else ""}</h4><p>{desc}</p></div></div>'
        for n, ttl, st, desc in ROAD)
    kpis = "".join(
        f'<div class="kpi"><div class="kn">{n}</div><div class="kl">{lab}</div>'
        f'<div class="kd">{d}</div></div>' for n, lab, d in KPIS)
    diagram = ('<img src="navguard_p1_block_diagram.png" alt="NAVGUARD architecture">'
               if os.path.exists(os.path.join(OUT, "navguard_p1_block_diagram.png")) else "")
    if diagram:
        diagram_section = (
            '<section><h2>How the parts would fit together</h2><div class="diagram">' + diagram +
            '<p class="cap">The signal chain we have in mind: four antennas → amplifiers → the vector '
            'modulators that do the analog nulling → combiner → GPS receiver, with a sensing tap '
            'feeding the FPGA that runs MUSIC and MVDR and sets the weights.</p></div></section>')
    else:
        diagram_section = ""

    steps = "".join(
        f'<div class="srow"><div class="snum">{n}</div><div><h4>{ttl}</h4>'
        f'<p>{desc}</p></div></div>' for n, ttl, desc in SIGNAL_STEPS)
    math = "".join(
        f'<div class="mrow"><code>{eq}</code><p>{desc}</p></div>' for eq, desc in MATH_ROWS)
    hw = "".join(
        f'<tr><td class="hb">{b}</td><td class="hp">{p}</td><td>{d}</td></tr>'
        for b, p, d in HW_ROWS)

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NAVGUARD-4 — GPS Anti-Jamming CRPA · Project Proposal</title>
<style>
  :root {{ --bg:#0d1117; --card:#161b22; --line:#30363d; --txt:#e6edf3; --mut:#8b949e;
           --acc:#4da6ff; --grn:#28e07a; --warn:#ff9e2c; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--txt);
          font:15.5px/1.6 -apple-system,Segoe UI,Roboto,sans-serif; }}
  a {{ color:var(--acc); }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:0 24px; }}
  section {{ padding:38px 0; border-top:1px solid var(--line); }}
  h2 {{ font-size:13px; letter-spacing:1.2px; text-transform:uppercase; color:var(--mut);
        margin:0 0 22px; font-weight:700; }}
  /* hero */
  .hero {{ text-align:center; padding:64px 24px 48px;
           background:radial-gradient(900px 380px at 50% -10%, rgba(77,166,255,.16), transparent); }}
  .pill {{ display:inline-block; font-size:11.5px; font-weight:700; letter-spacing:.6px;
           color:var(--grn); background:rgba(40,224,122,.12); border:1px solid rgba(40,224,122,.35);
           padding:5px 12px; border-radius:20px; margin-bottom:20px; }}
  .hero h1 {{ font-size:58px; margin:0; letter-spacing:1px;
              background:linear-gradient(90deg,#fff,#9fd0ff); -webkit-background-clip:text;
              -webkit-text-fill-color:transparent; }}
  .hero .sub {{ font-size:21px; margin:6px 0 18px; color:#c9d4e0; font-weight:600; }}
  .hero .lede {{ max-width:760px; margin:0 auto 26px; color:var(--mut); font-size:16.5px; }}
  .cta {{ display:inline-block; background:var(--acc); color:#001; font-weight:700;
          padding:12px 22px; border-radius:9px; text-decoration:none; }}
  /* roadmap */
  .road {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; }}
  .step {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px; }}
  .step.done {{ border-color:rgba(40,224,122,.5); }}
  .step .num {{ font-size:13px; font-weight:800; color:var(--mut); }}
  .step.done .num {{ color:var(--grn); }}
  .step h4 {{ margin:8px 0 6px; font-size:16px; }}
  .step p {{ margin:0; color:var(--mut); font-size:13.5px; }}
  .step.next {{ border-color:rgba(77,166,255,.4); }}
  /* kpis */
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:16px; }}
  .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px;
          text-align:center; }}
  .kpi .kn {{ font-size:30px; font-weight:800; color:#fff; }}
  .kpi .kl {{ font-size:14px; font-weight:600; margin-top:2px; }}
  .kpi .kd {{ font-size:12.5px; color:var(--mut); margin-top:4px; }}
  /* two col */
  .two {{ display:grid; grid-template-columns:1fr 1fr; gap:26px; }}
  .two h3 {{ margin:0 0 8px; font-size:18px; }}
  .two p {{ margin:0; color:#c2ccd6; }}
  .diagram img {{ width:100%; border:1px solid var(--line); border-radius:12px; display:block; }}
  .cap {{ color:var(--mut); font-size:13px; margin-top:10px; }}
  /* signal steps / math / hardware */
  .steps {{ display:flex; flex-direction:column; gap:12px; }}
  .srow {{ display:flex; gap:14px; background:var(--card); border:1px solid var(--line);
           border-radius:10px; padding:14px 16px; }}
  .snum {{ flex:0 0 34px; height:34px; border-radius:50%; background:rgba(77,166,255,.15);
           color:var(--acc); font-weight:800; display:flex; align-items:center; justify-content:center; }}
  .srow h4 {{ margin:1px 0 4px; font-size:15.5px; }}
  .srow p {{ margin:0; color:var(--mut); font-size:13.5px; }}
  .math {{ display:flex; flex-direction:column; gap:10px; }}
  .mrow {{ display:grid; grid-template-columns:minmax(210px,300px) 1fr; gap:18px;
           background:var(--card); border:1px solid var(--line); border-radius:10px; padding:13px 16px; }}
  .mrow code {{ color:#9fd0ff; font-size:14px; align-self:center; }}
  .mrow p {{ margin:0; color:var(--mut); font-size:13.5px; align-self:center; }}
  .hwtable {{ width:100%; border-collapse:collapse; }}
  .hwtable td {{ padding:10px 12px; border-bottom:1px solid var(--line); font-size:13.5px;
                 color:var(--mut); vertical-align:top; }}
  .hwtable .hb {{ color:var(--txt); font-weight:600; white-space:nowrap; }}
  .hwtable .hp {{ color:var(--acc); white-space:nowrap; }}
  /* demo cards (reused) */
  .featured {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(540px,1fr)); gap:22px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:16px;
           margin-top:18px; }}
  .card, .scard {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
           padding:16px; }}
  .scard {{ padding:12px; }}
  .card-head {{ display:flex; align-items:center; gap:10px; margin-bottom:6px; }}
  .card h3 {{ margin:0; font-size:18px; }} .scard h4 {{ margin:0; font-size:13.5px; }}
  .card p {{ margin:0 0 12px; color:var(--mut); font-size:13.5px; }}
  .tag {{ font-size:10px; font-weight:700; letter-spacing:.5px; padding:3px 7px; border-radius:5px;
          white-space:nowrap; }}
  .tag.html {{ background:rgba(77,166,255,.15); color:var(--acc); }}
  .tag.png {{ background:rgba(40,224,122,.15); color:var(--grn); }}
  .hero-frame {{ width:100%; height:720px; border:1px solid var(--line); border-radius:8px;
                 background:#000; }}
  .thumb-frame {{ width:100%; height:165px; border:1px solid var(--line); border-radius:6px;
                  background:#000; pointer-events:none; }}
  .scard img {{ width:100%; border:1px solid var(--line); border-radius:6px; display:block; }}
  a.open {{ margin-left:auto; color:var(--acc); text-decoration:none; font-weight:600;
            font-size:12.5px; }}
  .scard a.open {{ display:inline-block; margin-top:8px; }}
  footer {{ color:var(--mut); font-size:12.5px; padding:34px 0 60px; border-top:1px solid var(--line); }}
  @media (max-width:820px) {{ .road,.two,.mrow {{ grid-template-columns:1fr; }}
                              .hero h1 {{ font-size:42px; }} .featured {{ grid-template-columns:1fr; }} }}
</style></head><body>

<div class="hero">
  <div class="pill">TEAM RESEARCH PROJECT · SIMULATION</div>
  <h1>NAVGUARD-4</h1>
  <div class="sub">A research simulation of a GPS anti-jamming antenna</div>
  <p class="lede">We built this to understand how a small four-antenna array can spot GPS jammers and
  steer "nulls" to block them while still hearing the satellites. Everything here is a software
  simulation — our aim was to nail down the signal processing (MUSIC and MVDR) and work out a
  realistic path to building it on an FPGA. The demos below are interactive, so you can explore it
  the way we did.</p>
  <a class="cta" href="#demos">↓ Try the interactive demos</a>
</div>

<div class="wrap">

  <section>
    <h2>Why we built this</h2>
    <div class="two">
      <div><h3>The problem</h3><p>GPS turns out to be surprisingly easy to jam. A cheap transmitter
      even ~30 dB louder than the satellite signal can knock out navigation across a wide area — which
      is exactly what electronic-warfare systems do to drones. We wanted to understand why a single
      antenna can't fix this; basically, it just can't tell the jammer apart from the real signal.</p></div>
      <div><h3>The idea</h3><p>The approach we explored is using four antennas together as an array. By
      comparing the four signals, an algorithm called <b>MUSIC</b> can work out which direction each
      jammer comes from, and a second one called <b>MVDR</b> finds weights that make a blind spot toward
      each jammer while still listening to the GPS overhead. We also tried a hybrid analog+digital trick
      to cancel jammers before they overload the receiver.</p></div>
    </div>
  </section>

  <section>
    <h2>How it works — the signal at every step</h2>
    <div class="steps">{steps}</div>
  </section>

  <section>
    <h2>Two ways we watch the jammer — spatial vs spectral</h2>
    <div class="two">
      <div><h3>Spatial — <i>where</i> is it?</h3><p>Because there are four antennas, we can work out the
      <b>direction</b> each signal arrives from (that's MUSIC). Direction is what lets us steer a null
      and actually block the jammer, so spatial monitoring drives the defence — it answers
      <b>"where?"</b> You can see it in the 3D Sky-View, the Playground and the beam pattern.</p></div>
      <div><h3>Spectral — <i>what</i> is it?</h3><p>Tapping a channel and looking at its <b>frequency
      content</b> (an FFT) tells us the <i>kind</i> of jammer — a single tone (CW), a sweeping chirp
      (FMCW) or wideband noise (barrage) — and how much of the band it fills. Spectral monitoring is for
      identifying and reporting the threat, not for the nulling itself — it answers <b>"what?"</b> You
      can see it in the spectrum panel inside the demos. <b style="color:var(--warn)">Next step:</b> right
      now we only <i>show</i> the spectrum — automatically <i>classifying</i> the jammer type from it is
      planned, not built yet.</p></div>
    </div>
    <p class="cap" style="margin-top:14px">In short: <b>spatial removes the jammer; spectral identifies
    it.</b> A complete system does both — block the jammer by direction, and report what kind it was.</p>
  </section>

  {diagram_section}

  <section>
    <h2>The maths, in plain terms</h2>
    <div class="math">{math}</div>
  </section>

  <section>
    <h2>The hardware — parts and what each does</h2>
    <table class="hwtable"><tbody>{hw}</tbody></table>
  </section>

  <section>
    <h2>Where we'd take this next</h2>
    <div class="road">{road}</div>
  </section>

  <section>
    <h2>What the simulation shows so far</h2>
    <div class="kpis">{kpis}</div>
  </section>

  <section id="demos">
    <h2>Try it yourself — interactive demos</h2>
    <div class="featured">{os.linesep.join(hero_cards)}</div>
    <h2 style="margin-top:30px">More views</h2>
    <div class="grid">{os.linesep.join(small_cards)}</div>
  </section>

  <footer>
    <b>NAVGUARD-4</b> — a team research project · 4-antenna GPS array · L1 1575.42 MHz.<br>
    Everything here comes from a software simulation using standard MUSIC and MVDR array processing
    (we cross-checked the maths two different ways). Nothing is built in hardware yet — the parts and
    the performance numbers (like ≥35 dB null, ≤8 W) are targets we're aiming for in a future FPGA build.
    The demos run entirely in your browser.
  </footer>

</div>
</body></html>"""
    path = os.path.join(OUT, "index.html")
    with open(path, "w") as fh:
        fh.write(html)
    return path


if __name__ == "__main__":
    produced = run_steps()
    produced += [f for f in STATIC_FILES if os.path.exists(os.path.join(ROOT, f))]
    items    = collect(produced)
    # copy the architecture block diagram in for the proposal page (not a gallery card)
    _bd = os.path.join(ROOT, "navguard_p1_block_diagram.png")
    if os.path.exists(_bd):
        os.makedirs(OUT, exist_ok=True)
        shutil.copy2(_bd, os.path.join(OUT, "navguard_p1_block_diagram.png"))
    index    = build_index(items)
    print(f"\n{'='*56}")
    print(f"  Built {len(items)} visualizations into ./viz/")
    print(f"  Gallery: {index}")
    print(f"{'='*56}")
    try:
        webbrowser.open("file://" + index)
    except Exception:
        pass
