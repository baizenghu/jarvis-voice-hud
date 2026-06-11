# 主题:F5-TTS 接入(声音克隆 TTS)

2026-06-11 接入用户已有的本地 F5-TTS,作为 hermes 的 command-type TTS provider。

## 组成
- **F5 API 服务**:`/home/baizh/F5-TTS/api_server/api_server_gpu.py`,conda 环境 `f5-tts`,GPU(RTX 3060)。
  - 启动:`/home/baizh/anaconda3/envs/f5-tts/bin/python api_server_gpu.py --port 8002`(在 `api_server/` 目录下;nohup 后台)。
  - 端点:`POST /api/v1/tts`(multipart:`gen_text` + `ref_audio` 文件 + `ref_text`),返回 JSON 含 `audio_base64`(WAV)。
  - 模型缓存:`~/.cache/huggingface/hub/models--SWivid--F5-TTS/.../F5TTS_v1_Base/model_1250000.safetensors`。
- **桥接脚本**:`hud-app/f5_say.py`(仓库内)。hermes 以 `f5_say.py {input_path} {output_path}` 调用:读文本 →
  POST F5 API → 拿 WAV → ffmpeg 转 MP3 写到 `{output_path}`(转 MP3 是为了 HUD 按 `audio/mpeg` 正确播放)。
  - 参考音/文本用环境变量可换:`F5_REF_AUDIO`、`F5_REF_TEXT`、`F5_API`、`F5_NFE_STEP`。
  - 默认参考音 = F5 自带中文样本 `basic_ref_zh.wav`(文本「对,这就是我,万人敬仰的太乙真人。」)。

## hermes 配置(`~/.hermes/config.yaml`)
```yaml
tts:
  provider: f5
  providers:
    f5:
      type: command
      command: "/home/baizh/hermes-agent/.venv/bin/python /home/baizh/hermes-agent/hud-app/f5_say.py {input_path} {output_path}"
```

## 性能 / 取舍
- 单句 ~2.7–5s(扩散模型,比 Piper 慢;非流式)。质量/可克隆是其价值。
- 切回稳定快速:把 `tts.provider` 改回 `piper`(本地、近即时)即可,二者随时切换。

## 换"贾维斯"音色
给一段 5–10s 目标音色的清晰录音 + 其文字,设 `F5_REF_AUDIO` 指向它、`F5_REF_TEXT` 填文字即可,无需改代码。
相关:[../decisions](.) 与 ideas 里的"声音克隆"。
