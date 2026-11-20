#!/usr/bin/env python
"""Qwen3-TTS GGUF 环境体检 / 安装助手

用法:
    python install.py              体检 + 自动修复（交互）
    python install.py --check      只体检，不修改任何东西
    python install.py --check -q   静默体检，供 启动GUI.bat 调用

只依赖标准库，本脚本自己可以在任意 Python 3.8+ 下运行，
不需要先进 .venv。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- 常量

PY_MIN = (3, 14)                     # pyproject: requires-python >= 3.14
LLAMA_TAG = "b10621"
LLAMA_REL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}"

# 后端 -> (包名后缀, 显示名, 约多少 MB)；按显卡自动挑一个
LLAMA_BACKENDS = {
    "vulkan": ("bin-win-vulkan-x64.zip", "Vulkan", 33),
    "cuda-12.4": ("bin-win-cuda-12.4-x64.zip", "CUDA 12.4", 239),
    "cuda-13.3": ("bin-win-cuda-13.3-x64.zip", "CUDA 13.3", 140),
}
# CUDA 包不自带 cublas/cudart，本机没装 CUDA 运行时才补这个
LLAMA_CUDART = {
    "cuda-12.4": ("cudart-llama-bin-win-cuda-12.4-x64.zip", 373),
    "cuda-13.3": ("cudart-llama-bin-win-cuda-13.3-x64.zip", 373),
}

LLAMA_DIR = ROOT / "qwen3_tts_gguf" / "inference" / "bin"
LLAMA_FILES = ["llama.dll", "ggml.dll", "llama-server.exe"]

# N 卡 ONNX 加速方案：onnxruntime-gpu 的 Windows 包不捆绑 cuBLAS/cuDNN/cuFFT，
# 全部靠 pip 的 nvidia-* wheel 提供，用户不需要装 CUDA Toolkit。
# 版本要点：onnxruntime-gpu 1.25.x 认 CUDA 12.x；1.29 起硬绑 CUDA 13.x，
# 而 PyPI 上没有 cu13 的 cuDNN wheel，所以这里钉 1.25。
ORT_CUDA_SPEC = "onnxruntime-gpu>=1.25.0,<1.26"
ONNX_CUDA_WHEELS = [
    "nvidia-cublas-cu12",
    "nvidia-cudnn-cu12",
    "nvidia-cufft-cu12",
    "nvidia-curand-cu12",
    "nvidia-cuda-runtime-cu12",
    "nvidia-cuda-nvrtc-cu12",
]
# CUDA EP 运行时会按需加载这几个 dll，缺一个就静默退回 CPU
ONNX_CUDA_DLLS = ("cublaslt64", "cudnn64", "cufft64")

# 默认（Vulkan）包，hint 文案里引用
LLAMA_ZIP = f"llama-{LLAMA_TAG}-{LLAMA_BACKENDS['vulkan'][0]}"
LLAMA_URL = f"{LLAMA_REL}/{LLAMA_ZIP}"

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_DIR = ROOT / "vendor" / "ffmpeg"

MODEL_DIR = ROOT / "model-base"
MODEL_FILES = [
    "qwen3_tts_codec_encoder.fp16.onnx",
    "qwen3_tts_decoder.fp16.onnx",
    "qwen3_tts_speaker_encoder.fp16.onnx",
    "qwen3_tts_predictor.q8_0.gguf",
    "qwen3_tts_talker.q5_k.gguf",
    "tokenizer.json",
]

# import 名 -> pip 包名（诊断提示用）
PY_MODULES = {
    "numpy": "numpy",
    "scipy": "scipy",
    "soundfile": "soundfile",
    "sounddevice": "sounddevice",
    "tokenizers": "tokenizers",
    "gguf": "gguf",
    "ttkbootstrap": "ttkbootstrap",
    "windnd": "windnd",
    "onnxruntime": "onnxruntime-directml",
}

PIP_MIRROR = "https://mirrors.aliyun.com/pypi/simple/"

# ---------------------------------------------------------------- 输出


class C:
    """ANSI 颜色；Windows 终端不支持时自动降级为空串。"""

    _on = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    if _on and platform.system() == "Windows":
        try:
            import ctypes

            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:  # noqa: BLE001
            _on = False

    @classmethod
    def w(cls, code: str) -> str:
        return code if cls._on else ""

    @classmethod
    def ok(cls, s):
        return f"{cls.w(chr(27) + '[32m')}{s}{cls.w(chr(27) + '[0m')}"

    @classmethod
    def warn(cls, s):
        return f"{cls.w(chr(27) + '[33m')}{s}{cls.w(chr(27) + '[0m')}"

    @classmethod
    def err(cls, s):
        return f"{cls.w(chr(27) + '[31m')}{s}{cls.w(chr(27) + '[0m')}"

    @classmethod
    def dim(cls, s):
        return f"{cls.w(chr(27) + '[90m')}{s}{cls.w(chr(27) + '[0m')}"

    @classmethod
    def bold(cls, s):
        return f"{cls.w(chr(27) + '[1m')}{s}{cls.w(chr(27) + '[0m')}"


OK, WARN, FAIL = "OK", "WARN", "FAIL"


def _fix_console():
    """Windows 控制台切 UTF-8，避免中文/emoji 触发 GBK 编码异常。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def say(msg=""):
    print(msg, flush=True)


