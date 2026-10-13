# ComfyUI-Mosael-Plugins（可选输入）

[English](README.md) | [中文](README_zh.md)

一组自定义节点，让**同一个 ComfyUI 工作流可以接受可选输入**，并自动在执行分支之间切换——
例如文生图（txt2img）与图生图（img2img）——**无需手动改连线、绕过（bypass）、静音（mute）节点或切换布尔开关**。

在加载器里选一张图，工作流按图生图运行；选择 `none`，同一个工作流按文生图运行。
**未被选中的分支永远不会被执行。**

```
Optional Load Image ──image──▶ VAE Encode ──▶ latent_true ──▶ Lazy Latent Switch ──▶ KSampler
        │                                        （无图时被跳过）
        └──has_image──▶ condition      Empty Latent ──▶ latent_false ──▶ （无图时选中）
```

## 为什么普通开关节点不够用

朴素方案——普通 switch 节点，或让 `IMAGE → VAE Encode` 的图像有时缺失——会在两方面失败：

1. **急切求值。** 普通 switch 会执行*两个*分支，`VAE Encode` 依旧运行：没有图时它收到
   `None` 直接崩溃；用黑色占位图时白白浪费算力编码垃圾。
2. **占位图。** 伪造一张 1×1 黑图"让图保持合法"会悄悄改变工作流的行为，而且违反了
   一个原则：**黑图是有效数据，不是缺失输入**。

本插件使用 ComfyUI **官方支持的懒求值协议**（`{"lazy": True}` 输入 +
`check_lazy_status`），执行引擎根本不会调度未选中的分支。

## 节点

| 节点 | 用途 |
|---|---|
| **Optional Load Image** | 加载图片，或显式选择 `none`。输出 `image` + `mask`（由 alpha 通道推导，与官方 Load Image 节点一致；均可为 `None`）+ `has_image`。 |
| **Optional Load Video** | 加载视频（与官方 Load Video 节点相同的惰性 `VIDEO` 对象），或选择 `none`。输出 `video`（可为 `None`）+ `has_video` + 便捷导出 `images`（解码帧）、`frame_count`、`audio`——相当于官方 Get Video Components 节点。 |
| **Optional Load Audio** | 加载音频文件（或视频中的音轨），或选择 `none`。输出 `audio`（可为 `None`）+ `has_audio` + `sample_rate` + `duration`。 |
| **Optional Audio Preview** | 在界面中预览音频。其 `audio` 输入为懒输入，仅当 `condition` 为 True 时才拉取——接入 `has_audio` 后，无音频时整条音频分支都不会执行。 |
| **Quick Audio Edit** | 单节点快捷编辑：截取（起始/时长）、音量（dB）、线性淡入/淡出。可选安全——缺失音频原样透传。输出编辑后的音频及其新时长。 |
| **FunASR Transcribe** | 语音转文字，输出带逐字时间戳的逐字稿。可选依赖：`pip install funasr`（支持 Windows/Linux/macOS）。 |
| **VAD Auto Trim Audio** | 智能裁剪：语音活动检测自动去除静音。输出裁剪后音频 + 可编辑的片段 JSON 字符串。可选依赖 `funasr`。 |
| **Audio Trim by Segments** | 手动二次裁剪：编辑片段字符串（手动或程序化）后对原始音频重新裁剪。 |
| **LLM API Call** | 调用任意 OpenAI 兼容对话 API，供应商完全自定义——base URL、API key 和模型名。适用于 OpenAI、DeepSeek、Moonshot、通义、硅基流动、Groq、OpenRouter 及本地 Ollama / vLLM / LM Studio。无额外依赖。 |
| **Optional Video Preview** | 在界面中预览视频。其 `video` 输入为懒输入，仅当 `condition` 为 True 时才拉取——接入 `has_video` 后，无视频时整条视频分支都不会执行。 |
| **Optional Image** | 透传一个可选的 IMAGE 连接，并报告 `has_image`。 |
| **Has Image** | `IMAGE → BOOLEAN`：图像是否存在？按值本身判断，绝不看像素内容。 |
| **Lazy Image Switch** | 按 `condition` 选择 `image_true` / `image_false`；只执行选中的分支。 |
| **Lazy Latent Switch** | LATENT 版本（图生图 vs 文生图 latent）。完整保留 latent 字典。 |
| **Lazy Video Switch** | VIDEO 版本（视频生视频 vs 生成视频）。 |
| **Lazy Any Switch** | 通过 `*` 通配符支持任意类型。分支不做类型校验（见下文）。 |

