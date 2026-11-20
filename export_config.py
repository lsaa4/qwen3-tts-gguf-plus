import os
from dataclasses import dataclass
from pathlib import Path

# 官方模型目录：优先环境变量 QWEN_MODEL_HOME，否则按常见位置自动探测
def _pick_model_home():
    env = os.environ.get("QWEN_MODEL_HOME")
    cands = [Path(env) if env else None,
             Path(r"D:\qwen3-tts\models"),
             Path.home() / ".cache/modelscope/hub/models/Qwen"]
    for c in cands:
        if c is not None and c.exists():
            return c
    return cands[-1]


model_home = _pick_model_home()
# 导出结果落在哪儿：默认项目根目录下的 model-base 等；
# QWEN_EXPORT_DIR 给了就精确用这个目录（一次导一个模型，不再自动追加子目录名）
dest_home = Path(__file__).parent
_explicit_dest = os.environ.get("QWEN_EXPORT_DIR")


def _dest(name):
    return Path(_explicit_dest) if _explicit_dest else dest_home / name

@dataclass
class ModelConfig:
    source: Path
    dest: Path

class Models:
    base = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-1.7B-Base',
        _dest('model-base')
    )
    custom = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-1.7B-CustomVoice',
        _dest('model-custom')
    )
    design = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-1.7B-VoiceDesign',
        _dest('model-design')
    )
    base_small = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-0.6B-Base',
        _dest('model-base-small')
    )
    custom_small = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-0.6B-CustomVoice',
        _dest('model-custom-small')
    )


# 默认导出哪个模型；export_model.py 会通过 QWEN_EXPORT_MODEL 指定
_ALIASES = {
    'base': Models.base,
    'custom': Models.custom,
    'design': Models.design,
    'base-small': Models.base_small,
    'custom-small': Models.custom_small,
}
_SEL = (os.environ.get('QWEN_EXPORT_MODEL') or 'base').strip().lower()
if _SEL not in _ALIASES:
    raise SystemExit(f"未知的 QWEN_EXPORT_MODEL: {_SEL}（可选 {'/'.join(_ALIASES)}）")

model = _ALIASES[_SEL]

MODEL_DIR  = model.source
EXPORT_DIR = model.dest
