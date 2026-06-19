# CHECKPOINT — Real-World Upgrade (2026-06-10)

## Context
Full math-modeling review completed. Goal: fix bugs and convert the game-like
sim into a physically honest pipeline ("real product").

## Review findings (verified numerically)
1. **Element pattern pointed sideways** — `cos(el)` peaked at horizon, gain ≈ 0
   at zenith → GPS satellite (el=90°) had amplitude 4e-17, i.e. **156 dB below
   noise — GPS was completely absent from array_data.npy**.
2. **GPS direction inconsistent across files** — generator: el=90°;
   mvdr_beamformer + hybrid_sim: el=0° (constraint pointed 90° away).
3. **FMCW bug in realistic_sim.py** — `cumsum(freq)/n_snapshots` divided sweep
   rate by 1000 → chirp was effectively a DC tone.
4. **"CW" jammers aren't CW** — BPSK chips at full 10 MHz sample rate; sidesteps
   the real coherent-source problem (MUSIC needs FB averaging/spatial smoothing).
5. **Null depth in realistic_sim measured at IDEAL steering vectors** while data
   manifold is perturbed → "PASS >40dB" measures the wrong direction.
6. **hybrid_sim SINR is analytic** (unclipped steering vectors) — ignores
   clipping intermod, the dominant error in the claimed regime.
7. **hybrid_sim canceller uses ground-truth jammer vectors** — 13 dB extended
   range result is circular.
8. **Noise floor fantasy** — noise set 6 dB below GPS; physically GPS is ~25-30 dB
   BELOW kTB noise pre-correlation (kTB in 10 MHz ≈ -134 dBW, GPS ≈ -158.5 dBW).
9. **Actual J/S in generator is ~84 dB**, not 30 dB as documented.
10. **Fixed ADC clip (FS=5×GPS), no AGC** — "digital fails at X dB" decided by an
    arbitrary constant; real story is quantization-noise rise after AGC.
11. Multipath model is scalar AM on all channels — not real multipath.
12. Minor: c=3e8, GPS EIRP 50 W (should be ~500 W), realistic_sim unseeded RNG.

## Fixes COMPLETED ✅
- `generate_array_data.py`:
  - `element_pattern()` → boresight-up: `G_power = max(sin(el), 0.01)`
    (-20 dB backlobe floor for below-horizon jammers).
  - `steering_vector()` → true 3D phase `(2π/λ)(elem_pos·û)` (zenith source →
    zero inter-element phase). Removed azimuth-projection hack.
- `realistic_sim.py`: FMCW phase fixed → `2π·cumsum(freq_sweep)` (no /N).
- `mvdr_beamformer.py`:
  - Added `el_gps=90.0` param; steering_vector now takes (az, el) full 3D.
  - GPS constraint at zenith; added `JAMMER_ELEVS = [-9.73, -6.93, -4.53]`;
    null depths evaluated at true jammer elevations.
  - Plot annotation uses precomputed null_depths; legend shows az+el.
  - VERIFIED: runs, nulls 66-86 dB, constraint 0 dB at zenith.
- `music_spectrum.py` (IN PROGRESS — edit applied, NOT yet re-run):
  - Replaced 1D el=0° scan with 2D az×el scan (el grid -20°..+20°, 1° step),
    max-projection over elevation; `steering_matrix_ura(az_array, el)` vectorized.
  - Reason: with true 3D phase, 1D scan broke (J2 err -5.7°, J3 lost → 53.65°).
  - TODO: re-run music_spectrum.py to verify peaks recover; peak_el computed
    but not yet printed/used in output table.

## NOT YET STARTED — new real-physics pipeline (agreed plan)
Files to create:
1. `gps_ca_code.py` — C/A Gold code generator (G1/G2 LFSR, PRN tap table).
2. `real_scene.py` — physics-true IQ: GPS with C/A code BELOW kTB·NF noise floor
   (pre-corr SNR ≈ -27.5 dB at fs=10 MHz, C/N0 ≈ 42.5 dBHz), truly coherent
   CW/FMCW/barrage jammers (CW with small independent osc offsets), real link
   budget (J/S at port, sweep 30-80 dB), calibration errors (phase/gain),
   optional coherent multipath ray, GPS at realistic az/el (e.g. 45°, 60°).
3. `real_frontend.py` — AGC (RMS→FS/4) + n-bit quantizer (default 8-12 bit);
   analog pre-canceller driven by ESTIMATED DOAs with 6-bit quantized
   vector-modulator weights, applied pre-ADC.
4. `real_doa.py` — 2D MUSIC with forward-backward averaging (2×2 URA is
   centro-symmetric; FB valid), jammers only (GPS undetectable pre-corr).
5. `real_beamformer.py` — MVDR (GPS dir from geometry + attitude-error param)
   + power-inversion baseline (w = R⁻¹e₁/(e₁ᴴR⁻¹e₁)).
6. `real_cn0.py` — post-correlation C/N₀ estimator (1 ms coherent epochs,
   peak vs off-phase noise floor) — THE product KPI.
7. `run_real_product.py` — end-to-end: sweep J/S, 4 paths (unprotected /
   power-inversion / MVDR / hybrid), Monte Carlo over seeds, KPI table +
   C/N₀-vs-J/S figure (replaces old SINR plot).

Sanity targets: unjammed C/N₀ ≈ 42.5 dBHz; 1 ms coherent SNR ≈ +12.5 dB;
at J/S 80 dB unprotected C/N₀ collapses, MVDR should recover to ~40 dBHz;
8-bit ADC shows hybrid advantage via quantization-noise mechanism.

## Decisions made
- Legacy hybrid_sim.py left untouched (self-consistent toy; superseded by new
  pipeline). realistic_sim null-depth metric fixed properly in new pipeline only.
- Work in noise-normalized units (noise power = 1 per channel).
- CLAUDE.md "Current Status" section is stale — update after new pipeline lands.

## Resume point
First step on resume: run `MPLBACKEND=Agg python3 music_spectrum.py` and verify
all 3 jammer peaks recover (expect ≈ +30.96°, +165.96°, −71.57°). Then start
the new pipeline files. Nothing committed to git yet.
