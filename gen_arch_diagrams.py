"""Render the three COGNAV architecture block diagrams (matching style):
  arch1_diagram.png — Blind Power-Inversion Nulling
  arch2_diagram.png — Sensing-Tap Hybrid (open-loop MUSIC+MVDR)
  arch3_diagram.png — Closed-Loop Hybrid (MVDR aim + trim) — COGNAV-P1
Colors: green = analog GPS path, blue = digital sensing, orange = control/feedback,
gray = support, yellow = I/O.
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

ANALOG = dict(fc="#d5e8d4", ec="#4e7a3a")
DIGITAL = dict(fc="#dae8fc", ec="#39597a")
CTRL = dict(fc="#ffe6cc", ec="#b06a00")
SUPPORT = dict(fc="#f2f2f2", ec="#777777")
OUT = dict(fc="#fff2cc", ec="#a8861a")

OUTDIR = "/Users/atharvrathod/antiJAMsimulation/"


def new_canvas():
    fig, ax = plt.subplots(figsize=(16.5, 10.6))
    ax.set_xlim(0, 165)
    ax.set_ylim(0, 106)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, label, style, fs=8.0, lw=1.4, bold=False):
    p = mpatches.FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0.25,rounding_size=0.8",
                                fc=style["fc"], ec=style["ec"], lw=lw, zorder=3)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=fs,
            zorder=4, color="#1a1a1a",
            fontweight="bold" if bold else "normal", linespacing=1.15)


def arrow(ax, x1, y1, x2, y2, color="#222222", lw=1.5, ls="-"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw,
                                linestyle=ls, shrinkA=0, shrinkB=0), zorder=2)


def line(ax, pts, color="#222222", lw=1.5, ls="-"):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=lw, ls=ls, zorder=2, solid_capstyle="round")


def legend(ax, lx, ly, items):
    ax.text(lx, ly + 6.5, "Legend", fontsize=8.5, fontweight="bold")
    for dy, (style, lab) in enumerate(items):
        yy = ly + 4 - dy * 2.6
        ax.add_patch(mpatches.Rectangle((lx, yy - 0.8), 2.6, 1.7,
                     fc=style["fc"], ec=style["ec"], lw=1.2))
        ax.text(lx + 3.4, yy, lab, fontsize=7.4, va="center")


def chains(ax, cols, rows, BH=7, into_x=None):
    """Draw 4 identical channel chains and arrows; return nothing."""
    for i, yc in enumerate(rows):
        y0 = yc - BH / 2
        for j, (x, w, lab) in enumerate(cols):
            style = ANALOG if j > 0 else OUT
            box(ax, x, y0, w, BH, lab.format(n=i + 1), style, fs=7.6)
        for (x, w, _), (x2, _, _) in zip(cols, cols[1:]):
            arrow(ax, x + w + 0.25, yc, x2 - 0.25, yc, lw=1.6)
        if into_x is not None:
            xl, wl, _ = cols[-1]
            arrow(ax, xl + wl + 0.25, yc, into_x - 0.25, yc, lw=1.6)


# =====================================================================
# ARCHITECTURE 1 — Blind Power-Inversion
# =====================================================================
def arch1():
    fig, ax = new_canvas()
    ax.text(82, 103.2, "ARCHITECTURE 1  —  Blind Power-Inversion Nulling",
            ha="center", fontsize=15.5, fontweight="bold")
    ax.text(82, 99.8, '"The array that FEELS the jammer"  |  one ADC after the combiner — '
            "no per-element observation  |  weights found by trial (Compton 1979)",
            ha="center", fontsize=9, color="#444444")

    rows = [86, 74, 62, 50]
    cols = [(3, 8, "PATCH\n{n}"), (15, 10, "PIN\nLIMITER"), (28, 10, "SAW BPF\nMurata"),
            (41, 10, "LNA\nQPL9547"), (54, 14, "WEIGHT\nφ-shift + VGA")]
    chains(ax, cols, rows, into_x=74)
    box(ax, 74, 46, 9, 44, "4-WAY\nWILKINSON\nΣ\n\nJAMMER\nDIES\nHERE", ANALOG, fs=8, lw=2, bold=True)

    # output chain
    line(ax, [(83.3, 72), (88, 72)], lw=1.8)
    box(ax, 88, 68, 16, 8, "BPF +\nPOST-LNA", ANALOG, fs=8)
    line(ax, [(104.3, 72), (110, 72)], lw=1.8)
    box(ax, 110, 68, 12, 8, "ADC", ANALOG, fs=8.5, bold=True)
    arrow(ax, 122.3, 72, 128, 72, lw=1.8)
    box(ax, 128, 64, 24, 14, "GPS CORRELATOR\n+ C/N₀ monitor\n→ position fix\n(UART out)", OUT, fs=7.8, lw=1.8)
    ax.text(116, 64.6, "sized for α = 0\n(full jammer at\nre-convergence)", fontsize=6.8,
            color="#4e7a3a", ha="center", style="italic")

    # power detector branch
    line(ax, [(106, 72), (106, 56), (108, 56)], lw=1.6)
    arrow(ax, 107.2, 56, 108.2, 56, lw=1.6)
    box(ax, 108, 52, 18, 7.5, "COUPLER →\nPWR DET", CTRL, fs=7.8)

    # FPGA/MCU
    box(ax, 56, 22, 46, 16,
        "FPGA / MCU  —  POWER INVERSION\n"
        "• dither wₙ ±Δ → measure ΔP (detector)\n"
        "• gradient step  w ← w − µ·∇̂P\n"
        "• constraint w₀ = 1 (reference element — NOT θs)\n"
        "• AGC disable • ADC config • (opt.) 16-probe R̂ reconstruction",
        DIGITAL, fs=7.8, lw=1.8)

    # control: FPGA -> weights
    line(ax, [(61, 38.3), (61, 45.9)], color="#b06a00", lw=2.0)
    arrow(ax, 61, 44.9, 61, 46.1, color="#b06a00", lw=2.0)
    ax.text(62.2, 41.5, "SPI φ + SPI A\nweight words ×4", fontsize=7,
            color="#b06a00", style="italic")

    # feedback: detector -> FPGA (fast), C/N0 -> FPGA (slow)
    line(ax, [(117, 51.7), (117, 44), (102.4, 44)], color="#b06a00", lw=1.8, ls="--")
    line(ax, [(102.4, 44), (102.4, 36)], color="#b06a00", lw=1.8, ls="--")
    arrow(ax, 102.4, 37, 102.3, 35.8, color="#b06a00", lw=1.8)
    ax.text(118.2, 47.5, "FAST trigger\n(ms-scale)", fontsize=7, color="#b06a00", style="italic")
    line(ax, [(140, 63.7), (140, 30), (102.4, 30)], color="#777777", lw=1.4, ls="--")
    arrow(ax, 103.4, 30, 102.2, 30, color="#777777", lw=1.4)
    ax.text(141.2, 46, "SLOW KPI\n(C/N₀ drop,\n0.1–1 s)", fontsize=7, color="#777777", style="italic")

    # what's missing on purpose
    box(ax, 128, 22, 34, 16,
        "NOT PRESENT (by design):\n• sense couplers / 4-ch RX\n• MUSIC — no DOA possible\n"
        "• a(θs) constraint / IMU\n→ single ADC ⇒ X is 1×N ⇒\n   R̂ is a scalar (no subspace)",
        SUPPORT, fs=7.4)

    box(ax, 3, 11, 33, 6, "POWER: 12–24 V → buck + LDO tree", SUPPORT, fs=7.4)
    box(ax, 40, 11, 26, 6, "TCXO (single chain — clocking\nonly, no coherence problem)", SUPPORT, fs=7.4)
    legend(ax, 3, 25.5, [(ANALOG, "Analog GPS path (jammer suppressed pre-ADC)"),
                         (DIGITAL, "Digital control (blind — sees only output power)"),
                         (CTRL, "Control / feedback (weights, triggers)"),
                         (SUPPORT, "Support / notes")])
    ax.text(3, 92.2, "4× identical analog channels (CH1–CH4)", fontsize=8,
            color="#4e7a3a", style="italic")
    fig.savefig(OUTDIR + "arch1_diagram.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# =====================================================================
# ARCH 2 / ARCH 3 share the sensing-tap layout
# =====================================================================
def sensing_arch(fname, title, subtitle, fpga_label, trim=True):
    fig, ax = new_canvas()
    ax.text(82, 103.2, title, ha="center", fontsize=15.5, fontweight="bold")
    ax.text(82, 99.8, subtitle, ha="center", fontsize=9, color="#444444")

    rows = [86, 74, 62, 50]
    cols = [(3, 8, "PATCH\n{n}"), (14, 9, "PIN\nLIMITER"), (26, 9, "SAW BPF\nMurata"),
            (38, 9, "LNA\nQPL9547"), (50, 13, "COUPLER\n−10 dB"),
            (70, 14, "VECTOR MOD\nAD8341")]
    chains(ax, cols, rows, into_x=90)
    box(ax, 90, 46, 9, 44, "4-WAY\nWILKINSON\nΣ\n\n(microstrip\nRO4350)\n\nJAMMER\nDIES\nHERE",
        ANALOG, fs=8, lw=2, bold=True)

    # sense taps
    sense_xs = [64.6, 65.6, 66.6, 67.6]
    for xi, yc in zip(sense_xs, rows):
        line(ax, [(63.3, yc - 2.2), (xi, yc - 2.2), (xi, 41)], color="#39597a", lw=1.1)
    line(ax, [(64.6, 41), (78, 41)], color="#39597a", lw=1.6)
    arrow(ax, 77.0, 41, 78.0, 41, color="#39597a", lw=1.6)
    ax.text(63.8, 44.6, "4× sense taps\n(always unweighted)", fontsize=7,
            color="#39597a", ha="right", style="italic")

    # digital row
    box(ax, 78, 33, 26, 10, "4-CH COHERENT SENSING RX\nsingle-LO (NT1065-class)\nor 2×AD9361 + cal • 12-bit IQ",
        DIGITAL, fs=7.8)
    box(ax, 110, 26, 30, 16, fpga_label, DIGITAL, fs=7.8, lw=1.8)
    arrow(ax, 104.3, 38, 110, 38, color="#39597a", lw=1.8)

    box(ax, 78, 19, 26, 6.5, "AD5676 16-bit DAC ×8\n+ OPA354 buffers", CTRL, fs=7.8)
    line(ax, [(110, 29), (107, 29), (107, 22.2), (104.6, 22.2)], color="#b06a00", lw=1.6)
    arrow(ax, 105.4, 22.2, 104.3, 22.2, color="#b06a00", lw=1.6)
    line(ax, [(84, 25.8), (84, 45.9)], color="#b06a00", lw=2.0)
    arrow(ax, 84, 44.9, 84, 46.1, color="#b06a00", lw=2.0)
    ax.text(85.2, 30.5, "8× I/Q weight\nvoltages (×4 VMs)" + ("" if trim else "\nopen loop"),
            fontsize=7, color="#b06a00", style="italic")

    # cal tone
    box(ax, 44, 24, 16, 6.5, "CAL SYNTH\n(L1 tone, keyed)", CTRL, fs=7.8)
    line(ax, [(52, 30.8), (52, 46.0)], color="#b06a00", lw=1.4, ls="--")
    arrow(ax, 52, 45.0, 52, 46.2, color="#b06a00", lw=1.4)
    ax.text(51, 36.5, "cal tone → 4× coupler\nisolated ports", fontsize=7,
            color="#b06a00", ha="right", style="italic")

    # outputs
    line(ax, [(99.3, 72), (104, 72)], lw=1.8)
    box(ax, 104, 68, 16, 8, "POST-LNA\n+ BPF", ANALOG, fs=8)
    arrow(ax, 120.3, 72, 126, 72, lw=1.8)
    box(ax, 126, 66, 22, 12, "SMA — CLEAN L1 RF OUT\nactive-antenna emulation\n(any GNSS receiver /\nautopilot GPS port)",
        OUT, fs=7.8, lw=1.8)
    line(ax, [(102, 72), (102, 58), (104, 58)], lw=1.6)
    arrow(ax, 103.2, 58, 104.2, 58, lw=1.6)
    box(ax, 104, 54, 16, 8, "u-blox M10\nGNSS RX\n(embedded)", ANALOG, fs=7.8)
    line(ax, [(102, 58), (102, 48.2), (122, 48.2)], lw=1.6)
    arrow(ax, 121, 48.2, 122.2, 48.2, lw=1.6)
    box(ax, 122, 45, 17, 6.2, "PWR DET\nAD8314", CTRL, fs=7.8)

    if trim:
        line(ax, [(130, 44.8), (130, 42.4)], color="#b06a00", lw=1.8, ls="--")
        arrow(ax, 130, 43.2, 130, 42.2, color="#b06a00", lw=1.8)
        ax.text(131.2, 43.4, "residual jammer\npower → TRIM", fontsize=7,
                color="#b06a00", style="italic", fontweight="bold")
    else:
        line(ax, [(130, 44.8), (130, 42.4)], color="#777777", lw=1.4, ls="--")
        arrow(ax, 130, 43.2, 130, 42.2, color="#777777", lw=1.4)
        ax.text(131.2, 43.4, "monitor ONLY\n(does not steer)", fontsize=7,
                color="#777777", style="italic")

    box(ax, 146, 30, 16, 13, "UART →\nAUTOPILOT\nNMEA + C/N₀\n+ jammer\nbearings", OUT, fs=7.6)
    line(ax, [(120.3, 58), (152, 58), (152, 43.6)], lw=1.4)
    arrow(ax, 152, 44.6, 152, 43.4, lw=1.4)
    line(ax, [(140.3, 34), (146, 34)], color="#39597a", lw=1.6)
    arrow(ax, 145, 34, 146.2, 34, color="#39597a", lw=1.6)

    # support
    box(ax, 110, 17.5, 22, 6, "IMU ICM-42688\n(+ almanac → a(θs))", SUPPORT, fs=7.4)
    arrow(ax, 121, 23.8, 121, 25.7, color="#777777", lw=1.3)
    box(ax, 40, 11, 28, 6, "TCXO 10 MHz + 1:4 CLK BUFFER\n(shared, holdover — NO GPSDO)", SUPPORT, fs=7.4)
    line(ax, [(68.3, 14), (74, 14), (74, 35.5), (77.7, 35.5)], color="#777777", lw=1.2, ls="--")
    arrow(ax, 76.8, 35.5, 78.0, 35.5, color="#777777", lw=1.2)
    line(ax, [(68.3, 14), (108, 14), (108, 25.7)], color="#777777", lw=1.2, ls="--")
    arrow(ax, 108, 24.8, 108, 26.0, color="#777777", lw=1.2)
    box(ax, 3, 11, 33, 6, "POWER: 12–24 V drone bus → buck 5 V\n→ low-noise LDO tree (analog rails)",
        SUPPORT, fs=7.4)

    legend(ax, 3, 25.5, [(ANALOG, "Analog GPS path (jammer suppressed pre-ADC)"),
                         (DIGITAL, "Digital sensing brain (never carries the GPS signal)"),
                         (CTRL, "Control / feedback (weights, cal" + (", trim)" if trim else ")")),
                         (SUPPORT, "Support (clock, power, attitude)")])
    ax.text(3, 92.2, "4× identical analog channels (CH1–CH4)", fontsize=8,
            color="#4e7a3a", style="italic")
    fig.savefig(OUTDIR + fname, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


arch1()
sensing_arch(
    "arch2_diagram.png",
    "ARCHITECTURE 2  —  Sensing-Tap Hybrid (open-loop MUSIC + MVDR)",
    '"The array that SEES the jammer"  |  couplers tap all 4 elements → coherent sensing → '
    "one-shot MVDR weights  |  open loop: computed, written, done",
    "ZYNQ-7020 (FPGA + ARM)\n• R̂ = XXᴴ/N covariance\n• MUSIC → jammer DOAs"
    "\n• MVDR one-shot weight solve\n• cal FSM • OPEN LOOP (no trim)",
    trim=False)
sensing_arch(
    "arch3_diagram.png",
    "ARCHITECTURE 3  —  Closed-Loop Hybrid (MVDR aim + power-detector TRIM)  ·  COGNAV-P1",
    '"Sees, aims, then polishes"  |  Arch 2 sensing + Arch 1 feedback as a fine-trim loop  |  '
    "target ≥ 35 dB delivered null  |  contains Arch 1 & 2 as fallback modes",
    "ZYNQ-7020 (FPGA + ARM)\n• R̂ covariance → MUSIC DOA\n• MVDR weight solve (AIM)"
    "\n• TRIM loop (detector dither)\n• cal FSM • PI fallback (Arch 1)",
    trim=True)
print("saved 3 diagrams")
