"""Manus 手套 → 21 个 canonical 手部关键点（teleoperation/rokoko 的等价替代）。

作用：复用 sharpa-manus-sdk 的 Manus 采集（C++ 客户端 `SharpaManusClient.out` 通过 ZMQ PUB 在
`tcp://127.0.0.1:2044` 上发布 `MocapKeypoints`，每只手 25 个 Pose = 位置 + 四元数）。
本模块：
  1. 订阅该 ZMQ 流；
  2. **丢弃四元数**，只取位置；
  3. 把 Manus 的 25 节点映射成 Rokoko/OpenPose 的 21 关键点（去掉 4 个 *_virtual_base）；
  4. 做与 dexjoco `rokoko/common.py` **完全一致** 的 canonical 规范化；
  5. 产出 `(21,3) float32`，与 rokoko_mocap.py 的输出格式一模一样，供下游 GeoRT 直接消费。

依赖：pyzmq、protobuf，以及 sharpa-manus-sdk 提供的 `sharpa_hand_pb2`。
环境变量 `SHARPA_MANUS_SDK` 指向 sharpa-manus-sdk 根目录（默认 /mnt/gaokj/dexjoco/sharpa-manus-sdk）。
"""

from __future__ import annotations

import os
import sys

import numpy as np

# ---- 定位 sharpa-manus-sdk 并导入其 protobuf 定义（复用，不重写 proto）----
_SDK_ROOT = os.environ.get("SHARPA_MANUS_SDK", "/mnt/gaokj/dexjoco/sharpa-manus-sdk")
_PROTO_DIR = os.path.join(_SDK_ROOT, "retargeting", "include", "proto_hand")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)
try:
    import sharpa_hand_pb2  # 由 sharpa-manus-sdk 提供
except Exception as exc:  # pragma: no cover - 运行期依赖
    raise ImportError(
        f"无法导入 sharpa_hand_pb2（在 {_PROTO_DIR}）。请设置 SHARPA_MANUS_SDK 指向 "
        f"sharpa-manus-sdk 根目录，并确保已安装 protobuf。"
    ) from exc

import zmq

# ============================================================
# 关键点定义与映射
# ============================================================

# Manus C++ 客户端发布的 25 节点顺序（见 SDK: openpose21_retarget_test.py 的 MANUS25_NAMES）
MANUS25_NAMES = [
    "wrist",
    "thumb1", "thumb2", "thumb3", "thumb_tip",
    "index_virtual_base", "index1", "index2", "index3", "index_tip",
    "middle_virtual_base", "middle1", "middle2", "middle3", "middle_tip",
    "ring_virtual_base", "ring1", "ring2", "ring3", "ring_tip",
    "pinky_virtual_base", "pinky1", "pinky2", "pinky3", "pinky_tip",
]

# 目标 21 关键点：wrist + 5 指 ×（proximal/medial/distal/tip）。
# 顺序与 dexjoco rokoko/common.py 的 *_JOINT_NAMES 完全一致（GeoRT 训练所用约定）：
#   0 wrist | 1-4 thumb | 5-8 index | 9-12 middle | 13-16 ring | 17-20 little/pinky
OPEN21_NAMES = [
    "wrist",
    "thumb1", "thumb2", "thumb3", "thumb_tip",
    "index1", "index2", "index3", "index_tip",
    "middle1", "middle2", "middle3", "middle_tip",
    "ring1", "ring2", "ring3", "ring_tip",
    "pinky1", "pinky2", "pinky3", "pinky_tip",
]

# Manus25 → 21 的索引：丢弃 4 个 *_virtual_base（Manus idx 5/10/15/20）
MANUS25_TO_OPEN21 = [0, 1, 2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18, 19, 21, 22, 23, 24]
assert len(MANUS25_TO_OPEN21) == 21


def manus25_to_keypoints21(poses) -> np.ndarray | None:
    """从 repeated Pose（25 个）抽取 **位置**、丢弃四个手指virtual base、映射成 (21,3) float32。

    poses 缺失（手未连接，长度 < 25）时返回 None。
    """
    if poses is None or len(poses) < 25:
        return None
    pts = np.empty((21, 3), dtype=np.float32)
    for out_i, src_i in enumerate(MANUS25_TO_OPEN21):
        p = poses[src_i].position  # 只取 position，丢弃 poses[*].orientation（四元数）
        pts[out_i, 0] = p.x
        pts[out_i, 1] = p.y
        pts[out_i, 2] = p.z
    return pts


