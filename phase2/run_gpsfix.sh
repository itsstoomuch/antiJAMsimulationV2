#!/bin/bash
# Push gpsfix.py to the SBC that has the USRP and run it there, with the output
# here. Modelled on run_gpsacq.sh, minus the build step -- gpsfix.py is pure
# Python and numpy, so there is nothing to compile.
#
#   ./run_gpsfix.sh --probe
#   ./run_gpsfix.sh --run --seconds 120
#   ./run_gpsfix.sh --gain-sweep 20,30,40,50,60
#   ./run_gpsfix.sh --selftest              # verifies the DSP, needs no radio
#
# Set GPSFIX_HOST / GPSFIX_USER if the defaults do not match. (Not USER --
# that is the login name of whoever is running this, and clobbering it is a
# good way to confuse everything else in the shell.)
#
#   GPSFIX_HOST=10.79.122.240 GPSFIX_USER=padtpl ./run_gpsfix.sh --probe
#
# NOTE ON REACHABILITY: this needs the SBC and this machine on the same network
# with client-to-client traffic allowed. Many office and campus Wi-Fi networks
# enable AP client isolation, which blocks peer traffic even when both machines
# sit in the same /24 -- the symptom is that ping and ssh both time out while
# an ARP entry for the target stays "(incomplete)". Check with `arp -n <ip>`.
# There is no client-side fix: use a wired link, a phone hotspot, or run
# gpsfix.py on the SBC's own console.

set -u

SBC_USER="${GPSFIX_USER:-padtpl}"
HOST="${GPSFIX_HOST:-}"
REMOTE_DIR="${REMOTE_DIR:-~/CRPA/phase2}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

# Probe with ssh rather than ping: ICMP is not what this needs (plenty of hosts
# drop it while accepting ssh), and the ping flag for "give up after N seconds"
# is -t on macOS but -W on Linux, where -t sets the TTL instead. ssh
# -o ConnectTimeout is spelled the same everywhere.
reachable() {
    ssh -o BatchMode=yes -o ConnectTimeout=5 \
        -o StrictHostKeyChecking=accept-new \
        "${SBC_USER}@$1" true >/dev/null 2>&1
}

find_host() {
    if [ -n "$HOST" ]; then
        echo "$HOST"
        return 0
    fi
    for candidate in 10.79.122.240 padtpl-shashank.local padtpl-shashank \
                     skysense-desktop.local; do
        if reachable "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

TARGET="$(find_host)" || {
    cat >&2 <<'EOF'
Cannot open an ssh session to the SBC on any known address.

That is either "the host is unreachable" or "the key is not authorized there".
If the board is up and you know its address, pass it explicitly:

    GPSFIX_HOST=10.79.122.240 GPSFIX_USER=padtpl ./run_gpsfix.sh --probe

If that still times out, check whether the network is isolating clients:

    arp -n 10.79.122.240        # "(incomplete)" means the AP is blocking peers

On AP client isolation nothing on this side helps. Either put both machines on
a wired link or a phone hotspot, or copy gpsfix.py to the board on a USB stick
and run it from the board's own console -- it needs only python3 and numpy.

Find the board's address on its own screen with:  hostname -I
EOF
    exit 1
}

echo "SBC: ${SBC_USER}@${TARGET}"
ssh -o BatchMode=yes -o ConnectTimeout=10 "${SBC_USER}@${TARGET}" \
    "mkdir -p ${REMOTE_DIR}" \
    || { echo "ssh failed -- is the key authorized on ${TARGET}?" >&2; exit 1; }

echo "syncing..."
scp -q -o BatchMode=yes \
    "$SRC_DIR/gpsfix.py" "$SRC_DIR/usrp_gps_l1_ch1.conf" \
    "${SBC_USER}@${TARGET}:${REMOTE_DIR}/" \
    || { echo "copy failed" >&2; exit 1; }

echo "checking the remote environment..."
ssh -o BatchMode=yes "${SBC_USER}@${TARGET}" "
    cd ${REMOTE_DIR} || exit 1
    chmod +x gpsfix.py
    python3 -c 'import numpy' 2>/dev/null \
        || { echo 'MISSING: numpy  ->  sudo apt install python3-numpy'; }
    python3 -c 'import uhd'   2>/dev/null \
        || { echo 'MISSING: python3-uhd  ->  sudo apt install uhd-host python3-uhd'; }
    command -v gnss-sdr >/dev/null \
        || { echo 'MISSING: gnss-sdr  ->  sudo apt install gnss-sdr  (only --fix/--live need it)'; }
    true
"

echo
# -t forces a pty so progress lines flush as they happen rather than arriving
# as one lump when the run ends.
exec ssh -t -o BatchMode=yes "${SBC_USER}@${TARGET}" \
    "cd ${REMOTE_DIR} && ./gpsfix.py $*"
