# NAVGUARD-4 — GPS Anti-Jamming CRPA (Simulation)

A research simulation of a **4-element controlled-reception-pattern antenna (CRPA)** that detects GPS
jammers by **direction** and steers antenna **nulls** to block them, while keeping the GPS signal.
Pure Python on synthetic IQ data — no hardware yet (pre-hardware, TRL-3).

**Live interactive dashboard:** https://itsstoomuch.github.io/antiJAMsimulationV2/

- **Frequency:** GPS L1, 1575.42 MHz · **Array:** 2×2 (4 elements), half-wavelength spacing
- **Algorithms:** MUSIC (direction finding) + MVDR (null steering) + a hybrid analog/digital stage

---

## Quick start

```bash
pip install numpy scipy matplotlib plotly      # dependencies
python run_all.py        # run the simulation: prints KPIs, saves figures
python build_viz.py      # run sim + build all interactive dashboards into viz/index.html
```

`run_all.py` is the simulation pipeline; `build_viz.py` additionally builds the browser dashboards.
Open `navguard_playground.html` directly in a browser for the interactive tool (no Python needed).

---

## How the simulation works (data flow)

```
generate_array_data.py ──> array_data.npy ──> music_spectrum.py   (find jammer directions)
                                          └──> mvdr_beamformer.py  (compute nulls -> mvdr_weights.npy)
hybrid_sim.py        (analog pre-cancel + ADC dynamic-range sweep, self-contained)
run_all.py           (orchestrates the above + an ideal-vs-realistic comparison)
```

---

## The code — simulation core

| File | What it does |
| :-- | :-- |
| `generate_array_data.py` | Generates synthetic 4-channel IQ data: array geometry, steering vectors, path loss, CW/FMCW/barrage jammers. `realistic=True` adds hardware imperfections (phase/gain mismatch, coupling, drift, ADC). Writes `array_data.npy`. |
| `music_spectrum.py` | **MUSIC** direction-of-arrival: covariance → eigendecomposition → noise subspace → azimuth pseudospectrum → jammer angles. |
| `mvdr_beamformer.py` | **MVDR** beamformer: solves for the complex weights that null the jammers while keeping GPS at unit gain. Saves `mvdr_weights.npy` + beampattern. |
| `hybrid_sim.py` | Sweeps jammer power and compares **ideal / pure-digital / hybrid** output SINR, showing the hybrid analog pre-canceller extends the ADC dynamic range. |
| `realistic_sim.py` | Runs the chain with hardware imperfections and compares **ideal vs realistic** DoA accuracy and null depth. |
| `dof_comparison.py` | Degrees-of-freedom study: 4-element vs 6-element arrays (how many jammers each can null). |
| `run_all.py` | Master pipeline — runs MUSIC + MVDR + hybrid, prints the KPI table, and produces `publication_figure.png` plus an ideal-vs-realistic comparison (STEP 7). |

## The code — visualization (interactive dashboards)

| File | Builds | What it shows |
| :-- | :-- | :-- |
| `build_viz.py` | `viz/index.html` | One command: runs the sim and assembles every figure + interactive panel into a single proposal-style gallery page. |
| `navguard_playground.html` | (self-contained) | Live in-browser tool: set jammer **count, direction, type, power**; the MVDR nulls + spectrum update in real time (math runs in JavaScript). |
| `gen_skyview.py` | `navguard_skyview.html` | 3D antenna radiation pattern (dents = nulls) with a 9-scenario (count × jammer-type) selector and a spectrum panel. |
| `gen_imperfection_slider.py` | `navguard_imperfection_slider.html` | Drag a channel-mismatch slider and watch the nulls collapse — the case for calibration. |
| `gen_hybrid_interactive.py` | `navguard_hybrid.html` | Slider over jammer power: pure-digital collapses as the ADC saturates while the hybrid holds. |
| `gen_subspace.py` | `navguard_subspace.html` | Why a 4-element array must keep GPS out of the jammer-finder (kept as reference; not in the gallery). |
| `gen_video.py` | `navguard_demo.mp4` | Short shareable clip: a jammer moves and the null tracks it. |
| `gen_arch_diagrams.py` | `arch1/2/3_diagram.png` | The three architecture block diagrams. |
| `make_block_diagram.py` | `navguard_p1_block_diagram.png` | The flight-prototype signal-chain block diagram. |

## Documentation

| File | Contents |
| :-- | :-- |
| `NAVGUARD_MathModelling_v2_CORRECTED.md` | Full mathematical model (array model, MUSIC, MVDR, hybrid, link budget) — the source of truth for the math. |
| `NAVGUARD_ARCHITECTURES.md` | The three candidate architectures (blind power-inversion, sensing-tap hybrid, closed-loop hybrid) with diagrams, math and limitations. |
| `arch1.md`, `arch3.md` | Individual architecture write-ups. |
| `ARCH_REVIEW_AND_HARDWARE.md` | Architecture comparison + hardware/BOM review + power tiers (T1/T2/T3). |
| `plan.md` | NAVGUARD-P1 prototype plan (L1-only, analog-nulling-first, drone-mounted). |
| `simplan.md` | `cogsim` plan — porting the simulation to fixed-point, FPGA-ready C. |
| `SIM_TO_PRODUCT.md` | **Gap list:** what the sim gets wrong/misses and how to fix it to become a real product (start here for next steps). |
| `hardware_selection_prompt.md` | Structured prompt for choosing the actual components. |
| `CLAUDE.md` | Project notes / current status. |

## Other

- `navguard_viz/` — a separate, partially-built web app (Flask backend + Three.js frontend); independent of the Plotly dashboards above.
- `array_data.npy`, `mvdr_weights.npy` — generated data artifacts.

---

## Status & honesty note

Everything here is a **software simulation** using standard MUSIC / MVDR array processing (the math is
cross-checked two ways). **No hardware exists yet**; the performance figures (e.g. ≥35 dB null, ≤8 W)
are design targets. See `SIM_TO_PRODUCT.md` for the honest list of what's idealized and the path to a
real CRPA product.
