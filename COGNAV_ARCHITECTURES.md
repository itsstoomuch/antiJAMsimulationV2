# COGNAV — The Three CRPA Architectures

## GPS L1 Anti-Jamming, 2×2 Array: Architecture Definition Document

**Version 1.1 — June 2026 | Compact reference: block diagram (PNG + ASCII) + math + limitations + strengths per architecture, comparison, conclusion.**

> **Naming map (avoid confusion with repo filenames):** Arch 1 here = `arch1.md` (blind power-inversion). Arch 2 here = `arch3.md` (sensing-tap hybrid). Arch 3 here = the closed-loop product architecture of `plan.md` (COGNAV-P1). Math references (§) point to `COGNAV_MathModelling_v2_CORRECTED.md` v2.1.
> **Diagrams:** `arch1_diagram.png`, `arch2_diagram.png`, `arch3_diagram.png` (regenerate via `gen_arch_diagrams.py`). Color code in all three: **green** = analog GPS path, **blue** = digital sensing, **orange** = control/feedback, **gray** = support, **yellow** = I/O.

---

## 0. Common Foundation (all three architectures)

- **Band:** GPS L1, 1575.42 MHz, C/A bandwidth 2.046 MHz (SAW ~2–4 MHz).
- **Array:** 2×2 URA, RHCP patches, d = λ/2 = 95.1 mm, ground plane ≥ 190×190 mm, upward-facing on the drone's prop-free center.
- **Front end (×4, identical):** PIN limiter → SAW BPF → LNA. System NF ≈ 2–2.5 dB (SAW-first); nominal C/N₀ ≈ 43.5–44 dB-Hz (§10.2).
- **Weight stage (×4):** complex weight w_n = A_n·e^{jφ_n} applied at RF, then **4-way Wilkinson combiner**: y(t) = wᴴx(t). The jammer is cancelled **in the analog domain, before any ADC** — this is the family trait.
- **Signal model (§2):** x(t) = s(t)a(θ_s,φ_s) + Σ_k j_k(t)a(θ_k,φ_k) + n(t); steering a = a_y ⊗ a_x, +j convention; element pattern g = sin(φ_elev).
- **Hard physics shared by all three:**
  - K_max = M−1 = 3 nulls; zero DOF margin at 3 (§5.7). Honest spec: 2 jammers with margin; 3 = demonstrated maximum.
  - Null depth vs steering error: **−20 dB per decade of Δθ** (§5.8).
  - GPS is ~25 dB below the noise floor pre-correlation → **no architecture can "see" GPS spatially**; the GPS direction a(θ_s) comes from almanac + IMU attitude (§10.2).
  - Shared holdover clock (TCXO) required; a GPSDO cannot discipline while jammed (§9.3).
- **What distinguishes the three architectures is exactly one question: *how does the system learn the weights w?***

---

## ARCHITECTURE 1 — Blind Power-Inversion Nulling

*"The array that FEELS the jammer."* One ADC after the combiner; no per-element observation; weights found by trial.

### 1.1 Block diagram

![Architecture 1 — Blind Power-Inversion Nulling](arch1_diagram.png)

```
ANT1..4 → [LIM→SAW→LNA] → [WEIGHT w1..w4] → [Σ WILKINSON] → [BPF→POST-LNA]
                                ↑                  │
                                │                  ├→ [coupler→PWR DET]──┐  (fast trigger, ms)
                                │                  └→ [ADC] → [GPS CORRELATOR → C/N₀]
                                │                                        │  (slow KPI, 0.1–1 s)
                          [FPGA/MCU: dither weight → measure ΔP → gradient step] ◄┘
```

### 1.2 Math

Only the scalar output power is observable: **P(w) = wᴴRw**. The architecture solves

- **Objective:** minimize_w wᴴRw subject to **w₀ = 1** (reference element — NOT the GPS direction)
- **Closed form (if R were known):** w_PI = R⁻¹e₀ / (e₀ᴴR⁻¹e₀) (§13.1)
- **In hardware (R unknown):** iterative — dither w_n by ±Δ, measure ΔP on the power detector, gradient/SPSA step w ← w − µ·∇̂P.

