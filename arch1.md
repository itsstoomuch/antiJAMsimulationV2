# Architecture 1 — Blind Analog Nulling (Power-Inversion CRPA)
## COGNAV-4 CRPA Anti-Jamming System | GPS L1 1575.42 MHz

**Status:** Corrected (Fable review) — companion analysis in ARCH_REVIEW_AND_HARDWARE.md  
**Source:** Hand-drawn block diagram (Arch 1) — originally titled "Dedicated Sensing Mode"; renamed because with a single post-combiner ADC this architecture has **no per-element sensing** (see Limitations)  
**Date:** June 2026

---

## Overview

Architecture 1 is a **blind analog nulling** design (power-inversion adaptive array). All four antenna channels pass through independent analog weighting stages (phase shifter + VGA) before being combined. The combined signal then travels through a single RF chain to the ADC. Because only the combined output is digitized, the FPGA/MCU **cannot observe per-element data and cannot run MUSIC directly** — it adapts the weights by minimizing the measured output power (power inversion, Compton 1979), optionally reconstructing the spatial covariance from ≥16 weight-probe power measurements (math doc §13.1). Control words are fed back via two SPI buses — one for phase (SPI φ) and one for attenuation (SPI A). The GPS correlator's C/N₀ acts as the slow outer KPI loop; a fast post-combiner power detector (recommended addition, as in Arch 3) is the ms-scale update trigger.

The key characteristic of this architecture is that the **analog pre-cancellation happens before the combiner**, and the **single ADC path is shared** between the sensing function and the GPS output. AGC is explicitly disabled to prevent the automatic gain control from fighting the adaptive weighting loop.

---

## Block Diagram (Signal Flow)

```
ANT 1          ANT 2          ANT 3          ANT 4
  |              |              |              |
[LNA]          [LNA]          [LNA]          [LNA]
  |              |              |              |
[Phase        [Phase        [Phase        [Phase
 Shifter]      Shifter]      Shifter]      Shifter]
  |    ↑          |    ↑          |    ↑          |    ↑
  |    └──────────┴──────────────┴──────────────┘
  |             SPI φ (phase words from FPGA/MCU)
[VGA]          [VGA]          [VGA]          [VGA]
  |    ↑          |    ↑          |    ↑          |    ↑
  |    └──────────┴──────────────┴──────────────┘
  |             SPI A (attenuation words from FPGA/MCU)
  └──────────────┴──────────────┴──────────────┘
                        |
               [Wilkinson Combiner]
                        |
                      [BPF]
                        |
                  [Post LNA]   ← (Post-combiner amplifier)
                        |
               [Down Converter]
                        |
                      [ADC]
                        |
              [GPS Correlator + C/N₀ monitor]
                        |
                  GPS position fix
                        |
              ──────────┴──────────
              (C/N₀ feedback trigger)
                        |
                  ┌─────▼──────┐
                  │  FPGA/MCU  │
                  │            │
                  │  Power     │
                  │  inversion │
                  │            │
                  │  Weight    │
                  │  search    │
                  │            │
                  │  SPI φ ────┼──→ Phase shifters
                  │  words     │
                  │            │
                  │  SPI A ────┼──→ VGAs (attenuation)
                  │  attenua-  │
                  │  tion      │
                  │            │
                  │  AGC ──────┼──→ Down converter
                  │  disable   │    (disables hardware AGC)
                  │            │
                  │  ADC ──────┼──→ ADC configuration
                  │  config    │
                  │            │
                  │  C/N₀ ─────┼──← GPS correlator
                  │  trigger   │    (triggers weight update)
                  └────────────┘
```

---

## Stage-by-Stage Description

### Stage 1 — Antenna Array (×4)

Four receive antennas in a 2×2 URA layout. Element spacing d = λ/2 = 9.5 cm at GPS L1.

Each antenna feeds its own independent processing chain. All four chains operate simultaneously — there is no RF switching or time-multiplexing between elements. This is critical: simultaneous sampling of all four elements is required for MUSIC and MVDR to work correctly.

### Stage 2 — LNA (×4)

Low noise amplifier per channel. Amplifies the received signal before any splitting or processing.

