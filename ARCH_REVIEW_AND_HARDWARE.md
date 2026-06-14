# COGNAV-4 — Architecture Review, Math-Model Mapping, and Hardware Audit

**Version 1.0 — June 2026 (Fable review)**
**Inputs: arch1.md, arch3.md, COGNAV_MathModelling_v2_CORRECTED.md, components_arch3.docx**
**Targets: professional-grade drone-mounted CRPA, power goal 1.5 W, FPGA candidate "Z-turn 7035"**

---

## Part 1 — The two architectures in one sentence each

- **Arch 1 — "the array that FEELS the jammer":** weights at RF → combine → **one** ADC after the combiner. The system never sees the individual antennas digitally; it adapts weights by watching a single output power / C/N₀ number go down or up. Blind, simple, low power, slow.
- **Arch 3 — "the array that SEES the jammer":** same RF weighting + combiner for the GPS path, **plus** a directional-coupler tap on every element feeding a 4-channel coherent digitizer. The FPGA computes the jammer directions (MUSIC) and the exact weights (MVDR) in one shot and writes them to the vector modulators. Observable, fast, publishable — at the cost of 4 extra receive chains.

| | Arch 1 | Arch 3 |
| :-- | :-- | :-- |
| Per-element digital data | ❌ none (1 ADC, post-combiner) | ✅ 4 coherent channels (sense tap) |
| Jammer DOA knowledge | ❌ not directly observable | ✅ MUSIC, sub-degree |
| Weight computation | Iterative search / power inversion | Closed-form MVDR, one shot |
| Convergence after jammer appears | Slow (many probe-measure cycles) | Fast (~1 covariance epoch + DAC write) |
| Multi-jammer (K=2–3) | Hard to converge blindly | Native (DOF-limited at 3) |
| Moving / frequency-agile jammer | Weak (trigger + search latency) | Good (continuous re-estimation) |
| GPS receiver input | Analog combiner output | Analog combiner output (same) |
| Null depth ceiling | Analog weight resolution (~26–36 dB) | Same ceiling — sensing improves *steering accuracy*, not the analog quantization floor |
| Power / size / cost | Lowest | Highest (4 RX chains + FPGA load) |
| Failure visibility | Only "C/N₀ dropped" | Full spatial picture, logged KPIs |
| Research novelty | Low (Compton power-inversion array, 1979) | High (your hybrid sensing-tap contribution) |

**Both share:** identical antenna array, SAW+LNA front end, analog weighting, Wilkinson combiner, GPS receiver, and the same final-null-depth physics. Arch 3 ⊃ Arch 1: if you build Arch 3 and switch the sensing path off, you have Arch 1. **Strong recommendation: design ONE board = Arch 3, with Arch 1 as its degraded/fallback operating mode.** That gives you both architectures for the paper with one hardware spin, and a genuinely useful selling point (sensing chain dies → system degrades to power-inversion instead of failing).

---

## Part 2 — Weaknesses and fixes, per architecture

### Arch 1 — critical internal contradiction (must fix the document)

**W1.1 — MUSIC/MVDR cannot run as written. This is fatal as documented.** arch1.md Stage 11 shows `snapshot buffer → R̂ = XXᴴ/N → eigendecomposition → MUSIC → MVDR` — but the only digitized signal is the **single combined output**. X is 1×N, R̂ is a 1×1 scalar. There is no 4×4 covariance, no noise subspace, no MUSIC, and no a(θ_s)-constrained MVDR. That processing chain was copy-pasted from a 4-channel design. Two honest ways to make Arch 1 work:

- **(a) Power-inversion adaptive array (recommended, classic):** drop DOA entirely. Adapt w to minimize output power subject to a unity reference-element constraint (w₀ = 1). Strong jammers dominate output power, so minimizing power ≈ steering nulls onto jammers; GPS is 25 dB below noise and is untouched by the minimization. Gradient is estimated by **dithering** the weights (perturb one weight, read the power detector, SPSA/coordinate descent). No knowledge of a_s needed. Reference: Compton, *"The Power-Inversion Adaptive Array"*, IEEE Trans. AES 1979.
- **(b) Covariance reconstruction by weight probing (keeps MUSIC):** R̂ (4×4 Hermitian) has 16 real degrees of freedom. Each setting of the analog weights gives one scalar measurement P_i = w_iᴴ·R̂·w_i. Apply ≥16 linearly independent probe patterns, solve the linear system for R̂'s entries, then run MUSIC + MVDR on the reconstructed R̂. Cost: 16+ dwell intervals per update (slow), extra estimation variance, and during probing the GPS path is being deliberately mis-weighted — GPS tracking must coast on its PLL during a probe burst.

