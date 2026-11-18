"""
Qwen3-TTS GGUF 图形界面（ttkbootstrap）——组装层。

- 克隆 / 自定义音色 / 音色设计 Tab：各自载入区（模型/后端/上下文）+ 推理区
- 服务 Tab：载入区 + OpenAI 兼容 HTTP 接口的启停
- 设置 Tab：全局开关（如单模型模式）
- 日志 Tab：只读日志 + 清除

各模式走批量生成，不做流式。页面实现拆在 clone_tab / custom_tab / design_tab /
settings_tab / log_tab，此处只做样式与组装。
"""
import tkinter as tk
import tkinter.font as tkfont

import ttkbootstrap as ttkb
from ttkbootstrap.constants import *

from .i18n import set_lang, load_config, t
from .clone_tab import CloneTab
from .custom_tab import CustomTab
from .design_tab import DesignTab
from .service_tab import ServiceTab
from .tools_tab import ToolsTab
from .settings_tab import SettingsTab
from .log_tab import LogTab

UI_SCALE = 1.25        # 整体缩放系数
DEBUG_TOPMOST = False  # 调试阶段可置 True 让窗口保持前台

ACCENT = "#2c3e50"        # 顶部标题条 / 选中 tab
ACCENT_SOFT = "#0e7490"   # 分组标题
BORDER = "#d5dbdf"

APP_TITLE = "Qwen3-TTS GGUF"
APP_SUB = "llama.cpp Vulkan · ONNX DirectML"


