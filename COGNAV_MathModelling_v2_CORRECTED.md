# COGNAV-4 Mathematical Modelling — CORRECTED

## CRC Hybrid Analog-Digital Anti-Jamming System — GPS L1 1575.42 MHz

**Version: 2.1 — Corrected by Fable, June 2026**
**Supersedes Draft 1.0. All errors found in v1.0 are listed in Section 0, then fixed in place.**
**v2.1 adds Section 13 (architecture-specific math for Arch 1 power-inversion and Arch 3 inter-chip calibration), the SAW-first NF update in §10.2, and the §9.3/§12.2 alignment notes — synchronized with arch1.md, arch3.md, and ARCH_REVIEW_AND_HARDWARE.md.**

---

## Section 0 — Errors Found in Draft 1.0 (summary)

| # | Location | Error | Correction |
| :-- | :-- | :-- | :-- |
| E1 | §1.1 | d = 0.09517 m inconsistent with λ = 0.19029 m | d = λ/2 = **0.095147 m** (use exact c) |
| E2 | §2.2 | Kronecker order a_x ⊗ a_y contradicts the stated element ordering (0,0),(1,0),(0,1),(1,1) | Use **a = a_y ⊗ a_x** for that element ordering (or reorder elements) |
| E3 | §2.3 | Simulation uses cos(φ) element pattern | **sin(φ)** is correct for elevation convention (confirmed) |
| E4 | §4.3 | ∂a/∂θ has wrong sign structure: (m·sinθ + n·cosθ) | Correct: **(−m·sinθ + n·cosθ)**, with +j prefactor |
| E5 | §4.3 | CRLB formula missing the projection P_a^⊥ on the derivative | Added below |
| E6 | §5.4 | SINR_MVDR missing source power P_s | **SINR = P_s · aₛᴴ·R_{i+n}⁻¹·aₛ** |
| E7 | §6.1 | Sign error: e = α·s_ref − r cannot yield e = GPS + n + (1−α)·jammer | **e = r − α·s_ref** |
| E8 | §6.4 | "Shifts saturation from J/S = 11 dB to 24 dB" with Δ = 20 dB (11+20 ≠ 24) | Theory gives **+20 dB**; simulation measured **+13 dB**; gap explained below |
| E9 | §10.2 | dBm/dBW units mixed in one equation | Cleaned up (result was right) |
| E10 | §10.3 | "Post-correlation C/N₀ = −54.7 dBHz" is dimensionally and numerically wrong | **C/N₀ = 45.3 dB-Hz** nominal; processing gain does not enter C/N₀ |
| E11 | §3.3 | δ = λ_min is a weak loading choice | Use **δ ≈ 10·σ̂²** (10 dB above noise floor) — standard in CRPA literature |
| E12 | Block diagram | RF switch time-multiplexes one chain across 4 antennas — breaks array coherence | Architecture corrected in **Section 12** |