**W1.2 — C/N₀-triggered updates react after the damage.** A meaningful C/N₀ estimate needs ~0.1–1 s of correlator integration; by the time the trigger fires, tracking is already stressed, and during the (slow, see W1.1) blind re-convergence it may be lost entirely. Fix: add the **post-combiner power detector from Arch 3** as the fast trigger (ms-scale) and keep C/N₀ as the outer KPI loop. This costs one coupler + one detector and removes Arch 1's worst latency.

**W1.3 — ADC sees the full jammer before convergence.** After convergence the null protects the ADC, but at jammer turn-on (weights stale) the single ADC takes the full J/S hit. Spec the ADC headroom for the **unweighted** worst case (math doc §6.4 with α = 0), not the converged case.

**W1.4 — minor corrections to arch1.md:**
- "Wilkinson insertion loss ~6 dB" — for **coherent** signals a 4-way Wilkinson *combiner* is ideally lossless (the 6 dB figure is per-port splitting loss / incoherent inputs). Real excess loss ≈ 0.5–1 dB. The Post-LNA is still justified, but by NF of the downconverter, not by "6 dB."
- BPF bandwidth "4 MHz = 2 × chip rate": fine, but state C/A main lobe = 2.046 MHz explicitly.
- The phase-shifter table says null ceiling "~36 dB" — use the v2 math doc §6.2 numbers consistently: 6-bit phase ⟹ 26 dB worst-case, ~31 dB RMS; amplitude error makes it slightly worse. "36 dB" is optimistic.

### Arch 3 — strong concept, four real problems

**W3.1 — The B210 ×2 + OctoClock sensing back-end is lab equipment, not an architecture.** Verified facts: B210's FPGA is a **Spartan-6 XC6SLX150** (arch3.md says "Artix-7" — wrong); it is USB-3.0 bus-powered and **requires a USB-3 host computer** running UHD — and a Zynq-7000 has **no USB 3.0**, so your Z-turn cannot host them properly (USB 2.0 caps usable rate and adds latency). Two B210s ≈ 9–10 W, OctoClock-G is a mains/bench-supplied distribution box. This stack is **fine for Phase-1 bench validation** (that's what it's for) but it can never fly under your power/mass budget. Keep it explicitly labelled "lab prototype back-end" and design the flight back-end per Part 4.

