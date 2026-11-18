# Qwen3-TTS GGUF

[English](readme.en.md)

用 llama.cpp 跑的 Qwen3-TTS，支持流式合成、声音克隆，附带图形界面和 OpenAI 兼容的本地 HTTP 服务。

本项目基于 [HaujetZhao/Qwen3-TTS-GGUF](https://github.com/HaujetZhao/Qwen3-TTS-GGUF)（MIT）二次开发，在上游基础上新增图形界面、OpenAI 兼容 HTTP 服务与一键安装脚本。

三步用起来：双击 `setup.bat` 装环境 → 准备 `model-base` 模型目录 → 双击 `启动GUI.bat`。

## 目录

- [这个版本多了什么](#这个版本多了什么)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [模型](#模型)
- [推理](#推理)
- [HTTP API 服务](#http-api-服务)
- [代码调用](#代码调用)
- [性能与显存](#性能与显存)
- [导出模型](#导出模型)
- [原理](#原理)
- [常见问题](#常见问题)

## 这个版本多了什么

相对上游的改动：

- **图形界面**（`52-GUI.py`）：克隆 / 自定义音色 / 音色设计 / 服务 / 工具 / 设置 / 日志，七个标签页，不用改代码就能跑。
- **OpenAI 兼容 HTTP 服务**（`tts_server.py`）：`/v1/audio/speech`、`/v1/voices`，SillyTavern、Cherry Studio、Open WebUI 直接填地址就能用。
- **一键安装体检**（`install.py` + `setup.bat`）：Python 版本、虚拟环境、依赖、llama.cpp 运行库、模型、FFmpeg、音色目录逐项检查，缺什么装什么。
- **中文文档与启动脚本**：`启动GUI.bat` / `启动服务.bat` / `克隆音色.bat`，双击即用。

上游本身提供的能力：

- **流式合成**：边推边播，首音延迟最低 300ms 内。
- **加速推理**：Talker / Predictor 走 llama.cpp（Vulkan 或 CUDA），Encoder / Decoder 走 ONNX Runtime（DirectML 或 CUDA）。
- **确定性控制**：Talker 与 Predictor 的随机种子可独立设置，输出可复现。

## 环境要求

| 项目 | 要求 |
| :--- | :--- |
| 系统 | Windows 10/11 x64（Linux 需自行准备 llama.cpp 与 FFmpeg） |
| Python | **3.14**（`pyproject.toml` 要求 `>=3.14`） |
| 显卡 | 建议独显。N 卡走 CUDA 或 Vulkan；A 卡 / I 卡走 Vulkan；纯 CPU 也能跑，但 RTF > 1 |
| 显存 | 1.7B 全套约 **1.8 GB**；0.6B 再省约 500 MB |
| 磁盘 | 模型约 **1.5 GB**，llama.cpp 运行库约 94 MB，虚拟环境约 3.4 GB |
| 其他 | FFmpeg（读取/转码音频，`setup.bat` 会自动装） |

`setup.bat` 会自动检查并补齐 Python 依赖、llama.cpp 运行库和 FFmpeg，只有模型需要你自己准备（见[模型](#模型)）。

### 本机实测

表格里的数字来自下面这台机器，全部是实际跑出来的：

| 项目 | 配置 |
| :--- | :--- |
| 机型 | 机械革命 MEOW R16 24H（笔记本） |
| CPU | AMD Ryzen 9 7845HX |
| 显卡 | NVIDIA RTX 4060 Laptop，8 GB 显存 |
| 内存 | 32 GB |
| 系统 | Windows 11 |

一段 13.76 秒的中文，用 1.7B 模型克隆音色、ONNX 走 CUDA：

```
性能分析报告 (音频长度: 13.76s)
  1. Prompt:    0.03s
  2. Prefill:   0.04s
  3. Generate:  4.74s (Talker: 1.25s, Predictor: 3.49s)
  4. Decode:    5.15s
  5. Latency:   0.72s
核心总耗时: 4.80s | RTF (Core): 0.35
```

RTF 0.35 表示生成 1 秒音频只要 0.35 秒，比实时播放快约三倍，流式播放不会卡。显存占用约 1.8 GB，8 GB 的 4060 绰绰有余。

## 快速开始

### 1. 装环境

双击 `setup.bat`。它会检查 Python 版本、创建 `.venv`、装依赖、下载 llama.cpp 运行库和 FFmpeg，最后打印一份体检报告：

```
[ OK ] Python 版本    3.14.7
[ OK ] 虚拟环境 .venv  Python 3.14.7
[ OK ] Python 依赖     齐全，加速 DmlExecutionProvider
[ OK ] llama.cpp 运行库  qwen3_tts_gguf\inference\bin  共 94 MB
[ FAIL ] 模型文件 model-base  目录不存在
[ OK ] FFmpeg  7.1.1-essentials_build  C:\ffmpeg\bin\ffmpeg.EXE
[ OK ] 音色目录  9 个音色
```

第一遍通常只有「模型文件」一项是红的，这是正常的——下一步解决。

只想检查不想改动，用命令行：

```bash
python install.py --check       # 完整体检
python install.py --check -q    # 只报问题
python install.py               # 体检 + 自动修复，加 --yes 免确认
```

### 2. 准备模型

推理需要 `model-base` 目录，放在项目根目录下，里面是导出好的 GGUF 与 ONNX 文件。三条路，选一条：

**A. 自己导出**（从零，最慢，约 1-2 小时）

先下载官方模型，再跑[导出模型](#导出模型)里的脚本。适合想换量化精度或改结构的人。

**B. 直接拷贝现成的 `model-base` 目录**

最快的办法。问有导出过的朋友拷一份，整目录放到项目根下即可，`install.py` 会自己认出来。

**C. 从 ModelScope 下载官方模型后导出**

官方模型地址：

- [Qwen3-TTS-12Hz-1.7B-Base](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-1.7B-Base)
- [Qwen3-TTS-12Hz-1.7B-CustomVoice](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- [Qwen3-TTS-12Hz-1.7B-VoiceDesign](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign)
- [Qwen3-TTS-12Hz-0.6B-Base](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-0.6B-Base)
- [Qwen3-TTS-12Hz-0.6B-CustomVoice](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)

```bash
pip install modelscope
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-Base
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign
```

下载位置默认在 `~/.cache/modelscope/hub/models/Qwen`，导出脚本会自动探测；放在别处就设环境变量 `QWEN_MODEL_HOME` 指过去（见[导出模型](#导出模型)）。

### 3. 启动

| 文件 | 作用 |
| :--- | :--- |
| `启动GUI.bat` | 图形界面（启动前跑一次快速体检） |
| `启动服务.bat` | 只启 HTTP 服务，不开界面，默认 `127.0.0.1:8899` |
| `克隆音色.bat` | 交互式克隆音色，边推边播 |

双击任意一个就行。命令行等价写法：

```bash
python 52-GUI.py                       # 图形界面
python tts_server.py --port 8899       # HTTP 服务
python 51-Interactive-Clone.py         # 交互式克隆
```

### 手动部署（不用 bat）

想自己控制环境，按下面的来。

**依赖**

```bash
uv sync --extra dml      # DirectML（A 卡 / I 卡 / N 卡都行）
uv sync --extra gpu      # CUDA（N 卡，更快）
```

跑导出脚本再加 `--extra export`。不用 uv 就 `pip install -r requirements.txt`。

**llama.cpp 运行库**

适配版本 **b10621**。从 [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) 下预编译包，DLL 放进 `qwen3_tts_gguf/inference/bin/`：

| 平台 | 下载文件 |
| :--- | :--- |
| Windows (Vulkan) | `llama-b10621-bin-win-vulkan-x64.zip` |
| Windows (CUDA) | `llama-b10621-bin-win-cuda-13.3-x64.zip`（另需 `cudart64_13.dll`、`cublas64_13.dll`） |

**FFmpeg**

用于读写音频文件，装完确保 `ffmpeg` 在 PATH 里。

## 模型

### 支持的模型

五种官方模型，对应三种用法：

| 源模型 | 用法 | 导出的目录 |
| :--- | :--- | :--- |
| Qwen3-TTS-12Hz-1.7B-Base | 声音克隆 | `model-base` |
| Qwen3-TTS-12Hz-1.7B-CustomVoice | 内置音色 + 风格指令 | `model-custom` |
| Qwen3-TTS-12Hz-1.7B-VoiceDesign | 用自然语言设计音色 | `model-design` |
| Qwen3-TTS-12Hz-0.6B-Base | 声音克隆（省显存） | `model-base-small` |
| Qwen3-TTS-12Hz-0.6B-CustomVoice | 内置音色（省显存） | `model-custom-small` |

用哪个就导哪个。0.6B 能再省约 500 MB 显存，但速度提升不明显——**计算瓶颈在 Predictor**，每秒音频要自回归 12.5×15=187.5 次，0.6B 和 1.7B 的差别只在 Talker。

### 内置音色

CustomVoice 模型自带 9 个音色：

| ID | 说明 |
| :--- | :--- |
| vivian | 年轻女声，明亮利落 |
| serena | 温暖女声，柔和亲切 |
| uncle_fu | 成熟男声，沉稳低沉 |
| dylan | 北京男声，自然清晰 |
| eric | 成都男声，略带沙哑 |
| ryan | 活力男声，节奏感强 |
| aiden | 阳光美男，中频清澈 |
| ono_anna | 日语女声，俏皮轻快 |
| sohee | 韩语女声，温润动情 |

### 支持的语言

chinese、english、japanese、korean、german、spanish、french、russian、italian、portuguese、beijing_dialect、sichuan_dialect。

## 推理

### 图形界面（推荐）

双击 `启动GUI.bat`，或 `python 52-GUI.py`。

| 标签页 | 用途 |
| :--- | :--- |
| 克隆 | 用参考音频克隆音色，批量出 wav/json |
| 自定义音色 | 内置音色 + 风格指令 |
| 音色设计 | 用自然语言描述音色 |
| 服务 | 把引擎挂成本地 HTTP 服务，供其他程序调用 |
| 工具 | 音色向量重建、WAV ↔ JSON 互转 |
| 设置 | 单模型模式、界面语言 |
| 日志 | 运行日志 |

模型载入时可以分别指定 LLM 设备（GPU/CPU）和 ONNX 组件设备（GPU/CPU）。显存不够就把编码器丢给 CPU，它只做特征提取，不吃算力。

### 脚本模式

三个示例脚本，对应三种模型：

```bash
python 41-Inference-Custom.py  # 内置音色
python 42-Inference-Design.py  # 音色设计
python 43-Inference-Base.py    # 声音克隆
```

### 交互模式

```bash
python 51-Interactive-Clone.py
```

启动后直接打字，边推边播，适合调音色。

## HTTP API 服务

GUI 的「服务」页可以把引擎挂成一个 **OpenAI 兼容**的本地 HTTP 服务，SillyTavern、Cherry Studio、Open WebUI、AnythingLLM 这类支持自定义 endpoint 的客户端，填 `http://127.0.0.1:8899` 就能用。

不想开界面也可以单独跑：

```bash
启动服务.bat                                    # 默认 127.0.0.1:8899
python tts_server.py --host 0.0.0.0 --port 8899 --voice 巧克力
```

注意 `--host 0.0.0.0` 会把服务暴露到局域网，没有鉴权，只在自己信任的网络里用。

### 接口

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| `POST` | `/v1/audio/speech` | 合成语音，返回音频字节流 |
| `GET` | `/v1/voices` | 列出可用音色（音色目录下的 json / wav） |
| `GET` | `/v1/models` | OpenAI 模型列表，返回一个本地模型 |
| `GET` | `/health` | 健康检查，返回引擎是否就绪、当前音色 |

### 合成请求

```bash
curl http://127.0.0.1:8899/v1/audio/speech ^
  -H "Content-Type: application/json" ^
  -d "{\"input\":\"你好，我是巧克力。\",\"voice\":\"巧克力\",\"response_format\":\"mp3\"}" ^
  --output hello.mp3
```

| 字段 | 默认 | 说明 |
| :--- | :--- | :--- |
| `input` | 必填 | 要合成的文本（也接受 `text`） |
| `voice` | 服务默认音色 | 音色名，不带后缀，在音色目录里查找 |
| `response_format` | `mp3` | `mp3` / `wav` / `flac` / `opus` / `aac` / `pcm`，非 wav 走 FFmpeg 转码 |
| `language` | `Chinese` | 语种，见[支持的语言](#支持的语言) |
| `speed` | `1.0` | 语速倍率，1.25 表示快 25% |
| `temperature` | 0.6 | 采样温度，越小越稳 |
| `seed` | 42 | 随机种子，固定后输出可复现 |

引擎在第一次请求时才载入（DirectML 下约 3–6 秒），之后复用同一个 stream，连续请求不会反复初始化。合成是串行的，多个请求会排队。

### 客户端接入

OpenAI SDK 直接改 base_url：

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8899/v1", api_key="not-needed")
audio = client.audio.speech.create(
    model="qwen3-tts-gguf",
    voice="巧克力",
    input="今晚吃什么？",
    response_format="mp3",
)
audio.stream_to_file("hello.mp3")
```

## 代码调用

```python
from qwen3_tts_gguf import TTSEngine, TTSConfig

# 初始化引擎（后台并行加载模型）
engine = TTSEngine(model_dir="model-base")
stream = engine.create_stream()

# 设置音色（支持 .wav 路径、.json 路径或 TTSResult 对象）
stream.set_voice("output/elaborate/sample.json")

# 配置推理参数
config = TTSConfig(
    temperature=0.8,      # 核心温度，控制随机性
    sub_temperature=0.8,  # 细节温度，控制随机性
    seed=42,              # 核心种子
    sub_seed=45,          # 细节种子
    streaming=True,       # 开启流式
)

# 合成
result = stream.clone("你好，世界！", config=config)
stream.join()             # 等待播完

# 保存结果
result.save("output/output.wav")
result.save("output/output.json")  # 保存 codes，下次无损加载
```

## 性能与显存

### 速度

RTF < 1 表示生成比实时播放快。

| 设备 | RTF | 说明 |
| :--- | :--- | :--- |
| RTX 4060 Laptop 8G + CUDA | 0.35 | 本机实测，见[本机实测](#本机实测) |
| RTX 5050 | 0.35 | 上游作者的实测数据 |
| 纯 CPU | 1.3 | 跟不上实时播放 |
| 集显 | 1.3 | 同上 |

没有独显的机器很难做到 RTF < 1，流式播放会卡顿。批量推理例外，见[批量显存估算](#批量显存估算)。

### 显存占用

1.7B 全套：

| 组件 | 量化 | 占用 |
| :--- | :--- | :--- |
| Encoder（特征提取） | fp16 ONNX | 可用 CPU，不占显存 |
| Talker 1.7B | Q5_K | 权重 955 MB + 上下文 224 MB + 计算 50 MB ≈ 1229 MB |
| Predictor 0.1B | Q8_0 | 权重 144 MB + 上下文 5 MB + 计算 7 MB ≈ 156 MB |
| Decoder | fp16 ONNX | 模型 237 MB + 推理 204 MB |
| **合计** | | **约 1.8 GB** |

显存紧张时把 Encoder 放到 CPU，能省下约 120 MB。

### 上下文长度估算

每路任务在 Talker 上下文里占的 token 数：

- 每秒音频占 **12.5** 个音频 token（12Hz 帧率）
- 目标文本按每秒音频 **4** 个文本 token 折算（约 4 字/秒，随音频帧逐个注入）
- 再加约 **10** 个常数控制 token（角色头、语言、说话人嵌入、TTS_BOS 等）

克隆时参考音频同样占上下文（音频 12.5 token/秒，参考文本 4 token/秒），所以单路上下文只取决于**总音频秒数**（参考 + 生成）：

```
ctx ≈ 10 + 16.5 × 总音频秒数
```

例：每路 512 ctx，参考加生成合计最长 `(512 - 10) / 16.5 ≈ 30` 秒。Custom Voice / Voice Design 没有参考音频，上下文全部留给生成。超出会报 Talker context overflow，批量推理时 `n_ctx_per_seq` 按这个上限取。

### 批量显存估算

批量推理（`BatchRunner`，CUDA）分两块：

**常驻部分**（按文件大小计）：

| 组件 | 大小 |
| :--- | :--- |
| Talker 权重 (Q5_K) | 960 MB |
| Predictor 权重 (Q8_0) | 144 MB |
| Decoder chunk64 | 620 MB |

**批量部分**（每轮 `clone_batch` 创建、跑完释放，随路数 B 线性增长）：

| 组件 | 大小 |
| :--- | :--- |
| Talker KV | 0.11 MB/token，即 0.11 MB × B × ctx |
| Predictor KV | 5 MB × B |
| 计算缓冲 | 50 MB + 2 MB × B |

合计：`总量 ≈ 1.78 GB + 0.11 MB × B × ctx`

例：32 路、每路 512 ctx ≈ 1.78 + 1.80 ≈ **3.6 GB**（注意 512 ctx 只装得下 30 秒总音频）。

批量只对 LLM 部分有加速（读取瓶颈），生成 codes 之后的解码器部分是计算瓶颈，多路没有加速。实测 32 路 ctx512 在 RTX 5050 上能做到 RTF 0.055（LLM 0.043 + Decoder 0.012）。

## 导出模型

只有走「自己导出」这条路才需要看这节。

### 配置路径

`export_config.py` 决定从哪儿读官方模型、往哪儿写导出结果。源目录按这个顺序自动探测：

1. 环境变量 `QWEN_MODEL_HOME`
2. `D:\qwen3-tts\models`
3. `~/.cache/modelscope/hub/models/Qwen`

都不对就在命令行里临时指定：

```bash
set QWEN_MODEL_HOME=E:\models\Qwen
```

输出目录固定是项目根下的 `model-base` / `model-custom` / `model-design` / `model-base-small` / `model-custom-small`。文件里 `model = Models.base` 这一行切换默认导出哪个模型。

### 阶段一：导出小组件

```bash
python 11-Export-Codec-Encoder.py    # 编码器，克隆时提取 codes
python 12-Export-Speaker-Encoder.py  # 说话人特征提取
python 13-Export-Decoder.py          # 解码器，核心渲染器
python 14-Export-Embeddings.py       # Embedding 权重
python 15-Copy-Tokenizer.py          # 文本分词器
python 16-Quantize-ONNX-Models.py    # 关键：ONNX 转 FP16 才能走 DML 加速
```

### 阶段二：导出 Talker

Talker 是 1.42B 的 LLM backbone，负责理解文本、生成语音骨架：

```bash
python 21-Extract-Talker-Weights.py    # 拆分并初始化权重
python 22-Prepare-Talker-Tokenizer.py  # 构造 GGUF 所需的迷你词表
python 23-Convert-Talker-GGUF.py       # 转成 F16 的 GGUF
python 24-Quantize-Talker-GGUF.py      # 量化为 Q5_K，推理默认加载这版
```

### 阶段三：导出 Predictor

Predictor 是 142M 的小模型，负责给骨架补细节：

```bash
python 31-Extract-Predictor-Weights.py
python 32-Prepare-Predictor-Tokenizer.py
python 33-Convert-Predictor-GGUF.py
python 34-Quantize-Predictor-GGUF.py   # 量化为 Q8_0，推理默认加载这版
```

导完 `model-base` 里应该有 6 个文件、约 1.5 GB。导出过程中踩过的坑记在 [Experience](./Experience) 目录里。

## 原理

### 架构

用人体器官理解：

1. **耳朵**（Encoder）：听参考音频，提取音色特征
2. **大脑**（Talker）：生成语音骨架（28 层，1.42B）
3. **双手**（Predictor）：补充细节（8 层，142M）
4. **嘴巴**（Decoder）：把 codes 解码成声音

推理引擎：Talker / Predictor 用 llama.cpp（GGUF，Vulkan / CUDA 加速），Encoder / Decoder 用 ONNX Runtime（ONNX，DirectML / CUDA 加速）。

### 声音克隆

克隆的本质是**接续说话**（In-Context Learning）。

想象你正在读一段话，读到一半我让你接着读，你自然会用同样的语气和声音。Qwen3-TTS 也是这么做的：

1. **文本拼接**：把参考文本和目标文本连起来。
2. **注入记忆**：把参考音频转成 spk_emb 和 codes 注入记忆，让模型以为前面那段是它自己刚说的。
   - **嗓子**（spk_emb）：整体音色，告诉模型它用的是什么样的嗓子。
   - **音节**（codes）：具体发音码（12.5Hz），让模型相信「我刚才确实说了这些音节」。
3. **顺势说完**：有了嗓子和音节记忆，模型就保持这个声音把剩下的读完。

### 内置音色

和克隆类似，只是模型自带说话人音色（spk_emb），记忆里只有嗓子没有音节，需要根据指令和目标文本进入相应情感状态再读。

- 克隆：读了一半，接着读。
- Custom Voice：还没读，酝酿情感，从头读。

所以 Clone 情感基调已定，音色更稳；Custom Voice 每次抽卡会酝酿出不同基调。最佳实践是先拿 Custom Voice 对同一段文字抽卡出最好的效果，再用 Base 模型基于这段音频克隆其它文本。

## 常见问题

**Q: 双击 `setup.bat` 之后提示「模型文件 model-base 目录不存在」？**

正常，模型不在自动安装范围内。见[准备模型](#2-准备模型)，拷一份 `model-base` 目录放进项目根即可。

**Q: 为什么不用官方 PyTorch？**

官方实现吃显存。llama.cpp 省资源，还能用 Vulkan / DML 加速，8 GB 显卡就能跑。

**Q: 流式和离线有什么区别？**

流式边推边播，首包延迟低（约 300ms）；离线要等全部生成完才出音。

**Q: 服务起不来，提示端口被占用？**

换端口，或先关掉占用 8899 的进程。`netstat -ano | findstr :8899` 找 PID。

**Q: 客户端连上了但一直转圈？**

引擎是懒加载的，第一次请求要等模型载入（DirectML 下 3–6 秒）。先 `curl http://127.0.0.1:8899/health` 看 `engine` 是不是 `true`。

**Q: 显存不够怎么办？**

三招：Encoder 放 CPU（省 120 MB）；换 0.6B 模型（省 500 MB）；缩短参考音频和 `max_steps`，上下文按 `10 + 16.5 × 总音频秒数` 估。

**Q: 怎么调质量？**

`TTSConfig(temperature=0.8, sub_temperature=0.8, seed=42, sub_seed=45)`。温度控制随机性，种子控制复现。音色不稳就先固定种子多跑几次挑一个。

## 相关链接

- [上游项目：HaujetZhao/Qwen3-TTS-GGUF](https://github.com/HaujetZhao/Qwen3-TTS-GGUF)
- [Qwen3-TTS 技术报告](./Qwen3-TTS%20Technical%20Report.md)
- [导出经验笔记](./Experience)
- [llama.cpp](https://github.com/ggerganov/llama.cpp)
- [License (MIT)](./LICENSE)
