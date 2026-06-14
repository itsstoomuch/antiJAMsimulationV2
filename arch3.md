# Architecture 3 — Hybrid Analog-Digital CRPA with Sensing Tap

## COGNAV-4 | GPS L1 1575.42 MHz | Full Hybrid Two-Layer Architecture

**Status:** Draft  
**Source:** Hand-drawn block diagram (Arch 3\) \+ CRPA\_Report Chapter 5–7  
**Date:** June 2026

---

## Overview

Architecture 3 is the **most complete and novel design** in this project. It introduces a dedicated **sensing tap** (directional coupler) on each antenna channel that splits off a copy of the received signal for digital analysis — while the main signal path continues through vector modulators and a Wilkinson combiner to the GPS receiver.

This is the **two-layer closed-loop architecture**:

- **Layer 1 — Analog:** AD8341 vector modulators apply MVDR weights at RF. Jammer cancels at the Wilkinson combiner. GPS receiver sees clean signal.  
- **Layer 2 — Digital:** Directional couplers tap signals before weighting. AD9361 chips (USRP B210) digitize all 4 channels simultaneously. FPGA runs MUSIC \+ MVDR \+ weight generation. Weights fed back to vector modulators via DAC.

The key novelty is that the sensing path (directional couplers → ADCs) is **separate from the GPS path** (vector modulators → combiner → GPS receiver). This means the GPS receiver is never exposed to the ADC conversion — it receives an analog RF signal that has already been spatially filtered.

---

## Block Diagram (Signal Flow)

ANT 1              ANT 2              ANT 3              ANT 4

  |                  |                  |                  |

\[SAW filter\]      \[SAW\]              \[SAW\]              \[SAW\]

  |                  |                  |                  |

\[LNA\]             \[LNA\]             \[LNA\]              \[LNA\]

  |                  |                  |                  |

  ├─ CH1             ├─ CH2             ├─ CH3 (main)      ├─ CH4 (coupled)

  |  (sense)         |  (sense)         |                  |

\[Directional     \[DC\]              \[DC\]               \[DC\]

 Coupler\]        CH2 sense         CH3 main path      CH4 coupled path

  |                  |                  |                  |

  ↓                  ↓                  ↓                  ↓

CH1              CH2              CH3              CH4

sense            sense            sense            sense

  |                  |                  |                  |

  └──────────────────┴──────────────────┴──────────────────┘

                            |

                   ┌────────┴────────┐

                   |                 |

            \[AD9361 / B210\]   \[AD9361 / B210\]

            CH1 \+ CH2         CH3 \+ CH4

                   |                 |

                   └────────┬────────┘

                            |

                         \[GPSDO\]

                     (10 MHz \+ 1 PPS

                      phase-locks both

                      AD9361 chips)

                            |

                          \[FPGA\]

                   ┌────────────────┐

                   | • AOA using    |

                   |   MUSIC        |

                   | • MVDR         |

                   |   Beamforming  |

                   | • Weight       |

                   |   generation   |

                   └───────┬────────┘

                           |

                         \[FPGA\]   ← weight outputs

                           |

                         \[DAC\]

                           |

              ─────────────┼─────────────

              ↓            ↓            ↓            ↓

          \[VM\]          \[VM\]         \[VM\]         \[VM\]

        Vector         Vector       Vector       Vector

        Modulator      Modulator    Modulator    Modulator

        (CH1)          (CH2)        (CH3)        (CH4)

        AD8341         AD8341       AD8341       AD8341

              ↓            ↓            ↓            ↓

              └────────────┴────────────┴────────────┘

                                  |

                      \[4-Way Wilkinson Combiner\]

                                  |

                      \[Directional Coupler\]  ──→  \[Power detector\]

                                  |                       |

                           \[GPS Receiver\]              \[MCU\]

                                  |                       |

                          Position fix              Monitors power,

                                                    controls loop

---

## Stage-by-Stage Description

