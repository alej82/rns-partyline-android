#!/usr/bin/env python3
"""Headless Partyline engine harness.

Connects to a Partyline server and prints the engine event stream and
snapshots. Intended for desktop development against
scripts/partyline-dev.sh, and for on-device log checks.
"""

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hash", help="server destination hash (32 hex characters)")
    parser.add_argument("--room")
    parser.add_argument("--password")
    parser.add_argument("--server-password")
    parser.add_argument("--name", default="android-headless")
    parser.add_argument("--configdir", default=os.path.expanduser("~/.reticulum"), help="Reticulum config directory")
    parser.add_argument(
        "--statedir", default=os.path.expanduser("~/.config/partyline-dev/headless-state"), help="identity and state"
    )
    parser.add_argument("--duration", type=float, default=45.0, help="seconds to stay connected (0 = forever)")
    parser.add_argument("--json", action="store_true", help="print events and snapshots as JSON lines")
    parser.add_argument("--tone", type=float, default=None, help="send a continuous tone at this frequency (Hz)")
    parser.add_argument("--null-audio", action="store_true", help="analyze receive audio instead of using a speaker")
    parser.add_argument("--listen", action="store_true", help="receive only, never open the microphone")
    parser.add_argument("--mode", choices=("ptt", "vox", "open"), default="ptt", help="transmit mode")
    return parser.parse_args()


def main():
    args = parse_args()
    os.environ["PARTYLINE_RNS_DIR"] = args.configdir
    os.environ["PARTYLINE_CONFIG_DIR"] = args.statedir
    os.makedirs(args.statedir, exist_ok=True)

    from partyline_android.engine import Engine
    from partyline_android.reticulum import SharedInstanceUnavailable

    audio_requested = args.tone is not None or args.null_audio or args.listen
    client_options = {"mode": args.mode, "text_only": not audio_requested}
    if audio_requested:
        if args.tone is not None:
            client_options["tone"] = args.tone
        if args.null_audio:
            client_options["null_audio"] = True
        if args.listen:
            client_options["listen"] = True

    engine = Engine(
        rns_dir=args.configdir,
        config_dir=args.statedir,
        identity_path=os.path.join(args.statedir, "identity"),
        display_name=args.name,
        client_options=client_options,
    )
    try:
        engine.start()
    except SharedInstanceUnavailable as error:
        print(f"transport error: {error}", file=sys.stderr)
        return 2

    snapshot = engine.snapshot()
    print(f"identity: {snapshot['identity']}")
    print(f"shared instance: {snapshot['transport']['shared_instance']}")
    try:
        engine.connect(args.hash, room=args.room, password=args.password, server_password=args.server_password)
    except ValueError as error:
        print(f"invalid hash: {error}", file=sys.stderr)
        engine.stop()
        return 2

    started = time.time()
    connected_at = None
    failed = False
    last_printed = 0.0

    try:
        while True:
            for event in engine.drain_events():
                if args.json:
                    print(json.dumps(event, ensure_ascii=False, sort_keys=True), flush=True)
                else:
                    print(f"event {event['seq']:>4} {event['type']}: {_detail(event)}", flush=True)
                if event["type"] == "connected":
                    connected_at = time.time()
                if event["type"] in ("retry_stopped",):
                    failed = True

            if time.time() - last_printed >= 1.0:
                last_printed = time.time()
                snapshot = engine.snapshot()
                if args.json:
                    print(json.dumps({"snapshot": snapshot}, ensure_ascii=False, sort_keys=True), flush=True)
                else:
                    connection = snapshot["connection"]
                    audio = snapshot["audio"]
                    print(
                        f"state={connection['state']} server={snapshot['server']['name']} "
                        f"room={_own_room(snapshot)} users={snapshot['counts']['users']} "
                        f"retry_in={connection['retry_in']}",
                        flush=True,
                    )
                    print(
                        f"  audio rx={audio['rx_ready']} tx={audio['tx_ready']} "
                        f"transmitting={audio['transmit']} level={audio['level_db']} "
                        f"profile={audio['profile']} frame_ms={audio['frame_ms']} "
                        f"rx_pkts={audio['rx_packets']} tx_pkts={audio['tx_packets']} "
                        f"heard={audio['heard']} error={audio['error']}",
                        flush=True,
                    )

            if failed:
                return 2
            if args.duration and connected_at and time.time() - connected_at >= args.duration:
                return 0
            if args.duration and not connected_at and time.time() - started > args.duration + 30:
                return 2
            time.sleep(0.1)
    except KeyboardInterrupt:
        return 0
    finally:
        engine.stop()


def _own_room(snapshot):
    me = snapshot.get("me")
    return me["room"] if me else None


def _detail(event):
    keys = [key for key in event if key not in ("seq", "ts", "type")]
    return ", ".join(f"{key}={event[key]!r}" for key in keys)


if __name__ == "__main__":
    sys.exit(main())
