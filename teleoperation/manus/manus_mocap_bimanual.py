#!/usr/bin/env python3
"""Manus 双手桥接：Manus(ZMQ) → 左右各 canonical (21,3) → UDP 右5013 + 左5015。

dexjoco `teleoperation/rokoko/rokoko_mocap_bimanual.py` 的 **drop-in 替代**。
下游 GeoRT（右 5013→5014、左 5015→5016）与仿真无需改动。
"""

from __future__ import annotations

import argparse
import socket
import time

import numpy as np

try:
    from .manus_common import ManusKeypointSource
except ImportError:
    from manus_common import ManusKeypointSource


DEFAULT_RIGHT_TARGET_PORT = 5013
DEFAULT_LEFT_TARGET_PORT = 5015


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Forward both Manus hands as canonical 21 keypoints to GeoRT over UDP."
    )
    parser.add_argument("--manus-address", default="tcp://localhost:2044",
                        help="Manus C++ client ZMQ PUB address")
    parser.add_argument("--target-ip", default="127.0.0.1",
                        help="GeoRT bind_ip (where to send the keypoints)")
    parser.add_argument("--right-port", type=int, default=DEFAULT_RIGHT_TARGET_PORT)
    parser.add_argument("--left-port", type=int, default=DEFAULT_LEFT_TARGET_PORT)
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Position scale to match Rokoko metric scale used by GeoRT")
    parser.add_argument("--frequency", type=float, default=90.0)
    parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> int:
    args = build_argparser().parse_args()
    src = ManusKeypointSource(address=args.manus_address, scale=args.scale)
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / args.frequency if args.frequency > 0 else 0.0

    print(
        f"Forwarding Manus left hand to {args.target_ip}:{args.left_port} and right hand to "
        f"{args.target_ip}:{args.right_port}. Press Ctrl+C to stop."
    )

    try:
        while True:
            tick_start = time.time()
            left_can, right_can = src.recv()  # 各 (21,3) float32 或 None

            if right_can is not None:
                send_sock.sendto(np.asarray(right_can, dtype=np.float32).tobytes(),
                                 (args.target_ip, args.right_port))
            if left_can is not None:
                send_sock.sendto(np.asarray(left_can, dtype=np.float32).tobytes(),
                                 (args.target_ip, args.left_port))

            if not args.quiet:
                left_text = "missing" if left_can is None else " ".join(
                    f"{v: .4f}" for v in left_can.mean(axis=0))
                right_text = "missing" if right_can is None else " ".join(
                    f"{v: .4f}" for v in right_can.mean(axis=0))
                print(f"\rleft mean: {left_text} | right mean: {right_text}", end="", flush=True)

            if interval > 0:
                sleep_s = interval - (time.time() - tick_start)
                if sleep_s > 0:
                    time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("\nStopped forwarding bimanual Manus data.")
        return 0
    finally:
        src.close()
        send_sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