### Stage 1 — Antenna Array (×4)

Four RHCP patch antennas in a 2×2 URA configuration. Element spacing d \= λ/2 \= 9.5 cm at GPS L1 1575.42 MHz.

Antennas must be mounted on the top face of the UAV enclosure (upward-facing for maximum GPS gain). Minimum ground plane: 190×190 mm. Blade flash multipath from propellers occurs at 100–400 Hz — this is the dominant source of fast-changing multipath in UAV deployments.

### Stage 2 — SAW Filter (×4)

Surface Acoustic Wave bandpass filter at the input of each channel.

| Parameter | Value |
| :---- | :---- |
| Component | Murata SAFEB1G57KE0F00 |
| Center frequency | 1575.42 MHz |
| Bandwidth | \~2 MHz |
| Rejection | \>40 dB out-of-band |
| Purpose | Suppress out-of-band signals before LNA |

SAW filter placed before the LNA ensures out-of-band interferers (cellular, WiFi, etc.) do not compress the LNA.

⚠️ **NF correction:** the pre-LNA SAW's ~1–1.5 dB insertion loss adds dB-for-dB to the system noise figure → real system NF ≈ 2–2.5 dB, not the 0.7 dB used in the original link budget. Nominal unjammed C/N₀ ≈ 43.5–44 dB-Hz (vs 45.3 ideal). Kept deliberately — out-of-band survivability in a hostile RF environment is worth ~1.5 dB.

### Stage 3 — LNA (×4)

Per-channel low noise amplifier.

| Parameter | Value |
| :---- | :---- |
| Component | QPL9547 |
| Gain | \~19.5–20 dB |
| Noise figure | 0.25–0.3 dB (datasheet, 1.9 GHz) |
| Supply | 65 mA bias → \~0.2–0.3 W each; ×4 ≈ 0.86 W (see power note in ARCH\_REVIEW) |
| Frequency | GPS L1 1575.42 MHz (0.1–6 GHz part) |

### Stage 4 — Directional Couplers (×4)

This is the key innovation of Architecture 3\. A directional coupler on each channel splits the signal into:

- **Main path** — continues to the vector modulator for analog null steering  
- **Sense path (coupled port)** — routed to the digital sensing ADCs

Coupling ratio: **−10 dB recommended** (−20 dB leaves ≈ 0 dB net gain ahead of the AD9361 → sense-path NF ~10 dB; harmless for strong jammers but −10 dB buys margin for free)

Main path loss: typically 0.5–1.0 dB (through loss)

The coupled port provides a replica of the received signal before any weighting. This is critical — it preserves the original per-element spatial information that MUSIC needs. The sensing ADCs always see the unweighted raw signals regardless of what the vector modulators are doing.

✅ **Dual use — calibration injection:** the couplers' **isolated ports** double as the injection point for a known L1-band calibration tone into all 4 channels simultaneously. This measures per-channel gain/phase mismatch AND the inter-AD9361 LO phase offset (see Stage 6 correction) with zero additional RF parts. Run at startup and on temperature change. Single highest-value addition to the design (math doc §13.2).

✅ **This solves the Architecture 2 problem.** Architecture 2's RF switch could only look at one channel at a time, destroying coherence for MUSIC. Architecture 3's directional couplers tap all 4 channels simultaneously and continuously — MUSIC always has all 4 coherent channels available.

### Stage 5 — AD9361 / USRP B210 (×2 boards, 4 channels total)

Two USRP B210 boards each containing one AD9361 RF chip with 2 receive channels. Together they digitize all 4 antenna channels.

| Parameter | Value |
| :---- | :---- |
| Chip | AD9361 (on USRP B210) |
| Channels | CH1+CH2 on board 1, CH3+CH4 on board 2 |
| Resolution | 12-bit |
| Sample rate | Up to 61.44 MSPS |
| Frequency range | 70 MHz – 6 GHz |
| Interface | USB 3.0 — requires a USB-3 **host computer/SBC**; a Zynq-7000 has no USB 3.0 |
| Onboard FPGA | **Spartan-6 XC6SLX150** (streaming only — not Artix-7, and not usable for MUSIC/MVDR) |

