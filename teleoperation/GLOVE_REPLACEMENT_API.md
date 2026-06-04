# 数据手套替换 API 文档（DexJoCo 遥操手部输入接口）

> 目的：说明 DexJoCo 当前 `teleoperation/rokoko/` 这套手套桥接在**整条手部数据链路**中承担的输入/输出接口，
> 以便用**其它数据手套**替换 Rokoko 时，知道"必须满足哪些接口契约"。
>
> 适用范围：只涉及**手部（手指关节）**这一路。手腕 6D 位姿走的是 Vive/OpenVR → UDP 5012，与本文无关。

---

## 1. 链路总览：rokoko 文件夹处在哪一段

手部信号从硬件到仿真共 **4 段、3 个可替换边界**：

```
[数据手套硬件]                                                                  仿真
   │                                                                             ▲
   │  ① 厂商软件(Rokoko Studio)                                                   │
   ▼  UDP 14044  (JSON 场景, 含 21 关键点)                                         │
┌──────────────────────────────┐                                                 │
│ teleoperation/rokoko/ 桥接    │  ← 本文档的对象                                  │
│  RokokoReceiver: 解析 + 规范化 │                                                 │
└──────────────────────────────┘                                                 │
   │  ② UDP 5013(右)/5015(左)  (canonical 21×3 keypoints, float32)                │
   ▼                                                                             │
┌──────────────────────────────┐                                                 │
│ teleoperation/GeoRT/ 重定向   │  model.forward((21,3)) → 机器手关节角 qpos        │
└──────────────────────────────┘                                                 │
   │  ③ UDP 5014(右/单)/5016(左)  (N 维 qpos, float64)                            │
   └─────────────────────────────────────────────────────────────────────────────┘
                                                       sim_teleop.py 后台线程接收
```

**`rokoko/` 文件夹的职责** = 把厂商软件(Rokoko Studio)的 **① 原始手部数据** 解析、抽取 21 个关节、做**规范化(canonical)**，再以 **② 固定格式**转发给 GeoRT。它的：
- **输入接口**（消费）：端口 `14044` 上的 **Rokoko Studio JSON 包**。
- **输出接口**（产出）：端口 `5013/5015` 上的 **canonical `(21,3)` float32 关键点**。

涉及文件：
| 文件 | 作用 |
|---|---|
| [`rokoko/common.py`](rokoko/common.py) | `RokokoReceiver`：收 14044、解析 JSON、抽 21 关键点、`hand_to_canonical` 规范化 |
| [`rokoko/rokoko_mocap.py`](rokoko/rokoko_mocap.py) | 单手转发：canonical `(21,3)` → 5013/5015 |
| [`rokoko/rokoko_mocap_bimanual.py`](rokoko/rokoko_mocap_bimanual.py) | 双手转发：左右各一路 → 5015/5013 |
| [`rokoko/collect_mocap_data.py`](rokoko/collect_mocap_data.py) | 录 canonical 关键点为 `.npy`（`[T,21,3]`，给 GeoRT 训练用） |

---

## 2. 换手套：选哪个边界接入（三选一）

替换手套的本质是"在某个边界上，用你的设备产出和现有约定**一模一样**的字节流"。从易到难三种：

| 方案 | 接入边界 | 你需要产出的格式 | 复用 | 改动量 |
|---|---|---|---|---|
| **A. 仿 Rokoko Studio** | ① UDP `14044` | Rokoko Studio 风格 **JSON 场景**（含 21 命名关节的世界坐标） | rokoko 桥接 + GeoRT 全复用 | 大（要拼 JSON schema） |
| **B. 仿桥接输出（推荐）** | ② UDP `5013/5015` | **canonical `(21,3)` float32**（252 字节） | 复用 GeoRT；绕过 rokoko 桥接 | 中（自己产 21 关键点 + 规范化） |
| **C. 自带重定向** | ③ UDP `5014/5016` | **N 维关节角 `qpos` float64** | 绕过 rokoko + GeoRT，自己做人手→机器手映射 | 取决于你的重定向方案 |

> - 若你的手套也能给出**21 个手部关键点的 3D 位置**，走 **B** 最划算（GeoRT 直接用）。
> - 若你的手套只给关节角、或你已有自己的 retargeting，走 **C**，连 GeoRT 都不要。
> - **C 同时也是换灵巧手后最省事的测试入口**（见上一份 `simulator_explained.md` 的 mock 发送脚本）。

---

## 3. 接口契约详表

### 3.1 边界 ①：Rokoko Studio JSON（端口 14044，UDP 入）

`RokokoReceiver` 期望的包体（`parse_rokoko_packet`）：