def section(title):
    say()
    say(C.bold(f"── {title} " + "─" * max(0, 58 - len(title))))


# ---------------------------------------------------------------- 检查项


class Result:
    def __init__(self, key, level, title, detail="", hint=""):
        self.key = key
        self.level = level
        self.title = title
        self.detail = detail
        self.hint = hint

    @property
    def failed(self):
        return self.level == FAIL


def run(cmd, **kw):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=kw.pop("timeout", 600), **kw,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None


def venv_python() -> Path:
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# ---------------------------------------------------------------- 设备探测

_GPU = None


def _ps(cmd, timeout=20):
    r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], timeout=timeout)
    return r.stdout.strip() if r and r.returncode == 0 else ""


def has_cuda_runtime() -> bool:
    """本机是否已有 cublas 运行库（系统 CUDA、System32 或 pip 的 nvidia wheel）。"""
    if os.environ.get("CUDA_PATH"):
        return True
    names = ("cublas64_13.dll", "cublas64_12.dll", "cublasLt64_13.dll", "cublasLt64_12.dll")
    if any(shutil.which(n) for n in names):
        return True
    sysdir = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32"
    if any((sysdir / n).exists() for n in names):
        return True
    # pip 装的 nvidia-*-cu12 wheel（本项目 CUDA 方案默认走这条）
    py = venv_python()
    if py.exists():
        nv = py.parent.parent / "Lib" / "site-packages" / "nvidia"
        if nv.is_dir() and any(p.name.lower().startswith("cublaslt64")
                               for b in nv.glob("*/bin") for p in b.glob("*.dll")):
            return True
    return False


def detect_gpu():
    """探测显卡和驱动，决定装哪个 llama.cpp 后端。

    返回 {"vendor","name","driver","backend","reason"}，
    backend 取 vulkan / cuda-12.4 / cuda-13.3。结果会缓存，探测失败一律退回 Vulkan。
    """
    global _GPU
    if _GPU is not None:
        return _GPU

    info = {"vendor": "unknown", "name": "", "driver": "", "backend": "vulkan", "reason": ""}

    # 1) nvidia-smi 最准：卡名和驱动版本一次拿全
    smi = shutil.which("nvidia-smi")
    if not smi:
        cand = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "nvidia-smi.exe"
        smi = str(cand) if cand.exists() else None
    if smi:
        r = run([smi, "--query-gpu=name,driver_version", "--format=csv,noheader"], timeout=20)
        if r and r.returncode == 0 and r.stdout.strip():
            line = r.stdout.strip().splitlines()[0]
            name, _, drv = (x.strip() for x in line.partition(","))
            info.update(vendor="nvidia", name=name, driver=drv)
            m = re.match(r"(\d+)", drv)
            major = int(m.group(1)) if m else 0
            if major >= 580:
                info.update(backend="cuda-13.3", reason="N 卡 + 驱动 580 及以上")
            elif major >= 550:
                info.update(backend="cuda-12.4", reason="N 卡 + 驱动 550 及以上")
            else:
                info["reason"] = "N 卡但驱动偏旧，退回 Vulkan"
            _GPU = info
            return info

    # 2) 退回 WMI 列显卡名
    names = _ps("(Get-CimInstance Win32_VideoController).Name -join '|'")
    names = [n.strip() for n in names.split("|") if n.strip()]
    # 展示时优先挑真卡，别把串流/虚拟显示器当成显卡
    real = [n for n in names
            if not re.search(r"virtual|basic display|remote|parsec|gameviewer|idd", n, re.I)]
    info["name"] = (real or names or [""])[0]
    low = " ".join(names).lower()
    if "nvidia" in low:
        info.update(vendor="nvidia", backend="cuda-12.4",
                    reason="识别到 N 卡，取不到驱动版本，按 CUDA 12.4 装")
    elif "amd" in low or "radeon" in low:
        info.update(vendor="amd", reason="A 卡走 Vulkan + DirectML")
    elif "intel" in low or "arc" in low:
        info.update(vendor="intel", reason="I 卡走 Vulkan + DirectML")
    else:
        info["reason"] = "没识别到独显，用通用的 Vulkan"
    _GPU = info
    return info


