# Plan: `cogsim` — C-Portable Arch-3 Simulation for FPGA Deployment

## Context

The existing sim suite (generate_array_data.py, music_spectrum.py, mvdr_beamformer.py, hybrid_sim.py, realistic_sim.py, dof_comparison.py) validated the math but **cannot model Architecture 3** (COGNAV-P1, per COGNAV_ARCHITECTURES.md / plan.md) and **cannot be ported to C/FPGA**. Audit findings (gap):

| Gap | Detail |
| :-- | :-- |
| No Arch-3 loop | No power detector model, no dither/trim loop, no cal tone, no VM model, no DAC/weight quantization — the entire AIM→TRIM→SUPERVISE machinery is absent |
| Wrong pre-cancel model | hybrid_sim.py uses ideal spatial projection with TRUE jammer steering vectors (math doc Bug D) — not per-element VM weighting |
| Physics bugs live | 3 inconsistent steering models (sin vs cos element pattern, ± j conventions); **hybrid_sim.py puts GPS at el=0° while the data has it at el=90°** (Bug B); 4 different diagonal-loading formulas; SINR computed analytically from weights, not from waveforms (Bug C); N=256 vs 1000 confound |
| Not portable | float64/complex128 everywhere, np.linalg.eigh/solve/inv in the core, plotting mixed with computation, .npy file handoffs, global state |

**Goal:** a fresh package `cogsim/` that simulates Arch 3 end-to-end with a clean split between *plant* (testbench, Python-only, never ported) and *core* (the DSP that ships — written to mirror C 1:1, with golden test vectors for later C/FPGA verification).

**User decisions (locked):** ① PS-float32 + PL-fixed split (matches Zynq-7020: fixed-point only for fabric kernels, float32 C99 for ARM kernels). ② Fresh package alongside legacy (legacy frozen as reference). ③ **Arch 3 scope only** — PI fallback stubbed as a mode flag, no C/A correlator in this effort (SINR measured at combiner; Bug E stays a documented follow-on).

## Package structure

```
cogsim/
  config.py            # single source of truth: physical constants, scenario dataclasses,
                       # Q-format table, loop rates. NO other file defines constants.
  geometry.py          # THE one steering model: +j convention, a_y ⊗ a_x, element order
                       # (0,0),(1,0),(0,1),(1,1), g = sin(el), d = 0.0951468 m
                       # (math doc §2.2/§2.3 — fixes Bugs A/B and the 3-model inconsistency)
  scene.py             # stimulus: GPS at el=90°, jammers CW/FMCW/barrage from xyz geometry,
                       # path-loss amplitudes, thermal noise. Reuse waveform recipes from
                       # generate_array_data.py (CW/FMCW/barrage generators) — port, don't rewrite.
  plant/               # the analog world (testbench only — never ported)
    rf_chain.py        # per-channel limiter/SAW/LNA gain+NF, −10 dB coupler split,
                       # AD8341 VM model (gain = f(I,Q) with compression + band-edge phase
                       # error term + control-voltage quantization from 16-bit AD5676),
                       # Wilkinson sum, post-LNA
    imperfections.py   # per-channel static phase/gain mismatch, shared vs independent drift,
                       # mutual coupling matrix (port the models from realistic_sim.py /
                       # generate_array_data.py — they are good; just unify conventions)
    adc.py             # sense ADC: envelope clip + 12-bit quantize (one function, one truth)
    detector.py        # AD8314 log-detector: P_dB → V transfer + noise + slow ADC sampling
  core/                # THE PORTABLE PART — mirrors future C file-for-file
    fxp.py             # fixed-point helpers: saturating add/mul, Q-format casts, int64 accum
    cov_accum.py       # [PL kernel, FIXED-POINT] streaming 4×4 Hermitian covariance:
                       # 12-bit IQ in → int64 accumulators → Q-scaled 4×4 out (N=256)
    cal_corr.py        # [PL kernel, FIXED-POINT] cal-tone correlator → per-channel ĥ_m;
                       # q_m = ĥ_m/ĥ_0 correction (math doc §13.2)
    evd4.py            # [PS kernel, float32] 4×4 Hermitian cyclic Jacobi — hand-coded,
                       # fixed sweep count, NO np.linalg
    music4.py          # [PS, float32] grid scan over precomputed steering ROM table
                       # (table generated offline by geometry.py → const array, as it will
                       # live in C), projection ‖U_nᴴa‖², simple ordered peak pick
    mvdr4.py           # [PS, float32] δ = 10·σ̂² loading (σ̂² = mean of noise eigenvalues —
                       # ONE formula, math doc §3.3) + 4×4 Cholesky solve — hand-coded
    weights.py         # [PS, float32] apply cal q_m, constraint projection wᴴa_s=1,
                       # map w → AD5676 I/Q codes (the realized weight ≠ requested weight)
    trim.py            # [PS, float32] dither FSM: perturb one DAC code axis, read detector,
                       # SPSA/coordinate step, constraint re-projection, quasi-static gate.
                       # PI-fallback = same kernel with w₀=1 constraint — STUB (flagged, untested)
    controller.py      # [PS, float32] AIM→TRIM→SUPERVISE state machine, event triggers
                       # (detector jump, DOA motion >0.5°, recal), epoch timing model
  vectors/
    export.py          # per-kernel golden vectors: input/output arrays → .npz + flat .bin
                       # (int16/int32/float32 little-endian) + README of formats — these are
                       # the C unit-test fixtures
  harness.py           # end-to-end Arch-3 run: scene → plant → core loop → metrics
                       # (delivered null depth from WAVEFORM power at combiner — fixes Bug C —
                       # trim gain vs open-loop, re-null epochs, weight traces)
  plots.py             # ALL plotting isolated here; nothing in core/plant imports matplotlib
  tests/               # pytest: kernel unit tests + physics invariants (see Verification)
```

