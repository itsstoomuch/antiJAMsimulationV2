# antiJAMsimulation Project Memory

## What this project is
Python simulation of a hybrid analog-digital GPS anti-jamming system.
4-element antenna array. Pure math on synthetic IQ data. No hardware yet.

## Stack
- Python 3
- NumPy (math)
- Matplotlib (plots)
- SciPy (eigenvalue decomposition for MUSIC)

## Physical parameters
- GPS L1 frequency: 1575.42 MHz
- Antenna spacing: half-wavelength = 9.5 cm
- Number of antennas: 4 elements
- Jammer angle: 45 degrees
- Jammer power: 30 dB above GPS
- IQ samples per channel: 1000

## The 4 simulations to build
1. generate_array_data.py — 4-channel synthetic IQ generator
2. music_spectrum.py — MUSIC algorithm angle estimation
3. mvdr_beamformer.py — MVDR null steering beamformer
4. hybrid_sim.py — hybrid analog pre-cancel + digital MVDR
5. run_all.py — master script, calls all four, generates all plots

## Novel contribution
Hybrid analog-digital beamformer. Vector modulator does coarse
analog cancellation before ADC. Extends dynamic range compared
to pure digital MVDR. Key result: SNR vs jammer power curve
showing hybrid stays higher longer before degrading.

## Style rules
- One function per file
- Every function has a clear docstring
- All plots publication quality
- Comments explain the physics not just the code


## Current Status — Shipped Design (azimuth-projected, all KPIs pass)

DESIGN AS BUILT:
- 3 simultaneous CW jammers — J1 +30.96°, J2 +165.96°, J3 −71.57° azimuth —
  from real 3D coordinates in generate_array_data.py.
- GPS satellite at zenith (el ≈ 90°). The horizon-boresight element pattern
  (cos(el) power) nulls the zenith GPS to ~zero amplitude, so the array data is
  effectively 3 jammers only — which a 4-element array CAN resolve.
- Steering model: AZIMUTH-PROJECTED phase (horizontal-plane unit vector);
  elevation enters only through the element-pattern amplitude gain. MUSIC scans
  azimuth at el = 0° (1-D) → clean rank-3 signal subspace, 1-D noise subspace.
- MVDR look direction constrained at az = 0° (GPS), 3 simultaneous nulls.

KPIs (python run_all.py): DoA error < 0.1°, nulls > 40 dB on all 3 jammers,
GPS passband gain ≈ 0 dB, hybrid extended range > 10 dB — ALL PASS.

REALISTIC MODE:
- generate_array_data(realistic=True) applies hardware imperfections (per-element
  phase/gain mismatch, mutual coupling, LNA noise figure, cable loss, oscillator
  phase drift, 14-bit ADC quantization; 256 snapshots).
- run_all.py STEP 7 runs an ideal-vs-realistic comparison (realistic_comparison.png
  + console table); realistic shows degraded-but-finite DoA/nulls.

DOCUMENTED LIMIT:
- A 4-element URA reliably resolves at most N−1 = 3 sources. A true-3D-phase
  steering model (keeping GPS at zenith as a 4th source) was tried and REVERTED:
  it leaves only a 1-D noise subspace for 3 jammers + GPS, collapsing MUSIC
  selectivity (a spurious az≈+53° ridge competes with the true J1 peak). The
  azimuth-projected model + horizon element pattern is the validated design.

FILES:
- generate_array_data.py — 2×2 URA geometry, path loss, horizon (cos el) element
  pattern, azimuth-projected steering, CW/FMCW/Barrage jammers, realistic=True
  hardware-imperfection mode, n_jammers param (1–3).
- music_spectrum.py — MUSIC DoA, el=0 azimuth scan, n_signals=3.
- mvdr_beamformer.py — MVDR null steering, az=0 GPS constraint.
- hybrid_sim.py — analog pre-cancel + digital MVDR dynamic-range sweep.
- run_all.py — master pipeline + STEP 7 ideal-vs-realistic comparison.

GITHUB: git@github.com:itsstoomuch/antiJAMsimulationV2.git