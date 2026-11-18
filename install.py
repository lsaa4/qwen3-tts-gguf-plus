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
LLAMA_ZIP = f"llama-{LLAMA_TAG}-bin-win-vulkan-x64.zip"
LLAMA_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/{LLAMA_ZIP}"
LLAMA_DIR = ROOT / "qwen3_tts_gguf" / "inference" / "bin"
LLAMA_FILES = ["llama.dll", "ggml.dll", "llama-server.exe"]

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


def check_python():
    ver = sys.version_info
    got = f"{ver.major}.{ver.minor}.{ver.micro}"
    if (ver.major, ver.minor) >= PY_MIN:
        return Result("python", OK, "Python 版本", f"{got} ({sys.executable})")
    return Result(
        "python", WARN, "Python 版本",
        f"{got} 低于项目要求 {PY_MIN[0]}.{PY_MIN[1]}",
        "装 Python 3.14 后重跑本脚本：https://www.python.org/downloads/",
    )


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
    return Result("packages", WARN, "Python 依赖",
                  "齐全，但只有 CPU provider（会慢 4 倍左右）",
                  "N 卡：uv sync --extra cuda / pip install onnxruntime-gpu")


def check_llama():
    missing = [f for f in LLAMA_FILES if not (LLAMA_DIR / f).exists()]
    if not missing:
        size = sum(p.stat().st_size for p in LLAMA_DIR.glob("*.dll")) / 2**20
        return Result("llama", OK, "llama.cpp 运行库", f"{LLAMA_DIR.relative_to(ROOT)}  共 {size:.0f} MB")
    return Result("llama", FAIL, "llama.cpp 运行库",
                  f"缺 {', '.join(missing)}" if LLAMA_DIR.exists() else "目录不存在",
                  f"运行本脚本自动下载，或手动解压 {LLAMA_ZIP} 到 {LLAMA_DIR.relative_to(ROOT)}")


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
        check_llama(),
        check_model(),
        check_ffmpeg(),
        check_voices(),
    ]


# ---------------------------------------------------------------- 修复动作


def _download(url, dest: Path, label):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    say(C.dim(f"  下载 {label} …"))

    def hook(blocks, bs, total):
        if total <= 0:
            return
        done = blocks * bs
        pct = min(100, done * 100 // total)
        bar = "#" * (pct // 4)
        sys.stdout.write(f"\r  [{bar:<25}] {pct:3d}%  {done / 2**20:.1f}/{total / 2**20:.1f} MB")
        sys.stdout.flush()

    req = urllib.request.Request(url, headers={"User-Agent": "qwen3-tts-gguf-setup"})
    with urllib.request.urlopen(req, timeout=60) as r, tmp.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        blocks = 0
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            blocks += 1
            hook(blocks, 1 << 18, total)
    sys.stdout.write("\r" + " " * 60 + "\r")
    tmp.replace(dest)
    return dest


def _extract_bin(zip_path: Path, dest_dir: Path, want="bin"):
    """从 zip 里挑出最像 bin 的那一层，平铺拷到 dest_dir。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    with zipfile.ZipFile(zip_path) as z:
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
            say(C.dim("  用 uv sync --extra dml 建环境（首次约 1-3 分钟）…"))
            extra = "dml"
            say(C.dim("  想用 CUDA：选 n，然后重跑。"))
            try:
                ans = input("  用 N 卡 CUDA 加速吗？(y/N) ").strip().lower()
            except EOFError:
                ans = ""
            if ans in ("y", "yes"):
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
    tmp = ROOT / ".cache" / LLAMA_ZIP
    if not tmp.exists():
        _download(LLAMA_URL, tmp, f"llama.cpp {LLAMA_TAG} Vulkan (~120 MB)")
    else:
        say(C.dim(f"  复用已下载的 {tmp.name}"))
    n = _extract_bin(tmp, LLAMA_DIR)
    say(C.dim(f"  解压 {n} 个文件到 {LLAMA_DIR.relative_to(ROOT)}"))
    return all((LLAMA_DIR / f).exists() for f in LLAMA_FILES)


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
        need_fix = r.key in ("venv", "packages", "llama", "ffmpeg")
        if not need_fix:
            say()
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
        if r.key in ("venv", "packages"):
            ok = fix_venv()
        elif r.key == "llama":
            ok = fix_llama()
        elif r.key == "ffmpeg":
            ok = fix_ffmpeg()
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
