# GPS L1 receive on B210 channel 1 / RX2, through the RFFE, to lat/lon

One antenna, one receive channel, an RF front end, and a position out the end.
This is the single-channel path — it does **not** need the four-channel CRPA
sync (no 10 MHz reference, no shared PPS, no boresight calibration), because a
single channel on a single board is self-coherent by construction.

**Chain:** antenna → RFFE (LNA + L1 filter + DC bias) → B210 `RX2` on channel 1
(subdev `A:B`), serial `34D04E6` → 1575.42 MHz @ 4 MSPS → acquisition → gnss-sdr
→ NMEA → lat/lon.

## Files

| File | What it is |
|---|---|
| `gpsfix.py` | The tool. Probe, record, acquire, fix. Pure Python + numpy. |
| `usrp_gps_l1_ch1.conf` | gnss-sdr config for the **live** path, channel 1. |
| `run_gpsfix.sh` | Push to the SBC over ssh and run it there. |

`gpsfix.py` writes its own gnss-sdr config for the recorded path, so
`usrp_gps_l1_ch1.conf` is only for `--live`.

## Before anything else: getting onto the box

At the time of writing the SBC at `10.79.122.240` was **not reachable** from the
development Mac on the same `/24`. Ping, ssh and mDNS all timed out and the ARP
entry stayed `(incomplete)`:

```
$ arp -n 10.79.122.240
? (10.79.122.240) at (incomplete) on en0 ifscope [ethernet]
```

An incomplete ARP entry for a host on your own subnet means the frames are not
crossing at layer 2. Both machines were on Wi-Fi, so the cause is almost
certainly **AP client isolation**, which many office and campus networks enable
to stop clients talking to each other. Nothing on the client side fixes it.

Options, in order of least effort:

1. Run `gpsfix.py` **on the SBC's own console**. It needs only `python3` and
   `numpy` — copy it on a USB stick and skip the network entirely.
2. Put both machines on a phone hotspot, or wire the SBC to the same switch.
3. Use the SBC's wired port `eno0` (currently `NO-CARRIER`) with a cable.

Confirm before blaming the radio:

```sh
arp -n 10.79.122.240        # "(incomplete)" -> layer 2 is blocked, not GPS
ssh padtpl@10.79.122.240 true
```

## Prerequisites on the SBC

```sh
sudo apt install uhd-host python3-uhd python3-numpy
sudo uhd_images_downloader          # once, for the B210 FPGA image
uhd_find_devices                    # must list serial 34D04E6
sudo apt install gnss-sdr           # only --fix and --live need this
```

`gpsfix.py --selftest` verifies the whole DSP path with no radio and no
gnss-sdr. Run it first; if it fails, nothing downstream is trustworthy.

## Bring-up order

Do not skip a step. Each one isolates a failure the next cannot distinguish.

### 0. Verify the tool

```sh
./gpsfix.py --selftest
```
Expect `All checks passed.` — 22 checks covering the C/A generator against
IS-GPS-200, acquisition against synthetic signals with known answers, the false
alarm rate, IQ file round trips, NMEA parsing and config generation.

### 1. Ask the radio what it has

```sh
./gpsfix.py --probe
```

Confirm: 2 RX channels, channel 1 present, `RX2` in its antenna list, gain
range 0–76 dB. If channel 1 is missing, the subdev spec collapsed to one
channel — force it with `--subdev 'A:A A:B'`.

### 2. Find the right gain for the RFFE

**This is the step most likely to be skipped and most likely to be the
problem.** The gain that suits a bare passive patch is badly wrong for an
amplified front end.

```sh
./gpsfix.py --gain-sweep 20,30,40,50,60 --sweep-seconds 2
```

It records at each gain, reports the ADC fill, runs a full PRN search on each,
and recommends one. Target RMS fill is 1–15 % of full scale.

| Symptom | Meaning |
|---|---|
| RMS > 15 %, or any clipping | Front end in compression. Drop 10 dB. |
| RMS < 1 % | Too little gain — **or the RFFE is not powered**. |

The B210's `RX2` port supplies **no DC bias**. An active antenna must be fed
from the RFFE or an external bias-T. This project's record is unambiguous that
a passive chain is a link-budget dead end.

### 3. Record

```sh
./gpsfix.py --record --seconds 120 --gain 40
```

120 s at 4 MSPS in `sc16` is ~1.9 GB. A first fix needs **at least 30 s** of
continuous signal, because the receiver has to decode a full ephemeris from
subframes 1–3, which repeat every 30 s.

Watch for overflow warnings — they mean the host could not keep up and the
recording has discontinuities that will break tracking.

### 4. Are there satellites in the capture at all?

```sh
./gpsfix.py --acq
```

