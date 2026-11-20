把官方模型整个文件夹放进这里，一个模型一个文件夹：

  models\
    Qwen3-TTS-12Hz-1.7B-Base\           <- model.safetensors / config.json / speech_tokenizer\ ...
    Qwen3-TTS-12Hz-1.7B-CustomVoice\
    Qwen3-TTS-12Hz-0.6B-Base\

然后双击 export-model.bat，脚本会先来这里找，不用设环境变量、也不用搬来搬去。

这个目录不进 git，放多大都行（1.7B 模型约 4.2 GB）。
