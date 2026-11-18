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
dest_home = Path(__file__).parent

@dataclass
class ModelConfig:
    source: Path
    dest: Path

class Models:
    base = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-1.7B-Base',
        dest_home / 'model-base'
    )
    custom = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-1.7B-CustomVoice',
        dest_home / 'model-custom'
    )
    design = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-1.7B-VoiceDesign',
        dest_home / 'model-design'
    )
    base_small = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-0.6B-Base',
        dest_home / 'model-base-small'
    )
    custom_small = ModelConfig(
        model_home / 'Qwen3-TTS-12Hz-0.6B-CustomVoice',
        dest_home / 'model-custom-small'
    )


model = Models.base

MODEL_DIR  = model.source
EXPORT_DIR = model.dest