def bin_backend() -> str:
    """看 bin 里现在装的是哪个后端。"""
    if (LLAMA_DIR / "ggml-cuda.dll").exists():
        return "cuda"
    if (LLAMA_DIR / "ggml-vulkan.dll").exists():
        return "vulkan"
    return ""


def check_python():
    """系统 Python 只负责跑本脚本；真正干活的是 .venv 里的解释器。"""
    ver = sys.version_info
    got = f"{ver.major}.{ver.minor}.{ver.micro}"

    # .venv 已达标就以它为准，系统 Python 旧一点不影响使用
    venv_ver = ""
    py = venv_python()
    if py.exists():
        r = run([str(py), "-V"], timeout=60)
        if r and r.returncode == 0:
            txt = (r.stdout or r.stderr or "").strip()
            m = re.search(r"(\d+)\.(\d+)", txt)
            if m:
                venv_ver = txt.replace("Python ", "")
                if (int(m.group(1)), int(m.group(2))) >= PY_MIN:
                    return Result("python", OK, "Python 版本", f"系统 {got}，.venv {venv_ver}")

    if (ver.major, ver.minor) >= PY_MIN:
        return Result("python", OK, "Python 版本", f"{got} ({sys.executable})")

    need = f"{PY_MIN[0]}.{PY_MIN[1]}"
    if venv_ver:
        hint = (f".venv 里是 {venv_ver}，删掉 .venv 后重跑本脚本即可重建"
                f"（用 uv 的话它会自己下 Python {need}）")
    else:
        hint = (f"装 Python {need} 后重跑本脚本：https://www.python.org/downloads/"
                f"（用 uv 的话也可以 uv python install {need}）")
    return Result("python", WARN, "Python 版本",
                  f"{got} 低于项目要求 {need}，且没有可用的解释器", hint)


def check_venv():
    py = venv_python()
    if not py.exists():
        return Result("venv", FAIL, "虚拟环境 .venv", "不存在", "运行本脚本（不带 --check）自动创建")
    r = run([str(py), "-V"])
    if r is None or r.returncode != 0:
        return Result("venv", FAIL, "虚拟环境 .venv", "存在但无法运行", "删掉 .venv 后重跑本脚本")
    return Result("venv", OK, "虚拟环境 .venv", r.stdout.strip() or r.stderr.strip())


