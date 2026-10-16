# 节点兼容性审核（2026-10-16）

本轮逐项检查了全部 17 个注册节点的 V1 声明、函数参数、控件默认值与范围、
输入输出类型、缺失输入、懒求值、缓存约定、预览及前端序列化。发现的问题已修复。
未改变节点 ID、输入名称或输出槽位。

## 实际验证环境

- ComfyUI `29e28e2b` / `0.41.0`，前端 `1.55.14`，Python 3.11.13、PyTorch 2.8.0，macOS CPU。
- 使用临时 base directory 和独立端口，仅装入当前插件及测试节点；未修改原 ComfyUI 安装。
- 使用本机已有 SDXL checkpoint 运行文生图、图生图及缓存切换测试。
- 使用已有本地 `fsmn-vad` 模型验证正常 VAD 推理和二次裁剪；未下载新模型。
- 264 项 Python 测试通过（208 项单元测试、56 项真实服务集成测试）；
  1 项外部 LLM 测试因未设置凭据而跳过。21 项前端回归测试通过。
- 浏览器内创建并保存/恢复了全部 17 个节点；确认负数参数及片段 JSON 保持不变，
  API prompt 不含播放器和编辑按钮等纯前端控件。

前端版本低于该 ComfyUI checkout 推荐的 `1.55.17`，未擅自升级环境；
上述结果针对已安装版本，不代表所有历史或未来版本。

## 逐节点结果

| 节点 | 核对重点与结果 |
|---|---|
| Optional Image | 可省略 IMAGE；返回同一对象或 None，并输出 BOOLEAN。缺失值可接懒分支，不能直接送入需要真实图像的节点。 |
| Optional Load Image | none/allow_none、官方图像和 MASK 解码、上传控件、文件内容哈希、文件校验正常；真实工作流覆盖切换、替换、重复执行。 |
| Optional Load Video | VIDEO/BOOLEAN/IMAGE/INT/AUDIO 输出声明与实际结果一致；使用官方视频对象及 mtime 指纹。为提供 images 等输出，选择文件后会解码全部帧，这是现有设计的内存成本。 |
| Optional Video Preview | OUTPUT_NODE、可选懒 VIDEO、官方预览协议正常；修复跳过时未显式返回空 images UI 的问题。 |
| Optional Load Audio | 输出 AUDIO [batch, channels, samples]、采样率和秒数符合官方加载器。补齐 none 的播放器清理，保留官方上传回调。 |
| Optional Audio Preview | 修复未注入 AUDIO_UI 播放器、空输入留下旧播放器、零采样音频进入编码器报错的问题。空音频原样输出，UI 清空。 |
| Quick Audio Edit | 修复前端默认 min=0 阻止负起始时间与负增益；起始时间支持正负，duration/fade 明确宽范围上限。volume_db 范围为 −120 到 +60 dB，避免原默认最大值 2048 dB 产生 Inf；单采样淡入/淡出也会生效。 |
| FunASR Transcribe | 修复 bfloat16/带梯度张量转 NumPy、空音频加载模型、多 batch 静默忽略的问题。要求 batch=1，声道混为 mono，fs 参数传入原采样率。文本及模型时间戳输出保持兼容。 |
| VAD Auto Trim Audio | 同样处理 dtype、空音频与 batch；padding 后合并重叠区，避免重复拼接。按照输出 JSON 的三位小数边界裁剪，确保直接输出和二次裁剪一致。 |
| Audio Trim by Segments | 修复非列表、畸形条目、NaN/Infinity 等输入被忽略或产生低层异常的问题；保留尾逗号、对象形式、排序和手动重叠片段重复拼接的行为。编辑按钮同时禁用工作流值序列化及 API prompt 序列化。无需 FunASR。 |
| LLM API Call | 修复 URL/模型名前后空白、空配置、非 HTTP(S) 端点、超时和非法文本结构的错误处理；finish_reason=length 时拒绝把截断回复当作完整结果。真实执行通过本地 mock 的 /chat/completions 服务验证。 |
| Text Translate | 必需/可选字段与函数默认参数匹配；真实执行验证省略可选 LLM 控件及空白 Google 输入。Google 分段/请求/响应使用单元测试；LLM 模式继承上述客户端修复。 |
| Has Image | 只以 None 判断缺失，黑图及空 batch 不会误判。可选输入、BOOLEAN 输出正常。 |
| Lazy Image Switch | 两个分支必需且 lazy，condition 非懒。真实执行证明未选中的报错分支不会运行；选中报错分支仍会失败。 |
| Lazy Latent Switch | 完整透传 LATENT 字典；真实 checkpoint 和无需模型的专用 LATENT 输出测试均覆盖懒执行。 |
| Lazy Video Switch | VIDEO 分支、懒求值与 None 透传符合执行引擎；未选中的报错分支被跳过。 |
| Lazy Any Switch | 官方 * 通配类型可连接不同类型，选中值原样返回。真实执行覆盖存在检测与字符串分支；通配并不保证下游能消费所选类型。 |

## 保留的约定和验证边界

- `condition` 未指定默认值时，官方 BOOLEAN 控件默认 False，属于有效声明。
  懒开关的两个分支仍需连接；“不执行”不意味着“无需通过结构和类型校验”。
- 未评估的懒输入及真实 None 都可能传入 `check_lazy_status`；官方执行引擎会过滤
  已评估的输入，因此不会因选中分支返回 None 而无限请求。
- 图像/音频加载器用内容哈希，视频用官方相同的 mtime 规则。LLM 和翻译遵循
  ComfyUI 默认缓存，输入不变可能复用结果；没有强制每次访问网络。
- FunASR 模型时间戳可能按字或词，不能保证与输出文本（尤其是标点）逐字符对应。
  不支持时间戳的模型可返回空列表。本机没有对应 ASR 模型，本轮未执行真实转写推理；
  该路径使用模型替身测试，VAD 则执行了真实缓存模型。
- 外部商业 LLM、Google 非官方翻译的线上可用性不在本轮通过范围内。
  Google 仍依赖网络和服务限流；本地 mock 仅证明兼容协议及节点执行。
- 可视化编辑器需要原始文件加载器（允许 Reroute），不跨越改变音频时间轴的节点；
  浏览器不能解码的格式需先提取 WAV。后端音视频编解码继续委托 ComfyUI。

## 复查命令

```bash
pytest tests -m 'not integration'
node --test tests/web/*.test.cjs
COMFYUI_URL=http://127.0.0.1:8188 pytest tests -m integration
```

集成服务需装入最新 `tests/lazy_proof_pack`，图像生成测试需要可用 checkpoint。
设置 `COMFYUI_FUNASR_VAD_MODEL` 为已缓存模型目录，可额外验证真实 VAD，避免下载。
外部 LLM 测试需自行提供 `LLM_API_URL`、`LLM_MODEL` 和可选的 `LLM_API_KEY`；
本地 mock LLM 测试不需要这些凭据。

## 对照依据

- [官方 V1 节点属性](https://docs.comfy.org/custom-nodes/backend/server_overview)
- [官方懒求值协议](https://docs.comfy.org/custom-nodes/backend/lazy_evaluation)
- [官方 AUDIO 加载及节点实现](https://github.com/Comfy-Org/ComfyUI/blob/29e28e2b/comfy_extras/nodes_audio.py)
- [官方 VIDEO 加载及预览实现](https://github.com/Comfy-Org/ComfyUI/blob/29e28e2b/comfy_extras/nodes_video.py)
- [官方前端音频控件扩展](https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/extensions/core/uploadAudio.ts)
