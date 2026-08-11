#!/usr/bin/env python3
"""gpsfix.py -- GPS L1 C/A on one USRP B210 RX channel, through to lat/lon.

WHAT THIS IS FOR: a single antenna on ONE B210 receive channel, through an
external RF front end (RFFE: LNA + L1 filter, and the DC bias the B210 cannot
supply), decoded all the way to a position. Defaults match this project's board:

    serial 34D04E6, channel 1 (RF B), antenna RX2, 1575.42 MHz, 4 MSPS

This is deliberately NOT the CRPA path. hardnull/usrpdoa/usrpgps all need four
sample-aligned channels, a shared 10 MHz reference and a PPS edge. This needs
one channel and a sky view, because a single channel on a single board is
self-coherent by construction. It isolates one question -- "does this antenna
chain produce a fix?" -- from every unresolved array variable.

STAGES (run them in this order; --run does all of them):

    --probe     what the radio reports: channels, antenna ports, gain range.
    --record    capture IQ from channel 1 / RX2 to disk, with a level report.
    --acq       search the recording for every PRN. Answers "are satellites
                actually in this capture?" in seconds, with no gnss-sdr and no
                build step.
    --fix       hand the recording to gnss-sdr, decode the navigation message,
                solve PVT, print lat/lon.

WHY RECORD-THEN-PROCESS RATHER THAN LIVE STREAMING: a file is deterministic and
re-runnable. When a fix fails you re-run the same samples against different loop
bandwidths and gains instead of re-flying the experiment, and --acq separates
the two failures that look identical from the outside: link budget (no
satellites in the capture at all) versus tracking (satellites clearly present,
gnss-sdr still not locking). --live exists for continuous operation once the
chain is known good.

WHY --acq MATTERS AND A SPECTRUM PLOT NEVER CAN: GPS L1 arrives at about
-130 dBm, roughly 20 dB BELOW thermal noise in a 2 MHz band, spread by a
1023-chip code. No power measurement can see it -- this is the same reason the
detection gates in hardnull.cpp and usrpdoa.cpp never trip on GPS. Correlating
one millisecond against the satellite's own code collapses that spread energy
into a single peak and buys about 43 dB, which is the only reason the signal is
recoverable at all.

THE RFFE IS THE WHOLE POINT. This project's record has the passive GC_ANT22_V1
patches acquiring real PRNs but cycling locks, and names the remedy: an L1 LNA
per channel. The B210's RX2 port supplies no DC, so an active antenna must be
fed from the RFFE or an external bias-T. If there is no fix, read the level
report from --record before touching a loop bandwidth.

Build-free: pure Python + numpy. gnss-sdr is needed only for --fix / --live.

    ./gpsfix.py --selftest              # no radio, no gnss-sdr: verifies the DSP
    ./gpsfix.py --probe
    ./gpsfix.py --run --seconds 120     # record -> acquire -> fix
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

import numpy as np

# =====================================================================
# SECTION 1 -- CONSTANTS
# =====================================================================

L1_HZ = 1575.42e6
CODE_RATE_HZ = 1.023e6
CODE_LEN_CHIPS = 1023
CODE_PERIOD_S = 1.0e-3

DEFAULT_SERIAL = "34D04E6"
DEFAULT_CHANNEL = 1
DEFAULT_ANTENNA = "RX2"
DEFAULT_SUBDEV = ""          # empty -> keep UHD's default spec, index by channel
DEFAULT_FS = 4.0e6           # matches gpsacq.cpp SAMPLE_RATE so results compare
DEFAULT_BW = 4.0e6

# gpsacq.cpp uses RX_GAIN = 40.0, and with an RFFE carrying its own LNA that is
# the right neighbourhood. The gain=70 in usrp_gps_l1.conf was chosen for BARE
# PASSIVE PATCHES; applied to an amplified front end it drives the B210 into
# compression, which looks exactly like "no satellites".
DEFAULT_GAIN = 40.0

# +/-10 kHz covers satellite Doppler (+/-5 kHz) plus the B210 TCXO's +/-2 ppm,
# which at L1 is +/-3.15 kHz. Do not narrow it unless the board is running on a
# disciplined reference.
DEFAULT_DOPPLER_MAX = 10000.0
DEFAULT_DOPPLER_STEP = 250.0
# 4 ms coherent x 20 accumulated groups = an 80 ms window, which measures a
# detection floor near 28 dB-Hz -- comfortably below the 35-45 dB-Hz a working
# active antenna delivers, so a failure here is unambiguous. See acquire() for
# why both numbers have to move together.
DEFAULT_NONCOH_MS = 80
DEFAULT_COH_MS = 4
# Per-PRN false-alarm probability. Across 32 PRNs this expects 0.03 false
# detections per search. The detection threshold is DERIVED from this and the
# dwell (see cfar_threshold), never fixed.
DEFAULT_PFA = 1e-3
DEFAULT_ACQ_THRESHOLD_DB: float | None = None

# ADC fill targets as a fraction of full scale. GPS is noise-like, so the RMS
# must sit well below full scale to leave headroom for ~4 sigma peaks; too low
# and the ADC's own quantisation noise starts to eat the margin.
LEVEL_RMS_MIN = 0.01
LEVEL_RMS_MAX = 0.15
LEVEL_CLIP_MAX = 1e-4

# The 32 C/A G2 phase-select tap pairs, IS-GPS-200 Table 3-I.
G2_TAPS = [
    (2, 6), (3, 7), (4, 8), (5, 9), (1, 9), (2, 10), (1, 8), (2, 9),
    (3, 10), (2, 3), (3, 4), (5, 6), (6, 7), (7, 8), (8, 9), (9, 10),
    (1, 4), (2, 5), (3, 6), (4, 7), (5, 8), (6, 9), (1, 3), (4, 6),
    (5, 7), (6, 8), (7, 9), (8, 10), (1, 6), (2, 7), (3, 8), (4, 9),
]

# First 10 chips of each PRN in octal, IS-GPS-200 Table 3-I. --selftest checks
# the generator against this. It is the standard way to catch a wrong tap pair,
# which otherwise yields a plausible-looking code that correlates with nothing.
CA_FIRST10_OCTAL = [
    "1440", "1620", "1710", "1744", "1133", "1455", "1131", "1454",
    "1626", "1504", "1642", "1750", "1764", "1772", "1775", "1776",
    "1156", "1467", "1633", "1715", "1746", "1763", "1063", "1706",
    "1743", "1761", "1770", "1774", "1127", "1453", "1625", "1712",
]

IQ_FORMATS = ("sc16", "fc32")
SC16_FULL_SCALE = 32767.0


# =====================================================================
# SECTION 2 -- C/A CODE
# =====================================================================

_CA_CACHE: dict[int, np.ndarray] = {}


def ca_code(prn: int) -> np.ndarray:
    """The 1023-chip C/A code for `prn`, as 0/1 int8."""
    if prn < 1 or prn > 32:
        raise ValueError(f"PRN must be 1..32, got {prn}")
    hit = _CA_CACHE.get(prn)
    if hit is not None:
        return hit

    tap_a, tap_b = G2_TAPS[prn - 1]
    g1 = [1] * 10
    g2 = [1] * 10
    out = np.empty(CODE_LEN_CHIPS, dtype=np.int8)
    for i in range(CODE_LEN_CHIPS):
        out[i] = g1[9] ^ g2[tap_a - 1] ^ g2[tap_b - 1]
        fb1 = g1[2] ^ g1[9]
        g1 = [fb1] + g1[:9]
        fb2 = g2[1] ^ g2[2] ^ g2[5] ^ g2[7] ^ g2[8] ^ g2[9]
        g2 = [fb2] + g2[:9]

    _CA_CACHE[prn] = out
    return out


def ca_bipolar(prn: int) -> np.ndarray:
    """C/A code mapped to +1/-1 float64 (chip value 0 -> +1)."""
    return 1.0 - 2.0 * ca_code(prn).astype(np.float64)


def ca_sampled(prn: int, fs: float, n_samples: int, chip_offset: float = 0.0) -> np.ndarray:
    """`prn`'s code sampled at `fs`, nearest-chip (no interpolation).

    `chip_offset` shifts the code in chips. The code wraps every 1023 chips, so
    any offset is valid and the result stays periodic at 1 ms.
    """
    idx = np.arange(n_samples, dtype=np.float64) * (CODE_RATE_HZ / fs) + chip_offset
    chips = np.floor(idx).astype(np.int64) % CODE_LEN_CHIPS
    return ca_bipolar(prn)[chips]


# =====================================================================
# SECTION 3 -- ACQUISITION
# =====================================================================

@dataclass
class AcqResult:
    prn: int
    detected: bool
    doppler_hz: float
    code_phase_samples: float
    code_phase_chips: float
    peak_to_floor_db: float
    peak_to_second_db: float
    cn0_dbhz: float
    threshold_db: float = 0.0
    coherent_ms: int = 1
    groups: int = 1


def _doppler_grid(dmax: float, dstep: float) -> np.ndarray:
    n = int(math.floor(dmax / dstep))
    return np.arange(-n, n + 1, dtype=np.float64) * dstep


def _chi2_even_tail_log(dof_half: int, x: float) -> float:
    """log P(X > x) for chi-squared with 2*dof_half degrees of freedom.

    Closed form for even DOF: P = exp(-x/2) * sum_{k<G} (x/2)^k / k!, summed in
    the log domain because (x/2)^k overflows long before the product does.
    """
    if x <= 0.0:
        return 0.0
    h = x / 2.0
    log_h = math.log(h)
    log_terms = [k * log_h - math.lgamma(k + 1) for k in range(dof_half)]
    peak = max(log_terms)
    log_sum = peak + math.log(sum(math.exp(t - peak) for t in log_terms))
    return -h + log_sum


def cfar_threshold(groups: int, n_cells: int, pfa: float = 1e-3) -> float:
    """Peak/mean-floor ratio giving false-alarm probability `pfa` per PRN.

    THIS IS NOT A CONSTANT, and treating it as one is the classic way to make an
    acquisition search lie. Under noise the accumulator over `groups`
    non-coherent sums is chi-squared with 2*groups degrees of freedom. Few
    groups means a heavy tail, so the largest of ~324k searched cells routinely
    sits 9 dB above the mean with no satellite present -- which is exactly the
    fixed threshold a 1 ms/10 ms search gets away with. Deriving the threshold
    from `groups` keeps the false-alarm rate fixed as the dwell changes.
    """
    target = math.log(max(pfa, 1e-300) / max(n_cells, 1))
    lo, hi = 1.0, 1000.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if _chi2_even_tail_log(groups, 2.0 * groups * mid) > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def acquire(
    iq: np.ndarray,
    fs: float = DEFAULT_FS,
    prns: list[int] | None = None,
    noncoherent_ms: int = DEFAULT_NONCOH_MS,
    coherent_ms: int = DEFAULT_COH_MS,
    doppler_max: float = DEFAULT_DOPPLER_MAX,
    doppler_step: float = DEFAULT_DOPPLER_STEP,
    threshold_db: float | None = DEFAULT_ACQ_THRESHOLD_DB,
    pfa: float = DEFAULT_PFA,
) -> list[AcqResult]:
    """Parallel code-phase search, coherent over `coherent_ms` then accumulated.

    HOW THE TWO DWELLS ACTUALLY TRADE, measured on synthetic captures at a fixed
    CFAR false-alarm rate (the numbers move if you fix the threshold instead,
    which is how this is usually got wrong):

      * Raising COHERENT length while EXTENDING the window to keep the number of
        non-coherent groups constant is a real ~3 dB per doubling:
        1/2/4/10 ms over 20 groups detects to 34/30/28/26 dB-Hz.
      * Raising COHERENT length inside a FIXED window is close to neutral.
        Coherent gain goes up, but fewer groups remain, the noise tail gets
        heavier, and the CFAR threshold rises by almost exactly as much:
        1/2/4/10 ms in 20 ms all land within a couple of dB of each other.
      * Adding NON-COHERENT milliseconds alone barely moves the floor. The
        peak-to-mean-floor ratio is (S+N)/N no matter how many magnitudes are
        summed, since the signal cell and the noise cells grow together; what
        improves is the threshold, via the lighter tail.

    So: to hear a weaker satellite, lengthen the coherent dwell AND the window
    together. The ceiling on the coherent dwell is the 50 Hz navigation data --
    a bit flip inside the window cancels the sum -- which is why 4 ms is the
    usual compromise and what this tool writes into the gnss-sdr config.

    The signal FFT does not depend on the PRN, so it is computed once per
    (Doppler, millisecond) and reused across all 32 codes. That inversion keeps
    a full 32-PRN search over 81 Doppler bins in the seconds range.
    """
    if prns is None:
        prns = list(range(1, 33))

    spms = int(round(fs * CODE_PERIOD_S))
    available_ms = len(iq) // spms
    total_ms = min(noncoherent_ms, available_ms)
    coh = max(1, min(coherent_ms, total_ms))
    groups = total_ms // coh
    if groups < 1:
        raise ValueError(
            f"need at least {coh * spms} samples ({coh} ms) to acquire, "
            f"have {len(iq)}"
        )
    blocks = groups * coh

    x = np.asarray(iq[: blocks * spms], dtype=np.complex64).reshape(blocks, spms)

    # Conjugated code spectra, one row per PRN.
    code_fft = np.conj(
        np.fft.fft(np.stack([ca_sampled(p, fs, spms) for p in prns]), axis=1)
    ).astype(np.complex64)

    dopplers = _doppler_grid(doppler_max, doppler_step)
    # Time runs continuously across the whole window, NOT restarting each
    # millisecond. Coherent summation across blocks is only valid if the
    # Doppler phase advance between them is carried through.
    t = (np.arange(blocks * spms, dtype=np.float64) / fs).reshape(blocks, spms)
    coh_s = coh * CODE_PERIOD_S

    if threshold_db is None:
        threshold_db = 10.0 * math.log10(
            cfar_threshold(groups, spms * len(dopplers), pfa)
        )

    # A full [prn, doppler, code_phase] cube would be far too large to hold, so
    # only the running best per PRN is kept.
    best_val = np.full(len(prns), -np.inf)
    best_dop = np.zeros(len(prns))
    best_phase = np.zeros(len(prns), dtype=np.int64)
    best_floor = np.ones(len(prns))
    best_second = np.ones(len(prns))

    # The correlation triangle is 2 chips wide, so its own skirt must be
    # excluded when measuring the noise floor or it hides a real detection.
    guard = max(1, int(round(fs / CODE_RATE_HZ)))

    for fd in dopplers:
        mix = np.exp(-2j * math.pi * fd * t).astype(np.complex64)
        xf = np.fft.fft(x * mix, axis=1)                      # (blocks, spms)
        for pi in range(len(prns)):
            corr = np.fft.ifft(xf * code_fft[pi], axis=1)     # (blocks, spms)
            # Coherent within a group, magnitude-square, then accumulate.
            coh_sum = corr.reshape(groups, coh, spms).sum(axis=1)
            acc = np.sum(np.abs(coh_sum) ** 2, axis=0)        # (spms,)

            peak_idx = int(np.argmax(acc))
            peak = float(acc[peak_idx])
            if peak <= best_val[pi]:
                continue

            mask = np.ones(spms, dtype=bool)
            lo, hi = peak_idx - guard, peak_idx + guard + 1
            if lo < 0:
                mask[lo:] = False
                mask[:hi] = False
            elif hi > spms:
                mask[lo:] = False
                mask[: hi - spms] = False
            else:
                mask[lo:hi] = False

            floor = float(np.mean(acc[mask]))
            second = float(np.max(acc[mask]))

            best_val[pi] = peak
            best_dop[pi] = fd
            best_phase[pi] = peak_idx
            best_floor[pi] = floor if floor > 0 else 1e-30
            best_second[pi] = second if second > 0 else 1e-30

    results: list[AcqResult] = []
    for pi, prn in enumerate(prns):
        ratio = best_val[pi] / best_floor[pi]
        p2f_db = 10.0 * math.log10(ratio) if ratio > 0 else -99.0
        p2s = best_val[pi] / best_second[pi]
        p2s_db = 10.0 * math.log10(p2s) if p2s > 0 else -99.0
        # Standard peak-to-average C/N0 estimator, referred to the coherent
        # dwell actually used.
        cn0 = (
            10.0 * math.log10((ratio - 1.0) / coh_s)
            if ratio > 1.0
            else -99.0
        )
        results.append(
            AcqResult(
                prn=prn,
                detected=bool(p2f_db >= threshold_db),
                doppler_hz=float(best_dop[pi]),
                code_phase_samples=float(best_phase[pi]),
                code_phase_chips=float(best_phase[pi]) * CODE_RATE_HZ / fs,
                peak_to_floor_db=p2f_db,
                peak_to_second_db=p2s_db,
                cn0_dbhz=cn0,
                threshold_db=threshold_db,
                coherent_ms=coh,
                groups=groups,
            )
        )
    return results


def print_acq_table(results: list[AcqResult]) -> int:
    hits = [r for r in results if r.detected]
    print()
    if results:
        r0 = results[0]
        print(f"  dwell: {r0.coherent_ms} ms coherent x {r0.groups} accumulated"
              f"   detection threshold {r0.threshold_db:.1f} dB (CFAR)")
    print("  PRN   Doppler   code phase    pk/floor   pk/2nd    C/N0")
    print("            [Hz]      [chips]        [dB]     [dB]  [dB-Hz]")
    print("  " + "-" * 58)
    for r in sorted(results, key=lambda r: (-r.peak_to_floor_db, r.prn)):
        flag = "  <== ACQUIRED" if r.detected else ""
        # Show near-misses: they distinguish "nothing there" from "almost".
        if not r.detected and r.peak_to_floor_db < r.threshold_db - 4.0:
            continue
        print(
            f"  {r.prn:3d}  {r.doppler_hz:8.0f}   {r.code_phase_chips:10.2f}"
            f"  {r.peak_to_floor_db:10.1f} {r.peak_to_second_db:8.1f}"
            f"  {r.cn0_dbhz:7.1f}{flag}"
        )
    print("  " + "-" * 58)
    print(f"  {len(hits)} satellite(s) acquired of {len(results)} PRNs searched.")
    if len(hits) == 0:
        print()
        print("  NO SATELLITES. This is a link-budget or configuration result,")
        print("  not a tracking problem. In order of likelihood:")
        print("    1. RFFE not powered, or its bias is not reaching the antenna.")
        print("    2. Antenna has no sky view. A window is marginal; outdoors is not.")
        print("    3. Wrong port -- confirm the cable is on RX2 of the channel used.")
        print("    4. Gain far off. Run --gain-sweep.")
    elif len(hits) < 4:
        print()
        print(f"  {len(hits)} acquired, but a 3D fix needs 4 satellites tracked")
        print("  simultaneously. Move to clearer sky or raise --seconds.")
    return len(hits)


# =====================================================================
# SECTION 4 -- IQ FILE I/O
# =====================================================================

def to_sc16(x: np.ndarray) -> np.ndarray:
    """complex64 in [-1,1) -> interleaved int16, the format UHD calls sc16."""
    out = np.empty(2 * x.size, dtype=np.int16)
    out[0::2] = np.clip(np.rint(x.real * SC16_FULL_SCALE), -32768, 32767)
    out[1::2] = np.clip(np.rint(x.imag * SC16_FULL_SCALE), -32768, 32767)
    return out


def read_iq(path: str, fmt: str, max_samples: int | None = None,
            skip_samples: int = 0) -> np.ndarray:
    """Read an IQ recording back as complex64 normalised to full scale."""
    if fmt == "fc32":
        count = -1 if max_samples is None else max_samples
        raw = np.fromfile(path, dtype=np.complex64, count=count,
                          offset=skip_samples * 8)
        return raw
    if fmt == "sc16":
        count = -1 if max_samples is None else 2 * max_samples
        raw = np.fromfile(path, dtype=np.int16, count=count,
                          offset=skip_samples * 4)
        raw = raw[: (raw.size // 2) * 2]
        return (raw[0::2].astype(np.float32)
                + 1j * raw[1::2].astype(np.float32)) / np.float32(SC16_FULL_SCALE)
    raise ValueError(f"unknown IQ format {fmt!r}")


def bytes_per_sample(fmt: str) -> int:
    return 8 if fmt == "fc32" else 4


@dataclass
class LevelReport:
    rms: float
    peak: float
    clipped_fraction: float
    overflows: int

    def verdict(self) -> tuple[str, str]:
        if self.clipped_fraction > LEVEL_CLIP_MAX:
            return ("CLIPPING", "lower --gain by 10 dB and re-record")
        if self.rms > LEVEL_RMS_MAX:
            return ("TOO HOT", "lower --gain by 6-10 dB")
        if self.rms < LEVEL_RMS_MIN:
            return ("TOO COLD", "raise --gain by 6-10 dB, or the RFFE is unpowered")
        return ("OK", "")

    def render(self) -> str:
        state, advice = self.verdict()
        line = (
            f"  ADC fill: RMS {self.rms * 100:.2f}% of full scale, "
            f"peak {self.peak * 100:.1f}%, clipped {self.clipped_fraction * 100:.4f}%"
        )
        line += f"\n  Level: {state}"
        if advice:
            line += f" -- {advice}"
        if self.overflows:
            line += (
                f"\n  WARNING: {self.overflows} overflow(s). The host could not keep up;"
                "\n  samples were dropped and the recording has discontinuities."
            )
        return line


# =====================================================================
# SECTION 5 -- USRP
# =====================================================================

def _import_uhd():
    try:
        import uhd  # noqa: F401
    except Exception as exc:                                  # pragma: no cover
        raise SystemExit(
            f"the UHD Python module is not importable: {exc}\n"
            "On Ubuntu:  sudo apt install uhd-host python3-uhd\n"
            "Then confirm the board is seen:  uhd_find_devices"
        )
    return sys.modules["uhd"]


def probe(serial: str, channel: int, subdev: str) -> None:
    uhd = _import_uhd()
    print(f"opening serial={serial} ...")
    usrp = uhd.usrp.MultiUSRP(f"serial={serial}")
    if subdev:
        usrp.set_rx_subdev_spec(uhd.usrp.SubdevSpec(subdev))

    nch = usrp.get_rx_num_channels()
    print(f"  motherboard : {usrp.get_mboard_name(0)}")
    print(f"  RX channels : {nch}")
    print(f"  subdev spec : {usrp.get_rx_subdev_spec(0)}")
    print(f"  clock source: {usrp.get_clock_source(0)}")
    for ch in range(nch):
        gr = usrp.get_rx_gain_range(ch)
        mark = "  <== requested" if ch == channel else ""
        print(f"  -- channel {ch}{mark}")
        print(f"       subdev   : {usrp.get_rx_subdev_name(ch)}")
        print(f"       antennas : {list(usrp.get_rx_antennas(ch))}")
        print(f"       current  : {usrp.get_rx_antenna(ch)}")
        print(f"       gain     : {gr.start():.0f} .. {gr.stop():.0f} dB")
    if channel >= nch:
        print()
        print(f"  ERROR: channel {channel} does not exist -- this board exposes "
              f"{nch}.")
        print("  A B210 shows 2 only when the subdev spec is 'A:A A:B'. Pass")
        print("  --subdev 'A:A A:B' to force it.")


def capture(
    path: str,
    seconds: float,
    serial: str = DEFAULT_SERIAL,
    channel: int = DEFAULT_CHANNEL,
    gain: float = DEFAULT_GAIN,
    fs: float = DEFAULT_FS,
    freq: float = L1_HZ,
    antenna: str = DEFAULT_ANTENNA,
    subdev: str = DEFAULT_SUBDEV,
    bandwidth: float = DEFAULT_BW,
    fmt: str = "sc16",
    quiet: bool = False,
) -> LevelReport:
    """Stream `seconds` of IQ from one RX channel to `path`.

    The antenna port is set EXPLICITLY here. That is the difference from driving
    gnss-sdr's UHD source directly: gnss-sdr has no antenna property at all (the
    set_antenna call in uhd_signal_source.cc is commented out), so that path
    depends on the B210 defaulting to RX2, which it does -- but silently, and
    only by default.
    """
    uhd = _import_uhd()
    usrp = uhd.usrp.MultiUSRP(f"serial={serial}")
    if subdev:
        usrp.set_rx_subdev_spec(uhd.usrp.SubdevSpec(subdev))

    nch = usrp.get_rx_num_channels()
    if channel >= nch:
        raise SystemExit(
            f"channel {channel} does not exist; this board exposes {nch}. "
            "Try --subdev 'A:A A:B'."
        )
    if antenna not in list(usrp.get_rx_antennas(channel)):
        raise SystemExit(
            f"antenna {antenna!r} not available on channel {channel}; "
            f"have {list(usrp.get_rx_antennas(channel))}"
        )

    usrp.set_rx_rate(fs, channel)
    usrp.set_rx_freq(uhd.types.TuneRequest(freq), channel)
    usrp.set_rx_gain(gain, channel)
    usrp.set_rx_antenna(antenna, channel)
    try:
        usrp.set_rx_bandwidth(bandwidth, channel)
    except Exception:
        pass  # not every front end exposes an analog bandwidth control

    actual_fs = usrp.get_rx_rate(channel)
    actual_freq = usrp.get_rx_freq(channel)
    actual_gain = usrp.get_rx_gain(channel)
    if not quiet:
        print(f"  serial   : {serial}   channel {channel}   antenna "
              f"{usrp.get_rx_antenna(channel)}")
        print(f"  subdev   : {usrp.get_rx_subdev_name(channel)}")
        print(f"  tuned    : {actual_freq / 1e6:.6f} MHz")
        print(f"  rate     : {actual_fs / 1e6:.6f} MSPS")
        print(f"  gain     : {actual_gain:.1f} dB")
        print(f"  writing  : {path}  ({fmt})")
    if abs(actual_fs - fs) > 1.0:
        print(f"  WARNING: requested {fs / 1e6:.6f} MSPS but got "
              f"{actual_fs / 1e6:.6f}. Acquisition and the gnss-sdr conf will "
              "use the ACTUAL rate.")

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [channel]
    streamer = usrp.get_rx_stream(st_args)
    max_samps = streamer.get_max_num_samps()
    buf = np.zeros((1, max_samps), dtype=np.complex64)
    metadata = uhd.types.RXMetadata()

    total_needed = int(round(actual_fs * seconds))
    got = 0
    overflows = 0
    sum_sq = 0.0
    peak = 0.0
    clipped = 0

    stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
    stream_cmd.stream_now = True
    streamer.issue_stream_cmd(stream_cmd)

    started = time.time()
    try:
        with open(path, "wb", buffering=1 << 22) as fh:
            while got < total_needed:
                n = streamer.recv(buf, metadata, 1.0)
                if metadata.error_code != uhd.types.RXMetadataErrorCode.none:
                    if metadata.error_code == uhd.types.RXMetadataErrorCode.overflow:
                        overflows += 1
                        continue
                    raise SystemExit(f"UHD receive error: {metadata.strerror()}")
                if n == 0:
                    continue
                take = min(n, total_needed - got)
                chunk = buf[0, :take]

                mag = np.abs(chunk)
                sum_sq += float(np.dot(mag, mag))
                cpk = float(mag.max()) if take else 0.0
                peak = max(peak, cpk)
                clipped += int(np.count_nonzero(mag >= 0.999))

                if fmt == "sc16":
                    to_sc16(chunk).tofile(fh)
                else:
                    chunk.astype(np.complex64).tofile(fh)
                got += take

                if not quiet and got % int(actual_fs) < max_samps:
                    el = time.time() - started
                    print(f"    {got / actual_fs:6.1f} s captured "
                          f"({el:5.1f} s wall, {overflows} overflow)", end="\r",
                          flush=True)
    finally:
        streamer.issue_stream_cmd(
            uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
        )
    if not quiet:
        print()

    rms = math.sqrt(sum_sq / got) if got else 0.0
    report = LevelReport(rms=rms, peak=peak,
                         clipped_fraction=(clipped / got if got else 0.0),
                         overflows=overflows)
    _write_sidecar(path, fmt, actual_fs, actual_freq, actual_gain, serial,
                   channel, antenna, got)
    return report


def _write_sidecar(path, fmt, fs, freq, gain, serial, channel, antenna, samples):
    with open(path + ".meta", "w") as fh:
        fh.write(
            f"format={fmt}\nsample_rate={fs:.6f}\ncenter_freq={freq:.3f}\n"
            f"gain={gain:.2f}\nserial={serial}\nchannel={channel}\n"
            f"antenna={antenna}\nsamples={samples}\n"
            f"seconds={samples / fs:.3f}\n"
            f"recorded={time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
        )


def read_sidecar(path: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    try:
        with open(path + ".meta") as fh:
            for line in fh:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    meta[k] = v
    except FileNotFoundError:
        pass
    return meta


# =====================================================================
# SECTION 6 -- gnss-sdr
# =====================================================================

FILE_CONF_TEMPLATE = """\
[GNSS-SDR]

