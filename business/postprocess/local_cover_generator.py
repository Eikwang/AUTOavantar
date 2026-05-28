"""
本地 AI 封面生成器
直接基于 local_adaptive.py 核心逻辑重构
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
    """本地 AI 封面生成器 - 直接复用 local_adaptive.py 核心逻辑"""

    _project_root = Path(__file__).parent.parent.parent
    _models_dir = _project_root / "models" / "standalone_models"

    MODEL_PATHS = {
        "fp4": str(_models_dir / "svdq-fp4_r32-qwen-image-edit-2509-lightning-4steps-251115.safetensors"),
        "int4": str(_models_dir / "svdq-int4_r32-qwen-image-edit-2509-lightning-4steps-251115.safetensors"),
    }
    STANDALONE_MODEL_PATH = str(_models_dir / "Qwen-Image-Edit-2509")

    NUM_INFERENCE_STEPS = 4
    RANK = 32

    def __init__(self, use_standalone_model: bool = True):
        self.use_standalone_model = use_standalone_model
        self.pipeline = None
        self.transformer = None
        self._is_initialized = False
        self._mode = None
        self._gpu_vram_gb = 0.0
        self._num_blocks = 0
        self._use_pin_memory = False
        self._use_fp4 = False

    def _is_blackwell_gpu(self) -> bool:
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
        try:
            return get_gpu_memory()
        except:
            return 11.0

    def _select_mode(self, gpu_vram_gb: float) -> Tuple[str, int, bool]:
        """
        根据显存大小选择运行模式
        返回: (mode_name, num_blocks_on_gpu, use_pin_memory)
        """
        if gpu_vram_gb >= 24:
            return "fp16_ultra", 50, False
        elif gpu_vram_gb >= 15:
            return "fp16_high", 50, False
        elif gpu_vram_gb >= 11:
            return "fp16_medium", 30, False
        elif gpu_vram_gb >= 7:
            return "fp16_low", 20, True
        else:
            return "fp16_minimal", 1, True

    def initialize(self) -> bool:
        """初始化模型和 pipeline - 直接复用 local_adaptive.py 逻辑"""
        if self._is_initialized:
            logger.info("封面生成器已初始化")
            return True

        try:
            logger.info("=" * 60)
            logger.info("  Nunchaku Pipeline - 封面生成器初始化")
            logger.info("=" * 60)

            self._gpu_vram_gb = self._get_gpu_memory_gb()
            gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "No GPU"
            self._use_fp4 = self._is_blackwell_gpu()

            logger.info(f"GPU: {gpu_name}")
            logger.info(f"VRAM: {self._gpu_vram_gb:.1f} GB")
            logger.info(f"Architecture: {'Blackwell' if self._use_fp4 else 'Non-Blackwell'}")

            transformer_path = self.MODEL_PATHS["fp4"] if self._use_fp4 else self.MODEL_PATHS["int4"]
            quant_type = "FP4" if self._use_fp4 else "INT4"
            logger.info(f"Transformer: {quant_type} quantized")
            logger.info(f"Transformer Path: {transformer_path}")

            self._mode, self._num_blocks, self._use_pin_memory = self._select_mode(self._gpu_vram_gb)
            logger.info(f"Mode: {self._mode} ({self._num_blocks} blocks on GPU, pin_memory={self._use_pin_memory})")

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

            logger.info("Loading Transformer...")
            t0 = time.time()
            self.transformer = NunchakuQwenImageTransformer2DModel.from_pretrained(transformer_path)
            logger.info(f"[✓] Transformer loaded in {time.time() - t0:.2f}s")

            if self.use_standalone_model and os.path.exists(self.STANDALONE_MODEL_PATH):
                model_path = self.STANDALONE_MODEL_PATH
                logger.info(f"Using standalone model: {model_path}")
            else:
                model_path = "Qwen/Qwen-Image-Edit-2509"
                logger.info(f"Using HF cache: {model_path}")

            logger.info(f"Loading Pipeline ({self._mode})...")
            self.pipeline = QwenImageEditPlusPipeline.from_pretrained(
                model_path,
                transformer=self.transformer,
                torch_dtype=torch.bfloat16,
                local_files_only=self.use_standalone_model
            )
            logger.info("[✓] Pipeline loaded")

            logger.info("Applying patches...")
            original_transformer_call = self.pipeline.transformer.forward
            def patched_forward(self, *args, **kwargs):
                if 'txt_seq_lens' not in kwargs and 'encoder_hidden_states' in kwargs:
                    kwargs['txt_seq_lens'] = [kwargs['encoder_hidden_states'].shape[1]]
                return original_transformer_call(*args, **kwargs)
            self.pipeline.transformer.forward = lambda *args, **kwargs: patched_forward(self.pipeline.transformer, *args, **kwargs)
            logger.info("[✓] Transformer patch applied")

            logger.info("Configuring offload...")

            if self._gpu_vram_gb >= 24:
                self.pipeline.enable_model_cpu_offload()
                logger.info("Strategy: Model CPU offload (24GB+ VRAM)")
            elif self._gpu_vram_gb >= 15:
                self.transformer.set_offload(True, use_pin_memory=self._use_pin_memory, num_blocks_on_gpu=self._num_blocks)
                self.pipeline._exclude_from_cpu_offload = getattr(self.pipeline, '_exclude_from_cpu_offload', [])
                self.pipeline._exclude_from_cpu_offload.append("transformer")
                self.pipeline.enable_sequential_cpu_offload()
                logger.info(f"Strategy: Sequential offload + {self._num_blocks} Transformer blocks on GPU")
            elif self._gpu_vram_gb >= 11:
                self.transformer.set_offload(True, use_pin_memory=self._use_pin_memory, num_blocks_on_gpu=self._num_blocks)
                self.pipeline._exclude_from_cpu_offload = getattr(self.pipeline, '_exclude_from_cpu_offload', [])
                self.pipeline._exclude_from_cpu_offload.append("transformer")
                self.pipeline.enable_sequential_cpu_offload()
                logger.info(f"Strategy: Sequential offload + {self._num_blocks} Transformer blocks on GPU")
            elif self._gpu_vram_gb >= 7:
                self.transformer.set_offload(True, use_pin_memory=self._use_pin_memory, num_blocks_on_gpu=self._num_blocks)
                self.pipeline._exclude_from_cpu_offload = getattr(self.pipeline, '_exclude_from_cpu_offload', [])
                self.pipeline._exclude_from_cpu_offload.append("transformer")
                self.pipeline.enable_sequential_cpu_offload()
                logger.info(f"Strategy: Sequential offload + {self._num_blocks} blocks on GPU")
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
        output_path: str
    ) -> Optional[str]:
        """
        生成封面图片

        Args:
            reference_image_path: 参考图片路径
            prompt: 提示词
            output_path: 输出图片路径

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

            image = load_image(reference_image_path).convert("RGB")

            inputs = {
                "image": [image],
                "prompt": prompt,
                "true_cfg_scale": 1.0,
                "num_inference_steps": self.NUM_INFERENCE_STEPS,
            }

            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
                start_vram = torch.cuda.memory_allocated() / 1024**3

            t_infer = time.time()
            output = self.pipeline(**inputs)
            t_infer_end = time.time()

            output.images[0].save(output_path)

            inference_time = t_infer_end - t_infer

            if torch.cuda.is_available():
                peak_vram = torch.cuda.max_memory_allocated() / 1024**3
                logger.info(f"封面生成成功：{output_path}")
                logger.info(f"推理时间：{inference_time:.2f}s | 每步: {inference_time/self.NUM_INFERENCE_STEPS:.2f}s")
                logger.info(f"峰值显存：{peak_vram:.2f} GB")
                logger.info(f"模式：{self._mode} | Transformer: {'FP4' if self._use_fp4 else 'INT4'}")
            else:
                logger.info(f"封面生成成功：{output_path}")

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
) -> Optional[str]:
    """
    便捷函数：从参考图生成封面

    Args:
        reference_image_path: 参考图片路径
        prompt: 提示词
        output_path: 输出图片路径

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
        output_path=output_path
    )