**W3.2 — Two AD9361s sharing a 10 MHz reference are NOT phase-coherent. This is the biggest hidden technical risk in the whole project.** Your §9.3 proof covers *common-mode reference drift*. But each AD9361 generates its RX LO with its **own internal PLL/VCO**: at every retune the two boards come up with a **random inter-board LO phase offset**, and they accumulate *differential* phase noise outside the PLL loop bandwidth. The shared GPSDO does not remove either effect. Consequence: elements {1,2} and {3,4} have an unknown rotation e^{jβ} between them → steering vectors are wrong → MUSIC biases and MVDR nulls land off-target. The FMComms5 (ADI's own dual-AD9361 board) needs an explicit RF phase-calibration tone for exactly this reason. **Fix: add a calibration path** — couple a known L1-band tone into all four channels (use the *isolated port of the directional couplers you already have* — zero extra RF parts), measure the per-channel phase/gain, absorb it into the steering model: ã_m = g_m·e^{jγ_m}·a_m. Run cal at startup and on temperature change. This also fixes your σ_phase = 5° static-mismatch problem (§9.1) — it's the single highest-value addition to the design.

**W3.3 — No digital fine stage on the GPS path: null depth is capped by analog hardware, and the doc should say so.** In Arch 3 the GPS receiver gets the analog combiner output only; the beautiful 4-channel digital data is *sensing-only*. So the delivered null depth = analog ceiling ≈ 26–36 dB (weight quantization + VM linearity + channel mismatch after cal), **not** the 38–56 dB from the digital simulation. Those simulated numbers describe what the *sensing layer estimates*, not what the *GPS receiver experiences*. Per the Betz/C-N₀ chain (math doc §10.3) a 30 dB null is still operationally excellent (J/S 40 → 10 dB restores acquisition), so this is honest-framing, not failure — but a reviewer will catch it if the paper conflates the two. Options: (i) accept and state it; (ii) Phase-3 upgrade — digitize the combiner output and run a residual digital canceller before the GPS receiver (uses sense channels as references; one more ADC).

**W3.4 — AD8341 specifics (verified against datasheet):** band is **1.5–2.4 GHz** — L1 = 1575.42 MHz sits 75 MHz above the lower band edge (in-band, but all datasheet typicals are at 1.9 GHz → must bench-characterize at 1575); max gain is **−4.5 dB** (it's a lossy modulator: −4.5 to −34.5 dB control range) → add ~5 dB to the GPS-path link budget; and it burns **~125 mA at 5 V ≈ 0.63 W each → 2.5 W for four**, which alone kills the 1.5 W target (see Part 4). arch3.md's "DC to 2.5 GHz" claim is wrong — fix the doc.

**W3.5 — smaller items:**
- Pre-LNA SAW insertion loss (~1–1.5 dB) adds dB-for-dB to system NF → real NF ≈ 2–2.5 dB, not the 0.7 dB used in the math doc §10.2 link budget. Keep the SAW (out-of-band survivability in a hostile RF environment is worth it; the in-band jammer passes through regardless) but update the budget: nominal C/N₀ ≈ 43.5–44 dB-Hz.
- −20 dB sense tap leaves ≈ 0 dB net gain in front of the AD9361 → sense-path NF ~10 dB. Harmless for jammer DOA (jammers are huge) and GPS is invisible to MUSIC anyway, but −10 dB coupling buys margin for free.
- Add a **PIN limiter** in front of each SAW: at extreme jammer power the QPL9547 (P1dB ~ +20 dBm out) survives, but a swept/pulsed high-power jammer near the platform can exceed input ratings.
- Blade-flash multipath (100–400 Hz) lands **inside** the N=256 covariance window at low sample rates — set the snapshot epoch ≪ blade period or gate covariance accumulation on the blade-pass phase (you have motor RPM on a drone — use it).

---

## Part 3 — Is the math model the same for both architectures?

**The core is shared; the data acquisition and the adaptation loop are not.** Section-by-section mapping of COGNAV_MathModelling_v2_CORRECTED.md:

| Math doc section | Arch 1 | Arch 3 |
| :-- | :-- | :-- |
| §1–2 array model, steering vectors, element pattern | ✅ identical | ✅ identical |
| §3.2 sample covariance R̂ = XXᴴ/N | ❌ **not available** — no per-element data. Replace with: (a) no covariance at all (power inversion), or (b) quadratic reconstruction P_i = w_iᴴR̂w_i from ≥16 probe weights | ✅ as written, from sense ADCs |
| §3.3 diagonal loading, §3.4 subspaces | Only if (b) reconstruction used; loading is *more* important (reconstructed R̂ is noisier) | ✅ as written |
| §4 MUSIC + CRLB | ❌ (a): not applicable. (b): applies to reconstructed R̂ with extra variance — CRLB no longer valid as stated (measurement model changed from linear snapshots to quadratic power readings; new bound needed) | ✅ as written |
| §5 MVDR, DOF, null-vs-Δθ | Formulas identical *once a covariance exists*; in mode (a) the converged power-inversion solution equals MVDR with a w₀=1 constraint instead of the distortionless a_s constraint (slight GPS gain ripple — new small derivation needed) | ✅ as written |
| §6 analog pre-cancellation / ADC headroom | §6.4 applies to the **single GPS-path ADC**, with α = 0 during re-convergence (W1.3) | §6.4 applies to the **GPS receiver's internal ADC**; the sense ADCs always see the *unweighted* jammer — they rely on AD9361 AGC (allowed there: sensing doesn't carry GPS tracking, math §10.2) |
| §7 SPLL weight update | ❌ replaced by **perturbation/SPSA loop** — new convergence/misadjustment analysis required (dither size vs null-depth jitter trade) | ✅ block-SMI as written |
| §8 quantization/clipping | Single ADC, AGC disabled (arch1's call is correct) | AD9361 12-bit with AGC on sense; GPS receiver ADC per §6.4 |
| §9.3 shared-clock proof | **Arch 1 is intrinsically immune to inter-channel LO drift** — weighting happens at RF *before* the only mixer; there is just one downconversion chain. Only static RF-path mismatch matters (cal) | Proof covers the shared 10 MHz only. **Insufficient for two AD9361s** — must add inter-chip LO phase term e^{jβ_b(t)} to the model and a calibration identity to remove it (W3.2). This is a genuinely new math-doc section |
| §10 link budget | NF update for pre-LNA SAW (both) | Same + separate sense-path NF line |

**Bottom line:** Arch 3 uses the v2 math document as-is plus one new section (inter-chip phase calibration). Arch 1 keeps §1–2, §5–6, §8–10 but replaces §3–4 and §7 with a power-inversion / covariance-reconstruction framework. **Both extensions are now drafted as math doc §13** (13.1 = Arch 1 power inversion + 16-probe reconstruction, 13.2 = Arch 3 inter-chip cal identity, 13.3 = applicability map); two sub-derivations remain open and are tagged [DERIVE] there (optimal dither amplitude; probe-design conditioning). The asymmetry is itself a clean motivation paragraph for the paper: *"Arch 1 trades observability for simplicity; recovering MUSIC under Arch 1 costs a 16-probe quadratic reconstruction with these variance penalties…"*

---

## Part 4 — Hardware audit (components_arch3.docx)

### 4.1 Outright errors in the BOM

| Item | Problem (datasheet-verified) | Fix |
| :-- | :-- | :-- |
| **ZAPD-4-S+** (combiner ref) | It is a **2-way** splitter, band **2000–4200 MHz** — wrong way-count AND doesn't cover 1575 MHz | Custom microstrip 4-way Wilkinson on the PCB (λ/4 ≈ 27 mm sections at L1 on RO4350 — easily fits the 190 mm board, ~$0, lowest loss), or a connectorized 4-way specified through 1.575 GHz for the bench rig |
| **STM32H74321** (MCU) | Not a real part number | STM32H743ZI is the real part — but **delete the MCU entirely**: the Zynq PS (dual Cortex-A9) does loop control, power monitoring, and DAC SPI. One chip fewer, one firmware fewer, ~0.3 W saved |
| **"FPGA Artix-7 on B210"** (arch3.md) | B210 carries a **Spartan-6 XC6SLX150**, full with the USRP streaming design; needs an external **USB 3.0 host** (Zynq-7000 has none) | Treat B210s as bench-only; flight sensing per §4.4 |
| **AD8341 "DC–2.5 GHz"** (arch3.md) | Actual band **1.5–2.4 GHz**; L1 is 75 MHz from the band edge; max gain **−4.5 dB**; **125 mA @ 5 V each** | Part is usable but must be characterized at 1575 MHz; insertion loss into link budget; power problem → §4.3 |
| **OctoClock-G CDA-2990** | Bench/rack clock distributor with external mains-class supply — physically and electrically absurd on a drone | On-board TCXO/OCXO + 1:4 LVCMOS clock buffer (< 0.1 W total). Note: **a GPSDO cannot discipline while jammed** (it needs GPS!) — what the math (§9.3) actually requires is a *shared* reference, not a *GPS-disciplined* one. Holdover-grade TCXO is the right concept for a CRPA |
| **Z-turn "7035"** | MYIR's Z-turn line is **XC7Z010/7020 only** — there is no Z-turn 7035. 7035 boards exist from others (e.g. ALINX AX7Z035) | See §4.4 — you don't need a 7035 at all |

### 4.2 Power reality check — the 1.5 W target vs. the current BOM

| Item | Draw (typ.) |
| :-- | --: |
| 4 × QPL9547 LNA (65 mA @ 3.3 V) | 0.86 W |
| 4 × AD8341 VM (125 mA @ 5 V) | 2.50 W |
| AD8318 detector (68 mA @ 5 V) | 0.34 W |
| AD5676 DAC + OPA354 buffers | 0.05 W |
| STM32H743 | 0.30 W |
| 2 × USRP B210 | ~9 W |
| OctoClock-G | bench supply (≥ several W) |
| Zynq XC7Z035 board (PS+PL, realistic DSP load) | 3–5 W |
| u-blox M9 receiver | 0.10 W |
| **Total** | **≈ 16–20 W + bench clock** |

**The listed BOM is more than 10× over the 1.5 W target, and four line items each individually exceed or nearly exceed the entire budget.** Also be aware: a **Zynq-7035 by itself cannot meet 1.5 W** — its PS idles near ~1.5 W before any PL logic runs. The honest engineering answer is a three-tier plan:

| Tier | Purpose | Sensing | Weighting | Digital | Clock | Power |
| :-- | :-- | :-- | :-- | :-- | :-- | --: |
| **T1 Bench** (now) | Validate math end-to-end | 2 × B210 + host PC | AD8341 ×4 (eval boards) | PC/UHD + Python | OctoClock-G | ~25 W, mains |
| **T2 Integrated prototype** | First flying unit, the paper's hardware | 2 × AD9361 on custom carrier **or** NT1065 + quad ADC | AD8341 ×4 | **Zynq-7020** (covariance in PL, MUSIC/MVDR on A9) | TCXO + clock buffer | **4–6 W** |
| **T3 Production module** | The 1.5 W-class product | **NT1065** (4-ch, single-LO mode, ~0.5 W) — internal 2-bit ADCs are sufficient for strong-jammer DOA | **Passive 6-bit phase shifter + 7-bit DSA per channel (≈ 0 W)** | Artix-7 XC7A35T + Cortex-M, or Zynq-7010 throttled | TCXO + buffer | **≈ 1.5–2.5 W** |

Key insight for T3: the per-element math load is tiny — a 4×4 complex covariance at ~8 MSPS plus a 4×4 EVD and a MUSIC grid scan at 1 kHz update is a fraction of an XC7A35T. The 7035 is ~10× oversized for this algorithm; you were about to pay 3–5 W for headroom you'll never use. **Use the 7035 (or whatever Zynq board you own) for T1/T2 development, and explicitly plan T3 around a small FPGA.**

### 4.3 Component-level swaps (with reasoning)

| Block | Listed | Verdict / recommended |
| :-- | :-- | :-- |
| Pre-LNA SAW | Murata SAFEB1G57KE0F00 | ✅ Keep. Add its ~1.5 dB IL to the NF budget (math doc §10.2 update: NF ≈ 2–2.5 dB, C/N₀ ≈ 43.5 dB-Hz) |
| LNA | QPL9547 | Superb NF (0.25–0.3 dB) but 0.86 W for four — and **the SAW in front makes the system NF SAW-dominated, shrinking QPL9547's advantage to ~0.5 dB**. For T3 swap to **MAX2659** (GPS-specific: 20.5 dB gain, NF 0.8 dB, **8.2 mA** → 0.11 W for four). Keep QPL9547 for T1/T2 where power is free |
| Post-LNA SAW | Taoglas DBP.1567.S.A.50 | ✅ Keep (image/out-of-band cleanup before VM and tap) |
| Sense coupler | Mini-Circuits **ZFDC-20-5+** | Electrically fine (0.1–2 GHz, 20 dB), but these are **connectorized coax bricks ×4** — heavy and huge for a drone. T1: fine. T2/T3: PCB coupled-line or SMD coupler (Xinger-class), −10 dB coupling (W3.5), **and route the isolated port to the cal-tone network (W3.2)** |
| Vector modulator | AD8341 ×4 | T1/T2: keep (verify performance at 1575 MHz, band edge). T3: replace with **passive 6-bit phase shifter (e.g. MACOM MAPS-010144 class) + 7-bit DSA (PE43711 class)** — near-zero DC power, and the DSA's 0.25 dB steps beat the "1 dB steps" in arch1/arch3 docs |
| Combiner | ZAPD-4-S+ "reference" | ❌ wrong part (§4.1) → custom microstrip Wilkinson |
| Power detector | AD8318 | Works but 0.34 W and 8 GHz capability you don't need. **AD8314** (~4.5 mA, covers L1) or duty-cycle the AD8318 |
| MCU | "STM32H74321" | Delete (Zynq PS does it). If a supervisor is wanted, an STM32L0/G0 at µA-class |
| DAC | AD5676 (8-ch, 16-bit) | ✅ Exactly right: 4 VMs × (I+Q) = 8 channels. Note AD8341 I/Q inputs want 0.5 V common-mode differential — the OPA354 buffers must provide VCM and anti-alias RC; fine |
| SDR | USRP B210 ×2 | T1 only (W3.1). T2/T3: **NT1065** — 4-channel GNSS front end with an explicit **single-LO mode for array processing** (this part was designed for CRPAs; one LO = §9.3 satisfied *by construction*, no inter-chip cal needed). Caveat: NTLab availability/export status must be checked for your jurisdiction; fallback = 2 × AD9361 with the W3.2 cal-tone scheme, or 4 × MAX2769C sharing one TCXO (separate PLLs → residual differential phase noise, needs cal) |
| Clock | OctoClock-G | ❌ (§4.1) → 10 MHz TCXO (±0.5 ppm, holdover-rated) + LVCMOS 1:4 buffer |
| FPGA | "Z-turn 7035", Zynq candidate | T1/T2: any Zynq-7020 board you like (Z-turn 7020 exists and is cheap). T3: Artix-7 A35T + M-class core. Don't buy a 7035 for this |
| GPS receiver | u-blox M9 | ✅ Keep — and use UBX-MON/NAV-SIG messages to log per-SV C/N₀: that's your headline KPI instrument |

### 4.4 Missing from the BOM entirely (professional-grade gaps)

1. **IMU / attitude source.** The math doc's own conclusion (§10.2): GPS is invisible to MUSIC, so the MVDR constraint direction a_s comes from **almanac + platform attitude**. Nothing in the BOM measures attitude. Add an IMU (ICM-42688/BMI088 class, talks to the Zynq PS) + almanac from the u-blox. Without this line item the distortionless constraint is unimplementable.
2. **Calibration injection network** (W3.2) — tone source (the Zynq's own PLL output or a small synth) coupled into all 4 channels via the sense couplers' isolated ports. Removes σ_phase=5° static mismatch *and* the dual-AD9361 LO offset. Single highest-value addition.
3. **PIN limiters** on the antenna ports (survivability against close-in/high-power jammers).
4. **Power tree:** low-noise LDOs for LNA/VM rails (PSRR matters — supply ripple phase-modulates the VMs), separate analog/digital rails, input filtering from the drone's noisy ESC bus. On a quad, the 4-in-1 ESC is a broadband EMI source on the same battery.
5. **RF shielding cans** over the front end + the enclosure as a Faraday box; controlled-impedance PCB (RO4350 or similar) for the L1 sections, especially the Wilkinson.
6. **ESD/surge** on antenna ports; bias-tees only if you later switch to active patches.
7. **Anti-alias filtering** on the sense-ADC inputs (if external ADC used in T2/T3).
8. **Connector/cable plan:** T1 is SMA everywhere; T2/T3 should be a single PCB with U.FL only at the four patches.

---

## Part 5 — Decisions to lock now

1. **One hardware platform, two architectures:** build Arch 3; Arch 1 = Arch 3 with the sensing path disabled (fallback mode + clean A/B comparison for the paper).
2. ✅ **APPLIED — arch1.md fixed:** MUSIC/covariance chain removed (impossible with 1 ADC); Stage 11 rewritten as power-inversion (Mode A) with optional 16-probe covariance reconstruction (Mode B); fast power-detector trigger added; Wilkinson-loss, BPF, null-ceiling, and ADC-headroom corrections applied; renamed "Blind Analog Nulling (Power-Inversion CRPA)".
3. ✅ **APPLIED — arch3.md fixed:** Spartan-6 not Artix-7; AD8341 band/gain/power corrected; inter-AD9361 phase-coherence problem + cal-tone solution added (Stages 4, 6, design flags); delivered null depth (~26–36 dB analog ceiling) now stated separately from the 38–56 dB sensing-layer estimates; MCU deleted (Zynq PS); SAW NF and C/N₀ updated; missing BOM items (IMU, cal network, limiters) added to the component summary.
4. ✅ **APPLIED — math doc v2.1:** new §13.1 (power-inversion solution w_PI = R⁻¹e₀/(e₀ᴴR⁻¹e₀), dither loop, 16-probe reconstruction P_i = vec(w_iw_iᴴ)ᴴvec(R)); new §13.2 (inter-chip model Γ = diag(e^{jβ₁},e^{jβ₁},e^{jβ₂},e^{jβ₂}) + cal identity q_m = ĥ_m/ĥ₀); §13.3 applicability map; §9.3 third caveat; §10.2 SAW NF update (C/N₀ ≈ 43.5–44 dB-Hz); §12.2 alignment note (digital fine stage = T3 upgrade, not Arch 3 baseline).
5. **Re-scope the power target:** 1.5 W = T3 production goal with the passive-weight + NT1065 + small-FPGA design. T2 flying prototype target: **4–6 W** (entirely respectable for a drone — a 4S quad burns 200+ W hovering; 5 W of payload electronics is 2–3% endurance).
6. **Don't buy:** second B210, OctoClock, 7035 board, ZAPD-4-S+, STM32H7. **Do buy/add:** cal-tone coupler network parts, IMU, TCXO + clock buffer, AD8314, limiters.

---

*End of review. COGNAV Project — June 2026*
