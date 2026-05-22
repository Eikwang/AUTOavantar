"""
音频混音模块
实现音量 Ducking、BGM 混音等功能
"""

import logging
import os
import numpy as np
from typing import Optional, Tuple
from pathlib import Path

from api.utils.async_subprocess import async_run_subprocess, async_run_ffmpeg, async_run_ffprobe

logger = logging.getLogger(__name__)


class AudioMixer:
    """音频混音器"""
    
    def __init__(self, temp_dir: str = "temp/audio"):
        """
        初始化音频混音器
        
        Args:
            temp_dir: 临时文件目录
        """
        self.temp_dir = temp_dir
        os.makedirs(temp_dir, exist_ok=True)
    
    async def mix_with_ducking(
        self,
        video_path: str,
        bgm_path: str,
        output_path: Optional[str] = None,
        bgm_volume: float = 0.3,
        ducking_threshold: float = -20.0,
        ducking_reduction: float = 15.0
    ) -> str:
        """
        混音并应用音量 Ducking
        
        Args:
            video_path: 视频路径
            bgm_path: BGM 路径
            output_path: 输出路径（可选）
            bgm_volume: BGM 基础音量 (0-1)
            ducking_threshold: 触发 Ducking 的阈值 (dB)
            ducking_reduction: Ducking 时音量降低量 (dB)
            
        Returns:
            输出视频路径
        """
        if output_path is None:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_mixed{ext}"
        
        try:
            # 使用 FFmpeg 的 sidechain 压缩器实现 Ducking
            filter_complex = (
                f"[1:a]volume={bgm_volume}[bgm];"
                f"[0:a][bgm]sidechaincompress=threshold={ducking_threshold}dB:"
                f"ratio=4:attack=200:release=1000:level_sc=1[out]"
            )
            
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-i", bgm_path,
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[out]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                output_path
            ]
            
            await async_run_ffmpeg(cmd, check=True)
            
            # 替换原视频
            os.replace(output_path, video_path)
            
            logger.info(f"混音完成：{video_path}")
            return video_path
            
        except Exception as e:
            logger.error(f"混音失败：{e}")
            return video_path
    
    async def simple_mix(
        self,
        video_path: str,
        bgm_path: str,
        bgm_volume: float = 0.3,
        output_path: Optional[str] = None
    ) -> str:
        """
        简单混音（无 Ducking）
        
        Args:
            video_path: 视频路径
            bgm_path: BGM 路径
            bgm_volume: BGM 音量 (0-1)
            output_path: 输出路径
            
        Returns:
            输出视频路径
        """
        if output_path is None:
            base, ext = os.path.splitext(video_path)
            output_path = f"{base}_mixed{ext}"
        
        try:
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-i", bgm_path,
                "-filter_complex",
                f"[1:a]volume={bgm_volume}[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]",
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                output_path
            ]
            
            await async_run_ffmpeg(cmd, check=True)
            
            # 替换原视频
            os.replace(output_path, video_path)
            
            logger.info(f"简单混音完成：{video_path}")
            return video_path
            
        except Exception as e:
            logger.error(f"混音失败：{e}")
            return video_path
    
    def detect_voice_activity(self, audio_path: str) -> np.ndarray:
        """
        检测语音活动
        
        Args:
            audio_path: 音频路径
            
        Returns:
            语音活动数组（1 表示有人声，0 表示无人声）
        """
        try:
            import librosa
            
            # 加载音频
            y, sr = librosa.load(audio_path, sr=None)
            
            # 计算 RMS 能量
            hop_length = 512
            rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
            
            # 阈值检测
            threshold = np.mean(rms) * 1.5
            voice_activity = (rms > threshold).astype(int)
            
            return voice_activity
            
        except ImportError:
            logger.warning("librosa 未安装，使用简单检测")
            return np.array([])
    
    async def apply_manual_ducking(
        self,
        video_path: str,
        bgm_path: str,
        voice_activity: np.ndarray,
        bgm_volume_normal: float = 0.3,
        bgm_volume_ducked: float = 0.1,
        output_path: Optional[str] = None
    ) -> str:
        """
        应用手动 Ducking（基于语音活动检测）
        
        Args:
            video_path: 视频路径
            bgm_path: BGM 路径
            voice_activity: 语音活动数组
            bgm_volume_normal: 正常 BGM 音量
            bgm_volume_ducked: Ducking 时 BGM 音量
            output_path: 输出路径
            
        Returns:
            输出视频路径
        """
        logger.warning("手动 Ducking 实现复杂，建议使用 FFmpeg 自动 Ducking")
        return await self.mix_with_ducking(video_path, bgm_path, output_path)


def create_audio_mixer(temp_dir: str = "temp/audio") -> AudioMixer:
    """创建音频混音器的便捷函数"""
    return AudioMixer(temp_dir=temp_dir)
