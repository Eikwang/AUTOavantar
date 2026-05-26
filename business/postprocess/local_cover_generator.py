"""
本地 AI 封面生成器
使用 Qwen-Image-Edit-2509 模型生成视频封面
"""

import os
import gc
import math
import time
import logging
from typing import Optional, Tuple
from pathlib import Path

import torch
from diffusers import FlowMatchEulerDiscreteScheduler, QwenImageEditPlusPipeline
from diffusers.utils import load_image
from nunchaku import NunchakuQwenImageTransformer2DModel
from nunchaku.utils import get_gpu_memory

logger = logging.getLogger(__name__)


class LocalCoverGenerator:
    """本地 AI 封面生成器"""

    # 模型路径配置 - 使用项目根目录的绝对路径
    # 项目根目录：D:\AI\AUTOavantar
    # 模型目录：D:\AI\AUTOavantar\models\standalone_models
    _project_root = Path(__file__).parent.parent.parent  # business/postprocess -> 项目根目录
    _models_dir = _project_root / "models" / "standalone_models"

    MODEL_PATHS = {
        "fp4": _models_dir / "svdq-fp4_r32-qwen-image-edit-2509-lightning-4steps-251115.safetensors",
        "int4": _models_dir / "svdq-int4_r32-qwen-image-edit-2509-lightning-4steps-251115.safetensors",
    }
    STANDALONE_MODEL_PATH = _models_dir / "Qwen-Image-Edit-2509"

    # 推理参数
    NUM_INFERENCE_STEPS = 4
    RANK = 32

    def __init__(self, use_standalone_model: bool = True):
        """
        初始化封面生成器

        Args:
            use_standalone_model: 是否使用独立模型目录
        """
        self.use_standalone_model = use_standalone_model
        self.pipeline = None
        self.transformer = None
        self._is_initialized = False
        self._mode = None

    def _is_blackwell_gpu(self) -> bool:
        """检测是否为 Blackwell 架构 GPU"""
        if not torch.cuda.is_available():
            return False

        gpu_name = torch.cuda.get_device_name(0)
        blackwell_keywords = [
            "RTX 50", "RTX50",
            "B100", "B200",
            "GB20", "GB10",
            "Blackwell"
        ]

        for keyword in blackwell_keywords:
            if keyword.lower() in gpu_name.lower():
                return True

        try:
            major, minor = torch.cuda.get_device_capability(0)
            if major >= 10:
                return True
        except:
            pass

        return False

    def _get_gpu_memory_gb(self) -> float:
        """获取 GPU 显存大小（GB）"""
        try:
            return get_gpu_memory()
        except:
            return 11.0  # 默认返回 11GB

    def _select_mode(self, gpu_vram_gb: float) -> Tuple[str, str, int]:
        """
        根据显存大小选择运行模式

        Returns:
            (mode_name, quant_type, num_blocks_on_gpu)
        """
        if gpu_vram_gb >= 24:
            return "fp16_ultra", "FP16", 50
        elif gpu_vram_gb >= 15:
            return "fp16_high", "FP16", 30
        elif gpu_vram_gb >= 11:
            return "fp16_medium", "FP16", 20
        elif gpu_vram_gb >= 7:
            return "fp16_low", "FP16", 10
        else:
            return "fp16_minimal", "FP16", 1

    def initialize(self) -> bool:
        """
        初始化模型和 pipeline

        Returns:
            是否初始化成功
        """
        if self._is_initialized:
            logger.info("封面生成器已初始化")
            return True

        try:
            logger.info("=" * 60)
            logger.info("  Nunchaku Pipeline - 封面生成器初始化")
            logger.info("=" * 60)

            # 1. 检测硬件
            gpu_vram_gb = self._get_gpu_memory_gb()
            gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "No GPU"
            use_fp4 = self._is_blackwell_gpu()

            logger.info(f"GPU: {gpu_name}")
            logger.info(f"VRAM: {gpu_vram_gb:.1f} GB")
            logger.info(f"Architecture: {'Blackwell' if use_fp4 else 'Non-Blackwell'}")

            # 2. 选择 Transformer 路径
            transformer_path = self.MODEL_PATHS["fp4"] if use_fp4 else self.MODEL_PATHS["int4"]
            quant_type = "FP4" if use_fp4 else "INT4"
            logger.info(f"Transformer: {quant_type} quantized")
            logger.info(f"Transformer Path: {transformer_path}")

            # 3. 选择运行模式
            mode, _, num_blocks = self._select_mode(gpu_vram_gb)
            self._mode = mode
            logger.info(f"Mode: {mode} ({num_blocks} blocks on GPU)")

            # 4. 加载 Scheduler
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

            # 5. 加载 Transformer
            logger.info("Loading Transformer...")
            t0 = time.time()
            self.transformer = NunchakuQwenImageTransformer2DModel.from_pretrained(transformer_path)
            logger.info(f"[✓] Transformer loaded in {time.time() - t0:.2f}s")

            # 6. 选择模型路径
            if self.use_standalone_model and os.path.exists(self.STANDALONE_MODEL_PATH):
                model_path = self.STANDALONE_MODEL_PATH
                logger.info(f"Using standalone model: {model_path}")
            else:
                model_path = "Qwen/Qwen-Image-Edit-2509"
                logger.info(f"Using HF cache: {model_path}")

            # 7. 加载 Pipeline
            logger.info(f"Loading Pipeline ({mode})...")
            self.pipeline = QwenImageEditPlusPipeline.from_pretrained(
                model_path,
                transformer=self.transformer,
                torch_dtype=torch.bfloat16,
                cache_dir=None if not self.use_standalone_model else None,
                local_files_only=self.use_standalone_model
            )
            logger.info("[✓] Pipeline loaded")

            # 8. 应用 patch
            logger.info("Applying patches...")
            original_transformer_call = self.pipeline.transformer.forward
            def patched_forward(self, *args, **kwargs):
                if 'txt_seq_lens' not in kwargs and 'encoder_hidden_states' in kwargs:
                    kwargs['txt_seq_lens'] = [kwargs['encoder_hidden_states'].shape[1]]
                return original_transformer_call(*args, **kwargs)
            self.pipeline.transformer.forward = lambda *args, **kwargs: patched_forward(self.pipeline.transformer, *args, **kwargs)
            logger.info("[✓] Transformer patch applied")

            # 9. 配置 Offload
            logger.info("Configuring offload...")

            if gpu_vram_gb >= 24:
                self.pipeline.enable_model_cpu_offload()
                logger.info("Strategy: Model CPU offload (24GB+ VRAM)")
            elif gpu_vram_gb >= 15:
                self.transformer.set_offload(True, use_pin_memory=False, num_blocks_on_gpu=num_blocks)
                self.pipeline._exclude_from_cpu_offload = getattr(self.pipeline, '_exclude_from_cpu_offload', [])
                self.pipeline._exclude_from_cpu_offload.append("transformer")
                self.pipeline.enable_sequential_cpu_offload()
                logger.info(f"Strategy: Sequential offload + {num_blocks} Transformer blocks on GPU")
            elif gpu_vram_gb >= 7:
                self.transformer.set_offload(True, use_pin_memory=True, num_blocks_on_gpu=num_blocks)
                self.pipeline._exclude_from_cpu_offload = getattr(self.pipeline, '_exclude_from_cpu_offload', [])
                self.pipeline._exclude_from_cpu_offload.append("transformer")
                self.pipeline.enable_sequential_cpu_offload()
                logger.info(f"Strategy: Sequential offload + {num_blocks} blocks on GPU")
            else:
                self.transformer.set_offload(True, use_pin_memory=True, num_blocks_on_gpu=1)
                self.pipeline._exclude_from_cpu_offload = getattr(self.pipeline, '_exclude_from_cpu_offload', [])
                self.pipeline._exclude_from_cpu_offload.append("transformer")
                self.pipeline.enable_sequential_cpu_offload()
                logger.info("Strategy: Minimal offload (< 7GB VRAM)")

            gc.collect()
            torch.cuda.empty_cache()
            logger.info("[✓] Offload configured")

            self._is_initialized = True
            logger.info("=" * 60)
            logger.info("封面生成器初始化完成")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"封面生成器初始化失败：{e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def generate_cover(
        self,
        reference_image_path: str,
        prompt: str,
        output_path: str,
        strength: float = 0.5
    ) -> Optional[str]:
        """
        生成封面图片

        Args:
            reference_image_path: 参考图片路径
            prompt: 提示词
            output_path: 输出图片路径
            strength: 重绘强度 (0.0-1.0)

        Returns:
            输出图片路径，失败返回 None
        """
        if not self._is_initialized:
            logger.warning("封面生成器未初始化，尝试初始化...")
            if not self.initialize():
                return None

        try:
            logger.info(f"开始生成封面：{reference_image_path} -> {output_path}")
            logger.info(f"提示词：{prompt}")

            # 加载参考图片
            image = load_image(reference_image_path).convert("RGB")

            # 构建输入
            inputs = {
                "image": [image],
                "prompt": prompt,
                "true_cfg_scale": 1.0,
                "num_inference_steps": self.NUM_INFERENCE_STEPS,
            }

            # 记录资源使用
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
                start_vram = torch.cuda.memory_allocated() / 1024**3

            # 执行推理
            t_infer = time.time()
            output = self.pipeline(**inputs)
            t_infer_end = time.time()

            # 保存输出
            output.images[0].save(output_path)

            # 报告
            if torch.cuda.is_available():
                peak_vram = torch.cuda.max_memory_allocated() / 1024**3
                logger.info(f"封面生成成功：{output_path}")
                logger.info(f"推理时间：{t_infer_end - t_infer:.2f}s")
                logger.info(f"峰值显存：{peak_vram:.2f} GB")
            else:
                logger.info(f"封面生成成功：{output_path}")

            # 清理
            gc.collect()
            torch.cuda.empty_cache()

            return output_path

        except Exception as e:
            logger.error(f"封面生成失败：{e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def unload(self):
        """卸载模型，释放显存"""
        if self.pipeline is not None:
            del self.pipeline
            self.pipeline = None
        if self.transformer is not None:
            del self.transformer
            self.transformer = None
        self._is_initialized = False
        gc.collect()
        torch.cuda.empty_cache()
        logger.info("封面生成器已卸载")


# 全局单例
_cover_generator_instance = None


def get_cover_generator() -> Optional[LocalCoverGenerator]:
    """获取封面生成器单例"""
    global _cover_generator_instance
    if _cover_generator_instance is None:
        _cover_generator_instance = LocalCoverGenerator()
    return _cover_generator_instance


def generate_cover_from_reference(
    reference_image_path: str,
    prompt: str,
    output_path: str,
    strength: float = 0.5
) -> Optional[str]:
    """
    便捷函数：从参考图生成封面

    Args:
        reference_image_path: 参考图片路径
        prompt: 提示词
        output_path: 输出图片路径
        strength: 重绘强度

    Returns:
        输出图片路径，失败返回 None
    """
    generator = get_cover_generator()
    if generator is None:
        logger.error("封面生成器获取失败")
        return None

    if not generator._is_initialized:
        if not generator.initialize():
            return None

    return generator.generate_cover(
        reference_image_path=reference_image_path,
        prompt=prompt,
        output_path=output_path,
        strength=strength
    )
