"""
HeyGemEngine - HeyGem 视频生成引擎封装类

封装 HeyGem 的 TransDhTask，支持直接调用视频生成，无需 HTTP 服务。

核心功能：
1. load() - 初始化 TransDhTask 单例
2. unload() - 调用 cleanup 释放显存
3. generate_video() - 执行视频生成
4. generate_video_simple() - 简化接口

使用方式：
    from core.engines.heygem_engine import HeyGemEngine

    engine = HeyGemEngine(heygem_root="engines/heygem")
    engine.load()
    engine.generate_video_simple(
        audio_path="audio.wav",
        video_path="source.mp4",
        task_id="task_001"
    )
    engine.unload()
"""

import gc
import logging
import os
import sys
import time
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("autoavantar.heygem_engine")


class HeyGemEngine:
    """
    HeyGem 引擎封装类 - 封装 TransDhTask

    支持：
    - 直接调用视频生成（无需 HTTP 服务）
    - GPU 显存管理（load/unload）
    - 与 GPUResourceManager 集成
    """

    def __init__(
        self,
        heygem_root: str = "engines/heygem",
        batch_size: int = 4,
        device: Optional[str] = None,
        managed: bool = True,
        preload_model: bool = True
    ):
        """
        初始化 HeyGemEngine

        Args:
            heygem_root: HeyGem 根目录
            batch_size: 批处理大小
            device: 设备（cuda:0, cpu 等），None 则自动选择
            managed: 是否由 GPUResourceManager 管理
            preload_model: 是否在初始化时预加载模型（低显存模式时设为 False）
        """
        self.heygem_root = heygem_root
        self.batch_size = batch_size
        self.device = device
        self.managed = managed
        self._preload_model = preload_model

        # 内部状态
        self._trans_dh_task: Optional[Any] = None
        self._is_loaded: bool = False
        self._original_cwd: Optional[str] = None

        # 注册到 GPU 资源管理器
        if self.managed:
            self._register_to_gpu_manager()

        logger.info(f"HeyGemEngine 初始化: heygem_root={heygem_root}, batch_size={batch_size}, preload_model={preload_model}")

        # 如果 preload_model=True，立即加载模型
        if preload_model:
            self.load()

    def _register_to_gpu_manager(self):
        """注册到 GPU 资源管理器"""
        try:
            from core.engines.gpu_manager import get_gpu_manager, EngineType

            gpu_manager = get_gpu_manager()
            gpu_manager.register_engine(EngineType.HEYGEM, self)
            logger.info("HeyGemEngine 已注册到 GPUResourceManager")
        except Exception as e:
            logger.warning(f"注册到 GPUResourceManager 失败: {e}")

    @property
    def is_loaded(self) -> bool:
        """引擎是否已加载"""
        return self._is_loaded

    @property
    def is_model_loaded(self) -> bool:
        """引擎是否已加载（is_loaded 的别名，用于统一接口）"""
        return self._is_loaded

    def load(self) -> bool:
        """
        加载引擎（初始化 TransDhTask 单例）

        Returns:
            是否成功加载
        """
        if self._is_loaded:
            logger.info("引擎已加载，跳过重复加载")
            return True

        try:
            # 保存当前工作目录
            self._original_cwd = os.getcwd()

            # 切换到 HeyGem 根目录（TransDhTask 需要在此目录下运行）
            heygem_abs_path = os.path.abspath(self.heygem_root)
            if not os.path.exists(heygem_abs_path):
                raise FileNotFoundError(f"HeyGem 根目录不存在: {heygem_abs_path}")

            os.chdir(heygem_abs_path)
            logger.info(f"切换工作目录: {heygem_abs_path}")

            # 确保 temp 和 result 目录存在（config.ini 中使用相对路径）
            os.makedirs("temp", exist_ok=True)
            os.makedirs("result", exist_ok=True)
            logger.info("已创建 temp 和 result 目录")

            # 添加 HeyGem 目录到 Python 路径
            if heygem_abs_path not in sys.path:
                sys.path.insert(0, heygem_abs_path)

            # 尝试导入 TransDhTask
            # 注意：实际路径可能不同，需要根据 HeyGem 项目结构调整
            try:
                from engines.heygem.service.trans_dh_service import TransDhTask
                logger.info("从 engines.heygem.service.trans_dh_service 导入 TransDhTask")
            except ImportError:
                try:
                    from service.trans_dh_service import TransDhTask
                    logger.info("从 service.trans_dh_service 导入 TransDhTask")
                except ImportError:
                    try:
                        from trans_dh_service import TransDhTask
                        logger.info("从 trans_dh_service 导入 TransDhTask")
                    except ImportError as e:
                        logger.error(f"无法导入 TransDhTask: {e}")
                        # 模拟模式：创建一个模拟对象用于测试
                        logger.warning("使用模拟模式（TransDhTask 不可用）")
                        self._trans_dh_task = self._create_mock_task()
                        self._is_loaded = True
                        return True

            # 获取单例，传递 batch_size 参数
            self._trans_dh_task = TransDhTask.instance(batch_size=self.batch_size)

            self._is_loaded = True
            logger.info(f"HeyGem 引擎加载成功，batch_size={self.batch_size}")
            return True

        except Exception as e:
            logger.error(f"加载 HeyGem 引擎失败: {e}")
            self._is_loaded = False
            self._trans_dh_task = None
            # 恢复工作目录
            if self._original_cwd:
                os.chdir(self._original_cwd)
            return False

    def _create_mock_task(self):
        """创建模拟的 TransDhTask 用于测试"""
        class MockTransDhTask:
            def instance(self):
                return self

            def work(self, *args, **kwargs):
                return {"status": "success", "output_path": "mock_output.mp4"}

            def cleanup(self):
                pass

        return MockTransDhTask()

    def unload(self) -> bool:
        """
        卸载引擎（调用 cleanup 释放显存）

        Returns:
            是否成功卸载
        """
        if not self._is_loaded:
            logger.info("引擎未加载，跳过卸载")
            return True

        try:
            # 调用 cleanup 释放显存
            if self._trans_dh_task is not None:
                try:
                    if hasattr(self._trans_dh_task, 'cleanup'):
                        self._trans_dh_task.cleanup()
                        logger.info("TransDhTask cleanup 完成")
                except Exception as e:
                    logger.warning(f"TransDhTask cleanup 失败: {e}")

                # 显式删除对象
                try:
                    del self._trans_dh_task
                except Exception:
                    pass
                self._trans_dh_task = None

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
            gc.collect()
            gc.collect()
            gc.collect()

            # 恢复工作目录
            if self._original_cwd:
                os.chdir(self._original_cwd)
                self._original_cwd = None

            self._is_loaded = False
            logger.info("HeyGem 引擎已卸载，显存已释放")
            return True

        except Exception as e:
            logger.error(f"卸载引擎失败: {e}")
            return False

    def generate_video(
        self,
        audio_path: str,
        video_path: str,
        output_path: str,
        face_id: int = 0,
        steps: int = 16,
        batch_size: int = 4,
        ifface: bool = True,
        chaofen: int = 0,
        **kwargs
    ) -> Tuple[bool, Optional[str]]:
        """
        执行视频生成

        Args:
            audio_path: 音频文件路径
            video_path: 源视频路径
            output_path: 输出视频路径
            face_id: 面部编号（0=左边，1=右边）
            steps: 推理步数
            batch_size: 推理批次大小（影响队列批处理）
            ifface: 是否使用原始参数模式
            chaofen: 超分开关 (0=不启用, 1=启用)
            **kwargs: 其他参数

        Returns:
            (是否成功, 输出路径或错误信息)

        Raises:
            RuntimeError: 引擎未加载时抛出异常
        """
        if not self._is_loaded:
            raise RuntimeError("引擎未加载，请先调用 load() 方法")

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        try:
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            # 生成任务代码（使用输出文件名作为任务标识）
            task_code = os.path.splitext(os.path.basename(output_path))[0]

            logger.info(f"开始视频生成: audio={audio_path}, video={video_path}, output={output_path}, batch_size={batch_size}")

            # TransDhTask.work() 参数签名:
            # work(self, audio_url, video_url, code, watermark_switch, digital_auth, chaofen, pn, target_face_id=0, batch_size=4)
            # 参数说明:
            # - audio_url: 音频文件路径
            # - video_url: 视频文件路径
            # - code: 任务代码（用于标识任务，输出文件名为 {code}.mp4）
            # - watermark_switch: 水印开关 (0/1)
            # - digital_auth: 数字授权 (0/1)
            # - chaofen: 超分开关 (0/1)
            # - pn: 批次处理模式 (1=ping-pong模式, 其他=顺序模式)
            # - target_face_id: 目标面部ID
            # - batch_size: 推理批次大小

            start_time = time.time()

            # 直接调用 TransDhTask.work()，使用位置参数
            # 传递 output_path 让 write_video 直接保存到目标路径，避免额外的文件复制
            if hasattr(self._trans_dh_task, 'work'):
                self._trans_dh_task.work(
                    audio_url=audio_path,
                    video_url=video_path,
                    code=task_code,
                    watermark_switch=0,  # 不添加水印
                    digital_auth=0,       # 无数字授权
                    chaofen=chaofen,          # 超分开关 (0=不启用, 1=启用)
                    pn=1,                 # 使用 ping-pong 模式
                    target_face_id=face_id,
                    batch_size=batch_size,  # 推理批次大小
                    output_path=output_path  # 直接输出到目标路径
                )
            else:
                raise RuntimeError("TransDhTask 没有 work 方法")

            elapsed = time.time() - start_time
            logger.info(f"视频生成完成，耗时: {elapsed:.2f}s")

            # 如果传递了 output_path，write_video 会直接保存到目标路径
            # 不需要额外的文件移动操作
            if os.path.exists(output_path):
                logger.info(f"视频已直接保存到: {output_path}")
                return True, output_path

            # 兼容旧版本：检查 result_dir 中的输出文件
            from y_utils.config import GlobalConfig
            result_dir = GlobalConfig.instance().result_dir
            # write_video 保存的文件名带有 -r 后缀
            expected_output = os.path.join(result_dir, f"{task_code}-r.mp4")

            if os.path.exists(expected_output):
                # 移动到指定的输出路径
                if expected_output != output_path:
                    import shutil
                    shutil.move(expected_output, output_path)
                    logger.info(f"移动输出文件: {expected_output} -> {output_path}")
                return True, output_path
            else:
                # 尝试不带 -r 后缀的路径（兼容旧版本）
                fallback_output = os.path.join(result_dir, f"{task_code}.mp4")
                if os.path.exists(fallback_output):
                    if fallback_output != output_path:
                        import shutil
                        shutil.move(fallback_output, output_path)
                        logger.info(f"移动输出文件: {fallback_output} -> {output_path}")
                    return True, output_path
                return False, f"输出文件不存在: {expected_output}"

        except Exception as e:
            logger.error(f"视频生成失败: {e}")
            return False, str(e)

    def generate_video_simple(
        self,
        audio_path: str,
        video_path: str,
        task_id: str,
        output_dir: str = "temp/video",
        face_id: int = 0,
        **kwargs
    ) -> Optional[str]:
        """
        简化的视频生成接口

        Args:
            audio_path: 音频文件路径
            video_path: 源视频路径
            task_id: 任务 ID（用于生成输出文件名）
            output_dir: 输出目录
            face_id: 面部编号
            **kwargs: 其他参数

        Returns:
            生成的视频路径，失败返回 None

        Raises:
            RuntimeError: 引擎未加载时抛出异常
        """
        # 生成输出路径
        output_path = os.path.join(output_dir, f"{task_id}.mp4")

        success, result = self.generate_video(
            audio_path=audio_path,
            video_path=video_path,
            output_path=output_path,
            face_id=face_id,
            **kwargs
        )

        if success:
            return result
        else:
            logger.error(f"视频生成失败: {result}")
            return None

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


def create_heygem_engine(
    heygem_root: str = "engines/heygem",
    batch_size: int = 4,
    managed: bool = True,
    preload_model: bool = True
) -> HeyGemEngine:
    """
    创建 HeyGemEngine 的便捷函数

    Args:
        heygem_root: HeyGem 根目录
        batch_size: 批处理大小
        managed: 是否由 GPUResourceManager 管理
        preload_model: 是否在初始化时预加载模型

    Returns:
        HeyGemEngine 实例
    """
    return HeyGemEngine(
        heygem_root=heygem_root,
        batch_size=batch_size,
        managed=managed,
        preload_model=preload_model
    )