⚠️ **Tier label:** the dual-B210 + OctoClock stack is the **bench (T1) sensing back-end** for validating the math. It cannot fly (≈ 9–10 W, USB-3 host required, bench clock). The flight back-end is NT1065 or dual AD9361 on a custom carrier (ARCH\_REVIEW\_AND\_HARDWARE.md §4.4).

**Both boards must be phase-coherent** — the GPSDO shared reference is **necessary but NOT sufficient** for this (see Stage 6 correction).

### Stage 6 — GPSDO (GPS-Disciplined Oscillator)

The GPSDO provides a 10 MHz reference clock and 1 PPS signal that phase-locks both AD9361 chips.

GPSDO → 10 MHz reference → both B210 boards

GPSDO → 1 PPS → timestamp alignment

This is the mathematical requirement proven in the simulation: without a shared reference oscillator, each ADC channel accumulates independent phase drift. The drift decorrelates the array covariance matrix, collapsing the eigenvalue gap from 705× to 50× and reducing null depths from 40–56 dB to 19–23 dB.

With the GPSDO shared reference, common-mode phase drift cancels in the covariance:

If x\_m(t) \= x\_m0(t)·exp(jφ(t)) for shared φ(t):

\[x·xᴴ\]\_{ij} \= x\_i0·x\*\_j0·exp(jφ)·exp(−jφ) \= x\_i0·x\*\_j0

The phase term cancels exactly. Null depths recover to 38–56 dB (digital sensing domain).

⚠️ **CORRECTION 1 — shared reference is necessary but NOT sufficient for two AD9361s.** The §9.3 proof covers *common-mode reference drift* only. Each AD9361 synthesizes its RX LO with its **own internal PLL/VCO**: the two boards come up with a **random inter-board LO phase offset at every retune**, and accumulate *differential* phase noise outside the PLL loop bandwidth. Neither is removed by the shared 10 MHz. Untreated, elements {1,2} vs {3,4} carry an unknown rotation e^{jβ} → biased MUSIC, off-target nulls. **Fix:** calibration tone injected via the sense couplers' isolated ports (Stage 4); measure and absorb the per-channel phase/gain into the steering model ã\_m \= g\_m·e^{jγ\_m}·a\_m (math doc §13.2). ADI's own dual-AD9361 board (FMComMS5) requires exactly this.

⚠️ **CORRECTION 2 — a GPSDO cannot discipline while jammed** (it needs GPS lock). What the math actually requires is a **shared** reference, not a GPS-*disciplined* one. Flight design: holdover-grade TCXO/OCXO + 1:4 clock distribution buffer (< 0.1 W). The OctoClock-G is bench (T1) equipment only.

### Stage 7 — FPGA (Digital Intelligence)

The FPGA receives 4-channel digitized IQ data and runs the complete signal processing chain:

**AOA using MUSIC:**

R̂ \= (1/N)·X·Xᴴ               (covariance, N=256 snapshots)

R̂ \= U·Λ·Uᴴ                   (eigendecomposition)

U\_n \= \[u\_{K+1}, ..., u\_M\]     (noise subspace)

P(θ,φ) \= 1/‖UnH·a(θ,φ)‖²     (MUSIC pseudospectrum)

θ̂\_k \= argmax P(θ,φ)           (jammer angles)

**MVDR Beamforming:**

R̂\_dl \= R̂ \+ δ·I               (diagonal loading, δ ≈ 10·σ̂² noise-floor loading — math doc §3.3; NOT λ\_min)

w \= R̂\_dl⁻¹·a(θs) / aH(θs)·R̂\_dl⁻¹·a(θs)   (MVDR weights)

**Weight generation:**

Extract: w \= \[w1, w2, w3, w4\]   (complex weights per element)

