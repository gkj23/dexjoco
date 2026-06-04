# DexJoCo 项目总结

## 项目定位
DexJoCo 是一个基于 MuJoCo 的灵巧操作仿真基准与工具链，核心目标是支持面向任务的单臂/双臂灵巧操作研究。项目覆盖 11 个任务，强调工具使用、双臂协同、长时序执行与一定的任务推理能力，同时提供数据采集、示教回放、训练与评测闭环。

## 目录结构
- README.md：项目总览、安装、评测、数据采集与训练说明。
- environment-dexjoco.yaml：主环境依赖，Python 版本要求为 3.10/3.11。
- dexjoco/：核心 Python 包。
- dexjoco/dexjoco_openpi_client/：OpenPI 策略客户端与评测入口。
- configs/：任务配置，按 rand_obj、rand_full、multi_task、ipad_reasoning 分类。
- scripts/：常用脚本，包括评测、录制示教、回放、环境测试。
- teleoperation/：遥操作采集相关文档与桥接模块。
- openpi/：针对 DexJoCo 适配的 OpenPI π0.5 训练与服务代码。
- ckpt/、outputs/：已有检查点与运行输出。

## 核心能力
- 仿真任务基准：11 个单臂/双臂操作任务。
- 数据采集：通过 	eleoperation/ 中的硬件/软件桥接进行示教录制。
- 数据格式：围绕 LeRobot 数据集格式组织，供 OpenPI 训练使用。
- 策略训练：依赖 openpi/ 子项目训练 π0.5 策略。
- 策略评测：通过 websocket 连接策略服务，在 DexJoCo 环境中执行评测。
- 随机化评测：支持 
and_obj 与 
and_full 两种随机化设定。

## 关键运行方式
### 1. 环境安装
主项目环境：
- conda env create -f environment-dexjoco.yaml
- conda activate dexjoco

OpenPI 环境：
- cd openpi
- ash install.bash
- conda activate openpi

### 2. 策略服务
OpenPI 服务端通常从 openpi/ 目录启动，例如：
- python scripts/serve_policy.py --port=8000 policy:checkpoint ...

### 3. 仿真评测
主入口是包脚本：
- dexjoco-openpi-eval --config=./configs/rand_obj/water_plant.yaml --seed=0 --port=8000

对应实现注册在：
- dexjoco/pyproject.toml
- dexjoco/dexjoco_openpi_client/eval_dexjoco_openpi.py

## 代码实现特点
- 评测端采用多进程结构，主进程与推理解耦。
- 通过 websocket 与 OpenPI 策略服务通信。
- 对动作 chunk 做缓存、时间戳对齐与插值平滑。
- 单臂与双臂动作空间分开处理，双臂任务使用更高维动作表示。

## 数据与训练约束
- 单臂任务默认 22 维动作，双臂任务默认 44 维动作。
- OpenPI 训练依赖 LeRobot 格式数据集。
- 
and_full 相比 
and_obj 增加更多视觉外观随机化。
- 双臂训练前需要将 π0.5 base checkpoint 转成 44 维动作版本。

## 适合的使用场景
- 灵巧操作 benchmark 复现。
- OpenPI/策略服务与仿真环境联调。
- 遥操作采集到训练再到评测的端到端实验流程。
- 面向单臂/双臂任务的策略泛化和随机化鲁棒性测试。

## 当前项目状态判断
从目录看，这个仓库不仅包含源码，还包含较大的 ckpt/、outputs/ 以及内置 openpi/ 子项目，说明当前目录更像 可直接训练和评测的工作区，而不是纯净源码镜像。后续接手时，建议优先确认：
- openpi/ 环境是否已正确安装。
- ckpt/ 中模型是否与当前配置匹配。
- configs/ 与数据集路径是否和本机实际路径一致。
- outputs/ 中历史结果是否需要保留或归档。