- **传输**：UDP datagram，绑定 `--listen-port`（默认 `14044`），`buffer_size=262144`。
- **编码**：UTF-8 **JSON**；**可选 LZ4** 压缩（frame 或 block；带 `\x04\x22\x4D\x18` magic 时自动解压）。
- **结构**（必须存在的路径）：
  ```json
  {
    "scene": { "actors": [ { "body": {
        "rightIndexTip":      {"position": {"x":.., "y":.., "z":..}},
        "rightMiddleProximal":{"position": {"x":.., "y":.., "z":..}},
        ... 每只手 21 个关节，见 §3.3 ...
    } } ] }
  }
  ```
- 取数逻辑：`msg["scene"]["actors"][0]["body"][<jointName>]["position"]` 的 `x,y,z`。
- **坐标系/单位**：世界坐标系下的 3D 位置（米）。规范化会消掉绝对平移与朝向，所以**单位需一致、左右手手性需正确**即可。

> 要走方案 A，你的设备软件就得在 14044 上发出**这个 JSON 形状**（至少包含目标手的 21 个命名关节的 `position`）。

### 3.2 边界 ②：canonical 关键点（端口 5013/5015，UDP 出）

rokoko 桥接转发、GeoRT 接收的格式（`rokoko_mocap.py` 发 / GeoRT `UDPRokokoReceiver._parse_binary` 收）：

- **传输**：UDP；**右手 → `5013`，左手 → `5015`**（注意：这两个是 rokoko→GeoRT 的中间端口，不是仿真侧的 5014/5016）。
- **数据**：`np.ndarray`，shape **`(21, 3)`**，dtype **`float32`**，行优先 `tobytes()`。
  - 字节数 = `21 × 3 × 4 = 252` 字节，布局 `[p0.x, p0.y, p0.z, p1.x, …, p20.z]`。
  - GeoRT 也接受 **JSON** 形式的 `(21,3)`（`_parse_json` 兜底），但二进制 float32 是推荐路径。
- **坐标系**：**canonical 手系**（已规范化，见 §3.4），不是世界坐标。

> 要走方案 B，你只需产出 `(21,3) float32` 的 canonical 关键点发到 5013/5015。**21 点顺序与规范化约定必须和 §3.3/§3.4 完全一致**（GeoRT 是按这个约定训练的）。

### 3.3 21 个手部关键点：名称、顺序、索引（关键！）

每只手固定 **21 个关键点**，顺序写死在 `common.py` 的 `LEFT_JOINT_NAMES` / `RIGHT_JOINT_NAMES`（右手把 `left` 换成 `right`）：

| idx | 关节 | idx | 关节 | idx | 关节 |
|---|---|---|---|---|---|
| 0 | Hand（腕根） | 7 | IndexDistal | 14 | RingMedial |
| 1 | ThumbProximal | 8 | **IndexTip** | 15 | RingDistal |
| 2 | ThumbMedial | 9 | MiddleProximal | 16 | **RingTip** |
| 3 | ThumbDistal | 10 | MiddleMedial | 17 | LittleProximal |
| 4 | **ThumbTip** | 11 | MiddleDistal | 18 | LittleMedial |
| 5 | IndexProximal | 12 | **MiddleTip** | 19 | LittleDistal |
| 6 | IndexMedial | 13 | RingProximal | 20 | LittleTip |

- 顺序：`Hand`(0) → 拇指 4 节(1-4) → 食指 4 节(5-8) → 中指(9-12) → 无名指(13-16) → 小指(17-20)。
- **指尖索引**：拇指=4、食指=8、中指=12、无名指=16、小指=20。这些正是 GeoRT `config.json` 里 `fingertip_link[*].human_hand_id` 指向的点（Allegro 用拇/食/中/无名 4 指 → id `4/8/12/16`，**不用小指**）。
- 缺任一关节或形状 ≠ `(21,3)`，`extract_hand_positions` 返回 `None`，该帧被丢弃。

### 3.4 canonical 规范化约定（`hand_to_canonical`）

把 21 个世界坐标点变换到以腕为原点、由手指几何定轴的手系（消除绝对位置/朝向，只保留手型）：

```
原点  = point[0]            # Hand（腕根）
z 轴  = normalize(point[9]  - point[0])        # 指向 MiddleProximal
y 辅助= 右手: point[5]-point[13] / 左手: point[13]-point[5]   # IndexProximal↔RingProximal（含手性）
x 轴  = normalize(cross(y辅助, z))
y 轴  = normalize(cross(z, x))
T     = [[x y z | point0], [0 0 0 1]]
canonical = (homogeneous(points) @ inv(T).T)[:, :3]   # (21,3)
```
- **左右手手性**靠 `is_left` 决定 y 辅助轴方向——务必标对，否则 GeoRT 输出镜像错乱。
- 走方案 B 时，你的 21 点必须按同样公式规范化（否则需要重训 GeoRT）。