def pad_title(title, width=6):
    """用全角空格把 tab 标题补到同样宽度，使各 tab 等宽"""
    pad = width - len(title)
    return "　" * (pad // 2) + title + "　" * (pad - pad // 2)


def ui_font(size=10, bold=False):
    """挑一个系统里真实存在的中文字体，避免非 Windows 平台退回等宽字体"""
    weight = "bold" if bold else "normal"
    have = set(tkfont.families())
    for name in ("微软雅黑", "Microsoft YaHei UI", "Microsoft YaHei",
                 "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", "Segoe UI"):
        if name in have:
            return (name, size, weight)
    return (tkfont.nametofont("TkDefaultFont").actual("family"), size, weight)


def init_style(root):
    """分组框描边 + 标题着色 + 顶部标题条，否则 flatly 下 Labelframe 只剩一行悬空文字"""
    style = ttkb.Style.get_instance()
    style.configure("TLabelframe", borderwidth=1, relief="solid", bordercolor=BORDER)
    style.configure("TLabelframe.Label", foreground=ACCENT_SOFT, font=ui_font(10, True))
    style.configure("Header.TFrame", background=ACCENT)
    style.configure("HeaderTitle.TLabel", background=ACCENT, foreground="#ffffff",
                    font=ui_font(13, True))
    style.configure("HeaderSub.TLabel", background=ACCENT, foreground="#a9bccd",
                    font=ui_font(9))
    # ttkbootstrap 的 bootstyle 会生成 success.TButton 之类样式名；
    # 直接把字体加粗配在这些样式上，别另建 style，否则会盖掉颜色
    for name in ("success.TButton", "primary.TButton", "danger.TButton",
                 "secondary.Outline.TButton", "info.TButton"):
        style.configure(name, font=ui_font(10, True))
    style.configure("Status.TLabel", font=ui_font(9))
    style.configure("TNotebook.Tab", padding=(22, 8), font=ui_font(10))
    style.configure("TEntry", padding=(6, 4))
    style.configure("TCombobox", padding=(6, 4))


def build_header(app):
    """顶部深色标题条：左侧项目名，右侧后端说明"""
    bar = ttkb.Frame(app, style="Header.TFrame", padding=(16, 9))
    bar.pack(side=TOP, fill=X)
    ttkb.Label(bar, text=APP_TITLE, style="HeaderTitle.TLabel").pack(side=LEFT)
    ttkb.Label(bar, text=APP_SUB, style="HeaderSub.TLabel").pack(side=RIGHT)
    return bar


def highlight_active_tab():
    """选中 tab 用普通按钮同款深色。必须等 Notebook 创建完再调——ttkbootstrap 建控件时会重刷样式"""
    style = ttkb.Style.get_instance()
    style.map("TNotebook.Tab", background=[("selected", "#2c3e50")], foreground=[("selected", "#ffffff")])


def pick_scale(screen_h):
    """按屏幕高度挑整体缩放系数。

    高 DPI 屏上 tk scaling 已经把字体放大了，再固定乘 1.25 会把内容顶出屏幕
    （1080p + 150% 缩放下逻辑高度只有 720，内容需要 1100+，底部状态栏直接被挤没）。
    """
    if screen_h >= 1150:
        return 1.25
    if screen_h >= 950:
        return 1.10
    if screen_h >= 800:
        return 1.00
    return 0.90


def main():
    set_lang(load_config())  # 组装控件前读好字典，重启切语言
    app = ttkb.Window(title=APP_TITLE, themename="flatly")
    # 在系统 DPI 给定的 scaling 基础上按系数放大（字体与以字符计宽的控件同步变大）
    base = float(app.tk.call("tk", "scaling"))
    app.tk.call("tk", "scaling", base * pick_scale(app.winfo_screenheight()))
    init_style(app)
    if DEBUG_TOPMOST:
        app.attributes("-topmost", True)

    build_header(app)

    # 状态栏与分隔线先 pack(side=BOTTOM) 占位，Notebook 再吃剩余高度。
    # 用 grid 的话窗口一矮，Tk 会从最后一行开始裁，状态栏第一个被裁掉
    bar = ttkb.Frame(app, padding=(14, 4))
    bar.pack(side=BOTTOM, fill=X)
    ttkb.Separator(app).pack(side=BOTTOM, fill=X)

    nb = ttkb.Notebook(app)
    nb.pack(fill=BOTH, expand=True, padx=10, pady=(8, 4))

    clone_tab = CloneTab(nb)
    custom_tab = CustomTab(nb)
    design_tab = DesignTab(nb)
    service_tab = ServiceTab(nb)
    tools_tab = ToolsTab(nb)
    settings_tab = SettingsTab(nb)
    log_tab = LogTab(nb)
    tabs = [
        (clone_tab, t("app.tab_clone")),
        (custom_tab, t("app.tab_custom")),
        (design_tab, t("app.tab_design")),
        (service_tab, t("app.tab_service")),
        (tools_tab, t("app.tab_tools")),
        (settings_tab, t("app.tab_settings")),
        (log_tab, t("app.tab_log")),
    ]
    for tab, title in tabs:
        nb.add(tab, text=pad_title(title))
    highlight_active_tab()

    # 底部状态栏: 状态文字 + 进度条
    status_var = tk.StringVar(value=t("app.ready"))
    ttkb.Label(bar, textvariable=status_var, style="Status.TLabel").pack(side=LEFT)
    progress = ttkb.Progressbar(bar, mode="determinate", length=240, bootstyle=SUCCESS)
    progress.pack(side=RIGHT)

    # 带引擎的页（含工具页）：共用状态栏/进度条/日志，参与单模型互斥与关窗收尾
    eng_tabs = (clone_tab, custom_tab, design_tab, service_tab, tools_tab)

    for tab in eng_tabs:
        tab.bind_feedback(status_var, progress, log_tab)

    def unload_others(current):
        """单模型模式: 在 current 页启动载入前，卸载其他页已载入的引擎。

        生成中/载入中的页跳过（生成中卸载是 use-after-free，载入中无法中断）。
        """
        if not settings_tab.single_model.get():
            return
        for page in eng_tabs:
            if page is not current and page.engine is not None and not page.generating and not page.loading:
                page.on_load_toggle(evict=True)

    for page in eng_tabs:
        page.unload_others = unload_others

    def on_close():
        for tab in eng_tabs:
            tab.shutdown()   # 停止生成 -> 卸载引擎
        app.destroy()

    # 显式接管关窗：先停生成/卸载引擎，destroy 后 _poll 由 winfo_exists 断开轮询链
    app.protocol("WM_DELETE_WINDOW", on_close)

    # 页面内容装在 ScrollPage 里，窗口自身的请求高度不再反映内容，
    # 所以宽度取最宽页面的真实内容宽，高度给一个舒适下限，剩下的看滚动
    app.update_idletasks()
    need_w = [app.winfo_reqwidth()]
    for tab, _title in tabs:
        sc = getattr(tab, "scroller", None)
        if sc is not None:
            need_w.append(sc.body.winfo_reqwidth() + 60)
    w = min(max(need_w), app.winfo_screenwidth() - 40)
    h = min(max(app.winfo_reqheight(), 780), app.winfo_screenheight() - 80)
    app.geometry(f"{w}x{h}")

    app.mainloop()
