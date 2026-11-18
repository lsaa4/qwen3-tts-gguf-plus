"""OpenAI 兼容的本地语音服务：把已载入的引擎暴露成 HTTP 接口。

一份实现两处用：
- GUI 的「服务」页：在界面里启停，日志进 GUI 日志页
- tts_server.py 命令行：无人值守后台跑

不自己载入引擎，由调用方通过 engine_provider 传入（callable -> engine or None），
这样 GUI 裁掉页面 / 卸载引擎后，服务会自动回 503 而不是拿着死引擎用。

接口：
    GET  /health            引擎与音色状态
    GET  /v1/models         模型列表（OpenAI 格式）
    GET  /v1/voices         可用音色
    POST /v1/audio/speech   {"input": "你好", "voice": "巧克力", "response_format": "mp3"}
    POST /audio/speech      同上，去掉 /v1 也认（部分客户端这么填）
"""
from __future__ import annotations

import io
import json
import socket
import subprocess
import threading
import time
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# OpenAI 支持的 response_format，转不了的用 ffmpeg 兜底
_FORMAT_CTYPE = {
    "mp3": ("audio/mpeg", "libmp3lame"),
    "opus": ("audio/ogg", "libopus"),
    "aac": ("audio/aac", "aac"),
    "flac": ("audio/flac", "flac"),
    "wav": ("audio/wav", None),
    "pcm": ("audio/wav", None),
}


