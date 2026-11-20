# Qwen3-TTS GGUF

[中文](readme.md)

Qwen3-TTS running on llama.cpp, with streaming synthesis and voice cloning, plus a graphical interface and an OpenAI-compatible local HTTP server.

Built on [HaujetZhao/Qwen3-TTS-GGUF](https://github.com/HaujetZhao/Qwen3-TTS-GGUF) (MIT). This version adds a graphical interface, an OpenAI-compatible HTTP server and a one-click installer on top of the upstream project.

Three steps: run `setup.bat` to prepare the environment → get a `model-base` directory → run `启动GUI.bat`.

## Contents

- [What this version adds](#what-this-version-adds)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Models](#models)
- [Inference](#inference)
- [HTTP API](#http-api)
- [Code usage](#code-usage)
- [Performance and VRAM](#performance-and-vram)
- [Exporting models](#exporting-models)
- [How it works](#how-it-works)
- [FAQ](#faq)

## What this version adds

Changes on top of upstream:

- **GUI** (`52-GUI.py`): clone / custom voice / voice design / server / tools / settings / log — seven tabs, no code editing required.
- **OpenAI-compatible HTTP server** (`tts_server.py`): `/v1/audio/speech`, `/v1/voices`; point SillyTavern, Cherry Studio, Open WebUI or any custom endpoint at it.
- **One-click install and health check** (`install.py` + `setup.bat`): checks Python version, venv, dependencies, llama.cpp runtime, models, FFmpeg and the voice folder, and installs what's missing.
- **Chinese docs and launchers**: `启动GUI.bat` / `启动服务.bat` / `克隆音色.bat`.

Capabilities inherited from upstream:

- **Streaming synthesis**: play while generating, first audio in as little as 300 ms.
- **Acceleration**: Talker / Predictor on llama.cpp (Vulkan or CUDA), Encoder / Decoder on ONNX Runtime (DirectML or CUDA).
- **Deterministic control**: separate seeds for Talker and Predictor, reproducible output.

## Requirements

| Item | Requirement |
| :--- | :--- |
| OS | Windows 10/11 x64 (on Linux bring your own llama.cpp and FFmpeg) |
| Python | **3.14** (`pyproject.toml` declares `>=3.14`) |
| GPU | Dedicated GPU recommended. NVIDIA: CUDA or Vulkan; AMD / Intel: Vulkan; CPU-only works but RTF > 1 |
| VRAM | ~**1.8 GB** for the full 1.7B set; the 0.6B saves another ~500 MB |
| Disk | ~**1.5 GB** of models, ~94 MB llama.cpp runtime, ~3.4 GB venv |
| Other | FFmpeg (installed automatically by `setup.bat`) |

`setup.bat` handles Python dependencies, the llama.cpp runtime and FFmpeg. Only the model is up to you — see [Models](#models).

### Measured on this machine

Every number below comes from real runs on this laptop:

| Item | Spec |
| :--- | :--- |
| CPU | AMD Ryzen 9 7845HX |
| GPU | NVIDIA RTX 4060 Laptop, 8 GB VRAM |
| RAM | 32 GB |
| OS | Windows 11 |

13.76 seconds of Chinese speech, 1.7B model, voice cloning, ONNX on CUDA:

```
Perf report (audio length: 13.76s)
  1. Prompt:    0.03s
  2. Prefill:   0.04s
  3. Generate:  4.74s (Talker: 1.25s, Predictor: 3.49s)
  4. Decode:    5.15s
  5. Latency:   0.72s
Core total: 4.80s | RTF (Core): 0.35
```

RTF 0.35 means one second of audio takes 0.35 s to generate — about 3× faster than real time, so streaming playback never starves. VRAM usage sits around 1.8 GB, comfortable on an 8 GB card.

## Quick start

### 1. Prepare the environment

Double-click `setup.bat`. It checks the Python version, creates `.venv`, installs dependencies, downloads the llama.cpp runtime and FFmpeg, then prints a health report:

```
[ OK ] Python version    3.14.7
[ OK ] venv .venv        Python 3.14.7
[ OK ] Python packages   complete, accelerator DmlExecutionProvider
[ OK ] llama.cpp runtime qwen3_tts_gguf\inference\bin  94 MB
[ FAIL ] Model model-base  directory missing
[ OK ] FFmpeg  7.1.1-essentials_build  C:\ffmpeg\bin\ffmpeg.EXE
[ OK ] Voice folder  9 voices
```

On the first run usually only the model line is red — that is expected, the next step fixes it.

Check only, without changing anything:

```bash
python install.py --check       # full check
python install.py --check -q    # problems only
python install.py               # check + fix, add --yes to skip prompts
```

### 2. Get a model

Inference needs a `model-base` directory in the project root, containing the exported GGUF and ONNX files. Pick one of three paths:

**A. Export it yourself**

Double-click `export-model.bat` and let it do the work: locate the source model (downloading it if missing), verify dependencies, run all fourteen scripts in order, check the output, and offer to delete the intermediates. Prefer manual control over quantization or layout? Follow the steps in [Exporting models](#exporting-models) one by one.

**B. Copy an existing `model-base` directory**

Fastest. Ask someone who already exported it, drop the whole folder into the project root, and `install.py` will pick it up.

**C. Download from ModelScope, then export**

Official model pages:

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

Files land in `~/.cache/modelscope/hub/models/Qwen` by default, which the export scripts detect automatically. Anywhere else: set `QWEN_MODEL_HOME` (see [Exporting models](#exporting-models)).

### 3. Launch

| File | Purpose |
| :--- | :--- |
| `启动GUI.bat` | GUI (runs a quick health check first) |
| `启动服务.bat` | HTTP server only, no UI, defaults to `127.0.0.1:8899` |
| `克隆音色.bat` | Interactive voice cloning with live playback |

Equivalent commands:

```bash
python 52-GUI.py                       # GUI
python tts_server.py --port 8899       # HTTP server
python 51-Interactive-Clone.py         # interactive cloning
```

Cloned voice files (`output/elaborate/*.json` plus reference audio) are personal voice biometrics, so they are not shipped in the repo — run the cloning step once after setup.

### Manual setup (no bat files)

**Dependencies**

```bash
uv sync --extra dml      # DirectML — AMD / Intel / NVIDIA
uv sync --extra gpu      # CUDA — NVIDIA, faster
```

Add `--extra export` for the export scripts. Without uv, use `pip install -r requirements.txt`.

**llama.cpp runtime**

Pinned to **b10621**. Grab a prebuilt package from [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) and put the DLLs in `qwen3_tts_gguf/inference/bin/`:

| Platform | File |
| :--- | :--- |
| Windows (Vulkan) | `llama-b10621-bin-win-vulkan-x64.zip` |
| Windows (CUDA) | `llama-b10621-bin-win-cuda-13.3-x64.zip` (also needs `cudart64_13.dll`, `cublas64_13.dll`) |

Don't want to pick by hand? Double-click `setup.bat`: it detects your GPU and driver first — NVIDIA on driver 580+ gets CUDA 13.3, 550+ gets CUDA 12.4; AMD / Intel / iGPU gets the Vulkan build. If no CUDA runtime is present it fetches `cudart` too.

**FFmpeg**

Used for reading and transcoding audio; make sure `ffmpeg` is on `PATH`.

## Models

### Supported models

Five official models, three use cases:

| Source model | Use case | Output directory |
| :--- | :--- | :--- |
| Qwen3-TTS-12Hz-1.7B-Base | Voice cloning | `model-base` |
| Qwen3-TTS-12Hz-1.7B-CustomVoice | Built-in voices + style prompt | `model-custom` |
| Qwen3-TTS-12Hz-1.7B-VoiceDesign | Describe a voice in natural language | `model-design` |
| Qwen3-TTS-12Hz-0.6B-Base | Voice cloning, less VRAM | `model-base-small` |
| Qwen3-TTS-12Hz-0.6B-CustomVoice | Built-in voices, less VRAM | `model-custom-small` |

Export only what you need. The 0.6B saves ~500 MB of VRAM but barely changes speed — **the bottleneck is the Predictor**, which autoregresses 12.5×15 = 187.5 steps per second of audio; 0.6B and 1.7B differ only in the Talker.

### Built-in voices

CustomVoice ships nine voices:

| ID | Description |
| :--- | :--- |
| vivian | Young female, bright and crisp |
| serena | Warm female, soft and friendly |
| uncle_fu | Mature male, deep and steady |
| dylan | Beijing male, natural and clear |
| eric | Chengdu male, slightly husky |
| ryan | Energetic male, rhythmic |
| aiden | Sunny male, clear midrange |
| ono_anna | Japanese female, playful |
| sohee | Korean female, warm and emotive |

### Languages

chinese, english, japanese, korean, german, spanish, french, russian, italian, portuguese, beijing_dialect, sichuan_dialect.

## Inference

### GUI (recommended)

Double-click `启动GUI.bat`, or run `python 52-GUI.py`.

| Tab | Purpose |
| :--- | :--- |
| Clone | Clone a voice from reference audio, batch out wav/json |
| Custom voice | Built-in voices + style prompt |
| Voice design | Describe a voice in natural language |
| Server | Serve the engine over local HTTP for other apps |
| Tools | Voice embedding rebuild, WAV ↔ JSON conversion |
| Settings | Single-model mode, UI language |
| Log | Runtime log |

At load time you can pick the LLM device (GPU/CPU) and the ONNX device (GPU/CPU) separately. Short on VRAM? Move the encoder to CPU — it only extracts features.

### Scripts

Three examples, one per model type:

```bash
python 41-Inference-Custom.py  # built-in voices
python 42-Inference-Design.py  # voice design
python 43-Inference-Base.py    # voice cloning
```

### Interactive mode

```bash
python 51-Interactive-Clone.py
```

Type and it speaks as it generates — handy for tuning a voice.

## HTTP API

The **Server** tab turns the engine into an **OpenAI-compatible** local HTTP service. Clients that accept a custom endpoint — SillyTavern, Cherry Studio, Open WebUI, AnythingLLM — just use `http://127.0.0.1:8899`.

Headless alternative:

```bash
启动服务.bat                                    # 127.0.0.1:8899
python tts_server.py --host 0.0.0.0 --port 8899 --voice 巧克力
```

`--host 0.0.0.0` exposes the service to your LAN with no authentication — trusted networks only.

### Endpoints

| Method | Path | Description |
| :--- | :--- | :--- |
| `POST` | `/v1/audio/speech` | Synthesize speech, returns audio bytes |
| `GET` | `/v1/voices` | List available voices (json / wav in the voice folder) |
| `GET` | `/v1/models` | OpenAI model list, one local model |
| `GET` | `/health` | Health check: engine ready, current voice |

### Synthesis request

```bash
curl http://127.0.0.1:8899/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Hello there.","voice":"巧克力","response_format":"mp3"}' \
  --output hello.mp3
```

| Field | Default | Description |
| :--- | :--- | :--- |
| `input` | required | Text to synthesize (also accepts `text`) |
| `voice` | server default | Voice name without extension, looked up in the voice folder |
| `response_format` | `mp3` | `mp3` / `wav` / `flac` / `opus` / `aac` / `pcm`; non-wav goes through FFmpeg |
| `language` | `Chinese` | See [Languages](#languages) |
| `speed` | `1.0` | Speed multiplier, 1.25 = 25% faster |
| `temperature` | 0.6 | Sampling temperature, lower is steadier |
| `seed` | 42 | Random seed, fixed value reproduces output |

The engine loads lazily on the first request (3–6 s with DirectML) and reuses the same stream afterwards, so consecutive requests don't re-initialize. Synthesis is serial; concurrent requests queue up.

### Client example

Point the OpenAI SDK at a different base_url:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8899/v1", api_key="not-needed")
audio = client.audio.speech.create(
    model="qwen3-tts-gguf",
    voice="myvoice",  # replace with your own cloned voice name
    input="What's for dinner?",
    response_format="mp3",
)
audio.stream_to_file("hello.mp3")
```

## Code usage

```python
from qwen3_tts_gguf import TTSEngine, TTSConfig

# Initialize (loads models in parallel in the background)
engine = TTSEngine(model_dir="model-base")
stream = engine.create_stream()

# Set a voice (.wav path, .json path or TTSResult object)
stream.set_voice("output/elaborate/myvoice.json")  # generate it yourself first

# Configure inference
config = TTSConfig(
    temperature=0.8,      # core temperature
    sub_temperature=0.8,  # detail temperature
    seed=42,              # core seed
    sub_seed=45,          # detail seed
    streaming=True,       # enable streaming
)

# Synthesize
result = stream.clone("Hello, world!", config=config)
stream.join()             # wait for playback

# Save
result.save("output/output.wav")
result.save("output/output.json")  # audio codes, lossless reload
```

## Performance and VRAM

### Speed

RTF < 1 means generation outpaces real-time playback.

| Device | RTF | Note |
| :--- | :--- | :--- |
| RTX 4060 Laptop 8G + CUDA | 0.35 | measured here, see [Measured on this machine](#measured-on-this-machine) |
| RTX 5050 | 0.35 | upstream author's measurement |
| CPU only | 1.3 | can't keep up with playback |
| Integrated GPU | 1.3 | same |

Machines without a dedicated GPU rarely reach RTF < 1, and streaming playback will stutter. Batch inference is the exception — see below.

### VRAM usage

Full 1.7B set:

| Component | Quantization | Usage |
| :--- | :--- | :--- |
| Encoder | fp16 ONNX | can run on CPU, no VRAM |
| Talker 1.7B | Q5_K | 955 MB weights + 224 MB context + 50 MB compute ≈ 1229 MB |
| Predictor 0.1B | Q8_0 | 144 MB + 5 MB + 7 MB ≈ 156 MB |
| Decoder | fp16 ONNX | 237 MB model + 204 MB inference |
| **Total** | | **~1.8 GB** |

Moving the encoder to CPU frees about 120 MB.

### Context length

Tokens per task in the Talker context:

- **12.5** audio tokens per second (12 Hz frame rate)
- Text at **4** tokens per second of audio (~4 characters/s, injected frame by frame)
- ~**10** constant control tokens (role header, language, speaker embedding, TTS_BOS, …)

During cloning the reference audio also occupies context (12.5 tokens/s audio, 4 tokens/s reference text), so the per-task context depends only on **total audio seconds** (reference + generated):

```
ctx ≈ 10 + 16.5 × total audio seconds
```

Example: at 512 ctx per task, reference plus generated can reach `(512 - 10) / 16.5 ≈ 30` seconds. Custom Voice / Voice Design have no reference audio, so the whole context is available for generation. Exceeding it raises Talker context overflow; for batch inference set `n_ctx_per_seq` from this formula.

### Batch VRAM

Batch inference (`BatchRunner`, CUDA) uses two parts:

**Resident** (by file size):

| Component | Size |
| :--- | :--- |
| Talker weights (Q5_K) | 960 MB |
| Predictor weights (Q8_0) | 144 MB |
| Decoder chunk64 | 620 MB |

**Batch part** (created per `clone_batch`, freed after, grows with batch size B):

| Component | Size |
| :--- | :--- |
| Talker KV | 0.11 MB/token, i.e. 0.11 MB × B × ctx |
| Predictor KV | 5 MB × B |
| Compute buffers | 50 MB + 2 MB × B |

Total: `≈ 1.78 GB + 0.11 MB × B × ctx`

Example: 32 streams at 512 ctx ≈ 1.78 + 1.80 ≈ **3.6 GB** (512 ctx holds only 30 s of total audio).

Batching only accelerates the LLM part (bandwidth bound); decoding the generated codes is compute bound and doesn't scale with more streams. Measured on an RTX 5050, 32 streams at ctx512 reach RTF 0.055 (LLM 0.043 + Decoder 0.012).

## Exporting models

Only needed if you take the "export it yourself" path.

### One command

```bash
python export_model.py                 # interactive picker, fully automatic
python export_model.py -m custom       # skip the menu
python export_model.py -m base --out D:\exp\model-base   # custom target
python export_model.py -m base --only 21,22,23,24          # rerun a few steps
```

Double-clicking `export-model.bat` does the same on Windows. It checks the source model (downloading it via modelscope when missing), export dependencies (`uv sync --extra export`), `llama-quantize.exe` (from `setup.bat`), and free disk space (8–10 GB of scratch). Afterwards it verifies the six core files plus `embeddings/`.

Measured: with dependencies and source model in place, 1.7B-Base exports in 2.6 minutes and matches a hand-run export byte-for-byte. Intermediates (`*_hf/`, `*.f16.gguf`, `*.fp32.onnx` with external data, `*.int8.onnx`) take about 6 GB and are cleaned on request.

### Step by step

What the one-command path does, if you'd rather drive it yourself.

### Paths

`export_config.py` decides where official models are read from and where exports go. The source is probed in this order:

1. Environment variable `QWEN_MODEL_HOME`
2. `D:\qwen3-tts\models`
3. `~/.cache/modelscope/hub/models/Qwen`

Set it explicitly when needed:

```batch
set QWEN_MODEL_HOME=E:\models\Qwen
```

Output always goes to `model-base` / `model-custom` / `model-design` / `model-base-small` / `model-custom-small` in the project root. Switch the default target with the line `model = Models.base`.

### Stage 1: small components

```bash
python 11-Export-Codec-Encoder.py    # codec encoder for cloning
python 12-Export-Speaker-Encoder.py  # speaker embedding extractor
python 13-Export-Decoder.py          # decoder, the core renderer
python 14-Export-Embeddings.py       # embedding weights
python 15-Copy-Tokenizer.py          # text tokenizer
python 16-Quantize-ONNX-Models.py    # critical: FP16 ONNX for DML acceleration
```

### Stage 2: Talker

The Talker is the 1.42B LLM backbone that reads text and produces the speech skeleton:

```bash
python 21-Extract-Talker-Weights.py    # split and initialize weights
python 22-Prepare-Talker-Tokenizer.py  # build the mini vocab GGUF needs
python 23-Convert-Talker-GGUF.py       # convert to F16 GGUF
python 24-Quantize-Talker-GGUF.py      # quantize to Q5_K (default at inference)
```

### Stage 3: Predictor

The 142M Predictor fills in the detail:

```bash
python 31-Extract-Predictor-Weights.py
python 32-Prepare-Predictor-Tokenizer.py
python 33-Convert-Predictor-GGUF.py
python 34-Quantize-Predictor-GGUF.py   # quantize to Q8_0 (default at inference)
```

Afterwards `model-base` holds 6 files and about 1.5 GB. Export gotchas we hit are written up in [Experience](./Experience).

## How it works

### Architecture

Think of it as body parts:

1. **Ears** (Encoder): listen to reference audio, extract timbre
2. **Brain** (Talker): generate the speech skeleton (28 layers, 1.42B)
3. **Hands** (Predictor): fill in detail (8 layers, 142M)
4. **Mouth** (Decoder): turn codes into sound

Engines: Talker / Predictor on llama.cpp (GGUF, Vulkan / CUDA), Encoder / Decoder on ONNX Runtime (ONNX, DirectML / CUDA).

### Voice cloning

Cloning is **continuation**, an in-context task.

Imagine reading a passage: halfway through, someone asks you to keep going — you'd continue in the same voice and tone. Qwen3-TTS does the same:

1. **Concatenate text**: reference transcript followed by target text.
2. **Inject memory**: encode the reference audio into spk_emb and codes, making the model believe it just said that.
   - **Timbre** (spk_emb): what the voice sounds like.
   - **Syllables** (codes): the actual pronunciation codes at 12.5 Hz, so the model believes "I really said these syllables".
3. **Continue**: with timbre and syllable memory in place, it finishes the rest in that voice.

### Built-in voices

Similar, but the speaker embedding comes from a preset voice — memory holds the timbre only, no syllables. The model has to get into an emotional state from the prompt, then read the text.

- Clone: half read, continue.
- Custom Voice: nothing read yet, get into character, start from the top.

So cloning keeps a stable emotional baseline, while Custom Voice varies with each seed — worth rolling several takes. Best practice: roll Custom Voice takes until one sounds right, then clone other text from that audio with the Base model.

## FAQ

**Q: `setup.bat` says the `model-base` directory is missing.**

Expected — models aren't part of the automatic install. See [Get a model](#2-get-a-model); copying a `model-base` folder into the project root is enough.

**Q: Why not the official PyTorch implementation?**

It's VRAM hungry. llama.cpp is lean and can use Vulkan / DML, so an 8 GB card is plenty.

**Q: What's the difference between streaming and offline?**

Streaming plays while generating, first audio in ~300 ms; offline waits for the whole utterance.

**Q: The server won't start — port already in use?**

Pick another port or free 8899: `netstat -ano | findstr :8899`.

**Q: The client connects but spins forever?**

The engine loads lazily; the first request waits 3–6 s (DirectML). Check `curl http://127.0.0.1:8899/health` and look at `engine`.

**Q: Not enough VRAM?**

Three moves: encoder on CPU (−120 MB), switch to 0.6B (−500 MB), shorten the reference audio and `max_steps` (context ≈ `10 + 16.5 × audio seconds`).

**Q: How do I tune quality?**

`TTSConfig(temperature=0.8, sub_temperature=0.8, seed=42, sub_seed=45)`. Temperature adds randomness, seeds make it reproducible. For a stable voice, fix the seed and pick the best take.

## Links

- [Upstream: HaujetZhao/Qwen3-TTS-GGUF](https://github.com/HaujetZhao/Qwen3-TTS-GGUF)
- [Qwen3-TTS Technical Report](./Qwen3-TTS%20Technical%20Report.md)
- [Export notes](./Experience)
- [llama.cpp](https://github.com/ggerganov/llama.cpp)
- [License (MIT)](./LICENSE)