Decompose: wi \= Ai·exp(jφi)     (amplitude \+ phase per element)

Quantize: 6-bit phase (5.6° resolution), 6-bit amplitude (1 dB steps)

Output: digital words → DAC → vector modulators

The FPGA runs both the sensing path (MUSIC \+ MVDR) and feeds the weight outputs back to the analog path.

### Stage 8 — DAC

Converts digital weight words from FPGA to analog control voltages for the vector modulators.

DAC output → I/Q control voltages → AD8341 vector modulators

### Stage 9 — Vector Modulators (×4) — AD8341

Four AD8341 vector modulators apply the computed complex weights to the main signal path (not the sensing path). This is the analog null steering layer.

| Parameter | Value |
| :---- | :---- |
| Component | AD8341 |
| Function | Complex weight: wi \= Ai·exp(jφi) |
| Control | I/Q voltage from DAC |
| Frequency range | **1.5–2.4 GHz** (datasheet — the earlier "DC to 2.5 GHz" was wrong) |
| GPS L1 operation | 1575.42 MHz — in band, but only 75 MHz above the lower edge; datasheet typicals are at 1.9 GHz → **bench-characterize at L1** |
| Max gain | **−4.5 dB** (lossy modulator; control range −4.5 to −34.5 dB) — add ~5 dB to GPS-path link budget |
| Supply | \~125 mA @ 5 V ≈ 0.63 W each → **2.5 W for ×4** (dominant power item; T3 swap: passive phase shifter \+ DSA, ARCH\_REVIEW §4.3) |

The AD8341 takes I and Q control inputs and applies the corresponding amplitude and phase shift to the RF signal. By setting all 4 vector modulators correctly, the jammer signals arrive at the Wilkinson combiner with phase differences that cause destructive cancellation.

**Why vector modulators instead of separate phase shifter \+ VGA:** A vector modulator applies amplitude and phase in a single chip — fewer components, better matching, and continuous (DAC-resolution) control instead of 6-bit steps. The AD8341 uses an I/Q modulator topology which inherently provides independent amplitude and phase control from two DC voltages. **Trade-offs (corrected):** it is *not* low-loss (max gain −4.5 dB) and it is *not* low-power (0.63 W each). For the T3 production module the near-zero-DC-power alternative is a passive 6-bit phase shifter \+ 7-bit DSA per channel (ARCH\_REVIEW §4.3) at the cost of stepped resolution.

### Stage 10 — 4-Way Wilkinson Combiner

Sums the 4 weighted element signals. With correct MVDR weights:

- GPS signals from all elements arrive in phase → add constructively (+12 dB for 4 elements)  
- Jammer signals arrive with destructive phase relationships → cancel

y(t) \= Σ wi\* · xi(t) \= wH · x(t)

At optimal weights: |wH·a(θjammer)| → 0, |wH·a(θGPS)| \= 1

### Stage 11 — Directional Coupler (Post-combiner) \+ Power Detector

After the combiner, a directional coupler taps a small fraction of the combined signal to a power detector. The power detector reads the total output power and feeds it to the Zynq PS (the separate MCU is deleted — see Stage 12).

This closes the analog loop — if jammer power is still high at the combiner output, the controller triggers a weight recomputation. **Component note:** the listed AD8318 draws 68 mA @ 5 V ≈ 0.34 W and is an 8 GHz part; the AD8314 (~4.5 mA, covers L1) does this job at 1/15th the power, or duty-cycle the AD8318.

### Stage 12 — MCU *(deleted — absorbed into Zynq PS)*

The docx listed "STM32H74321" (not a real part number; STM32H743ZI is the real part). **Corrected design: no separate MCU.** The Zynq PS (dual Cortex-A9) monitors the power detector, times the weight-update loop, and drives the DAC over SPI — one chip fewer, one firmware fewer, ~0.3 W saved.

### Stage 13 — GPS Receiver

