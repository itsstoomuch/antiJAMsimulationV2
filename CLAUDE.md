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
3. mvdr_weights.py — MVDR null steering beamformer
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


## Current Status — MUSIC Fix In Progress

PROBLEM IDENTIFIED:
- 4 element array cannot resolve 4 sources (3 jammers + GPS)
- Maximum sources = N-1 = 3 for 4 element array
- Signal amplitudes too small (1e-4) causing numerical issues
- Covariance matrix needs regularisation

FIXES NEEDED IN music_spectrum.py:
1. Reduce to 2 jammers in generate_array_data.py (keep jammer1 
   at [500,300,0] and jammer2 at [-800,200,0], remove jammer3)
2. Normalise array data before MUSIC: X_norm = X / max(abs(X))
3. Add diagonal loading: R = R + 1e-6 * eye(4)
4. n_signals = 3 (GPS + 2 jammers)
5. Scan -180 to +180 degrees full azimuth

EXPECTED RESULT AFTER FIX:
- Jammer 1 found near +30.96°
- Jammer 2 found near +165.96°
- GPS found near 0°
- 3 large eigenvalues visible in bar chart

FILES COMPLETED:
- generate_array_data.py — realistic geometry, 2x2 URA, 
  path loss, cosine pattern, CW/FMCW/Barrage jammer types
- music_spectrum.py — needs fix above
- mvdr_beamformer.py — done
- hybrid_sim.py — done  
- run_all.py — done

GITHUB: git@github.com:itsstoomuch/antiJAMsimulationV2.git