| Parameter | Value |
|-----------|-------|
| Gain | ~20 dB |
| Noise figure | ~0.7 dB |
| Frequency | GPS L1 1575.42 MHz |

### Stage 3 — Phase Shifter (×4)

Digitally controlled phase shifter on each channel. Receives phase control word from FPGA via **SPI φ bus**.

| Parameter | Value |
|-----------|-------|
| Control | SPI words from FPGA/MCU |
| Resolution | 6-bit (Δφ = 5.6°) |
| Function | Adjusts per-element phase to steer null toward jammer |

The phase shifter applies the complex phase component of the MVDR weight:

```
w_n = A_n · exp(j·φ_n)
```

where φ_n is set by the SPI φ word for element n.

### Stage 4 — VGA (×4)

Variable gain amplifier per channel. Receives attenuation control word from FPGA via **SPI A bus**.

| Parameter | Value |
|-----------|-------|
| Control | SPI attenuation words from FPGA/MCU |
| Resolution | 6-bit amplitude (1 dB steps) |
| Function | Adjusts per-element amplitude to complete complex weight |

The VGA applies the amplitude component A_n of the MVDR weight w_n.

### Stage 5 — Wilkinson Combiner

4-way power combiner that sums the four weighted element signals. With optimal weights applied, the jammer signals from different elements arrive with opposite phases and cancel at the combiner output. The GPS signals from different elements arrive coherently and add constructively.

```
y_combined(t) = Σ_{n=0}^{3} w_n* · x_n(t)
```

When w = w_MVDR: jammer cancels, GPS preserved.

**Insertion loss (corrected):** for **coherent** inputs an ideal 4-way Wilkinson *combiner* is lossless — the "6 dB" figure applies to power *splitting* or incoherent inputs. Real-world excess loss ≈ 0.5–1 dB. The Post LNA is justified by the downconverter noise figure, not by a 6 dB combiner loss.

### Stage 6 — BPF (Bandpass Filter)

Post-combiner bandpass filter centered at GPS L1. Removes out-of-band interference and image products before down-conversion.

| Parameter | Value |
|-----------|-------|
| Center frequency | 1575.42 MHz |
| Bandwidth | ~4 MHz (C/A main lobe = 2.046 MHz, plus margin) |
| Rejection | >40 dB out-of-band |

### Stage 7 — Post LNA

Post-combiner amplifier to compensate for combiner insertion loss and maintain adequate signal level for the down converter. This is separate from the per-element LNAs in Stage 2.

### Stage 8 — Down Converter

Mixes the combined GPS L1 signal down to IF (intermediate frequency) or baseband for ADC sampling.

**AGC disable control:** The FPGA sends an explicit AGC disable command to the down converter. This is essential — if the hardware AGC were enabled, it would automatically increase gain when the adaptive weighting reduces signal power, fighting against the null steering and causing instability in the weight update loop.

### Stage 9 — ADC

Single ADC digitizes the combined signal after analog pre-cancellation. Once converged, the analog nulls protect the ADC from saturation.

**Headroom spec (corrected):** at jammer turn-on, or whenever the jammer moves faster than the update loop, the weights are stale and the ADC sees the **full unweighted jammer**. Size the ADC full-scale for the α = 0 worst case (math doc §6.4), not the converged case.

| Parameter | Value |
|-----------|-------|
| Resolution | 12–14 bit |
| Sample rate | 61.44 MSPS |
| AGC | Disabled (controlled by FPGA) |
| Config | Set via ADC config SPI from FPGA |

### Stage 10 — GPS Correlator + C/N₀ Monitor

Performs GPS C/A code correlation to extract navigation data. Continuously monitors C/N₀ (carrier-to-noise density ratio).

```
C/N₀ threshold for acquisition: ~33–35 dB-Hz
C/N₀ threshold for tracking:    ~25–28 dB-Hz
Nominal C/N₀ (no jamming):      ~45 dB-Hz
```

The C/N₀ monitor feeds back to the FPGA via the **C/N₀ trigger** signal. When C/N₀ drops below threshold, it triggers a weight update cycle. This makes the system **event-driven** — weights are updated when performance degrades, not on a fixed timer.