def check_packages():
    py = venv_python()
    if not py.exists():
        return Result("packages", FAIL, "Python 依赖", "跳过（无 .venv）", "先创建虚拟环境")
    code = (
        "import importlib,json,sys\n"
        f"mods={list(PY_MODULES)!r}\n"
        "bad=[]\n"
        "for m in mods:\n"
        "    try: importlib.import_module(m)\n"
        "    except Exception: bad.append(m)\n"
        "prov=[]\n"
        "try:\n"
        "    import onnxruntime as o; prov=o.get_available_providers()\n"
        "except Exception: pass\n"
        "print(json.dumps({'bad':bad,'prov':prov}))\n"
    )
    r = run([str(py), "-c", code])
    if r is None or r.returncode != 0:
        return Result("packages", FAIL, "Python 依赖", "探测失败", (r.stderr if r else "")[-300:])
    info = json.loads(r.stdout.strip().splitlines()[-1])
    bad = info["bad"]
    if bad:
        pkgs = ", ".join(PY_MODULES[m] for m in bad)
        return Result("packages", FAIL, "Python 依赖", f"缺 {len(bad)} 个：{pkgs}",
                      "运行本脚本自动安装")
    prov = info["prov"]
    accel = [p for p in prov if p in ("DmlExecutionProvider", "CUDAExecutionProvider")]
    if accel:
        return Result("packages", OK, "Python 依赖", f"齐全，加速 {', '.join(accel)}")
    return Result("packages", OK, "Python 依赖", "齐全（ONNX 加速见下一项）")


def check_onnx_cuda():
    """检查 onnxruntime 的 CUDA 后端是否真的能用（providers 有名字 ≠ dll 能加载）。"""
    py = venv_python()
    if not py.exists():
        return Result("onnx-cuda", OK, "ONNX 加速后端", "跳过（无 .venv）")

    code = (
        "import json,os,sys\n"
        "sp=os.path.join(sys.prefix,'Lib','site-packages')\n"
        "nv=os.path.join(sp,'nvidia')\n"
        "dll=set()\n"
        "if os.path.isdir(nv):\n"
        "    for d in os.listdir(nv):\n"
        "        b=os.path.join(nv,d,'bin')\n"
        "        if os.path.isdir(b):\n"
        "            dll|={f.lower() for f in os.listdir(b)}\n"
        "prov=[];ver=''\n"
        "try:\n"
        "    import onnxruntime as o;prov=list(o.get_available_providers());ver=o.__version__\n"
        "except Exception: pass\n"
        "print(json.dumps({'prov':prov,'ver':ver,'dll':sorted(dll)}))\n"
    )
    r = run([str(py), "-c", code])
    if r is None or r.returncode != 0:
        return Result("onnx-cuda", OK, "ONNX 加速后端", "探测失败",
                      (r.stderr if r else "")[-200:])
    info = json.loads(r.stdout.strip().splitlines()[-1])
    prov, ver, dll = info["prov"], info["ver"], info["dll"]

    if not prov:
        return Result("onnx-cuda", OK, "ONNX 加速后端", "未安装 onnxruntime",
                      "见上一条依赖检查")

    has_cuda = "CUDAExecutionProvider" in prov
    has_dml = "DmlExecutionProvider" in prov
    if not has_cuda and not has_dml:
        return Result("onnx-cuda", WARN, "ONNX 加速后端",
                      f"{ver} 只有 CPU provider（合成会慢 3-4 倍）",
                      "运行本脚本自动换成 CUDA 版；A 卡用户装 onnxruntime-directml")

    if has_dml:
        return Result("onnx-cuda", OK, "ONNX 加速后端", f"{ver}  DirectML")

    # 有 CUDA EP 还要查 dll：缺 dll 时 ORT 只会在日志里刷红字然后静默退 CPU
    lack = [n for n in ONNX_CUDA_DLLS if not any(d.startswith(n) for d in dll)]
    if lack:
        return Result("onnx-cuda", FAIL, "ONNX 加速后端",
                      f"{ver} 缺 CUDA 运行库：{', '.join(lack)}*.dll",
                      "运行本脚本自动补装 nvidia-*-cu12 wheel（约 700 MB，无需装 CUDA Toolkit）")
    return Result("onnx-cuda", OK, "ONNX 加速后端", f"{ver}  CUDA 运行库齐全")


