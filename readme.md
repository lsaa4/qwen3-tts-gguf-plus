# Qwen3-TTS GGUF

[English](readme.en.md)

用 llama.cpp 跑的 Qwen3-TTS，支持流式合成、声音克隆，附带图形界面和 OpenAI 兼容的本地 HTTP 服务。

Windows 上双击 `setup.bat` 装好环境，再双击 `启动GUI.bat` 就能用。

## 模型类型

本项目支持三种官方模型，对应三种场景：

| 源模型 | 场景 |
| :--- | :--- |
| Qwen3-TTS-12Hz-1.7B-Base | 声音克隆 |
| Qwen3-TTS-12Hz-1.7B-CustomVoice | 内置音色 + 风格指令 |
| Qwen3-TTS-12Hz-1.7B-VoiceDesign | 用自然语言设计音色 |
| Qwen3-TTS-12Hz-0.6B-Base | 声音克隆 |
| Qwen3-TTS-12Hz-0.6B-CustomVoice | 内置音色 + 风格指令 |

你想用哪个，就导出哪个，但是需要先下载官方模型才能导出。

## 性能表现

在我的 RTX 5050 上的实测数据：

- **RTX 5050 (独显)**: RTF 0.35 (实时率，1秒音频只需0.35秒生成)
- **CPU**: RTF 1.3
- **集显**: RTF 1.3

RTF < 1 就表示生成速度比实时播放还快。没有独显的电脑，很难做到 RTF < 1，因此不太可能流畅地流式播放。

显存占用：

- **Encoder** 用于从音频提取特征克隆，无需显卡加速，可节省显存
- **Talker 1.7B**，用 Q5_k 量化，载入 955MB，上下文224MB，计算50MB，共1229MB
- **Predictor 0.1B**，用 Q8_0 量化，载入 144MB，上下文5MB，计算7MB，共156MB
- **Decoder** 用 fp16 量化，DML 加速，模型 237MB，推理204MB

使用 1.7B 总共需 1.8G 显存。

用 0.6B 版可以再省 500MB 显存，但对速度的提升不大，因为**计算瓶径在于 Predictor**，每一秒的音频需要自回归 12.5*15=187.5 次，0.6B 和 1.7B 的差异仅在于 Talker。

### 上下文长度估算

每路任务在 Talker 上下文里占用的 token 数可以这样估算：

- 每秒音频占 **12.5** 个音频 token（12Hz 帧率，12.5 帧/秒）
- 目标文本按每秒生成音频 **4** 个文本 token 折算（约 4 字/秒的语速，文本 token 随音频帧逐个注入）
- 再加约 **10** 个常数控制 token（角色头、语言、说话人嵌入、TTS_BOS 等）

克隆时参考音频同样占上下文（音频 12.5 token/秒，参考文本同样折算 4 token/秒），于是单路所需上下文只看**总音频秒数**（参考 + 生成）：

```
ctx ≈ 10 + 16.5 × 总音频秒数
```

例：每路 512 ctx 时，参考音频加生成音频合计最长 `(512 - 10) / 16.5 ≈ 30` 秒；Custom Voice / Voice Design 没有参考音频，全部上下文都留给生成。超出上下文会报 Talker context overflow，批量推理时 `n_ctx_per_seq` 按这个公式的上限取即可。

### 批量显存估算

批量推理（`BatchRunner`，CUDA）时显存分两块：

**常驻部分**（权重按文件大小计）：

| 组件 | 大小 |
| :--- | :--- |
| Talker 权重 (q5_k) | 960 MB |
| Predictor 权重 (q8_0) | 144 MB |
| Decoder chunk64 | 620 MB |

**批量部分**（每轮 `clone_batch` 创建、跑完即释放，随路数 B 线性增长）：

| 组件 | 大小 |
| :--- | :--- |
| Talker KV | 0.11 MB/token，即 0.11 MB × B × ctx |
| Predictor KV | 5 MB × B |
| 计算缓冲 | 50 MB + 2 MB × B |