; Generated by gpsfix.py -- do not hand-edit, regenerate instead.
; Source: {iq_file}
; Captured from serial {serial} channel {channel} antenna {antenna}.

GNSS-SDR.internal_fs_sps={fs:.0f}

SignalSource.implementation=File_Signal_Source
SignalSource.filename={iq_file}
SignalSource.item_type={item_type}
SignalSource.sampling_frequency={fs:.0f}
SignalSource.samples=0
SignalSource.repeat=false
; A file is not real time, so let it run as fast as the CPU allows.
SignalSource.enable_throttle_control=false

SignalConditioner.implementation=Signal_Conditioner
DataTypeAdapter.implementation={adapter}
InputFilter.implementation=Pass_Through
Resampler.implementation=Pass_Through

Channels_1C.count={channels}
Channels.in_acquisition=2
Channel.signal=1C

Acquisition_1C.implementation=GPS_L1_CA_PCPS_Acquisition
Acquisition_1C.item_type=gr_complex
Acquisition_1C.pfa={pfa}
Acquisition_1C.doppler_max={doppler_max:.0f}
Acquisition_1C.doppler_step={doppler_step:.0f}
; Coherent integration beyond one code period is the main lever for a weak
; signal. 4 ms stays clear of the 20 ms navigation bit boundary.
Acquisition_1C.coherent_integration_time_ms={coh_ms}
Acquisition_1C.max_dwells=3
Acquisition_1C.blocking=true