def check_llama():
    g = detect_gpu()
    be = g["backend"] if g["backend"] in LLAMA_BACKENDS else "vulkan"
    missing = [f for f in LLAMA_FILES if not (LLAMA_DIR / f).exists()]
    if missing:
        zipname = f"llama-{LLAMA_TAG}-{LLAMA_BACKENDS[be][0]}"
        return Result("llama", FAIL, "llama.cpp 运行库",
                      f"缺 {', '.join(missing)}" if LLAMA_DIR.exists() else "目录不存在",
                      f"运行本脚本自动下载 {zipname} 到 {LLAMA_DIR.relative_to(ROOT)}")
    size = sum(p.stat().st_size for p in LLAMA_DIR.glob("*.dll")) / 2**20
    cur = bin_backend()
    detail = f"{LLAMA_DIR.relative_to(ROOT)}  {size:.0f} MB  后端 {cur or '未知'}"
    want = "cuda" if be.startswith("cuda") else "vulkan"
    if cur and cur != want:
        # 能跑就别动，只提示可以换更快的那版
        return Result("llama-opt", WARN, "llama.cpp 运行库", detail,
                      f"检测到 {g['name'] or g['vendor']}，换成 {LLAMA_BACKENDS[be][1]} 版会更快；"
                      f"想换就删掉 {LLAMA_DIR.relative_to(ROOT)} 后重跑本脚本")
    return Result("llama", OK, "llama.cpp 运行库", detail)


def check_model():
    if not MODEL_DIR.exists():
        return Result("model", FAIL, "模型文件 model-base", "目录不存在",
                      "需要先导出（见 README「导出」章节），或从别处拷贝整个 model-base 目录")
    missing = [f for f in MODEL_FILES if not (MODEL_DIR / f).exists()]
    if missing:
        return Result("model", FAIL, "模型文件 model-base",
                      f"缺 {len(missing)} 个：{', '.join(missing)}",
                      "需要先导出，或从别处拷贝整个 model-base 目录")
    size = sum(p.stat().st_size for p in MODEL_DIR.rglob("*") if p.is_file()) / 2**30
    return Result("model", OK, "模型文件 model-base", f"6 个文件齐全，{size:.1f} GB")


def which_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return Path(exe)
    local = FFMPEG_DIR / "bin" / "ffmpeg.exe"
    if local.exists():
        return local
    hits = list(FFMPEG_DIR.glob("*/bin/ffmpeg.exe")) if FFMPEG_DIR.exists() else []
    return hits[0] if hits else None


def check_ffmpeg():
    exe = which_ffmpeg()
    if exe is None:
        return Result("ffmpeg", WARN, "FFmpeg", "未找到",
                      "克隆音色与 mp3/opus 转码需要；运行本脚本自动下载，或 winget install ffmpeg")
    r = run([str(exe), "-version"])
    ver = ""
    if r and r.returncode == 0:
        m = re.search(r"ffmpeg version (\S+)", r.stdout)
        ver = m.group(1) if m else ""
    return Result("ffmpeg", OK, "FFmpeg", f"{ver}  {exe}")


def check_voices():
    d = ROOT / "output" / "elaborate"
    if not d.exists():
        return Result("voices", WARN, "音色目录", "output/elaborate 不存在",
                      "GUI 里生成音色后会自动创建")
    n = len({p.stem for p in list(d.glob("*.json")) + list(d.glob("*.wav"))})
    return Result("voices", OK, "音色目录", f"{n} 个音色")


def gather():
    return [
        check_python(),
        check_venv(),
        check_packages(),
        check_onnx_cuda(),
        check_llama(),
        check_model(),
        check_ffmpeg(),
        check_voices(),
    ]


# ---------------------------------------------------------------- 修复动作


class DownloadError(RuntimeError):
    """下载失败/中断/文件损坏。"""


