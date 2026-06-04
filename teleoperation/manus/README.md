# teleoperation/manus —— Manus 手套接入（替代 rokoko）

把 **Manus 手套** 接入 DexJoCo 遥操，**完全替代 `teleoperation/rokoko/` 的角色**：
采集手套 → 产出 **canonical 21 关键点（丢弃四元数）** → 发往 **GeoRT**。下游 GeoRT 与仿真 wrapper 不变。

## 数据链路

```
Manus 手套 → Manus Core → sharpa-manus-sdk: SharpaManusClient.out
    (ZMQ PUB tcp://127.0.0.1:2044, MocapKeypoints = 每手 25 个 Pose[pos+quat])
        │
        ▼  本包：订阅 ZMQ → 丢四元数 → 25→21 映射 → canonical 规范化
manus_mocap.py / manus_mocap_bimanual.py
        │  UDP, canonical (21,3) float32（与 rokoko_mocap.py 输出完全相同）
        ▼  右→5013 / 左→5015
GeoRT（不变）── 5014/5016 ──► sim_teleop.py（不变）
```

## 与 rokoko 的对应关系

| rokoko 文件 | 本包等价文件 | 区别 |
|---|---|---|
| `common.py`（UDP+JSON 收 Rokoko Studio） | `manus_common.py`（ZMQ 收 Manus 客户端） | 数据源换成 Manus；**丢四元数**；25→21 映射 |
| `rokoko_mocap.py`（单手→5013/5015） | `manus_mocap.py` | 输出格式完全相同 |
| `rokoko_mocap_bimanual.py`（双手） | `manus_mocap_bimanual.py` | 同上 |

输出契约与 rokoko 完全一致：`(21,3) float32` 的 canonical 关键点，右手→5013、左手→5015。
21 关键点顺序 = `wrist + 拇/食/中/无名/小指 × (proximal/medial/distal/tip)`，与 GeoRT 训练约定一致。

## 依赖与环境

```bash
# dexjoco 环境里需要：
pip install pyzmq protobuf
# 指向 sharpa-manus-sdk（提供 sharpa_hand_pb2 与 proto）
export SHARPA_MANUS_SDK=/mnt/gaokj/dexjoco/sharpa-manus-sdk
```

## 运行（替代 Rokoko Studio + rokoko_mocap）

```bash
# 1) 先起 Manus 采集客户端（在 sharpa-manus-sdk 里，按其启动流程标定/联网后）
cd $SHARPA_MANUS_SDK/client && ./SharpaManusClient.out

# 2) 起 GeoRT（不变，仍是 Allegro 模型）
python $SHARPA_MANUS_SDK/../dexjoco/teleoperation/GeoRT/geort/mocap/rokoko_retarget_send_right.py \
    -ckpt_tag dexjoco_right_default --bind_ip 127.0.0.1 --bind_port 5013 \
    --target_ip 127.0.0.1 --target_port 5014

# 3) 起本包的桥接（替代 rokoko_mocap.py）
python teleoperation/manus/manus_mocap.py --hand right --target-ip 127.0.0.1
#   双手：python teleoperation/manus/manus_mocap_bimanual.py --target-ip 127.0.0.1
```

## 注意

- `--scale`：Manus 位置单位/尺度若与 Rokoko 不一致，用它对齐（GeoRT 对尺度敏感）。
- GeoRT 是在 **Rokoko** 关键点上训练的；用 Manus 关键点能跑通，但**重定向质量可能下降**，
  建议用 Manus 采集一批数据**重训 GeoRT**（GeoRT README 流程）以获得最佳效果。
- 手腕 6D 位姿（5012）这一路与本包无关，保持原样（Manus 手套不提供手腕世界位姿）。