def hand_to_canonical(hand_point: np.ndarray, is_left: bool) -> np.ndarray:
    """与 dexjoco `teleoperation/rokoko/common.py::hand_to_canonical` 完全一致的规范化。

    GeoRT 是在这个 canonical 手系上训练的，故必须保持一致。
    用到的索引（OPEN21 顺序）：0=wrist, 5=index_proximal, 9=middle_proximal, 13=ring_proximal。
    """
    p = np.asarray(hand_point, dtype=np.float32)
    eps = 1e-6

    z_axis = p[9] - p[0]
    if np.linalg.norm(z_axis) < eps:
        return p - p[0]
    z_axis = z_axis / np.linalg.norm(z_axis)

    if is_left:
        y_axis_aux = p[13] - p[5]
    else:
        y_axis_aux = p[5] - p[13]
    if np.linalg.norm(y_axis_aux) < eps:
        return p - p[0]
    y_axis_aux = y_axis_aux / np.linalg.norm(y_axis_aux)

    x_axis = np.cross(y_axis_aux, z_axis)
    if np.linalg.norm(x_axis) < eps:
        return p - p[0]
    x_axis = x_axis / np.linalg.norm(x_axis)

    y_axis = np.cross(z_axis, x_axis)
    y_axis = y_axis / np.linalg.norm(y_axis)

    transform = np.eye(4, dtype=np.float32)
    transform[:3, :3] = np.stack([x_axis, y_axis, z_axis], axis=1)
    transform[:3, 3] = p[0]

    homo = np.concatenate([p, np.ones((21, 1), dtype=np.float32)], axis=1)
    return (homo @ np.linalg.inv(transform).T)[:, :3]


# ============================================================
# Manus ZMQ 订阅源
# ============================================================

class ManusKeypointSource:
    """订阅 Manus C++ 客户端的 ZMQ `MocapKeypoints`，产出 canonical (21,3)（已丢四元数）。

    用法：
        src = ManusKeypointSource(address="tcp://localhost:2044", scale=1.0)
        left_can, right_can = src.recv()       # 各为 (21,3) float32 或 None
        right_can = src.get(is_left=False)      # 单手便捷接口
    """

    def __init__(self, address: str = "tcp://localhost:2044", scale: float = 1.0):
        self.address = address
        self.scale = float(scale)
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.setsockopt(zmq.RCVHWM, 1)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(address)
        self.sock.setsockopt_string(zmq.SUBSCRIBE, "")
        self._last = {"left": None, "right": None}
        print(f"[ManusKeypointSource] subscribed to {address} (drop quaternion, 25->21, canonical)")

    def _recv_latest_msg(self):
        """非阻塞排空到最新一帧；若当前无数据则阻塞等一帧。"""
        payload = None
        while True:
            try:
                payload = self.sock.recv(flags=zmq.NOBLOCK)
            except zmq.Again:
                break
        if payload is None:
            try:
                payload = self.sock.recv()
            except Exception:
                return None
        msg = sharpa_hand_pb2.MocapKeypoints()
        msg.ParseFromString(payload)
        return msg

    def recv(self):
        """收一帧，返回 (left_canonical, right_canonical)，各为 (21,3) float32 或 None（缺手保留上一帧）。"""
        msg = self._recv_latest_msg()
        if msg is not None:
            left = manus25_to_keypoints21(msg.left_mocap_pose)
            right = manus25_to_keypoints21(msg.right_mocap_pose)
            if left is not None:
                if self.scale != 1.0:
                    left = left * self.scale
                self._last["left"] = hand_to_canonical(left, is_left=True)
            if right is not None:
                if self.scale != 1.0:
                    right = right * self.scale
                self._last["right"] = hand_to_canonical(right, is_left=False)
        return self._last["left"], self._last["right"]

    def get(self, is_left: bool):
        """单手便捷接口：返回该手 canonical (21,3) 或 None。"""
        left, right = self.recv()
        return left if is_left else right

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass
