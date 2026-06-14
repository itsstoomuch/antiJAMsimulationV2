# PROMPT — Hardware Architecture Selection for COGNAV-P1 (L1 Analog-Nulling CRPA Prototype)

> Use this prompt verbatim (with an engineering assistant or as a design-review brief) to generate the precise, datasheet-verified hardware selection for the flight prototype defined in plan.md. Companion context files: plan.md, arch3.md, ARCH_REVIEW_AND_HARDWARE.md, COGNAV_MathModelling_v2_CORRECTED.md.

---

## ROLE

You are an RF/mixed-signal hardware architect selecting components for a drone-mounted GPS anti-jamming CRPA prototype. Every claim you make must be verified against the manufacturer datasheet — at or interpolated to **1575.42 MHz** for RF parts — and you must cite the datasheet parameter table you used. If a part's specification is not stated at L1, say so explicitly and flag the characterization risk. Do not invent part numbers; if unsure a part exists, mark it `[VERIFY]`.

## FIXED SYSTEM CONTEXT (do not redesign these)

- Architecture: Arch 3 derivative — per-element analog weighting (vector modulator) → 4-way Wilkinson → clean L1 RF out (SMA, active-antenna emulation) + embedded GNSS receiver; sensing tap via −10 dB directional couplers → 4-channel coherent receiver → FPGA (MUSIC + MVDR); closed-loop null trim via post-combiner power detector; cal tone injected through coupler isolated ports.
- Band: **GPS L1 1575.42 MHz only**, ~2–4 MHz useful bandwidth.
- Array: 2×2 RHCP patch, d = 95.1 mm (λ/2), ≥190×190 mm ground plane.
- Power budget: **≤ 8 W total** from a 4S–6S drone bus (12.6–25.2 V input range). Sensing receiver may be duty-cycled after null convergence.
- Mass/size: ≤ 350 g, ~200×200×30 mm two-board stack (RF board + digital board) in a milled aluminum enclosure.
- Performance drivers: analog null depth ≥ 35 dB (1 jammer) after calibration + trim; re-null < 100 ms; channel-to-channel phase stability is the most precious analog property — prefer parts/bias choices that minimize phase drift vs temperature and supply.
- Already locked (do NOT propose alternatives unless a hard blocker exists; if you see a blocker, flag it in a dedicated "Locked-Part Risks" section): Murata SAFEB1G57KE0F00 pre-LNA SAW, Qorvo QPL9547 LNA, AD8341 vector modulators ×4, AD5676 16-bit 8-ch DAC, OPA354 buffers, AD8314-class power detector (replacing AD8318), microstrip Wilkinson on RO4350 (custom), u-blox M10-class embedded receiver.
- Known constraints from prior review: AD8341 band is 1.5–2.4 GHz (L1 near band edge — datasheet typicals at 1.9 GHz); B210/OctoClock are bench-only and must NOT appear in the flight BOM; no GPSDO (shared holdover TCXO instead); Zynq-7035 is oversized and over-budget — do not select it.

## YOUR TASK

For EACH selection block below, produce **2–3 candidate options** and **one recommended pick**, in a comparison table with exactly these columns:
`Part number | Manufacturer | Key specs @ 1575 MHz | Supply (V, mA, mW) | Package | Phase/temp stability note | Availability (Mouser/Digi-Key/LCSC, state stock class) | Unit cost (qty 10, USD approx.) | Why pick / why not`

### Block 1 — 4-channel coherent sensing receiver (the only major open decision)
Requirements: 4 RX channels, **single shared LO across all 4 channels strongly preferred** (eliminates inter-chip phase calibration); L1 coverage; IF/baseband output digitizable by FPGA; ≥ 2-bit effective quantization acceptable for strong-jammer DOA (jammers ≫ noise); total ≤ 1.6 W; SPI-configurable.
Options to evaluate (add others if real): (a) NTLab NT1065 single-LO mode — include an explicit availability/export assessment for purchase in India; (b) 2× AD9361 (or ADRV9002-class) with shared reference + cal-tone phase alignment — state the added cal burden and power; (c) discrete: 1× PLL synth (e.g. MAX2871-class) split 4 ways + 4× passive mixers + IF amps + quad ADC — state part-count, board area, and the quad ADC choice (≥12-bit, ≥ 8 MSPS/ch, lowest power that streams to a Zynq-7020).
Decide and justify against: power, phase coherence by construction, procurement risk, integration effort.

### Block 2 — FPGA/SoC processing module
Requirements: 4-ch covariance accumulation at the sensing sample rate, 4×4 EVD + MUSIC grid + MVDR at ~1 kHz, trim-loop FSM, DAC SPI, UART; ≤ 2.5 W; commercially available SoM preferred over custom; industrial temp.
Options: Zynq-7020 SoMs (e.g. MYIR Z-turn 7020, others), Zynq-7010, Artix-7 A35T/A50T + separate MCU. State PS/PL resource fit (LUTs/DSPs/BRAM for the covariance pipeline) and realistic power at this workload, not datasheet max.

