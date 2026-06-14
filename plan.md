# plan.md — COGNAV-P1: L1-Band Analog-Nulling CRPA Prototype (Drone-Mounted)

## Single prototype. GPS L1 only. Analog nulling used to its full depth. Our own design — Wall-E4 is the benchmark, not the template.

**Date:** June 2026
**Base architecture:** Arch 3 (arch3.md) — sensing tap + analog weighting + RF GPS path
**Math:** COGNAV_MathModelling_v2_CORRECTED.md v2.1 (incl. §13)
**Hardware verdicts:** ARCH_REVIEW_AND_HARDWARE.md
**Benchmark (for spec targets only):** RIMCO Wall-E4 — 4 elements, 3 nulls, 5 W, SMA RF out + embedded RX

---

## 1. What we are building (one paragraph)

A 2×2 GPS-L1 CRPA module on a λ/2 array (95.1 mm spacing) that mounts on our drone's base plate. **All jammer suppression happens in the analog domain** — vector modulators + Wilkinson combiner — so the GPS signal is cleaned *before any ADC* and comes out of an SMA connector looking like a normal active antenna (any receiver or autopilot GPS can use it), plus an embedded u-blox receiver giving NMEA to the autopilot over UART. The digital side (4-channel coherent sensing tap → MUSIC → MVDR) never touches the GPS signal: it only *computes and steers* the analog weights, and then a power-detector feedback loop *polishes* the analog null beyond what open-loop computation can reach. Jammer bearings are reported to the autopilot as telemetry — our differentiator.

Why this shape: analog nulling gives the two things a product needs that pure-digital cannot — (1) **the ADC/receiver never sees the full jammer** (dynamic-range protection, math §6.4), and (2) **a universal analog RF output**. The prototype's whole purpose is to demonstrate the deepest, most robust analog nulls we can achieve, with the digital layer as the brain, not the muscle.

---

## 2. Prototype target specification

| Parameter | Target | Notes |
| :-- | :-- | :-- |
| Band | **GPS L1 1575.42 MHz only** (Galileo E1 falls in-band for free; not a requirement) | Narrowband math (§2.1) holds; SAW BW ~2 MHz |
| Array | 2×2 RHCP patch, d = λ/2 = 95.1 mm, ≥190×190 mm ground plane | All existing sims apply unchanged |
| Nulls | 3 max (= M−1); **spec'd performance: 2 jammers with margin** | DOF honesty per math §5.7 |
| Analog null depth | **≥ 35 dB (1 CW jammer), ≥ 30 dB (2 jammers), ≥ 25 dB (3)** after cal + trim | See §4 — beyond the 26–31 dB open-loop 6-bit ceiling, achieved via continuous weights + closed-loop trim |
| Stacked JSR (with receiver, CW) | ≥ 85 dB single jammer | null + ~50–55 dB receiver C/A resistance (math §10.3 Betz budget) |
| Jammer types | CW, swept FMCW, AWGN barrage | Our existing simulated threat set |
| Re-null time | < 100 ms (jammer appears/moves) | MVDR one-shot + trim convergence |
| Outputs | SMA RF L1 (active-antenna emulation, sinks host 3–5 V bias) + UART NMEA (embedded RX) + jammer-bearing telemetry sentence | |
| Power | ≤ 8 W from the drone's 4S–6S bus (≈14.8–22.2 V → 12–24 V input range) | Prototype tier (T2); production power-down path known (ARCH_REVIEW T3) |
| Mass / size | ≤ 350 g, ~200×200×30 mm module on the Ø330 base plate, patches on top face | Per drone layout (math doc §12.4): central prop-free zone, clear of Ø406 props |
| Environment | Bench + fair-weather flight (−10…+50 °C) for the prototype | Qual range is production scope, not now |

Explicitly **out of scope for this prototype:** BDS B1I / GLONASS (wideband nulling), the 55 mm compact array (0.15λ mutual-coupling regime), production enclosure/qual, MTBF program. Each is listed in §9 as a follow-on.

---

## 3. Architecture (Arch 4 = Arch 3 productized, analog-first)

```
 4× RHCP patch (top face, shared 190×190 ground plane)
   │
 [PIN limiter] → [SAW BPF] → [LNA] ──────────────────────── ×4 channels
   │
 [directional coupler −10 dB]── sense ──→ 4-ch coherent RX → FPGA (sensing brain)
   │      ↑ isolated port ←── CAL TONE (startup / temperature / on-demand)
 main path (THE product path — stays analog end-to-end)
   │
 [AD8341 vector modulator] ×4  ← 16-bit DAC (AD5676) ← FPGA weights
   │
 [4-way Wilkinson combiner — microstrip, on-PCB]      ← jammer dies here
   │
 ├─→ [post-LNA + BPF] → SMA RF OUT (clean L1, active-antenna emulation)
 ├─→ [embedded u-blox RX] → UART: NMEA + per-SV C/N₀ (KPI) → autopilot
 └─→ [coupler → AD8314 power detector] → FPGA  ← the null-polishing sensor

 FPGA/Zynq-7020: covariance → MUSIC (jammer DOAs) → MVDR (weights)
                → DAC write → CLOSED-LOOP TRIM on power detector (§4)
                → fallback: pure power-inversion if sensing chain faults (Arch 1 mode, math §13.1)
 IMU + almanac (from embedded RX) → a(θs) constraint (math §10.2)
 Clock: ONE shared TCXO → buffer → all LOs/ADCs (no GPSDO — can't discipline while jammed)
```

