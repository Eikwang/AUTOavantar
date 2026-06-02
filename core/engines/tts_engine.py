"""
TTSEngine - IndexTTS 模型封装类

封装 IndexTTS2 模型，支持直接调用模型推理，无需 HTTP 服务。

核心功能：
1. load() - 加载模型到 GPU
2. unload() - 卸载模型释放显存
3. synthesize() - 执行语音合成，支持情绪标签参数和语速调节

语速调节说明：
IndexTTS 模型本身不支持原生语速调节。本引擎通过 ffmpeg 对参考音频进行 tempo 调节
来实现语速控制。当 speed ≠ 1.0 时，会先用 ffmpeg 调整参考音频的速度，然后使用调整
后的参考音频进行语音合成。

使用方式：
    from core.engines.tts_engine import TTSEngine

    engine = TTSEngine(
        cfg_path="checkpoints/config.yaml",
        model_dir="checkpoints",
        use_fp16=True
    )

    engine.load()
    engine.synthesize(
        text="大家好",
        voice_path="voice.wav",
        output_path="output.wav",
        emotion="开场",
        intensity=0.8,
        speed=1.0  # 1.0=正常, 0.8=慢, 1.2=快
    )
    engine.unload()
"""

import gc
import logging
import os
import platform
import subprocess
import sys
from typing import Optional, Dict, Any, List
from pathlib import Path as _Path

# FFmpeg 绝对路径（跨平台兼容）
_PROJECT_ROOT = _Path(__file__).parent.parent.parent
_FFMPEG_EXE = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
FFMPEG_PATH = str(_PROJECT_ROOT / "runtime" / "ffmpeg" / "bin" / _FFMPEG_EXE)

logger = logging.getLogger("autoavantar.tts_engine")


