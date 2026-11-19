#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把一段参考音频编码成「音色锚点」json，供 tts.py -v 或 GUI 克隆页复用。

用法:
    python clone.py 我的声音.wav
    python clone.py 我的声音.wav -t "这段录音的原话" -n 巧克力
    python clone.py 我的声音.wav -o output\\elaborate\\pudding.json

说明:
    音频 5~15 秒、单人、无背景音乐效果最好；wav/mp3/flac/m4a/opus 都行。
    -t 填音频的原话（转写），带转写的普通克隆效果比零样本好；不填就只用音色向量。
"""
import argparse
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
import os
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("audio", help="参考音频路径 (wav/mp3/flac/m4a/opus)")
    ap.add_argument("-t", "--text", default="", help="参考音频的转写文本 (可选，强烈建议填)")
    ap.add_argument("-n", "--name", default=None, help="音色名 (默认用音频文件名)")
    ap.add_argument("-o", "--out", default=None, help="输出 json 路径 (默认 output/elaborate/<名字>.json)")
    ap.add_argument("--cpu-decode", action="store_true")
    ap.add_argument("-T", "--text-file", default="", help="从 UTF-8 文件读取转写文本")
    ap.add_argument("-f", "--force", action="store_true", help="允许覆盖已存在的 json")
    args = ap.parse_args()

    src = Path(args.audio)
    if not src.exists():
        print(f"找不到音频: {src}")
        return 2

    out = Path(args.out) if args.out else Path("output/elaborate") / f"{args.name or src.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not args.force:
        i = 2
        while True:
            cand = out.with_name(f"{out.stem}_{i}.json")
            if not cand.exists():
                out = cand
                break
            i += 1
        print(f"同名音色已存在，改存为 {out.name}（要覆盖请加 -f）")

    from qwen3_tts_gguf.inference import TTSEngine, TTSResult
    from qwen3_tts_gguf.inference.utils.audio import load_audio

    print(f"载入编码器 (跳过 LLM，约 3 秒)...")
    engine = TTSEngine(model_dir="model-base",
                       onnx_provider="CPU" if args.cpu_decode else "DML",
                       subprocess_decoder=False, load_llm=False, verbose=False)
    if not engine:
        print("引擎初始化失败")
        return 1

    samples = load_audio(src)
    if samples is None:
        print("音频解码失败，换 wav 或先转码")
        engine.shutdown()
        return 1

    text = args.text or ""
    if args.text_file:
        from pathlib import Path as _P
        text = _P(args.text_file).read_text(encoding="utf-8").strip()
    voice = TTSResult(text=text,
                      text_ids=engine.tokenizer.encode(text).ids,
                      spk_emb=engine.speaker_encoder.encode(samples),
                      codes=engine.codec_encoder.encode(samples))
    if voice.spk_emb is None or voice.codes is None:
        print("音色提取失败（音频里有人声吗？时长 5~15 秒最佳）")
        engine.shutdown()
        return 1

    voice.save(str(out))
    print(f"音色已保存: {out}  ({out.stat().st_size} bytes)")
    print(f"   codes {voice.codes.shape} / 音色向量 {voice.spk_emb.shape} / 音频 {samples.shape[0]/24000:.1f}s")
    print(f"   使用: tts.py \"文本\" -v {out}")
    engine.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
