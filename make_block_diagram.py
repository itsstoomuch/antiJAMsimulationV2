"""Render the COGNAV-P1 (Arch 4) flight-prototype block diagram to PNG.

Layout: four horizontal analog channel chains feeding a vertical Wilkinson
combiner (the analog GPS path), with the digital sensing brain along the
bottom and outputs on the right. Colors: green = analog GPS path,
blue = digital sensing, orange = control/feedback, gray = support.
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# palette
ANALOG = dict(fc="#d5e8d4", ec="#4e7a3a")
DIGITAL = dict(fc="#dae8fc", ec="#39597a")
CTRL = dict(fc="#ffe6cc", ec="#b06a00")
SUPPORT = dict(fc="#f2f2f2", ec="#777777")
OUT = dict(fc="#fff2cc", ec="#a8861a")

fig, ax = plt.subplots(figsize=(16.5, 10.6))
ax.set_xlim(0, 165)
ax.set_ylim(0, 106)
ax.axis("off")


def box(x, y, w, h, label, style, fs=8.0, lw=1.4, bold=False):
    p = mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.25,rounding_size=0.8",
        fc=style["fc"], ec=style["ec"], lw=lw, zorder=3)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=fs, zorder=4, color="#1a1a1a",
            fontweight="bold" if bold else "normal", linespacing=1.15)
    return p


def arrow(x1, y1, x2, y2, color="#222222", lw=1.5, ls="-", z=2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw,
                                linestyle=ls, shrinkA=0, shrinkB=0),
                zorder=z)


def line(pts, color="#222222", lw=1.5, ls="-", z=2):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=lw, ls=ls, zorder=z,
            solid_capstyle="round")


# ---------------- title ----------------
ax.text(82, 103.2, "COGNAV-P1  —  L1 Analog-Nulling CRPA (Arch 4)  —  Flight Prototype",
        ha="center", fontsize=15.5, fontweight="bold")
ax.text(82, 99.8, "GPS L1 1575.42 MHz only  |  2×2 RHCP array, d = λ/2 = 95.1 mm  |  "
        "jammer suppressed in ANALOG domain before any ADC  |  ≤ 8 W from 4S–6S drone bus",
        ha="center", fontsize=9, color="#444444")

# ---------------- 4 analog channel chains ----------------
rows = [86, 74, 62, 50]          # channel row centers (CH1 top .. CH4 bottom)
BH = 7                            # box height
cols = [   # (x, w, label)
    (3,  8,  "PATCH\n{n}"),
    (14, 9,  "PIN\nLIMITER"),
    (26, 9,  "SAW BPF\nMurata"),
    (38, 9,  "LNA\nQPL9547"),
    (50, 13, "COUPLER\n−10 dB"),
    (70, 14, "VECTOR MOD\nAD8341"),
]
for i, yc in enumerate(rows):
    y0 = yc - BH / 2
    for j, (x, w, lab) in enumerate(cols):
        style = ANALOG if j > 0 else OUT
        box(x, y0, w, lab.format(n=i + 1), style) if False else None
        box(x, y0, w, BH, lab.format(n=i + 1), style, fs=7.6)
    # chain arrows between boxes
    for (x, w, _), (x2, _, _) in zip(cols, cols[1:]):
        arrow(x + w + 0.25, yc, x2 - 0.25, yc, lw=1.6)
    # VM -> combiner
    arrow(cols[-1][0] + cols[-1][1] + 0.25, yc, 90 - 0.25, yc, lw=1.6)

# ---------------- combiner ----------------
box(90, 46, 9, 44, "4-WAY\nWILKINSON\nΣ\n\n(microstrip\nRO4350)\n\nJAMMER\nDIES\nHERE", ANALOG, fs=8, lw=2, bold=True)

# ---------------- sense taps (couplers -> sensing RX) ----------------
sense_xs = [64.6, 65.6, 66.6, 67.6]
for xi, yc in zip(sense_xs, rows):
    line([(63 + 0.3, yc - 2.2), (xi, yc - 2.2), (xi, 41)],
         color="#39597a", lw=1.1)
line([(64.6, 41), (78, 41)], color="#39597a", lw=1.6)
arrow(77.0, 41, 78.0, 41, color="#39597a", lw=1.6)
ax.text(63.8, 44.6, "4× sense taps\n(always unweighted)", fontsize=7,
        color="#39597a", ha="right", style="italic")

# ---------------- digital bottom row ----------------
box(78, 33, 26, 10, "4-CH COHERENT SENSING RX\nsingle-LO (NT1065-class)\nor 2×AD9361 + cal  •  12-bit IQ",
    DIGITAL, fs=7.8)
box(110, 26, 30, 16,
    "ZYNQ-7020 (FPGA + ARM)\n• R̂ covariance → MUSIC DOA\n• MVDR weight solve"
    "\n• TRIM loop (power-det dither)\n• cal FSM  • PI fallback (Arch 1)",
    DIGITAL, fs=7.8, lw=1.8, bold=False)
arrow(104.3, 38, 110, 38, color="#39597a", lw=1.8)

box(78, 19, 26, 6.5, "AD5676 16-bit DAC ×8\n+ OPA354 buffers", CTRL, fs=7.8)
# FPGA -> DAC (elbow)
line([(110, 29), (107, 29), (107, 22.2), (104.6, 22.2)], color="#b06a00", lw=1.6)
arrow(105.4, 22.2, 104.3, 22.2, color="#b06a00", lw=1.6)
# DAC -> VMs (weight voltages up into VM column)
line([(84, 25.8), (84, 45.9)], color="#b06a00", lw=2.0)
arrow(84, 44.9, 84, 46.1, color="#b06a00", lw=2.0)
ax.text(85.2, 30.5, "8× I/Q weight\nvoltages\n(fans to all 4 VMs)", fontsize=7,
        color="#b06a00", style="italic")

# ---------------- cal tone ----------------
box(44, 24, 16, 6.5, "CAL SYNTH\n(L1 tone, keyed)", CTRL, fs=7.8)
line([(52, 30.8), (52, 46.0)], color="#b06a00", lw=1.4, ls="--")
arrow(52, 45.0, 52, 46.2, color="#b06a00", lw=1.4)
ax.text(51, 36.5, "cal tone → 4× coupler\nisolated ports", fontsize=7,
        color="#b06a00", ha="right", style="italic")

# ---------------- combiner outputs ----------------
# main node out of combiner
line([(99.3, 72), (104, 72)], lw=1.8)
box(104, 68, 16, 8, "POST-LNA\n+ BPF", ANALOG, fs=8)
arrow(120.3, 72, 126, 72, lw=1.8)
box(126, 66, 22, 12, "SMA — CLEAN L1 RF OUT\nactive-antenna emulation\n(any GNSS receiver /\nautopilot GPS port)", OUT, fs=7.8, lw=1.8, bold=False)
# branch down to u-blox and detector
line([(102, 72), (102, 58), (104, 58)], lw=1.6)
arrow(103.2, 58, 104.2, 58, lw=1.6)
box(104, 54, 16, 8, "u-blox M10\nGNSS RX\n(embedded)", ANALOG, fs=7.8)
line([(102, 58), (102, 48.2), (122, 48.2)], lw=1.6)
arrow(121, 48.2, 122.2, 48.2, lw=1.6)
box(122, 45, 17, 6.2, "PWR DET\nAD8314", CTRL, fs=7.8)
# detector -> FPGA (trim feedback)
line([(130, 44.8), (130, 42.4)], color="#b06a00", lw=1.8, ls="--")
arrow(130, 43.2, 130, 42.2, color="#b06a00", lw=1.8)
ax.text(131.2, 43.4, "residual jammer\npower (trim)", fontsize=7, color="#b06a00",
        style="italic")
# u-blox -> UART box ; FPGA -> UART box
box(146, 30, 16, 13, "UART →\nAUTOPILOT\nNMEA + C/N₀\n+ jammer\nbearings", OUT, fs=7.6)
line([(120.3, 58), (152, 58), (152, 43.6)], lw=1.4)
arrow(152, 44.6, 152, 43.4, lw=1.4)
line([(140.3, 34), (146, 34)], color="#39597a", lw=1.6)
arrow(145, 34, 146.2, 34, color="#39597a", lw=1.6)

# ---------------- support ----------------
box(110, 17.5, 22, 6, "IMU ICM-42688\n(+ almanac → a(θs))", SUPPORT, fs=7.4)
arrow(121, 23.8, 121, 25.7, color="#777777", lw=1.3)
box(40, 11, 28, 6, "TCXO 10 MHz + 1:4 CLK BUFFER\n(shared, holdover — NO GPSDO)", SUPPORT, fs=7.4)
line([(68.3, 14), (74, 14), (74, 35.5), (77.7, 35.5)], color="#777777", lw=1.2, ls="--")
arrow(76.8, 35.5, 78.0, 35.5, color="#777777", lw=1.2)
line([(68.3, 14), (108, 14), (108, 25.7)], color="#777777", lw=1.2, ls="--")
arrow(108, 24.8, 108, 26.0, color="#777777", lw=1.2)
box(3, 11, 33, 6, "POWER: 12–24 V drone bus → buck 5 V\n→ low-noise LDO tree (analog rails)", SUPPORT, fs=7.4)

# ---------------- legend ----------------
lx, ly = 3, 25.5
ax.text(lx, ly + 6.5, "Legend", fontsize=8.5, fontweight="bold")
for dy, (style, lab) in enumerate([
        (ANALOG, "Analog GPS path (jammer suppressed here, pre-ADC)"),
        (DIGITAL, "Digital sensing brain (never carries the GPS signal)"),
        (CTRL, "Control / feedback (weights, cal, trim)"),
        (SUPPORT, "Support (clock, power, attitude)")]):
    yy = ly + 4 - dy * 2.6
    ax.add_patch(mpatches.Rectangle((lx, yy - 0.8), 2.6, 1.7,
                 fc=style["fc"], ec=style["ec"], lw=1.2))
    ax.text(lx + 3.4, yy, lab, fontsize=7.4, va="center")

# channel group label
ax.text(3, 92.2, "4× identical analog channels  (CH1–CH4, top→bottom)",
        fontsize=8, color="#4e7a3a", style="italic")

fig.savefig("/Users/atharvrathod/antiJAMsimulation/cognav_p1_block_diagram.png",
            dpi=200, bbox_inches="tight", facecolor="white")
print("saved")
