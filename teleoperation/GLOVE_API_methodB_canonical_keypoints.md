# 数据手套替换 API（方案 B：canonical 关键点 → GeoRT）

> **适用**：用你自己的数据手套替换 Rokoko，但**继续复用 DexJoCo 的 GeoRT 重定向和仿真**。
> **你要做的唯一事情**：把你手套的手部姿态整理成 **21 个关键点的 canonical 坐标**，按固定字节格式用 UDP 发给 GeoRT。
> 之后 GeoRT → `5014/5016` → 仿真这一段**完全不用动**。
>
> 本文是自包含的：只看这一篇就能写出替换桥接。

---

## 0. 你在链路里替换的是哪一段

```
[你的数据手套] ──你写的桥接──►  UDP 5013(右)/5015(左)   ──►  GeoRT  ──► 5014/5016 ──► 仿真
                 ^^^^^^^^^^^^      (canonical 21×3 float32)      (不动)        (不动)      (不动)
                 本文档要你实现
```

即：你只替换"产出 canonical 关键点并发出"这一段（原来是 `rokoko/common.py` + `rokoko_mocap.py`）。

---

## 1. 输出接口契约（必须严格满足）

GeoRT 的接收端是 `rokoko_retarget_send_*.py` 里的 `UDPRokokoReceiver`，它**只认**下面这种包：

| 项 | 规格 |
|---|---|
| 传输 | UDP datagram |
| 目标端口 | **右手 / 单手 → `5013`**；**左手 → `5015`** |
| 目标 IP | GeoRT 进程的 `--bind_ip`（默认 `10.6.60.137`，本机调试用 `127.0.0.1`） |
| 数据 | `numpy.ndarray`，shape **`(21, 3)`**，dtype **`float32`**，C 顺序 `.tobytes()` |
| 字节数 | `21 × 3 × 4 = 252` 字节，布局 `[p0.x,p0.y,p0.z, p1.x,…, p20.z]` |
| 坐标系 | **canonical 手系**（见 §3，不是世界坐标！） |
| 频率 | ≤ 90 Hz（建议 60–90 Hz；GeoRT 非阻塞读最新帧） |

GeoRT 解析逻辑（你必须匹配）：
```python
arr = np.frombuffer(data, dtype=np.float32)   # 你的字节流
if arr.size < 63: raise                       # 至少 63 个 float32
keypoints = arr[:63].reshape(21, 3)           # 取前 21×3
qpos = model.forward(keypoints)               # → 机器手关节角，发去 5014/5016
```
> 备选：GeoRT 也接受 **JSON** 形式 `json.dumps(arr.tolist())`（shape 必须 `(21,3)`）。二进制 float32 更高效，**推荐二进制**。

---

## 2. 21 个关键点：语义、顺序、索引（最关键）

你的 `(21,3)` **每一行是哪根手指的哪一节，顺序写死，必须照填**（来自 `common.py` 的 `*_JOINT_NAMES`）：

| idx | 关节（右手名） | idx | 关节 | idx | 关节 |
|---|---|---|---|---|---|
| 0 | rightHand（腕根/掌心根） | 7 | rightIndexDistal | 14 | rightRingMedial |
| 1 | rightThumbProximal | 8 | **rightIndexTip** | 15 | rightRingDistal |
| 2 | rightThumbMedial | 9 | rightMiddleProximal | 16 | **rightRingTip** |
| 3 | rightThumbDistal | 10 | rightMiddleMedial | 17 | rightLittleProximal |
| 4 | **rightThumbTip** | 11 | rightMiddleDistal | 18 | rightLittleMedial |
| 5 | rightIndexProximal | 12 | **rightMiddleTip** | 19 | rightLittleDistal |
| 6 | rightIndexMedial | 13 | rightRingProximal | 20 | rightLittleTip |