Receives the combined analog RF output from the Wilkinson combiner. Because the vector modulators and combiner have already spatially filtered the signal in the analog domain, the GPS receiver sees a signal where the jammer has been significantly attenuated.

C/N₀ threshold for acquisition: \~33–35 dB-Hz

C/N₀ threshold for tracking:    \~25–28 dB-Hz

Nominal C/N₀ (no jamming):      \~43.5–44 dB-Hz (45.3 ideal − pre-LNA SAW NF, Stage 2)

---

## Signal Equations

### Per-element received signal

x\_i(t) \= s(t)·a\_i(θs,φs) \+ Σk jk(t)·a\_i(θk,φk) \+ n\_i(t)

### Complex weight applied by vector modulator

w\_i \= A\_i · exp(j·φ\_i)

### After Wilkinson combiner

y(t) \= wH · x(t) \= Σ wi\* · xi(t)

### Null depth at jammer direction

null\_depth\_dB \= 20·log10(|wH · a(θjammer)|)

Target: \< −40 dB (jammer suppressed \>40 dB)

### MUSIC pseudospectrum

P\_MUSIC(θ,φ) \= 1 / (aH(θ,φ) · Un · UnH · a(θ,φ))

### MVDR optimal weight

w\_MVDR \= R̂\_dl⁻¹·a(θs) / (aH(θs)·R̂\_dl⁻¹·a(θs))

### Steering vector for 2×2 URA

a(θ,φ) \= a\_y(θ,φ) ⊗ a\_x(θ,φ)

a\_x \= \[1, exp(j·2πd·cos(φ)·cos(θ)/λ)\]ᵀ

a\_y \= \[1, exp(j·2πd·cos(φ)·sin(θ)/λ)\]ᵀ

d \= λ/2 \= 9.5 cm

---

## Key Component Summary