### 缺失值语义

- 输入缺失 → `image` 与 `mask` 输出均为 Python `None`，`has_image` 为 `False`。
- 有效张量——**包括全黑图或空批次图**——视为存在，原样透传（同一对象、零拷贝，批次 /
  设备 / dtype 保持不变）。
- 损坏或被删除的文件是**硬错误**，绝不会静默当作"缺失"。

IMAGE 输出上的 `None` 只有接到懒开关输入（或其他显式接受它的节点）才是安全的——这是平台
约定，完整分析见 `docs/DESIGN.md`。

## 安装

### ComfyUI Manager（推荐）

在 Manager 中搜索 "Optional Inputs" 安装。

### 手动安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Alndaly/ComfyUI-Mosael-Plugins.git
# 重启 ComfyUI —— 无需任何额外 Python 依赖
```

## 用法：一个工作流，同时支持文生图与图生图

1. 添加 **Optional Load Image**。选择 `none` 即文生图，选择 / 上传图片即图生图。
2. 按如下方式连线：

```
Optional Load Image.image      → VAE Encode.pixels        → Lazy Latent Switch.latent_true
Optional Load Image.has_image  → Lazy Latent Switch.condition
EmptyLatentImage.LATENT        → Lazy Latent Switch.latent_false
Lazy Latent Switch.latent      → KSampler.latent_image
```

3. 运行。就这样——不需要任何切换操作。

现成的工作流在 [`examples/`](examples/)：

- `txt2img_img2img.json` —— UI 格式，可直接拖入 ComfyUI 画布。
- `txt2img_img2img_api.json` —— API 格式，用于 `/prompt` 提交。
- `optional_image_basic_api.json` —— 最小化的 `Optional Image` / `Has Image` /
  `Lazy Image Switch` 演示。

### API 调用

选择项就是普通的 widget 值，因此工作流可以完全无头运行：

```python
workflow["4"]["inputs"]["image"] = "none"            # 文生图
workflow["4"]["inputs"]["image"] = "uploaded.png"    # 图生图
requests.post("http://127.0.0.1:8188/prompt", json={"prompt": workflow, "client_id": "..."})
```

## 工作原理

- **可选输入。** 声明在 `"optional"` 下的输入可以不出现在 prompt 中，而不会导致图校验失败。
- **懒求值。** 声明为 `{"lazy": True}` 的分支输入不会进入初始执行图。switch 的
  `check_lazy_status` 只请求选中的分支；另一分支的节点根本不会被调度。
- **缓存。** 加载器的 `IS_CHANGED` 对所选文件做哈希（`none` 是稳定常量），因此增删、替换
  图片都会正确使缓存的分支选择失效——已由自动化测试验证。
- **校验。** `VALIDATE_INPUTS` 在执行前就拒绝不存在的文件，让拼写错误快速失败并给出清晰
  报错。

完整的可行性分析、协议细节与已知限制见 [`docs/DESIGN.md`](docs/DESIGN.md)。

## 语音转文字、智能音频裁剪与 LLM 调用

### FunASR 节点（可选依赖）

`FunASR Transcribe`、`VAD Auto Trim Audio` 与 `Audio Trim by Segments` 需要
可选的 [FunASR](https://github.com/modelscope/FunASR) 包（不随插件分发——仅需要
这些节点时再安装）：

```bash
pip install funasr
```

支持 Windows / Linux / macOS；模型（paraformer-zh、fsmn-vad 等）首次使用时自动
下载到本地 ModelScope 缓存。无论是否安装，节点都正常注册——未安装时只在执行阶段
报出安装指引，不会影响工作流加载。

**逐字稿：** `FunASR Transcribe` 输出文本 + 逐字时间戳（`chars`，JSON：
`[{index, start, end}, …]`，单位秒）——可直接用于字幕、卡拉OK 时轴或逐字特效。

**智能裁剪 + 手动二次编辑：**

1. `VAD Auto Trim Audio` 检测语音活动并剪掉静音，提供 `padding` / `min_speech` /
   `merge_gap` 三个控制项。输出裁剪后的音频**以及**保留片段的 JSON 字符串，如
   `[[0.0, 2.1], [3.2, 5.0]]`。
2. 把该字符串复制到 `Audio Trim by Segments` 的 `segments` 输入框里自由编辑数字
   （容错：尾逗号、多余空格、`{"start":…, "end":…}` 对象形式均可），然后对
   *原始*音频重新裁剪——也可以直接连线实现自动重裁。

### LLM API Call

供应商完全自定义——没有厂商列表、没有硬编码端点：

| 输入 | 示例 |
|---|---|
| `base_url` | `https://api.deepseek.com/v1`、`https://api.openai.com/v1`、`http://127.0.0.1:11434/v1`（Ollama） |
| `model` | `deepseek-chat`、`gpt-4o-mini`、`qwen2.5:7b` |
| `api_key` | 供应商密钥；无需鉴权的端点（如本地 Ollama）留空即可 |

