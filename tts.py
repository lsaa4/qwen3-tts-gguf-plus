#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Qwen3-TTS-GGUF 命令行合成工具（ONNX DirectML + llama.cpp Vulkan）

用法:
    python tts.py "要说的中文" 
    python tts.py "text" -v output\\elaborate\\晓晓.json -o out.wav
    python tts.py --list-voices

可选参数:
    -v/--voice   参考音色 json 或 wav (默认 output\\elaborate\\Vivian.json)
    -o/--out     输出 wav 路径 (默认 output\\clone\\<文本前12字>.wav)
    -s/--seed    随机种子 (默认 42，固定音色更稳定)
    -t/--temp    采样温度 (默认 0.6)
    -z/--zero    使用零样本克隆 (仅用说话人嵌入，跨语种更稳)
"""
import argparse
import glob
import os
import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK，emoji/中文 print 会抛 UnicodeEncodeError（引擎会当作致命异常）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

DEFAULT_VOICE = "output/elaborate/Vivian.json"


def list_voices():
    files = sorted(glob.glob("output/elaborate/*.json"))
    print("可用音色 (json 为无损 code, wav 为有损但可直接用):")
    for f in files:
        print("  ", f)
    if not files:
        print("   (没有找到，请把参考音频或 json 放进 output/elaborate/)")


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("text", nargs="?", help="要合成的文本")
    ap.add_argument("-f", "--file", default=None, help="从 UTF-8 文本文件读入（避免命令行引号问题）")
    ap.add_argument("-v", "--voice", default=DEFAULT_VOICE)
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("-s", "--seed", type=int, default=42)
    ap.add_argument("-t", "--temp", type=float, default=0.6)
    ap.add_argument("-z", "--zero", action="store_true", help="零样本克隆")
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--cpu-decode", action="store_true", help="ONNX 解码器用 CPU (DML 出错时)")
    args = ap.parse_args()

    if args.list_voices:
        list_voices()
        return 0
    if args.file:
        args.text = Path(args.file).read_text(encoding="utf-8").strip()
    if not args.text:
        ap.print_help()
        return 2

    from qwen3_tts_gguf.inference import TTSEngine, TTSConfig

    provider = "CPU" if args.cpu_decode else "DML"
    t0 = time.time()
    engine = TTSEngine(model_dir="model-base", onnx_provider=provider, subprocess_decoder=False, verbose=False)
    stream = engine.create_stream()

    voice = args.voice
    if voice and Path(voice).exists():
        stream.set_voice(voice)
    else:
        print(f"参考音色不存在: {voice} (将用模型默认行为)", file=sys.stderr)

    cfg = TTSConfig(max_steps=1024, temperature=args.temp, sub_temperature=args.temp,
                    seed=args.seed, sub_seed=args.seed + 3, streaming=False)

    t1 = time.time()
    result = stream.clone(text=args.text, language="Chinese", zero_shot=args.zero, config=cfg)
    gen = time.time() - t1

    audio = getattr(result, "audio", None)
    sr = getattr(result, "sample_rate", 24000)
    dur = (len(audio) / sr) if audio is not None else 0.0

    out = args.out
    if not out:
        safe = "".join(c for c in args.text.strip() if c not in r'<>:"/\|?*')[:12].strip() or "tts"
        out = f"output/clone/{safe}.wav"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    result.save(out)

    print(f"{out}")
    print(f"   音频 {dur:.2f}s | 生成 {gen:.2f}s | RTF {gen/dur if dur else 0:.3f} | 端到端 {time.time()-t0:.2f}s")
    stream.join()
    engine.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