This is the gate that separates a link-budget failure from a tracking failure,
and it takes about 4 seconds. A spectrum plot can never answer this question:
GPS L1 arrives ~20 dB **below** thermal noise, so it is invisible to any power
measurement. Correlating against the satellite's own code recovers ~43 dB, which
is the only reason any of this works.

* **0 satellites** → stop. It is the antenna, the RFFE power, the sky view or
  the port. Nothing in gnss-sdr will help.
* **4 or more** → proceed. There is a fix in this data.
* **1–3** → real signal, not enough for 3D. Better sky view or a longer capture.

### 5. Position

```sh
./gpsfix.py --fix
```

Prints `[FIX] lat … lon … alt … sats …` as gnss-sdr solves, then a summary with
an OpenStreetMap link. NMEA, KML and GPX land in `/tmp/gpsfix/`.

### All of it in one command

```sh
./gpsfix.py --run --seconds 120 --gain 40
```

Records, acquires, and only runs gnss-sdr if acquisition found something —
because gnss-sdr cannot decode what is not there.

### Continuous, once the chain is known good

```sh
gnss-sdr --config_file=usrp_gps_l1_ch1.conf
# or
./gpsfix.py --live
```

## Measured behaviour of the acquisition search

From synthetic captures with known answers (`--selftest` and the sweeps behind
it), at 4 MSPS with a CFAR false-alarm rate of 1e-3 per PRN:

| Coherent dwell | Window | Detection floor |
|---|---|---|
| 1 ms | 20 ms | ~34 dB-Hz |
| 2 ms | 40 ms | ~30 dB-Hz |
| 4 ms | 80 ms | ~28 dB-Hz |
| 10 ms | 200 ms | ~26 dB-Hz |

Default is 4 ms × 20 groups. A working active antenna delivers 35–48 dB-Hz, so
the default floor sits well below anything real — a null result is meaningful.

**The two dwells do not trade the way people expect.** Raising the coherent
dwell *inside a fixed window* is close to neutral: coherent gain rises, but
fewer non-coherent groups remain, the noise tail gets heavier and the CFAR
threshold rises by almost exactly as much. You get ~3 dB per doubling only if
you extend the window to keep the group count constant. Adding non-coherent
milliseconds alone barely moves the floor at all, because the peak-to-mean-floor
ratio is (S+N)/N no matter how many magnitudes are summed.

This is also why the detection threshold is **derived**, never fixed. A constant
9 dB threshold is safe at 1 ms × 10 groups and produces a dozen false PRNs at
4 ms × 5 groups, which would read as "satellites everywhere".

## Two errors in the older `usrp_gps_l1.conf`

That file predates this work and targets the array, not this chain. Both of its
mistakes are silent:

1. **`SignalSource.antenna=RX2` does nothing.** gnss-sdr's `UHD_Signal_Source`
   reads no antenna property at all — in `uhd_signal_source.cc` the
   `set_antenna()` call is commented out. The line looks like it selects the
   port and does not. It happens to work anyway because UHD's B200/B210 driver
   initialises every RX frontend to `RX2` in `b200_impl.cpp`, so a fresh process
   lands there by default. That is a default, not a request. `gpsfix.py
   --record` calls `set_rx_antenna()` explicitly and fails loudly if the port is
   unavailable.
2. **`internal_fs_sps=4096000` with a comment claiming it "matches gpsacq".** It
   does not: `gpsacq.cpp` has `SAMPLE_RATE = 4e6`. `usrp_gps_l1_ch1.conf` and
   `gpsfix.py` both use 4 MSPS so all three tools are comparable.

Also note `usrp_gps_l1.conf` uses `subdevice=A:A`, which is **channel 0**. On an
antenna wired to channel 1 that produces a clean recording of nothing.

## Troubleshooting

| Symptom | First thing to check |
|---|---|
| `--probe` shows 1 RX channel | `--subdev 'A:A A:B'` |
| RMS fill < 1 % | RFFE unpowered — it needs DC the B210 will not supply |
| RMS fill > 15 % or clipping | Gain too high for an amplified front end |
| 0 satellites in `--acq` | Sky view, RFFE power, cable on the wrong port |
| Satellites acquired, no fix | Capture ≥ 30 s? Then `--pll-bw 15 --dll-bw 1.0` |
| Overflow warnings while recording | Slow disk or USB — record to SSD, or use `--iq-format sc16` |
| Locks cycle in gnss-sdr | Narrow the loops; this is the failure the passive patches showed |

## What this does not do

Acquisition here yields Doppler and code phase, **not** a position — gnss-sdr
does tracking, navigation-message decode and the PVT solve. `gpsfix.py --acq`
exists to answer one question cheaply and unambiguously: is the signal there?
