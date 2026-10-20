#!/usr/bin/env bash
# Partyline dev/test launcher.
#
# Starts a Partyline server with its own Reticulum instance (no shared
# instance), reusing the interfaces from ~/.reticulum/config.
#
# Usage:
#   scripts/partyline-dev.sh setup
#   scripts/partyline-dev.sh server [extra partyline-server args]
#   scripts/partyline-dev.sh client <destination-hash> [extra client args]
#
# Environment:
#   PARTYLINE_DEV_DIR         default ~/.config/partyline-dev
#   PARTYLINE_SRC_RNS_CONFIG  default ~/.reticulum/config
#   PARTYLINE_STATEDIR        default $PARTYLINE_DEV_DIR/state
#   PARTYLINE_NAME            default Test
#   PARTYLINE_PROFILE         default opus-high (default profile of the server)
#   PARTYLINE_ANNOUNCE        default 60
#   PARTYLINE_ROOMS           default all: one room per codec profile.
#                             "all" creates the rooms listed in PROFILE_ROOMS,
#                             "none" keeps the server's own room config, or pass
#                             a comma-separated list of NAME[:PROFILE] specs,
#                             e.g. PARTYLINE_ROOMS="Lobby,Codec2:c2-1200".

set -euo pipefail

DEV_DIR="${PARTYLINE_DEV_DIR:-$HOME/.config/partyline-dev}"
SRC_CONFIG="${PARTYLINE_SRC_RNS_CONFIG:-$HOME/.reticulum/config}"
STATEDIR="${PARTYLINE_STATEDIR:-$DEV_DIR/state}"
NAME="${PARTYLINE_NAME:-Test}"
PROFILE="${PARTYLINE_PROFILE:-opus-high}"
ANNOUNCE="${PARTYLINE_ANNOUNCE:-60}"
ROOMS="${PARTYLINE_ROOMS:-all}"

# One room per profile in partyline.common.PROFILES (keep this list in sync).
PROFILE_ROOMS=(
    "Opus High:opus-high"
    "Opus Med:opus-med"
    "Opus Low:opus-low"
    "Codec2 3200:c2-3200"
    "Codec2 2400:c2-2400"
    "Codec2 1200:c2-1200"
    "Codec2 700:c2-700"
    "Music Low:music-low"
    "Music Med:music-med"
    "Music High:music-high"
)

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

build_room_args() {
    ROOM_ARGS=()
    local spec
    case "$ROOMS" in
        all)
            for spec in "${PROFILE_ROOMS[@]}"; do
                ROOM_ARGS+=(--room "$spec")
            done
            ;;
        none|default)
            ;;
        *)
            local IFS=','
            for spec in $ROOMS; do
                spec="${spec#"${spec%%[![:space:]]*}"}"
                spec="${spec%"${spec##*[![:space:]]}"}"
                if [ -n "$spec" ]; then
                    ROOM_ARGS+=(--room "$spec")
                fi
            done
            ;;
    esac
}

die() {
    echo "error: $*" >&2
    exit 1
}

prepare_rns_config() {
    local dst="$1"
    [ -f "$SRC_CONFIG" ] || die "no encuentro $SRC_CONFIG"
    mkdir -p "$dst"
    if [ ! -f "$dst/config" ]; then
        python3 - "$SRC_CONFIG" "$dst/config" <<'PY'
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
lines = open(src, encoding="utf-8").read().splitlines()
out = []
section = None
seen = {"enable_transport": False, "share_instance": False, "loglevel": False}


def flush_reticulum():
    if section == "[reticulum]":
        for key in ("enable_transport", "share_instance"):
            if not seen[key]:
                out.append(f"  {key} = No")
                seen[key] = True


for line in lines:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        flush_reticulum()
        section = stripped
        out.append(line)
        continue
    if section == "[reticulum]" and re.match(r"^\s*(enable_transport|share_instance)\s*=", stripped):
        key = stripped.split("=", 1)[0].strip()
        out.append(f"  {key} = No")
        seen[key] = True
        continue
    if section == "[logging]" and re.match(r"^\s*loglevel\s*=", stripped):
        out.append("  loglevel = 4")
        seen["loglevel"] = True
        continue
    out.append(line)

flush_reticulum()
if not any(line.strip() == "[interfaces]" for line in out):
    out.append("[interfaces]")

open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
    fi
    chmod 600 "$dst/config"
}

server_cmd() {
    if command -v partyline-server >/dev/null 2>&1; then
        partyline-server "$@"
    else
        python3 -m partyline.server "$@"
    fi
}

client_cmd() {
    if command -v partyline-client >/dev/null 2>&1; then
        partyline-client "$@"
    else
        python3 -m partyline.client "$@"
    fi
}

cmd="${1:-}"
[ -n "$cmd" ] || usage 1
shift || true

case "$cmd" in
    setup)
        prepare_rns_config "$DEV_DIR/server-rns"
        prepare_rns_config "$DEV_DIR/client-rns"
        mkdir -p "$STATEDIR"
        echo "server RNS config: $DEV_DIR/server-rns/config"
        echo "client RNS config: $DEV_DIR/client-rns/config"
        echo "server state:      $STATEDIR"
        ;;
    server)
        prepare_rns_config "$DEV_DIR/server-rns"
        mkdir -p "$STATEDIR"
        build_room_args
        echo "starting Partyline server with RNS config $DEV_DIR/server-rns" >&2
        echo "rooms/state: $STATEDIR" >&2
        echo "rooms: ${ROOMS}" >&2
        server_cmd \
            --configdir "$DEV_DIR/server-rns" \
            --statedir "$STATEDIR" \
            --name "$NAME" \
            --profile "$PROFILE" \
            --announce-interval "$ANNOUNCE" \
            ${ROOM_ARGS[@]+"${ROOM_ARGS[@]}"} \
            "$@"
        ;;
    client)
        hash="${1:-}"
        [ -n "$hash" ] || die "uso: $0 client <destination-hash> [args]"
        shift
        prepare_rns_config "$DEV_DIR/client-rns"
        mkdir -p "$DEV_DIR"
        client_cmd "$hash" \
            --configdir "$DEV_DIR/client-rns" \
            --identity "$DEV_DIR/client_identity" \
            --name "${PARTYLINE_CLIENT_NAME:-Probe}" \
            --text-only \
            --duration "${PARTYLINE_CLIENT_DURATION:-60}" \
            "$@"
        ;;
    -h|--help|help)
        usage 0
        ;;
    *)
        usage 1
        ;;
esac