## C-port rules for `core/` (enforced from day one)

1. Fixed-size arrays only (M=4 hardcoded); no dynamic allocation, no list comprehensions in kernels — plain indexed loops that transliterate to C.
2. No numpy linalg/fft anywhere in `core/`; numpy used only as array storage.
3. Every kernel = pure function, explicit input/output dataclasses (→ C structs); no globals.
4. float32 kernels: cast inputs to np.float32 at the boundary and keep all intermediates float32, so Python results bit-match C float to ULP-level.
5. Fixed-point kernels: integer dtypes only inside; documented Q formats — 12-bit ADC Q1.11, products int32, covariance accumulators int64 (24-bit product + 8-bit growth @ N=256), output covariance Q-scaled to int32 with documented shift.
6. Each kernel ships with exported golden vectors + a comment block giving its future C signature.

## Implementation phases

- **P0 — scaffold + geometry:** config.py, geometry.py with unit tests proving math-doc identities (Kronecker order vs element order; g=sin(el); known DOA phase values). Gate: tests pass.
- **P1 — scene + plant:** port waveform generators and imperfection models from legacy (cite source functions), add the NEW models (AD8341 VM with control quantization + compression, AD8314 detector, envelope-clip ADC). Gate: open-loop scene through plant reproduces legacy MUSIC DOA accuracy (sanity anchor vs music_spectrum.py results, ~0.02° on strong jammers).
- **P2 — core float32 kernels:** evd4 (Jacobi vs scipy.eigh reference <1e-4 rel), music4, mvdr4, weights. Gate: open-loop delivered null through the VM plant agrees with the **§6.2 closed-form prediction C ≈ −10·log₁₀(ε_A²+ε_φ²) evaluated at the plant's actual injected error magnitudes** (self-consistent anchor). The legacy "26–36 dB" figure is order-of-magnitude sanity only — it was partly derived with the old buggy geometry. If corrected geometry shifts the numbers, **COGNAV_ARCHITECTURES.md gets updated to match cogsim, never the reverse.**
- **P3 — trim loop (the headline):** trim.py + controller.py; harness measures delivered null open-loop vs trimmed on identical scenes — plan.md task S-1. **Run as a sweep, not a one-shot:** trim gain vs imperfection magnitude (cal residue, VM nonlinearity, drift level) and null-depth-vs-time under a simulated temperature/drift ramp. A static, perfectly-calibrated scene would show ~0 dB trim gain by construction and prove nothing. Gate: trim gain quantified across the sweep (report honestly), re-null epoch count < 100 ms equivalent. **Contingency if static gain < +5 dB:** the drift-ramp result becomes the headline — trimmed null holds while open-loop decays (drift-immunity / self-verification narrative), and plan.md §4's claims get re-worded accordingly before any datasheet use.

  **P3 runs in two ordered sub-phases to kill a circularity (review flag):** the quasi-static pacing is defined relative to the trim step size, so the step size must be frozen *before* the ramp rate is derived from it — otherwise tuning the step silently retunes the pass criteria.
  - **P3a (static, tunes and freezes the loop):** dither amplitude Δ and step µ are chosen against *static* criteria only — Δ from detector noise (gradient SNR ≥ 10 dB at the target null depth) and the dither floor formula null_floor ≈ 20·log₁₀(Δ·|∂(wᴴa_j)/∂w|) (≤ −40 dB class); µ from standard SPSA stability relative to Δ. The chosen (Δ, µ) are then **frozen into config.py as constants** and recorded in the report.
  - **P3b (ramp, frozen loop):** ramp rate is *derived from* the frozen step size via the ≤ 1/10 rule. **Independent variable: the frozen (Δ, µ). Downstream: the ramp rate.** No loop parameter may change between P3a and P3b.

  **Drift-ramp pass criteria (fixed now, before any data exists):**
  - *Ramp definition:* 12° RMS differential phase + 5% gain drift per channel, applied linearly over the ramp (representative of −10→+50 °C on the analog chain; consistent with §9.1's σ=5° static class). Quasi-static pacing: drift accrued per trim update ≤ 1/10 of one trim correction step — this also makes the arch doc's "quasi-static residual" assumption quantitative.
  - *Sanity (plant check):* open-loop null at ramp end within ±3 dB of the §6.2 prediction for the ramp's final error (ε_φ=0.21 rad, ε_A=0.05 → C ≈ 13 dB) — same self-consistent anchoring as the P2 gate.
  - **Pass 1 (hold):** trimmed null sags ≤ 3 dB from its pre-ramp value over the full ramp.
  - **Pass 2 (divergence):** trimmed − open-loop ≥ 15 dB at ramp end.
  - Both must hold for the drift-immunity narrative to be claimable; if either fails, that is a genuine negative result for the trim loop and goes in the report as such — no third narrative gets invented post hoc.

  **Standalone deliverable from P3 (independent of which headline wins):** the quantitative quasi-static limit. From the frozen (Δ, µ) and the trim update rate, compute the maximum tolerable residual-error slew, and map it through §5.8 to a **maximum jammer angular rate (deg/s) before the trim loop stops helping**. This converts COGNAV_ARCHITECTURES.md's qualitative "trim needs a quasi-static residual" limitation into a datasheet operating-conditions number — report it explicitly and back-fill it into the arch doc's Arch 3 limitations.
- **P4 — fixed-point PL kernels + vectors:** cov_accum + cal_corr in integers; float-vs-fixed delta budget (null depth change < 0.5 dB); export all golden vector sets; write the C signature header doc. Gate: fixed-point harness run within budget of float run.

## Verification

- `pytest cogsim/tests/` — kernel unit tests vs closed forms from COGNAV_MathModelling_v2_CORRECTED.md: MVDR optimality (§5.3–5.4), null-vs-Δθ −20 dB/decade (§5.8), noise factor α(2−α) (§6.5), cal identity recovery of injected mismatch (§13.2), Jacobi vs scipy on random Hermitian PSD matrices.
- End-to-end: `python -m cogsim.harness` prints the acceptance table — delivered null (1/2/3 jammers) open-loop vs trimmed, trim gain, epochs-to-renull, float-vs-fixed deltas. Compare anchors against legacy run_all.py results where overlapping (DOA accuracy, ideal null depths).
- Golden vectors: `python -m cogsim.vectors.export` regenerates fixtures; a checksum manifest catches accidental kernel drift.

## Schedule note (review feedback, June 2026)

NT1065 procurement and the AD8341 band-edge bench test do **not** wait on cogsim — they run in parallel from day one (the sensing-front-end choice is independent of the trim result). The only hard serial dependency is **cogsim P3 (S-1 result) → PCB tape-out decision**. P0–P2 are mostly porting validated code; schedule and technical risk both concentrate in P3, deliberately.

## Out of scope (documented follow-ons)

C/A correlator + C/N₀ KPI (Bug E), Arch 1/2 dedicated comparison harness (PI fallback left as stub), the actual C code itself, blade-flash gating, mutual-coupling calibration extension.
