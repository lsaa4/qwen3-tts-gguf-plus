"""cuda_dll.py - 让 onnxruntime 能找到 pip 安装的 CUDA 运行库 (nvidia-*-cu12 wheels)。

背景
----
onnxruntime-gpu 的 Windows 包不捆绑 cuBLAS / cuDNN / cuFFT，运行时按需
动态加载。`onnxruntime_providers_cuda.dll` 是以 LOAD_WITH_ALTERED_SEARCH_PATH
方式被加载的，因此 `os.add_dll_directory()` 注册的目录**不生效**，必须把
dll 目录前置进 `PATH` 才能解析依赖。

本项目在 pyproject 里固定使用 onnxruntime-gpu + nvidia-cu12 系列 wheel，
dll 位置为 `.venv/Lib/site-packages/nvidia/<lib>/bin/`。

必须在 `import onnxruntime` **之前** 调用 `ensure_cuda_dll_path()`。
"""
import os
import sys

from . import logger

# 记录已注册的目录，避免重复处理
_prepared = False


def _nvidia_bin_dirs():
    """返回 pip 安装的 nvidia 各库 bin 目录列表。"""
    roots = []
    # venv / 系统解释器的 site-packages
    for base in {sys.prefix, getattr(sys, "base_prefix", sys.prefix)}:
        sp = os.path.join(base, "Lib", "site-packages")
        if os.path.isdir(sp):
            roots.append(os.path.join(sp, "nvidia"))
        sp2 = os.path.join(base, "lib", "python%d.%d" % sys.version_info[:2],
                           "site-packages", "nvidia")
        if os.path.isdir(sp2):
            roots.append(sp2)

    dirs = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            b = os.path.join(root, name, "bin")
            if os.path.isdir(b):
                dirs.append(b)
    return dirs


def ensure_cuda_dll_path() -> list:
    """把 pip 的 CUDA dll 目录前置进 PATH（幂等）。返回实际注册的目录。"""
    global _prepared
    if _prepared:
        return []
    _prepared = True

    if os.name != "nt":
        return []

    dirs = _nvidia_bin_dirs()
    if not dirs:
        return []

    # PATH 前置：这是让 LOAD_WITH_ALTERED_SEARCH_PATH 生效的关键
    os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")
    # 兼容其它用 AddDllDirectory 的加载方式（如 PyTorch）
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except (OSError, AttributeError):
            pass

    logger.info(f"[CUDA] 已注册 {len(dirs)} 个 NVIDIA dll 目录")
    return dirs


def cuda_dll_present() -> bool:
    """粗查 pip 装的 CUDA 运行库是否齐全（cublas + cudnn + cufft）。"""
    dirs = _nvidia_bin_dirs()
    if not dirs:
        return False
    names = {os.path.basename(f).lower() for d in dirs for f in os.listdir(d)}
    need = ("cublaslt64", "cudnn64", "cufft64")
    return all(any(n.startswith(k) for n in names) for k in need)
