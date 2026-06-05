# Manus SDK
## 终端1：Manus 采集客户端（sharpa-manus-sdk，先按其启动流程标定+联网）
cd /mnt/gaokj/dexjoco/sharpa-manus-sdk/client && ./SharpaManusClient.out
##   持续打印 "Frame[..] glove: Right is published" → ZMQ PUB 在 tcp://127.0.0.1:2044


# 手部 manus 桥接（替代 rokoko_mocap，丢四元数→canonical 21点→5013/5015）
conda activate dexjoco
export SHARPA_MANUS_SDK=/mnt/gaokj/dexjoco/sharpa-manus-sdk
cd /mnt/gaokj/dexjoco
python teleoperation/manus/manus_mocap_bimanual.py --target-ip 127.0.0.1


# Vive Tracker

## 0) 先确保 SteamVR 已启动、tracker 已追踪；并装好 openvr
pip install openvr

## 1) 先列设备，找到你的 tracker 的 index / serial
python teleoperation/vive_bridge/send_vive_pose.py --list-devices
##   输出形如：index=3 class=tracker serial=LHR-XXXX model=...

## 2) 单双手腕：流式发 3×4 float64 位姿到 5012（默认 127.0.0.1:5012 @90Hz）
python teleoperation/vive_bridge/send_vive_pose.py \
  --host 127.0.0.1 --port 5012 \
  --two-trackers \
  --device-index 3 \          # primary → 右臂
  --second-device-index 4     # secondary → 左臂

python teleoperation/vive_bridge/send_vive_pose.py \
  --host 127.0.0.1 --port 5012 --two-trackers \
  --serial-contains AAAA \          # 右
  --second-serial-contains BBBB     # 左
##   不指定 --device-index 时，默认自动挑第一个 class=tracker 的设备

## tip
接收端right = arr[:12](=primary)、left = arr[12:24]，因此要第一个写right第二个写left


# GeoRT

## Smoke Test

```bash
python ./geort/mocap/rokoko_evaluation.py \
  -hand allegro_right \
  -ckpt_tag <YOUR_CKPT> \
  -data <YOUR_TRAINING_DATA>
```
## Retargeting
```bash
conda activate geort   # 或 GeoRT 所在环境
python teleoperation/GeoRT/geort/mocap/rokoko_retarget_send_right.py \
  -ckpt_tag dexjoco_right_default \
  --bind_ip 127.0.0.1 --bind_port 5013 --target_ip 127.0.0.1 --target_port 5014
```
## tip
因当前机型原因，将所有GeoRT代码设置成在cpu上跑，gpu版本存在.cudaback中


# 仿真 + 录制（human 渲染，按 ; 开遥操、r 丢弃重来）
conda activate dexjoco
python scripts/record_demos_zarr.py --exp_name=water_plant --render_mode=human --successes_needed=20 --out_dir=./demos

## tip
- exp_name可执行列表：
单臂	双臂
click_mouse	bimanual_assembly
fold_glasses	bimanual_hanoi
hammer_nail	bimanual_microwave_cook
pick_bucket	bimanual_photograph
pinch_tongs	bimanual_unlock_ipad
water_plant	

- render_mode
值	含义	适用
human	开一个交互式 GLFW 3D 窗口,实时显示场景;键盘回调挂在这个窗口上	采集/遥操必须用它
rgb_array	headless 离屏渲染(EGL),只产生图像/录像,不开窗口、没有键盘交互	策略评测/自动跑、无显示器

- render_mode=human时会开：
（1）MuJoCo 3D 交互窗口(GLFW)，键盘也重定向在这个地方（;开始录制, r 重置）
（2）OPENCV腕部相机窗口，--show_sim_cameras 默认 True，会弹出腕部相机

- 因为默认GLFW，因此对显卡的要求只有拥有OpenGL驱动，本任务离屏缓冲是 2048×2048,窗口默认 640×640，所需显存很小

- 当前保存逻辑是：任务成功时自动保存从;/r按下到成功的视频+轨迹

- 这里提供了一个按s就能保存一条的程序：
```bash
conda activate dexjoco
python scripts/record_demos_zarr_manualsave.py \
  --exp_name=water_plant --render_mode=human \
  --successes_needed=9999 \        # 设很大，避免自动成功就提前结束；你想手动存多少就存多少
  --out_dir=./demos
```


