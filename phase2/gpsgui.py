#!/usr/bin/env python3
"""gpsgui.py -- live dashboard for one B210 RX channel on GPS L1.

Keeps the radio open and re-searches every PRN on a loop, showing four things
that between them explain any GPS bring-up failure:

  C/N0 per satellite   what the antenna chain is actually delivering. This is
                       set by the antenna and its LNA. It is NOT improved by
                       raising the B210's gain -- if C/N0 stays flat while the
                       ADC fill rises, you are amplifying noise and the front
                       end has no usable gain in it.
  Spectrum             a jammer, a spur or a saturating front end is obvious
                       here and invisible everywhere else. GPS itself is NOT
                       visible in this plot -- it arrives ~20 dB below thermal
                       noise -- so a flat trace is the correct, healthy look.
  ADC fill history     whether the level is drifting, clipping, or dead.
  Doppler per PRN      +/-5 kHz is a real satellite. Values pinned at a search
                       edge are usually the clock, not the sky.

There is no sky plot, deliberately. Azimuth and elevation cannot be derived
from acquisition -- they need the ephemeris out of the navigation message,
which is gnss-sdr's job. A sky plot drawn from code phase and Doppler alone
would be decoration with no measurement behind it.

    ./gpsgui.py                       # defaults: serial 34D04E6, channel 1
    ./gpsgui.py --gain 71 --serial 34D04E6 --channel 1
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure                             # noqa: E402
import tkinter as tk                                             # noqa: E402
from tkinter import ttk                                          # noqa: E402

import gpsfix as gf  # noqa: E402


# =====================================================================
# SECTION 1 -- RADIO
# =====================================================================

class LiveRadio:
    """One B210 RX channel, held open, read in bursts.

    Bursts use num_samps_and_done rather than a continuous stream: the GUI only
    wants a recent snapshot every second or so, and a continuous stream left
    running between reads would overflow constantly and bury the log in
    warnings that mean nothing here.
    """

    def __init__(self, serial, channel, gain, fs, freq, antenna, subdev, bw):
        import uhd
        self.uhd = uhd
        self.channel = channel
        self.usrp = uhd.usrp.MultiUSRP(f"serial={serial}")
        if subdev:
            self.usrp.set_rx_subdev_spec(uhd.usrp.SubdevSpec(subdev))

        nch = self.usrp.get_rx_num_channels()
        if channel >= nch:
            raise SystemExit(f"channel {channel} does not exist (board has {nch})")
        if antenna not in list(self.usrp.get_rx_antennas(channel)):
            raise SystemExit(
                f"antenna {antenna!r} unavailable; have "
                f"{list(self.usrp.get_rx_antennas(channel))}")

        self.usrp.set_rx_rate(fs, channel)
        self.usrp.set_rx_freq(uhd.types.TuneRequest(freq), channel)
        self.usrp.set_rx_gain(gain, channel)
        self.usrp.set_rx_antenna(antenna, channel)
        try:
            self.usrp.set_rx_bandwidth(bw, channel)
        except Exception:
            pass

        self.fs = self.usrp.get_rx_rate(channel)
        self.freq = self.usrp.get_rx_freq(channel)

        st = uhd.usrp.StreamArgs("fc32", "sc16")
        st.channels = [channel]
        self.streamer = self.usrp.get_rx_stream(st)
        self.max_samps = self.streamer.get_max_num_samps()
        self.buf = np.zeros((1, self.max_samps), dtype=np.complex64)

    def gain(self):
        return self.usrp.get_rx_gain(self.channel)

    def set_gain(self, g):
        self.usrp.set_rx_gain(float(g), self.channel)

    def read(self, n_samples: int, retries: int = 1) -> tuple[np.ndarray, int]:
        """Read a burst, retrying once if it was corrupted by an overflow.

        The stall that causes an overflow here is transient -- it coincides with
        the GUI redrawing on the main thread -- so an immediate retry usually
        lands in a quiet gap. The count from the LAST attempt is what is
        returned, so a clean retry correctly reports zero.
        """
        for attempt in range(retries + 1):
            samples, overflows = self._read_once(n_samples)
            if overflows == 0 or attempt == retries:
                return samples, overflows
        return samples, overflows

    def _read_once(self, n_samples: int) -> tuple[np.ndarray, int]:
        """Return (samples, overflow_count).

        The overflow count is NOT cosmetic and must not be swallowed. An
        overflow drops samples mid-burst, and since the remaining samples are
        packed in contiguously the code phase jumps at the seam. Coherent
        integration across that seam partially cancels, which shows up as a
        LOWER C/N0 -- indistinguishable from a genuinely weaker signal unless
        the count is surfaced. Reporting a degraded number as if it were a
        measurement is how a host-side scheduling hiccup gets mistaken for an
        antenna problem.
        """
        cmd = self.uhd.types.StreamCMD(self.uhd.types.StreamMode.num_done)
        cmd.num_samps = int(n_samples)
        cmd.stream_now = True
        self.streamer.issue_stream_cmd(cmd)

        md = self.uhd.types.RXMetadata()
        out = np.empty(int(n_samples), dtype=np.complex64)
        got = 0
        overflows = 0
        deadline = time.time() + 5.0
        while got < n_samples and time.time() < deadline:
            n = self.streamer.recv(self.buf, md, 2.0)
            code = md.error_code
            if code != self.uhd.types.RXMetadataErrorCode.none:
                if code == self.uhd.types.RXMetadataErrorCode.timeout:
                    break
                if code == self.uhd.types.RXMetadataErrorCode.overflow:
                    overflows += 1
                continue
            if n == 0:
                continue
            take = min(n, n_samples - got)
            out[got:got + take] = self.buf[0, :take]
            got += take
        return out[:got], overflows


# =====================================================================
# SECTION 2 -- WORKER
# =====================================================================

@dataclass
class Frame:
    results: list = field(default_factory=list)
    psd_db: np.ndarray | None = None
    freqs_mhz: np.ndarray | None = None
    rms: float = 0.0
    peak: float = 0.0
    clipped: float = 0.0
    gain: float = 0.0
    elapsed: float = 0.0
    overflows: int = 0
    note: str = ""


def welch_psd(iq: np.ndarray, fs: float, nfft: int = 1024):
    """Averaged periodogram. Plain numpy so there is no scipy dependency."""
    n_seg = max(1, min(64, len(iq) // nfft))
    win = np.hanning(nfft)
    acc = np.zeros(nfft)
    for k in range(n_seg):
        seg = iq[k * nfft:(k + 1) * nfft]
        if len(seg) < nfft:
            break
        acc += np.abs(np.fft.fftshift(np.fft.fft(seg * win))) ** 2
    acc /= max(1, n_seg)
    psd_db = 10.0 * np.log10(acc / (np.sum(win ** 2) * fs) + 1e-30)
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1.0 / fs))
    return psd_db, freqs / 1e6


class Worker(threading.Thread):
    def __init__(self, radio: LiveRadio, args, out_q: queue.Queue,
                 stop_ev: threading.Event, gain_q: queue.Queue):
        super().__init__(daemon=True)
        self.radio = radio
        self.args = args
        self.q = out_q
        self.stop_ev = stop_ev
        self.gain_q = gain_q

    def run(self):
        need = int(self.radio.fs * 1e-3 * self.args.noncoherent_ms) + 4096
        while not self.stop_ev.is_set():
            try:
                while True:
                    self.radio.set_gain(self.gain_q.get_nowait())
            except queue.Empty:
                pass

            t0 = time.time()
            try:
                iq, overflows = self.radio.read(need)
            except Exception as exc:
                self.q.put(Frame(note=f"read failed: {exc}"))
                time.sleep(1.0)
                continue
            if len(iq) < int(self.radio.fs * 1e-3 * self.args.coherent_ms):
                self.q.put(Frame(note="short read"))
                continue

            mag = np.abs(iq)
            rms = float(np.sqrt(np.mean(mag ** 2)))
            peak = float(mag.max())
            clipped = float(np.count_nonzero(mag >= 0.999) / len(mag))
            psd_db, freqs = welch_psd(iq, self.radio.fs)

            try:
                results = gf.acquire(
                    iq, self.radio.fs,
                    noncoherent_ms=self.args.noncoherent_ms,
                    coherent_ms=self.args.coherent_ms,
                    doppler_max=self.args.doppler_max,
                    doppler_step=self.args.doppler_step,
                    pfa=self.args.pfa,
                )
            except Exception as exc:
                self.q.put(Frame(note=f"acquire failed: {exc}"))
                continue

            self.q.put(Frame(results=results, psd_db=psd_db, freqs_mhz=freqs,
                             rms=rms, peak=peak, clipped=clipped,
                             gain=self.radio.gain(), overflows=overflows,
                             elapsed=time.time() - t0))


# =====================================================================
# SECTION 2b -- gnss-sdr DECODE
# =====================================================================

TRACK_RE = re.compile(
    r"Tracking of GPS L1 C/A signal started on channel (\d+) for satellite "
    r"GPS PRN (\d+)(?:\s*\(Block (\S+)\))?", re.IGNORECASE)
LOSS_RE = re.compile(
    r"Loss of lock in channel (\d+), satellite GPS PRN (\d+)", re.IGNORECASE)
NAV_RE = re.compile(
    r"New GPS NAV message received in channel (\d+).*?PRN (\d+)", re.IGNORECASE)
EPH_RE = re.compile(r"Ephemeris.*?satellite GPS PRN (\d+)", re.IGNORECASE)


@dataclass
class SatState:
    prn: int
    block: str = "?"
    locked: bool = False
    starts: int = 0
    losses: int = 0
    nav: int = 0


class DecodeState:
    """What gnss-sdr is managing to do with the signal, accumulated over a run.

    Kept separate from acquisition on purpose. Acquisition answers "is the
    satellite there"; this answers "can it be held long enough to read". A
    chain can pass the first and fail the second by a wide margin, and that gap
    is the whole diagnosis when a fix does not appear.
    """

    def __init__(self):
        self.sats: dict[int, SatState] = {}
        self.fixes: list[dict] = []
        self.finished = False
        self.source = ""

    def feed(self, line: str) -> str | None:
        m = TRACK_RE.search(line)
        if m:
            prn = int(m.group(2))
            s = self.sats.setdefault(prn, SatState(prn))
            s.block = m.group(3) or s.block
            s.locked = True
            s.starts += 1
            return None
        m = LOSS_RE.search(line)
        if m:
            prn = int(m.group(2))
            s = self.sats.setdefault(prn, SatState(prn))
            s.locked = False
            s.losses += 1
            return None
        m = NAV_RE.search(line) or EPH_RE.search(line)
        if m:
            prn = int(m.group(m.lastindex))
            self.sats.setdefault(prn, SatState(prn)).nav += 1
            return None
        m = gf.POSITION_RE.search(line)
        if m:
            sm = gf.SATS_RE.search(line)
            fix = {"lat": float(m.group(1)), "lon": float(m.group(2)),
                   "alt": float(m.group(3)),
                   "sats": int(sm.group(1)) if sm else 0}
            self.fixes.append(fix)
            return (f"FIX  lat {fix['lat']:.6f}  lon {fix['lon']:.6f}  "
                    f"alt {fix['alt']:.0f} m  sats {fix['sats']}")
        return None

    def summary(self) -> str:
        if not self.sats:
            return ("  waiting for gnss-sdr...\n\n  (acquisition takes a few "
                    "seconds before the\n   first satellite appears)")
        rows = sorted(self.sats.values(),
                      key=lambda s: (-s.locked, -s.nav, -s.starts, s.prn))
        held = sum(1 for s in rows if s.locked)
        out = [f"  {len(rows)} PRN seen   {held} locked now   "
               f"{len(self.fixes)} fix(es)", ""]
        out.append("  PRN  block      state   locks  losses  nav")
        out.append("  " + "-" * 44)
        for s in rows[:14]:
            state = "LOCKED" if s.locked else "  lost"
            out.append(f"  {s.prn:3d}  {s.block:<9.9s} {state}  {s.starts:5d}"
                       f"  {s.losses:6d}  {s.nav:3d}")
        out.append("  " + "-" * 44)
        if self.fixes:
            f = self.fixes[-1]
            out.append(f"  POSITION  {f['lat']:.6f}, {f['lon']:.6f}")
            out.append(f"  altitude  {f['alt']:.1f} m   satellites {f['sats']}")
        else:
            total_loss = sum(s.losses for s in rows)
            out.append("  NO POSITION.")
            if total_loss:
                out.append(f"  {total_loss} lock losses -- tracking cannot hold")
                out.append("  the 30 s of continuous lock an ephemeris needs.")
                out.append("  That is link budget, not tuning.")
        if self.finished:
            out.append("")
            out.append("  [replay finished]")
        return "\n".join(out)


class GnssSdrRunner(threading.Thread):
    """Runs gnss-sdr on a RECORDING, not on the radio.

    Only one process can hold a B210 at a time, and this GUI already has it for
    live acquisition. Pointing gnss-sdr at the same board would simply fail to
    open it, so it decodes a previously captured file instead. The panel is
    labelled accordingly -- conflating a live number with a replayed one is how
    a stale result gets read as a current one.
    """

    def __init__(self, iq_path, gnss_sdr_bin, outdir, q, stop_ev,
                 pll_bw=15.0, dll_bw=1.0, channels=10):
        super().__init__(daemon=True)
        self.iq_path = iq_path
        self.bin = gnss_sdr_bin
        self.outdir = outdir
        self.q = q
        self.stop_ev = stop_ev
        self.pll_bw, self.dll_bw, self.channels = pll_bw, dll_bw, channels
        self.proc = None

    def run(self):
        import os
        import shutil
        import subprocess

        exe = shutil.which(self.bin) or self.bin
        if not os.path.exists(exe):
            self.q.put(("log", f"gnss-sdr not found at {self.bin}"))
            return
        if not os.path.exists(self.iq_path):
            self.q.put(("log", f"no recording at {self.iq_path}"))
            return

        meta = gf.read_sidecar(self.iq_path)
        fs = float(meta.get("sample_rate", gf.DEFAULT_FS))
        fmt = meta.get("format", "sc16")
        os.makedirs(self.outdir, exist_ok=True)
        conf = os.path.join(self.outdir, "gpsgui_decode.conf")
        gf.write_file_conf(conf, self.iq_path, fs, fmt, self.outdir,
                           channels=self.channels, pll_bw=self.pll_bw,
                           dll_bw=self.dll_bw)
        self.q.put(("log", f"gnss-sdr replaying {os.path.basename(self.iq_path)}"
                           f" ({meta.get('seconds','?')} s)"))
        try:
            self.proc = subprocess.Popen(
                [exe, f"--config_file={conf}"], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in self.proc.stdout:
                if self.stop_ev.is_set():
                    break
                self.q.put(("line", line.rstrip()))
        except Exception as exc:
            self.q.put(("log", f"gnss-sdr failed: {exc}"))
        finally:
            if self.proc:
                try:
                    self.proc.terminate()
                except Exception:
                    pass
            self.q.put(("done", ""))


# =====================================================================
# SECTION 3 -- GUI
# =====================================================================

BG = "#12151c"
FG = "#dfe4ee"
ACCENT = "#4da3ff"
GOOD = "#3ddc84"
WARN = "#ffb454"
BAD = "#ff5f5f"
MUTED = "#5b6478"


class Dashboard:
    def __init__(self, root, args, radio, out_q, stop_ev, gain_q, decode_q):
        self.root = root
        self.args = args
        self.radio = radio
        self.q = out_q
        self.stop_ev = stop_ev
        self.gain_q = gain_q
        self.decode_q = decode_q
        self.decode = DecodeState()
        self.fill_history: list[float] = []
        self.cn0_history: list[float] = []
        self.frames = 0

        root.title("GPS L1 -- B210 channel %d / %s" % (args.channel, args.antenna))
        root.configure(bg=BG)
        root.geometry("1400x900")

        self._build_header()
        self._build_plots()
        self._build_log()

        self.log(f"radio open: serial {args.serial} channel {args.channel} "
                 f"antenna {args.antenna}")
        self.log(f"tuned {radio.freq/1e6:.4f} MHz at {radio.fs/1e6:.4f} MSPS, "
                 f"gain {radio.gain():.0f} dB")
        self.log(f"dwell {args.coherent_ms} ms coherent x "
                 f"{args.noncoherent_ms // args.coherent_ms} accumulated, "
                 f"Doppler +/-{args.doppler_max/1000:.0f} kHz")
        self.log("GPS is ~20 dB below the noise floor -- a flat spectrum is "
                 "correct. Judge the chain by C/N0, not by the spectrum.")
        self._refresh_decode()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self.poll)

    # ---------------- header ----------------
    def _build_header(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=12, pady=(10, 4))

        self.status = tk.Label(bar, text="starting...", bg=BG, fg=FG,
                               font=("Menlo", 15, "bold"), anchor="w")
        self.status.pack(side="left")

        right = tk.Frame(bar, bg=BG)
        right.pack(side="right")
        tk.Label(right, text="RX gain (dB)", bg=BG, fg=MUTED,
                 font=("Menlo", 11)).pack(side="left", padx=(0, 6))
        self.gain_var = tk.DoubleVar(value=self.args.gain)
        self.gain_scale = tk.Scale(
            right, from_=0, to=76, orient="horizontal", resolution=1,
            variable=self.gain_var, command=self.on_gain, length=240,
            bg=BG, fg=FG, troughcolor="#232838", highlightthickness=0,
            font=("Menlo", 10))
        self.gain_scale.pack(side="left")

        self.verdict = tk.Label(self.root, text="", bg=BG, fg=MUTED,
                                font=("Menlo", 12), anchor="w",
                                justify="left", wraplength=1350)
        self.verdict.pack(fill="x", padx=12, pady=(0, 6))

    # ---------------- plots ----------------
    def _build_plots(self):
        self.fig = Figure(figsize=(14, 6.4), dpi=100, facecolor=BG)
        gs = self.fig.add_gridspec(2, 2, hspace=0.42, wspace=0.22,
                                   left=0.06, right=0.985,
                                   top=0.93, bottom=0.10)
        self.ax_cn0 = self.fig.add_subplot(gs[0, 0])
        self.ax_spec = self.fig.add_subplot(gs[0, 1])
        self.ax_dop = self.fig.add_subplot(gs[1, 0])
        self.ax_fill = self.fig.add_subplot(gs[1, 1])
        for ax in (self.ax_cn0, self.ax_spec, self.ax_dop, self.ax_fill):
            self._style(ax)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8)

    def _style(self, ax):
        ax.set_facecolor("#181c26")
        ax.tick_params(colors=MUTED, labelsize=9)
        for s in ax.spines.values():
            s.set_color("#2b3243")
        ax.grid(True, color="#242a39", linewidth=0.7)
        ax.title.set_color(FG)
        ax.xaxis.label.set_color(MUTED)
        ax.yaxis.label.set_color(MUTED)

    # ---------------- log ----------------
    def _build_log(self):
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", padx=12, pady=(2, 10))

        left = tk.Frame(wrap, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="LOG", bg=BG, fg=MUTED, anchor="w",
                 font=("Menlo", 10, "bold")).pack(fill="x")
        self.logbox = tk.Text(left, height=11, bg="#0d1017", fg=FG,
                              insertbackground=FG, font=("Menlo", 11),
                              relief="flat", wrap="word")
        sb = ttk.Scrollbar(left, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logbox.pack(side="left", fill="both", expand=True)

        right = tk.Frame(wrap, bg=BG)
        right.pack(side="right", fill="both", padx=(12, 0))
        self.decode_title = tk.Label(
            right, text="GNSS-SDR DECODE", bg=BG, fg=MUTED, anchor="w",
            font=("Menlo", 10, "bold"))
        self.decode_title.pack(fill="x")
        self.decodebox = tk.Text(right, height=11, width=52, bg="#0d1017",
                                 fg=FG, font=("Menlo", 11), relief="flat",
                                 wrap="none")
        self.decodebox.pack(fill="both", expand=True)
        self.logbox.tag_config("good", foreground=GOOD)
        self.logbox.tag_config("warn", foreground=WARN)
        self.logbox.tag_config("bad", foreground=BAD)
        self.logbox.tag_config("muted", foreground=MUTED)

    def log(self, msg, tag="muted"):
        self.logbox.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n", tag)
        self.logbox.see("end")

    # ---------------- control ----------------
    def on_gain(self, _v):
        self.gain_q.put(float(self.gain_var.get()))

    def on_close(self):
        self.stop_ev.set()
        self.root.after(150, self.root.destroy)

    # ---------------- update ----------------
    def poll(self):
        frame = None
        try:
            while True:
                frame = self.q.get_nowait()
        except queue.Empty:
            pass
        if frame is not None:
            if frame.note:
                self.log(frame.note, "bad")
            else:
                self.render(frame)

        dirty = False
        try:
            while True:
                kind, payload = self.decode_q.get_nowait()
                if kind == "line":
                    note = self.decode.feed(payload)
                    if note:
                        self.log(note, "good")
                    dirty = True
                elif kind == "log":
                    self.log(payload, "muted")
                elif kind == "done":
                    self.decode.finished = True
                    self.log("gnss-sdr replay finished", "muted")
                    dirty = True
        except queue.Empty:
            pass
        if dirty:
            self._refresh_decode()

        if not self.stop_ev.is_set():
            self.root.after(250, self.poll)

    def _refresh_decode(self):
        self.decodebox.delete("1.0", "end")
        self.decodebox.insert("1.0", self.decode.summary())
        n_fix = len(self.decode.fixes)
        self.decode_title.configure(
            text=("GNSS-SDR DECODE  (replay of recording)"
                  + ("  -- FIX" if n_fix else "")),
            fg=(GOOD if n_fix else MUTED))

    def render(self, f: Frame):
        self.frames += 1
        hits = [r for r in f.results if r.detected]
        thr = f.results[0].threshold_db if f.results else 0.0
        best = max((r.cn0_dbhz for r in hits), default=0.0)

        self.fill_history.append(f.rms * 100)
        self.cn0_history.append(best)
        self.fill_history = self.fill_history[-120:]
        self.cn0_history = self.cn0_history[-120:]

        ovf = f"   OVF {f.overflows}" if f.overflows else ""
        self.status.configure(
            text=(f"{len(hits)} satellite(s)   best C/N0 "
                  f"{best:5.1f} dB-Hz   gain {f.gain:.0f} dB   "
                  f"fill {f.rms*100:5.2f}%   scan {f.elapsed:.1f}s   "
                  f"#{self.frames}{ovf}"),
            fg=(BAD if f.overflows else
                GOOD if len(hits) >= 4 else WARN if hits else BAD))

        self.verdict.configure(text=self._verdict(f, hits, best),
                               fg=(BAD if f.overflows else
                                   GOOD if len(hits) >= 4
                                   else WARN if hits else BAD))
        if f.overflows and self.frames % 5 == 1:
            self.log(f"{f.overflows} overflow(s) -- C/N0 understated this scan",
                     "bad")

        if self.frames == 1 or len(hits) != getattr(self, "_last_n", -1):
            self._last_n = len(hits)
            if hits:
                names = ", ".join(f"PRN{r.prn}({r.cn0_dbhz:.0f})" for r in hits)
                self.log(f"acquired {len(hits)}: {names}",
                         "good" if len(hits) >= 4 else "warn")
            else:
                self.log("no satellites in this scan", "bad")

        self._plot_cn0(f, hits, thr)
        self._plot_spec(f)
        self._plot_dop(f, hits)
        self._plot_fill()
        self.canvas.draw_idle()

    def _verdict(self, f, hits, best):
        if f.overflows:
            return (f"{f.overflows} OVERFLOW(S) this scan -- the host dropped "
                    "samples, so the code phase jumps mid-window and the C/N0 "
                    "shown is UNDERSTATED. Do not judge the antenna from this "
                    "scan. Reduce --noncoherent-ms or close other load first.")
        if f.clipped > 1e-4:
            return ("CLIPPING -- the front end is saturated. Lower the gain "
                    "until this clears; nothing above is trustworthy.")
        if f.rms < 0.01:
            return ("ADC fill under 1% -- too little gain reaching the ADC, or "
                    "the RFFE is not powered. Raise gain; if C/N0 does not rise "
                    "with it, the front end has no LNA in circuit.")
        if not hits:
            return ("No satellites. This is link budget or siting, not tuning: "
                    "RFFE power, sky view, and the cable being on this channel's "
                    "RX2 port. gnss-sdr cannot decode what is not here.")
        if len(hits) < 4:
            return (f"{len(hits)} satellite(s) -- real signal, but a 3D fix "
                    "needs 4 tracked at once. Better sky view, or more gain "
                    "ahead of the B210.")
        if best < 35:
            return (f"{len(hits)} satellites but best C/N0 only {best:.0f} dB-Hz. "
                    "A fix may be unstable; healthy is 40-48 dB-Hz.")
        return (f"{len(hits)} satellites, best {best:.0f} dB-Hz -- healthy. "
                "Run gpsfix.py --run to decode a position.")

    def _plot_cn0(self, f, hits, thr):
        ax = self.ax_cn0
        ax.clear(); self._style(ax)
        prns = [r.prn for r in f.results]
        vals = [max(0.0, r.cn0_dbhz) for r in f.results]
        cols = [GOOD if r.detected else "#2f3646" for r in f.results]
        ax.bar(prns, vals, color=cols, width=0.78)
        ax.set_title(f"C/N0 per PRN   ({len(hits)} acquired, "
                     f"threshold {thr:.1f} dB)", fontsize=11)
        ax.set_xlabel("PRN"); ax.set_ylabel("dB-Hz")
        ax.set_xlim(0, 33)
        ax.set_ylim(0, max(50, max(vals) + 5 if vals else 50))
        ax.axhline(35, color=WARN, ls="--", lw=1)
        ax.text(0.6, 35.6, "35 dB-Hz: usable fix", color=WARN, fontsize=8)
        for r in hits:
            ax.text(r.prn, r.cn0_dbhz + 0.7, str(r.prn), color=GOOD,
                    fontsize=8, ha="center")

    def _plot_spec(self, f):
        ax = self.ax_spec
        ax.clear(); self._style(ax)
        if f.psd_db is not None:
            ax.plot(f.freqs_mhz, f.psd_db, color=ACCENT, lw=0.9)
            span = f.psd_db.max() - f.psd_db.min()
            ax.set_ylim(f.psd_db.min() - 2, f.psd_db.max() + 4)
            flag = "  <-- SPUR/JAMMER?" if span > 25 else ""
            ax.set_title(f"Spectrum around L1 (GPS is invisible here){flag}",
                         fontsize=11,
                         color=(BAD if span > 25 else FG))
        ax.set_xlabel("offset from 1575.42 MHz [MHz]")
        ax.set_ylabel("dB/Hz")

    def _plot_dop(self, f, hits):
        ax = self.ax_dop
        ax.clear(); self._style(ax)
        if hits:
            ax.scatter([r.prn for r in hits], [r.doppler_hz / 1000 for r in hits],
                       s=[max(28, (r.cn0_dbhz - 20) * 7) for r in hits],
                       color=GOOD, alpha=0.85, edgecolors="none")
            for r in hits:
                ax.annotate(f"{r.prn}", (r.prn, r.doppler_hz / 1000),
                            textcoords="offset points", xytext=(0, 8),
                            color=FG, fontsize=8, ha="center")
        ax.axhspan(-5, 5, color=GOOD, alpha=0.06)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.set_title("Doppler per acquired PRN (marker area ~ C/N0)", fontsize=11)
        ax.set_xlabel("PRN"); ax.set_ylabel("Doppler [kHz]")
        ax.set_xlim(0, 33)
        ax.set_ylim(-self.args.doppler_max / 1000 - 1,
                    self.args.doppler_max / 1000 + 1)

    def _plot_fill(self):
        ax = self.ax_fill
        ax.clear(); self._style(ax)
        x = range(len(self.fill_history))
        ax.plot(x, self.fill_history, color=ACCENT, lw=1.4, label="ADC fill %")
        ax.axhspan(1, 15, color=GOOD, alpha=0.07)
        ax.set_ylabel("ADC fill [% of full scale]")
        ax.set_xlabel("scan")
        ax.set_title("Level and best C/N0 history", fontsize=11)
        ax2 = ax.twinx()
        ax2.plot(x, self.cn0_history, color=GOOD, lw=1.4)
        ax2.set_ylabel("best C/N0 [dB-Hz]", color=GOOD)
        ax2.tick_params(colors=GOOD, labelsize=9)
        ax2.set_ylim(0, 50)
        for s in ax2.spines.values():
            s.set_color("#2b3243")


# =====================================================================
# SECTION 4 -- CLI
# =====================================================================

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Live GPS L1 dashboard for one USRP B210 RX channel.")
    p.add_argument("--serial", default=gf.DEFAULT_SERIAL)
    p.add_argument("--channel", type=int, default=gf.DEFAULT_CHANNEL)
    p.add_argument("--antenna", default=gf.DEFAULT_ANTENNA)
    p.add_argument("--subdev", default=gf.DEFAULT_SUBDEV)
    p.add_argument("--gain", type=float, default=71.0)
    p.add_argument("--fs", type=float, default=gf.DEFAULT_FS)
    p.add_argument("--freq", type=float, default=gf.L1_HZ)
    p.add_argument("--coherent-ms", type=int, default=gf.DEFAULT_COH_MS)
    p.add_argument("--noncoherent-ms", type=int, default=80)
    p.add_argument("--doppler-max", type=float, default=gf.DEFAULT_DOPPLER_MAX)
    # 500 Hz rather than gpsfix's 250 Hz: half the bins, so the loop refreshes
    # in about a second. Costs a little Doppler resolution, which the dashboard
    # does not need.
    p.add_argument("--doppler-step", type=float, default=500.0)
    p.add_argument("--pfa", type=float, default=gf.DEFAULT_PFA)
    p.add_argument("--decode-file", default="/tmp/gpsfix/gps_ch1.iq",
                   help="recording for the gnss-sdr decode panel. It replays a "
                        "FILE because only one process can hold the B210 and "
                        "this GUI has it for live acquisition.")
    p.add_argument("--no-decode", action="store_true",
                   help="skip the gnss-sdr panel")
    p.add_argument("--gnss-sdr", default="gnss-sdr")
    p.add_argument("--pll-bw", type=float, default=15.0)
    p.add_argument("--dll-bw", type=float, default=1.0)
    p.add_argument("--outdir", default="/tmp/gpsfix")
    args = p.parse_args(argv)

    print(f"opening serial={args.serial} channel {args.channel} ...")
    radio = LiveRadio(args.serial, args.channel, args.gain, args.fs,
                      args.freq, args.antenna, args.subdev, args.fs)
    print(f"tuned {radio.freq/1e6:.4f} MHz at {radio.fs/1e6:.4f} MSPS")

    out_q: queue.Queue = queue.Queue()
    gain_q: queue.Queue = queue.Queue()
    decode_q: queue.Queue = queue.Queue()
    stop_ev = threading.Event()
    Worker(radio, args, out_q, stop_ev, gain_q).start()

    if not args.no_decode and os.path.exists(args.decode_file):
        GnssSdrRunner(args.decode_file, args.gnss_sdr, args.outdir, decode_q,
                      stop_ev, args.pll_bw, args.dll_bw).start()
    elif not args.no_decode:
        decode_q.put(("log", f"no recording at {args.decode_file} -- run "
                             "gpsfix.py --record first for the decode panel"))

    root = tk.Tk()
    Dashboard(root, args, radio, out_q, stop_ev, gain_q, decode_q)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        stop_ev.set()
    stop_ev.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