class TTSEngine:
    """
    TTS 引擎封装类 - 封装 IndexTTS2 模型

    支持：
    - 直接调用模型推理（无需 HTTP 服务）
    - GPU 显存管理（load/unload）
    - 情绪标签和强度参数
    - 与 GPUResourceManager 集成
    """

    def __init__(
        self,
        cfg_path: str = "checkpoints/config.yaml",
        model_dir: str = "checkpoints",
        use_fp16: bool = True,
        device: Optional[str] = None,
        use_cuda_kernel: bool = False,
        use_torch_compile: bool = False,
        managed: bool = True,
        preload_model: bool = True,
        ultra_low_memory: bool = False
    ):
        """
        初始化 TTSEngine

        Args:
            cfg_path: IndexTTS 配置文件路径
            model_dir: IndexTTS 模型目录
            use_fp16: 是否使用 FP16 精度
            device: 设备（cuda:0, cpu 等），None 则自动选择
            use_cuda_kernel: 是否使用 CUDA kernel
            use_torch_compile: 是否使用 torch.compile 优化
            managed: 是否由 GPUResourceManager 管理
            preload_model: 是否在初始化时预加载模型（低显存模式时设为 False）
            ultra_low_memory: 是否启用超低显存模式（延迟加载 + 推理后释放）
                             当 True 时，只加载基础模型，其他模型按需加载
                             默认 False 以保持现有行为
        """
        self.cfg_path = cfg_path
        self.model_dir = model_dir
        self.use_fp16 = use_fp16
        self.device = device
        self.use_cuda_kernel = use_cuda_kernel
        self.use_torch_compile = use_torch_compile
        self.managed = managed
        self._preload_model = preload_model
        self._ultra_low_memory = ultra_low_memory

        # 内部状态
        self._model: Optional[Any] = None
        self._is_loaded: bool = False
        self._emotion_mapping: Dict[str, List[float]] = {}
        self._progress_callback: Optional[callable] = None  # 进度回调函数

        # 设置 HF 环境变量（离线模式、缓存路径）
        self._setup_hf_environment()

        # 注册到 GPU 资源管理器
        if self.managed:
            self._register_to_gpu_manager()

        logger.info(f"TTSEngine 初始化: cfg_path={cfg_path}, model_dir={model_dir}, use_fp16={use_fp16}, preload_model={preload_model}, ultra_low_memory={ultra_low_memory}")

        # 如果 preload_model=True，立即加载模型
        if preload_model:
            self.load()

    def _setup_hf_environment(self):
        """设置 HuggingFace 环境变量"""
        # 设置离线模式
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'

        # 设置缓存路径
        hf_cache = os.path.join(self.model_dir, 'hf_cache')
        os.makedirs(hf_cache, exist_ok=True)
        os.environ['HF_HUB_CACHE'] = hf_cache
        os.environ['HF_HOME'] = hf_cache

        logger.debug(f"HF 环境变量已设置: HF_HUB_CACHE={hf_cache}")

    def _register_to_gpu_manager(self):
        """注册到 GPU 资源管理器"""
        try:
            from core.engines.gpu_manager import get_gpu_manager, EngineType

            gpu_manager = get_gpu_manager()
            gpu_manager.register_engine(EngineType.TTS, self)
            logger.info("TTSEngine 已注册到 GPUResourceManager")
        except Exception as e:
            logger.warning(f"注册到 GPUResourceManager 失败: {e}")

    def _load_emotion_mapping(self) -> Dict[str, List[float]]:
        """
        加载情绪向量映射
        唯一来源：voicel/emotion_mapping.yaml

        Returns:
            情绪名称到向量列表的映射
        """
        # 查找 voicel 目录下的 emotion_mapping.yaml（唯一来源）
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        voicel_dir = os.path.join(project_root, "voicel")

        # 查找顺序：voicel 目录 > model_dir 目录
        possible_paths = [
            os.path.join(voicel_dir, "emotion_mapping.yaml"),
            os.path.join(self.model_dir, "emotion_mapping.yaml")
        ]

        mapping_path = None
        for path in possible_paths:
            if os.path.exists(path):
                mapping_path = path
                break

        emotion_mapping = {}

        if mapping_path:
            try:
                import yaml
                with open(mapping_path, 'r', encoding='utf-8') as f:
                    custom_mapping = yaml.safe_load(f)
                if custom_mapping:
                    # 处理 YAML 格式：每个情绪包含 vec1-vec8 和 speed
                    for emotion_name, params in custom_mapping.items():
                        if isinstance(params, dict):
                            # 提取 vec1-vec8 组成向量
                            vec = [
                                params.get(f"vec{i}", 0.0) for i in range(1, 9)
                            ]
                            emotion_mapping[emotion_name] = vec
                            # 同时保存 speed 参数（后续合成时使用）
                            if "speed" in params:
                                emotion_mapping[f"{emotion_name}_speed"] = params["speed"]
                    logger.info(f"已加载情绪映射: {mapping_path}, 共 {len(custom_mapping)} 种情绪")
            except Exception as e:
                logger.error(f"加载情绪映射文件失败: {e}")
        else:
            logger.warning("未找到 emotion_mapping.yaml 文件，情绪向量将为空")

        return emotion_mapping

    def _adjust_audio_speed(self, audio_path: str, speed: float) -> str:
        """
        使用 ffmpeg 调节音频速度（tempo）

        Args:
            audio_path: 原始音频路径
            speed: 速度倍率（1.0=正常, 0.5=半速, 2.0=双倍速）
                   推荐范围：0.5-2.0，超出此范围可能导致音频质量下降

        Returns:
            调整后的音频路径（临时文件）

        Raises:
            RuntimeError: ffmpeg 执行失败
        """
        if speed == 1.0:
            # 不需要调整，直接返回原路径
            return audio_path

        # 创建项目内的临时目录 temp/audio
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        temp_dir = os.path.join(project_root, "temp", "audio")
        os.makedirs(temp_dir, exist_ok=True)

        # 生成临时文件名（使用时间戳避免冲突）
        # 保持源文件扩展名，让 ffmpeg 根据扩展名自动选择编码器
        import time
        timestamp = int(time.time() * 1000)
        src_ext = os.path.splitext(audio_path)[1] or ".wav"
        temp_filename = f"tts_speed_{timestamp}{src_ext}"
        temp_path = os.path.join(temp_dir, temp_filename)

        # 确保 temp_path 不与现有文件冲突
        if os.path.exists(temp_path):
            os.remove(temp_path)

        # ffmpeg tempo 滤镜参数
        # tempo 滤镜接受的值范围是 0.5 到 2.0
        # 对于超出范围的值，需要多次应用滤镜
        if 0.5 <= speed <= 2.0:
            tempo_filter = f"atempo={speed}"
        else:
            # 对于超出范围的值，分解为多次应用
            # 例如 speed=4.0 -> atempo=2.0,atempo=2.0
            factors = []
            remaining = speed
            while remaining > 2.0:
                factors.append(2.0)
                remaining /= 2.0
            while remaining < 0.5:
                factors.append(0.5)
                remaining /= 0.5
            factors.append(remaining)
            tempo_filter = ",".join([f"atempo={f}" for f in factors])

        # 构建 ffmpeg 命令
        # 不指定编码器，让 ffmpeg 根据输出扩展名自动选择
        cmd = [
            FFMPEG_PATH,
            "-y",  # 覆盖输出文件
            "-i", audio_path,
            "-filter:a", tempo_filter,
            temp_path
        ]

        logger.debug(f"执行 ffmpeg 命令调整音频速度: {cmd}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )
            logger.info(f"音频速度调整完成: speed={speed}, 输出={temp_path}")
            return temp_path
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg 执行失败: {e.stderr}")
            raise RuntimeError(f"ffmpeg 执行失败: {e.stderr}")
        except FileNotFoundError:
            logger.error("ffmpeg 未安装或不在 PATH 中")
            raise RuntimeError("ffmpeg 未安装或不在 PATH 中，无法调整音频速度")

    @property
    def is_loaded(self) -> bool:
        """模型是否已加载"""
        return self._is_loaded

    @property
    def is_model_loaded(self) -> bool:
        """模型是否已加载（is_loaded 的别名，用于统一接口）"""
        return self._is_loaded

    def load(self) -> bool:
        """
        加载模型到 GPU

        Returns:
            是否成功加载
        """
        if self._is_loaded:
            logger.info("模型已加载，跳过重复加载")
            return True

        try:
            # 添加 voicel 目录到 Python 路径（IndexTTS 模块所在位置）
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            voicel_path = os.path.join(project_root, "voicel")

            if voicel_path not in sys.path:
                sys.path.insert(0, voicel_path)

            # 导入 IndexTTS2
            from indextts.infer_v2 import IndexTTS2

            # 加载模型
            logger.info(f"正在加载 IndexTTS2 模型: cfg_path={self.cfg_path}, model_dir={self.model_dir}")

            self._model = IndexTTS2(
                cfg_path=self.cfg_path,
                model_dir=self.model_dir,
                use_fp16=self.use_fp16,
                device=self.device,
                use_cuda_kernel=self.use_cuda_kernel,
                use_torch_compile=self.use_torch_compile,
                ultra_low_memory=self._ultra_low_memory
            )

            # 加载情绪映射
            self._emotion_mapping = self._load_emotion_mapping()

            self._is_loaded = True
            logger.info("IndexTTS2 模型加载成功")
            return True

        except Exception as e:
            logger.error(f"加载 IndexTTS2 模型失败: {e}")
            self._is_loaded = False
            self._model = None
            return False

    def unload(self) -> bool:
        """
        卸载模型释放显存

        Returns:
            是否成功卸载
        """
        if not self._is_loaded:
            logger.info("模型未加载，跳过卸载")
            return True

        try:
            # 清理模型引用
            if self._model is not None:
                # 尝试显式删除模型对象
                try:
                    # 如果模型有显式的清理方法，调用它
                    if hasattr(self._model, 'cleanup'):
                        self._model.cleanup()
                    elif hasattr(self._model, 'release'):
                        self._model.release()

                    # 显式删除模型对象
                    del self._model
                    self._model = None
                except Exception as e:
                    logger.warning(f"删除模型对象时出错: {e}")
                    self._model = None

            # 清理 CUDA 缓存并强制同步
            try:
                import torch
                if torch.cuda.is_available():
                    # 等待所有 CUDA 操作完成
                    torch.cuda.synchronize()
                    # 清理缓存
                    torch.cuda.empty_cache()
                    # 再次同步确保清理完成
                    torch.cuda.synchronize()
                    logger.debug("CUDA 缓存已清理")
            except ImportError:
                pass

            # 多次垃圾回收确保完全释放循环引用
            # 第一次回收可能只标记对象，第二次才能真正释放
            gc.collect()
            gc.collect()
            gc.collect()

            self._is_loaded = False
            logger.info("IndexTTS2 模型已卸载，显存已释放")
            return True

        except Exception as e:
            logger.error(f"卸载模型失败: {e}")
            return False

    def set_progress_callback(self, callback: Optional[callable]):
        """
        设置进度回调函数

        Args:
            callback: 进度回调函数，签名为 (progress: float, description: str)
                     progress: 0.0-1.0 的进度值
                     description: 进度描述文本
        """
        self._progress_callback = callback
        # 如果模型已加载，同步设置模型的 gr_progress
        if self._model is not None:
            self._model.gr_progress = callback
        logger.debug(f"进度回调已设置: {callback is not None}")

    def synthesize(
        self,
        text: str,
        voice_path: str,
        output_path: str,
        emotion: Optional[str] = None,
        intensity: float = 1.0,
        **kwargs
    ) -> Optional[str]:
        """
        执行语音合成

        Args:
            text: 要合成的文本
            voice_path: 参考音频路径（用于声音克隆）
            output_path: 输出音频路径
            emotion: 情绪标签（如 "开场", "开心", "难过" 等）
            intensity: 情绪强度 (0.0-1.0)
            **kwargs: 其他参数（如 temperature, top_p, speed 等）
                     speed: 语速倍率（1.0=正常, 0.8=慢, 1.2=快）

        Returns:
            生成的音频路径，失败返回 None

        Raises:
            RuntimeError: 模型未加载时抛出异常
        """
        if not self._is_loaded:
            raise RuntimeError("模型未加载，请先调用 load() 方法")

        if not os.path.exists(voice_path):
            raise FileNotFoundError(f"参考音频不存在: {voice_path}")

        # 设置模型的进度回调（用于超低显存模式下的模型加载进度）
        if self._model is not None and self._progress_callback is not None:
            self._model.gr_progress = self._progress_callback

        # 用于跟踪临时文件，确保在函数结束时清理
        temp_voice_path = None

        try:
            # 准备情绪向量
            emo_vector = None
            speed = kwargs.get('speed', 1.0)  # 默认正常语速

            if emotion and emotion in self._emotion_mapping:
                base_vector = self._emotion_mapping[emotion]
                # 不使用强度缩放，直接使用设定值
                emo_vector = base_vector
                # 从映射中获取语速参数（如果存在）
                speed_key = f"{emotion}_speed"
                if speed_key in self._emotion_mapping:
                    speed = self._emotion_mapping[speed_key]
                logger.debug(f"情绪向量: emotion={emotion}, intensity={intensity}, vector={emo_vector}, speed={speed}")

            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            # 语速调节：如果 speed ≠ 1.0，使用 ffmpeg 调整参考音频的速度
            actual_voice_path = voice_path
            if speed != 1.0:
                logger.info(f"调整参考音频速度: speed={speed}")
                try:
                    temp_voice_path = self._adjust_audio_speed(voice_path, speed)
                    actual_voice_path = temp_voice_path
                    logger.info(f"使用调整后的参考音频: {actual_voice_path}")
                except RuntimeError as e:
                    logger.warning(f"音频速度调整失败，使用原始音频: {e}")
                    actual_voice_path = voice_path

            # 调用模型推理
            logger.info(f"开始语音合成: text={text[:50]}..., voice={actual_voice_path}, output={output_path}")

            result = self._model.infer(
                spk_audio_prompt=actual_voice_path,
                text=text,
                output_path=output_path,
                emo_vector=emo_vector,
                emo_alpha=intensity if emo_vector else 1.0,
                verbose=kwargs.get('verbose', False)
            )

            # 处理返回值（infer 可能返回生成器）
            if result is not None:
                # 如果是生成器，取第一个值
                if hasattr(result, '__iter__') and not isinstance(result, str):
                    try:
                        result = list(result)[0]
                    except (StopIteration, IndexError):
                        result = output_path

                logger.info(f"语音合成完成: {result}")
                return result if isinstance(result, str) else output_path

            return output_path if os.path.exists(output_path) else None

        except Exception as e:
            logger.error(f"语音合成失败: {e}")
            return None

        finally:
            # 清理临时文件
            if temp_voice_path is not None and os.path.exists(temp_voice_path):
                try:
                    os.remove(temp_voice_path)
                    logger.debug(f"已清理临时音频文件: {temp_voice_path}")
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")

    def synthesize_batch(
        self,
        texts: List[str],
        voice_path: str,
        output_dir: str,
        emotions: Optional[List[str]] = None,
        intensities: Optional[List[float]] = None,
        **kwargs
    ) -> List[Optional[str]]:
        """
        批量语音合成

        Args:
            texts: 文本列表
            voice_path: 参考音频路径
            output_dir: 输出目录
            emotions: 情绪标签列表
            intensities: 情绪强度列表
            **kwargs: 其他参数

        Returns:
            生成的音频路径列表
        """
        results = []

        for i, text in enumerate(texts):
            # 生成输出路径
            output_path = os.path.join(output_dir, f"segment_{i}.wav")

            # 获取情绪参数
            emotion = emotions[i] if emotions and i < len(emotions) else None
            intensity = intensities[i] if intensities and i < len(intensities) else 1.0

            # 合成
            result = self.synthesize(
                text=text,
                voice_path=voice_path,
                output_path=output_path,
                emotion=emotion,
                intensity=intensity,
                **kwargs
            )
            results.append(result)

        return results

    def get_memory_info(self) -> Dict[str, Any]:
        """
        获取显存信息

        Returns:
            显存使用情况
        """
        try:
            import torch
            if torch.cuda.is_available():
                device = torch.cuda.current_device()
                total = torch.cuda.get_device_properties(device).total_memory
                allocated = torch.cuda.memory_allocated(device)
                reserved = torch.cuda.memory_reserved(device)
                return {
                    "total_mb": total / 1024 / 1024,
                    "allocated_mb": allocated / 1024 / 1024,
                    "reserved_mb": reserved / 1024 / 1024,
                    "free_mb": (total - allocated) / 1024 / 1024,
                    "is_loaded": self._is_loaded
                }
        except ImportError:
            pass
        except Exception as e:
            logger.error(f"获取显存信息失败: {e}")

        return {
            "total_mb": 0,
            "allocated_mb": 0,
            "reserved_mb": 0,
            "free_mb": 0,
            "is_loaded": self._is_loaded
        }


def create_tts_engine(
    cfg_path: str = "checkpoints/config.yaml",
    model_dir: str = "checkpoints",
    use_fp16: bool = True,
    managed: bool = True,
    preload_model: bool = True,
    ultra_low_memory: bool = False
) -> TTSEngine:
    """
    创建 TTSEngine 的便捷函数

    Args:
        cfg_path: 配置文件路径
        model_dir: 模型目录
        use_fp16: 是否使用 FP16
        managed: 是否由 GPUResourceManager 管理
        preload_model: 是否在初始化时预加载模型
        ultra_low_memory: 是否启用超低显存模式

    Returns:
        TTSEngine 实例
    """
    return TTSEngine(
        cfg_path=cfg_path,
        model_dir=model_dir,
        use_fp16=use_fp16,
        managed=managed,
        preload_model=preload_model,
        ultra_low_memory=ultra_low_memory
    )
    