Operating chain: **sense → solve → steer → polish → verify** (verify = embedded RX C/N₀ and power detector both confirm the null).

---

## 4. Making FULL use of analog nulling (the heart of this prototype)

The naive analog ceiling is 26–31 dB (6-bit stepped weights, math §6.2). We get past it with four stacked measures — this is the prototype's engineering thesis:

1. **Continuous weights, not stepped.** AD8341 is controlled by analog I/Q voltages from a **16-bit DAC** — weight resolution is effectively continuous; the quantization term ε_φ², ε_A² in §6.2 nearly vanishes. The ceiling moves to VM linearity + channel mismatch.
2. **Calibration kills static mismatch.** Cal tone through the coupler isolated ports (math §13.2) measures each channel's gain/phase (and any LO issues) → corrections absorbed into the steering model. This is what turns the §9.1 "σ_phase = 5° → 20–27 dB" disaster back into 35 dB+ capability.
3. **Closed-loop null trim — the key step.** MVDR gives the weights open-loop; residual error (cal residue, temperature drift, DOA error via §5.8) limits the null. The power detector on the combiner output measures the *actual* residual jammer power, and the FPGA performs a small dither/gradient descent around the MVDR solution (the §13.1 machinery, reused as a *trim* rather than a blind search — it starts already-converged). This closes the loop around every analog imperfection at once. Expected gain: +5–10 dB of null depth and immunity to slow drift. **MVDR = coarse aim, trim loop = fine polish.**
4. **Trim runs continuously at low rate; MVDR re-solves on events** (power detector jump, MUSIC sees the jammer move >0.5°, temperature step). This division keeps re-null < 100 ms while the steady-state null sits at its deepest.

Honest physics bounds to state on the datasheet: null depth is ultimately limited by VM linearity/noise floor and DOA error (§5.8: 20 dB per decade of angular error — with MUSIC at <0.1° and trim active, not the binding constraint). Target ≥ 35 dB single-jammer is conservative against this stack.

---

## 5. Hardware plan (one prototype build, two assembly stages)

### Stage A — Bench brassboard (existing locked parts, validates §4 before any custom PCB)
Connectorized chain on a plate: SAW + QPL9547 evals → ZFDC couplers → AD8341 evals → connectorized Wilkinson → SMA out; sensing via the 2× B210 + bench clock (T1 back-end, lab only); AD5676+OPA354 weight board; AD8314 detector. **Purpose:** demonstrate ≥35 dB conducted null with cal + trim loop. Nothing here flies; everything here de-risks the PCB.

### Stage B — Flight prototype (custom PCB stack, drone-mountable)

