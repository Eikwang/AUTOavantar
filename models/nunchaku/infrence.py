import math

import torch
from diffusers import FlowMatchEulerDiscreteScheduler, QwenImageEditPlusPipeline
from diffusers.utils import load_image

from nunchaku import NunchakuQwenImageTransformer2DModel
from nunchaku.utils import get_gpu_memory, get_precision

# From https://github.com/ModelTC/Qwen-Image-Lightning/blob/342260e8f5468d2f24d084ce04f55e101007118b/generate_with_diffusers.py#L82C9-L97C10
scheduler_config = {
    "base_image_seq_len": 256,
    "base_shift": math.log(3),  # We use shift=3 in distillation
    "invert_sigmas": False,
    "max_image_seq_len": 8192,
    "max_shift": math.log(3),  # We use shift=3 in distillation
    "num_train_timesteps": 1000,
    "shift": 1.0,
    "shift_terminal": None,  # set shift_terminal to None
    "stochastic_sampling": False,
    "time_shift_type": "exponential",
    "use_beta_sigmas": False,
    "use_dynamic_shifting": True,
    "use_exponential_sigmas": False,
    "use_karras_sigmas": False,
}
scheduler = FlowMatchEulerDiscreteScheduler.from_config(scheduler_config)

num_inference_steps = 4  # you can also use the 8-step model to improve the quality
rank = 32  # you can also use the rank=128 model to improve the quality
model_path = f"svdq-int4_r32-qwen-image-edit-2509-lightning-4steps-251115.safetensors"

# Load the model
transformer = NunchakuQwenImageTransformer2DModel.from_pretrained(model_path)

pipeline = QwenImageEditPlusPipeline.from_pretrained(
    "Qwen/Qwen-Image-Edit-2509", transformer=transformer, scheduler=scheduler, torch_dtype=torch.bfloat16
)

# LoRA Related Code
transformer.update_lora_params(
    "lora.safetensors"
)  # Path to your LoRA safetensors, can also be a remote HuggingFace path
transformer.set_lora_strength(1)  # Your LoRA strength here
# End of LoRA Related Code

if get_gpu_memory() > 18:
    pipeline.enable_model_cpu_offload()
else:
    # use per-layer offloading for low VRAM. This only requires 3-4GB of VRAM.
    transformer.set_offload(
        True, use_pin_memory=False, num_blocks_on_gpu=1
    )  # increase num_blocks_on_gpu if you have more VRAM
    pipeline._exclude_from_cpu_offload.append("transformer")
    pipeline.enable_sequential_cpu_offload()

image1 = load_image("D:\AI\AUTOavantar\models\nunchaku\011.png")
image1 = image1.convert("RGB")

prompt = "# 任务 /n 为画面添加具有电影级质感的文字排版设计。 /n # 文本内容 /n 主标题：“勇攀高峰！” /n 副标题：“从不畏惧挑战” /n 装饰文：“和我一起向上前行” /n # 排版与美学要求 /n **空间层级**： “主标题”采用“穿插式”构图。字号极大，放置在画面中后方，作为背景纹理，字体透明度为30%，人物身体需遮挡住部分文字，营造强烈的景深悬浮感。 /n **视觉焦点**： ”副标题“位于画面视觉中心偏下，使用高亮、加粗的无衬线字体，颜色为纯白或亮黄，并添加黑色描边或投影，确保在复杂背景下清晰可见。 /n **结构平衡**： “装饰文”位于副标题正下方，字号较小，字间距加宽，起到平衡画面的作用。 /n **画面风格**： 整体为高端杂志及影视海报风格。"
inputs = {
    "image": [image1],
    "prompt": prompt,
    "true_cfg_scale": 1.0,
    "num_inference_steps": num_inference_steps,
}

output = pipeline(**inputs)
output_image = output.images[0]
output_image.save(f"qwen-image-edit-2509-lightning-r{rank}-{num_inference_steps}steps.png")