def _download_once(url, tmp: Path, label):
    req = urllib.request.Request(url, headers={"User-Agent": "qwen3-tts-gguf-setup"})
    written = 0
    with urllib.request.urlopen(req, timeout=60) as r, tmp.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            written += len(chunk)
            if total > 0:
                pct = min(100, written * 100 // total)
                bar = "#" * (pct // 4)
                sys.stdout.write(
                    f"\r  [{bar:<25}] {pct:3d}%  {written / 2**20:.1f}/{total / 2**20:.1f} MB"
                )
                sys.stdout.flush()
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()
    if total and written < total:
        raise DownloadError(f"只收到 {written / 2**20:.1f}/{total / 2**20:.1f} MB")
    return written


def _download(url, dest: Path, label, tries=3):
    """下载到 dest，校验大小和 zip 完整性，失败自动重试。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    say(C.dim(f"  下载 {label} …"))
    last = None
    for attempt in range(1, tries + 1):
        try:
            _download_once(url, tmp, label)
            if dest.suffix.lower() == ".zip" and not zipfile.is_zipfile(tmp):
                raise DownloadError("文件不完整（不是有效的 zip）")
            tmp.replace(dest)
            return dest
        except DownloadError as e:
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        tmp.unlink(missing_ok=True)
        if attempt < tries:
            say(C.dim(f"  下载失败：{last}；第 {attempt}/{tries} 次重试 …"))
    raise DownloadError(f"{label} 下载失败：{last}")


def _extract_bin(zip_path: Path, dest_dir: Path, want="bin"):
    """从 zip 里挑出最像 bin 的那一层，平铺拷到 dest_dir。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        zip_path.unlink(missing_ok=True)
        raise DownloadError(f"{zip_path.name} 已损坏，已删除；重跑本脚本会重新下载") from None
    with z:
        names = z.namelist()
        # 找包含目标 exe/dll 的目录前缀
        prefixes = set()
        for n in names:
            if n.lower().endswith((".dll", ".exe")) and f"/{want}/" in n.replace("\\", "/").lower():
                prefixes.add(n.rsplit("/", 1)[0])
        if not prefixes:
            prefixes = {""}
        prefix = sorted(prefixes, key=len)[0]
        for n in names:
            if not n.startswith(prefix):
                continue
            if n.endswith("/"):
                continue
            rel = n[len(prefix):].lstrip("/")
            if not rel:
                continue
            target = dest_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            copied += 1
    return copied


def fix_venv():
    """创建/补装 .venv。优先 uv，退回 pip。"""
    py = venv_python()
    if not py.exists():
        uv = shutil.which("uv")
        if uv:
            say(C.dim("  用 uv sync 建环境（首次约 1-3 分钟）…"))
            extra = "dml"
            gpu = detect_gpu()
            want_cuda = gpu["backend"].startswith("cuda")
            if want_cuda:
                say(C.dim(f"  检测到 {gpu['name'] or 'NVIDIA 显卡'}，建议用 CUDA"))
            try:
                ans = input(f"  用 N 卡 CUDA 加速吗？({'Y/n' if want_cuda else 'y/N'}) ").strip().lower()
            except EOFError:
                ans = "y" if want_cuda else ""
            if ans in ("y", "yes") or (ans == "" and want_cuda):
                extra = "cuda"
            r = run([uv, "sync", "--extra", extra], cwd=str(ROOT), timeout=1800)
            if r and r.returncode == 0:
                return True
            say(C.err("  uv sync 失败，改用 pip"))
        say(C.dim("  创建 .venv 并安装依赖（首次约 2-5 分钟）…"))
        r = run([sys.executable, "-m", "venv", str(ROOT / ".venv")], timeout=300)
        if r is None or r.returncode != 0:
            say(C.err("  创建虚拟环境失败"))
            return False
        req = ROOT / "requirements.txt"
        cmd = [str(venv_python()), "-m", "pip", "install", "-U", "pip", "-i", PIP_MIRROR, "-q"]
        run(cmd, timeout=600)
        cmd = [str(venv_python()), "-m", "pip", "install", "-r", str(req), "-i", PIP_MIRROR]
        r = run(cmd, timeout=1800)
        return bool(r and r.returncode == 0)
    # venv 在，只补缺包
    res = check_packages()
    if not res.failed:
        return True
    say(C.dim("  补装缺失依赖 …"))
    code = (
        "import importlib\n"
        f"mods={list(PY_MODULES)!r}\n"
        "for m in mods:\n"
        "    try: importlib.import_module(m)\n"
        "    except Exception: print(m)\n"
    )
    r = run([str(py), "-c", code])
    miss = [m for m in (r.stdout or "").split() if m]
    pkg = [PY_MODULES[m] for m in miss if m in PY_MODULES]
    if not pkg:
        return True
    r = run([str(py), "-m", "pip", "install", *pkg, "-i", PIP_MIRROR], timeout=1200)
    return bool(r and r.returncode == 0)


def fix_llama():
    g = detect_gpu()
    be = g["backend"] if g["backend"] in LLAMA_BACKENDS else "vulkan"
    suffix, label, mb = LLAMA_BACKENDS[be]
    zipname = f"llama-{LLAMA_TAG}-{suffix}"
    url = f"{LLAMA_REL}/{zipname}"
    say(C.dim(f"  设备：{g['name'] or '未识别'}（{g['reason'] or '默认'}）-> {label} 后端"))

    # CUDA 包不含 cublas/cudart，本机没有 CUDA 运行时就顺手补一份
    cudart = None
    if be.startswith("cuda") and not has_cuda_runtime():
        crt, crt_mb = LLAMA_CUDART[be]
        say(C.dim(f"  本机没装 CUDA 运行时，需要额外下载 {crt}（~{crt_mb} MB）"))
        cudart = (f"{LLAMA_REL}/{crt}", ROOT / ".cache" / crt, crt_mb)

    tmp = ROOT / ".cache" / zipname
    if not tmp.exists():
        _download(url, tmp, f"llama.cpp {LLAMA_TAG} {label}（~{mb} MB）")
    else:
        say(C.dim(f"  复用已下载的 {tmp.name}"))

    # 换后端前先清掉旧的 ggml 后端 dll，别让 CUDA 和 Vulkan 混在一起
    if LLAMA_DIR.exists():
        for p in LLAMA_DIR.glob("ggml-*.dll"):
            try:
                p.unlink()
            except OSError:
                pass

    n = _extract_bin(tmp, LLAMA_DIR)
    if cudart:
        cu, path, cmb = cudart
        if not path.exists():
            _download(cu, path, f"CUDA 运行库 cudart（~{cmb} MB）")
        n += _extract_bin(path, LLAMA_DIR)
    say(C.dim(f"  解压 {n} 个文件到 {LLAMA_DIR.relative_to(ROOT)}"))
    return all((LLAMA_DIR / f).exists() for f in LLAMA_FILES)


def _pip_install(pkgs, timeout=2400) -> bool:
    """在 .venv 里装包：uv 建的 venv 没有 pip，所以优先走 uv pip。"""
    py = venv_python()
    uv = shutil.which("uv")
    if uv:
        r = run([uv, "pip", "install", "--python", str(py), *pkgs],
                cwd=str(ROOT), timeout=timeout)
        if r and r.returncode == 0:
            return True
        say(C.dim("  uv pip 失败，改用 pip …"))
    r = run([str(py), "-m", "pip", "install", *pkgs, "-i", PIP_MIRROR], timeout=timeout)
    return bool(r and r.returncode == 0)


def _ort_providers() -> list:
    py = venv_python()
    if not py.exists():
        return []
    r = run([str(py), "-c",
             "import onnxruntime as o;print('|'.join(o.get_available_providers()))"])
    return (r.stdout or "").strip().split("|") if r and r.returncode == 0 else []


def fix_onnx_cuda():
    """装 onnxruntime-gpu + pip 版 CUDA 运行库（不需要 CUDA Toolkit）。"""
    py = venv_python()
    if not py.exists():
        say(C.err("  没有 .venv，先修「虚拟环境」"))
        return False
    elif "DmlExecutionProvider" in _ort_providers():
        say(C.dim("  当前是 DirectML 版，保持不动（A 卡 / 不想动 CUDA 时更省事）"))
        return True

    pkgs = [ORT_CUDA_SPEC, *ONNX_CUDA_WHEELS]
    say(C.dim(f"  安装 {ORT_CUDA_SPEC} + {len(ONNX_CUDA_WHEELS)} 个 NVIDIA 运行库 wheel"
              "（约 700 MB，首次 3-10 分钟）…"))
    if _pip_install(pkgs):
        say(C.dim("  已安装，正在复核 …"))
        res = check_onnx_cuda()
        if res.level != FAIL:
            return True
        say(C.err(f"  {res.detail}"))
        return False
    say(C.err("  安装失败"))
    return False


def fix_ffmpeg():
    tmp = ROOT / ".cache" / "ffmpeg.zip"
    if not tmp.exists():
        _download(FFMPEG_URL, tmp, "FFmpeg essentials (~80 MB)")
    n = _extract_bin(tmp, FFMPEG_DIR)
    say(C.dim(f"  解压 {n} 个文件到 {FFMPEG_DIR.relative_to(ROOT)}"))
    return which_ffmpeg() is not None


# ---------------------------------------------------------------- 主流程


def print_report(results, quiet=False):
    if quiet:
        bad = [r for r in results if r.failed]
        if bad:
            for r in bad:
                print(f"[x] {r.title}: {r.detail}")
        return len(bad)
    for r in results:
        tag = {"OK": C.ok("[ OK ]"), "WARN": C.warn("[WARN]"), "FAIL": C.err("[FAIL]")}[r.level]
        say(f"{tag} {r.title:<22} {r.detail}")
        if r.hint and r.level != OK:
            say(C.dim(f"       -> {r.hint}"))
    return len([r for r in results if r.failed])


def main():
    _fix_console()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--check", action="store_true", help="只体检，不做修改")
    ap.add_argument("-q", "--quiet", action="store_true", help="只输出问题行")
    ap.add_argument("--yes", action="store_true", help="自动修复，不逐项确认")
    args = ap.parse_args()

    say(C.bold("Qwen3-TTS GGUF 环境检查"))
    say(C.dim(f"目录 {ROOT}"))
    if not args.quiet:
        g = detect_gpu()
        be = LLAMA_BACKENDS.get(g["backend"], (None, "Vulkan", 0))[1]
        say(C.dim(f"设备 {g['name'] or '未识别'}  驱动 {g['driver'] or '-'}  "
                  f"计划后端 {be}（{g['reason'] or '默认'}）"))

    results = gather()
    nfail = print_report(results, quiet=args.quiet)
    if args.check:
        if not args.quiet:
            say()
            if nfail == 0:
                say(C.ok("全部通过，可以启动 GUI。"))
            else:
                say(C.err(f"{nfail} 项需要处理。"))
        return 0 if nfail == 0 else 1

    todo = [r for r in results if r.level != OK]
    if not todo:
        say()
        say(C.ok("全部通过，无需修复。"))
        return 0

    say()
    say(C.bold("开始修复"))
    fixed = 0
    for r in todo:
        need_fix = r.key in ("venv", "packages", "onnx-cuda", "llama", "ffmpeg")
        if not need_fix:
            say()
            if r.level == WARN:
                say(C.warn(f"{r.title}："))
            else:
                say(C.warn(f"{r.title} 需要你手动处理："))
            say(f"  {r.hint}")
            continue
        if not args.yes:
            try:
                ans = input(f"  修复 {r.title}？(Y/n) ").strip().lower()
            except EOFError:
                ans = "y"
            if ans in ("n", "no"):
                continue
        say()
        section(f"修复 {r.title}")
        ok = False
        try:
            if r.key in ("venv", "packages"):
                ok = fix_venv()
            elif r.key == "onnx-cuda":
                ok = fix_onnx_cuda()
            elif r.key == "llama":
                ok = fix_llama()
            elif r.key == "ffmpeg":
                ok = fix_ffmpeg()
        except DownloadError as e:
            say(C.err(f"  {e}"))
            say(C.dim("  网络不稳的话直接重跑本脚本，已下好的文件会复用。"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            say(C.err(f"  出错了：{e}"))
            say(C.dim("  检查网络后重跑本脚本。"))
        say(C.ok(f"  {r.title} 完成") if ok else C.err(f"  {r.title} 失败，请手动处理"))
        fixed += 1 if ok else 0

    say()
    section("复检")
    results = gather()
    nfail = print_report(results)
    say()
    if nfail == 0:
        say(C.ok("环境就绪，双击「启动GUI.bat」开始使用。"))
    else:
        say(C.err(f"仍有 {nfail} 项未解决，按上面的提示处理后重跑本脚本。"))
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say()
        say("已取消")
        raise SystemExit(130) from None
