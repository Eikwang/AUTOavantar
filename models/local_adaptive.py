import math
import os
import time
import gc

import torch
from diffusers import FlowMatchEulerDiscreteScheduler, QwenImageEditPlusPipeline
from diffusers.utils import load_image
from nunchaku import NunchakuQwenImageTransformer2DModel
from nunchaku.utils import get_gpu_memory

print("=" * 80)
print("  Nunchaku Pipeline - Production Adaptive Manager")
print("  Based on verified working configurations")
print("=" * 80)

# ============================================================
# Configuration
# ============================================================
NUM_INFERENCE_STEPS = 4
RANK = 32

# GPU 架构检测 - Blackwell 使用 FP4，其他使用 INT4
def is_blackwell_gpu():
    """检测是否为 Blackwell 架构 GPU"""
    if not torch.cuda.is_available():
        return False
    
    gpu_name = torch.cuda.get_device_name(0)
    blackwell_keywords = [
        "RTX 50", "RTX50",  # RTX 50 系列
        "B100", "B200",     # 数据中心 Blackwell
        "GB20", "GB10",     # Blackwell 架构代号
        "Blackwell"
    ]
    
    for keyword in blackwell_keywords:
        if keyword.lower() in gpu_name.lower():
            return True
    
    # 通过 compute capability 判断 (Blackwell 是 10.x)
    try:
        major, minor = torch.cuda.get_device_capability(0)
        if major >= 10:  # Blackwell 架构 compute capability >= 10.0
            return True
    except:
        pass
    
    return False

# 根据架构选择模型
USE_FP4 = is_blackwell_gpu()
if USE_FP4:
    MODEL_PATHS = {
        "transformer": r".\standalone_models\svdq-fp4_r32-qwen-image-edit-2509-lightning-4steps-251115.safetensors",
    }
    QUANT_TYPE = "FP4"
else:
    MODEL_PATHS = {
        "transformer": r".\standalone_models\svdq-int4_r32-qwen-image-edit-2509-lightning-4steps-251115.safetensors",
    }
    QUANT_TYPE = "INT4"

STANDALONE_MODEL_PATH = r".\standalone_models\Qwen-Image-Edit-2509"
IMAGE_PATH = r".\633.png"

# 是否使用独立模型目录（推荐用于部署到其他项目）
USE_STANDALONE_MODEL = True

# ============================================================
# 模拟显存测试 (用于测试不同显存配置)
# 设置 SIMULATE_VRAM 为 None 使用真实显存，或设置为具体数值模拟显存
# ============================================================
SIMULATE_VRAM = None  # 可选值：None, 16, 12, 8, 6

prompt = """图中的人正对着镜头展示一张海报，镜头拉近，可以清晰看到海报上面用书法写着中文，文字内容是：从田间到餐桌：湛江雷州白切鸡的 五大美味密码！”"""

# ============================================================
# Step 1: Detect Hardware & Select Verified Strategy
# ============================================================
print("\n[1/6] Detecting hardware...")
gpu_vram_gb = get_gpu_memory()
gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "No GPU"
print(f"  GPU: {gpu_name}")
print(f"  VRAM: {gpu_vram_gb:.1f} GB")
print(f"  Architecture: {'Blackwell' if USE_FP4 else 'Non-Blackwell'}")
print(f"  Transformer: {QUANT_TYPE} quantized")

# 如果启用模拟显存
if SIMULATE_VRAM is not None:
    print(f"\n    SIMULATING VRAM: {SIMULATE_VRAM} GB (Testing Mode)")
    gpu_vram_gb = SIMULATE_VRAM

# 选择经过验证的策略 - 使用 FP16 模型 + 智能卸载
if gpu_vram_gb >= 24:
    mode = "fp16_ultra" 
    print(f"\n  Mode: FP16 Ultra (24GB+ VRAM)")
    print(f"     Strategy: FP16 TE + All Transformer blocks on GPU")
    print(f"     ~20GB VRAM / ~10GB RAM")
elif gpu_vram_gb >= 15:
    mode = "fp16_high" 
    print(f"\n  Mode: FP16 High (15GB VRAM)")
    print(f"     Strategy: FP16 TE + 20 Transformer blocks on GPU")
    print(f"     ~14GB VRAM / ~12GB RAM")
elif gpu_vram_gb >= 11:
    mode = "fp16_medium" 
    print(f"\n  Mode: FP16 Medium (11GB VRAM)")
    print(f"     Strategy: FP16 TE + 10 Transformer blocks + CPU offload")
    print(f"     ~10GB VRAM / ~15GB RAM")
elif gpu_vram_gb >= 7:
    mode = "fp16_low" 
    print(f"\n  Mode: FP16 Low (7GB VRAM)")
    print(f"     Strategy: FP16 TE + 1 Transformer block + aggressive offload")
    print(f"     ~6GB VRAM / ~18GB RAM")
else:
    mode = "fp16_minimal" 
    print(f"\n  Mode: FP16 Minimal (5GB VRAM)")
    print(f"     Strategy: FP16 TE on GPU + Sequential offload (minimum)")
    print(f"     ~5GB VRAM / ~20GB RAM")

# ============================================================
# Step 2: Load Transformer (Common)
# ============================================================
print("\n[2/6] Loading Transformer...")
t0 = time.time()

scheduler_config = {
    "base_image_seq_len": 256,
    "base_shift": math.log(3),
    "invert_sigmas": False,
    "max_image_seq_len": 8192,
    "max_shift": math.log(3),
    "num_train_timesteps": 1000,
    "shift": 1.0,
    "shift_terminal": None,
    "stochastic_sampling": False,
    "time_shift_type": "exponential",
    "use_beta_sigmas": False,
    "use_dynamic_shifting": True,
    "use_exponential_sigmas": False,
    "use_karras_sigmas": False,
}
scheduler = FlowMatchEulerDiscreteScheduler.from_config(scheduler_config)

transformer = NunchakuQwenImageTransformer2DModel.from_pretrained(MODEL_PATHS["transformer"])
print(f"  [✓] Loaded in {time.time()-t0:.2f}s")

# ============================================================
# Step 3/4: Load Pipeline (Mode-Specific)
# ============================================================
print(f"\n[3/6] Loading Pipeline ({mode})...")

# ========== 使用 FP16 模型 + 智能 offload ==========
print(f"  Loading FP16 pipeline with smart offload...")

# 选择模型路径
if USE_STANDALONE_MODEL and os.path.exists(STANDALONE_MODEL_PATH):
    model_path = STANDALONE_MODEL_PATH
    print(f"  Using standalone model: {model_path}")
else:
    model_path = "Qwen/Qwen-Image-Edit-2509"
    print(f"  Using HF cache: {model_path}")

# 加载 pipeline
pipeline = QwenImageEditPlusPipeline.from_pretrained(
    model_path,
    transformer=transformer,
    torch_dtype=torch.bfloat16,
    local_files_only=USE_STANDALONE_MODEL
)

print("  [✓] Pipeline loaded")

# ============================================================
# Step 5: Apply Patches & Configure Offload
# ============================================================
print("\n[4/6] Applying patches...")

original_transformer_call = pipeline.transformer.forward
def patched_forward(self, *args, **kwargs):
    if 'txt_seq_lens' not in kwargs and 'encoder_hidden_states' in kwargs:
        kwargs['txt_seq_lens'] = [kwargs['encoder_hidden_states'].shape[1]]
    return original_transformer_call(*args, **kwargs)
pipeline.transformer.forward = lambda *args, **kwargs: patched_forward(pipeline.transformer, *args, **kwargs)
print("  [✓] Transformer patch applied")

print("\n[5/6] Configuring offload...")

# 根据显存大小选择 offload 策略
if gpu_vram_gb >= 24:
    # 24GB+: 全部在 GPU 上
    pipeline.enable_model_cpu_offload()
    print("  Strategy: Model CPU offload (24GB+ VRAM)")
    print("  Expected: ~20GB VRAM, maximum performance")
        
