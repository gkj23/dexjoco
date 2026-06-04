"""teleoperation.manus —— Manus 手套接入（替代 teleoperation/rokoko）。

把 Manus 手套（经 sharpa-manus-sdk 的 C++ 客户端 ZMQ 发布的 MocapKeypoints）转换成
与 Rokoko 完全一致的 canonical 21 关键点信号，发往 GeoRT（5013/5015），下游不变。

公开接口：
    ManusKeypointSource     —— 订阅 Manus ZMQ，产出 canonical (21,3)（已丢四元数）
    manus25_to_keypoints21  —— 25 节点 → 21 关键点（丢四元数）
    hand_to_canonical       —— 与 rokoko/common.py 一致的规范化
    MANUS25_TO_OPEN21 / OPEN21_NAMES / MANUS25_NAMES —— 映射与命名
"""

from .manus_common import (  # noqa: F401
    MANUS25_NAMES,
    MANUS25_TO_OPEN21,
    OPEN21_NAMES,
    ManusKeypointSource,
    hand_to_canonical,
    manus25_to_keypoints21,
)