Because jammers dominate R (J/S ≥ 30 dB) and GPS is below noise, minimizing power steers nulls onto jammers without knowing their directions (Compton, *"The Power-Inversion Adaptive Array,"* IEEE Trans. AES, 1979).

**Optional covariance reconstruction:** R̂ (16 real DOF) recovered from ≥16 probe-weight power readings Pᵢ = vec(wᵢwᵢᴴ)ᴴ·vec(R) — restores MUSIC/MVDR offline at the cost of L dwell periods and reconstruction variance (§13.1b).

### 1.3 Limitations

1. **No DOA knowledge** — cannot report jammer bearings; cannot verify which direction was nulled.
2. **Slow convergence** — many probe-measure cycles per update; weak against swept/agile jammers.
3. **No GPS distortionless constraint** — w₀ = 1 protects element 0, not θ_s → GPS gain ripple vs geometry.
4. **ADC takes the full jammer during re-convergence** — must be sized for α = 0 (§6.4).
5. C/N₀-only triggering reacts after damage — needs the fast power-detector trigger.
6. Multi-jammer (K = 2–3) blind convergence is fragile (local minima in a 3-null search).

### 1.4 Strengths

- Simplest, cheapest, lowest power (1 ADC, no sensing receiver).
- Intrinsically immune to inter-channel LO problems (single downconversion chain).
- Always functional — ideal as a **fallback mode**.

---

## ARCHITECTURE 2 — Sensing-Tap Hybrid (open-loop MUSIC + MVDR)

*"The array that SEES the jammer."* Directional couplers tap all 4 elements before weighting; a dedicated 4-channel coherent receiver digitizes the unweighted signals; the FPGA computes jammer DOAs and the exact weights in one shot.

### 2.1 Block diagram

![Architecture 2 — Sensing-Tap Hybrid (open-loop MUSIC + MVDR)](arch2_diagram.png)

```
ANT1..4 → [LIM→SAW→LNA] → [COUPLER −10dB] → [WEIGHT w1..w4] → [Σ WILKINSON] ─┬→ [POST-LNA → SMA RF OUT]
                              │ sense ×4  ↑                                   ├→ [u-blox RX → UART NMEA]
                              │ (isolated ports ← CAL TONE)                   └→ [coupler→PWR DET → monitor ONLY]
                              ▼           │
                  [4-CH COHERENT RX (single LO)] → [FPGA: R̂ → MUSIC → MVDR] → [DAC] ─┘
                          ↑ shared TCXO                 ↑ IMU + almanac → a(θs)
```

### 2.2 Math

The sense path delivers true 4-channel snapshots X ∈ ℂ^{4×N}:

- **Covariance:** R̂ = XXᴴ/N, diagonal loading δ ≈ 10σ̂² (§3)
- **MUSIC:** P(θ,φ) = 1/‖U_nᴴa(θ,φ)‖² → jammer DOAs to sub-degree accuracy (§4)
- **MVDR (one shot):** **w = R̂_dl⁻¹a(θ_s) / (a(θ_s)ᴴR̂_dl⁻¹a(θ_s))** — distortionless at the GPS direction (§5)
- Weights → DAC → vector modulators. **Open loop: computed, written, done — until the next epoch.**
- **Calibration (mandatory):** cal tone via coupler isolated ports → q_m = ĥ_m/ĥ₀ absorbs channel mismatch and inter-chip LO offset into ã_m = q_m·a_m (§13.2). Without it, σ_phase = 5° mismatch collapses nulls to 20–27 dB (§9.1). Dual-chip front ends (2× AD9361) require cal at every retune; single-LO front ends (NT1065-class) avoid the inter-chip term by construction.

### 2.3 Limitations

1. **Open-loop accuracy ceiling:** delivered null depth is set by how exactly the *computed* weight is *realized* in analog hardware — VM linearity, DAC-to-RF transfer error, cal residue, temperature drift. Practically **~26–36 dB**, regardless of how good MVDR is digitally. The 38–56 dB simulation figures are *sensing-layer estimates*, not delivered nulls.
2. **No self-correction:** any drift after the weight write goes unnoticed until the next full re-solve; the power detector only *monitors*, it does not *steer*.
3. Cost/power of the sensing chain (4 coherent channels + FPGA) — the price of observability.
4. Dual-chip sensing receivers need the §13.2 cal at every retune.
5. Zero DOF margin at K = 3 (shared trait).

### 2.4 Strengths

- Sub-degree jammer DOA — reportable telemetry.
- One-shot convergence (~one covariance epoch + DAC write).
- Native multi-jammer handling; full spatial observability for diagnostics and the research paper.

---

## ARCHITECTURE 3 — Closed-Loop Hybrid (MVDR aim + power-detector trim) — COGNAV-P1

*"The array that sees, aims, and then polishes."* Arch 2's sensing brain **plus** Arch 1's power-feedback used as a *fine-trim loop around the MVDR solution*. This is the product architecture: it makes full use of analog nulling by closing the loop around every analog imperfection at once.

### 3.1 Block diagram

![Architecture 3 — Closed-Loop Hybrid (COGNAV-P1)](arch3_diagram.png)

```
ANT1..4 → [LIM→SAW→LNA] → [CPLR −10dB] → [AD8341 VM ×4] → [Σ WILKINSON] ─┬→ [POST-LNA → SMA CLEAN L1 OUT]
                             │ sense ×4      ↑ continuous I/Q             ├→ [u-blox M10 → UART NMEA+C/N₀]
                             │ (cal tone ↗)  │ (16-bit DAC)               └→ [CPLR → AD8314 PWR DET]──┐
                             ▼               │                                                        │
            [4-CH COHERENT RX] → [FPGA:  R̂ → MUSIC → MVDR  ──→  TRIM LOOP (dither ∂P/∂w) ←──────────┘
                  ↑ shared TCXO           cal FSM | PI-fallback | IMU+almanac → a(θs)]
                                                  └→ [AD5676 DAC] → VMs
```

(Part-level version with the full drone-prototype detail: `cognav_p1_block_diagram.png`.)

### 3.2 Math — the three-stage weight law

**Stage 1 — AIM (Arch 2 math):**

w⁰ = R̂_dl⁻¹a(θ_s) / (a(θ_s)ᴴR̂_dl⁻¹a(θ_s)) — MVDR from the calibrated sense path (§5.2, §13.2).

**Stage 2 — TRIM (Arch 1 math, re-purposed):** the power detector measures the *actual* residual P(w) = wᴴRw at the combiner. Starting from w⁰ (already near the minimum), perform constrained dither descent:

w^{k+1} = w^k − µ·∇̂P(w^k),  projected onto wᴴa(θ_s) = 1 after each step

Because w⁰ is already inside the convergence basin, this is a **polish, not a search** — it cancels, in one loop, every error between the computed and realized weight: VM nonlinearity, DAC transfer error, cal residue, temperature drift, and the §5.8 penalty of small DOA error. Expected gain over open-loop: **+5–10 dB** (simulation task S-1, plan.md). Steady-state floor:

null_floor ≈ 20·log₁₀(Δ_dither · |∂(wᴴa_j)/∂w|) — the §5.8 law in weight space (§13.1 [DERIVE] closes the optimal Δ).

**Stage 3 — SUPERVISE:** trim runs continuously at low rate; full MVDR re-solve fires on events — power-detector jump (new jammer / bearing change), MUSIC sees jammer motion > 0.5°, temperature step (→ recal). Re-null < 100 ms. If the sensing chain faults, the system degrades to pure Arch 1 (power inversion, w₀ = 1) instead of failing — **graceful degradation is built into the math, not bolted on.**

**Why the weights can be this good:** AD8341 VMs are driven by a 16-bit DAC → weight quantization (ε_φ², ε_A² in §6.2) effectively vanishes; the ceiling moves to VM linearity + mismatch — exactly the errors the trim loop removes.

**Performance targets:** ≥ 35 dB delivered null (1 jammer), ≥ 30 dB (2), ≥ 25 dB (3); stacked JSR ≥ 85 dB with the downstream receiver (§10.3 Betz budget); re-null < 100 ms; ≤ 8 W.

### 3.3 Limitations