**Correction — C/N₀ alone is too slow as the primary trigger:** a meaningful C/N₀ estimate needs ~0.1–1 s of correlator integration, so it fires *after* tracking is already stressed. Add a post-combiner directional coupler + power detector (as in Arch 3) as the fast ms-scale trigger; keep C/N₀ as the slow outer KPI loop.

### Stage 11 — FPGA/MCU (Control and Processing)

The FPGA/MCU runs the adaptation and control loop. It has the following functional blocks:

| Block | Function |
|-------|----------|
| Power-inversion search | Adapts weights to minimize combined output power, subject to w₀ = 1 on the reference element. Strong jammers dominate output power, so minimizing it steers nulls onto them; GPS (25 dB below noise) is unaffected |
| Covariance reconstruction (optional) | Recovers the 4×4 R̂ from ≥16 weight-probe power readings Pᵢ = wᵢᴴ·R̂·wᵢ, enabling offline MUSIC/MVDR (math doc §13.1) — slow, GPS coasts on its PLL during probing |
| SPI φ words | Serializes phase weights and sends to phase shifters via SPI |
| SPI attenuation | Serializes amplitude weights and sends to VGAs via SPI |
| AGC disable | Disables hardware AGC in the down converter |
| ADC config | Configures ADC sample rate, gain, offset |
| C/N₀ trigger | Receives C/N₀ from correlator, triggers weight update when below threshold |

**Processing chain inside FPGA:**

```
Output power estimate P_out (power detector or ADC power)
   ↓
MODE A — Power inversion (default, fast):
   perturb weight w_n (dither ±Δ) → measure ΔP_out
   gradient step: w ← w − µ·∇̂P   subject to w₀ = 1
   repeat until P_out at minimum (nulls on strong jammers)
   ↓
MODE B — Covariance reconstruction (optional, slow):
   apply ≥16 known probe weights wᵢ → record Pᵢ = wᵢᴴ·R̂·wᵢ
   solve the linear system for the 16 real DOF of R̂
   run MUSIC + MVDR on the reconstructed R̂ (math doc §13.1)
   ↓
Extract phase φn and amplitude An from w
   ↓
Quantize to 6-bit SPI words
   ↓
Send via SPI φ → phase shifters
Send via SPI A → VGAs

⚠️ CORRECTION: the earlier draft showed `snapshot buffer → R̂ = XXᴴ/N →
eigendecomposition → MUSIC → MVDR` here. That chain is IMPOSSIBLE in this
architecture: the single post-combiner ADC yields 1×N data, so R̂ is a
scalar — no 4×4 covariance, no noise subspace, no MUSIC, no a(θs)-
constrained MVDR. Direct MUSIC requires the Arch 3 sensing tap.
Reference: R. T. Compton, "The Power-Inversion Adaptive Array,"
IEEE Trans. Aerospace and Electronic Systems, 1979.
```

---

## Signal Equations

### Received signal per element

```
x_n(t) = s(t)·a_n(θs,φs) + Σk jk(t)·a_n(θk,φk) + n_n(t)
```

### After per-element weighting

```
x_n_weighted(t) = w_n* · x_n(t)    where w_n = A_n · exp(j·φ_n)
```

### After Wilkinson combiner

```
y(t) = Σ_{n=0}^{3} w_n* · x_n(t) = wH · x(t)
```

### Null condition

```
|wH · a(θjammer)| → 0    (jammer cancelled)
|wH · a(θGPS)|   = 1     (GPS preserved — distortionless constraint)
```

### Residual jammer at ADC (after analog cancellation)

```
P_jammer_at_ADC = P_jammer_in · (1 − α)²
```

Where α is the effective cancellation fraction (≤ 0.9 for 6-bit phase resolution).

### ADC headroom gain

```
Δ_analog = −20·log10(1 − α) dB
```

For α = 0.9: Δ_analog = 20 dB (jammer 20 dB weaker at ADC input)

### C/N₀ after beamforming

```
C/N₀_post = C/N₀_pre + null_depth_dB − jammer_contribution_dB
```

---