elif gpu_vram_gb >= 15:
    # 15GB: Transformer offload + 20 blocks on GPU
    transformer.set_offload(True, use_pin_memory=False, num_blocks_on_gpu=50)
    pipeline._exclude_from_cpu_offload = getattr(pipeline, '_exclude_from_cpu_offload', [])
    pipeline._exclude_from_cpu_offload.append("transformer")
    pipeline.enable_sequential_cpu_offload()
    print("  Expected: ~14GB VRAM")
        
elif gpu_vram_gb >= 11:
    # 11GB: Transformer offload + 10 blocks on GPU
    transformer.set_offload(True, use_pin_memory=False, num_blocks_on_gpu=30)
    pipeline._exclude_from_cpu_offload = getattr(pipeline, '_exclude_from_cpu_offload', [])
    pipeline._exclude_from_cpu_offload.append("transformer")
    pipeline.enable_sequential_cpu_offload()
    print("  Strategy: Sequential offload + 10 Transformer blocks on GPU")
    print("  Expected: ~11GB VRAM")
    
elif gpu_vram_gb >= 7:
    # 7GB: Transformer offload + 1 block on GPU
    transformer.set_offload(True, use_pin_memory=True, num_blocks_on_gpu=20)
    pipeline._exclude_from_cpu_offload = getattr(pipeline, '_exclude_from_cpu_offload', [])
    pipeline._exclude_from_cpu_offload.append("transformer")
    pipeline.enable_sequential_cpu_offload()
    print("  Expected: ~7GB VRAM")
    
else:
    # 5GB: 最小化配置
    transformer.set_offload(True, use_pin_memory=True, num_blocks_on_gpu=1)
    pipeline._exclude_from_cpu_offload = getattr(pipeline, '_exclude_from_cpu_offload', [])
    pipeline._exclude_from_cpu_offload.append("transformer")
    pipeline.enable_sequential_cpu_offload()
    print("  Expected: ~3-5GB VRAM")

gc.collect()
torch.cuda.empty_cache()
print("  [✓] Offload configured")

# ============================================================
# Step 6: Run Inference
# ============================================================
print(f"\n[6/6] Running inference...")

image = load_image(IMAGE_PATH).convert("RGB")
OUTPUT_FILENAME = f"qwen-edit-{mode}-r{RANK}-{NUM_INFERENCE_STEPS}steps.png"

inputs = {
    "image": [image],
    "prompt": prompt,
    "true_cfg_scale": 1.0,
    "num_inference_steps": NUM_INFERENCE_STEPS,
}

if torch.cuda.is_available():
    torch.cuda.reset_peak_memory_stats()
    start_vram = torch.cuda.memory_allocated() / 1024**3
    
    try:
        import psutil
        start_ram = psutil.virtual_memory().used / (1024**3)
    except:
        start_ram = None

t_infer = time.time()
output = pipeline(**inputs)
t_infer_end = time.time()

output.images[0].save(OUTPUT_FILENAME)

inference_time = t_infer_end - t_infer

# Report
if torch.cuda.is_available():
    peak_vram = torch.cuda.max_memory_allocated() / 1024**3
    
    try:
        end_ram = psutil.virtual_memory().used / (1024**3)
        ram_delta = end_ram - start_ram if start_ram else None
    except:
        ram_delta = None

print(f"\n{'='*80}")
print(f"   SUCCESS! Image generated: {OUTPUT_FILENAME}")
print(f"{'='*80}")
print(f"\n    Performance:")
print(f"     Time: {inference_time:.2f}s | Per step: {inference_time/NUM_INFERENCE_STEPS:.2f}s")
print(f"\n   Resources:")
print(f"     Peak VRAM: {peak_vram:.2f} GB (+{peak_vram-start_vram:.2f})")
if ram_delta is not None:
    print(f"     RAM delta: {ram_delta:+.2f} GB")
print(f"\n    Config:")
print(f"     Mode: {mode}")
print(f"     Transformer: {QUANT_TYPE}")
print(f"     Text Encoder: FP16")
print(f"     Output: {os.path.getsize(OUTPUT_FILENAME)/1024:.1f} KB")
print(f"{'='*80}\n")
