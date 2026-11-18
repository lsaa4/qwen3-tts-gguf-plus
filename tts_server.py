#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""命令行入口：载入引擎后跑 OpenAI 兼容语音服务（无人值守用）。

GUI 的「服务」页用的是同一份 qwen3_tts_gguf/service.py，这里只是外壳：
载入引擎 -> 起服务 -> 挂住等 Ctrl+C。

用法:
    .venv\\Scripts\\python.exe tts_server.py [--port 8899] [--voice 巧克力] [--cpu-decode]

接口:
    POST /v1/audio/speech   {"input":"你好","voice":"巧克力","response_format":"mp3"}
    POST /audio/speech      (不带 /v1 也认)
    GET  /health            引擎与音色状态
    GET  /v1/models         模型列表
    GET  /v1/voices         可用音色
"""
import argparse
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)                 # 模型与音色都用相对路径，先站到仓库根
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

LOG_PATH = ROOT / "tts_server.log"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--voice", default="", help="默认音色名（省略后缀），空则用模型默认行为")
    ap.add_argument("--voice-dir", default="output/elaborate")
    ap.add_argument("--model", default="model-base")
    ap.add_argument("--temp", type=float, default=0.6)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--cpu-decode", action="store_true", help="解码器走 CPU（不占显存）")
    args = ap.parse_args()

    from qwen3_tts_gguf.inference import TTSEngine

    provider = "CPU" if args.cpu_decode else "DML"
    log(f"载入引擎 model={args.model} provider={provider}")
    t0 = time.time()
    try:
        engine = TTSEngine(model_dir=args.model, onnx_provider=provider,
                           subprocess_decoder=False, verbose=False)
    except Exception as e:
        log("引擎加载失败: " + repr(e))
        log(traceback.format_exc()[:1500])
        return 1
    log(f"引擎就绪 ({time.time() - t0:.2f}s)")

    srv = _make_server(engine, args)
    try:
        srv.start(args.host, args.port)
    except OSError as e:
        log(f"端口 {args.port} 起不来: {e}")
        return 1

    log(f"监听 {srv.address}  端点 /v1/audio/speech  默认音色 {args.voice or '(模型默认)'}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("收到中断，退出")
    finally:
        srv.stop()
        try:
            engine.shutdown()
        except Exception:
            pass
    return 0


def _make_server(engine, args):
    from qwen3_tts_gguf.service import SpeechServer
    return SpeechServer(engine_provider=lambda: engine,
                        voice_dir=args.voice_dir,
                        default_voice=args.voice,
                        temp=args.temp,
                        seed=args.seed,
                        log=log)


if __name__ == "__main__":
    sys.exit(main())
