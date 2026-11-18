"""可滚动页面容器。

1080p + 150% DPI 的 Windows 上，Tk 认为屏幕只有 720 逻辑像素高，而本界面
（标题条 + 标签栏 + 载入区 + 推理区 + 状态栏）需要 800 以上，硬塞会把参数区
和状态栏顶出窗口。这里给每个标签页套一层 Canvas 视口：

    sp = ScrollPage(tab)
    sp.pack(fill=BOTH, expand=True)
    在 sp.body 里摆控件（它就是一个普通 Frame）

内容不高时滚动条完全隐藏，高了才出现。滚轮只绑在非自滚动控件上，
文本框、下拉框、日志区自己的滚动不受影响。
"""
import tkinter as tk

import ttkbootstrap as ttkb
from ttkbootstrap.constants import *

# 这些控件自带滚动，滚轮不该转发给外层 Canvas
_SELF_SCROLL = {"Text", "Listbox", "TCombobox", "Treeview", "TScrollbar"}


class ScrollPage(ttkb.Frame):
    """带垂直滚动的页面容器，内容放在 .body 里。"""

    def __init__(self, master, padding=14, **kwargs):
        super().__init__(master, **kwargs)

        self.canvas = ttkb.Canvas(self, highlightthickness=0, borderwidth=0, takefocus=0)
        self.vbar = ttkb.Scrollbar(self, orient=VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll)

        self.canvas.grid(row=0, column=0, sticky=NSEW)
        self.vbar.grid(row=0, column=1, sticky=NS)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.body = ttkb.Frame(self.canvas, padding=padding)
        self._win = self.canvas.create_window(0, 0, anchor=NW, window=self.body)
        self.body.bind("<Configure>", self._sync_region)
        self.canvas.bind("<Configure>", self._fit_width)

        self._bar_shown = False
        self.vbar.grid_remove()
        self.after(100, self._bind_wheel)

    # ---------- 内部同步 ----------

    def _sync_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_width(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_scroll(self, first, last):
        self.vbar.set(first, last)
        need = not (float(first) <= 0.0 and float(last) >= 1.0)
        if need != self._bar_shown:
            self._bar_shown = need
            if need:
                self.vbar.grid()
            else:
                self.vbar.grid_remove()

    # ---------- 滚轮 ----------

    def _enabled(self):
        return self._bar_shown

    def _bind_wheel(self):
        for w in self._walk(self.canvas):
            if w.winfo_class() in _SELF_SCROLL:
                continue
            w.bind("<MouseWheel>", self._on_wheel, add="+")
            w.bind("<Button-4>", self._on_wheel, add="+")
            w.bind("<Button-5>", self._on_wheel, add="+")

    def _walk(self, w):
        yield w
        for c in w.winfo_children():
            yield from self._walk(c)

    def _on_wheel(self, event):
        if not self._enabled():
            return
        if getattr(event, "num", None) == 4:
            step = -3
        elif getattr(event, "num", None) == 5:
            step = 3
        else:
            step = -3 if event.delta > 0 else 3
        self.canvas.yview_scroll(step, UNITS)

    # ---------- 便捷方法 ----------

    def scroll_top(self):
        self.canvas.yview_moveto(0.0)
