"""生成 `examples/` 下 MiniMax H3 的几张工作流(界面格式),Mosael 的长片 / 数字人模板就是按它们的节点号接的。

    python3 scripts/build_minimax_h3_examples.py            # 写进 examples/
    python3 scripts/build_minimax_h3_examples.py --out DIR  # 写到别处(比对用)

每张图的取舍都在 5090(32 GB 显存、31 GB 内存)上逐项对照过,记录在 Mosael 仓库的 ADR 0092:

- **加速 LoRA**:hybrid 底模 8 步不挂加速 LoRA 是糊的(底模要 20 多步)。lightx2v FL2V turbo 8 步、强度 1.0、不改 shift
  最清晰也最稳;强度 1.25、shift 6、叠真实感 LoRA、DMAD 4 步都更糊或更闪。
- **第二遍用块稀疏注意力**(ComfyUI 自带的 sol-attn,tau 1.3):一段从 480 秒降到 163 秒,清晰度不降。它和按头分组的
  省显存补丁不兼容,所以不挂那个;前馈仍分 2 块。第一遍 token 少,不到稀疏的门槛,不挂。
- **省显存**:采样完卸模型、解码完清内存,画面逐帧相同,耗时不变。
- **两遍采样**:864×480 定动作 → 潜空间放大 2 倍(音频锁住)→ 低噪声补细节,第二遍接 DisableNoise。
- **接缝**:每段存第二遍的高清潜空间;续写时第二遍原样锁住重叠帧,第一遍接它解码缩小后的画面。
- **超分**:整段 2K 画面一次放进内存要 11 GB,所以 SeedVR2 超分是单独一张图,用 VHS 分批(一批 61 帧)跑。

节点号是和 Mosael 的约定(`50.scene_number` 读上一段、`52.scene_number` 存这一段、超分的 `6.width` / `6.height`),
改号要同时改 Mosael 的 templates_models。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HYBRID = "minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
UPSCALER = "h3_clean_latent_upscaler_film_epoch200.safetensors"
TURBO_LORA = "minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors"
SEEDVR2 = "seedvr2_7b_sharp_int8_convrot.safetensors"
SEEDVR2_VAE = "seedvr2_ema_vae_fp16.safetensors"

REAL = ("Photorealistic documentary footage, real skin with pores and fine hair, natural micro-expressions, eye blinks, "
        "subtle breathing, slight head movement. Natural available light, realistic film grain, no beauty filter, "
        "no plastic skin, no CGI look. ")
SPEAK = ("Highest priority: whenever she is on screen her mouth keeps speaking, the lips, jaw and cheeks follow <Audio 1> "
         "syllable by syllable, opening and closing naturally every half second, teeth and the inside of the mouth "
         "visible when she opens it; she never stops with her mouth closed while the voice continues. ")
#: 一段 243 帧(24fps 约 10 秒),续写读上一段最后 39 帧做上文。
LENGTH = 243
CONTEXT_FRAMES = 39
#: 超分一批多少帧:2K 一批 61 帧在 31 GB 内存上跑得下,批与批之间不闪(实测)。
FRAMES_PER_BATCH = 61


class Graph:
    """界面格式的图:节点按加入顺序排位置,连线时把两头的 inputs / outputs 都记上。"""

    def __init__(self) -> None:
        self.nodes: dict[int, dict] = {}
        self.links: list[list] = []

    def node(self, id_: int, type_: str, widgets: list | dict | None = None, title: str | None = None,
             outputs: tuple[tuple[str, str], ...] | list = ()) -> None:
        index = len(self.nodes)
        raw = {
            "id": id_, "type": type_, "pos": [40 + (index % 3) * 640, 40 + (index // 3) * 300], "size": [300, 120],
            "flags": {}, "order": index, "mode": 0, "inputs": [],
            "outputs": [{"name": name, "type": kind, "links": [], "slot_index": slot} for slot, (name, kind) in enumerate(outputs)],
            "properties": {"Node name for S&R": type_},
            "widgets_values": widgets if widgets is not None else [],
        }
        if title:
            raw["title"] = title
        self.nodes[id_] = raw

    def wire(self, source: int, slot: int, target: int, name: str, kind: str) -> None:
        link = len(self.links) + 1
        self.links.append([link, source, slot, target, len(self.nodes[target]["inputs"]), kind])
        self.nodes[source]["outputs"][slot]["links"].append(link)
        self.nodes[target]["inputs"].append({"name": name, "type": kind, "link": link})

    def declare_widgets(self, id_: int, widgets: list[tuple[str, str]]) -> None:
        """动态下拉(COMFY_DYNAMICCOMBO_V3)这类 widget 要在 inputs 里登记,前端才排得对。"""
        for name, kind in widgets:
            self.nodes[id_]["inputs"].append({"name": name, "type": kind, "link": None, "widget": {"name": name}})

    def json(self) -> dict:
        return {"last_node_id": max(self.nodes), "last_link_id": len(self.links), "nodes": list(self.nodes.values()),
                "links": self.links, "groups": [], "config": {}, "extra": {}, "version": 0.4}


def loaders(g: Graph) -> tuple[int, int]:
    """模型、文本编码器、两个 VAE;底模后面挂加速 LoRA、前馈分块。交回 (第一遍的 MODEL, 第二遍的 MODEL) 节点号:
    第二遍再挂块稀疏注意力。"""
    g.node(3, "UNETLoader", [HYBRID, "default"], outputs=[("MODEL", "MODEL")])
    g.node(30, "LoraLoaderModelOnly", [TURBO_LORA, 1.0], "加速 LoRA / Turbo LoRA", [("MODEL", "MODEL")])
    g.wire(3, 0, 30, "model", "MODEL")
    g.node(32, "MiniMaxChunkFeedForward", [2, 4096], outputs=[("model", "MODEL")])
    g.wire(30, 0, 32, "model", "MODEL")
    g.node(33, "BlockSparseAttention", ["sol-attn", 1.3, 0.0, 1.0, "", 12288, 256, "exact_kv_and_rows", False],
           "第二遍稀疏注意力 / Sparse attention (pass 2)", [("MODEL", "MODEL")])
    g.wire(32, 0, 33, "model", "MODEL")
    g.declare_widgets(33, [("selection", "COMFY_DYNAMICCOMBO_V3"), ("selection.tau", "FLOAT"), ("start_percent", "FLOAT"),
                           ("end_percent", "FLOAT"), ("dense_blocks", "STRING"), ("min_tokens", "INT"), ("extra_tokens", "INT"),
                           ("sink_conditioning", "COMBO"), ("verbose", "BOOLEAN")])
    g.node(4, "CLIPLoader", [CLIP, "minimax", "default"], outputs=[("CLIP", "CLIP")])
    g.node(5, "VAELoader", [VIDEO_VAE], "Video VAE", [("VAE", "VAE")])
    g.node(6, "VAELoader", [AUDIO_VAE], "Audio VAE", [("VAE", "VAE")])
    return 32, 33


def previous_tail(g: Graph, positive: tuple[int, int], latent: tuple[int, int], with_audio: bool):
    """上一段存下的高清潜空间尾巴。第一遍是低分辨率,解码缩小后再做引导:接的是上一段成片的构图,不是上一段第一遍的
    (第二遍会把构图挪一点,接第一遍的话这点偏移在接缝上一次露出来)。交回第一遍的 positive 和这份尾巴,第二遍原样锁它。"""
    g.node(50, "VRGDG_MiniMaxH3LoadLatent", ["mosael/latents", 1, CONTEXT_FRAMES, False], "上一段的潜空间 / Previous latent",
           [("context_latent", "LATENT"), ("sliced_tokens", "INT")])
    g.node(53, "VAEDecode", outputs=[("IMAGE", "IMAGE")])
    g.wire(50, 0, 53, "samples", "LATENT")
    g.wire(5, 0, 53, "vae", "VAE")
    g.node(54, "ImageScale", ["area", 864, 480, "disabled"], outputs=[("IMAGE", "IMAGE")])
    g.wire(53, 0, 54, "image", "IMAGE")
    g.node(55, "MiniMaxH3AddGuide", [0], outputs=[("positive", "CONDITIONING")])
    g.wire(*positive, 55, "positive", "CONDITIONING")
    g.wire(*latent, 55, "latent", "LATENT")
    g.wire(5, 0, 55, "vae", "VAE")
    g.wire(54, 0, 55, "image", "IMAGE")
    if with_audio:
        g.node(56, "VAEDecodeAudio", outputs=[("AUDIO", "AUDIO")])
        g.wire(50, 0, 56, "samples", "LATENT")
        g.wire(6, 0, 56, "vae", "VAE")
        g.wire(6, 0, 55, "audio_vae", "VAE")
        g.wire(56, 0, 55, "audio", "AUDIO")
    return (55, 0), (50, 0)


def two_pass(g: Graph, models: tuple[int, int], positive, latent, audio, guided=None, tail=None) -> None:
    """低分辨率定动作;放大 2 倍(音频锁住),低噪声补细节,存下高清潜空间给下一段。

    `guided` 是第一遍带上文引导的 positive,放大时不带它:低分辨率的引导进高分辨率潜空间是一片网格。第二遍锁的是
    上一段高清的 `tail`,同分辨率,重叠帧和上一段成片一模一样。"""
    model, fine = models
    g.node(10, "RandomNoise", [1, "randomize"], outputs=[("NOISE", "NOISE")])
    g.node(11, "KSamplerSelect", ["euler"], outputs=[("SAMPLER", "SAMPLER")])
    g.node(12, "BasicScheduler", ["beta", 8, 1], outputs=[("SIGMAS", "SIGMAS")])
    g.wire(model, 0, 12, "model", "MODEL")
    g.node(9, "BasicGuider", outputs=[("GUIDER", "GUIDER")])
    g.wire(model, 0, 9, "model", "MODEL")
    g.wire(*(guided or positive), 9, "conditioning", "CONDITIONING")
    g.node(13, "SamplerCustomAdvanced", outputs=[("output", "LATENT"), ("denoised_output", "LATENT")])
    g.wire(10, 0, 13, "noise", "NOISE")
    g.wire(9, 0, 13, "guider", "GUIDER")
    g.wire(11, 0, 13, "sampler", "SAMPLER")
    g.wire(12, 0, 13, "sigmas", "SIGMAS")
    g.wire(*latent, 13, "latent_image", "LATENT")
    g.node(70, "MiniMaxH3Pass2StaggeredScheduler", [4, 0.45, 7.0, "karras", 8, "simple"], outputs=[("SIGMAS", "SIGMAS")])
    g.wire(fine, 0, 70, "model", "MODEL")
    g.node(71, "RandomNoise", [2, "randomize"], outputs=[("NOISE", "NOISE")])
    g.node(72, "MiniMaxH3LatentUpscaleCombined", ["learned model", UPSCALER, 0.0, "independent", 0.0],
           outputs=[("latent", "LATENT"), ("positive", "CONDITIONING"), ("negative", "CONDITIONING")])
    g.wire(13, 0, 72, "samples", "LATENT")
    g.wire(fine, 0, 72, "model", "MODEL")
    g.wire(71, 0, 72, "noise", "NOISE")
    g.wire(70, 0, 72, "sigmas", "SIGMAS")
    g.wire(*positive, 72, "positive", "CONDITIONING")
    fine_positive, fine_latent = (72, 1), (72, 0)
    if tail:
        g.node(57, "VRGDG_MiniMaxH3ApplyLatentGuide", [0, False], outputs=[("positive", "CONDITIONING"), ("latent", "LATENT")])
        g.wire(*fine_positive, 57, "positive", "CONDITIONING")
        g.wire(*fine_latent, 57, "latent", "LATENT")
        g.wire(*tail, 57, "context_latent", "LATENT")
        fine_positive, fine_latent = (57, 0), (57, 1)
    g.node(73, "BasicGuider", outputs=[("GUIDER", "GUIDER")])
    g.wire(fine, 0, 73, "model", "MODEL")
    g.wire(*fine_positive, 73, "conditioning", "CONDITIONING")
    g.node(75, "DisableNoise", outputs=[("NOISE", "NOISE")])
    g.node(74, "SamplerCustomAdvanced", outputs=[("output", "LATENT"), ("denoised_output", "LATENT")])
    g.wire(75, 0, 74, "noise", "NOISE")
    g.wire(73, 0, 74, "guider", "GUIDER")
    g.wire(11, 0, 74, "sampler", "SAMPLER")
    g.wire(70, 0, 74, "sigmas", "SIGMAS")
    g.wire(*fine_latent, 74, "latent_image", "LATENT")
    #: 控件依次是 project_folder、scene_number、frame_count、fps、pass1、tail_padding_frames。pass1 必须为 False:
    #: 为 True 时存成 scene_NNN.pass1.latent(只有第一遍),下一段的 LoadLatent 读的是 scene_NNN.latent,会找不到。
    g.node(52, "VRGDG_MiniMaxH3SaveLatent", ["mosael/latents", 1, 0, 24.0, False, -1], "存下这一段的潜空间 / Keep this latent",
           [("latent", "LATENT"), ("saved_path", "STRING")])
    g.wire(74, 0, 52, "latent", "LATENT")
    #: 采样完把模型挪出显存、解码完清内存:高清解码有显存用,接着跑的超分(另一个任务)有内存用。画面不变,单段不变慢(实测)。
    g.node(60, "VRAMCleanup", [True, True], "腾出显存 / Free VRAM", [("output", "*")])
    g.wire(52, 0, 60, "anything", "*")
    g.node(14, "VAEDecode", outputs=[("IMAGE", "IMAGE")])
    g.wire(60, 0, 14, "samples", "LATENT")
    g.wire(5, 0, 14, "vae", "VAE")
    g.node(61, "RAMCleanup", [True, True, True, 3], "腾出内存 / Free RAM", [("output", "*")])
    g.wire(14, 0, 61, "anything", "*")
    g.node(16, "CreateVideo", [24, "auto", "sRGB", "none"], outputs=[("VIDEO", "VIDEO")])
    g.wire(61, 0, 16, "images", "IMAGE")
    if audio is None:
        g.node(15, "VAEDecodeAudio", outputs=[("AUDIO", "AUDIO")])
        g.wire(60, 0, 15, "samples", "LATENT")
        g.wire(6, 0, 15, "vae", "VAE")
        audio = (15, 0)
    g.wire(*audio, 16, "audio", "AUDIO")
    g.node(17, "SaveVideo", ["video/mosael_h3", "auto", "auto"])
    g.wire(16, 0, 17, "video", "VIDEO")
    g.declare_widgets(16, [("fps", "FLOAT"), ("bit_depth", "COMBO"), ("color_space", "COMBO"), ("codec", "COMBO")])
    g.declare_widgets(17, [("filename_prefix", "STRING"), ("format", "COMFY_DYNAMICCOMBO_V3")])


def long_video(continuing: bool) -> dict:
    g = Graph()
    models = loaders(g)
    g.node(7, "MiniMaxH3ImageToVideo", [REAL + "One continuous shot, no cut.", 864, 480, LENGTH],
           outputs=[("positive", "CONDITIONING"), ("LATENT", "LATENT")])
    g.wire(4, 0, 7, "clip", "CLIP")
    g.wire(5, 0, 7, "vae", "VAE")
    positive, latent = (7, 0), (7, 1)
    guided, tail = previous_tail(g, positive, latent, True) if continuing else (None, None)
    two_pass(g, models, positive, latent, None, guided, tail)
    return g.json()


def talk(continuing: bool) -> dict:
    g = Graph()
    models = loaders(g)
    g.node(40, "LoadImage", ["face.png", "image"], "人物 / Face", [("IMAGE", "IMAGE"), ("MASK", "MASK")])
    g.node(41, "LoadAudio", ["voice.wav"], "这一段的配音 / Voice for this segment", [("AUDIO", "AUDIO")])
    prompt = "<Picture 1> speaks to the camera. " + SPEAK + REAL + "One continuous shot, the camera stays still, no cut."
    g.node(7, "MiniMaxH3ReferenceToVideo", [prompt, 864, 480, LENGTH, "match"], outputs=[("positive", "CONDITIONING"), ("LATENT", "LATENT")])
    g.wire(4, 0, 7, "clip", "CLIP")
    g.wire(5, 0, 7, "vae", "VAE")
    g.wire(6, 0, 7, "audio_vae", "VAE")
    g.wire(40, 0, 7, "ref_images.ref_image_0", "IMAGE")
    g.wire(41, 0, 7, "ref_audios.ref_audio_0", "AUDIO")
    g.node(42, "VRGDG_MiniMaxH3AudioDrive", outputs=[("audio_driven_av_latent", "LATENT"), ("original_audio", "AUDIO")])
    g.wire(7, 1, 42, "av_latent", "LATENT")
    g.wire(41, 0, 42, "source_audio", "AUDIO")
    g.wire(6, 0, 42, "audio_vae", "VAE")
    positive, latent = (7, 0), (42, 0)
    guided, tail = previous_tail(g, positive, latent, False) if continuing else (None, None)
    two_pass(g, models, positive, latent, (42, 1), guided, tail)
    return g.json()


def upscale() -> dict:
    """SeedVR2 7B sharp 一步超分到 `6.width` × `6.height`(默认 2560×1440,即 2K)。VHS 分批:一批读、超、写,
    内存只占一批;每一批在 ComfyUI 里是一个任务,最后一批的历史里才有视频(Mosael 的插件会顺着跟到最后)。"""
    g = Graph()
    g.node(0, "VHS_BatchManager", {"frames_per_batch": FRAMES_PER_BATCH}, "分批 / Batches", [("meta_batch", "VHS_BatchManager")])
    g.node(1, "VHS_LoadVideo", {"video": "source.mp4", "force_rate": 0, "custom_width": 0, "custom_height": 0,
                                "frame_load_cap": 0, "skip_first_frames": 0, "select_every_nth": 1, "format": "AnimateDiff"},
           "要超分的视频 / Video to upscale",
           [("IMAGE", "IMAGE"), ("frame_count", "INT"), ("audio", "AUDIO"), ("video_info", "VHS_VIDEOINFO")])
    g.wire(0, 0, 1, "meta_batch", "VHS_BatchManager")
    g.node(3, "UNETLoader", [SEEDVR2, "default"], outputs=[("MODEL", "MODEL")])
    g.node(4, "VAELoader", [SEEDVR2_VAE], outputs=[("VAE", "VAE")])
    #: 宽高是普通的整数格(`6.width` / `6.height`),Mosael 按时间线画布填;动态下拉的子项插件不当参数交出去。
    g.node(6, "ImageScale", ["lanczos", 2560, 1440, "disabled"], "目标尺寸 / Target size", [("IMAGE", "IMAGE")])
    g.wire(1, 0, 6, "image", "IMAGE")
    g.node(7, "SeedVR2Preprocess", outputs=[("images", "IMAGE")])
    g.wire(6, 0, 7, "resized_images", "IMAGE")
    g.node(8, "VAEEncode", outputs=[("LATENT", "LATENT")])
    g.wire(7, 0, 8, "pixels", "IMAGE")
    g.wire(4, 0, 8, "vae", "VAE")
    g.node(9, "SeedVR2TemporalChunk", [2, "auto"], outputs=[("latents", "LATENT"), ("temporal_overlap", "INT")])
    g.wire(8, 0, 9, "latent", "LATENT")
    g.declare_widgets(9, [("temporal_overlap", "INT"), ("chunking_mode", "COMFY_DYNAMICCOMBO_V3")])
    g.node(10, "SeedVR2Conditioning", outputs=[("positive", "CONDITIONING"), ("negative", "CONDITIONING")])
    g.wire(3, 0, 10, "model", "MODEL")
    g.wire(9, 0, 10, "vae_conditioning", "LATENT")
    g.node(11, "KSampler", [42, "fixed", 5, 1.0, "euler", "simple", 1.0], outputs=[("LATENT", "LATENT")])
    g.wire(3, 0, 11, "model", "MODEL")
    g.wire(10, 0, 11, "positive", "CONDITIONING")
    g.wire(10, 1, 11, "negative", "CONDITIONING")
    g.wire(9, 0, 11, "latent_image", "LATENT")
    g.node(12, "SeedVR2TemporalMerge", outputs=[("latent", "LATENT")])
    g.wire(11, 0, 12, "latents", "LATENT")
    g.wire(9, 1, 12, "temporal_overlap", "INT")
    g.node(13, "VAEDecode", outputs=[("IMAGE", "IMAGE")])
    g.wire(12, 0, 13, "samples", "LATENT")
    g.wire(4, 0, 13, "vae", "VAE")
    g.node(14, "SeedVR2PostProcessing", ["lab"], outputs=[("images", "IMAGE")])
    g.wire(13, 0, 14, "images", "IMAGE")
    g.wire(6, 0, 14, "original_resized_images", "IMAGE")
    g.node(17, "VHS_VideoCombine", {"frame_rate": 24, "loop_count": 0, "filename_prefix": "video/mosael_upscaled",
                                    "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 16, "save_metadata": False,
                                    "trim_to_audio": False, "pingpong": False, "save_output": True},
           outputs=[("Filenames", "VHS_FILENAMES")])
    g.wire(14, 0, 17, "images", "IMAGE")
    g.wire(1, 2, 17, "audio", "AUDIO")
    g.wire(0, 0, 17, "meta_batch", "VHS_BatchManager")
    #: 随格式出现的几格(pix_fmt、crf……)不在节点定义里,要登记成 widget 才会交出去。
    g.declare_widgets(17, [("pix_fmt", "COMBO"), ("crf", "INT"), ("save_metadata", "BOOLEAN"), ("trim_to_audio", "BOOLEAN")])
    return g.json()


GRAPHS = {
    "minimax_h3_open": lambda: long_video(False),
    "minimax_h3_continue": lambda: long_video(True),
    "minimax_h3_talk_open": lambda: talk(False),
    "minimax_h3_talk_continue": lambda: talk(True),
    "seedvr2_upscale_batched": upscale,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "examples")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, build in GRAPHS.items():
        (args.out / f"{name}.json").write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n")
        print(f"wrote {name}.json")


if __name__ == "__main__":
    main()