合计估算：`总量 ≈ 1.78 GB + 0.11 MB × B × ctx`

例：32 路、每路 512 ctx ≈ 1.78 + 1.80 ≈ **3.6 GB**。（注意：上下文 512 只能容纳 30s 总音频时长）

批量仅对 LLM 部分有加速效果（读取瓶径），生成 Codes 后，音频解码器部分（计算瓶径）多路无加速效果。

实测，在 RTX5050 上，32路 ctx512 可以做到 RTF0.055（LLM 0.043 + Decoder 0.012）

## 项目特性

- **流式合成**：大幅缩短流式实际首音延迟，最低可至 300ms 内。
- **加速推理**：对 1.7B 模型，RTX5050 可以做到 RTF0.35，AMD 显卡也可以用 Vulkan 加速
- **确定性控制**：支持独立设置 Talker 和 Predictor 的随机种子，确保输出可复现。

## Clone 原理

声音克隆的本质是 **接续说话** (In-Context Learning)。

想象一下，你正在读一段话，读到一半时，我让你接着往下读，你自然会用同样的语气和声音。Qwen3-TTS 的克隆原理也是如此：

1. **文本拼接**：把「参考文本」和「目标文本」连接起来。
2. **注入记忆**：把「参考音频」转为 spk_emb 和 codes，注入记忆，让模型以为前面的音频是它自己刚说的：
   - **嗓子（spk_emb）**：整体音色特征，告诉模型我是用什么样的嗓子在说话。
   - **音节（codes）**：具体的发音码（12.5Hz），让模型认为「我刚才确实亲口说出了这些音节」。
3. **顺势说完**：有了之前的「嗓子」和音节记忆，模型就会顺理成章地继续保持这个声音，把剩下的文字接着读完。

## Custom Voice 原理

与克隆类似，只是模型内置了一些说话人音色（spk_embd），模型的记忆中只会有嗓子，没有音节。它要根据指令和目标文本，让自己处于某种情感状态（入戏），然后用嗓子音色把目标文本读出来。

有点像是读台词：

- Clone是读了一半（参考文本），然后接着读（目标文本）。
- Custom Voice 是还没有读，酝酿一下情感，从头开始读。

因此带来了不同的特点：

- Clone 因为已经读了一半，情感基调已定，音色就更稳定可控。
- Custom Voice 因为要酝酿情感，不同的随机种子，会酝酿出不同的基调，就会有些抽卡。

因此最佳的配音实践是：用 Custom Voice 对同一段文字抽卡出最好的效果，再用 Base 模型基于这个音频克隆阅读其它文本。

## 快速开始

### 一键部署（Windows）

环境、模型、运行库都不用手动折腾，双击即可：

| 文件 | 作用 |
| :--- | :--- |
| `setup.bat` | 体检 + 自动修复：Python 版本、`.venv`、依赖、llama.cpp 运行库、模型文件、FFmpeg、音色目录，缺什么装什么 |
| `启动GUI.bat` | 启动图形界面（启动前跑一次快速体检） |
| `启动服务.bat` | 只启 HTTP 服务，不开界面 |
| `克隆音色.bat` | 交互式克隆音色 |

只想看看环境有没有问题：

```bash
python install.py --check       # 完整体检
python install.py --check -q    # 只报问题
python install.py               # 体检 + 自动修复，加 --yes 免确认
```

体检输出长这样：

```
[ OK ] Python 版本    3.14.7
[ OK ] 虚拟环境 .venv  Python 3.14.7
[ OK ] Python 依赖     齐全，加速 DmlExecutionProvider
[ OK ] llama.cpp 运行库  qwen3_tts_gguf\inference\bin  共 94 MB
[ OK ] 模型文件 model-base  6 个文件齐全，2.3 GB
[ OK ] FFmpeg  7.1.1-essentials_build  C:\ffmpeg\bin\ffmpeg.EXE
[ OK ] 音色目录  9 个音色
```

#### 下载模型

