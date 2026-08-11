---
marp: true
paginate: true
size: 16:9
style: |
  section {
    background: #ffffff;
    color: #000000;
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 20px;
    padding: 48px 56px;
  }
  h1 { font-size: 34px; font-weight: 600; border-bottom: 2px solid #000; padding-bottom: 8px; }
  h2 { font-size: 24px; font-weight: 600; margin-top: 4px; }
  h3 { font-size: 20px; font-weight: 600; }
  table { font-size: 15px; border-collapse: collapse; width: 100%; }
  th { border-bottom: 1.5px solid #000; text-align: left; font-weight: 600; }
  td { border-bottom: 0.5px solid #999; }
  code { background: #f2f2f2; color: #000; }
  strong { font-weight: 700; }
  section::after { color: #666; font-size: 13px; }
  blockquote { border-left: 3px solid #000; padding-left: 14px; color: #333; font-style: normal; }
---

<!-- _paginate: false -->

# COGNAV-4
## Cognitive Anti-Jam CRPA for NavIC / GNSS Drone Navigation

### Technical Review — Work Completed to Date

Review date: 11 August 2026
Reporting period: June 2026 – August 2026
Latest field session: 10 August 2026

Platform under test: 4-element 2×2 URA · 2 × Ettus USRP B210 · GPS L1 (1575.42 MHz)

---

# 1. Executive Summary

**The signal processing is proven. The RF front end is the bottleneck.**

| Subsystem | State | Strongest evidence |
|---|---|---|
| DSP / beamforming mathematics | **Verified** | C++ matches Python reference to ~1e-14; 159 self-test checks pass |
| 4-channel phase coherence | **Working** | Boresight jitter `[0, 2.3, 1.9, 1.8]°`, tone SNR 41–46 dB |
| 10 MHz REF distribution | **Working** | `ref_locked` on both boards, every attempt, indoors and outdoors |
| Adaptive DoA + nulling | **Proven on hardware** | Walk-around: 29–50 dB suppression, azimuth error ≤ ±7° |
| Commanded static nulling | **Proven on hardware** | −18.9 dB and −23.6 dB at two typed directions |
| PPS / shared timebase | **Intermittent** | ~50 % of launches fail to align; both boards fail together |
| GPS signal reception | **Blocked** | 0 / 32 PRNs acquired at 76 dB gain — link budget, not software |
| Analog pre-nulling stage (C1) | **Designed, not built** | Simulation only: 31.6 dB SINR gain at the 30 dB design point |

> Both undemonstrated headline capabilities are blocked by the same cause — **the RF front end, not the signal processing.** Neither requires a line of code to change.

---

# 2. Objectives — Evidence Status

| # | Objective (abridged) | Status | Evidence held today |
|---|---|---|---|
| **O1** | 4-element dual-band RHCP CRPA (L5/S + L1/L2 + E1/E5a), >4 dBic, <3 dB AR, coupling <−20 dB | **Partial** | Single-band L1 4-element array `AJ_GC_ANT22_V1` fabricated, 65 mm spacing (0.341 λ). Gain, axial ratio and coupling **not yet measured** — no anechoic data. Dual-band L5/S array not started. |
| **O2** | Hybrid analog–digital null steering, >30 dB analog pre-null, >40 dB combined | **Partial** | Digital LCMV stage proven on hardware to −47 dB adaptive. Analog stage architected and costed this month; **no hardware built**. |
| **O3** | FPGA real-time pipeline: MUSIC, LCMV, CNN classifier, dual-domain synthesiser | **Partial** | MUSIC + LCMV implemented and hardware-validated **in host C++** (~17,500 lines). No FPGA RTL. CNN classifier not started. |
| **O4** | Multi-constellation NavIC baseband, EKF, RAIM, DroneCAN, 80×80×18 mm PCB | **Not started** | GPS L1 C/A acquisition engine `gpsacq` written (2,974 lines) but has never acquired. No NavIC code, no PCB. |
| **O5** | Anechoic + Spirent + field validation, UAV integration, 25 TRL-7 units | **Not started** | Bench and open-air testing only. No chamber, no simulator, no UAV integration. |

**Framing:** the present L1 rig is a **risk-reduction testbed** that de-risks the array processing, synchronisation and calibration architecture ahead of the NavIC dual-band build. It is not itself an O1 deliverable.

---

# 3. Novelty Claims — Evidence Status

| # | Claim | Status | Basis |
|---|---|---|---|
| **C1** | Hybrid analog+digital nulling shifts the digital-MVDR failure point (~24 dB) and preserves covariance integrity | **Simulated** | `hybrid_sim.py`: 31.6 dB SINR improvement at the 30 dB design point (target >15 dB); 13 dB dynamic-range extension (target >10 dB). **Ideal conditions only.** No hardware. |
| **C2** | Dual-domain spatial + spectral defence with CNN weight allocation | **Concept** | No implementation. Spatial domain proven; spectral notching and classifier not started. |
| **C3** | Motion-assisted virtual aperture from drone motion | **Concept** | No implementation, no simulation. |
| **C4** | First NavIC S-band (2492.028 MHz) CRPA | **Concept** | No S-band hardware or code. Current work is GPS L1 only. |
| **C5** | Open-source NavIC ecosystem + 250 k-sample jammer dataset | **Partial** | Substantial codebase exists and is internally documented; not yet licensed or released. Dataset not built. |

**Review position:** C1 is the claim closest to demonstration and carries quantified simulation support. C2–C4 are currently design intent. Presenting them as achieved would not survive scrutiny; presenting C1 with its simulation provenance clearly stated will.

---

# 4. System As Built

**Array.** `AJ_GC_ANT22_V1` — 4 corner-truncated square patches (circular polarisation), 2×2 planar, element spacing **65 mm = 0.341 λ** at L1. Passive: no LNA, no bias network.

**Radio.** 2 × Ettus USRP B210 (serials `34D04E6`, `34D126B`), RX2 port on all four channels.

| Parameter | Value |
|---|---|
| Centre frequency | 1.57542 GHz (GPS L1) |
| Sample rate | 4 MSPS complex |
| RX gain | 40 dB (76 dB for acquisition attempts) |
| Snapshot / FFT length | 1024 (16,384 for image-link tools) |
| Geometry | 2×2 URA, row-major `Rx0=(0,0) Rx1=(d,0) Rx2=(0,d) Rx3=(d,d)` |
| Reference / timebase | External 10 MHz + external 1 PPS, both boards |

**Timebase.** LBE-1421 GPSDO-locked clock source → Mini-Circuits ZN2PD2-14W-S+ splitter → both B210s. Enclosure also carries a buck regulator and the SBC.

**Software.** Two hardware instruments in C++ (single translation unit each, Qt5 + UHD + Eigen) plus the originating Python family:

| Tool | Lines | Function |
|---|---|---|
| `hardnull.cpp` | 5,548 | Two **commanded static** nulls — weights ignore received data |
| `usrpdoa.cpp` | 5,853 | **DoA-guided adaptive** null — MUSIC bearing → hard LCMV zero |
| `gpsacq.cpp` | 2,974 | GPS L1 C/A acquisition search + dashboard |
| `usrpgps.cpp` | 3,095 | u-blox repeater path (end-to-end fix demonstration) |

---

# 5. Phase 1 — Simulation Baseline (June 2026)

Five-stage synthetic pipeline: array data generation → MUSIC → MVDR → hybrid analog/digital comparison → realistic-impairment comparison.

**KPI results, ideal conditions — all pass:**

| KPI | Result | Target | Verdict |
|---|---|---|---|
| DoA accuracy | 0.01–0.02° | <1° | Pass |
| Null depth (J1/J2) | 50–64 dB | >40 dB | Pass |
| GPS look-direction gain | 0.00 dB | 0 dB | Pass |
| Hybrid dynamic-range extension | 13 dB | >10 dB | Pass |
| **SINR improvement at 30 dB JNR** | **31.6 dB** | >15 dB | Pass |

**The C1 result.** `hybrid_sim.py` sweeps jammer power 0–30 dB and compares three paths — ideal, pure-digital, and hybrid with analog pre-cancellation. The pure-digital path degrades once the modelled ADC saturates; the hybrid path does not. This is the origin of the 31.6 dB figure quoted in C1.

**Declared risk, unresolved.** Second-null depth is 50 dB ideal but estimated **30–42 dB** under modelled hardware impairment, against a >40 dB target. Phase mismatch dominates: ±5–8° per channel costs 10–20 dB of null depth. The mitigation identified at the time was a 6-element array.

> All Phase-1 figures are **simulation**. No hardware existed when they were produced.

---

# 6. Phase 2 — Coherence and Calibration

Four coherent channels across two independent radios is the enabling problem. Two mechanisms were separated and solved individually.

**Synchronisation.** 10 MHz REF locks sample *rate*; 1 PPS establishes a common sample-time *origin*. Both are required. Every tool **fails closed** — without verified REF lock on both boards *and* an observed shared PPS edge, no GUI opens and no result is published. Covariance, MUSIC and the LCMV solve all look plausible on misaligned data while being physically meaningless.

**The single-C phase model.** Per-channel correction `offset = [0, A1, C, C+d]`:

| Term | Measured | Nature |
|---|---|---|
| `A1` — Rx1 vs Rx0 (intra-board A) | ≈ −66° | Fixed hardware constant |
| `d` — Rx3 vs Rx2 (intra-board B) | ≈ −17.8° (σ ≈ 0.2°) | Fixed hardware constant |
| `C` — board B vs board A | Re-measured per session | Jumps on PLL / stream re-lock |

**Boresight calibration.** CW source at zenith, 8 snapshots × 4096 samples, cross-correlation phase at peak-magnitude lag, per-channel 12 dB tone gate. Append-only JSON history keyed to hardware identity and **exact element spacing**.

**Best validated run (10 Aug 2026):** jitter `[0, 2.3, 1.9, 1.8]°`, tone SNR `[45.1, 43.4, 46.2, 41.1] dB`.

**Why calibration is load-bearing:** an uncalibrated array reports a jammer at **292°** when it is physically at **45°**.

---

# 7. Measured Anti-Jam Performance (Hardware)

A real CW jammer was carried around the array in 45° azimuth steps. Nothing about the jammer was entered into the software.

**Campaign 1 — Auto-MVDR (Capon, live covariance):**

| True az | 0° | 45° | 90° | 135° | 180° | 225° | 270° | 315° |
|---|---|---|---|---|---|---|---|---|
| Measured az | 0 | 47 | 86 | 133 | 187 | 226 | 274 | 316 |
| Suppression (dB) | −35.5 | −50 | −32 | −44 | −43 | −41.4 | −32.8 | −41.6 |

Azimuth error ≤ ±7°; suppression **32–50 dB**.

**Campaign 2 — DoA-guided LCMV (MUSIC bearing → hard zero + unity zenith):**
Azimuth tracking ≤ **±4°**; suppression **29–47 dB** across the same eight stations.

**Campaign 3 — Commanded static nulls (`usrprun22` / `hardnull`), weights from typed angles only:**

| Commanded (az, bore) | Measured suppression |
|---|---|
| 180°, 45° | **−18.9 dB** |
| 90°, 90° | **−23.6 dB** |

Both cleared the −15 dB NULLED threshold. Static nulls are expectedly shallower than adaptive: a geometric null lands on the jammer only if calibration, steering model and typed angle are all correct, whereas an adaptive null digs itself onto the true position.

---

# 8. Degrees of Freedom — and a Rejected Approach

**DOF budget of a 4-element array:**

| Constraint | Complex DOF |
|---|---|
| Unity gain at zenith (protect GNSS) | 1 |
| Hard null, commanded direction 1 | 1 |
| Hard null, commanded direction 2 | 1 |
| Remaining (conditioning / min-norm) | **1** |

A third null consumes all four DOF: white-noise gain rises ≈ **+17 dB** and ≈ **21 dB** of zenith SNR is burned — "protected" in name only. A fourth null is impossible. **WNG policy:** 2-null warn +10 dB / reject +15 dB; 3-null warn +15 dB / reject +25 dB.

**The methodological result — two-null MVDR was tested and rejected.**

Adding null constraints to a live-covariance objective leaves one spare DOF, which power minimisation spends nulling whatever is strongest — commanded or not. **Measured on hardware: a jammer 90° away from the commanded null still read ≈ −60 dB "suppression."** The walk-around test would then read SUPPRESSED everywhere and prove nothing.

The fix was architectural: the static tool's weights are computed from typed angles alone (`R → I`), and received samples only *measure* the output. The two instruments are deliberately kept separate and must not be merged.

> This is a genuine review finding: a configuration that appeared to work better was rejected because it could not be falsified.

---

# 9. Verification and Defect Record

**Numerical verification.** The C++ instruments are ports, not rewrites, and are held to the Python reference:

| Check | Result |
|---|---|
| `hardnull --selftest` | **104 checks pass** — weights match to ~1e-14, DSP to ~1e-9 dB, published WNG table reproduced (+6.8 / +9.6 / −0.9 / +11.1 dB) |
| `usrpdoa --selftest` | **55 checks pass** — MUSIC recovers 5 synthetic bearings at 0° azimuth error |
| Moving-jammer regression | Stale weights leave the jammer at **+3.9 dB**; re-solved weights null it at **−91.1 dB** |
| Synthetic two-null contrast | **−78 dB** on-null vs **+3.4 dB** off-null; rejection cases all fire |

**Defects found and fixed (Aug 2026 session):**

| Defect | Consequence | Fix |
|---|---|---|
| Calibration had no jitter gate | A no-PPS run (jitter `[0, 12.9, 92.7, 91.7]°`) was saved and silently became every tool's default | Reject jitter > 15°; disable calibration under `--allow-unsynced` |
| `have_bearing_` latched | Published a NULLED verdict computed from noise after the jammer went off air | Gate readout on the current frame, not on history |
| Acquisition false alarms | An absent PRN scored 3.1 against a 2.8 threshold | Peak-to-secondary metric, threshold 2.5, reject edge-pegged Doppler |
| Wrong element spacing | 95.21 mm model on the 65 mm array gave −9.3 dB instead of −90 dB — looks like a hardware fault | Both tools pinned to operator-confirmed 65 mm; store keys on exact spacing |

---

# 10. Open Blockers

**10.1 GPS reception — link budget, not software.**
`gpsacq` searched all 32 PRNs at 76 dB gain with 20 ms non-coherent integration. **Zero satellites.** Every PRN scored 1.25–1.38; a known-absent control satellite measured 1.28 — that is the noise distribution, not weak signal.

*Cause:* the array elements are passive bare patches. GPS L1 arrives at ≈ **−130 dBm**, roughly **20 dB below thermal noise** in a 2 MHz band. The B210's RX2 port supplies no DC bias, so an active antenna cannot be powered without an external bias-T.

*False-alarm discipline established.* PRN 16 was rejected because its code phase jumped 60.9 → 910.9 chips between captures and its Doppler pegged at the −6000 Hz search edge. PRN 27 survived those checks at 2.44 → 2.36, and was still killed by the **integration test**: tripling integration (20 → 60 ms) should have taken 2.4 to ≈ 4; it fell to 1.2 and recovered only to 1.6. **Rule adopted: never accept a detection from a single sweep.**

**10.2 PPS intermittent — dominant operational blocker.**
~50 % of launches fail alignment, and both boards always fail *identically*, implicating the shared source rather than a cable. Leading candidates: GPSDO lock instability from poor sky view, and 1 PPS distributed through a **ZN2PD2-14W-S+ specified 500–10500 MHz** — a 1 Hz TTL pulse through that part is differentiated into a spike that crosses threshold only sometimes.

**10.3 Anti-jam function unproven live.** The beamformer ran sample-aligned with valid calibration, but **no jammer was transmitting**. Peak −73 to −80 dBFS never cleared the 12 dB gate; eigenvalue ratios 1.0–1.2 against a required 3.0. Correct refusal to publish — but not a demonstration.

---

# 11. Hybrid Analog Front End — Design for C1 / O2

**Architecture.** Two analog-nulled subarrays feeding one B210, preserving two channels for the digital stage:

```
patch1 ─ SAW ─ LNA1 ─ VM1 ─┐
                            ├─ Wilkinson ─ LNA2 ─ B210 RX-A ─┐
patch2 ─ SAW ─ LNA1 ─ VM2 ─┘                                  ├─ digital LCMV
patch3 ─ SAW ─ LNA1 ─ VM3 ─┐                                  │
                            ├─ Wilkinson ─ LNA2 ─ B210 RX-B ─┘
patch4 ─ SAW ─ LNA1 ─ VM4 ─┘
       └─ 20 dB couplers ──────────────→ B210 #2 (weight computation)
```

**Weighting element: Analog Devices AD8341** (1.5–2.4 GHz vector modulator; −4.5 to −34.5 dB amplitude, continuous 360° phase, differential ±500 mV I/Q). It is a hardware complex multiplier: two DC control voltages set `w = I + jQ`. The ADL5390 alternative was rejected — discontinued. Purchase as `AD8341-EVALZ` (SMA-connectorised).

| Design quantity | Value |
|---|---|
| Cascade noise figure (LNA1 25–30 dB, network 8 dB, LNA2) | ≈ 1.5 dB |
| Usable J/S, digital only (12-bit ADC + AGC) | ≈ 65 dB |
| Usable J/S, with 30 dB analog pre-null | ≈ 95 dB |
| Path match required for −30 dB null | 0.27 dB / 1.8° ≈ 0.7 mm of coax |
| Single-tap null limit over 2.046 MHz C/A (0.31 ns aperture delay) | ≈ −48 dB |
| Same, against a 20 MHz barrage jammer | ≈ −28 dB |

**Two side benefits:** both channels of one B210 share an AD9361 LO, so the signal path becomes coherent **without PPS**; and LNA1 simultaneously resolves blocker 10.1.

**Build order:** (1) two-element canceller, one vector modulator, one B210; (2) four elements open-loop, reusing `dual_null_weights()` unchanged; (3) close the loop against measured output power; (4) standalone embedded controller.

---

# 12. Roadmap and Priorities

**P0 — free, do first.** Borrow the GPSDO's active GPS antenna onto a B210 through a bias-T and re-run `gpsacq`. Satellites appearing proves the correlator, sample rate and search are correct and isolates the fault to the passive patches — deciding the LNA purchase before money is spent. Ten minutes, hardware already in the enclosure.

**P1 — unblocks GPS.** One L1 LNA per channel with bias-T. Antenna to open sky, facing up.

**P2 — unblocks reliable operation.** Verify whether 1 PPS survives the ZN2PD2; if not, replace that leg with a DC-coupled resistive splitter or logic fan-out. Give the GPSDO antenna proper sky view. Wired Ethernet to the operator machine.

**P3 — closes validation gaps.** Measure element spacing with calipers. Reconfirm `HARDWARE_AZIMUTH_SIGN` against a known non-180° azimuth. Run the live-jammer demonstration with `HOLD NULL` to prove the null is spatial and not self-confirming.

**P4 — extends capability toward the objectives.** Install `gnss-sdr` for full position decode. Build the analog stage (§11). Then, in objective order: anechoic characterisation of the existing array (O1 metrics), FPGA migration of the proven MUSIC/LCMV chain (O3), NavIC L5/S front end and baseband (O1/O4), CNN classifier (O3/C2), open-source release (C5).

**Honest closing position.** Three things are genuinely established: the beamforming mathematics is verified to 1e-14 against an independent implementation, the array demonstrably suppresses a real jammer by 29–50 dB while tracking its bearing to ±4°, and the system provably refuses to publish results it cannot justify. Two things are not: GPS has never been received, and the analog stage that carries claim C1 exists only in simulation. Both are RF front-end work, and both are costed and specified.