- 顺序：`Hand(0)` → 拇指 4 节(1–4) → 食指 4 节(5–8) → 中指(9–12) → 无名指(13–16) → 小指(17–20)。
- **GeoRT 实际只用到的点**（Allegro 4 指，见其 `config.json` 的 `human_hand_id`）：
  - 拇指尖 = idx **4**，食指尖 = idx **8**，中指尖 = idx **12**，无名指尖 = idx **16**；
  - 以及 §3 规范化要用到的 idx **0/5/9/13**。
  - **小指(17–20) 当前不被 Allegro retarget 使用**——但你仍需把 21 行填满（GeoRT 按 `arr[:63]` 取整块）。没有小指数据就用占位（如复制无名指或填 0），不影响 Allegro。
- **单位**：米。规范化会消掉绝对平移与朝向，所以**只要各点单位一致、相对几何正确**即可。
- **缺点不可**：必须凑满 21 行；少于 63 个 float32 GeoRT 会直接报错丢帧。

---

## 3. canonical 规范化（必须与此一致，否则要重训 GeoRT）

GeoRT 是在 **canonical 手系**上训练的。你产出的世界坐标点必须先经过下面这个变换再发出（公式来自 `common.py::hand_to_canonical`）：

```
原点   o = p[0]                                  # rightHand
z 轴   = normalize(p[9] - p[0])                  # 指向 MiddleProximal
y 辅助 = (右手) p[5] - p[13]                       # IndexProximal - RingProximal
        (左手) p[13] - p[5]                       # ← 左右手在这里区分手性！
x 轴   = normalize(cross(y辅助, z))
y 轴   = normalize(cross(z, x))
T      = [[ x | y | z | o ],[0 0 0 1]]            # 列为基向量，平移为 o
canonical = (homogeneous(p) @ inv(T)^T)[:, :3]   # (21,3)
```

要点：
- **左右手手性**靠 y 辅助轴方向区分（`is_left`）。**填错会导致 GeoRT 输出镜像/错乱**。
- 若任一基向量退化（模 < 1e-6），约定回退为 `p - p[0]`（仅平移到腕原点）。
- §6 直接给出可复制的 `hand_to_canonical` 实现，照用即可，**不要自创规范化**。

---

## 4. 你只需实现一个函数

整套桥接里**唯一需要你写的设备相关部分**就是：

```python
def get_raw_keypoints(is_left: bool) -> np.ndarray | None:
    """
    从你的手套 SDK 取一帧，返回 (21,3) float 的【世界坐标】关键点，
    顺序严格按 §2 的索引表；缺帧返回 None。
    单位：米。坐标系：任意右手系世界坐标（规范化会消掉绝对位姿）。
    """
    ...
```

其余（规范化 + 打包 + UDP 发送 + 频率控制）用 §6 的骨架，不用改。

---

## 5. 验证流程（建议顺序）

1. **离线自检**：用现成工具把你产出的关键点录成 `.npy` 看 shape/数值是否合理——
   把你的桥接接到 `collect_mocap_data.py` 的取数口，或直接 `np.save("test.npy", np.stack(frames))`，确认 shape `[T,21,3]`、腕原点附近、指尖在合理范围。
2. **接 GeoRT**：起 GeoRT 重定向
   `python teleoperation/GeoRT/geort/mocap/rokoko_retarget_send_right.py -ckpt_tag dexjoco_right_default --bind_ip 127.0.0.1 --bind_port 5013 --target_ip 127.0.0.1 --target_port 5014`
   再跑你的桥接发往 `127.0.0.1:5013`，看 GeoRT 打印的 `qpos`（16 维）是否随手型变化、是否在关节限位内。
3. **接仿真**：起 human 渲染的任务环境，按 `;` 开启遥操，看灵巧手是否跟手型动（手腕仍由 Vive/5012 这路负责，与本文无关）。
4. **手性检查**：故意做"张开/握拳/捏取"，确认机器手不是镜像反的；反了就检查 §3 的 `is_left` 与 y 辅助轴方向。

---