Tracking_1C.implementation=GPS_L1_CA_DLL_PLL_Tracking
Tracking_1C.item_type=gr_complex
; Wide loops track dynamics but admit noise. On a static antenna with an RFFE
; there are no dynamics to track, so narrow is strictly better -- narrowing is
; the first thing to try when locks cycle.
Tracking_1C.pll_bw_hz={pll_bw}
Tracking_1C.dll_bw_hz={dll_bw}
Tracking_1C.early_late_space_chips=0.5
Tracking_1C.dump=false

TelemetryDecoder_1C.implementation=GPS_L1_CA_Telemetry_Decoder
Observables.implementation=Hybrid_Observables

PVT.implementation=RTKLIB_PVT
PVT.positioning_mode=Single
PVT.output_rate_ms=1000
PVT.display_rate_ms=1000
PVT.elevation_mask=5
PVT.nmea_rate_ms=1000
PVT.nmea_output_file_enabled=true
PVT.nmea_dump_filename=gnss_sdr_pvt.nmea
PVT.nmea_output_file_path={out_dir}
PVT.kml_output_enabled=true
PVT.gpx_output_enabled=true
PVT.rinex_output_enabled=false
PVT.output_path={out_dir}
"""


def write_file_conf(
    conf_path: str,
    iq_file: str,
    fs: float,
    fmt: str,
    out_dir: str,
    serial: str = DEFAULT_SERIAL,
    channel: int = DEFAULT_CHANNEL,
    antenna: str = DEFAULT_ANTENNA,
    channels: int = 10,
    pll_bw: float = 25.0,
    dll_bw: float = 1.5,
    coh_ms: int = 4,
    pfa: float = 0.01,
    doppler_max: float = DEFAULT_DOPPLER_MAX,
    doppler_step: float = DEFAULT_DOPPLER_STEP,
) -> str:
    if fmt == "sc16":
        item_type, adapter = "ishort", "Ishort_To_Complex"
    elif fmt == "fc32":
        item_type, adapter = "gr_complex", "Pass_Through"
    else:
        raise ValueError(f"unknown IQ format {fmt!r}")

    text = FILE_CONF_TEMPLATE.format(
        iq_file=os.path.abspath(iq_file), fs=fs, item_type=item_type,
        adapter=adapter, out_dir=os.path.abspath(out_dir), channels=channels,
        pll_bw=pll_bw, dll_bw=dll_bw, coh_ms=coh_ms, pfa=pfa,
        doppler_max=doppler_max, doppler_step=doppler_step,
        serial=serial, channel=channel, antenna=antenna,
    )
    with open(conf_path, "w") as fh:
        fh.write(text)
    return conf_path


POSITION_RE = re.compile(
    r"Lat\s*=\s*(-?\d+\.?\d*)\s*\[deg\].*?"
    r"Long\s*=\s*(-?\d+\.?\d*)\s*\[deg\].*?"
    r"Height\s*=\s*(-?\d+\.?\d*)",
    re.IGNORECASE,
)
# gnss-sdr has printed both wordings across versions ("using 6 observations",
# "using 6 satellites"), so accept either rather than silently reporting 0.
SATS_RE = re.compile(r"using\s+(\d+)\s+(?:satellites|observations)", re.IGNORECASE)


def run_gnss_sdr(conf_path: str, gnss_sdr_bin: str = "gnss-sdr",
                 timeout: float | None = None) -> list[dict]:
    """Run gnss-sdr on a config, echoing output and collecting positions."""
    exe = shutil.which(gnss_sdr_bin)
    if exe is None:
        raise SystemExit(
            f"{gnss_sdr_bin!r} is not on PATH.\n"
            "On Ubuntu:  sudo apt install gnss-sdr\n"
            "The --acq stage needs none of this and still tells you whether the "
            "antenna chain works."
        )

    print(f"  running {exe} --config_file={conf_path}")
    print("  (first fix needs a full ephemeris: ~30 s of signal minimum)")
    fixes: list[dict] = []
    proc = subprocess.Popen(
        [exe, f"--config_file={conf_path}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    started = time.time()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            m = POSITION_RE.search(line)
            if m:
                sats = SATS_RE.search(line)
                fix = {
                    "lat": float(m.group(1)),
                    "lon": float(m.group(2)),
                    "alt": float(m.group(3)),
                    "sats": int(sats.group(1)) if sats else 0,
                }
                fixes.append(fix)
                print(f"  [FIX] lat {fix['lat']:.7f}  lon {fix['lon']:.7f}  "
                      f"alt {fix['alt']:.1f} m  sats {fix['sats']}")
            elif any(k in line for k in
                     ("Tracking of GPS L1", "Loss of lock", "New GPS NAV message",
                      "Ephemeris record", "channel  ", "Current input signal time")):
                print(f"    {line}")
            if timeout is not None and time.time() - started > timeout:
                proc.terminate()
                break
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        proc.wait()
    return fixes


# =====================================================================
# SECTION 7 -- NMEA
# =====================================================================

def nmea_checksum(body: str) -> int:
    """XOR of every character between '$' and '*'."""
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    return calc


def nmea_sentence(body: str) -> str:
    """Wrap a bare body (no '$', no '*') into a complete NMEA sentence."""
    return f"${body}*{nmea_checksum(body):02X}"


def nmea_checksum_ok(sentence: str) -> bool:
    s = sentence.strip()
    if not s.startswith("$") or "*" not in s:
        return False
    body, _, given = s[1:].partition("*")
    try:
        return nmea_checksum(body) == int(given[:2], 16)
    except ValueError:
        return False


def dm_to_deg(value: str, hemisphere: str) -> float | None:
    """NMEA ddmm.mmmm / dddmm.mmmm plus hemisphere -> signed decimal degrees."""
    if not value:
        return None
    dot = value.find(".")
    if dot < 0:
        dot = len(value)
    deg_digits = dot - 2
    if deg_digits < 1:
        return None
    degrees = float(value[:deg_digits])
    minutes = float(value[deg_digits:])
    out = degrees + minutes / 60.0
    if hemisphere.upper() in ("S", "W"):
        out = -out
    return out


def parse_gga(sentence: str) -> dict | None:
    """Parse a GGA sentence into lat/lon/alt/sats/hdop, or None."""
    s = sentence.strip()
    if not nmea_checksum_ok(s):
        return None
    body = s[1:].split("*")[0]
    f = body.split(",")
    if len(f) < 10 or not f[0].endswith("GGA"):
        return None
    quality = int(f[6]) if f[6].isdigit() else 0
    if quality == 0:
        return None
    lat = dm_to_deg(f[2], f[3])
    lon = dm_to_deg(f[4], f[5])
    if lat is None or lon is None:
        return None
    return {
        "utc": f[1],
        "lat": lat,
        "lon": lon,
        "quality": quality,
        "sats": int(f[7]) if f[7].isdigit() else 0,
        "hdop": float(f[8]) if f[8] else float("nan"),
        "alt": float(f[9]) if f[9] else float("nan"),
    }


def last_fix_from_nmea(path: str) -> dict | None:
    best = None
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                got = parse_gga(line)
                if got:
                    best = got
    except FileNotFoundError:
        return None
    return best


# =====================================================================
# SECTION 8 -- SELFTEST
# =====================================================================

def _synth_capture(prn: int, fs: float, ms: int, doppler: float,
                   code_phase_chips: float, cn0_dbhz: float | None,
                   seed: int = 12345) -> np.ndarray:
    """A synthetic L1 C/A capture with a known answer, at a stated C/N0.

    Signal power C is fixed at 1, so N0 = C / 10^(C/N0 / 10) and the complex
    noise variance over the sampled bandwidth is N0 * fs. That makes cn0_dbhz
    mean what it says rather than being an arbitrary SNR knob.

    cn0_dbhz=None gives noise only, which is the false-alarm control: the
    detector must stay silent on it.
    """
    rng = np.random.default_rng(seed)
    n = int(round(fs * 1e-3 * ms))
    t = np.arange(n) / fs

    if cn0_dbhz is None:
        noise = (rng.normal(0, math.sqrt(0.5), n)
                 + 1j * rng.normal(0, math.sqrt(0.5), n))
        return noise.astype(np.complex64)

    code = ca_sampled(prn, fs, n, chip_offset=-code_phase_chips)
    # 50 Hz navigation data, which is what forces non-coherent accumulation.
    bits = rng.integers(0, 2, size=ms // 20 + 2) * 2 - 1
    data = bits[(t * 50.0).astype(int)]

    signal = code * data * np.exp(2j * math.pi * doppler * t)

    n0 = 1.0 / (10.0 ** (cn0_dbhz / 10.0))
    noise_var = n0 * fs
    noise = (rng.normal(0, math.sqrt(noise_var / 2), n)
             + 1j * rng.normal(0, math.sqrt(noise_var / 2), n))
    return (signal + noise).astype(np.complex64)


def selftest() -> int:
    """Verify the DSP and the plumbing with no radio and no gnss-sdr."""
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    print("gpsfix selftest")
    print()
    print(" C/A code generator (IS-GPS-200 Table 3-I)")
    bad = []
    for prn in range(1, 33):
        bits = "".join(str(int(b)) for b in ca_code(prn)[:10])
        octal = oct(int(bits, 2))[2:].zfill(4)
        if octal != CA_FIRST10_OCTAL[prn - 1]:
            bad.append(f"PRN{prn} {octal}!={CA_FIRST10_OCTAL[prn - 1]}")
    check("first 10 chips of all 32 PRNs match the ICD", not bad,
          "; ".join(bad[:4]))

    ones = [int(ca_code(p).sum()) for p in range(1, 33)]
    check("every code is balanced (512 ones of 1023)", all(o == 512 for o in ones))

    a = ca_bipolar(1)
    b = ca_bipolar(2)
    auto = int(a @ a)
    cross = int(a @ b)
    check("autocorrelation peak is 1023", auto == 1023, f"got {auto}")
    check("cross-correlation PRN1 x PRN2 is one of -65/-1/63",
          cross in (-65, -1, 63), f"got {cross}")

    print()
    print(" Acquisition")
    fs = DEFAULT_FS
    truth_prn, truth_dop, truth_chip = 7, 2500.0, 511.5
    iq = _synth_capture(truth_prn, fs, 20, truth_dop, truth_chip, 45.0)
    res = {r.prn: r for r in acquire(iq, fs, noncoherent_ms=10)}
    hit = res[truth_prn]
    check(f"PRN {truth_prn} detected at 45 dB-Hz", hit.detected,
          f"pk/floor {hit.peak_to_floor_db:.1f} dB")
    check("Doppler within one search bin",
          abs(hit.doppler_hz - truth_dop) <= DEFAULT_DOPPLER_STEP,
          f"got {hit.doppler_hz:.0f} Hz, truth {truth_dop:.0f} Hz")
    got_chip = hit.code_phase_chips
    err = min(abs(got_chip - truth_chip), CODE_LEN_CHIPS - abs(got_chip - truth_chip))
    check("code phase within 1 chip", err <= 1.0,
          f"got {got_chip:.2f}, truth {truth_chip:.2f}, err {err:.2f} chips")
    others = [r for p, r in res.items() if p != truth_prn and r.detected]
    check("no other PRN falsely detected", not others,
          f"false: {[r.prn for r in others]}")
    check("C/N0 estimate within 3 dB of truth", abs(hit.cn0_dbhz - 45.0) <= 3.0,
          f"got {hit.cn0_dbhz:.1f} dB-Hz")

    noise_only = _synth_capture(1, fs, 20, 0.0, 0.0, None, seed=999)
    nres = acquire(noise_only, fs, noncoherent_ms=10)
    false_hits = [r.prn for r in nres if r.detected]
    check("noise-only capture yields no detections", not false_hits,
          f"false: {false_hits}")

    print()
    print(" IQ file round trip")
    src = (np.random.default_rng(7).normal(0, 0.05, 4096)
           + 1j * np.random.default_rng(8).normal(0, 0.05, 4096)).astype(np.complex64)
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gpsfix_selftest.iq")
    try:
        to_sc16(src).tofile(tmp)
        back = read_iq(tmp, "sc16")
        check("sc16 round trip preserves samples", back.size == src.size
              and float(np.max(np.abs(back - src))) < 2.0 / SC16_FULL_SCALE,
              f"max err {float(np.max(np.abs(back - src))):.2e}")
        src.tofile(tmp)
        back = read_iq(tmp, "fc32")
        check("fc32 round trip is exact", np.array_equal(back, src))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    print()
    print(" NMEA")
    good = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    check("checksum accepted on a valid sentence", nmea_checksum_ok(good))
    check("checksum rejected when a digit is altered",
          not nmea_checksum_ok(good.replace("4807.038", "4807.039")))
    g = parse_gga(good)
    check("GGA latitude 4807.038 N -> 48.1173 deg",
          g is not None and abs(g["lat"] - 48.1173) < 1e-4,
          f"got {g['lat']:.6f}" if g else "parse failed")
    check("GGA longitude 01131.000 E -> 11.5167 deg",
          g is not None and abs(g["lon"] - 11.516667) < 1e-4,
          f"got {g['lon']:.6f}" if g else "parse failed")
    check("GGA satellites and altitude",
          g is not None and g["sats"] == 8 and abs(g["alt"] - 545.4) < 1e-6)
    # Derived sentences are built with the generator so the checksum is right by
    # construction -- a hand-typed one would make these pass for the wrong reason
    # (rejected as corrupt rather than for the property under test).
    check("generator reproduces the canonical *47 checksum",
          nmea_sentence(good[1:].split("*")[0]) == good)
    sg = parse_gga(nmea_sentence(
        "GPGGA,123519,4807.038,S,01131.000,W,1,08,0.9,545.4,M,46.9,M,,"))
    check("southern/western hemispheres are negated",
          sg is not None and sg["lat"] < 0 and sg["lon"] < 0,
          f"lat {sg['lat']:.4f} lon {sg['lon']:.4f}" if sg else "parse failed")
    check("a no-fix sentence (quality 0) is rejected, checksum valid",
          parse_gga(nmea_sentence("GPGGA,123519,,,,,0,00,,,M,,M,,")) is None)

    print()
    print(" gnss-sdr console parsing")
    for wording in ("observations", "satellites"):
        line = (f"Position at 2026-Aug-11 12:34:56 UTC using 7 {wording} is "
                f"Lat = 12.9715987 [deg], Long = 77.5945627 [deg], "
                f"Height = 920.4 [m]")
        m = POSITION_RE.search(line)
        sm = SATS_RE.search(line)
        check(f"position line parsed ('{wording}' wording)",
              m is not None and sm is not None
              and abs(float(m.group(1)) - 12.9715987) < 1e-7
              and abs(float(m.group(2)) - 77.5945627) < 1e-7
              and int(sm.group(1)) == 7)
    neg = ("Position at 2026-Aug-11 00:00:00 UTC using 5 observations is "
           "Lat = -33.8688 [deg], Long = -151.2093 [deg], Height = -12.5 [m]")
    mn = POSITION_RE.search(neg)
    check("southern/western/below-ellipsoid values keep their sign",
          mn is not None and float(mn.group(1)) < 0
          and float(mn.group(2)) < 0 and float(mn.group(3)) < 0)

    print()
    print(" gnss-sdr config generation")
    conf = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gpsfix_selftest.conf")
    try:
        write_file_conf(conf, "/tmp/x.iq", 4000000.0, "sc16", "/tmp/out")
        text = open(conf).read()
        check("sc16 maps to ishort + Ishort_To_Complex",
              "SignalSource.item_type=ishort" in text
              and "DataTypeAdapter.implementation=Ishort_To_Complex" in text)
        check("internal_fs_sps matches the capture rate",
              "GNSS-SDR.internal_fs_sps=4000000" in text)
        write_file_conf(conf, "/tmp/x.iq", 4000000.0, "fc32", "/tmp/out")
        text = open(conf).read()
        check("fc32 maps to gr_complex + Pass_Through",
              "SignalSource.item_type=gr_complex" in text
              and "DataTypeAdapter.implementation=Pass_Through" in text)
    finally:
        if os.path.exists(conf):
            os.remove(conf)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


# =====================================================================
# SECTION 9 -- CLI
# =====================================================================

def _default_iq_path(out_dir: str) -> str:
    return os.path.join(out_dir, "gps_ch1.iq")


def do_acq(args, iq_path: str) -> int:
    meta = read_sidecar(iq_path)
    fmt = meta.get("format", args.iq_format)
    fs = float(meta.get("sample_rate", args.fs))
    if not os.path.exists(iq_path):
        raise SystemExit(f"no recording at {iq_path} -- run --record first")

    need = int(fs * 1e-3 * args.noncoherent_ms)
    iq = read_iq(iq_path, fmt, max_samples=need, skip_samples=int(fs * args.acq_skip))
    print(f"  searching {args.noncoherent_ms} ms from t={args.acq_skip:.1f} s of "
          f"{iq_path} at {fs / 1e6:.4f} MSPS")
    prns = [args.prn] if args.prn else list(range(1, 33))
    t0 = time.time()
    results = acquire(iq, fs, prns=prns, noncoherent_ms=args.noncoherent_ms,
                      coherent_ms=args.coherent_ms,
                      doppler_max=args.doppler_max, doppler_step=args.doppler_step,
                      threshold_db=args.threshold_db, pfa=args.pfa)
    print(f"  searched {len(prns)} PRN(s) in {time.time() - t0:.1f} s")
    return print_acq_table(results)


def do_fix(args, iq_path: str) -> int:
    meta = read_sidecar(iq_path)
    fmt = meta.get("format", args.iq_format)
    fs = float(meta.get("sample_rate", args.fs))
    if not os.path.exists(iq_path):
        raise SystemExit(f"no recording at {iq_path} -- run --record first")

    conf = os.path.join(args.outdir, "gpsfix_file.conf")
    write_file_conf(conf, iq_path, fs, fmt, args.outdir,
                    serial=args.serial, channel=args.channel,
                    antenna=args.antenna, channels=args.channels,
                    pll_bw=args.pll_bw, dll_bw=args.dll_bw)
    print(f"  wrote {conf}")
    fixes = run_gnss_sdr(conf, args.gnss_sdr, timeout=args.gnss_timeout)

    nmea = os.path.join(args.outdir, "gnss_sdr_pvt.nmea")
    tail = last_fix_from_nmea(nmea)
    print()
    if fixes:
        f = fixes[-1]
        print("  ================= POSITION =================")
        print(f"   latitude  : {f['lat']:.7f} deg")
        print(f"   longitude : {f['lon']:.7f} deg")
        print(f"   altitude  : {f['alt']:.1f} m")
        print(f"   satellites: {f['sats']}")
        print(f"   fixes     : {len(fixes)} over the capture")
        print("  ============================================")
        print(f"   map: https://www.openstreetmap.org/?mlat={f['lat']:.7f}"
              f"&mlon={f['lon']:.7f}#map=17/{f['lat']:.5f}/{f['lon']:.5f}")
        print(f"   NMEA: {nmea}")
        print(f"   KML : {os.path.join(args.outdir, 'gnss_sdr_pvt.kml')}")
        return 0
    if tail:
        print("  ================= POSITION (from NMEA) =================")
        print(f"   latitude  : {tail['lat']:.7f} deg")
        print(f"   longitude : {tail['lon']:.7f} deg")
        print(f"   altitude  : {tail['alt']:.1f} m   sats {tail['sats']}  "
              f"HDOP {tail['hdop']}")
        return 0

    print("  NO FIX from this capture.")
    print("  Read the --acq table above before changing anything here:")
    print("    * 0 satellites acquired  -> link budget. RFFE power, sky view, port.")
    print("    * 4+ acquired, no fix    -> tracking or ephemeris. Try a longer")
    print("      --seconds (a fix needs 30 s of continuous ephemeris), then")
    print("      --pll-bw 15 --dll-bw 1.0 to narrow the loops.")
    return 2


def do_gain_sweep(args) -> int:
    gains = [float(g) for g in args.gain_sweep.split(",")]
    print(f"gain sweep over {gains} -- {args.sweep_seconds:.1f} s per point")
    scores = []
    for g in gains:
        path = os.path.join(args.outdir, f"sweep_{int(g)}dB.iq")
        print(f"\n-- gain {g:.0f} dB")
        rep = capture(path, args.sweep_seconds, serial=args.serial,
                      channel=args.channel, gain=g, fs=args.fs,
                      antenna=args.antenna, subdev=args.subdev,
                      fmt=args.iq_format, quiet=True)
        print(rep.render())
        fs = float(read_sidecar(path).get("sample_rate", args.fs))
        iq = read_iq(path, args.iq_format,
                     max_samples=int(fs * 1e-3 * args.noncoherent_ms))
        res = acquire(iq, fs, noncoherent_ms=args.noncoherent_ms,
                      coherent_ms=args.coherent_ms,
                      doppler_max=args.doppler_max,
                      doppler_step=args.doppler_step,
                      threshold_db=args.threshold_db, pfa=args.pfa)
        hits = [r for r in res if r.detected]
        best = max((r.cn0_dbhz for r in hits), default=float("-inf"))
        scores.append((g, len(hits), best, rep))
        print(f"  -> {len(hits)} satellite(s), best C/N0 "
              f"{best:.1f} dB-Hz" if hits else "  -> 0 satellites")

    print("\n  gain   sats   best C/N0   RMS fill   verdict")
    print("  " + "-" * 52)
    for g, n, best, rep in scores:
        state, _ = rep.verdict()
        cn = f"{best:9.1f}" if n else "        -"
        print(f"  {g:4.0f}   {n:4d}  {cn}   {rep.rms * 100:7.2f}%   {state}")
    winner = max(scores, key=lambda s: (s[1], s[2]))
    print(f"\n  Best: {winner[0]:.0f} dB ({winner[1]} satellites). "
          f"Use --gain {winner[0]:.0f}.")
    return 0 if winner[1] else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gpsfix.py",
        description="GPS L1 C/A on one USRP B210 RX channel, through to lat/lon.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  ./gpsfix.py --selftest                    verify the DSP, no hardware needed
  ./gpsfix.py --probe                       what does the radio actually report
  ./gpsfix.py --record --seconds 120        capture channel 1 / RX2 to disk
  ./gpsfix.py --acq                         are there satellites in that capture
  ./gpsfix.py --fix                         decode it to a position
  ./gpsfix.py --run --seconds 120           all three, in order
  ./gpsfix.py --gain-sweep 20,30,40,50,60   find the right gain for the RFFE
  ./gpsfix.py --live                        continuous, straight off the radio
""",
    )
    st = p.add_argument_group("stages")
    st.add_argument("--probe", action="store_true", help="report radio capabilities")
    st.add_argument("--record", action="store_true", help="capture IQ to disk")
    st.add_argument("--acq", action="store_true", help="search a recording for PRNs")
    st.add_argument("--fix", action="store_true", help="gnss-sdr on a recording")
    st.add_argument("--run", action="store_true", help="record, then acq, then fix")
    st.add_argument("--live", action="store_true",
                    help="gnss-sdr straight off the radio, continuous")
    st.add_argument("--gain-sweep", metavar="G1,G2,...",
                    help="record and acquire at each gain, then recommend one")
    st.add_argument("--selftest", action="store_true",
                    help="verify the DSP with no radio and no gnss-sdr")

    rf = p.add_argument_group("radio")
    rf.add_argument("--serial", default=DEFAULT_SERIAL)
    rf.add_argument("--channel", type=int, default=DEFAULT_CHANNEL,
                    help=f"RX channel index (default {DEFAULT_CHANNEL} = RF B)")
    rf.add_argument("--antenna", default=DEFAULT_ANTENNA)
    rf.add_argument("--subdev", default=DEFAULT_SUBDEV,
                    help="UHD subdev spec, e.g. 'A:A A:B'. Empty keeps the default.")
    rf.add_argument("--gain", type=float, default=DEFAULT_GAIN)
    rf.add_argument("--fs", type=float, default=DEFAULT_FS)
    rf.add_argument("--freq", type=float, default=L1_HZ)
    rf.add_argument("--seconds", type=float, default=120.0,
                    help="capture length; a first fix needs 30 s minimum")
    rf.add_argument("--sweep-seconds", type=float, default=2.0)
    rf.add_argument("--iq-format", choices=IQ_FORMATS, default="sc16")

    ac = p.add_argument_group("acquisition")
    ac.add_argument("--prn", type=int, help="search one PRN instead of all 32")
    ac.add_argument("--noncoherent-ms", type=int, default=DEFAULT_NONCOH_MS,
                    help="total window searched, in ms")
    ac.add_argument("--coherent-ms", type=int, default=DEFAULT_COH_MS,
                    help="coherent dwell, in ms. To hear a weaker satellite "
                         "raise this AND --noncoherent-ms together (~3 dB per "
                         "doubling); raising it alone is close to neutral. "
                         "Above ~10 ms the 50 Hz nav bits cancel the sum.")
    ac.add_argument("--doppler-max", type=float, default=DEFAULT_DOPPLER_MAX)
    ac.add_argument("--doppler-step", type=float, default=DEFAULT_DOPPLER_STEP)
    ac.add_argument("--threshold-db", type=float, default=None,
                    help="override the CFAR detection threshold (dB above the "
                         "correlation floor). Default: derived from --pfa.")
    ac.add_argument("--pfa", type=float, default=DEFAULT_PFA,
                    help=f"per-PRN false-alarm probability (default {DEFAULT_PFA})")
    ac.add_argument("--acq-skip", type=float, default=1.0,
                    help="seconds to skip before searching (default 1.0, past "
                         "the AGC and tune transient)")

    gs = p.add_argument_group("gnss-sdr")
    gs.add_argument("--channels", type=int, default=10, help="tracking channels")
    gs.add_argument("--pll-bw", type=float, default=25.0)
    gs.add_argument("--dll-bw", type=float, default=1.5)
    gs.add_argument("--gnss-sdr", default="gnss-sdr", help="binary name or path")
    gs.add_argument("--gnss-timeout", type=float, default=None,
                    help="stop gnss-sdr after this many seconds")
    gs.add_argument("--live-conf", default=None,
                    help="conf for --live (default usrp_gps_l1_ch1.conf beside "
                         "this script)")

    p.add_argument("--outdir", default="/tmp/gpsfix")
    p.add_argument("--iq", default=None, help="IQ file path (default <outdir>/gps_ch1.iq)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.selftest:
        return selftest()

    stages = (args.probe, args.record, args.acq, args.fix, args.run,
              args.live, bool(args.gain_sweep))
    if not any(stages):
        build_parser().print_help()
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    iq_path = args.iq or _default_iq_path(args.outdir)

    if args.probe:
        probe(args.serial, args.channel, args.subdev)
        return 0

    if args.live:
        conf = args.live_conf or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "usrp_gps_l1_ch1.conf")
        if not os.path.exists(conf):
            raise SystemExit(f"no live conf at {conf}")
        print(f"live from the radio using {conf}")
        print("  NOTE: gnss-sdr has no antenna setting -- it relies on the B210")
        print("  defaulting to RX2. --record sets the port explicitly instead.")
        fixes = run_gnss_sdr(conf, args.gnss_sdr, timeout=args.gnss_timeout)
        return 0 if fixes else 2

    if args.gain_sweep:
        return do_gain_sweep(args)

    if args.record or args.run:
        need = args.seconds * args.fs * bytes_per_sample(args.iq_format)
        print(f"recording {args.seconds:.0f} s to {iq_path} "
              f"({need / 1e9:.2f} GB)")
        free = shutil.disk_usage(args.outdir).free
        if free < need * 1.1:
            raise SystemExit(
                f"not enough disk: need ~{need / 1e9:.2f} GB, "
                f"{free / 1e9:.2f} GB free in {args.outdir}"
            )
        report = capture(iq_path, args.seconds, serial=args.serial,
                         channel=args.channel, gain=args.gain, fs=args.fs,
                         freq=args.freq, antenna=args.antenna,
                         subdev=args.subdev, fmt=args.iq_format)
        print(report.render())
        state, _ = report.verdict()
        if state != "OK":
            print("  Fix the level before trusting anything downstream.")

    rc = 0
    if args.acq or args.run:
        hits = do_acq(args, iq_path)
        if args.run and hits == 0:
            print("\n  Stopping before gnss-sdr: it cannot decode what is not there.")
            return 2
        rc = 0 if hits else 2

    if args.fix or args.run:
        rc = do_fix(args, iq_path)

    return rc


if __name__ == "__main__":
    sys.exit(main())