| Block | Part (per ARCH_REVIEW verdicts) | Power |
| :-- | :-- | --: |
| 4× limiter + SAW (Murata) + LNA QPL9547 | locked parts | 0.86 W |
| 4× coupler (PCB coupled-line, −10 dB) | replaces ZFDC bricks | 0 W |
| 4× AD8341 + AD5676 + OPA354 buffers | locked parts — kept for the prototype (continuous weights are the point, §4.1) | 2.55 W |
| Wilkinson (microstrip RO4350) | custom — NOT ZAPD-4-S+ (wrong band/way) | 0 W |
| 4-ch coherent sensing RX | **Plan A: NT1065-class single-LO** (procurement check first); **Plan B: 2× AD9361 on carrier + §13.2 cal** (works, more power) | 0.5–1.6 W |
| Zynq-7020 SoM (not 7035 — oversized; not B210s — can't fly) | covariance in PL, MUSIC/MVDR/trim on the A9s | 2.0–2.5 W |
| Embedded u-blox M10 + IMU (ICM-42688) + TCXO + clock buffer | | 0.2 W |
| Post-LNA, AD8314 detector, cal synth | | 0.15 W |
| DC-DC from 4S–6S bus (≈85% eff.) | | 0.7–1.0 W |
| **Total** | | **≈ 7–9 W** → trim to ≤8 W by duty-cycling sensing RX once nulls converged |

Mechanical: two-board sandwich (RF board top / digital board below) in a milled Al box; patches + ground plane on the lid; one SMA, one GH-series power/UART connector; mounts in the drone's central prop-free zone per the §12.4 layout (props Ø406, clock-distribution lines length-matched).

---

## 6. Math & simulation tasks (all on the existing Python codebase — before PCB layout)

1. **S-1 Trim-loop simulation:** add the §13.1 dither machinery *seeded by MVDR weights* to hybrid/realistic sim; quantify null gain vs dither amplitude and detector noise; closes the §13 [DERIVE] on optimal dither. **Gate for §4.3.**
2. **S-2 Continuous-weight ceiling:** rerun §6.2 hardware-error model with 16-bit DAC + AD8341 linearity specs instead of 6-bit steps → predicted ceiling for the datasheet.
3. **S-3 Cal residue budget:** end-to-end null depth vs residual gain/phase error after §13.2 cal (sweep 0.1°–2°); sets the cal accuracy requirement.
4. **S-4 Re-null latency budget:** covariance epoch + EVD + DAC settle + trim settle < 100 ms; allowed jammer angular rate via §5.8.
5. **S-5 Stacked-JSR table:** Betz-formula budget (§10.3) converting our null depths into "with receiver" JSR numbers for honest benchmark comparison.
6. **S-6 Element pattern fix** (math doc Bug A — sin φ) must land in the sim suite first; it's a precondition for S-1…S-3 being physically valid.

---

## 7. Firmware scope (planning only — no code now)

PL: 4-ch covariance accumulator, cal-tone correlator. PS: Jacobi EVD, MUSIC scan (coarse→fine), MVDR solve, DAC SPI, **trim-loop state machine (the §4 differentiator)**, Arch-1 fallback mode, temperature-triggered recal, UART protocol (NMEA passthrough + $PCOG jammer-bearing sentence / optional MAVLink), boot self-test via cal loopback, IQ-snapshot logging mode for sim cross-validation.

---

## 8. Test plan

| # | Test | Pass |
| :-- | :-- | :-- |
| 1 | Conducted (4-port fixture, GNSS sim + cabled jammers): null depth vs J/S, 1/2/3 jammers, CW/FMCW/AWGN | ≥ 35/30/25 dB; trim adds measurable depth over open-loop MVDR (the thesis test) |
| 2 | Conducted: C/N₀ vs J/S through embedded RX **and** external receiver on SMA | matches S-5 budget ±3 dB |
| 3 | Re-null latency (switched jammer) | < 100 ms |
| 4 | Anechoic: commanded null bearing vs truth; MUSIC DOA accuracy | < 2° null placement; < 1° DOA |
| 5 | Drone integration: EMI from ESCs, blade-flash effect on covariance, vibration | no null degradation > 3 dB props-on vs props-off |
| 6 | Flight: GPS hold with module as sole GPS source (no OTA jamming — conducted-only jamming per regs; flight tests verify integration, not jamming) | clean nav handover to autopilot |

All jamming is cabled/conducted or at an authorized facility — never radiated in the open. Export-control sanity check (SCOMET/Wassenaar dual-use) before publishing a datasheet.

---

## 9. Phases

| Phase | ~Duration | Output | Gate |
| :-- | :-- | :-- | :-- |
| **P0** | 2–3 wk | Sims S-6 → S-1…S-5 done; NT1065 procurement verdict; Stage-A parts on the bench | Trim-loop sim shows ≥ +5 dB over open-loop |
| **P1** | 6–8 wk | Stage-A brassboard: live cal + MVDR + trim on real RF | ≥ 35 dB conducted null, 1 jammer |
| **P2** | 10–14 wk | Stage-B flight prototype PCB stack in enclosure | Test table rows 1–4 passed |
| **P3** | 4–6 wk | Drone integration + flight | Rows 5–6 passed → prototype DONE |

**Follow-ons (explicitly not this prototype):** compact 0.15λ array (mutual-coupling program), BDS/GLONASS wideband nulling, passive-weight low-power variant (ARCH_REVIEW T3, ~2.5 W), production qual/MTBF, 6-element DOF-margin variant.

---

## 10. Risks

| Risk | Mitigation |
| :-- | :-- |
| Trim loop interacts badly with fast jammers (chasing a moving target) | Trim only when power detector is quasi-static; MVDR handles dynamics (S-4 sets thresholds) |
| NT1065 unobtainable | Plan B dual-AD9361 with §13.2 cal is fully specified; decide at P0 |
| AD8341 at band edge (1.5 GHz spec edge vs 1575.42) | First Stage-A measurement: characterize one AD8341 at L1 before committing 4 to PCB |
| 7–9 W budget creep | Duty-cycle sensing RX after convergence; trim loop needs only the power detector, not the 4-ch RX |
| Zero DOF margin at 3 jammers | Datasheet spec = 2 jammers with margin; 3 = demonstrated max |
| ESC/motor EMI on drone | Shielded enclosure, LDO tree, test row 5 early with a mule airframe |

---

## 11. This week

1. Run S-6 (sin φ fix) then S-1 (trim-loop sim) — the single result this whole plan bets on (+5–10 dB from closed-loop trim). Pure Python, existing codebase.
2. NT1065 procurement check → locks the sensing back-end (Plan A/B).
3. Bench-characterize one AD8341 eval board at 1575.42 MHz (band-edge risk retire).
4. Draft the 4-port conducted test fixture spec (doubles as the cal rig).

---

*plan.md — COGNAV-P1 single-prototype plan: L1-only, analog-nulling-first, drone-mounted. No code in this phase.*
*COGNAV Project | June 2026*