| Block | Component | Purpose |
| :---- | :---- | :---- |
| SAW filter | Murata SAFEB1G57KE0F00 | Out-of-band rejection before LNA |
| LNA | QPL9547 | Low noise 20 dB gain |
| Directional coupler (sense) | 4× — 10-20 dB coupled | Tap for sensing ADC, preserves main path |
| Vector modulator | AD8341 × 4 | Analog complex weight wi \= Ai·exp(jφi) |
| 4-way combiner | Wilkinson | Spatial combining — jammer cancels here |
| Post-combiner coupler | 1× | Feeds power detector |
| Power detector | 1× | Monitors combined output power |
| MCU | *(deleted — Zynq PS Cortex-A9 does this)* | Loop control, DAC interface; the docx's "STM32H74321" is not a real part number (STM32H743ZI is) — but a separate MCU is unnecessary |
| DAC | AD5676 or similar | Weight words → analog control voltages |
| RF SDR | USRP B210 × 2 (AD9361) | 4-channel simultaneous digitization |
| Clock reference | Bench: GPSDO/OctoClock-G; Flight: shared TCXO/OCXO \+ 1:4 buffer | Common reference (necessary); inter-AD9361 LO phase removed by **cal tone**, not by the clock (Stage 6) |
| FPGA | External Zynq-7020 class (the B210's onboard FPGA is a **Spartan-6**, streaming-only) | MUSIC \+ MVDR \+ weight generation |
| GPS receiver | u-blox M9 or similar | Navigation output \+ per-SV C/N₀ logging via UBX (headline KPI) |
| Cal tone source | Zynq PLL output or small synth → coupler isolated ports | Per-channel gain/phase \+ inter-chip LO offset calibration (math doc §13.2) |
| IMU / attitude | ICM-42688 / BMI088 class | Platform attitude \+ almanac → a(θs) for the MVDR constraint (math doc §10.2: GPS is invisible to MUSIC) |
| PIN limiter ×4 | At each antenna port, before SAW | LNA survivability against close-in/high-power jammers |

---

## Key Design Parameters

| Parameter | Value | Notes |
| :---- | :---- | :---- |
| Array | 2×2 URA, RHCP patch | d \= 9.5 cm (λ/2) |
| SAW filter | Murata SAFEB1G57KE0F00 | Before LNA |
| LNA | QPL9547, NF=0.7 dB | Per channel |
| Sensing tap | Directional coupler −10 to −20 dB | All 4 channels simultaneously |
| Vector modulator | AD8341 | Complex weight per element |
| Combiner | 4-way Wilkinson | Analog null steering output |
| SDR | USRP B210 × 2 | 2 channels each, AD9361 |
| Clock | GPSDO → both B210 | Essential for coherence |
| FPGA algorithms | MUSIC \+ MVDR \+ weight gen | Sensing path only |
| Weight resolution | 16-bit DAC → AD8341 (analog I/Q); effective limit \= VM linearity \+ channel mismatch | ~26–36 dB analog ceiling after cal (math doc §6.2); 6-bit figures apply to the T3 stepped-weight variant |
| Null depth (sensing-layer estimate) | 38–56 dB | Digital-domain estimate from MVDR simulation with GPSDO \+ imperfections |
| Null depth (delivered at GPS receiver) | **~26–36 dB** | Capped by the ANALOG weight hardware — the digital path is sensing-only; do not conflate with the row above (ARCH\_REVIEW W3.3) |
| Max simultaneous jammers | 3 (= M−1 \= 4−1) | DOF limit |
| Update rate | \~1 kHz | FPGA → DAC → VM loop |

---

## Comparison With Architectures 1 and 2

| Feature | Arch 1 (Blind Power-Inversion) | Arch 2 (CRC Reference Cancel) | Arch 3 (This) |
| :---- | :---- | :---- | :---- |
| GPS path | Single: all 4 channels weighted then combined | Single: one reference channel selected | Separate: main path (VMs \+ combiner) |
| Sensing path | Same as GPS path (post ADC) | Same path, RF switch selects reference | Dedicated: directional couplers → B210 |
| Simultaneous 4-channel sensing | ❌ No digital sensing — 4 channels exist only in analog; single post-combiner ADC (MUSIC impossible, see arch1.md) | ❌ No (RF switch time-multiplexes) | ✅ Yes |
| Analog weight stage | Phase shifter \+ VGA (6-bit) | Phase shifter \+ VGA on ref chain | AD8341 vector modulator (I/Q) |
| Cancellation method | Pre-combiner spatial weighting | Analog subtraction (hybrid coupler) | Pre-combiner spatial weighting |
| Digital processing | On GPS ADC output | On ADC output (e(t)) | Dedicated sensing ADCs (B210) |
| GPSDO requirement | For per-element phase drift | For shared LO between two chains | For phase-locking two B210 boards |
| GPS receiver input | After ADC | After analog subtractor | Analog RF from Wilkinson combiner |
| Number of ADCs | 1 (post-combiner) | 1 (post-subtractor) | 4 (sensing only, before combining) |
| AGC | Disabled explicitly | Not applicable | Not required (sensing ADC separate) |
| Weight update trigger | Power detector (fast) \+ C/N₀ (slow KPI) | SPLL cross-correlation | FPGA continuous loop \+ power monitor (Zynq PS) |
| Multi-jammer support | Up to 3 (DOF limited) | 1 at a time (RF switch) | Up to 3 (DOF limited) |
| Novel claim | Fast analog null steering | Analog pre-cancellation before ADC | ★ Analog spatial pre-cancel at RF before GPS ADC, simultaneous 4-channel sensing, closed-loop feedback |

---

## Design Flags

### ✅ Directional couplers preserve spatial information correctly

All 4 channels are tapped simultaneously and continuously. MUSIC always sees the full unweighted 4×N IQ data matrix. This is the fundamental improvement over Architecture 2's RF switch approach.

### ⚠️ AD8341 vector modulator — precise but lossy, power-hungry, and at band edge (corrected)

A vector modulator applies complex weight in one chip via I/Q inputs with continuous (DAC-limited) resolution — more precise and better matched than a series phase shifter \+ VGA. **Datasheet corrections:** band is **1.5–2.4 GHz** (not "DC to 2.5 GHz"); L1 sits 75 MHz above the lower band edge with all typicals specified at 1.9 GHz — characterize at 1575.42 MHz before locking. Max gain is **−4.5 dB** (lossy), and 4 devices draw **2.5 W** — the dominant analog power item. Keep for T1/T2; swap to passive phase shifter \+ DSA for the 1.5 W-class T3 module.

### ✅ GPS receiver sees analog RF — not digitized

The GPS receiver input is the analog Wilkinson combiner output. The GPS receiver contains its own ADC (or can use a dedicated high-resolution ADC). The sensing ADCs on the B210 boards are only for the MUSIC/MVDR processing — they do not feed the GPS receiver. This cleanly separates the sensing function from the navigation function.

### ⚠️ Shared clock is necessary but NOT sufficient — inter-AD9361 phase calibration required (corrected)

The shared 10 MHz reference removes *common-mode* drift — the realistic\_sim.py result (eigenvalue gap 50× → 652×, null depths 19–23 dB → 38–56 dB) is real and stands. But each AD9361 generates its RX LO with its own PLL: a **random inter-board phase offset at every retune** plus differential phase noise outside the PLL loop bandwidth survive the shared reference. Without calibration, MUSIC is biased across the board boundary and nulls land off-target. **Fix: cal tone via the sense couplers' isolated ports** (Stage 4, math doc §13.2). Also note a GPSDO cannot discipline *while jammed* — the flight requirement is a shared **holdover** reference (TCXO/OCXO \+ buffer), with the OctoClock-G as bench equipment only.

### ⚠️ 6-bit weight resolution limits null depth ceiling

AD8341 is controlled by I/Q DC voltages from the DAC. If the DAC is 16-bit (AD5676), the vector modulator can be controlled with very fine resolution — the limiting factor is the AD8341's own linearity, not the DAC. This may allow better than 6-bit effective resolution. Characterization needed.

### ⚠️ LO distribution lines must be length-matched

The GPSDO reference is distributed from a single source to both B210 boards. The cables or PCB traces carrying the 10 MHz reference must be equal length. Only common-mode drift cancels — differential drift (from unequal cable lengths) does not cancel and will degrade null depth.

### ⚠️ 4-element array at DOF limit with 3 jammers

M=4 elements gives M−1=3 null DOF. With 3 simultaneous jammers plus the GPS distortionless constraint, there is zero DOF margin. Any DOA estimation error or calibration imperfection causes null degradation. Simulation confirms J3 is marginal at 38 dB (below 40 dB target) under realistic conditions. A 6-element array would give 2 DOF margin.

### ⚠️ Propeller blade flash multipath

On a UAV, the rotating propeller blades cause periodic multipath reflections at 100–400 Hz (depending on RPM). This fast-changing spatial disturbance is not captured by the current simulation which uses static jammer positions. The weight update rate of \~1 kHz is adequate for jammer tracking but the blade flash appears as fast impulsive multipath that can bias the covariance estimate during the integration window.

---

### ❌ Missing items now added to the component summary (were absent from the original BOM)

- **IMU / attitude source** — without it the MVDR constraint direction a(θs) is unimplementable (GPS is invisible to MUSIC; a\_s must come from almanac \+ attitude, math doc §10.2)
- **Calibration injection network** — via sense-coupler isolated ports (Stage 4 / Stage 6 corrections)
- **PIN limiters** on antenna ports — LNA survivability
- Low-noise LDO power tree, RF shielding cans, ESD on antenna ports, anti-alias filters on external sense ADCs (T2/T3) — see ARCH\_REVIEW\_AND\_HARDWARE.md §4.4

---

*End of arch3.md (corrected — Fable review, June 2026).*  
*COGNAV Project | June 2026*  