### 3.5 边界 ③：重定向后关节角（端口 5014/5016，供参考）

GeoRT 之后、仿真之前的格式（`rokoko_retarget_send_*.py` 发 / `sim_teleop.py` 收）：

- **传输**：UDP；**右/单手 → `5014`，左手 → `5016`**。
- **数据**：`qpos`，dtype **`float64`**，`tobytes()`；维度 = 机器手关节数 **N**（Allegro=16）。
- 仿真侧 `_recv_hand_loop`：`np.frombuffer(data, float64)`，**当前实现按 16 截断/补零**（换手改 N 时这里的 16 也要改）。

---

## 4. 端口 / 速率 / dtype 速查

| 边界 | 端口 | 方向 | dtype | 形状/字节 | 默认频率 |
|---|---|---|---|---|---|
| ① Rokoko Studio | `14044` | 入(桥接监听) | JSON(可LZ4) | 变长 | 由厂商软件决定 |
| ② canonical 关键点 | `5013`右 / `5015`左 | 出(桥接→GeoRT) | float32 | `(21,3)`=252B | ≤90 Hz（`--frequency`） |
| ③ 关节角 qpos | `5014`右 / `5016`左 | 出(GeoRT→仿真) | float64 | `(N,)`，N=16 → 128B | 跟随输入 |
| （手腕，非本文） | `5012` | Vive→仿真 | float64 | `(3,4)`=96B | 90 Hz |

- IP 默认 `127.0.0.1`，均可用命令行参数改（`--listen-ip/--target-ip/--bind_ip/--target_ip`、端口同理）。
- 典型双机拓扑：Rokoko Studio + rokoko 桥接在「手套 PC」，GeoRT + 仿真在「机器人 PC」。

---

## 5. 替换步骤（按方案）

### 方案 B（推荐）：你的手套 → canonical `(21,3)` → 5013/5015
1. 用你的手套 SDK 取**21 个手部关键点的 3D 世界坐标**（按 §3.3 的关节语义与顺序排好；缺的关节需估计/补齐）。
2. 按 §3.4 公式做 **canonical 规范化**（注意左右手手性）。
3. `np.asarray(arr, np.float32).tobytes()` 发到 `5013`（右）/`5015`（左）。
4. 继续用现有 GeoRT（`dexjoco_right/left_default`）→ 5014/5016 → 仿真。**无需改 GeoRT、无需改仿真**。
   - 验证：先用 [`collect_mocap_data.py`](rokoko/collect_mocap_data.py) 录一段你产出的关键点，确认 shape `[T,21,3]`、数值合理。

### 方案 C：你的手套 → 自做重定向 → qpos → 5014/5016
1. 自行把手套数据映射成**机器手 N 维关节角**（你自己的 retargeting，或重训 GeoRT）。
2. `qpos.astype(np.float64).tobytes()` 发到 `5014`（右/单）/`5016`（左）。
3. 若 N≠16，同步改 `sim_teleop.py` 里硬编码的 16 与 env 的 `_N_ALLEGRO`（见灵巧手替换四步）。

### 方案 A：你的设备软件 → 仿 Rokoko Studio JSON → 14044
1. 让你的软件在 14044 上发出 §3.1 的 JSON（含目标手 21 命名关节的 `position`）。
2. rokoko 桥接 + GeoRT 全部不动。

---

## 6. 必须满足的接口契约（一句话清单）

替换手套硬件后，**至少满足下列之一**即可接入 DexJoCo 手部链路：

- **[最省事-C]** 在 `5014/5016` 上发 **`float64` 的 N 维关节角 qpos**（自带重定向）。
- **[复用GeoRT-B]** 在 `5013/5015` 上发 **`float32` 的 `(21,3)` canonical 关键点**（21 点顺序 + 规范化约定见 §3.3/§3.4）。
- **[全复用-A]** 在 `14044` 上发 **Rokoko Studio 风格 JSON**（含 21 命名关节世界坐标）。

不在此列的任何"私有格式"都不会被现有 `rokoko/`、GeoRT、`sim_teleop.py` 接收。

---

## 附：与手腕一路的关系

手部（本文）与手腕是**两条独立链路**，互不影响：
- 手部：手套 → (rokoko) → (GeoRT) → `5014/5016`。
- 手腕：Vive Tracker → OpenVR → `send_vive_pose.py` → `5012`（`(3,4)` float64）。

换手套只动手部这一路；手腕路（5012）保持不变即可。
