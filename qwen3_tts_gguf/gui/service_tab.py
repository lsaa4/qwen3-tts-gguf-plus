"""服务页：把已载入的引擎开成 OpenAI 兼容的 HTTP 接口。

载入区与其它页一致（模型 / 上下文 / 设备），下面接服务控制：监听地址、端口、
默认音色、启停按钮、端点提示。服务实现见 qwen3_tts_gguf/service.py，命令行入口
tts_server.py 用的是同一份。

鸭子类型兼容 app.py 的 eng_tabs：暴露 engine / generating / loading /
on_load_toggle / bind_feedback / shutdown，因此自动参与单模型互斥与关窗收尾。
这里 generating 语义是「服务运行中」——占用引擎，别的页不该把它顶掉。
"""
import queue
import threading
import time
import tkinter as tk
import webbrowser

import ttkbootstrap as ttkb
from ttkbootstrap.constants import *

from qwen3_tts_gguf import logger
from qwen3_tts_gguf.inference import TTSEngine
from qwen3_tts_gguf.service import SpeechServer
from .scroll_page import ScrollPage

from .base_tab import LLM_DEVICES, ONNX_PROVIDERS, _hook_drop_folder
from .i18n import t


class ServiceTab(ttkb.Frame):
    """载入引擎 + 启停 HTTP 服务"""

    MODEL_DEFAULT = "model-base"

    def __init__(self, master):
        super().__init__(master)
        self.scroller = ScrollPage(self)
        self.scroller.pack(fill=BOTH, expand=True)
        self.page = self.scroller.body
        self.page.columnconfigure(0, weight=1)
        self.page.rowconfigure(1, weight=1)

        self.engine = None
        self.loading = False
        self.ui_queue = queue.Queue()
        self.server = SpeechServer(engine_provider=lambda: self.engine,
                                   voice_dir="output/elaborate",
                                   log=lambda m: self.ui_queue.put(("log", m)))

        self._build_load_group()
        self._build_service_group()

    # ---------- 与其它页一致的属性 ----------

    @property
    def generating(self):
        """服务运行中 = 占用引擎，单模型互斥据此跳过卸载"""
        return self.server.running

    # ---------- 载入区 ----------

    def _build_load_group(self):
        group = ttkb.Labelframe(self.page, text=t("load.group"), padding=8)
        group.grid(row=0, column=0, sticky=EW)
        group.columnconfigure(1, weight=1)

        ttkb.Label(group, text=t("load.model_folder")).grid(row=0, column=0, sticky=W, padx=(0, 10), pady=4)
        self.model_dir = tk.StringVar(value=self.MODEL_DEFAULT)
        self.model_entry = ttkb.Entry(group, textvariable=self.model_dir)
        self.model_entry.grid(row=0, column=1, sticky=EW, pady=4)
        _hook_drop_folder(self.model_entry, self.model_dir)
        ttkb.Button(group, text=t("load.browse"), command=self.on_browse_model, width=14) \
            .grid(row=0, column=2, padx=(8, 0), pady=4)

        opt_row = ttkb.Frame(group)
        opt_row.grid(row=1, column=0, columnspan=2, sticky=EW, pady=4)
        ttkb.Label(opt_row, text=t("load.n_ctx")).pack(side=LEFT, padx=(0, 10))
        self.n_ctx = tk.StringVar(value="512")
        self.n_ctx_entry = ttkb.Entry(opt_row, textvariable=self.n_ctx, width=8)
        self.n_ctx_entry.pack(side=LEFT, padx=(0, 24))
        ttkb.Label(opt_row, text=t("load.llm_device")).pack(side=LEFT, padx=(0, 10))
        self.llm_device = tk.StringVar(value=LLM_DEVICES[0])
        self.llm_combo = ttkb.Combobox(opt_row, textvariable=self.llm_device, values=LLM_DEVICES,
                                       state="readonly", width=8)
        self.llm_combo.pack(side=LEFT, padx=(0, 24))
        ttkb.Label(opt_row, text=t("load.onnx")).pack(side=LEFT, padx=(0, 10))
        self.onnx_provider = tk.StringVar(value=ONNX_PROVIDERS[0])
        self.onnx_combo = ttkb.Combobox(opt_row, textvariable=self.onnx_provider, values=ONNX_PROVIDERS,
                                        state="readonly", width=9)
        self.onnx_combo.pack(side=LEFT)
        self._load_fields = [self.model_entry, self.n_ctx_entry, self.llm_combo, self.onnx_combo]

        self.load_btn = ttkb.Button(group, text=t("load.load"), command=self.on_load_toggle,
                                    width=12, bootstyle=SUCCESS)
        self.load_btn.grid(row=1, column=2, sticky=E, pady=4)

    # ---------- 服务控制区 ----------

    def _build_service_group(self):
        group = ttkb.Labelframe(self.page, text=t("service.group"), padding=8)
        group.grid(row=1, column=0, sticky=NSEW, pady=(10, 0))
        group.columnconfigure(1, weight=1)
        group.rowconfigure(4, weight=1)

        # 监听地址 + 端口
        row0 = ttkb.Frame(group)
        row0.grid(row=0, column=0, columnspan=3, sticky=EW, pady=3)
        ttkb.Label(row0, text=t("service.host")).pack(side=LEFT, padx=(0, 8))
        self.host = tk.StringVar(value="127.0.0.1")
        ttkb.Entry(row0, textvariable=self.host, width=16).pack(side=LEFT, padx=(0, 24))
        ttkb.Label(row0, text=t("service.port")).pack(side=LEFT, padx=(0, 8))
        self.port = tk.StringVar(value="8899")
        ttkb.Entry(row0, textvariable=self.port, width=8).pack(side=LEFT, padx=(0, 24))
        ttkb.Label(row0, text=t("service.temp")).pack(side=LEFT, padx=(0, 8))
        self.temp = tk.StringVar(value="0.6")
        ttkb.Entry(row0, textvariable=self.temp, width=6).pack(side=LEFT, padx=(0, 24))
        ttkb.Label(row0, text=t("service.seed")).pack(side=LEFT, padx=(0, 8))
        self.seed = tk.StringVar(value="42")
        ttkb.Entry(row0, textvariable=self.seed, width=6).pack(side=LEFT)

        # 音色目录
        row1 = ttkb.Frame(group)
        row1.grid(row=1, column=0, columnspan=3, sticky=EW, pady=3)
        ttkb.Label(row1, text=t("service.voice_dir")).pack(side=LEFT, padx=(0, 8))
        self.voice_dir = tk.StringVar(value="output/elaborate")
        self.voice_entry = ttkb.Entry(row1, textvariable=self.voice_dir)
        self.voice_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        _hook_drop_folder(self.voice_entry, self.voice_dir)
        ttkb.Button(row1, text=t("load.browse"), command=self.on_browse_voice_dir, width=10) \
            .pack(side=LEFT, padx=(0, 8))
        # 音色目录一改就重扫：默认音色下拉跟着变
        self.voice_dir.trace_add("write", lambda *a: self.refresh_voices())

        # 默认音色 + 启停按钮
        row2 = ttkb.Frame(group)
        row2.grid(row=2, column=0, columnspan=3, sticky=EW, pady=3)
        ttkb.Label(row2, text=t("service.default_voice")).pack(side=LEFT, padx=(0, 8))
        self.voice = tk.StringVar(value="")
        self.voice_combo = ttkb.Combobox(row2, textvariable=self.voice, values=[], width=24)
        self.voice_combo.pack(side=LEFT, padx=(0, 16))
        ttkb.Button(row2, text=t("service.rescan"), command=self.refresh_voices, width=10) \
            .pack(side=LEFT, padx=(0, 16))
        self.stop_btn = ttkb.Button(row2, text=t("service.stop"), command=self.on_stop,
                                    width=13, bootstyle=DANGER, state="disabled")
        self.stop_btn.pack(side=RIGHT)
        self.start_btn = ttkb.Button(row2, text=t("service.start"), command=self.on_start,
                                     width=13, bootstyle=SUCCESS, state="disabled")
        self.start_btn.pack(side=RIGHT, padx=(0, 8))

        # 状态行
        self.state_var = tk.StringVar(value=t("service.idle"))
        ttkb.Label(group, textvariable=self.state_var, font=("微软雅黑", 10, "bold"),
                   foreground="#0e7490").grid(row=3, column=0, columnspan=3, sticky=W, pady=(8, 3))

        # 端点提示 + 复制
        tips = ttkb.Labelframe(group, text=t("service.endpoints"), padding=6)
        tips.grid(row=4, column=0, columnspan=3, sticky=NSEW, pady=(3, 0))
        tips.columnconfigure(0, weight=1)
        tips.rowconfigure(0, weight=1)
        self.tip_text = tk.Text(tips, height=5, wrap="none", relief="flat", padx=6, pady=4,
                                highlightthickness=1, highlightbackground="#c9c9c9",
                                highlightcolor="#1a7f8e")
        self.tip_text.grid(row=0, column=0, sticky=NSEW)
        self._update_tips()
        btn_bar = ttkb.Frame(tips)
        btn_bar.grid(row=1, column=0, sticky=EW, pady=(6, 0))
        ttkb.Button(btn_bar, text=t("service.copy_curl"), command=self.on_copy_curl, width=14) \
            .pack(side=LEFT)
        self.open_btn = ttkb.Button(btn_bar, text=t("service.open_health"), command=self.on_open_health,
                                    width=14, state="disabled")
        self.open_btn.pack(side=LEFT, padx=(8, 0))

        self.refresh_voices()

    # ---------- 音色 ----------

    def refresh_voices(self):
        self.server.voice_dir = self.voice_dir.get().strip() or "output/elaborate"
        names = self.server.voices()
        self.voice_combo.configure(values=names)
        if names and self.voice.get() not in names:
            # 优先选名字里带「巧克力」的，否则第一个
            self.voice.set(next((n for n in names if "巧克力" in n), names[0]))
        elif not names:
            self.voice.set("")

    def on_browse_voice_dir(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(title=t("service.pick_voice_dir"))
        if path:
            self.voice_dir.set(path)

    # ---------- 载入/卸载 ----------

    def on_browse_model(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(title=t("load.pick_model_dir"))
        if path:
            self.model_dir.set(path)

    def unload_others(self, current):
        """app.py 注入的单模型互斥钩子（保持接口一致）"""
        pass

    def on_load_toggle(self, evict=False):
        if self.loading:
            return
        if self.engine is not None:
            if self.server.running:
                self.on_stop()
            self.server.dispose_stream()
            self.engine.shutdown()
            self.engine = None
            self._set_loaded(False)
            if not evict:
                self.ui_queue.put(("status", t("load.unloaded")))
            return
        self.unload_others(self)
        self.load_btn.configure(state="disabled")
        self.loading = True
        self.ui_queue.put(("status", t("load.loading")))
        threading.Thread(target=self._load_worker,
                         kwargs=dict(model_dir=self.model_dir.get(),
                                     llm=self.llm_device.get(),
                                     onnx=self.onnx_provider.get()),
                         daemon=True).start()

    def _load_worker(self, model_dir, llm, onnx):
        try:
            t0 = time.time()
            eng = TTSEngine(model_dir=model_dir, onnx_provider=onnx,
                            llm_use_gpu=(llm == "GPU"), subprocess_decoder=False, chunk_size=64)
            self.engine = eng or None
            self.ui_queue.put(("loaded", bool(eng)))
            if eng:
                self.ui_queue.put(("status", t("load.engine_ready").format(sec=f"{time.time() - t0:.1f}")))
            else:
                self.ui_queue.put(("status", t("load.load_failed")))
        except Exception as e:
            self.engine = None
            logger.exception("载入失败")
            self.ui_queue.put(("loaded", False))
            self.ui_queue.put(("error", t("load.load_error").format(msg=e)))
        finally:
            self.loading = False

    def _set_loaded(self, ok):
        self.load_btn.configure(text=t("load.unload") if ok else t("load.load"), state="normal")
        for w in self._load_fields:
            w.configure(state="disabled" if ok else "normal")
        if not self.server.running:
            self.start_btn.configure(state="normal" if ok else "disabled")

    # ---------- 服务启停 ----------

    def on_start(self):
        if self.engine is None:
            self.ui_queue.put(("error", t("service.need_engine")))
            return
        try:
            port = int(self.port.get())
        except ValueError:
            self.ui_queue.put(("error", t("service.bad_port")))
            return
        try:
            self.server.temp = float(self.temp.get())
            self.server.seed = int(self.seed.get())
        except ValueError:
            self.ui_queue.put(("error", t("gen.param_error")))
            return
        self.server.default_voice = self.voice.get().strip()
        self.start_btn.configure(state="disabled")
        threading.Thread(target=self._start_worker, args=(self.host.get().strip(), port),
                         daemon=True).start()

    def _start_worker(self, host, port):
        try:
            addr = self.server.start(host, port)
            self.ui_queue.put(("started", addr))
        except OSError as e:
            self.ui_queue.put(("error", t("service.port_busy").format(port=port, msg=e)))
            self.ui_queue.put(("started", ""))
        except Exception as e:
            self.ui_queue.put(("error", f"{type(e).__name__}: {e}"))
            self.ui_queue.put(("started", ""))

    def on_stop(self):
        self.stop_btn.configure(state="disabled")
        try:
            self.server.stop()
        except Exception as e:
            self.ui_queue.put(("error", f"{type(e).__name__}: {e}"))
        self.stop_btn.configure(state="disabled")
        self.start_btn.configure(state="normal" if self.engine is not None else "disabled")
        self.open_btn.configure(state="disabled")
        self.state_var.set(t("service.idle"))

    def _on_started(self, addr):
        if addr:
            self.state_var.set(t("service.running").format(addr=addr))
            self.stop_btn.configure(state="normal")
            self.open_btn.configure(state="normal")
            self._update_tips(addr)
            # 默认音色在启服务时落到 stream 上：首个请求才会真正切，这里只记日志
            if self.server.default_voice:
                self.server.log(t("service.default_voice_log").format(name=self.server.default_voice))
        else:
            self.start_btn.configure(state="normal" if self.engine is not None else "disabled")
            self.state_var.set(t("service.idle"))

    def on_open_health(self):
        if self.server.running:
            webbrowser.open(self.server.address + "/health")

    def on_copy_curl(self):
        addr = self.server.address or f"http://{self.host.get()}:{self.port.get()}"
        voice = self.voice.get() or "default"
        curl = (f'curl -X POST {addr}/v1/audio/speech -H "Content-Type: application/json" '
                f'-d \'{{"input":"你好，世界","voice":"{voice}","response_format":"mp3"}}\' -o out.mp3')
        self.clipboard_clear()
        self.clipboard_append(curl)
        self.ui_queue.put(("status", t("service.copied")))

    def _update_tips(self, addr=""):
        addr = addr or f"http://{self.host.get()}:{self.port.get()}"
        voice = self.voice.get() or "…"
        lines = [
            f"POST {addr}/v1/audio/speech",
            f'{{"input": "你好，世界", "voice": "{voice}", "response_format": "mp3"}}',
            "",
            t("service.tip_clients"),
        ]
        self.tip_text.configure(state="normal")
        self.tip_text.delete("1.0", "end")
        self.tip_text.insert("1.0", "\n".join(lines))
        self.tip_text.configure(state="disabled")

    # ---------- 事件管道 ----------

    def bind_feedback(self, status_var, progress, log_tab):
        self.status_var = status_var
        self.progress = progress
        self.log_tab = log_tab
        self.after(100, self._poll)

    def _poll(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                ev = self.ui_queue.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self.log_tab.append(ev[1])
                elif kind == "status":
                    self.status_var.set(ev[1])
                elif kind == "loaded":
                    self._set_loaded(ev[1])
                elif kind == "started":
                    self._on_started(ev[1])
                elif kind == "error":
                    self.log_tab.append(f"{ev[1]}")
                    self.status_var.set(f"{ev[1]}")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ---------- 收尾 ----------

    def shutdown(self):
        try:
            self.server.stop()
        except Exception:
            pass
        self.server.dispose_stream()
        if self.engine is not None:
            self.engine.shutdown()
            self.engine = None
