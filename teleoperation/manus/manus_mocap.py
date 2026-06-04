#!/usr/bin/env python3
"""Manus 单手桥接：Manus(ZMQ) → canonical (21,3) → UDP 5013(右)/5015(左)。

这是 dexjoco `teleoperation/rokoko/rokoko_mocap.py` 的 **drop-in 替代**：
输出格式（canonical (21,3) float32 到 5013/5015）完全相同，下游 GeoRT 与仿真无需改动。

前置：先在 sharpa-manus-sdk 里启动 Manus C++ 客户端（`client/SharpaManusClient.out`），
它会在 tcp://127.0.0.1:2044 上发布 MocapKeypoints。
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
        description="Forward one Manus hand as canonical 21 keypoints to GeoRT over UDP "
                    "(drop-in replacement for rokoko_mocap.py)."
    )
    parser.add_argument("--hand", choices=["left", "right"], default="right",
                        help="Which hand to forward")
    parser.add_argument("--manus-address", default="tcp://localhost:2044",
                        help="Manus C++ client ZMQ PUB address")
    parser.add_argument("--target-ip", default="127.0.0.1",
                        help="GeoRT bind_ip (where to send the keypoints)")
    parser.add_argument("--target-port", type=int, default=None,
                        help="Destination UDP port; defaults to 5013 (right) / 5015 (left)")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Position scale to match Rokoko metric scale used by GeoRT")
    parser.add_argument("--frequency", type=float, default=90.0,
                        help="Maximum UDP send rate in Hz")
    parser.add_argument("--quiet", action="store_true",
                        help="Disable live keypoint mean printing")
    return parser


def main() -> int:
    args = build_argparser().parse_args()
    is_left = args.hand == "left"
    target_port = args.target_port
    if target_port is None:
        target_port = DEFAULT_LEFT_TARGET_PORT if is_left else DEFAULT_RIGHT_TARGET_PORT

    src = ManusKeypointSource(address=args.manus_address, scale=args.scale)
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / args.frequency if args.frequency > 0 else 0.0
    side = "left" if is_left else "right"

    print(
        f"Forwarding {side} Manus hand (canonical 21x3 float32) to "
        f"{args.target_ip}:{target_port}. Press Ctrl+C to stop."
    )

    try:
        while True:
            tick_start = time.time()
            can = src.get(is_left)  # (21,3) float32 or None
            if can is not None:
                send_sock.sendto(np.asarray(can, dtype=np.float32).tobytes(),
                                 (args.target_ip, target_port))
                if not args.quiet:
                    mean = can.mean(axis=0)
                    print(f"\r{side} hand mean: {mean[0]: .6f} {mean[1]: .6f} {mean[2]: .6f}",
                          end="", flush=True)
            if interval > 0:
                sleep_s = interval - (time.time() - tick_start)
                if sleep_s > 0:
                    time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("\nStopped forwarding Manus hand.")
        return 0
    finally:
        src.close()
        send_sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
