"""
音频语速调节模块
使用 FFmpeg + rubberband 滤镜实现高质量语速调节
"""

import logging
import os
from pathlib import Path
from typing import Optional

from api.utils.async_subprocess import async_run_subprocess, async_run_ffmpeg, async_run_ffprobe

logger = logging.getLogger(__name__)


class AudioSpeedProcessor:
    """
    音频语速调节器
    
    使用 FFmpeg 的 rubberband 滤镜实现高质量语速调节
    支持 0.8-1.2 倍语速范围
    """

    def __init__(self, output_dir: str = "temp/audio"):
        """
        初始化音频语速处理器

        Args:
            output_dir: 输出目录
        """
        # 如果是相对路径，转换为绝对路径
        if not os.path.isabs(output_dir):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            output_dir = os.path.join(project_root, output_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"音频语速处理器初始化: {self.output_dir}")

    async def adjust_speed(
        self,
        audio_path: str,
        speed: float,
        output_path: Optional[str] = None
    ) -> Optional[str]:
        """
        调节音频语速

        Args:
            audio_path: 输入音频路径
            speed: 语速倍率 (0.8-1.2)
            output_path: 输出音频路径（可选，默认自动生成）

        Returns:
            调节后的音频路径，失败返回 None
        """
        # 规范化路径：处理相对路径和正斜杠/反斜杠
        audio_path = os.path.normpath(audio_path.replace('\\', '/'))

        # 如果是相对路径，转换为绝对路径
        if not os.path.isabs(audio_path):
            # 获取项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            audio_path = os.path.join(project_root, audio_path)
            audio_path = os.path.normpath(audio_path)

        if not os.path.exists(audio_path):
            logger.error(f"音频文件不存在: {audio_path}")
            return None

        if speed == 1.0:
            logger.info(f"语速为 1.0，无需调节，直接返回原音频: {audio_path}")
            return audio_path

        if speed < 0.8 or speed > 1.2:
            logger.warning(f"语速 {speed} 超出支持范围 (0.8-1.2)，限制到范围内")
            speed = max(0.8, min(1.2, speed))

        if output_path is None:
            # 确保 output_dir 是绝对路径
            output_dir_abs = self.output_dir
            if not output_dir_abs.is_absolute():
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                output_dir_abs = Path(project_root) / self.output_dir
            output_path = str(
                output_dir_abs / f"speed_{Path(audio_path).stem}_{speed}x{Path(audio_path).suffix}"
            )
        else:
            # 如果提供了 output_path，确保是绝对路径
            output_path = os.path.abspath(output_path)

        # 确保输出目录存在
        output_dir_path = Path(output_path).parent
        output_dir_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"调节音频语速: {audio_path} -> {output_path}, 速度: {speed}x")

        try:
            # 使用 rubberband 滤镜进行语速调节
            # tempo 参数：>1 加快，<1 减慢
            cmd = [
                "ffmpeg",
                "-i", audio_path,
                "-af", f"rubberband=tempo={speed}",
                "-c:a", "libmp3lame",
                "-b:a", "320k",
                output_path
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if returncode == 0 and os.path.exists(output_path):
                logger.info(f"音频语速调节成功: {output_path}")
                return output_path
            else:
                _err = stderr.decode() if stderr else ""
                logger.error(f"音频语速调节失败: {_err}")
                return None

        except FileNotFoundError:
            logger.error("FFmpeg 未找到，请确保已安装并添加到 PATH")
            return None
        except Exception as e:
            logger.error(f"音频语速调节异常: {e}")
            return None

    async def adjust_speed_simple(
        self,
        audio_path: str,
        speed: float,
        output_path: Optional[str] = None
    ) -> Optional[str]:
        """
        简单语速调节（使用 atempo 滤镜）

        atempo 范围限制在 0.5-2.0，需要多次级联实现更广范围

        Args:
            audio_path: 输入音频路径
            speed: 语速倍率 (0.8-1.2)
            output_path: 输出音频路径（可选，默认自动生成）

        Returns:
            调节后的音频路径，失败返回 None
        """
        # 规范化路径：处理相对路径和正斜杠/反斜杠
        audio_path = os.path.normpath(audio_path.replace('\\', '/'))

        # 如果是相对路径，转换为绝对路径
        if not os.path.isabs(audio_path):
            # 获取项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            audio_path = os.path.join(project_root, audio_path)
            audio_path = os.path.normpath(audio_path)

        if not os.path.exists(audio_path):
            logger.error(f"音频文件不存在: {audio_path}")
            return None

        if speed == 1.0:
            logger.info(f"语速为 1.0，无需调节，直接返回原音频: {audio_path}")
            return audio_path

        if output_path is None:
            # 确保 output_dir 是绝对路径
            output_dir_abs = self.output_dir
            if not output_dir_abs.is_absolute():
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                output_dir_abs = Path(project_root) / self.output_dir
            output_path = str(
                output_dir_abs / f"speed_atempo_{Path(audio_path).stem}_{speed}x{Path(audio_path).suffix}"
            )
        else:
            # 如果提供了 output_path，确保是绝对路径
            output_path = os.path.abspath(output_path)

        # 确保输出目录存在
        output_dir_path = Path(output_path).parent
        output_dir_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"调节音频语速 (atempo): {audio_path} -> {output_path}, 速度: {speed}x")

        try:
            # atempo 滤镜范围是 0.5-2.0
            # 对于 0.8-1.2 的范围，可以直接使用
            cmd = [
                "ffmpeg",
                "-i", audio_path,
                "-af", f"atempo={speed}",
                "-c:a", "libmp3lame",
                "-b:a", "320k",
                output_path
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if returncode == 0 and os.path.exists(output_path):
                logger.info(f"音频语速调节成功 (atempo): {output_path}")
                return output_path
            else:
                _err = stderr.decode() if stderr else ""
                logger.error(f"音频语速调节失败 (atempo): {_err}")
                return None

        except FileNotFoundError:
            logger.error("FFmpeg 未找到，请确保已安装并添加到 PATH")
            return None
        except Exception as e:
            logger.error(f"音频语速调节异常 (atempo): {e}")
            return None


def create_audio_speed_processor(output_dir: str = "temp/audio") -> AudioSpeedProcessor:
    """
    创建音频语速处理器实例
    
    Args:
        output_dir: 输出目录
        
    Returns:
        AudioSpeedProcessor 实例
    """
    return AudioSpeedProcessor(output_dir)
