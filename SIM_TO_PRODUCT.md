# NAVGUARD-4 — Simulation → Product Gap List

**What this is:** an honest, prioritized checklist of what the current simulation gets wrong or leaves
out, and how to fix each, to turn it into a real CRPA (controlled-reception-pattern antenna) product.
Status as of June 2026. Most fixes are software (doable in simulation now); see the cogsim plan
(`simplan.md`) and the corrected math (`NAVGUARD_MathModelling_v2_CORRECTED.md`).

---

## Phase A — Software fixes (in the simulation, no hardware needed)

| # | Problem | Why it matters | How to fix | Effort | Tracked in |
| :-- | :-- | :-- | :-- | :-- | :-- |
| **A1** | **No C/N₀ — wrong KPI.** The sim headlines *null depth*; it never checks whether GPS still acquires/tracks. | Null depth is meaningless if the receiver can't lock. C/N₀ is what a customer actually buys. | Add a GPS **C/A correlator**: generate the Gold code, spread GPS, despread at the combiner output, compute **C/N₀ before vs after** nulling. | Medium | math doc Bug E |
| **A2** | **Azimuth-only nulling.** Steering is azimuth-projected; it nulls in az but not elevation. | A real 2×2 CRPA must null in 2D. Jammers at the same azimuth/different elevation can't be separated. | Full **2D (az+el) steering + 2D MUSIC** scan. Keep GPS out of the source count (known direction from almanac+IMU) so it doesn't re-break MUSIC like the reverted 3D model. | Medium | new |
| **A3** | **Deep nulls are idealized.** Analytic covariance gives 50–79 dB. | Real R from finite snapshots + mismatch tops out ~26–36 dB (5–8 dB uncalibrated). Designing to 70 dB is a trap. | Make the **realistic covariance** path the headline; quote realistic numbers, not the analytic ideal. | Low | realistic_sim.py exists |
| **A4** | **Calibration + trim loop unbuilt** (the make-or-break). | The imperfection slider shows nulls collapsing to single digits from channel mismatch alone; the fix is unproven. | Implement **cal-tone gain/phase estimation** (§13.2) + **closed-loop trim** (power-detector dither around MVDR); re-run the imperfection sweep *with* cal+trim and show recovery. | High | cogsim P3 |
| **A5** | **Spectral = display only.** The spectrum panel shows the signature but doesn't classify. | Currently overstated if called "monitoring." | Add an **FFT feature classifier** that labels CW / FMCW / barrage from the spectrum. | Low–Med | next step (flagged on site) |
| **A6** | **No mutual coupling.** | At real λ/2 spacing, coupling shifts apparent directions and costs 5–15 dB of null. | Add coupling matrix **C** (X→C·X) from an EM sim of the patch layout; fold C into calibration. | Medium | math doc §9.4 |
| **A7** | **Narrowband vs wideband jammers.** One weight per element nulls one frequency. | FMCW/barrage are wideband; a single weight can't deep-null across the band. | **Subband / STAP**: split the band, MVDR weights per subband, beamform in frequency (or tapped-delay lines). | High | new |
| **A8** | **4 elements = 3 nulls, zero DOF margin.** | No headroom for 3+ jammers, wideband, multipath, or cal error. | Run `dof_comparison` for **4 vs 6 elements**; decide array size early (it's a board respin). | Low | dof_comparison.py exists |

**Recommended order:** A1 → A4 → A3 → A2 → A8 → A5 → A6 → A7.
A1 first: it converts the whole story from "we made deep nulls" to "GPS survives jamming."

## Phase B — Port to C → FPGA
Execute the **cogsim plan** (`simplan.md`): fixed-point C reference model (PS-float32 / PL-fixed) →
golden test vectors → Zynq-7020. Most Phase A fixes land *inside* the cogsim rewrite — fix and port
together.

## Phase C — Hardware
Bench brassboard → drone prototype → conducted / range anti-jam testing (T1/T2/T3 tiers in
`ARCH_REVIEW_AND_HARDWARE.md`). Anti-jam testing is legally conducted/range-only.

## Key insight
"Fix all" ≈ **execute the cogsim plan + add A1 (correlator), A2 (2D), A5 (classifier), A7 (wideband).**
The math for most of it is already derived in `NAVGUARD_MathModelling_v2_CORRECTED.md` — this is
implementation, not research.

---
*NAVGUARD-4 · gap list for taking the simulation to a fielded CRPA product · June 2026*