1. **Trim needs a quasi-static residual** — a jammer sweeping faster than the trim rate is handled by MVDR re-solves alone (falls back to Arch 2 performance, ~26–36 dB, until quasi-static again).
2. **Single scalar feedback:** the detector measures *total* residual power — with multiple jammers the trim improves the *sum*, not each null individually; per-null verification still comes from the sensing layer.
3. Most complex of the three (two feedback loops + cal FSM); loop-interaction stability must be designed (trim only when detector quasi-static; MVDR owns dynamics).
4. AD8341 at its 1.5–2.4 GHz band edge at L1 (typicals at 1.9 GHz) — characterize before tape-out; 2.5 W for 4 VMs dominates the analog power budget (passive-weight variant is the production power-down path, at the cost of stepped weights).
5. Zero DOF margin at K = 3; trim cannot create degrees of freedom (shared trait).

### 3.4 Strengths

- Deepest delivered analog nulls of the three; drift-immune by construction.
- Self-verifying: power detector + embedded-receiver C/N₀ both confirm the null.
- Jammer-bearing telemetry from the integrated MUSIC layer.
- Clean RF output usable by any downstream GPS receiver (active-antenna emulation).
- Built-in fallback: contains Arch 2 (trim off) and Arch 1 (sensing off) as degraded operating states.

---

## Comparison

| | **Arch 1** — Power Inversion | **Arch 2** — Sensing Hybrid | **Arch 3** — Closed-Loop Hybrid |
| :-- | :-- | :-- | :-- |
| Learns weights by | trial (dither on output power) | computation (MUSIC+MVDR, open loop) | computation + feedback polish |
| Per-element digitization | ❌ none (1 ADC) | ✅ 4-ch sense tap | ✅ 4-ch sense tap |
| Jammer DOA / telemetry | ❌ | ✅ sub-degree | ✅ sub-degree |
| GPS constraint | w₀=1 (ripple) | distortionless at a(θs) | distortionless at a(θs), held by trim |
| Convergence | slow (many cycles) | one shot (~1 epoch) | one shot + continuous polish |
| Delivered null (realistic) | ~26–31 dB, fragile multi-jammer | ~26–36 dB (open-loop ceiling) | **≥35 dB target**, drift-immune |
| Drift handling | implicit (always searching) | none until next solve | explicit (trim loop) |
| Hardware cost / power | lowest | high (sensing chain) | high + detector loop (≤8 W flight) |
| Failure behavior | — (is the simplest mode) | weights freeze stale | degrades to Arch 2 → Arch 1 → frozen |
| Role in COGNAV | **fallback mode** of Arch 3 | **research baseline** + sensing layer of Arch 3 | **the product (COGNAV-P1)** |

---

## Conclusion

The three architectures are one family answering a single question — *how do we learn the weights* — with increasing intelligence:

- **Arch 1 FEELS** — blind power minimization on a single output: robust, simple, always functional, but slow, unobservable, and unable to protect the GPS direction explicitly.
- **Arch 2 SEES** — computes exact weights from 4-channel coherent sensing: fast (one-shot MVDR), observable (sub-degree jammer bearings), but **open-loop** — component imperfection caps the delivered null at ~26–36 dB no matter how good the math is.
- **Arch 3 SEES, AIMS, AND POLISHES** — MVDR provides the aim, the power-detector trim loop closes around every analog imperfection at once, and calibration ties the digital model to the analog reality. Its delivered null depth is limited by physics (detector noise, DOA error), not by component tolerance.

**Arch 3 is the build target (COGNAV-P1, plan.md)** — and not only on performance. It *contains* the other two: Arch 2 is its sensing layer running open-loop, and Arch 1 is its fallback mode when the sensing chain faults. One hardware platform therefore demonstrates all three architectures, which is simultaneously the strongest engineering choice (graceful degradation instead of failure) and the strongest research narrative (a controlled A/B/C comparison of three weight-learning strategies on identical hardware, identical array, identical RF chain — the only variable is the intelligence).

---

*COGNAV_ARCHITECTURES.md v1.1 — companion to plan.md, COGNAV_MathModelling_v2_CORRECTED.md (math §refs), ARCH_REVIEW_AND_HARDWARE.md (BOM), diagrams arch1/2/3_diagram.png + cognav_p1_block_diagram.png.*
*COGNAV Project | June 2026*