All derivations requested in v1.0 (items #1–#6, #9) are completed below. Items #7, #8, #10 are outlined with references.

---

## Section 1 — System Parameters and Notation

### 1.1 Constants ✅ CORRECTED

| Symbol | Value | Description |
| :---- | :---- | :---- |
| c | 299,792,458 m/s | Speed of light (exact, SI definition) |
| f_L1 | 1575.42 MHz | GPS L1 carrier frequency |
| λ | c / f_L1 = 0.190294 m | Wavelength at GPS L1 |
| d | λ/2 = 0.095147 m | Antenna element spacing |
| M | 4 | Number of array elements (2×2 URA) |
| N | 256 | Snapshots per processing epoch |
| K | up to 3 | Number of simultaneous jammers (= M−1, zero margin) |

**Answer to v1.0 note:** Yes — use the exact c in the formal derivation and in any hardware calibration tables. Quote λ = 0.190294 m and d = 95.15 mm. The v1.0 value d = 0.09517 m was internally inconsistent (it matches neither c = 3×10⁸ nor the exact c).

### 1.2 Signal Notation — unchanged from v1.0, with one addition

| Symbol | Description |
| :---- | :---- |
| α ∈ [0,1] | Analog pre-cancellation **amplitude** fraction (α = 0.9 means 90% of the jammer field amplitude is removed, i.e. 99% of jammer power) |

This clarification matters everywhere α appears: residual **amplitude** is (1−α), residual **power** is (1−α)².

---

## Section 2 — Array Signal Model

### 2.1 Received Signal ✅ CONFIRMED (unchanged)

x(t) = s(t)·a(θ_s, φ_s) + Σ_{k=1}^{K} j_k(t)·a(θ_k, φ_k) + n(t),  n(t) ~ CN(0, σ²I)

Assumptions as in v1.0 (narrowband, uncorrelated sources, spatially white noise, no mutual coupling, far field). All five must be stated in the proposal.

### 2.2 Steering Vector for 2×2 URA ✅ CORRECTED

**Convention (standardized, answers Question 1):** we adopt the **+j** convention throughout:

a_m(θ,φ) = exp(+j·k·u·r_m),  k = 2π/λ

where u = (cosφ·cosθ, cosφ·sinθ, sinφ) is the unit vector **from the array toward the source**, θ = azimuth from x-axis, φ = elevation above the horizon, and r_m is the position of element m. Both ±j conventions are valid; +j matches our simulation. Rahul's −j code must be converted (conjugate all steering vectors) before any weights cross between codebases. **Rule: weights and data must always be generated under the same convention — this should be a stated interface requirement in the integration plan.**

Element positions (in units of d): Element 0: (0,0), Element 1: (1,0), Element 2: (0,1), Element 3: (1,1).

Phase at element (m,n) — m is the x-index, n is the y-index:

ψ_{m,n}(θ,φ) = (2π·d/λ) · cosφ · (m·cosθ + n·sinθ)

Full steering vector in the element order above:

a(θ,φ) = [1, e^{jψ_{1,0}}, e^{jψ_{0,1}}, e^{jψ_{1,1}}]ᵀ

**Kronecker form (E2 fixed):** with a_x = [1, e^{j(2πd/λ)cosφ·cosθ}]ᵀ and a_y = [1, e^{j(2πd/λ)cosφ·sinθ}]ᵀ, the vector consistent with the element ordering (0,0),(1,0),(0,1),(1,1) is

a(θ,φ) = **a_y ⊗ a_x**

(v1.0 wrote a_x ⊗ a_y, which corresponds to element ordering (0,0),(0,1),(1,0),(1,1) — the m and n indices get swapped. Either ordering works, but the Kronecker order and the element list must agree, otherwise simulated data and analytically computed weights are silently mismatched on elements 1 and 2.)

### 2.3 Element Pattern ✅ CONFIRMED — sin(φ) is correct

With φ = **elevation** (φ = 90° at zenith), a patch antenna mounted flat (boresight up) has its pattern maximum at zenith. The standard first-order model is

g(θ,φ) = sin(φ) for φ ∈ [0°, 90°],  g = 0 for φ < 0°

(equivalently cos(θ_z) in zenith-angle convention, θ_z = 90° − φ — this is where the cos/sin confusion came from). The v1.0 flag is right: with cos(φ) the GPS satellite near zenith gets gain ≈ 0 and is effectively deleted from the data. **Fix in generate_array_data.py / realistic_sim.py before any physically-valid claims.** For the paper, note that a real GPS patch is closer to cosᑫ(θ_z) with q ≈ 1–2 and has a roll-off floor of −10 to −15 dB at the horizon, not a hard zero; the hard zero overstates horizon jammer attenuation.

Modified steering vector: ã(θ,φ) = g(θ,φ) · a(θ,φ) — unchanged.

### 2.4 Jammer Amplitude Conversion ✅ CONFIRMED (unchanged)

A_jam = 10^(J_dB/20) (amplitude); power uses 10^(J_dB/10). Correct as written.

---

## Section 3 — Spatial Covariance Matrix

### 3.1, 3.2 ✅ CONFIRMED (unchanged)

R = A·R_s·Aᴴ + σ²I;  R̂ = (1/N)·X·Xᴴ. The N ≫ M caveat stands: with M = 4, N = 256, the SMI loss relative to optimum SINR is ≈ (N+1−M)/(N+1) → about 0.05 dB (Reed–Mallett–Brennan rule: N ≥ 2M for loss < 3 dB). Quote RMB in the paper — it converts the "N ≫ M" hand-wave into a citable bound.

### 3.3 Diagonal Loading ✅ CORRECTED (answers Question 2)

R̂_dl = R̂ + δ·I

**δ = λ_min(R̂) is not the standard choice and is weak in exactly the regime where loading is needed:** with N < ∞ and K < M, λ_min(R̂) ≈ σ̂² when conditioning is fine, but under-loads when R̂ is genuinely ill-conditioned. The CRPA-standard choice (Cox, Zeskind & Owen 1987; Carlson 1988) is to load relative to the **noise floor**:

δ = β·σ̂²,  σ̂² = (1/(M−K))·Σ_{i=K+1}^{M} λ_i(R̂),  β ≈ 10 (i.e. 10 dB above noise)

This bounds white-noise gain, desensitizes MVDR to steering-vector error, and costs < 1 dB of null depth against strong jammers (loading only matters relative to the eigenvalue being nulled; a 30 dB-above-noise jammer eigenvalue is barely perturbed by 10·σ²). Keep the ε = 10⁻¹² floor for numerical safety only.

### 3.4 Eigendecomposition and Orthogonality — DERIVATION COMPLETED (item #3, part 1)

**Claim:** For the ensemble covariance R = A·R_s·Aᴴ + σ²I with A full column rank (K+1 ≤ M) and R_s full rank, the noise-subspace eigenvectors satisfy U_nᴴ·a(θ_k) = 0 **exactly** for every true source direction.

**Proof.** A·R_s·Aᴴ is Hermitian PSD with rank K+1, so it has eigendecomposition Σᵢ γᵢ eᵢeᵢᴴ with γ₁ ≥ … ≥ γ_{K+1} > 0 and γᵢ = 0 for i > K+1. Then R·eᵢ = (γᵢ + σ²)·eᵢ — the same eigenvectors, eigenvalues shifted by σ². Hence R has K+1 eigenvalues > σ² (signal subspace U_s = range(A)) and M−K−1 eigenvalues exactly σ² (noise subspace U_n = range(A)^⊥). Every steering vector a(θ_k) is a column-space vector of A, so a(θ_k) ∈ range(A) = span(U_s) ⊥ span(U_n), i.e. U_nᴴ·a(θ_k) = 0. ∎

For the **sample** covariance R̂, perturbation theory gives U_nᴴ·a(θ_k) = O_p(1/√N): eigenvector perturbation is first-order proportional to ‖R̂ − R‖/(eigvalue gap), and ‖R̂ − R‖ = O_p(1/√N). So MUSIC's null at the true direction fills in at rate 1/N in power — this is the consistency statement of §4.2. References: Schmidt (1986); Stoica & Nehorai, *IEEE Trans. ASSP* 37(5), 1989 (exact asymptotic variance, see §4.2).

---

## Section 4 — MUSIC Direction Finding

### 4.1 MUSIC Pseudospectrum ✅ CONFIRMED (unchanged)

P_MUSIC(θ,φ) = 1 / (aᴴ·U_n·U_nᴴ·a + ε). The 2D-scan gap stands: azimuth-only scan with assumed elevation is acceptable for ground-based jammers seen from a flying platform only if the elevation prior is good to a few degrees; Rahul's joint (θ,φ) scan removes the assumption.

### 4.2 MUSIC Consistency ✅ DERIVED (item #3, part 2)

With the §3.4 result: at a true direction, the denominator aᴴU_nU_nᴴa = ‖U_nᴴa‖² = 0 for ensemble R, and O_p(1/N) for R̂ — hence P_MUSIC(θ_k) = O_p(N) → ∞, while at any other direction the denominator converges to a positive constant. That is the formal consistency statement.

**Convergence rate / finite-N variance (Stoica & Nehorai 1989, Eq. 3.12):**

var(θ̂_k) ≈ (σ²/(2N)) · [ (aₖᴴ·P_A^⊥·aₖ)⁻¹ ]-weighted term = (σ²/(2N·P_k)) · ( d̃ₖᴴ·d̃ₖ )⁻¹ · (1 + σ²·(aₖᴴP_A^⊥aₖ)⁻¹/P_k + …)

where d̃ₖ = P_A^⊥·(∂a/∂θ)|_{θ_k} and P_A^⊥ = I − A(AᴴA)⁻¹Aᴴ. Key qualitative facts to quote: variance ∝ 1/N and ∝ 1/SNR at high SNR (MUSIC reaches the CRB), but has a **threshold SNR** below which the signal/noise subspaces swap and MUSIC breaks down — for strong jammers (J/S ≥ 30 dB) we are far above threshold, which is why 0.02° accuracy is achievable on jammers but GPS itself is invisible to MUSIC (see §10.2).

### 4.3 Cramér-Rao Lower Bound ✅ CORRECTED + COMPLETED (item #10)

**Corrected steering-vector derivative (E4).** From ψ_{m,n} = (2πd/λ)·cosφ·(m·cosθ + n·sinθ):

∂a_{m,n}/∂θ = a_{m,n} · j·(2πd/λ) · cosφ · (**−m·sinθ + n·cosθ**)

∂a_{m,n}/∂φ = a_{m,n} · j·(2πd/λ) · (**−sinφ**) · (m·cosθ + n·sinθ)

(v1.0 had −j·(m·sinθ + n·cosθ): the n-term sign was wrong — differentiation of cosθ gives −sinθ on the m-term and of sinθ gives +cosθ on the n-term.)

**Single-source CRLB (deterministic signal, known waveform power P, M elements, N snapshots, SNR ρ = P/σ²):**

var(θ̂) ≥ 1 / ( 2·N·ρ · ‖**P_a^⊥**·(∂a/∂θ)‖² ),  P_a^⊥ = I − a·aᴴ/‖a‖²

The projector P_a^⊥ was missing in v1.0; without it the bound is optimistic (the component of ∂a/∂θ parallel to a carries no direction information — it is absorbed by the unknown complex gain).

**Joint (θ,φ) FIM, single source:** with D = [P_a^⊥·∂a/∂θ, P_a^⊥·∂a/∂φ] ∈ ℂ^{M×2},

FIM = 2·N·ρ · Re{ Dᴴ·D },  CRLB(θ) = [FIM⁻¹]_{11}, CRLB(φ) = [FIM⁻¹]_{22}

**Degenerate-geometry warning for the 2×2 URA:** at θ = 45° (our jammer azimuth!), the two URA axes contribute identically, Re{DᴴD} becomes poorly conditioned in the (θ,φ) basis near the horizon, and at φ → 90° (zenith) ∂a/∂θ → 0 entirely — azimuth is unobservable for an overhead source. Both facts must be stated when quoting "0.02°". Numerical recipe for the paper: evaluate the 2×2 FIM above on a (θ,φ) grid at ρ corresponding to J/S = 30 dB, N = 256, and overlay MUSIC RMSE from Monte-Carlo. Reference: Van Trees, *Optimum Array Processing*, Ch. 8.

---

## Section 5 — MVDR Beamforming

### 5.1, 5.2 ✅ CONFIRMED (unchanged)

min wᴴR̂w s.t. wᴴa_s = 1;  w_MVDR = R̂_dl⁻¹a_s / (a_sᴴR̂_dl⁻¹a_s).

### 5.3 MVDR Optimality Proof ✅ COMPLETED (item #1)

The v1.0 Lagrange derivation is correct; one formal cleanup: with complex w, treat w and w* as independent (Wirtinger calculus) and write the constraint as the pair (wᴴa_s − 1, a_sᴴw − 1) with multipliers (μ, μ*) so L is real. Then ∂L/∂w* = R̂w + μ·a_s = 0 ⟹ w = −μ·R̂⁻¹a_s; the constraint gives μ = −1/(a_sᴴR̂⁻¹a_s) (real, since R̂ ≻ 0 Hermitian) and w_MVDR = R̂⁻¹a_s/(a_sᴴR̂⁻¹a_s). Second-order check: the Hessian w.r.t. w is R̂ ≻ 0, so this is the unique global minimum. ∎

**Max-SINR equivalence (the part v1.0 asked for).** Decompose R = P_s·a_s a_sᴴ + R_{i+n}. By the Sherman–Morrison identity:

R⁻¹·a_s = R_{i+n}⁻¹·a_s / (1 + P_s·a_sᴴR_{i+n}⁻¹a_s)

i.e. R⁻¹a_s ∝ R_{i+n}⁻¹a_s. Since output SINR = P_s·|wᴴa_s|²/(wᴴR_{i+n}w) is invariant to scaling of w, the MVDR weight (computed from the **full** R, signal included) and the max-SINR weight w ∝ R_{i+n}⁻¹a_s achieve **identical SINR**. This is why training on data that contains the GPS signal is harmless here — and the caveat: the equivalence requires the assumed a_s to be exact; with steering error, signal-inclusive training causes self-nulling, which is one more reason for diagonal loading (§3.3). ∎

### 5.4 Theoretical SINR ✅ CORRECTED + DERIVED (item #2, E6)

SINR_MVDR = **P_s** · a_sᴴ · R_{i+n}⁻¹ · a_s

(v1.0 omitted P_s; it only "worked" because the simulation sets P_s = 1.)

**Derivation.** Take any w with wᴴa_s = 1. Output signal power = P_s·|wᴴa_s|² = P_s; output interference+noise power = wᴴR_{i+n}w. By Cauchy–Schwarz in the R_{i+n} inner product:

1 = |wᴴa_s|² = |⟨R_{i+n}^{1/2}w, R_{i+n}^{−1/2}a_s⟩|² ≤ (wᴴR_{i+n}w)·(a_sᴴR_{i+n}⁻¹a_s)

⟹ wᴴR_{i+n}w ≥ 1/(a_sᴴR_{i+n}⁻¹a_s), with equality iff w ∝ R_{i+n}⁻¹a_s. Hence SINR = P_s/(wᴴR_{i+n}w) ≤ P_s·a_sᴴR_{i+n}⁻¹a_s, achieved by w_MVDR (per §5.3 equivalence). ∎

**Reconciliation with the simulation formula (§5.5):** substituting R_{i+n} = Σₖ Pₖaₖaₖᴴ + σ²I into wᴴR_{i+n}w gives exactly Σₖ|wᴴaₖ|²Pₖ + σ²‖w‖² — the §5.5 denominator generalized to K jammers. The two formulas are the same quantity; §5.5 as written is the K = 1 special case.

### 5.5 Output SINR ✅ CONFIRMED with K-jammer generalization

SINR = |wᴴa_s|²·P_s / ( Σ_{k=1}^{K} |wᴴa_k|²·P_k + σ²·‖w‖² )

The BPSK-decorrelation assumption (jammer ⊥ GPS) stands; it fails only for repeater/spoofer jammers, which are out of scope — state this.

### 5.6 Beampattern ✅ CONFIRMED (unchanged)

### 5.7 Degrees of Freedom ✅ DERIVED (item #6)

**Claim:** with M elements, 1 distortionless constraint, and K jammers to null, the remaining free DOF is M − K − 1; feasibility requires K ≤ M − 1; designing for 1 DOF of margin requires M ≥ K + 2.

**Proof.** w ∈ ℂ^M has M complex DOF. The constraint set {wᴴa_s = 1, wᴴa_k = 0, k = 1..K} is a linear system Cᴴw = [1,0,…,0]ᵀ with C = [a_s, a_1, …, a_K] ∈ ℂ^{M×(K+1)}. A solution exists for generic geometry iff rank(C) = K+1 ≤ M, i.e. **K ≤ M−1**; the solution set is then an affine subspace of dimension M−(K+1) = **M−K−1** — these are the DOF left for noise minimization, robustness, and pattern control. At K = M−1 the solution is the unique w = C^{-ᴴ}e₁: zero margin, so any perturbation (steering error, coupling, a 4th jammer) has no free dimension to absorb it and null depths collapse. For K > M−1 the system is overdetermined — exact nulls are impossible and MVDR instead minimizes total residual jammer power (shallow, shared nulls). Hence M_min = K + 2 for one DOF of margin. ∎

For COGNAV-4: M = 4, K = 3 is the **zero-margin** operating point — quote it as a demonstrated extreme, and quote K = 2 (one DOF margin) as the design point.

### 5.8 Null Depth vs Angular Error ✅ DERIVED (item #9)

Let w be the weight that puts an exact null at the estimated direction θ̂ = θ_k + Δθ, and B(θ) = |wᴴa(θ)|². Taylor-expand a(θ_k) = a(θ̂) − Δθ·a′(θ̂) + (Δθ²/2)·a″(θ̂) − …, and use wᴴa(θ̂) = 0:

wᴴa(θ_k) = −Δθ·wᴴa′(θ̂) + O(Δθ²)

**null_depth_dB(Δθ) ≈ 20·log₁₀( |Δθ_rad| · |wᴴa′(θ̂)| )**

Consequences to state in the paper:

1. Null depth degrades **20 dB per decade of angular error**. A 60 dB null needs |Δθ|·|wᴴa′| ≈ 10⁻³; with |wᴴa′| = O(2πd/λ·‖w‖) = O(π) for our array, that is Δθ ≈ 0.02° — exactly why Rahul's sub-0.1° DoA accuracy is load-bearing for >50 dB nulls.
2. Sanity check against the observed J1 bug: Δθ = 31° is far outside the Taylor regime; there B(θ_k) is just "sidelobe level at 31° from the null" ≈ −8 dB relative to constraint gain — consistent with the observed collapse from 62 dB to ~8 dB.
3. The slope |wᴴa′(θ̂)| is computable in closed form from §4.3's corrected derivative; plot null depth vs Δθ from 0.001° to 10° (log-log: a straight −20 dB/decade line transitioning to the sidelobe floor).

---

## Section 6 — Analog Pre-Cancellation (CRC Stage)

### 6.1 Pre-Cancellation Signal Model ✅ CORRECTED (E7)

The 180° hybrid subtractor computes (sign fixed so the claimed residual follows):

e(t) = r(t) − α·s_ref(t)

where r(t) is the main-chain signal (GPS + jammer + noise) and α·s_ref(t) is the phase-shifter+VGA-weighted reference. With s_ref dominated by the jammer (J/S ≥ 30 dB makes the reference ≈ jammer to within 10^(−J/S/20)), and α tuned to the jammer's complex amplitude in the main chain:

e(t) = GPS(t) + n(t) + (1−α)·jammer(t) − α·(GPS_ref(t) + n_ref(t))

v1.0 dropped the last term. It matters at the precision we claim: the reference path injects a −α-scaled copy of GPS and reference-chain noise into e(t). For α ≈ 0.9 this is a ~1 dB-level GPS distortion and a 3 dB-level noise increase that the digital MVDR stage inherits — include it in the SINR budget (it is the analog analogue of the §5.3 self-nulling caveat).

### 6.2 Matrix Form ✅ CONFIRMED with the v1.0 flag answered

X_pre = (I − α·â_n·â_nᴴ)·X, â_n = a_jam/‖a_jam‖.

**Answer to the MAJOR FLAG (and Question 4) — modelling hardware-limited α.** Replace the ideal scalar α by the realized complex weight α̂ = (1+ε_A)·e^{jε_φ}·α, where ε_A and ε_φ are amplitude and phase setting errors. The achievable cancellation of a tone by an imperfect anti-phase copy is

C_dB = −10·log₁₀( (1+ε_A)² − 2(1+ε_A)cos(ε_φ) + 1 ) ≈ −10·log₁₀( ε_A² + ε_φ² ) for small errors

For a **6-bit phase shifter** (LSB = 5.625°): worst-case quantization error = 2.81° = 0.0491 rad → C = 26.2 dB; RMS error = LSB/√12 = 1.62° = 0.0283 rad → C ≈ 31 dB. Add a 6-bit VGA with 0.25 dB steps (ε_A ≈ 0.014 RMS) and DoA-induced steering error from §5.8, combined in RSS:

α_effective: (1−α)²_effective = ε_A² + ε_φ² + (Δθ·|∂(âᴴa)/∂θ|)²

**So the honest hardware claim is α_eff ≈ 0.97 (30 dB analog cancellation ceiling), not an arbitrary 0.9** — conveniently, the simulated α = 0.9 (20 dB) is *conservative* relative to the 6-bit ceiling, which is the right way to present it. State all three error contributions in the proposal.

### 6.3 Residual Power ✅ CONFIRMED, terminology tightened

P_residual = P_input·(1−α)²; ΔP = 20·log₁₀(1−α) = −20 dB at α = 0.9. Correct, with §1.2's clarification that α is an **amplitude** fraction (90% amplitude = 99% power cancellation; saying "90% cancellation" without qualifier invites a reviewer to read 10·log₁₀(0.1) = −10 dB).

### 6.4 ADC Headroom ✅ FULLY DERIVED (item #5) + discrepancy E8 resolved

**Derivation.** Let the ADC clip at full-scale amplitude FS. The ADC input envelope is dominated by the residual jammer plus GPS+noise. No-saturation condition with crest factor χ (peak/RMS of the jammer, χ ≈ 3 ≈ 9.5 dB for Gaussian barrage, χ = √2 for CW):

χ·(1−α)·A_j + A_floor ≤ FS, A_floor = RMS amplitude of GPS+noise

Solving for the maximum jammer amplitude and converting to J/S (with A_j = 10^{(J/S)/20}·A_GPS):

**J/S_max(α) = 20·log₁₀( (FS − A_floor) / (χ·A_GPS) ) − 20·log₁₀(1−α)**

i.e. **J/S_max(α) = J/S_max(0) + Δ_analog, Δ_analog = −20·log₁₀(1−α)** — the pre-canceller buys headroom dB-for-dB of amplitude cancellation. For α = 0.9: Δ_analog = +20 dB. The system *fails* when (1−α)·A_j·χ > FS − A_floor and *succeeds* otherwise; expressed in power, success ⟺ P_j·(1−α)² ≤ ((FS−A_floor)/χ)².

**Resolution of E8 (theory +20 dB vs simulation +13 dB / 11→24 dB):** the v1.0 sentence "shifts saturation from 11 dB to 24 dB" contradicts its own Δ = 20 dB. The simulation's measured extension was 13 dB, not 20, because (a) the GPS+noise floor A_floor consumes headroom that the simple −20log₁₀(1−α) formula ignores, (b) saturation in the simulation is defined by SINR degradation, not first clip — soft degradation begins before hard saturation, and (c) jammer crest factor. Present **+20 dB as the ideal-component upper bound** and **+13 dB as the measured end-to-end extension**, with the gap explained by exactly these three terms. Do not quote "24 dB" as if it followed from the formula.

### 6.5 Modified Noise After Pre-Cancellation ✅ DERIVED (item #4)

**Claim:** e(t) = (I − α·P)·x(t) with P = â_nâ_nᴴ (Hermitian, idempotent: P² = P) maps noise covariance σ²I to

R_noise,pre = σ²·(I − α(2−α)·P)

**Derivation.** R_noise,pre = (I−αP)·σ²I·(I−αP)ᴴ = σ²·(I − 2αP + α²P²) = σ²·(I − 2αP + α²P) = σ²·(I − α(2−α)·P). ∎

Interpretation: in the jammer direction the residual noise power factor is 1 − α(2−α) = (1−α)² — noise is suppressed by the same factor as the jammer along â_n (the canceller can't tell them apart in that one spatial dimension); in the M−1 orthogonal dimensions noise is untouched. Post-cancellation SINR computations must use this colored R_noise,pre, not σ²I. (With the §6.1 correction, add the reference-chain noise term α²σ_ref²·P if the reference antenna noise is independent.)

---

## Section 7 — SPLL Adaptive Weight Update

### 7.1 Cross-Correlation Matrices ✅ CONFIRMED (unchanged)

### 7.2 Optimal SPLL Weights ✅ CONFIRMED + convergence answered

W_opt = R̂_xx⁻¹·R̂_rx is the **block Wiener / sample-matrix-inversion (SMI)** solution, not LMS — it converges in a single block if the jammer is stationary over the N samples, with the RMB transient (≈3 dB loss at N = 2M). The questions asked:

- **Stationarity requirement:** at f_s = 10 MHz and N = 256, the block spans 25.6 µs. A jammer on a platform moving at 50 m/s changes geometry by ~1.3 mm ≪ λ in that window — spatially stationary for any realistic kinematics. The binding constraint is the **update loop latency** (FPGA correlate → SPI → DAC settle), not N.
- **If implemented as iterative LMS** w(n+1) = w(n) + µ·x(n)·e*(n): stability requires 0 < µ < 2/λ_max(R_xx); time constant of mode k is τ_k ≈ 1/(µ·λ_k); eigenvalue spread λ_max/λ_min ≈ J/S (30 dB ⟹ slow convergence of the weak modes — another reason to prefer block SMI in the FPGA).
- **Tracking lag:** for jammer angular rate ω̇ (rad/s) and update period T_u, steering lag Δθ = ω̇·T_u feeds §5.8's null-depth formula — this closes the loop between hardware update rate and achievable null depth, and belongs in the proposal as a single combined plot.

---

## Section 8 — ADC and Quantization

### 8.1 Clipping Model ✅ CONFIRMED, question answered

Independent I/Q clipping vs envelope clipping: for the **dynamic-range trend analysis** (SINR vs J/S curves) the difference is small — both models saturate at the same input power within ~1–2 dB, and the qualitative knee location is unchanged. The difference matters for **intermodulation spectra** (envelope clipping of a CW jammer creates odd harmonics in-band differently than I/Q clipping), so: keep I/Q clipping for the dynamic-range curves, state it as a limitation, and do not use the clipped-spectrum fine structure for any claim.

### 8.2 Quantization Noise ✅ ANSWERED

SQNR = 6.02·N_bits + 1.76 = 74.0 dB (12-bit) — correct. Quantization noise is negligible **provided the AGC keeps the signal near full scale**: σ_q² is fixed relative to FS, so the real condition is

(thermal noise at ADC input, dB below FS) < SQNR − 10 dB ⟺ backoff + crest margin < ~64 dB

Under jamming, AGC scales to the jammer; the GPS+noise floor sits J/S below it. Quantization becomes significant when **J/S + 10 dB margin > SQNR**, i.e. J/S ≳ 64 dB for an ideal 12-bit ADC (≈ 52–58 dB at ENOB 10–11). Inside our operating envelope (J/S ≤ 40 dB) quantization is genuinely negligible — but say it via this condition, since the condition itself is another argument for the analog pre-canceller (it reduces the J/S seen by the ADC by Δ_analog, keeping the floor away from the quantization limit).

### 8.3 ENOB ✅ kept as in v1.0 (10–11 bits typical; fold into the §8.2 condition).

---

## Section 9 — Hardware Imperfections

### 9.1, 9.2 ✅ CONFIRMED (unchanged)

### 9.3 GPSDO Common-Mode Cancellation ✅ PROOF CONFIRMED (Question 3)

The v1.0 argument is correct and sufficient. Formally: if x(t) = x₀(t)·e^{jφ(t)} with **the same** φ(t) on all channels, then

R̂ = (1/N)·Σ_t x(t)x(t)ᴴ = (1/N)·Σ_t x₀(t)x₀(t)ᴴ·e^{jφ(t)}e^{−jφ(t)} = R̂₀

— exact cancellation in the outer product for any φ(t), no smallness assumption needed. ∎ Three caveats for the paper: (1) it cancels only the **common-mode** part; residual per-channel differential drift (LO distribution skew, temperature gradients) survives and is what the σ_phase = 5° of §9.1 models; (2) the common phase still rotates the absolute carrier — irrelevant to R̂ and to MVDR weights, but the GPS receiver's own tracking loop sees it; (3) **a shared reference does NOT make two separately-synthesized LOs phase-coherent** — when the 4 channels are split across two RF chips (e.g. two AD9361s), each chip's PLL adds a random inter-chip phase offset at every retune plus differential phase noise outside the loop bandwidth; this must be calibrated out (formal model and identity in **§13.2**). Also note a GPS-*disciplined* oscillator cannot discipline while jammed — the architectural requirement is a *shared holdover-grade* reference, not GPS discipline.

### 9.4 Mutual Coupling ✅ QUESTION ANSWERED (Question 5)

Standard model: x_coupled = C·x_ideal, estimated jointly with DoA or pre-calibrated. The standard references: **Gupta & Ksienski 1983** (*IEEE Trans. AP*, coupling effect on adaptive arrays — the canonical citation), **Friedlander & Weiss 1991** (joint DoA + coupling auto-calibration), and for patch arrays specifically, full-wave EM simulation (HFSS/CST) of the fabricated 2×2 layout, validated by a 2-port S-parameter measurement (C_ij ≈ S_ij for matched elements). Recommendation: for the proposal, (a) cite −20 to −30 dB typical adjacent-element coupling at λ/2, (b) simulate its impact by applying a synthetic C with |C_ij| = −25 dB random phase and reporting DoA bias and null-depth loss, (c) plan a measured-C calibration table in hardware phase 2. Analytic patch-coupling formulas exist (Pozar 1982) but EM simulation of the actual board is the defensible choice.

---

## Section 10 — Physical Link Budget

### 10.1 Free Space Path Loss ✅ CONFIRMED (182.5 dB — verified)

### 10.2 Thermal Noise Floor ✅ CORRECTED units (E9)

N₀ = −204 dBW/Hz + NF = −204 + 0.7 = −203.3 dBW/Hz (equivalently −174 + 0.7 = −173.3 dBm/Hz)

N_thermal(10 MHz) = −203.3 + 70 = −133.3 dBW ✓ (v1.0's number was right; it just mixed dBm and dBW in one line)

GPS at −158 dBW is **24.7 ≈ 25 dB below** the 10 MHz noise floor pre-correlation ✓. The implication stands and is one of the strongest statements in the document: **MUSIC sees only jammers; the GPS constraint direction must come from almanac + platform attitude.** Keep verbatim. (Hardware consequence: the BOM must include an IMU/attitude source — added to arch3.md.)

**Hardware NF update (Arch 1 & Arch 3 BOMs):** both architectures place a SAW filter *before* the LNA for out-of-band survivability. Its ~1–1.5 dB insertion loss adds dB-for-dB to NF → system NF ≈ **2–2.5 dB**, not the 0.7 dB used above. Nominal unjammed C/N₀ becomes ≈ **43.5–44 dB-Hz**. The 0.7 dB figure remains valid for the LNA-first idealization only; the proposal should quote the SAW-first number.

### 10.3 GPS Processing Gain and C/N₀ ✅ CORRECTED (E10) + thresholds answered

Processing gain = 10·log₁₀(1.023×10⁶ × 10⁻³) ≈ 30.1 dB ✓ (correct in v1.0).

**The v1.0 C/N₀ arithmetic was wrong** (it produced −54.7 "dBHz", a negative carrier-to-noise-density, and double-counted processing gain — C/N₀ is defined *before* despreading and does not include processing gain). Correct chain:

C/N₀ = C − N₀ = −158 dBW − (−203.3 dBW/Hz) = **45.3 dB-Hz** (nominal unjammed — matches the well-known 44–45 dB-Hz for GPS L1 C/A)

**Effective C/N₀ under jamming (Betz formula — this is the headline-KPI equation):**

(C/N₀)_eff = 1 / [ (C/N₀)⁻¹ + (J/S)/(Q·R_c) ] (linear units; R_c = 1.023 Mcps; Q = spectral separation coefficient ≈ 1 for narrowband CW at band center, ≈ 1.5 for matched-spectrum noise, ≈ 2 for wideband)

**Thresholds (answering the question):** acquisition needs ≈ **33–35 dB-Hz** (standard correlators, 1 ms coherent); tracking holds to ≈ **25–28 dB-Hz**. Worked example for the proposal: J/S = 40 dB CW, Q·R_c → (C/N₀)_eff ≈ 20 dB-Hz → acquisition impossible. A 30 dB spatial null reduces J/S to 10 dB → (C/N₀)_eff ≈ 43 dB-Hz → fully recovered. **Each dB of null depth is a dB off J/S, mapped through the Betz formula to C/N₀** — this single chain converts our null-depth results into the physically meaningful KPI, and is the missing piece flagged as Gap E. Implementing a C/A correlator in the simulation remains the right next step to demonstrate it end-to-end.

---

## Section 11 — Status of Derivations After This Revision

| # | Item | v1.0 status | v2.0 status |
| :-- | :---- | :---- | :---- |
| 1 | MVDR optimality + max-SINR equivalence | Partial | ✅ Done (§5.3) |
| 2 | SINR = P_s·aₛᴴR_{i+n}⁻¹aₛ | Missing | ✅ Done, reconciled with sim formula (§5.4) |
| 3 | MUSIC consistency/orthogonality | Outline | ✅ Done (§3.4, §4.2 + Stoica-Nehorai rate) |
| 4 | Noise after pre-cancel α(2−α) | Stated | ✅ Done (§6.5) |
| 5 | ADC headroom from FS | Formula only | ✅ Done incl. crest factor + floor (§6.4) |
| 6 | DOF: M_min = K+2 | Stated | ✅ Done (§5.7) |
| 7 | GPS BPSK decorrelation condition | Missing | ⚠️ Outline: E[s·j*] = 0 holds for any jammer independent of the C/A code; quantitative bound needs the code cross-correlation argument — cite Betz Q-factor as interim |
| 8 | Sample covariance convergence | Missing | ⚠️ RMB rule cited (§3.2); full bound: Vershynin-type ‖R̂−R‖ = O(√(M/N)) — cite, don't derive |
| 9 | Null depth vs Δθ | Missing | ✅ Done: −20 dB/decade law (§5.8) |
| 10 | CRLB for 2×2 URA | Missing | ✅ FIM given + degeneracy warnings (§4.3); numerical evaluation still to run |

Physics corrections A–E from v1.0 remain **simulation work items** (element pattern sin(φ), consistent GPS direction, SINR from clipped waveform, estimated-not-true a_jam, C/A correlator) — the math for each is now in place in §2.3, §5.8, §6.4, §6.2, §10.3 respectively.

---

## Section 12 — The 2×2 Anti-Jam CRPA Module: Corrected Architecture

This section replaces the hand-drawn block diagram. Two structural problems in the drawn version, then the corrected design.

### 12.1 What's wrong with the drawn block diagram

**Problem 1 — the RF switch breaks the array (E12, critical).** The drawing routes 4 LNAs into one RF switch feeding a single chain. A switched (time-multiplexed) front end captures element m at time t_m, element m′ at t_m′ — but MUSIC/MVDR need the **inter-element phase at the same instant**. Switching only preserves usable phase coherence for a perfectly stationary CW jammer with a common LO; for FMCW or barrage jammers (our stated threat model) the snapshots decohere and both R̂ and the steering relationship are destroyed. Everything in Sections 3–5 assumes simultaneous x(t) ∈ ℂ⁴. **A CRPA cannot be built around a 1-of-4 RF switch.**

**Problem 2 — as drawn it is a 2-channel sidelobe canceller, not a 4-element CRPA.** One phase shifter + one VGA realizes exactly one complex weight, i.e. one steerable null (K_max = 1). The §5.7 result says 3 simultaneous nulls need 3 independent complex weights. The drawn topology, even with the switch fixed, is the M = 2 special case.

What the drawing gets **right** (keep all of it): LNA-first per element; shared LO between front-end chips (§9.3 proof is the justification); 180° hybrid as the analog subtractor; e(t) fed back via correlator → weight extraction → SPI → DAC → phase-shifter/VGA (this is exactly the §7 SPLL); anti-alias filtering at IF before the ADC; GPS receiver consuming the cleaned output.

### 12.2 Corrected architecture

```
            ANT0 (ref)      ANT1            ANT2            ANT3
2×2 patch     │               │               │               │
d = 95.1 mm  LNA             LNA             LNA             LNA
              │               │               │               │
             BPF             BPF             BPF             BPF   (L1 SAW, ~20 MHz)
              │               │               │               │
              │          ┌────┴────┐     ┌────┴────┐     ┌────┴────┐
              │          │ VECTOR  │     │ VECTOR  │     │ VECTOR  │   3 × analog complex
              │          │ MOD w1  │     │ MOD w2  │     │ MOD w3  │   weights (VM: I/Q or
              │          │ (φ+VGA) │     │ (φ+VGA) │     │ (φ+VGA) │   phase-shifter+VGA)
              │          └────┬────┘     └────┬────┘     └────┬────┘
              │               │               │               │
              └───────────►  4:1 COMBINER (Wilkinson) ◄───────┘
                              │
                         e(t) = x0 + Σ wm·xm      ← analog beam with up to 3 nulls
                              │
                    ┌─────────┴─────────┐
                    │                   │
              directional           main path
              coupler tap               │
                    │              MIXER (shared LO) → IF BPF (anti-alias, ≥2.046 MHz)
                    │                   │
                    │                  ADC ch0  ─────────┐
                    │                                    │
   per-element taps (x1..x3, pre-VM, via couplers)       │
        │   │   │                                        ▼
      MIXERS (same shared LO) → IF BPF → ADC ch1–3 →   FPGA
                                                         │
        ┌────────────────────────────────────────────────┤
        │  FPGA processing:                              │
        │  1. R̂ = XXᴴ/N from 4 coherent channels        │
        │  2. MUSIC → jammer DoAs (θ̂k, φ̂k)             │
        │  3. a_s from almanac + IMU attitude (§10.2!)   │
        │  4. w_MVDR = R̂_dl⁻¹a_s/(aᴴR̂_dl⁻¹a_s)        │
        │  5. Coarse part → SPI words (Wz, Wa) → DACs    │──► DACs ──► VMs (analog
        │  6. Fine digital MVDR on residual              │            coarse nulls)
        └────────────────────┬───────────────────────────┘
                             │ cleaned IF / IQ
                       GPS RECEIVER (C/A correlator → C/N₀ KPI)

  CLOCKING (the §9.3 requirement, = "Ettus Clock PCB" on the drone):
  GPSDO 10 MHz ──► clock distribution ──► shared LO synth, all ADC clocks, FPGA
  (one oscillator, one LO, split 4 ways — common-mode drift cancels in R̂ exactly)
```

**How the hybrid split works (ties §6 to §5):** the 3 vector modulators apply the **coarse analog weights** before the ADC — this is the (I − αP) pre-canceller of §6.2, realized with ~30 dB ceiling per §6.2's 6-bit analysis, buying Δ_analog of ADC headroom per §6.4. The 4 coherent ADC channels then let the FPGA compute full-precision digital MVDR on the residual — digital weights have no 6-bit limit, so the final null depth is set by channel mismatch (§9.1: 20–27 dB at σ_phase = 5°, recoverable to 38–56 dB with the GPSDO per §9.3). Analog stage = dynamic range; digital stage = null depth. That division of labor is the novel contribution, stated precisely.

⚠️ **Mapping to the as-built Arch 3 (alignment note):** in arch3.md the digital path is **sensing-only** — the GPS receiver gets the analog combiner output with no digital second stage. There, the *delivered* null depth equals the **analog ceiling (~26–36 dB after calibration)**, and the 38–56 dB figures describe the sensing layer's estimate, not what the GPS receiver experiences. The "digital fine MVDR on the GPS path" described above is the **Phase-3/T3 upgrade** (one more ADC on the combiner output). Papers must keep the two numbers separate (ARCH_REVIEW_AND_HARDWARE.md, W3.3).

**Minimum-viable variant (closer to the drawing, honest about limits):** keep ANT0 as reference and only ONE auxiliary chain with VM + hybrid subtractor → a classic 2-channel analog canceller: K = 1 null, ~26–31 dB deep (6-bit limit), no digital MVDR stage. Valid as a Phase-1 hardware demo, but it must be labelled M = 2, K = 1 — the 4-element math of this document does not apply to it.

### 12.3 Component-level corrections to the drawn diagram

| Drawn element | Issue | Correction |
| :-- | :-- | :-- |
| RF switch + MCU after LNAs | Breaks coherence (§12.1) | Delete. 4 parallel chains; MCU keeps housekeeping only (AGC, temperature, cal) |
| One phase shifter + VGA total | 1 complex weight = 1 null | One VM per auxiliary element (3 total) for K = 3 |
| Power splitter making s_ref | OK in concept | Implement as directional couplers (−10 dB taps) so the main path isn't 3 dB-starved |
| "RC filter, IF BW" | RC = 6 dB/oct, inadequate anti-alias | ≥3rd-order LC or SAW IF bandpass; BW ≥ 2.046 MHz (C/A main lobe), centered at IF |
| e(t) = s(t) − r(t) | Sign/role of arms ambiguous | Define e = main − w·reference (§6.1); the 180° hybrid's Δ port does this natively |
| Single ADC → FPGA | No digital array processing possible | 4-channel coherent ADC (shared sample clock from GPSDO); ≥12-bit per §8.2 |
| Sample r(t), e(t) → R_rx, R_xx → W_z, W_a → SPI | Correct — this is §7 verbatim | Keep; specify update period T_u and check Δθ_lag = ω̇·T_u against §5.8 |
| Shared LO between the two front ends | Correct and essential | Keep; extend to all 4 chains + ADC clocks from the GPSDO (§9.3) |

### 12.4 Physical layout on the drone (per the CAD screenshot)

- **Array geometry:** 2×2 patches at d = 95.1 mm pitch → array spans 95×95 mm plus ground plane. Ground plane should extend ≥ λ/4 ≈ 48 mm beyond the patch edges → **≥ 190×190 mm board**. The Ø330 mm base plate accommodates this; the CRPA enclosure sits centered on it as drawn.
- **Propeller clearance:** Ø406.4 mm (16″) props on a 960 mm diagonal. Rotating blades over the antennas cause "blade flash" — periodic multipath modulation at the blade-pass frequency (2 × RPM/60 × n_blades, order of 100–400 Hz), which shows up as sidebands on R̂ and as a slowly time-varying steering perturbation. The drawn layout keeps the array in the central prop-free zone — correct; verify no blade tip crosses the array's upper-hemisphere sightlines above ~10° elevation.
- **Clock PCB placement:** the Ettus clock board sits adjacent to the enclosure — good (short, matched 10 MHz/LO distribution lines; per §9.3 the LO split must be length-matched to keep differential phase ≪ 5°, since only common-mode drift cancels).
- **EMI:** motor ESCs are PWM noise sources at L1-relevant harmonics; keep ESC power runs off the base plate, shield the CRPA enclosure (it's the "Faraday box" for the RF chains), single-point ground to the plate.
- **Mass/keep-out note:** the enclosure must not shadow the patches — antennas on the **top face** of the enclosure (or a separate top-mounted array board feeding through SMA bulkheads), with the full RF chain inside directly beneath to keep the LNA-to-patch run < a few cm.

---

## Section 13 — Architecture-Specific Extensions (Arch 1 vs Arch 3)

The core model (§1–2 array model, §5 MVDR/DOF/null-vs-Δθ, §6 headroom, §8–10) applies to both architectures. The data-acquisition and adaptation math differ. This section holds the architecture-specific pieces.

### 13.1 Arch 1 — Power Inversion and Covariance Reconstruction (single post-combiner ADC)

Arch 1 digitizes only the scalar y(t) = wᴴx(t). The available measurement per weight setting is the output power

P(w) = E[|y|²] = wᴴ·R·w

**(a) Power-inversion adaptation (default mode).** Solve

minimize_w  wᴴ·R·w   subject to  w₀ = e₀ᴴw = 1   (reference-element constraint)

By the same Lagrange argument as §5.3 with a_s replaced by e₀ = [1,0,0,0]ᵀ:

w_PI = R⁻¹·e₀ / (e₀ᴴ·R⁻¹·e₀)

Because jammers dominate R (J/S ≥ 30 dB) and GPS is 25 dB below noise (§10.2), w_PI places nulls on the jammers like MVDR, but the constraint protects element 0's response, **not** the GPS direction — the GPS gain |w_PIᴴ·a_s|² varies with geometry (gain ripple). This ripple, relative to the distortionless MVDR, is the formal price of Arch 1: ΔG_dB = 20·log₁₀|w_PIᴴ·a_s| ≤ 0, computable in closed form for any scenario — plot it across jammer geometries for the paper. Reference: Compton, "The Power-Inversion Adaptive Array," IEEE Trans. AES, 1979.

Since R is not observable, w_PI is found iteratively from scalar power readings: dither one weight component by ±Δ, estimate the gradient ∇̂P (finite differences or SPSA), step w ← w − µ·∇̂P, re-project onto w₀ = 1. Convergence/misadjustment trade: dither amplitude Δ sets both gradient SNR and steady-state null jitter; the null-depth floor from dithering is ≈ 20·log₁₀(Δ·|∂(wᴴa_j)/∂w|) — the §5.8 law with Δθ replaced by the weight-space dither. **[DERIVE for paper: optimal Δ vs detector noise.]**

**(b) Covariance reconstruction (optional, restores MUSIC).** R ∈ ℂ^{4×4} Hermitian has exactly M² = 16 real degrees of freedom. Each probe weight gives one linear equation in those unknowns:

P_i = w_iᴴ·R·w_i = vec(w_i·w_iᴴ)ᴴ · vec(R)   (linear in R's entries)

With probes {w_i}, i = 1..L ≥ 16 such that the rank-one matrices {w_i·w_iᴴ} span the 16-dimensional real space of Hermitian forms, the system P = A·r is invertible and R̂ = solve(A, P). Then §3–§5 (MUSIC + MVDR) run unchanged on the reconstructed R̂. Costs to state: (i) L dwell intervals per update (slow — jammer must be stationary across the probe sequence); (ii) variance amplification by cond(A) — probe patterns should be chosen to minimize it (e.g. DFT-like phase patterns); (iii) during probing the GPS path is deliberately mis-weighted (GPS receiver coasts on its tracking loop). The §4.3 CRLB does **not** apply to this estimator (the measurement model is quadratic-power, not linear snapshots); a new bound is needed before quoting accuracy. **[DERIVE: probe-design conditioning + variance of reconstructed-R̂ MUSIC.]**

### 13.2 Arch 3 — Inter-Chip LO Phase Model and Calibration Identity

When the 4 channels are split across two RF chips (two AD9361s), each chip b ∈ {1,2} downconverts with its own PLL-synthesized LO. The received model gains a per-chip phase factor:

x̃(t) = Γ(t)·x(t),   Γ(t) = diag( e^{jβ₁(t)}, e^{jβ₁(t)}, e^{jβ₂(t)}, e^{jβ₂(t)} )

where β_b(t) = β_b⁰ + δβ_b(t): β_b⁰ is the random phase at PLL lock (re-randomized at every retune) and δβ_b(t) is the differential phase noise outside the PLL loop bandwidth. The shared 10 MHz reference makes the *common* part of β₁, β₂ cancel per §9.3, but the *difference* β₂ − β₁ survives and rotates the steering vectors: ã(θ) = Γ·a(θ). Consequence: MUSIC peaks bias and MVDR nulls move (via §5.8, an effective Δθ ≈ (β₂−β₁)/(2πd·cosφ/λ) for sources near broadside).

**Calibration identity.** Inject a tone c(t) of known (or common-mode unknown) phase into all 4 channels simultaneously via the sense couplers' isolated ports. The received calibration snapshot is x_cal = Γ·g·c(t) + n, where g collects the static per-channel gains/phases (§9.1). The per-channel complex response ĥ_m = ⟨x_cal,m, c⟩/⟨c, c⟩ estimates Γ_mm·g_m up to one global complex constant. Normalizing to channel 0:

q_m = ĥ_m / ĥ₀  ⟹  corrected steering vector  ã_m(θ) = q_m · a_m(θ)

removes both the inter-chip offset and the §9.1 static mismatch in a single measurement — the global constant is absorbed by MVDR's scale invariance (§5.4). Residual error after cal = δβ_b(t) drift since the last cal plus cal-tone SNR error; cal must re-run at startup, after any retune, and on temperature change. (Single-LO front ends — e.g. a 4-channel chip in single-LO mode, or Arch 1's one-chain topology — satisfy β₁ = β₂ by construction and skip this entirely.)

### 13.3 Section applicability map

| Math section | Arch 1 | Arch 3 |
| :-- | :-- | :-- |
| §1–2 array model, steering, element pattern | ✅ as-is | ✅ as-is |
| §3 covariance, loading, subspaces | only via §13.1(b) reconstruction | ✅ as-is (sense ADCs) |
| §4 MUSIC + CRLB | only via §13.1(b); CRLB invalid as stated | ✅ as-is |
| §5 MVDR, DOF, null-vs-Δθ | §5 formulas once R̂ exists; default mode uses w₀=1 constraint (§13.1a) | ✅ as-is |
| §6 pre-cancellation, ADC headroom | §6.4 on the single GPS-path ADC, α = 0 during re-convergence | §6.4 on the GPS receiver's ADC; sense ADCs see unweighted jammer (AGC permitted there) |
| §7 SPLL block update | replaced by §13.1(a) dither loop | ✅ as-is |
| §9.3 shared clock | intrinsically immune (one downconversion chain) | + §13.2 inter-chip cal required |
| §10 link budget | ✅ with SAW NF update | ✅ with SAW NF update + sense-path NF |
| Delivered null depth | analog ceiling §6.2 | analog ceiling §6.2 (digital stage is sensing-only; T3 upgrade adds digital fine stage) |

---

## Answers to the Six Questions (consolidated)

1. **Sign convention:** standardize on **+j** (matches our sim); define u and r_m explicitly as in §2.2; conjugate Rahul's vectors at the interface.
2. **Diagonal loading:** not λ_min — use **δ ≈ 10·σ̂²** with σ̂² from the noise eigenvalues (Cox/Zeskind/Owen 1987, Carlson 1988). §3.3.
3. **GPSDO proof:** yes, the outer-product cancellation argument is correct and exact; caveats on differential drift in §9.3.
4. **Finite-resolution α:** model as complex weight error; C_dB ≈ −10log₁₀(ε_A² + ε_φ²); 6-bit phase ⟹ ~26–31 dB ceiling. §6.2.
5. **Mutual coupling:** Gupta & Ksienski 1983 for impact, Friedlander & Weiss 1991 for auto-cal, EM-simulated + S-parameter-measured C for the real board. §9.4.
6. **CRLB:** 2×2 FIM with projected derivatives, §4.3 — includes the corrected ∂a/∂θ and the zenith/45° observability warnings; numerical evaluation is the remaining task.

---

*End of corrected document. Version 2.1 — Fable review complete.*
*COGNAV Project — June 2026*
