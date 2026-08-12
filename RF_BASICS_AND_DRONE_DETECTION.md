# RF Basics → Drone Detection

**A ground-up guide.** Part 1 assumes you know nothing. Part 2 assumes you read Part 1.
Everything is explained in plain words first, with the maths added only after the idea is clear.

---

## Table of contents

**PART 1 — THE BASICS**
1. [The one idea behind all of it](#1-the-one-idea-behind-all-of-it)
2. [What a radio signal actually is](#2-what-a-radio-signal-actually-is)
3. [Decibels — the language of RF](#3-decibels--the-language-of-rf)
4. [The envelope](#4-the-envelope)
5. [Downsampling](#5-downsampling)
6. [The noise floor](#6-the-noise-floor)
7. [Why narrow bandwidth lowers the noise floor](#7-why-narrow-bandwidth-lowers-the-noise-floor)
8. [Estimating the noise floor from real data](#8-estimating-the-noise-floor-from-real-data)
9. [Statistics you actually need](#9-statistics-you-actually-need)
10. [Turning numbers into a yes/no decision](#10-turning-numbers-into-a-yesno-decision)

**PART 2 — ADVANCED / BROAD**
11. [The four ways to detect a drone](#11-the-four-ways-to-detect-a-drone)
12. [The RF detection ladder](#12-the-rf-detection-ladder)
13. [Finding *where* it is](#13-finding-where-it-is)
14. [Micro-Doppler and radar](#14-micro-doppler-and-radar)
15. [The full pipeline in the real world](#15-the-full-pipeline-in-the-real-world)
16. [Why it is genuinely hard](#16-why-it-is-genuinely-hard)
17. [Cheat sheet](#17-cheat-sheet)

---
---

# PART 1 — THE BASICS

## 1. The one idea behind all of it

A drone is not silent. To be flown, it must **talk to its controller** — constantly, in both directions. That conversation is radio energy leaking into the air in every direction, and anyone with a receiver can hear that *something* is being said.

You do not need to understand the words. You only need to notice:

- **that** someone is talking (is there energy that wasn't there before?)
- **where** they are talking (which frequency?)
- **how** they talk (short bursts? continuous? how often? how regular?)

That third one is the interesting one, and it is the one this document builds toward. Human traffic on a radio band is messy and irregular. A machine flying itself talks like a **metronome**. That difference is measurable, and it survives encryption — because encryption scrambles *what* you say, not *when* you say it.

> **The core insight:** you can tell a drone from a laptop without decoding a single bit, purely from the rhythm of its transmissions.

---

## 2. What a radio signal actually is

### The wave

A radio signal is an electromagnetic wave — an invisible ripple travelling at the speed of light. Two properties matter:

- **Amplitude** — how *big* the ripple is. Bigger = more power = stronger signal.
- **Frequency** — how *fast* it ripples. Measured in Hertz (Hz) = ripples per second.
  - 2.4 GHz = 2,400,000,000 ripples per second.

### Why the receiver gives you two numbers, not one

When you plug an SDR (Software Defined Radio) into your laptop, it does not hand you "the signal." It hands you a stream of **pairs** of numbers, called **I** and **Q**.

Here is the mental picture. Imagine a bicycle wheel spinning, with a reflector stuck on the rim.

```
            Q  (up/down)
            ↑
            |      ● ← the reflector
            |    ⁄
            |  ⁄  ← distance from centre = AMPLITUDE
            |⁄  θ  ← angle around the circle = PHASE
   ---------+---------→  I  (left/right)
            |
            |
```

- **I** = how far left/right the reflector is
- **Q** = how far up/down it is

From those two you can work out both things you care about:

- **Amplitude** = how far the dot is from the centre = `√(I² + Q²)`
- **Phase** = which angle around the circle it sits at = `atan2(Q, I)`

The wheel spins at the radio frequency. Amplitude is how *strong* the signal is; phase is *where in its cycle* it currently is.

### Why we write it as a complex number

`I + jQ` is just a compact way of writing the pair. The `j` is engineering notation for √−1 (mathematicians write `i`, but `i` already means current in electronics). Nothing mystical is happening — it is a 2-D coordinate with convenient algebra. That is why IQ files are stored as `complex64` (two 32-bit floats) or `sc16` (two 16-bit integers).

### Power

**Power** is amplitude squared:

```
power = I² + Q²  =  |IQ|²
```

Why squared? Because power is what actually heats a resistor, and physically that goes as the square of amplitude. It is also easier to work with — no square root, and it's always positive.

**This is the single most-used quantity in detection.** Almost everything downstream is computed from `|IQ|²`.

---

## 3. Decibels — the language of RF

You cannot read anything in RF without decibels, so let's kill this now.

### The problem dB solves

Radio powers span an absurd range. A Wi-Fi router transmits about **0.1 watts**. By the time it reaches your phone across the house it might be **0.00000001 watts**. A weak drone signal at distance might be **0.000000000000001 watts**.

Writing those numbers out is hopeless. So we use a logarithmic scale.

### The definition

```
power in dB = 10 × log₁₀(power ratio)
```

That's it. It converts multiplication into addition.

### The only three facts you need to memorise

| Change | In dB |
|---|---|
| **2× the power** | **+3 dB** |
| **10× the power** | **+10 dB** |
| **100× the power** | **+20 dB** |

And they add up:
- 4× = 2×2 = 3+3 = **+6 dB**
- 1000× = **+30 dB**
- half the power = **−3 dB**
- one-millionth = **−60 dB**

### dBm — an absolute scale

`dB` on its own is a *ratio* (twice as loud). `dBm` is measured against a fixed reference of **1 milliwatt**:

- 0 dBm = 1 mW
- +30 dBm = 1 W (a strong Wi-Fi/drone transmitter)
- −30 dBm = 1 µW (very strong received signal)
- −90 dBm = a normal weak Wi-Fi signal
- −110 dBm = right down at the noise

So when you see **"−76 dB"** in a capture log, read it as "about 40 million times weaker than a milliwatt" — but nobody thinks that way. You just learn the scale: **bigger (less negative) = stronger**.

### The 20log₁₀ trap

If you are working with **amplitude** rather than **power**, the formula is `20 × log₁₀`, because power = amplitude², and log(x²) = 2·log(x). A common source of bugs — factor-of-two errors in dB. Rule:

- power / energy / `|IQ|²` → **10·log₁₀**
- voltage / amplitude / `|IQ|` → **20·log₁₀**

---

## 4. The envelope

### The plain-English version

Put on a song. Now stop listening to the *music* and only watch the **volume meter** bouncing. The bouncing meter is the **envelope**. You have thrown away the melody, the words, the instruments — you kept only "how loud, moment to moment."

That is exactly what an envelope is in RF: **the shape of the signal's strength over time, with all the fine detail thrown away.**

```
Raw signal (2.4 billion wiggles/sec — impossible to draw):
  ||||||||||||||||||||||||        ||||||||||||||        ||||||||
  ||||||||||||||||||||||||        ||||||||||||||        ||||||||

Envelope (the outline of the above):
   ______________________          ____________          ________
  |                      |        |            |        |        |
__|                      |________|            |________|        |___
   ← packet →              ← gap →   ← packet →
```

The envelope is where **packets become visible**. You cannot see a packet in raw IQ — it is just a blur of oscillation. In the envelope it is an obvious rectangle.

### How you compute it

Three steps:

**Step 1 — Take the power.**
```python
power = np.abs(iq)**2      # = I² + Q²
```
This throws away phase and keeps only strength. Phase is where the *information* lives (the actual bits), and we deliberately do not want it — we want behaviour, not content.

**Step 2 — Smooth it.**
Raw power is extremely jumpy, because noise is random and even a steady signal fluctuates sample to sample. So you take a running average:

```python
kernel = np.ones(N) / N
smoothed = np.convolve(power, kernel, mode='same')
```

That is a **boxcar** (moving average) filter: each output = the mean of the N samples around it. It flattens the jitter and leaves the shape.

**Step 3 — Convert to dB (optional but usual).**
```python
power_db = 10 * np.log10(smoothed + 1e-30)
```
The `+ 1e-30` is a guard so you never take `log(0)`, which is −∞ and will poison every calculation downstream. **Always add an epsilon before a log or a division.**

### The smoothing trade-off

This is the choice that decides what you can see:

| Smoothing window | What you see | What you lose |
|---|---|---|
| 0.01 ms | Individual packet edges, sharp | Very noisy, false triggers |
| **0.1–0.5 ms** | Individual packets as clean blocks | Sub-packet structure |
| 2 ms | Groups of packets, general activity | Individual packets merge |
| 50 ms | Overall "is the band busy" | All burst structure — the entire point |

Smooth too little → you drown in noise. Smooth too much → the packets merge into a smear and every timing feature dies. **A good rule: your smoothing window should be a few times shorter than the shortest thing you want to see.** If packets are ~800 µs long, smoothing at 0.5 ms is fine; smoothing at 5 ms erases them.

---

## 5. Downsampling

### What it is

You have too many numbers. You throw away most of them, carefully.

At 8 MSPS ("8 mega-samples per second") you get **8 million IQ pairs every second**. A 30-second recording is 240 million samples — around **2 GB**. Doing anything per-sample in Python at that size takes minutes to hours.

Downsampling by a factor **D = 40** turns 8,000,000 samples/sec into **200,000 samples/sec**. Same 30 seconds, now 6 million samples instead of 240 million. **40× less data, 40× faster.**

### The two ways to do it

**Decimation** — keep every 40th sample, bin the rest:
```
[5, 7, 6, 8, ...] → keep index 0, 40, 80, ...
```
Fast, but it *throws information away*, and it can cause **aliasing** (see below).

**Block averaging** — average each group of 40 into one:
```python
power_ds = power[:n_trim].reshape(-1, 40).mean(axis=1)
```
```
Original:  [5, 7, 6, 8] [9, 3, 4, 4] [2, 2, 3, 1]
Averaged:      6.5           5.0          2.0
```
Slower by a hair, but it **keeps** the information as an average rather than discarding it, and it suppresses noise. For envelopes this is almost always what you want.

### Why we do it — three separate reasons

**Reason 1: Speed.** The obvious one. 40× fewer samples ≈ 40× faster, and it can be the difference between an algorithm that runs and one that doesn't. It also means the data now fits in RAM.

**Reason 2: Noise reduction.** This is the reason people forget. Averaging 40 noisy numbers gives you a much *steadier* number, because the random ups and downs partially cancel.

If each sample has noise with standard deviation σ, the average of D independent samples has standard deviation **σ/√D**.

For D = 40: `σ/√40 = σ/6.3` — the noise wobble drops to about **16%** of what it was. Your noise floor becomes a flat line instead of a fuzzy band, which makes thresholding far more reliable.

**Reason 3: You genuinely don't need the resolution.** Ask what you're trying to see. If packets are ~800 µs long, do you need 0.125 µs resolution? No. After D=40 you have 5 µs resolution — still **160 samples across every packet**. Plenty.

### What you lose

You cannot see anything faster than your new sample rate. That's the whole cost, and it is a real one:

| | Before (8 MSPS) | After D=40 (200 kSPS) |
|---|---|---|
| Time resolution | 0.125 µs | 5 µs |
| Shortest visible event | ~0.25 µs | ~10 µs |
| Data size (30 s) | 240 M samples | 6 M samples |

So if a system emits 2 µs pulses, D=40 makes them invisible. **Choose D by asking "what is the shortest thing I care about?", then make sure you still get several samples across it.**

### Aliasing — the one trap

If you decimate without filtering first, fast wiggles don't disappear — they **disguise themselves as slow wiggles**. This is aliasing.

The everyday version: film a spinning wheel with a camera. If the wheel spins faster than the camera's frame rate, it appears to spin *backwards*, or stand still. The camera is undersampling and inventing a false slow motion.

The rule (**Nyquist**): to represent a signal correctly you must sample at more than **twice** its highest frequency. If you're going to sample at 200 kHz, everything above 100 kHz must be filtered out first, or it will fold down and contaminate your data as fake low-frequency content.

**Block averaging saves you here** — averaging *is* a crude low-pass filter, so it does some of the anti-alias filtering for free. That is another reason to prefer it over plain decimation.

---

## 6. The noise floor

### What noise is

Take a radio receiver, connect nothing to it, put it in an empty field, turn it on. You still get a signal. A quiet hiss that never stops.

That is **thermal noise** — the electrical crackle of atoms jiggling because they are above absolute zero. Every conductor above 0 K produces it. It is not a fault, not interference, not bad design. It is physics, and it is the fundamental limit on how weak a signal you can ever hear.

**The noise floor is the power level of that hiss.** Any signal weaker than the floor is buried and effectively invisible.

### The analogy

You are in a room with a constant rainfall sound outside. Someone whispers.

- If the rain is quiet, you hear the whisper. → **low noise floor, signal detectable**
- If the rain is loud, the whisper vanishes. → **high noise floor, signal lost**

You have two options: make the whisper louder (more transmit power, closer range, bigger antenna) or **make the rain quieter**. Section 7 is about making the rain quieter, and it's the option you actually control.

### The formula

```
Noise power (watts) = k × T × B
```

- **k** = Boltzmann's constant = 1.38 × 10⁻²³ (a constant of nature)
- **T** = temperature in Kelvin (room temp ≈ 290 K)
- **B** = **bandwidth in Hz** ← *this is the one you control*

In dBm at room temperature this collapses to a single number worth memorising:

```
Noise floor (dBm) = −174 + 10·log₁₀(Bandwidth in Hz) + NF
```

**−174 dBm/Hz is nature's floor.** It is the quietest any receiver on Earth at room temperature can be, per hertz of bandwidth.

**NF** is the **noise figure** — how much extra hiss your own hardware adds. A great low-noise amplifier might add 1 dB. A bare SDR with no front-end might add 6–10 dB. This is exactly what an **LNA** (low-noise amplifier) buys you: placed right at the antenna, it sets the noise figure of the whole chain before cable losses can degrade it.

---

## 7. Why narrow bandwidth lowers the noise floor

This is the most important idea in the document, and it follows directly from `B` sitting in that formula.

### The bucket analogy

Imagine:
- **Noise** = rain, falling evenly everywhere, all the time.
- **Your signal** = someone pouring water from a jug, into one specific spot.

Now go and collect water.

**Wide bucket (wide bandwidth):**
```
      ☂ rain    ☂ rain    🫗 jug    ☂ rain    ☂ rain
   ┌────────────────────────────────────────────────┐
   │                  WIDE  BUCKET                  │
   └────────────────────────────────────────────────┘
   Result: all the jug water + LOTS of rain
```

**Narrow bucket, placed under the jug (narrow bandwidth):**
```
                          🫗 jug
                       ┌────────┐
                       │ NARROW │
                       └────────┘
   Result: all the jug water + a LITTLE rain
```

**Both buckets caught the same amount of jug water.** The narrow one caught far less rain. So the *ratio* of jug-water to rain-water — the **signal-to-noise ratio** — is much better in the narrow bucket.

> **The key asymmetry: noise is spread across all frequencies, so the noise you collect scales with your bandwidth. A narrowband signal is concentrated at one frequency, so the signal you collect does not.**

That asymmetry is the entire trick. Listening to *less* of the spectrum makes a weak signal *easier* to hear, not harder — as long as you're pointed at the right spot.

### The numbers

Straight from `−174 + 10·log₁₀(B)`:

| Bandwidth | Noise floor | vs 100 MHz |
|---|---|---|
| 1 Hz | −174 dBm | +80 dB better |
| 1 kHz | −144 dBm | +50 dB better |
| 1 MHz | −114 dBm | +20 dB better |
| **8 MHz** | **−105 dBm** | **+11 dB better** |
| 20 MHz | −101 dBm | +7 dB better |
| 100 MHz | −94 dBm | — |

**Narrowing from 100 MHz to 8 MHz buys you 11 dB.** That is 12× more sensitivity — roughly a **3.5× increase in detection range** in free space, for free, just by listening to less.

Every 10× narrower = 10 dB quieter.

### The same trick inside the FFT

You don't have to change your hardware to get this. An **FFT does it in software.**

An FFT splits your captured bandwidth into N narrow **bins**. Each bin is its own tiny narrow-bandwidth receiver.

Capture 8 MHz, run a 2048-point FFT:
```
Bin width = 8,000,000 / 2048 = 3,906 Hz per bin
Noise per bin = −174 + 10·log₁₀(3906) = −138 dBm
```

Compare: −105 dBm across the whole 8 MHz, but **−138 dBm inside a single bin**. That is **33 dB of free sensitivity** — and 33 dB = 10·log₁₀(2048), exactly the FFT size.

This is called **processing gain**, and it is why a spectrum analyser can show you signals that a power meter says aren't there. A narrowband transmitter dumps all its power into one or two bins, while noise spreads evenly across all 2048.

**Rule of thumb: doubling FFT size buys 3 dB.** The cost is time resolution — a bigger FFT needs a longer chunk of samples, so you see finer frequency detail but blur fast events. This is the **time–frequency uncertainty** trade, and you cannot escape it: *fine in frequency = coarse in time, and vice versa.*

### Integration — the other free gain

Averaging over **time** helps too, for the same reason: noise is random and partially cancels itself; a real signal is consistent and adds up.

Two flavours, and the difference matters:

- **Coherent integration** (average the complex IQ, keeping phase): gain = **10·log₁₀(N)**. Averaging 100 samples → **+20 dB**. Powerful, but only works if you know the signal's phase behaviour and it stays stable.
- **Non-coherent integration** (average the *power*, after throwing away phase — what envelope smoothing does): gain ≈ **5·log₁₀(N)** at low SNR. Averaging 100 → **+10 dB**.

Coherent is twice as good in dB, but it's fragile — it requires phase-locking to the signal. Non-coherent is weaker but works on anything. The penalty between them is the classic **square-law detector loss**, and it's the price of the convenience of working with envelopes.

### Summary of every knob you have

| Knob | Gain | Cost |
|---|---|---|
| Narrower RF bandwidth | 10·log₁₀(ratio) | You might miss the signal entirely |
| Bigger FFT | 10·log₁₀(N) | Worse time resolution |
| Non-coherent averaging | ~5·log₁₀(N) | Worse time resolution |
| Coherent averaging | 10·log₁₀(N) | Needs phase knowledge |
| Better LNA | Reduces NF, up to ~10 dB | Money |
| Bigger / directional antenna | Real gain, 10–20 dB+ | Size, and you must aim it |

---

## 8. Estimating the noise floor from real data

The formula gives you the *theoretical* floor. In the real world you have interference, hardware quirks, and no calibration, so you must **measure** the floor from the data itself. This is one of the most consequential choices in a detector.

### The naive approach and why it fails

```python
noise_floor = np.mean(power)     # ✗ WRONG
```

If 20% of your recording is loud bursts, those bursts drag the mean **upward**. Your "noise floor" is now partly signal. You set your threshold above it — and become blind to the very thing you're detecting. **The detector fails hardest exactly when there's most to see.** That is the worst possible failure mode.

### Better: the median

```python
noise_floor = np.median(power)   # ~ OK
```

The median is the middle value, so it ignores outliers. Immune to a few loud bursts. But if bursts occupy **more than 50%** of the time, the median itself lands inside a burst and you're back to the same problem.

### Best for dense traffic: a low percentile

```python
noise_floor = np.percentile(power, 10)   # ✓ ROBUST
```

"The level that 90% of the recording is above." As long as the band is quiet at least 10% of the time, this lands squarely in genuine noise. Robust even when bursts dominate.

**Choose by how busy your band is:**

| Band occupancy | Use |
|---|---|
| < 10% busy | mean is fine |
| < 50% busy | median |
| > 50% busy | 10th percentile (or lower) |

### Relative thresholds vs absolute

Without a calibrated receiver you have no idea what an absolute −105 dBm looks like in your ADC counts. So **never** write:

```python
if power_dbm > -95:    # ✗ meaningless without calibration
```

Always work **relative to the measured floor**:

```python
threshold = noise_floor + 8          # dB above whatever the floor is today
```

This is why detectors are written as `floor + 8 dB` or `median × 1.5`. It makes the system **self-calibrating** — move it indoors, outdoors, to a different city, change the gain, swap the antenna, and it still works, because it re-measures its own floor each time.

### Choosing the threshold offset

There is no free lunch here — it is a straight trade:

| Threshold | Effect |
|---|---|
| floor + 3 dB | Catches weak signals, **lots of false alarms** |
| floor + 6 dB | Sensitive, some false alarms |
| **floor + 8 to 10 dB** | Common sweet spot |
| floor + 15 dB | Only strong signals, misses distant ones |
| floor + 20 dB | Very confident, very deaf |

Every dB you raise it: fewer false alarms, shorter detection range. This is the **Pd/Pfa trade-off** (Section 10) and it never goes away — you only choose where to sit on it.

### CFAR — an adaptive floor

**CFAR** = Constant False Alarm Rate. Instead of one floor for the whole recording, estimate it **locally**, right next to each point you're testing.

```
        [ training ][guard][ CUT ][guard][ training ]
         ←estimate→        ↑test        ←estimate→
```

- **CUT** = Cell Under Test — the sample you're deciding about.
- **Guard cells** — skipped, so that if the signal is slightly wider than one cell it doesn't leak into your noise estimate.
- **Training cells** — averaged to estimate the local noise.

Then: `is CUT > mean(training) + threshold?`

This adapts automatically to a floor that slopes across frequency or drifts over time. It's the standard in radar.

**Its failure mode, which matters:** if the training cells are *themselves* full of signal — dense back-to-back bursts, or several emitters close together — the noise estimate inflates and the detector goes blind. This is called **self-masking** or target masking. In a crowded band, a plain global percentile threshold can genuinely outperform CFAR. Variants exist for this (OS-CFAR uses an order statistic instead of the mean; GO/SO-CFAR pick the greater/smaller of the two training sides) — but know that CFAR is not automatically the better choice.

---

## 9. Statistics you actually need

Only five ideas. Each one in plain words, then the formula.

### 9.1 Mean — the middle

Add everything up, divide by how many. The "typical" value.

```
mean(2, 4, 6, 8) = 20/4 = 5
```

**In RF:** average power, average packet rate, average packet length.

**The limitation that drives everything else:** the mean tells you *nothing about consistency*. These two are identical on average and completely different in character:

```
A: 5, 5, 5, 5, 5      → mean 5    (a metronome)
B: 1, 9, 2, 8, 5      → mean 5    (chaos)
```

Almost every interesting detection feature lives in the difference between A and B — not in the mean.

### 9.2 Standard deviation (std) — the spread

**How far, typically, things sit from the mean.**

- Small std = everything clustered near the mean = **consistent**
- Large std = values scattered widely = **erratic**

```
A: 5, 5, 5, 5, 5    → mean 5, std 0.0   ← perfectly consistent
B: 1, 9, 2, 8, 5    → mean 5, std 3.2   ← all over the place
```

**How to compute it**, step by step on B:

```
1. Mean:                      5
2. Deviation from mean:       -4, +4, -3, +3, 0
3. Square each:               16, 16, 9, 9, 0     ← squaring kills the signs
4. Mean of those = VARIANCE:  50/5 = 10
5. Square root = STD:         √10 = 3.16
```

**Why square then square-root?** Step 3 makes everything positive (otherwise +4 and −4 cancel and you'd get zero spread for a wildly varying set). Step 5 undoes the squaring so the answer comes back in the **original units**. Variance of a time in ms is in ms²  — which is meaningless to a human. Std is in ms, which you can picture.

> **Variance = std². Std = √variance.** Same information, different units. Use variance in maths, std when talking to people.

**Everyday example:** two buses both average 10 minutes.
- Bus A: 9, 10, 11, 10, 10 → std ≈ 0.6 min. You can plan your day.
- Bus B: 2, 18, 5, 15, 10 → std ≈ 6 min. Useless.

Same mean, totally different service. **Std is the number that tells you which.**

### 9.3 Coefficient of variation (CV) — spread, fairly compared

**CV = std ÷ mean**

Why you need it: std alone can mislead when the things you're comparing have different scales.

- **Bus:** every 10 min, std 2 min → 2 minutes late is a disaster
- **Train:** every 60 min, std 2 min → 2 minutes late is nothing

Same std, completely different reliability. Divide by the mean:

- Bus: 2/10 = **0.20**
- Train: 2/60 = **0.033**

The train is **6× more reliable**, and CV shows it while std hides it.

**CV is dimensionless** — no units. Which means you can compare a drone with a 125 Hz control loop directly against one with a 500 Hz loop and ask "which is more regular?" — a question raw std cannot answer.

**The reference scale you must internalise:**

| CV | Meaning | Physical picture |
|---|---|---|
| **0** | Perfect metronome | A clock ticking |
| **0.1–0.3** | Highly regular, machine-driven | **A drone's control loop** |
| **~1.0** | Completely random (Poisson) | Raindrops hitting a window |
| **> 1** | Clustered / bursty | Rain shaken off a tree in gusts |

**CV = 1 is the dividing line between "structured" and "random".** That is the single most useful reference point in this whole document.

Read it as: **below 1 = a machine. Around 1 = nature/randomness. Above 1 = something bursty and clumped, like human-driven network traffic.**

### 9.4 Covariance and correlation — do two things move together?

**Variance** is about one thing varying. **Covariance** is about *two* things varying **together**.

```
Cov(X,Y) = mean[ (X − meanX) × (Y − meanY) ]
```

Read the sign:

- **Positive** — when X is above its average, Y tends to be too. *(Temperature ↑, ice cream sales ↑)*
- **Negative** — when X is high, Y tends to be low. *(Rainfall ↑, ice cream sales ↓)*
- **Near zero** — no relationship. *(Ice cream sales and your neighbour's shoe size)*

**Problem with covariance:** its size depends on units. Measure temperature in °C or °F and the covariance changes, though the relationship didn't. So we normalise:

**Correlation coefficient:**
```
ρ = Cov(X,Y) / (stdX × stdY)
```

Always between **−1 and +1**:
- **+1** = perfect lockstep
- **0** = unrelated
- **−1** = perfect opposition

Now it's comparable across anything.

**Where covariance really matters in RF:** with multiple antennas you build a **covariance matrix** — every antenna's signal correlated against every other's. That matrix encodes the *directions* signals arrive from, because a wave hitting antenna 1 before antenna 2 creates a specific, predictable phase relationship. Algorithms like **MUSIC** and **MVDR** are, at heart, eigen-decompositions of that covariance matrix. Direction finding and adaptive nulling both live here. (See Section 13.)

### 9.5 Autocorrelation — does a signal repeat?

Correlate a signal **with a delayed copy of itself**, and sweep the delay.

```
Signal:        ▁▇▁▁▁▇▁▁▁▇▁▁▁▇▁▁▁▇▁
Shift by 4:        ▁▇▁▁▁▇▁▁▁▇▁▁▁▇▁▁▁▇▁
                   ↑ lines up perfectly → high autocorrelation at lag 4
```

- **Peak at lag τ** → the signal repeats every τ.
- Peak value near **1.0** → very strong, clean repetition.
- Peak near **0** → no repeating structure.

This is how you find hidden rhythm buried in noise, because noise does not correlate with itself at any nonzero lag, while a repeating pattern does. It finds periodicity *without you having to guess the period in advance.*

**In drone detection:** control links repeat. Rotors modulate at a repeating rate. Hop sequences repeat. Autocorrelation on the envelope surfaces all of them, and its peak tells you the period directly.

### 9.6 The Fano factor / index of dispersion — a warning

You'll meet the **Fano factor** in burst analysis. Properly defined it's:

```
Fano = Var(count in a window) / Mean(count in a window)
```

It is **dimensionless**, and 1.0 = Poisson = perfectly random.

**The common bug:** people compute it from *intervals* instead of *counts*:

```python
fano = np.var(intervals_ms) / np.mean(intervals_ms)     # ✗ has units of ms!
```

That quantity is **not dimensionless**. Switch your intervals from milliseconds to seconds and the number changes by 1000×, though nothing physical changed. Any conclusion of the form "it's below 1, therefore sub-Poisson" is then an accident of unit choice.

**The correct dimensionless version computed from intervals is CV²:**

```python
dispersion = (np.std(intervals) / np.mean(intervals))**2   # ✓ CV² — unit-safe
```

For a renewal process this equals the index of dispersion of the counts, which is what you actually meant. **If you take one practical thing from this section: use CV², not Var/Mean of intervals.**

---

## 10. Turning numbers into a yes/no decision

You have features. Now you must answer "drone: yes or no?"

### Two ways to be right, two ways to be wrong

|  | Drone really there | No drone |
|---|---|---|
| **You say YES** | ✅ True Positive (TP) | ❌ False Positive (FP) — *false alarm* |
| **You say NO** | ❌ False Negative (FN) — *missed it* | ✅ True Negative (TN) |

Two rates matter:

- **TPR** (True Positive Rate) = TP / (all real drones) — *what fraction did I catch?* Also called **recall**, **sensitivity**, or **Pd** (probability of detection).
- **FPR** (False Positive Rate) = FP / (all non-drones) — *how often do I cry wolf?* Also called **Pfa** (probability of false alarm).

**You want TPR high and FPR low, and they fight each other.** Lower the threshold → catch more drones, but also more false alarms. Raise it → fewer false alarms, but you start missing real drones. There is no setting that fixes both; there is only choosing where on the curve to sit.

Which end you choose is an **operational** decision, not a technical one:
- Airport perimeter: false alarms are expensive (you halt flights) → high threshold.
- Military forward site: a missed drone is catastrophic → low threshold, live with the noise.

### ROC and AUC

Sweep the threshold across every possible value, plot TPR against FPR at each point, and you get the **ROC curve**.

```
TPR
 1.0 |      ___________  ← great detector (hugs top-left)
     |    /
     |   /       ....  ← mediocre
     |  /   ....
     | / ...
     |/...              ← diagonal = random guessing
 0.0 +------------------→ FPR
    0.0              1.0
```

**AUC** = Area Under the Curve, a single number summarising the whole trade-off:

- **1.00** = perfect separation
- **0.90+** = strong
- **0.70** = mediocre
- **0.50** = coin flip, useless

Its cleanest interpretation: **AUC is the probability that a randomly chosen drone-present sample scores higher than a randomly chosen drone-absent sample.**

### The trap that catches everyone

If you compute AUC from **one recording**, sliced into windows, you are measuring how well you separate *slices of the same two files* — not how well you detect drones.

Everything is constant within one recording: the room, the multipath, the temperature, the gain setting, the interference, that specific airframe. A classifier can latch onto any of those and score beautifully while having learned nothing about drones.

> **AUC 0.99 on one session means "these two files are different." It does not mean "I can detect drones."**

The honest test is **cross-session**: train on Monday's data, test on Tuesday's. Different room, different drone, different day. The number will drop — that drop is the real information, and reporting it is what separates engineering from self-deception.

Related habits worth building:
- **Leave-one-session-out** cross-validation, not leave-one-window-out.
- Report the **confusion matrix**, not just accuracy — accuracy is meaningless when classes are imbalanced (99% of the time there's no drone, so "always say no" scores 99%).
- State the **operating point** (the actual TPR and FPR you'd deploy at), not just AUC.

---
---

# PART 2 — ADVANCED / BROAD

*How drone detection is done in the field, generally — independent of any one system.*

---

## 11. The four ways to detect a drone

| Method | How it works | Range | Strengths | Weaknesses |
|---|---|---|---|---|
| **RF (passive)** | Listen for the control/video link | 1–5 km+ | Cheap, long range, silent, no licence needed, identifies model | **Blind to RF-silent drones** |
| **Radar (active)** | Transmit, analyse the echo | 0.5–10 km | Works on any physical drone, gives range + velocity | Expensive, needs a licence, confuses birds, poor at low altitude |
| **Acoustic** | Microphone array hears the rotors | 100–500 m | Cheap, works on autonomous drones, no line of sight needed | Very short range, useless in wind or urban noise |
| **EO/IR (cameras)** | Visual / thermal + computer vision | 0.5–3 km | Visual confirmation, identifies payload | Needs line of sight, fails in fog/night/clutter, narrow field of view |

**Nobody serious uses one alone.** Real counter-UAS systems **fuse** them: RF cues the direction → radar confirms and tracks → camera slews to that bearing for visual ID → operator decides. Each covers the others' blind spots.

The RF/acoustic pairing is especially important: RF finds the drone at long range but goes deaf if the drone is autonomous; acoustics is short-range but *cannot* be evaded by turning off the radio, because rotors must make noise to make lift.

---

## 12. The RF detection ladder

Roughly ordered from crudest to most sophisticated. Real systems stack several.

### Rung 1 — Energy detection (the radiometer)

"Is there more power than usual?"

Measure power, compare to the noise floor, alarm if it exceeds a threshold.

- ✅ Trivial to build, needs no knowledge of the signal, works on anything
- ❌ Cannot tell a drone from a microwave oven
- ❌ Hits the **SNR wall**: below a certain SNR, uncertainty in your own noise floor estimate exceeds the signal, and *no amount of extra integration time fixes it*. This is a hard theoretical limit, not an engineering one.

Useful as a first-stage trigger. Never sufficient alone in a busy band.

### Rung 2 — Spectral shape / occupied bandwidth

"What does it look like in frequency?"

Different emitters have different footprints:
- **Wi-Fi**: 20/40 MHz wide, contiguous OFDM, sits still on channels 1/6/11
- **Bluetooth**: 1–2 MHz, hops 1600 times/sec across 79 channels
- **Drone control link**: often 1–10 MHz, frequency-hopping
- **Drone video downlink**: 10–20 MHz, more continuous, higher duty cycle

Measure **occupied bandwidth**, **spectral flatness** (noise-like vs tonal), **shape**, and where it sits, and you can already separate broad families.

- ✅ Cheap, interpretable, good at rejecting Wi-Fi
- ❌ Defeated by anything that changes frequency or mimics Wi-Fi (and many drones deliberately *are* Wi-Fi)

### Rung 3 — Protocol / waveform identification

"Which exact radio is this?"

Detect and decode the specific protocol:

| Protocol | Used by | Notes |
|---|---|---|
| **OcuSync / Lightbridge** | DJI | Proprietary; well-studied |
| **DJI DroneID** | DJI | **Broadcasts serial number, drone GPS position, *and operator GPS position* — largely unencrypted.** Reverse-engineered publicly. |
| **Wi-Fi (802.11)** | Many consumer drones | Identify by SSID patterns, MAC OUI vendor prefix |
| **ExpressLRS / CRSF** | FPV / hobbyist | Open source, LoRa-based, very agile |
| **FrSky ACCST/ACCESS** | Hobbyist | FHSS |
| **Remote ID** | Legally mandated (US/EU) | Broadcast Bluetooth/Wi-Fi ID beacon |

- ✅ Extremely reliable when it hits — you get make, model, often serial and position
- ❌ Only works for protocols you've already reverse-engineered; a firmware update or a custom link defeats it
- ❌ Useless against a bespoke or military link

Note the asymmetry: **Remote ID and DroneID make cooperative drones trivially detectable.** They are a compliance mechanism, not a security one — anyone intending harm simply disables them. So protocol ID solves the easy 95% and none of the hard 5%.

### Rung 4 — Cyclostationary detection

"Does the signal's *statistics* repeat, even when the signal itself looks like noise?"

Digital signals contain hidden periodicities — the symbol rate, the carrier, the cyclic prefix in OFDM, the frame structure. These make the signal **cyclostationary**: its mean and autocorrelation vary *periodically* with time, even though the data payload is random.

Computing the **spectral correlation function** (or cyclic autocorrelation) reveals sharp features at those cyclic frequencies. Noise, being truly stationary, has none — it produces nothing off the zero-cycle axis.

- ✅ Works **below the noise floor**, where energy detection is dead
- ✅ Beats the SNR wall, because it doesn't depend on knowing the noise level
- ✅ Separates overlapping signals with different symbol rates
- ❌ Computationally heavy
- ❌ Needs a reasonably long observation window

This is the standard technique in cognitive radio and low-probability-of-intercept work, and it is the most under-used tool in amateur drone detection.

### Rung 5 — Behavioural / traffic analysis

"Never mind the content — what is the *rhythm*?"

Extract, from bursts alone: packet rate, duty cycle, inter-arrival time distribution, timing regularity (CV/CV²), packet length distribution, and how all of those change over time.

The physics behind why it works: **a flying drone runs a hard real-time control loop.** It must exchange state with its controller on a fixed schedule, or it falls out of the sky. That constraint produces a signature — highly regular, machine-paced transmission — that human-driven traffic simply does not have. Web browsing, video streaming, file transfers are all bursty and demand-driven (CV > 1). A control loop is metronomic (CV ≪ 1).

- ✅ **Works perfectly through encryption** — you never touch the payload
- ✅ Protocol-agnostic; works on links you've never seen before
- ✅ Distinguishes *states* (idle / armed / flying), not just presence
- ❌ Needs enough packets to build statistics (typically seconds, not milliseconds)
- ❌ Defeatable by a defender who deliberately shapes their traffic (constant-rate transmission, padding, cover traffic)

This is the same family of technique as website fingerprinting over Tor and encrypted-VoIP analysis: **metadata leaks even when content doesn't.** It is the strongest general answer to "the drone is encrypted, now what?"

### Rung 6 — Machine learning on time–frequency images

"Let a neural network look at the spectrogram."

Turn the IQ into a spectrogram (a 2-D image of frequency vs time, brightness = power), and feed it to a CNN — the same architecture used for photo classification.

- ✅ Learns patterns humans wouldn't think to hand-code
- ✅ State of the art on benchmark datasets
- ❌ **Data-hungry** — needs thousands of labelled captures across many conditions
- ❌ Generalises badly: train in one environment, deploy in another, and performance can collapse
- ❌ Black box — you can't explain a detection to an operator or a court
- ❌ Easy to fool yourself: if all your drone captures are from Tuesday and all your no-drone captures from Wednesday, the network learns *the day*, not the drone

Hand-crafted features (Rung 5) generalise better and are explainable; CNNs score higher when you have the data. Serious systems use both, and use the hand-crafted features to sanity-check the network.

### Rung 7 — RF fingerprinting (individual transmitter ID)

"Not *what kind* of radio — *which specific unit*."

Every transmitter has manufacturing imperfections unique to that physical device:
- **IQ imbalance** — I and Q paths not perfectly matched in gain/phase
- **Carrier frequency offset** — the crystal is never exactly on frequency
- **Phase noise** — oscillator jitter
- **Power amplifier nonlinearity** — the distinctive way it distorts at high drive
- **Turn-on transients** — the microsecond-scale shape as the PA powers up

These are analogue side-effects of manufacturing tolerance. They are **impossible to remove in firmware** and hard to spoof without different physical hardware.

- ✅ Distinguishes two identical drones off the same production line
- ✅ Supports "have we seen this specific airframe before?" and re-identification across sessions
- ❌ Sensitive to temperature, ageing, and receiver hardware
- ❌ Needs a prior enrolment of that specific device
- ❌ Requires high SNR and careful calibration

---

## 13. Finding *where* it is

Detection tells you a drone exists. Operators need a **bearing**, and ideally a position.

### Angle of Arrival (AoA / DoA)

Use **multiple antennas**. A wave arriving at an angle hits one antenna slightly before the next, creating a measurable **phase difference**.

```
              incoming wavefront
        \   \   \   \   \   \
         \   \   \   \   \   \
          ●----●----●----●----●     antenna array
          ↑    ↑
      arrives  arrives slightly later
       first   → phase difference → angle
```

For a uniform linear array with spacing `d`, the phase difference between adjacent elements is:

```
Δφ = 2π · (d/λ) · sin(θ)
```

Solve for θ and you have the bearing. Key constraint: **d ≤ λ/2**, otherwise multiple angles produce the same phase difference and you get ambiguous "grating lobes."

**The algorithms, in increasing sophistication:**

- **Conventional beamforming (Bartlett)** — steer the array in each direction, see which is loudest. Simple, robust, poor resolution (limited by array aperture).
- **MVDR / Capon** — steer toward the target *while actively nulling* everything else. Much sharper. Needs the covariance matrix (Section 9.4).
- **MUSIC** — eigen-decompose the covariance matrix, split it into "signal subspace" and "noise subspace," then scan for directions orthogonal to the noise subspace. **Super-resolution**: can separate sources closer together than the classical beamwidth. The standard workhorse.
- **ESPRIT** — exploits rotational invariance between two identical sub-arrays. Gives a closed-form answer with no scanning, so it's faster than MUSIC.

All of them require **coherent multi-channel receive** — every channel sampled by the same clock with a known, stable phase relationship. That is the hard hardware requirement, and it's why a KrakenSDR (5 phase-coherent receivers) exists as a category distinct from 5 separate SDRs.

### Time Difference of Arrival (TDOA)

Multiple receivers, **far apart**, sharing precise time (GPS-disciplined clocks). The signal reaches each at slightly different times. Each pair of receivers gives you a hyperbola of possible positions; three or more receivers intersect to a point.

- ✅ Gives an actual **position**, not just a bearing
- ✅ Works over wide areas
- ❌ Needs nanosecond-level time sync (1 ns error ≈ 30 cm)
- ❌ Needs infrastructure at multiple sites and a data link between them

### Frequency Difference of Arrival (FDOA)

Uses Doppler shift differences between receivers to get velocity. Usually paired with TDOA.

### RSSI trilateration

Just use received signal strength and assume power falls off predictably with distance. **Cheap and unreliable** — multipath, fading, antenna orientation, and obstacles all wreck the assumption. Useful for a very rough "near or far," nothing more.

### Practical reality

Bearing-only from one site is usually enough operationally: it tells you where to point the camera and where to send the interceptor. Two sites with AoA cross-fix to a position without needing TDOA's timing infrastructure — this is often the sweet spot on cost.

---

## 14. Micro-Doppler and radar

The active approach, and the only one immune to an RF-silent drone.

**Basic Doppler:** transmit, and the echo comes back frequency-shifted in proportion to the target's radial velocity. That gives you the drone's bulk motion.

**Micro-Doppler** is the clever part. The rotor blades are *also* moving — fast, and periodically. Each blade advances toward you then retreats, at hundreds of revolutions per second. This adds a **family of sidebands** around the main Doppler return, with structure at:

```
blade-pass frequency = (number of blades) × (RPM / 60)
```

For a 2-blade rotor at 6000 RPM: 2 × 100 = **200 Hz**.

That signature is the discriminator:

| Target | Micro-Doppler signature |
|---|---|
| **Drone** | Strong, symmetric, *stable* rotor sidebands, and typically **4+ independent rotors** |
| **Bird** | Wing-beat modulation — irregular, intermittent, much lower frequency (a few Hz), and it stops when the bird glides |
| **Car / person** | Very different, low-frequency limb or wheel modulation |

This is the standard way radar solves the **bird-versus-drone** problem, which is otherwise the single biggest source of false alarms in the field.

**Why it's hard:**
- Drones have a **tiny radar cross-section** — often 0.01 m² or less, comparable to a large bird
- Plastic/carbon airframes reflect poorly
- Low-altitude flight means fighting ground clutter
- Small drones fly slowly and can hover, so they can sit in the **zero-Doppler notch** where clutter-rejection filters throw them away along with the trees

Note the contrast with RF: an RF envelope *cannot* reliably see rotor blade modulation, because the rotors don't transmit — any apparent rotor rate in a passive RF envelope is more likely body-shadowing, vibration-induced antenna movement, or coincidence. **Micro-Doppler is a radar phenomenon; treat rotor-rate claims from passive RF with heavy scepticism.**

---

## 15. The full pipeline in the real world

Every deployed counter-UAS system follows roughly this chain:

```
   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌────────┐   ┌────────────┐
   │  DETECT  │ → │ CLASSIFY │ → │ LOCALISE │ → │ TRACK  │ → │  MITIGATE  │
   └──────────┘   └──────────┘   └──────────┘   └────────┘   └────────────┘
   "something"    "it's a drone" "bearing 47°"   "heading    "jam / capture
                  "not a bird"   "1.2 km"         toward us"  / hand to human"
```

**1. Detect** — something is there. Optimise for high sensitivity; false alarms are acceptable here because later stages filter them.

**2. Classify** — is it a drone? Which type? Friend or foe? This is where most of the value is, and where most systems are weakest.

**3. Localise** — bearing, and ideally position and altitude.

**4. Track** — associate detections over time into a trajectory. Usually a **Kalman filter** or particle filter, which smooths noisy measurements into a coherent path and lets you predict where the drone will be next. Tracking also massively reduces false alarms: a real drone produces a *physically plausible, continuous* trajectory; noise produces detections that jump around randomly and don't persist.

**5. Mitigate** — jam, spoof, net-capture, or (most often, and most legally) simply alert a human who makes the decision.

**Legal reality worth knowing:** in most jurisdictions, *detecting* is legal, but *jamming* is a serious offence and often restricted to state actors even on your own property. Intercepting and decoding the content of a communication may also be illegal — which, incidentally, is another reason behavioural analysis (Rung 5) is attractive: it never touches the payload.

**Performance is quoted as:**
- **Pd** — probability of detection, at a stated range and Pfa
- **Pfa** — false alarm rate, usually per hour
- **Detection range**, per drone class and environment
- **Latency** — detection to alert
- **Track continuity** — how often a track is dropped and re-acquired

Always ask *"at what range, against which drone, in what environment?"* Any vendor number without those three is meaningless.

---

## 16. Why it is genuinely hard

**1. The RF-silent drone.** Pre-programmed GPS waypoints, or fibre-optic spool control (increasingly common in conflict zones), emits **nothing**. Every passive RF technique in Section 12 fails completely. This is the fundamental limit, and it's why acoustic and radar remain necessary.

**2. Crowded spectrum.** The 2.4 GHz ISM band contains Wi-Fi, Bluetooth, Zigbee, cordless phones, wireless cameras, baby monitors, and microwave oven leakage. Your drone is one faint voice in a stadium.

**3. Multipath.** Signals bounce off buildings and ground and arrive multiple times at slightly different delays. This causes deep fades (the signal briefly vanishes), corrupts phase-based direction finding, and makes power an unreliable proxy for distance.

**4. Low SNR at range.** Free-space path loss goes as 1/r², so doubling the range quarters the power (−6 dB). Detection range is set by the noise floor, which is why Section 7 matters so much operationally.

**5. Frequency agility.** FHSS drones hop hundreds or thousands of times per second across the band. Park on one narrow channel and you catch a small fraction of packets; watch the whole band and your noise floor rises. This is a direct, unavoidable tension between Section 7's advice and Section 12's needs.

**6. Birds.** A gull at 500 m looks a lot like a quadcopter to a radar. Micro-Doppler is the answer, but it needs adequate SNR and dwell time.

**7. Swarms.** Multiple drones produce interleaved transmissions. Interleaving two regular processes produces something that looks *irregular* — so timing features (CV, Fano) degrade badly when several drones are present. Separating them usually requires the frequency or spatial dimension, not the time dimension.

**8. Adaptive adversaries.** A defender who knows your detection method can shape their emissions to defeat it: constant-rate transmission to kill timing features, packet padding to kill length features, spread-spectrum to drop below the noise floor, decoy emitters to waste your attention. **Every detection feature you rely on is a feature someone can deliberately flatten.**

**9. The base-rate problem.** Drones are rare. If a drone appears once per week but your detector has a 1-in-10,000 false alarm rate on 1-second windows, you get ~60 false alarms per week and one real detection. Operators stop trusting the alarm — and an ignored alarm is worse than no alarm. **This is why false-alarm rate, not detection rate, is usually the metric that decides whether a system is actually usable.**

---

## 17. Cheat sheet

### Concepts

| Term | In one line |
|---|---|
| **IQ** | Two numbers per sample: the signal as a point on a spinning circle |
| **Amplitude** | `√(I²+Q²)` — how strong |
| **Phase** | `atan2(Q,I)` — where in its cycle |
| **Power** | `I²+Q²` — amplitude squared; the workhorse quantity |
| **Envelope** | Signal strength over time, fine detail smoothed away |
| **Downsampling** | Fewer samples: faster, smoother, at the cost of time resolution |
| **Aliasing** | Fast wiggles disguised as slow ones after bad downsampling |
| **Noise floor** | The permanent background hiss; nothing below it is visible |
| **kTB** | Noise = Boltzmann × temperature × **bandwidth** |
| **Processing gain** | Free sensitivity from narrowing bandwidth (FFT) or averaging in time |
| **CFAR** | A noise floor estimated locally instead of globally |
| **SNR** | Signal-to-noise ratio; the number that decides everything |
| **Mean** | The typical value |
| **Variance** | Mean squared distance from the mean (units²) |
| **Std** | √variance — spread, in the original units |
| **CV** | std/mean — spread, dimensionless, comparable across scales |
| **Covariance** | Do two things move together? |
| **Correlation** | Covariance normalised to −1…+1 |
| **Autocorrelation** | Does a signal repeat, and with what period? |
| **Fano / IDC** | Var/Mean of *counts*; 1.0 = random. From intervals, use **CV²** |
| **TPR / Pd** | Fraction of real drones caught |
| **FPR / Pfa** | Fraction of false alarms |
| **ROC / AUC** | The whole TPR-vs-FPR trade-off, summarised in one number |

### Numbers to know by heart

```
+3 dB   = 2× power                  −174 dBm/Hz = thermal noise floor at room temp
+10 dB  = 10× power                 Noise (dBm) = −174 + 10·log₁₀(B) + NF
+20 dB  = 100× power

Noise floor:   1 MHz → −114 dBm     Averaging D samples → noise wobble ÷ √D
               8 MHz → −105 dBm     FFT of size N       → +10·log₁₀(N) dB gain
             100 MHz →  −94 dBm     2048-pt FFT         → +33 dB

CV = 0     metronome                Doubling range = −6 dB received power
CV ≈ 0.2   a drone control loop     Antenna spacing must be ≤ λ/2 for AoA
CV = 1     pure randomness          λ at 2.4 GHz = 12.5 cm  (so d ≤ 6.25 cm)
CV > 1     bursty, clumped
```

### The rules that save you

1. **Always add an epsilon before `log()` or division.** `+1e-30` costs nothing and prevents `-inf` poisoning your whole pipeline.
2. **Estimate the noise floor with a percentile, not the mean,** whenever the band might be busy.
3. **Make every threshold relative to the measured floor,** never an absolute dBm, unless your receiver is calibrated.
4. **Smooth a few times finer than the shortest thing you want to see** — no more.
5. **Normalise before comparing.** Use CV, not std. Use CV², not Var/Mean of intervals.
6. **CV = 1 is the line** between machine-like and random.
7. **Validate across sessions, not across windows.** Same-recording AUC is a measure of your recording, not your detector.
8. **Report the false alarm rate.** It is usually what decides whether a system is deployable.
9. **Every feature you depend on is a feature an adversary can flatten.** Assume they will.

---

*End of document.*