## Key Design Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Array | 2×2 URA | 4 elements, simultaneous sampling |
| Element spacing | 9.5 cm (λ/2) | GPS L1 |
| Phase shifter bits | 6 | Δφ = 5.6°; null ceiling 26 dB worst-case / ~31 dB RMS (math doc §6.2) |
| Amplitude bits | 6 | 1 dB steps |
| Combiner type | Wilkinson 4-way | ~6 dB insertion loss |
| ADC resolution | 12–14 bit | AGC disabled |
| AGC | Explicitly disabled | Prevents fighting adaptive loop |
| Update trigger | C/N₀ drop | Event-driven, not fixed-rate |
| SPI buses | 2 (φ and A) | Separate phase and amplitude control |
| GPS output | C/N₀ monitored | Position fix from correlator |

---

## Limitations and Design Flags

### ❌ Single ADC path — MUSIC is impossible in this architecture

This architecture digitizes only the combined output: X is 1×N and R̂ is a scalar. There is no 4×4 covariance, no noise subspace, and therefore **no direct MUSIC and no a(θs)-constrained MVDR**. Consequences:
- Jammer DOA is not directly observable — adaptation must be blind (power inversion) or use slow ≥16-probe covariance reconstruction (math doc §13.1)
- During re-convergence (stale weights), the ADC sees the full unweighted jammer — size FS for α = 0
- No per-element algorithms are possible after the combiner
- The GPS distortionless constraint cannot be applied exactly: power inversion uses a reference-element constraint (w₀ = 1) instead, which costs a small GPS gain ripple (math doc §13.1)

### ⚠️ 6-bit weight resolution limits null depth

Phase resolution Δφ = 2π/64 = 5.6° limits the achievable null depth to ~26 dB worst-case / ~31 dB RMS (math doc §6.2: C_dB ≈ −10·log₁₀(ε_A² + ε_φ²)). The earlier "~36 dB" figure was optimistic. Each extra bit of phase resolution buys ~6 dB; for the >40 dB target, 8-bit weights (Δφ = 1.4°, ~38–43 dB ceiling) are the minimum, and channel mismatch must also be calibrated.

### ⚠️ C/N₀ triggered updates — latency on fast jammers

The weight update is triggered by C/N₀ degradation. For a fast frequency-hopping jammer, C/N₀ may drop before the FPGA has time to recompute and apply new weights. This is acceptable for slow CW jammers but may be insufficient for FMCW or fast barrage jammers. On top of this, blind power-inversion convergence itself takes many probe-measure cycles — Arch 1 is structurally slower than Arch 3's one-shot MVDR. **Mitigation:** fast power-detector trigger (see Stage 10 correction) + dither loop running continuously rather than waiting for the trigger.

### ✅ AGC disable — correct design choice

Explicitly disabling hardware AGC is the right approach. Hardware AGC would increase gain when the adaptive null reduces jammer power, counteracting the null and causing loop instability. The FPGA controls gain explicitly through the SPI attenuation words.

### ✅ Simultaneous 4-channel sampling (before combiner)

All four channels are processed simultaneously before the combiner. This preserves the inter-element phase relationships that MUSIC and MVDR require. The RF switching approach (used in earlier CRC diagram) would destroy this — Architecture 1 correctly avoids time-multiplexing.

---

## Comparison With Architecture 3

Full comparison and shared-hardware recommendation in **ARCH_REVIEW_AND_HARDWARE.md** (Part 1). Summary:

| Feature | Architecture 1 (this) | Architecture 3 |
|---------|---------------|----------------|
| Per-element digital data | ❌ none (1 ADC, post-combiner) | ✅ 4 coherent sense channels |
| Jammer DOA | Not directly observable | MUSIC, sub-degree |
| Weight computation | Blind power-inversion search | Closed-form MVDR, one shot |
| Convergence | Slow (many probe cycles) | Fast (~1 covariance epoch) |
| AGC | Disabled (FPGA-controlled) | Not required on GPS path; AGC allowed on sense ADCs |
| Update trigger | Power detector (fast) + C/N₀ (slow KPI) | Continuous FPGA loop + power monitor |
| Power / complexity | Lowest | Highest |

**Relationship:** Arch 1 = Arch 3 with the sensing path disabled. Recommended build: one Arch 3 board; run Arch 1 as its degraded/fallback mode and as the A/B baseline for the paper.

---

*End of arch1.md (corrected).*  
*COGNAV Project | June 2026*