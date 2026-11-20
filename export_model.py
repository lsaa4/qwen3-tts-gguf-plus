# coding=utf-8
"""
export_model.py —— 一键把官方原版 Qwen3-TTS 转成推理用的 model-base。

原版权重是 bf16 safetensors，仓库里的推理引擎要的是 GGUF + fp16 ONNX。
手工跑十四个脚本很容易漏步、也容易搞错顺序，所以这里打包成一条流水线：
定位源模型 → 检查依赖 → 依次执行 → 校验产物。

用法：
    python export_model.py                    # 交互选择模型，全程自动
    python export_model.py -m base            # 直接指定模型
    python export_model.py -m custom --out D:\\exp\\model-custom
    python export_model.py -m base --only 21,22,23,24   # 只跑指定步骤
    python export_model.py -m base --keep     # 保留中间产物（默认跑完询问是否清）
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------- 输出

class C:
    """ANSI 颜色；管道或老终端自动降级为空串。"""

    _on = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    if _on and os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleMode(ctypes.windll.kernel32.GetStdHandle(-11), 7)
        except Exception:
            _on = False

    @staticmethod
    def dim(s):
        return f"\033[2m{s}\033[0m" if C._on else s

    @staticmethod
    def ok(s):
        return f"\033[32m{s}\033[0m" if C._on else s

    @staticmethod
    def warn(s):
        return f"\033[33m{s}\033[0m" if C._on else s

    @staticmethod
    def err(s):
        return f"\033[31m{s}\033[0m" if C._on else s

    @staticmethod
    def b(s):
        return f"\033[1m{s}\033[0m" if C._on else s

    @staticmethod
    def cy(s):
        return f"\033[36m{s}\033[0m" if C._on else s


def say(msg=""):
    print(msg, flush=True)


def section(title):
    say()
    say(C.cy("─" * 58))
    say(C.b(f"  {title}"))
    say(C.cy("─" * 58))


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} GB"


# ---------------------------------------------------------------- 模型与步骤

MODELS = {
    "base": ("Qwen3-TTS-12Hz-1.7B-Base", "声音克隆", "model-base"),
    "custom": ("Qwen3-TTS-12Hz-1.7B-CustomVoice", "内置音色 + 风格指令", "model-custom"),
    "design": ("Qwen3-TTS-12Hz-1.7B-VoiceDesign", "自然语言设计音色", "model-design"),
    "base-small": ("Qwen3-TTS-12Hz-0.6B-Base", "声音克隆（省显存）", "model-base-small"),
    "custom-small": ("Qwen3-TTS-12Hz-0.6B-CustomVoice", "内置音色（省显存）", "model-custom-small"),
}
ORDER = ["base", "custom", "design", "base-small", "custom-small"]

# (脚本, 说明, 产物)  产物用于校验：脚本自己吞异常时靠它兜底
STAGE1 = [
    ("11-Export-Codec-Encoder.py", "编码器导出", ["qwen3_tts_codec_encoder.fp32.onnx"]),
    ("12-Export-Speaker-Encoder.py", "说话人特征导出", ["qwen3_tts_speaker_encoder.fp32.onnx"]),
    ("13-Export-Decoder.py", "解码器导出（最慢的一步）", ["qwen3_tts_decoder.fp32.onnx"]),
    ("14-Export-Embeddings.py", "Embedding 权重导出", ["embeddings/text_embedding_projected.npy"]),
    ("15-Copy-Tokenizer.py", "文本分词器复制", ["tokenizer.json"]),
    ("16-Quantize-ONNX-Models.py", "ONNX 转 FP16",
     ["qwen3_tts_codec_encoder.fp16.onnx", "qwen3_tts_speaker_encoder.fp16.onnx",
      "qwen3_tts_decoder.fp16.onnx"]),
]
STAGE2 = [
    ("21-Extract-Talker-Weights.py", "Talker 权重拆分", ["talker_hf"]),
    ("22-Prepare-Talker-Tokenizer.py", "Talker 迷你词表", ["talker_hf"]),
    ("23-Convert-Talker-GGUF.py", "Talker 转 F16 GGUF", ["qwen3_tts_talker.f16.gguf"]),
    ("24-Quantize-Talker-GGUF.py", "Talker 量化 Q5_K", ["qwen3_tts_talker.q5_k.gguf"]),
]
STAGE3 = [
    ("31-Extract-Predictor-Weights.py", "Predictor 权重拆分", ["predictor_hf"]),
    ("32-Prepare-Predictor-Tokenizer.py", "Predictor 迷你词表", ["predictor_hf"]),
    ("33-Convert-Predictor-GGUF.py", "Predictor 转 F16 GGUF", ["qwen3_tts_predictor.f16.gguf"]),
    ("34-Quantize-Predictor-GGUF.py", "Predictor 量化 Q8_0", ["qwen3_tts_predictor.q8_0.gguf"]),
]
STAGES = [("阶段一 · 导出小组件", STAGE1), ("阶段二 · 导出 Talker", STAGE2), ("阶段三 · 导出 Predictor", STAGE3)]

FINAL_FILES = [
    "qwen3_tts_codec_encoder.fp16.onnx",
    "qwen3_tts_decoder.fp16.onnx",
    "qwen3_tts_speaker_encoder.fp16.onnx",
    "qwen3_tts_predictor.q8_0.gguf",
    "qwen3_tts_talker.q5_k.gguf",
    "tokenizer.json",
]
# 中间产物：目录 + 通配。16 号脚本还会顺手生成 int8 和 fp32 的外部权重 .data，
# 推理都不加载，留着白占一两个 GB。
INTERMEDIATE_DIRS = ["talker_hf", "predictor_hf"]
INTERMEDIATE_GLOBS = [
    "*.fp32.onnx", "*.fp32.onnx.data",
    "*.int8.onnx", "*.int8.onnx.data",
    "*.int4.onnx", "*.int4.onnx.data",
    "*.f16.gguf",
]

EXPORT_DEPS = ["torch", "torchaudio", "onnx", "onnxruntime", "safetensors", "transformers", "numpy"]
QUANTIZER = ROOT / "qwen3_tts_gguf" / "inference" / "bin" / "llama-quantize.exe"


# ---------------------------------------------------------------- 前置检查

def find_source(name: str) -> Path | None:
    """按 export_config 的探测顺序找官方模型目录。"""
    home = os.environ.get("QWEN_MODEL_HOME")
    cands = [Path(home) if home else None,
             Path(r"D:\qwen3-tts\models"),
             Path.home() / ".cache/modelscope/hub/models/Qwen"]
    for c in cands:
        if c is not None and (c / name).is_dir():
            return c / name
    return None


def download_source(name: str) -> Path | None:
    """用 modelscope 拉原版模型；HF 用户自行下载后放好即可。"""
    try:
        import modelscope  # noqa: F401
    except ImportError:
        say(C.warn("  没装 modelscope，尝试安装…"))
        r = subprocess.run([sys.executable, "-m", "pip", "install", "modelscope",
                            "-i", "https://mirrors.aliyun.com/pypi/simple/"],
                           cwd=ROOT)
        if r.returncode != 0:
            say(C.err("  安装 modelscope 失败，请手动下载模型后重试。"))
            return None
    say(f"  下载 {name}（几个 GB，首次会慢）…")
    code = (
        "import os,sys\n"
        "from modelscope import snapshot_download\n"
        f"p = snapshot_download('Qwen/{name}')\n"
        "print('LOCAL_DIR=' + p)\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=False)
    if r.returncode != 0:
        say(C.err("  下载失败。可手动从 Hugging Face / ModelScope 下载，放到 "
                  r"D:\\qwen3-tts\\models 或设 QWEN_MODEL_HOME 指过去。"))
        return None
    return find_source(name)


def check_deps() -> list[str]:
    import importlib.util

    return [m for m in EXPORT_DEPS if importlib.util.find_spec(m) is None]


def free_space_gb(path: Path) -> float:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free / 2**30
    except OSError:
        return 999.0


# ---------------------------------------------------------------- 执行

def run_step(script: str, desc: str, outputs: list[str], out_dir: Path, env: dict) -> bool:
    t0 = time.time()
    say()
    say(C.b(f"▸ {script}") + C.dim(f"  {desc}"))
    r = subprocess.run([sys.executable, script], cwd=ROOT, env=env)
    dt = time.time() - t0

    if r.returncode != 0:
        say(C.err(f"  失败（退出码 {r.returncode}，耗时 {dt:.0f}s）"))
        return False

    missing = [o for o in outputs if not (out_dir / o).exists()]
    if missing:
        # 脚本内部吞异常时退出码仍是 0，这里靠产物兜底
        say(C.err(f"  跑完了但没产出：{', '.join(missing)}（耗时 {dt:.0f}s）"))
        say(C.dim("  往上翻输出，找 [失败] / Error / Traceback 那几行。"))
        return False

    say(C.ok(f"  完成（{dt:.0f}s）"))
    return True


def verify(out_dir: Path) -> bool:
    section("校验产物")
    missing = [f for f in FINAL_FILES if not (out_dir / f).exists()]
    emb = out_dir / "embeddings"
    npy = list(emb.glob("*.npy")) if emb.exists() else []

    total = 0
    for f in FINAL_FILES:
        p = out_dir / f
        if p.exists():
            total += p.stat().st_size
            say(f"  {C.ok('✓')} {f:<36} {human(p.stat().st_size):>10}")
    if npy:
        esz = sum(p.stat().st_size for p in npy)
        total += esz
        say(f"  {C.ok('✓')} {'embeddings/':<36} {human(esz):>10}  ({len(npy)} 个文件)")

    if missing:
        say()
        say(C.err(f"  缺 {len(missing)} 个关键文件：{', '.join(missing)}"))
        return False

    if len(npy) < 17:
        say()
        say(C.warn(f"  embeddings 只有 {len(npy)} 个文件，正常是 19 个，可能没导全。"))

    say()
    say(C.ok(f"  全部就绪，共 {human(total)}"))
    say(C.dim(f"  目录：{out_dir}"))
    return True


def clean_intermediate(out_dir: Path):
    freed = 0
    for name in INTERMEDIATE_DIRS:
        d = out_dir / name
        if d.is_dir():
            freed += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            shutil.rmtree(d, ignore_errors=True)
            say(f"  已删 {name}/")

    for pattern in INTERMEDIATE_GLOBS:
        for f in sorted(out_dir.glob(pattern)):
            freed += f.stat().st_size
            f.unlink(missing_ok=True)
            say(f"  已删 {f.name}")

    say(C.dim(f"  释放 {human(freed)}"))


# ---------------------------------------------------------------- 主流程

def pick_model() -> str:
    say()
    say("  想导出哪个模型？")
    for i, key in enumerate(ORDER, 1):
        name, desc, dest = MODELS[key]
        say(f"   {i}) {key:<13} {desc}  →  {dest}")
    say()
    try:
        ans = input("  序号或名字（直接回车 = 1 base）：").strip()
    except EOFError:
        ans = ""
    if not ans:
        return "base"
    if ans.isdigit() and 1 <= int(ans) <= len(ORDER):
        return ORDER[int(ans) - 1]
    if ans in MODELS:
        return ans
    say(C.err(f"  没有这个选项：{ans}"))
    raise SystemExit(2)


def main() -> int:
    ap = argparse.ArgumentParser(description="一键导出 Qwen3-TTS GGUF 模型")
    ap.add_argument("-m", "--model", choices=ORDER, help="要导出的模型（不给就交互选择）")
    ap.add_argument("--out", help="输出目录（默认项目根下的 model-base 等）")
    ap.add_argument("--only", help="只跑指定步骤编号，逗号分隔，例如 21,22,23,24")
    ap.add_argument("--keep", action="store_true", help="保留中间产物")
    ap.add_argument("--no-download", action="store_true", help="源模型不存在时不自动下载")
    ap.add_argument("--yes", action="store_true", help="不询问，直接开始")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    say()
    say(C.b("  Qwen3-TTS · 模型导出流水线"))

    key = args.model or pick_model()
    src_name, desc, dest_name = MODELS[key]
    out_dir = Path(args.out) if args.out else ROOT / dest_name

    say()
    say(f"  模型：{src_name}（{desc}）")
    say(f"  输出：{out_dir}")

    # 1. 源模型
    section("定位源模型")
    src = find_source(src_name)
    if src is None:
        if args.no_download:
            say(C.err(f"  没找到 {src_name}，也没有允许自动下载。"))
            return 2
        src = download_source(src_name)
        if src is None:
            return 2
    nfiles = sum(1 for _ in src.rglob("*") if _.is_file())
    say(f"  {C.ok('✓')} {src}")
    say(C.dim(f"    {nfiles} 个文件，{human(sum(f.stat().st_size for f in src.rglob('*') if f.is_file()))}"))

    # 2. 依赖
    section("检查依赖")
    missing = check_deps()
    if missing:
        say(C.err(f"  缺 Python 包：{', '.join(missing)}"))
        say(C.dim("  跑一次：uv sync --extra export   （或 pip install torch onnx onnxruntime safetensors transformers）"))
        return 3
    say(C.ok("  ✓ 导出依赖齐全"))

    if not QUANTIZER.exists():
        say(C.err(f"  缺量化工具：{QUANTIZER}"))
        say(C.dim("  跑一次 setup.bat 会自动装 llama.cpp b10621。"))
        return 3
    say(C.ok(f"  ✓ llama-quantize.exe"))

    free = free_space_gb(out_dir)
    if free < 10:
        say(C.warn(f"  磁盘只剩 {free:.1f} GB，导出过程临时要 8~10 GB，可能不够。"))
        if not args.yes:
            try:
                if input("  继续？(y/N) ").strip().lower() not in ("y", "yes"):
                    return 4
            except EOFError:
                return 4
    else:
        say(C.dim(f"  可用空间 {free:.0f} GB"))

    # 3. 开跑
    want = None
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        known = {s[0].split("-")[0] for _, steps in STAGES for s in steps}
        bad = want - known
        if bad:
            say(C.err(f"  --only 里有不存在的步骤：{', '.join(sorted(bad))}"))
            return 2

    plan = [(title, [s for s in steps if want is None or s[0].split("-")[0] in want])
            for title, steps in STAGES]
    total_steps = sum(len(steps) for _, steps in plan)

    if not args.yes:
        say()
        say(f"  即将依次执行 {total_steps} 个脚本，预计 10~30 分钟（看显卡和 CPU）。")
        try:
            if input("  开始？(Y/n) ").strip().lower() in ("n", "no"):
                return 0
        except EOFError:
            pass

    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["QWEN_EXPORT_MODEL"] = key
    env["QWEN_MODEL_HOME"] = str(src.parent)
    env["QWEN_EXPORT_DIR"] = str(out_dir)
    env["PYTHONIOENCODING"] = "utf-8"

    t_all = time.time()
    for title, steps in plan:
        if not steps:
            continue
        section(title)
        for script, desc, outputs in steps:
            if not run_step(script, desc, outputs, out_dir, env):
                say()
                say(C.err("  中止。修好上面这一步后重跑本脚本即可，已完成的步骤会跳过重复劳动（脚本幂等）。"))
                return 5

    say()
    say(C.ok(f"  流水线跑完，总耗时 {(time.time() - t_all) / 60:.1f} 分钟"))

    if want is not None:
        say()
        say(C.dim("  只跑了指定步骤，跳过完整校验。"))
        return 0

    ok = verify(out_dir)

    if ok and not args.keep:
        section("清理中间产物")
        say(C.dim("  这些文件只在导出时用得上，留着白占几个 GB。"))
        try:
            ans = input("  删掉？(Y/n) ").strip().lower()
        except EOFError:
            ans = "y"
        if ans not in ("n", "no"):
            clean_intermediate(out_dir)
        else:
            say(C.dim("  已保留，可稍后手动删。"))

    say()
    if ok:
        say(C.ok("  完成。把整个目录放到项目根，双击「启动GUI.bat」就能用了。"))
    else:
        say(C.err("  产物不完整，看上面的缺口。"))
    return 0 if ok else 6


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say()
        say("已取消")
        raise SystemExit(130) from None