- [Qwen3-TTS-12Hz-1.7B-Base](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-1.7B-Base)
- [Qwen3-TTS-12Hz-1.7B-CustomVoice](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- [Qwen3-TTS-12Hz-1.7B-VoiceDesign](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign)

- [Qwen3-TTS-12Hz-0.6B-Base](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-0.6B-Base)
- [Qwen3-TTS-12Hz-0.6B-CustomVoice](https://www.modelscope.cn/models/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice)

```
pip install modelscope
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-Base
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign

modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-Base
modelscope download --model Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice
```

#### 依赖环境

适配版本 **llama.cpp b10621**。从 [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) 下载预编译二进制，将 DLL 放入 `qwen3_tts_gguf/inference/bin/`（`setup.bat` 会自动下载并解压到这个位置）：

| 平台 | 下载文件 |
|------|----------|
| **Windows (Vulkan)** | `llama-b10621-bin-win-vulkan-x64.zip` |
| **Windows (CUDA)** | `llama-b10621-bin-win-cuda-13.3-x64.zip`（另需 CUDA 13 运行时 `cudart64_13.dll`、`cublas64_13.dll`） |

另外还需安装 FFmpeg，用于读取音频文件。

推荐用 [uv](https://docs.astral.sh/uv/) 安装依赖：

```
uv sync --extra dml
```

N 卡可换 `--extra gpu`；跑导出脚本再加 `--extra export`。不用 uv 则 `pip install -r requirements.txt`。

#### 配置路径

打开 `export_config.py`，在里面配置好模型的导出路径：


#### 阶段一：导出小组件

```bash
python 11-Export-Codec-Encoder.py    # 编码器，用于克隆
python 12-Export-Speaker-Encoder.py  # 说话人特征提取器
python 13-Export-Decoder.py          # 解码器，核心渲染器
python 14-Export-Embeddings.py       # Embedding 权重
python 15-Copy-Tokenizer.py          # 文本分词器
python 16-Quantize-ONNX-Models.py    # 重要：将 ONNX 转为 FP16 以供 DML 加速
```

#### 阶段二：导出大师（Talker）

大师是 1.42B 的 LLM backbone，负责理解文本、生成语音骨架：

```bash
python 21-Extract-Talker-Weights.py    # 拆分并初始化权重
python 22-Prepare-Talker-Tokenizer.py  # 构造 GGUF 所需的迷你词表
python 23-Convert-Talker-GGUF.py       # 转换为 F16 的 GGUF
python 24-Quantize-Talker-GGUF.py      # 量化为 q5_k，这是推理引擎默认加载的版本
```

#### 阶段三：导出工匠（Predictor）

工匠是 142M 的小模型，负责给骨架补充细节：

```bash
python 31-Extract-Predictor-Weights.py
python 32-Prepare-Predictor-Tokenizer.py
python 33-Convert-Predictor-GGUF.py
python 34-Quantize-Predictor-GGUF.py    # 量化为 q8_0，这是推理引擎默认加载的版本
```

导完之后，`EXPORT_DIR` 里就有你需要的所有文件了。

## 推理

### GUI 模式（推荐）

双击 `启动GUI.bat`，或：

```
python 52-GUI.py
```

七个标签页：

| 标签页 | 用途 |
| :--- | :--- |
| 克隆 | 用参考音频克隆音色，批量出 wav/json |
| 自定义音色 | 内置音色 + 风格指令 |
| 音色设计 | 用自然语言描述音色 |
| 服务 | 把引擎挂成本地 HTTP 服务，供其他程序调用 |
| 工具 | 音色向量重建、WAV ↔ JSON 互转 |
| 设置 | 单模型模式、界面语言 |
| 日志 | 运行日志 |

模型载入时可分别指定 LLM 设备（GPU/CPU）和 ONNX 组件设备（GPU/CPU），显存档位不够时把编码器丢给 CPU。

### 脚本模式

三个示例脚本，对应三种模型：

```bash
python 41-Inference-Custom.py  # 精品音色
python 42-Inference-Design.py  # 音色设计
python 43-Inference-Base.py    # 声音克隆
```

### 交互模式（推荐）

```bash
python 51-Interactive-Clone.py
```

启动后直接打字，边推边播。

## HTTP API 服务

GUI 的「服务」页可以把引擎挂成一个 **OpenAI 兼容**的本地 HTTP 服务，SillyTavern、Cherry Studio、Open WebUI、AnythingLLM 这类支持自定义 endpoint 的客户端直接填 `http://127.0.0.1:8899` 就能用。

不想开界面也可以单独跑：

```bash
启动服务.bat                                    # 默认 127.0.0.1:8899
python tts_server.py --host 0.0.0.0 --port 8899 --voice 巧克力
```

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
| `language` | `Chinese` | `Chinese` / `English` / `Japanese` / `Korean` / 各语种与方言 |
| `speed` | `1.0` | 语速倍率，1.25 表示快 25% |
| `temperature` | 服务默认 0.6 | 采样温度，越小越稳 |
| `seed` | 服务默认 42 | 随机种子，固定后输出可复现 |

引擎在第一次请求时才载入（DirectML 下约 3–6 秒），之后复用同一个 stream，因此连续请求不会反复初始化。合成是串行的，多个请求会排队。

### 客户端接入示例

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

# 初始化引擎（后台自动并行加载模型）
engine = TTSEngine(model_dir="model-base")
stream = engine.create_stream()

# 设置音色（支持 .wav 路径、.json 路径或 TTSResult 对象）
stream.set_voice("output/elaborate/sample.json")

# 配置推理参数
config = TTSConfig(
    temperature=0.8,      # 核心温度，控制随机性
    sub_temperature=0.8,  # 细节温度，控制随机性
    seed=42,           # 核心种子
    sub_seed=45,       # 细节种子
    streaming=True,    # 开启流式
)

# 流式合成
result = stream.clone("你好，世界！", config=config)
stream.join()  # 等待播完

# 保存结果
result.save("output/output.wav")
result.save("output/output.json")  # 保存 codes，下次可无损加载
```

## 可用说话人

CustomVoice 模型内置 9 个音色：

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

## 支持的语言

- chinese, english, japanese, korean
- german, spanish, french, russian, italian, portuguese
- beijing_dialect, sichuan_dialect

## 架构简述

用人体器官来理解：

1. **耳朵**（Encoder）: 听参考音频，提取音色特征
2. **大脑**（Talker）: 生成语音骨架 (28层, 1.42B)
3. **双手**（Predictor）: 补充细节 (8层, 142M)
4. **嘴巴**（Decoder）: 把 codes 解码成声音

推理引擎：
- Talker / Predictor: llama.cpp (GGUF格式，Vulkan/Cuda 加速)
- Encoder / Decoder: ONNX Runtime (ONNX格式，DirectML/Cuda 加速)

## 常见问题

**Q: 为什么不用官方 PyTorch？**

官方实现要大显存。llama.cpp 省资源，还能用 Vulkan/DML 加速。

**Q: 流式和离线有什么区别？**

流式边推边播，首包延迟低（~300ms）。

**Q: 服务起不来，提示端口被占用？**

换一个端口，或者先关掉占用 8899 的进程。Windows 上可以用 `netstat -ano | findstr :8899` 找到 PID。

**Q: 客户端连上了但一直转圈？**

引擎是懒加载的，第一次请求要等模型载入（DirectML 下 3–6 秒）。先 `curl http://127.0.0.1:8899/health` 看 `engine` 是否为 `true`。

**Q: 怎么调质量？**

`TTSConfig(temperature=0.8, sub_temperature=0.8, seed=42, sub_seed=45)` 温度控制随机性，用种子控制稳定复现。

## 相关链接

- [上游项目：HaujetZhao/Qwen3-TTS-GGUF](https://github.com/HaujetZhao/Qwen3-TTS-GGUF)
- [Qwen3-TTS 技术报告](./Qwen3-TTS%20Technical%20Report.md)
- [llama.cpp](https://github.com/ggerganov/llama.cpp)