使用 OpenAI 兼容的 `/chat/completions` 协议（OpenAI、DeepSeek、Moonshot、通义、
硅基流动、Groq、OpenRouter、Ollama、vLLM、LM Studio……）。仅依赖 Python 标准库。
注意：API key 是普通 widget 值，会像其他输入一样保存进工作流 JSON——建议使用
限额/临时密钥。

**JSON 输出：** 把 `response_format` 设为 `json_object` 可请求保证为 JSON 的回复
（OpenAI 式 `response_format` 参数——OpenAI、DeepSeek、Moonshot、通义等均支持）。
请在提示词中提及 "json" 及期望的结构；个别不支持的模型/供应商可能对该参数报错。

## 兼容性

- 已在 **ComfyUI `08ff3c11` / `0df64eb`（master，2026-10-09）** 上测试——即撰写时的最新版本。
- 无额外 Python 依赖；只使用 ComfyUI 核心 API（`folder_paths`、`nodes.LoadImage`）。
- 使用执行引擎仍完整支持的 legacy（V1）节点 API。

尚未在更旧的 ComfyUI 版本上测试——如果你在使用旧版本，欢迎提 issue 反馈结果。

## 测试

单元测试（无需 ComfyUI）：

```bash
pytest tests -m "not integration"
```

针对运行中的 ComfyUI 的集成测试（需先安装本插件）：

```bash
COMFYUI_URL=http://127.0.0.1:8188 pytest tests -m integration
```

集成测试里包含一个放在未选中分支上的"必然报错节点"：运行通过即从机器层面证明懒求值
确实跳过了该分支。跑这部分测试前，请把 `tests/lazy_proof_pack/` 也复制到 `custom_nodes`。
两套测试（49 个单元 + 11 个集成）均已在 ComfyUI master（2026-10-09）上用真实 checkpoint
跑通。

## 故障排查

- **"`none` is selected but allow_none is disabled"** —— 加载器的保护逻辑。重新打开
  `allow_none` 或选择一张图片。
- **"Image file not found … was it deleted"** —— 文件在校验时还在、执行时被删了。重新选择
  图片即可。
- **某个节点收到 `None` 后崩溃** —— 你把可选的 `image` 输出接到了一个在"无图"路径上运行、
  且需要真实张量的节点。请改走懒开关。
- **未选中的分支仍然执行了** —— 有*其他*节点通过非懒输入消费了该分支，引擎被迫满足它的
  依赖。给那个消费者独立供数，或检查分支是否只终止于开关。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。特别欢迎针对其他 ComfyUI 版本的兼容性反馈。

## 许可证

[MIT](LICENSE)