class SpeechServer:
    """HTTP 服务外壳。start/stop 可在任意线程调用，合成串行。"""

    def __init__(self, engine_provider, voice_dir="output/elaborate",
                 model_name="qwen3-tts-gguf", default_voice="", temp=0.6, seed=42, log=None):
        self.engine_provider = engine_provider      # callable -> engine | None
        self._voice_dir = Path(voice_dir)
        self.model_name = model_name
        self.default_voice = default_voice          # 请求没指定 voice 时用它
        self.temp = temp
        self.seed = seed
        self.log = log or (lambda msg: None)
        self._httpd = None
        self._thread = None
        self._stream = None
        self._stream_engine = None
        self._voice = None                          # 当前 stream 上的音色名
        self._lock = threading.Lock()                # 合成串行，避免多请求抢同一个 stream

    # ---------- 状态查询 ----------

    @property
    def voice_dir(self):
        return self._voice_dir

    @voice_dir.setter
    def voice_dir(self, path):
        """GUI 里会直接赋字符串，统一转成 Path"""
        self._voice_dir = Path(path or "output/elaborate")

    @property
    def running(self):
        return self._httpd is not None

    @property
    def address(self):
        if not self.running:
            return ""
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def voice(self):
        return self._voice

    def voices(self):
        """音色目录下所有可当音色用的文件（.json 音色 / .wav 参考音频）"""
        if not self._voice_dir.exists():
            return []
        # 同名 .json / .wav 会重复，按 stem 去重
        return sorted({p.stem for p in list(self._voice_dir.glob("*.json")) + list(self._voice_dir.glob("*.wav"))})

    def resolve_voice(self, name):
        """音色名 -> 路径，支持绝对路径、带/不带后缀、子目录相对路径"""
        if not name:
            return None
        p = Path(name)
        if p.suffix in (".json", ".wav") and p.exists():
            return p
        for suffix in (".json", ".wav"):
            cand = self._voice_dir / f"{name}{suffix}"
            if cand.exists():
                return cand
        return None

    # ---------- 合成 ----------

    def _stream_for(self, engine):
        """同一引擎复用一条 stream；引擎换了就重建"""
        if engine is None:
            raise RuntimeError("引擎未载入")
        if self._stream is None or self._stream_engine is not engine:
            self._stream = engine.create_stream()
            self._stream_engine = engine
            self._voice = None
        return self._stream

    def synth(self, text, voice=None, fmt="mp3", language="Chinese",
              temp=None, seed=None, speed=1.0):
        """返回 (音频字节, content-type)。串行执行，调用方不必加锁。"""
        from qwen3_tts_gguf.inference import TTSConfig

        engine = self.engine_provider()
        if engine is None:
            raise RuntimeError("引擎未载入")

        temp = self.temp if temp is None else temp
        seed = self.seed if seed is None else seed
        voice = voice or self.default_voice

        with self._lock:
            stream = self._stream_for(engine)

            want = self.resolve_voice(voice) if voice else None
            if want is not None and want.stem != self._voice:
                stream.set_voice(str(want))
                self._voice = want.stem
                self.log(f"切换音色 -> {want.name}")

            cfg = TTSConfig(max_steps=1024, temperature=temp, sub_temperature=temp,
                            seed=seed, sub_seed=seed + 3, streaming=False)
            t0 = time.time()
            result = stream.clone(text=text, language=language or "Chinese",
                                 zero_shot=False, config=cfg)
            gen = time.time() - t0

        audio = result.audio
        sr = int(getattr(result, "sample_rate", 24000))
        dur = len(audio) / sr if audio is not None else 0.0
        if audio is None:
            raise RuntimeError("合成结果为空")

        import numpy as np
        a = np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0)
        wav = _to_wav((a * 32767.0).astype("<i2").tobytes(), sr)

        fmt = (fmt or "mp3").lower()
        ctype, codec = _FORMAT_CTYPE.get(fmt, _FORMAT_CTYPE["mp3"])
        if codec is None:
            body = wav
        else:
            body = _ffmpeg(wav, codec, speed)

        self.log(f"合成 {dur:.2f}s 音频 / 用时 {gen:.2f}s / "
                 f"RTF {gen / dur if dur else 0:.2f} / {fmt} {len(body) / 1024:.0f}KB / "
                 f"voice={self._voice or '默认'} / {text[:20]}")
        return body, ctype

    # ---------- 启停 ----------

    @staticmethod
    def port_in_use(host, port):
        """探测端口是否已被监听。

        Windows 上 SO_REUSEADDR 允许重复绑定同一端口，HTTPServer 不会报错，
        结果是两个进程抢请求——必须先自己探一次。
        """
        probe = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            return s.connect_ex((probe, port)) == 0

    def start(self, host="127.0.0.1", port=8899):
        if self.running:
            raise RuntimeError("服务已在运行")
        if self.port_in_use(host, port):
            raise OSError(f"端口 {port} 已被占用")
        handler = self._make_handler()
        httpd = ThreadingHTTPServer((host, port), handler)   # 端口占用在此抛 OSError
        httpd.daemon_threads = True
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever,
                                        kwargs=dict(poll_interval=0.3), daemon=True)
        self._thread.start()
        self.log(f"服务已启动 {self.address}  端点 /v1/audio/speech")
        return self.address

    def stop(self):
        if not self.running:
            return
        httpd, self._httpd = self._httpd, None
        httpd.shutdown()          # 停 accept 循环
        httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        self.log("服务已停止")

    def dispose_stream(self):
        """页面卸载引擎前调用：丢掉缓存的 stream，避免拿着失效引擎"""
        self._stream = None
        self._stream_engine = None
        self._voice = None

    # ---------- HTTP ----------

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                server.log(f"{self.address_string()} {fmt % args}")

            def _send(self, code, body, ctype="application/json; charset=utf-8"):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _json(self, code, obj):
                self._send(code, json.dumps(obj, ensure_ascii=False))

            def do_GET(self):
                path = self.path.split("?")[0].rstrip("/") or "/"
                engine = server.engine_provider()
                if path in ("/health", "/healthz"):
                    return self._json(200, {"status": "ok" if engine else "loading",
                                            "engine": engine is not None,
                                            "voice": server.voice or server.default_voice,
                                            "model": server.model_name})
                if path in ("/v1/models", "/models"):
                    return self._json(200, {"object": "list", "data": [
                        {"id": server.model_name, "object": "model", "owned_by": "local"}]})
                if path in ("/v1/voices", "/voices", "/audio/voices"):
                    return self._json(200, {"object": "list", "data": server.voices()})
                if path == "/":
                    return self._json(200, {"service": "Qwen3-TTS GGUF", "model": server.model_name,
                                            "endpoint": "/v1/audio/speech"})
                return self._json(404, {"error": {"message": f"no route {path}"}})

            def do_POST(self):
                path = self.path.split("?")[0].rstrip("/")
                if path not in ("/v1/audio/speech", "/audio/speech"):
                    return self._json(404, {"error": {"message": f"no route {path}"}})
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(n) or b"{}")
                except Exception as e:
                    return self._json(400, {"error": {"message": f"bad json: {e}"}})
                if server.engine_provider() is None:
                    return self._json(503, {"error": {"message": "engine not ready"}})

                text = (payload.get("input") or payload.get("text") or "").strip()
                if not text:
                    return self._json(400, {"error": {"message": "missing input"}})
                try:
                    # 额外的可选字段：temperature / seed / language / speed，缺省走服务默认
                    temp = payload.get("temperature")
                    seed = payload.get("seed")
                    body, ctype = server.synth(
                        text,
                        voice=payload.get("voice"),
                        fmt=payload.get("response_format") or "mp3",
                        language=payload.get("language") or "Chinese",
                        temp=float(temp) if temp is not None else None,
                        seed=int(seed) if seed is not None else None,
                        speed=float(payload.get("speed") or 1.0),
                    )
                    return self._send(200, body, ctype)
                except Exception as e:
                    server.log("合成失败: " + repr(e))
                    server.log(traceback.format_exc()[:1200])
                    return self._json(500, {"error": {"message": f"{type(e).__name__}: {e}"}})

        return Handler


def _to_wav(pcm: bytes, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def _ffmpeg(wav: bytes, codec: str, speed: float = 1.0) -> bytes:
    """把 wav 转成目标格式；speed != 1 用 atempo 变速（不变调）"""
    import shutil
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("没找到 ffmpeg，无法输出该格式（可在请求里改用 wav）")
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0"]
    speed = max(0.25, min(4.0, float(speed or 1.0)))
    if abs(speed - 1.0) > 0.01:
        # atempo 单次只接受 0.5~2.0，超出拆成多级
        while speed > 2.0:
            args += ["-filter:a", "atempo=2.0"]
            speed /= 2.0
        while speed < 0.5:
            args += ["-filter:a", "atempo=0.5"]
            speed /= 0.5
        args += ["-filter:a", f"atempo={speed:.4f}"]
    # 输出选项必须在 -i 之后
    if codec in ("libmp3lame", "libopus", "aac"):
        args += ["-codec:a", codec, "-b:a", "96k", "-ac", "1"]
    args += ["-f", {"libmp3lame": "mp3", "libopus": "ogg", "aac": "adts",
                    "flac": "flac"}.get(codec, "mp3"), "pipe:1"]
    p = subprocess.run(args, input=wav, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 转码失败: {p.stderr.decode('utf-8', 'replace')[:300]}")
    return p.stdout