## 6. 参考实现骨架（自包含，填 `get_raw_keypoints` 即可）

```python
#!/usr/bin/env python3
"""方案 B 桥接：你的手套 → canonical (21,3) float32 → GeoRT(5013/5015)。
   只需实现 get_raw_keypoints()，其余照用。"""
import argparse, socket, time
import numpy as np

# ---- 与 GeoRT 训练一致的规范化（勿改），复制自 rokoko/common.py ----
def hand_to_canonical(hand_point: np.ndarray, is_left: bool) -> np.ndarray:
    p = np.asarray(hand_point, dtype=np.float32); eps = 1e-6
    z = p[9] - p[0]
    if np.linalg.norm(z) < eps: return p - p[0]
    z = z / np.linalg.norm(z)
    yaux = (p[13] - p[5]) if is_left else (p[5] - p[13])
    if np.linalg.norm(yaux) < eps: return p - p[0]
    yaux = yaux / np.linalg.norm(yaux)
    x = np.cross(yaux, z)
    if np.linalg.norm(x) < eps: return p - p[0]
    x = x / np.linalg.norm(x)
    y = np.cross(z, x); y = y / np.linalg.norm(y)
    T = np.eye(4, dtype=np.float32)
    T[:3, :3] = np.stack([x, y, z], axis=1); T[:3, 3] = p[0]
    homo = np.concatenate([p, np.ones((21, 1), np.float32)], axis=1)
    return (homo @ np.linalg.inv(T).T)[:, :3]

# ====== 你唯一要实现的部分 ======
def get_raw_keypoints(is_left: bool):
    """返回 (21,3) float 世界坐标，顺序见文档 §2；缺帧返回 None。"""
    raise NotImplementedError("接入你的手套 SDK，按 21 点顺序返回世界坐标")
# ================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hand", choices=["left", "right"], default="right")
    ap.add_argument("--target-ip", default="127.0.0.1")     # GeoRT 的 bind_ip
    ap.add_argument("--target-port", type=int, default=None) # 右=5013 左=5015
    ap.add_argument("--hz", type=float, default=90.0)
    a = ap.parse_args()
    is_left = a.hand == "left"
    port = a.target_port if a.target_port is not None else (5015 if is_left else 5013)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / a.hz if a.hz > 0 else 0.0
    print(f"sending {a.hand} canonical keypoints -> {a.target_ip}:{port}")
    while True:
        t0 = time.time()
        raw = get_raw_keypoints(is_left)            # (21,3) 世界坐标
        if raw is not None:
            can = hand_to_canonical(raw, is_left)   # (21,3) canonical
            sock.sendto(np.asarray(can, np.float32).tobytes(), (a.target_ip, port))  # 252 B
        if interval > 0:
            dt = interval - (time.time() - t0)
            if dt > 0: time.sleep(dt)

if __name__ == "__main__":
    main()
```

---

## 7. 一页checklist（满足即接入成功）

- [ ] 输出 `(21,3)`、**float32**、`tobytes()`，目标 **右5013 / 左5015**（IP=GeoRT bind_ip）。
- [ ] 21 行顺序严格按 §2（指尖 idx 4/8/12/16；规范化用到 0/5/9/13）。
- [ ] 发出前做 §3/§6 的 **canonical 规范化**（不要发世界坐标）。
- [ ] 左右手 `is_left` 正确（影响 y 辅助轴 → 不会镜像）。
- [ ] 单位米；缺帧返回 None 跳过，不发半包。
- [ ] GeoRT 用 `dexjoco_right_default`/`dexjoco_left_default`，输出 16 维 qpos → 5014/5016（这段不改）。

> 满足以上，**GeoRT 与仿真侧零改动**即可用你的手套遥操 Allegro。
> （若你同时换了灵巧手导致关节数≠16，则属于"换手"范畴，需另训 GeoRT 并改仿真侧的 16，见 `GLOVE_REPLACEMENT_API.md` / 灵巧手替换说明。）
