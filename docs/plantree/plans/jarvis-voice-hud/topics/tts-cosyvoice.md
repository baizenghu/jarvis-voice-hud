# CosyVoice 调参记录(在 /home/baizh/CosyVoice,不在 hermes git)

`cosyvoice/cli/frontend.py` 中文 split_paragraph 参数改为:
`token_max_n=50, token_min_n=30, merge_len=20, comma_split=True`(原 80/60/False)。

原因(源码分析):
- inference_zero_shot 内部用 text_frontend 分段;默认 comma_split=False 使长逗号句(无句号)
  被当一整段(最长 80 token)喂入 AR → 易重复。
- inference_zero_shot 对"段落 < 0.5×参考文本长度"会警告"性能差"→ 太短的段会幻觉。
  参考文本 ~50 字,故段需 ≥25 字;token_min_n=30 保证不低于该阈值。
- 数字归一化由 CosyVoice wetext 前端完成(text_frontend=True),勿外部拆分绕过它。

服务端 hud-app/cosyvoice_server.py 已撤掉外部拆分,整段交给 inference_zero_shot。
若 CosyVoice 仓库更新会覆盖此改动,需重新应用。