### Block 3 — Antenna elements
Requirements: RHCP patch, L1, ≥ +3 dBic zenith, usable on a shared 190×190 mm ground plane at 95.1 mm pitch; passive (we provide the LNA); repeatable phase center; 4 units matched.
Options: COTS ceramic patches (state dielectric size: 25/35 mm class) vs custom-printed patch on the RF board itself. Address element-to-element phase-center matching and mutual coupling at λ/2 (~−20 dB expected) and whether vendor S-parameter data exists.

### Block 4 — Front-end protection + filtering details
Requirements: PIN limiter per channel ahead of the SAW (survive +20 dBm CW sustained, spec the actual threat level you assume); insertion loss ≤ 0.5 dB (it sits before the NF-critical chain — account for it in the NF budget you output).
Options: 2–3 limiter candidates. Also confirm post-LNA filter choice (Taoglas DBP.1567.S.A.50 is incumbent) or propose better.

### Block 5 — Directional couplers (sense tap + cal injection)
Requirements: PCB-integrable (coupled-line on RO4350 or SMD), −10 dB coupling, ≥ 20 dB directivity at L1, isolated port usable for cal-tone injection, through-loss ≤ 0.5 dB.
Options: on-board coupled-line (give dimensions class for RO4350) vs SMD parts (Xinger-class or equivalent — real part numbers only, `[VERIFY]` if unsure).

### Block 6 — Clock tree
Requirements: one shared reference for sensing RX LO + FPGA + cal synth; holdover-grade stability (±0.5 ppm class TCXO or better); low phase noise adequate for L1 downconversion; 1:4+ distribution buffer; length-matched distribution is a layout rule — state the skew budget in degrees at L1 that keeps differential phase ≪ 1°.
Options: TCXO vs OCXO (power trade), plus buffer candidates.

### Block 7 — Cal-tone source
Requirements: L1-band tone, ≥ 40 dB above sense-path noise floor at the ADC after −10 dB coupling, on/off keyable by FPGA, frequency-plannable to avoid sitting exactly on live GPS C/A (offset injection or scheduled during init).
Options: dedicated small synth (MAX2871-class), or reuse of the sensing RX's own LO/aux output, or FPGA-driven mixer spur — judge spectral purity needs honestly.

### Block 8 — Power tree
Requirements: 12.6–25.2 V in → rails for 5 V (AD8341), 3.3 V analog (LNA — state whether QPL9547 runs at 3.3 V bias point to save 0.4 W vs 5 V, with NF/IP3 penalty from datasheet), 1.8/1.0 V digital; low-noise LDOs on LNA/VM rails (PSRR ≥ 60 dB @ 1 kHz–1 MHz — VM control lines are phase-sensitive); input filtering against ESC noise on the drone bus.
Options: buck controller candidates + LDO candidates; output a rail map with per-rail current.

### Block 9 — Embedded receiver, IMU, interfaces
Confirm u-blox M10 module choice (specific module PN), IMU (ICM-42688 vs BMI088) with mounting/vibration note for a multirotor, UART/connector (GH-series), and the SMA output stage: net gain target 28–35 dB, behavior when host receiver supplies 3–5 V antenna bias (sink it safely, don't backfeed).

## REQUIRED OUTPUTS (in this order)

1. **Decision summary table** — one row per block: recommended part(s), runner-up, deciding factor (one sentence each).
2. **Per-block comparison tables** as specified above.
3. **System power budget** — every active part at its chosen bias, worst-case and typical columns, DC-DC efficiency applied, with the duty-cycled-sensing figure shown separately. Must close ≤ 8 W worst-case.
4. **Cascaded RF budget** — per-channel NF (limiter→SAW→LNA→coupler→VM), gain map antenna→SMA (target 28–35 dB net), and headroom check: max jammer level at AD8341 input vs its P1dB/IIP3 at the J/S values 30/40/50 dB.
5. **Phase-stability budget** — expected channel-to-channel phase drift over −10…+50 °C per block, summed RSS, compared against the cal + trim correction capability (recal trigger threshold).
6. **Procurement risk register** — any part single-sourced, export-sensitive, or > 8-week lead, with the named fallback.
7. **Locked-Part Risks** — anything about the locked parts (esp. AD8341 at band edge) that the measurements in plan.md §11 must retire before PCB tape-out.
8. **Open questions** — maximum 5, only ones that genuinely block schematic capture.

## RULES

- Precision over breadth: numbers with units, conditions stated (frequency, bias, temperature), datasheet section cited.
- No bench/lab equipment in the flight BOM.
- If two options are genuinely close, say so and give the tiebreaker measurement to run on the Stage-A brassboard.
- Currency: assume purchase from India; note import/export issues where relevant (NT1065 especially).
- Do not propose architecture changes — selection only. Architecture deviations go in "Open questions".

---

*hardware_selection_prompt.md — feed to the hardware-selection session for COGNAV-P1. Derived from plan.md (June 2026).*
