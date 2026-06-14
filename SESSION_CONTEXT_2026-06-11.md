# SESSION CONTEXT — 2026-06-11 (Fable review session)

> Digest of the full working session. Read this first to recover context: what was reviewed, what was corrected, what was decided, and where every artifact lives. Chronological order.

---

## 1. Math model review → COGNAV_MathModelling_v2_CORRECTED.md (v2.1)

Reviewed `COGNAV_MathModelling.md` (draft 1.0), found and fixed these errors (full list in the v2 doc's Section 0):

- **E10 (worst):** §10.3 "post-correlation C/N₀ = −54.7 dBHz" was wrong in arithmetic and concept. Correct: **C/N₀ = 45.3 dB-Hz** nominal; processing gain does not enter C/N₀. Added Betz jamming-equivalent C/N₀ formula; thresholds: acquisition ≈ 33–35 dB-Hz, tracking ≈ 25–28 dB-Hz.
- **E2:** Kronecker order must be **a_y ⊗ a_x** for element ordering (0,0),(1,0),(0,1),(1,1).
- **E4/E5:** steering derivative is `(−m·sinθ + n·cosθ)` with +j; CRLB needs projector P_a^⊥.
- **E6:** SINR_MVDR = **P_s**·aₛᴴR_{i+n}⁻¹aₛ (P_s was missing).
- **E7:** pre-cancel sign: **e = r − α·s_ref** (and the −α·GPS_ref term matters).
- **E8:** "11→24 dB" inconsistent with Δ=20 dB; theory +20 dB vs measured +13 dB, gap explained (noise floor headroom, crest factor, soft degradation).
- **E11:** diagonal loading δ = λ_min is weak → use **δ ≈ 10·σ̂²** (Cox/Zeskind/Owen 1987, Carlson 1988).
- d = λ/2 = **0.095147 m** (exact c). Element pattern **sin(φ)** confirmed correct (elevation convention).
- Completed all requested derivations: MVDR optimality + max-SINR equivalence (Sherman–Morrison), theoretical SINR (Cauchy–Schwarz), MUSIC consistency (subspace proof + Stoica–Nehorai rate), α(2−α) noise after pre-cancel, ADC headroom from FS with crest factor, DOF proof (M_min = K+2), null-vs-Δθ **−20 dB/decade law** (§5.8 — why 0.02° DOA matters for 60 dB nulls).
- 6-bit weight ceiling: C_dB ≈ −10log₁₀(ε_A²+ε_φ²) → **26 dB worst / ~31 dB RMS** (not "36 dB").
- §9.3 GPSDO common-mode proof confirmed; §10.2 conclusion: **GPS is 25 dB below noise → MUSIC sees only jammers; a(θs) must come from almanac + attitude (IMU required)**.
- v2.1 additions (later in session): **§13.1** Arch-1 power-inversion math (w_PI = R⁻¹e₀/(e₀ᴴR⁻¹e₀), dither/SPSA loop, 16-probe covariance reconstruction Pᵢ = vec(wᵢwᵢᴴ)ᴴvec(R)); **§13.2** inter-chip LO model Γ = diag(e^{jβ₁},e^{jβ₁},e^{jβ₂},e^{jβ₂}) + cal identity q_m = ĥ_m/ĥ₀ via coupler isolated ports; **§13.3** applicability map; SAW-first NF update (system NF ≈ 2–2.5 dB → C/N₀ ≈ 43.5–44 dB-Hz); two open [DERIVE]: optimal dither amplitude, probe conditioning.

## 2. Architecture reviews → arch1.md & arch3.md corrected in place

**arch1.md** (renamed "Blind Analog Nulling / Power-Inversion CRPA"):
- **Fatal flaw fixed:** single post-combiner ADC ⇒ X is 1×N ⇒ **MUSIC impossible as originally drawn**. Stage 11 rewritten: Mode A = power inversion (Compton 1979, w₀=1 constraint), Mode B = 16-probe covariance reconstruction.
- Other fixes: Wilkinson combiner ~lossless for coherent inputs (not 6 dB), fast power-detector trigger added (C/N₀ needs 0.1–1 s — fires too late), ADC sized for α=0 worst case, null ceiling 26–31 dB.

**arch3.md** (sensing-tap hybrid — the flagship):
- B210 FPGA is **Spartan-6** (not Artix-7), needs USB-3 host (Zynq-7000 has none) → B210+OctoClock labeled bench-tier T1 only.
- **Biggest hidden risk found: two AD9361s sharing 10 MHz are NOT phase-coherent** (own PLLs → random inter-board offset per retune + differential phase noise). Fix: **cal tone via sense couplers' isolated ports** (§13.2). Also: GPSDO can't discipline while jammed → requirement is shared *holdover* reference (TCXO), not GPS discipline.
- AD8341 truth: band **1.5–2.4 GHz** (L1 = 75 MHz above band edge, typicals at 1.9 GHz — characterize at L1), max gain **−4.5 dB**, **125 mA @ 5 V → 2.5 W ×4**.
- Honest null split: **delivered at GPS receiver = analog ceiling ~26–36 dB**; the 38–56 dB figures are sensing-layer estimates (digital path is sensing-only). Never conflate in papers.
- MCU deleted (Zynq PS does it; "STM32H74321" not a real PN), δ=10σ̂², −10 dB coupling recommended, AD8314 instead of AD8318, missing items added: **IMU, cal network, PIN limiters**.

**Relationship decided: build ONE board = Arch 3; Arch 1 = its sensing-off fallback mode** (A/B baseline for the paper).

## 3. Hardware audit → ARCH_REVIEW_AND_HARDWARE.md

- BOM errors (datasheet-verified): **ZAPD-4-S+ is 2-way, 2–4.2 GHz** (wrong both ways — use custom microstrip Wilkinson); STM32H74321 typo; OctoClock-G bench-only; **MYIR Z-turn has no 7035 variant**; Zynq-7035 oversized AND idles >1.5 W.
- **User's 1.5 W target impossible with listed BOM (~16–20 W).** Re-scoped to tiers:
  - **T1 bench** (~25 W): current locked parts incl. 2×B210 — validates math.
  - **T2 flying prototype** (4–6 W): Zynq-7020 + NT1065 or dual-AD9361, AD8341s.
  - **T3 production** (~1.5–2.5 W): NT1065 single-LO + **passive phase shifter + DSA** (~0 W) + Artix-7 A35T, MAX2659 LNAs (8.2 mA; SAW-dominated NF makes QPL9547's 0.25 dB advantage shrink to ~0.5 dB).
- NT1065 (NTLab): 4-ch GNSS front end with **single-LO mode designed for CRPA** — Plan A for sensing; check India procurement/export. Plan B: dual AD9361 + §13.2 cal. 
- Part 5 decision log updated with ✅ APPLIED entries after the doc corrections landed.

## 4. Product benchmark → Wall-E4 analysis

RIMCO Wall-E4 CRPA: 55×55×15 mm, 80 g, 5 W, 4 elements, 3 nulls, JSR 95 dB (1 jammer)/80 dB (3), SMA RF out + embedded RX, UART NMEA 1 Hz, 12–24 V, −40…+85 °C, MTBF 2000 h. Key readings:
- 55 mm package ⇒ **~0.15λ element spacing** — different EM regime (strong coupling, degraded DOA; nulling still works). Our sims are all λ/2.
- "JSR 95 dB" = stacked: ~35–45 dB array null + ~50–55 dB receiver C/A resistance.
- **SMA RF out = the product feature** (CRPA as drop-in active antenna) → analog nulling architecture (Arch 3) is the right base; pure digital can't do this without re-modulating.
- Beatable: 1 Hz nav (→10 Hz), MTBF 2000 h, no jammer-bearing reporting (our differentiator).

## 5. Final product plan → plan.md (COGNAV-P1)

User direction: **ONE prototype, GPS L1 only, full use of analog nulling, drone-mounted, our own design** (not a Wall-E4 clone). Plan highlights:
- 2×2 λ/2 (95.1 mm), ≥190×190 mm ground plane, ~200×200×30 mm, ≤350 g, **≤8 W** from 4S–6S bus, on the Ø330 drone base plate (prop-free zone, Ø406 props).
- Targets: analog null **≥35 dB (1 jammer) / ≥30 (2) / ≥25 (3)**, stacked JSR ≥85 dB, re-null <100 ms, SMA clean-RF out + u-blox M10 NMEA + jammer-bearing telemetry.
- **§4 thesis — beating the 26–31 dB ceiling:** (1) continuous weights (AD8341 + 16-bit AD5676 → quantization vanishes), (2) cal tone kills static mismatch, (3) **closed-loop trim**: power detector + dither descent seeded by MVDR (§13.1 reused as trim, not blind search) → +5–10 dB expected, (4) trim continuous / MVDR on events. **MVDR = coarse aim, trim = polish.**
- Two assembly stages: **Stage A** bench brassboard (locked parts + B210s, lab) proves ≥35 dB conducted null before any PCB; **Stage B** flight PCB stack (Zynq-7020 SoM, NT1065 or dual-AD9361, two-board sandwich in milled Al box).
- Sim tasks first (no code yet committed): S-6 sin(φ) fix → S-1 trim-loop sim (the bet: +5–10 dB) → S-2 continuous-weight ceiling → S-3 cal residue → S-4 latency → S-5 stacked-JSR table.
- Phases P0(2–3wk sims/procurement) → P1(6–8wk brassboard) → P2(10–14wk flight proto) → P3(4–6wk drone integration/flight). Out of scope: compact 0.15λ array, BDS/GLONASS wideband, production qual.
- Test rules: all jamming **conducted/cabled only** (no OTA without authorized range); export-control review (SCOMET/Wassenaar) before datasheet claims.
- This-week actions: S-6+S-1 sims, NT1065 procurement check, **bench-characterize one AD8341 at 1575.42 MHz** (band-edge risk), 4-port test-fixture spec (doubles as cal rig).

## 6. Other artifacts produced this session

| File | What it is |
| :-- | :-- |
| `COGNAV_MathModelling_v2_CORRECTED.md` | v2.1 corrected math + §13 (source of truth) |
| `arch1.md` / `arch3.md` | corrected in place (the two operating modes) |
| `ARCH_REVIEW_AND_HARDWARE.md` | comparison + BOM audit + T1/T2/T3 tiers + decision log |
| `plan.md` | COGNAV-P1 single-prototype plan (current direction) |
| `hardware_selection_prompt.md` | ready-to-run prompt: 9 selection blocks, 2–3 options each, 8 mandatory outputs (power/NF/phase budgets must close), India procurement, [VERIFY] rule |
| `cognav_p1_block_diagram.png` + `make_block_diagram.py` | Arch 4 flight-prototype block diagram (green=analog path, blue=sensing, orange=control, gray=support) |
| `SESSION_CONTEXT_2026-06-11.md` | this file |

## 7. Standing decisions (do not relitigate without new data)

1. Arch 3 is the base; Arch 1 is its fallback mode — one hardware platform.
2. L1-only prototype; λ/2 spacing; compact array and multi-band are follow-ons.
3. Analog nulling is the product path (clean RF out); digital is sensing/steering only.
4. No B210/OctoClock/GPSDO/Zynq-7035 in anything that flies.
5. Sensing front end: NT1065 single-LO (Plan A) / dual-AD9361 + cal (Plan B) — decide at P0 by procurement.
6. Honest spec language: 2 jammers with margin (3 = demonstrated max); null depth quoted separately from stacked JSR.
7. Cal tone through coupler isolated ports is mandatory (fixes mismatch AND inter-chip phase).

*COGNAV Project | session digest written 2026-06-11*
