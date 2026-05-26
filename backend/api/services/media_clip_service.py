"""
音视频剪辑服务
提供视频/音频的精确剪辑功能
"""

import os
import logging
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger("autoavantar-api.media_clip")


class MediaClipService:
    """音视频剪辑服务类"""

    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent.parent.parent.parent

    def get_video_info(self, video_path: str) -> Dict[str, Any]:
        """
        获取视频信息（使用 ffprobe）

        Args:
            video_path: 视频文件路径（相对路径或绝对路径）

        Returns:
            包含视频信息的字典：duration, fps, width, height, total_frames
        """
        # 解析路径
        if video_path.startswith("backend/"):
            full_path = self.base_dir / video_path
        elif video_path.startswith("uploads/") or video_path.startswith("data/"):
            full_path = self.base_dir / video_path
        else:
            full_path = Path(video_path)

        if not full_path.exists():
            raise ValueError(f"视频文件不存在：{video_path}")

        # 使用 ffprobe 获取视频信息
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(full_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe 执行失败：{result.stderr}")

        info = json.loads(result.stdout)

        video_stream = None
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break

        if not video_stream:
            raise RuntimeError("未找到视频流")

        duration = float(info.get("format", {}).get("duration", 0))
        fps = eval(video_stream.get("r_frame_rate", "30/1")) if video_stream.get("r_frame_rate") else 30
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        total_frames = int(video_stream.get("nb_frames", 0)) if video_stream.get("nb_frames") else int(duration * fps)

        return {
            "duration": duration,
            "fps": fps,
            "width": width,
            "height": height,
            "total_frames": total_frames,
            "path": str(full_path)
        }

    def get_audio_info(self, audio_path: str) -> Dict[str, Any]:
        """
        获取音频信息

        Args:
            audio_path: 音频文件路径

        Returns:
            包含音频信息的字典：duration, sample_rate, channels
        """
        # 解析路径
        if audio_path.startswith("backend/"):
            full_path = self.base_dir / audio_path
        elif audio_path.startswith("uploads/") or audio_path.startswith("data/"):
            full_path = self.base_dir / audio_path
        else:
            full_path = Path(audio_path)

        if not full_path.exists():
            raise ValueError(f"音频文件不存在：{audio_path}")

        # 使用 ffprobe 获取音频信息
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(full_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe 执行失败：{result.stderr}")

        info = json.loads(result.stdout)

        audio_stream = None
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "audio":
                audio_stream = stream
                break

        if not audio_stream:
            raise RuntimeError("未找到音频流")

        duration = float(info.get("format", {}).get("duration", 0))
        sample_rate = int(audio_stream.get("sample_rate", 44100))
        channels = int(audio_stream.get("channels", 2))

        return {
            "duration": duration,
            "sample_rate": sample_rate,
            "channels": channels,
            "path": str(full_path)
        }

    def clip_video(
        self,
        video_path: str,
        start_time: float,
        end_time: float,
        output_path: Optional[str] = None,
        replace_original: bool = False
    ) -> Dict[str, Any]:
        """
        剪辑视频

        Args:
            video_path: 原视频路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
            output_path: 输出路径（可选，默认在原路径添加_clip 后缀）
            replace_original: 是否替换原文件

        Returns:
            剪辑结果：{success: bool, output_path: str, duration: float}
        """
        # 解析路径
        if video_path.startswith("backend/"):
            full_path = self.base_dir / video_path
        elif video_path.startswith("uploads/") or video_path.startswith("data/"):
            full_path = self.base_dir / video_path
        else:
            full_path = Path(video_path)

        if not full_path.exists():
            raise ValueError(f"视频文件不存在：{video_path}")

        # 确定输出路径
        if replace_original:
            output_path = str(full_path)
            # 创建临时文件
            temp_path = full_path.with_suffix(".temp.mp4")
            output_for_ffmpeg = str(temp_path)
        elif output_path:
            if output_path.startswith("backend/"):
                output_for_ffmpeg = str(self.base_dir / output_path)
            else:
                output_for_ffmpeg = output_path
        else:
            # 默认在原路径添加_clip 后缀
            output_for_ffmpeg = str(full_path.with_name(f"{full_path.stem}_clip{full_path.suffix}"))

        # 构建 FFmpeg 命令 - 使用精确的帧级剪辑
        # -ss 放在 -i 之前用于快速定位，-to 用于精确结束
        cmd = [
            "ffmpeg",
            "-y",  # 覆盖输出文件
            "-ss", str(start_time),  # 开始时间
            "-i", str(full_path),
            "-to", str(end_time),  # 结束时间
            "-c:v", "copy",  # 视频流复制（不重新编码）
            "-c:a", "copy",  # 音频流复制
            "-avoid_negative_ts", "make_zero",
            output_for_ffmpeg
        ]

        logger.info(f"剪辑视频：{full_path} [{start_time:.2f}s - {end_time:.2f}s] -> {output_for_ffmpeg}")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 执行失败：{result.stderr}")

        # 如果替换原文件，移动临时文件
        if replace_original:
            temp_path.replace(full_path)
            output_for_ffmpeg = output_path

        # 获取剪辑后的时长
        clip_duration = end_time - start_time

        return {
            "success": True,
            "output_path": output_for_ffmpeg,
            "duration": clip_duration,
            "start_time": start_time,
            "end_time": end_time
        }

    def clip_audio(
        self,
        audio_path: str,
        start_time: float,
        end_time: float,
        output_path: Optional[str] = None,
        replace_original: bool = False
    ) -> Dict[str, Any]:
        """
        剪辑音频

        Args:
            audio_path: 原音频路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
            output_path: 输出路径（可选）
            replace_original: 是否替换原文件

        Returns:
            剪辑结果
        """
        # 解析路径
        if audio_path.startswith("backend/"):
            full_path = self.base_dir / audio_path
        elif audio_path.startswith("uploads/") or audio_path.startswith("data/"):
            full_path = self.base_dir / audio_path
        else:
            full_path = Path(audio_path)

        if not full_path.exists():
            raise ValueError(f"音频文件不存在：{audio_path}")

        # 确定输出路径
        if replace_original:
            output_path = str(full_path)
            temp_path = full_path.with_suffix(".temp" + full_path.suffix)
            output_for_ffmpeg = str(temp_path)
        elif output_path:
            if output_path.startswith("backend/"):
                output_for_ffmpeg = str(self.base_dir / output_path)
            else:
                output_for_ffmpeg = output_path
        else:
            output_for_ffmpeg = str(full_path.with_name(f"{full_path.stem}_clip{full_path.suffix}"))

        # 构建 FFmpeg 命令
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
            "-i", str(full_path),
            "-to", str(end_time),
            "-c:a", "copy",
            "-avoid_negative_ts", "make_zero",
            output_for_ffmpeg
        ]

        logger.info(f"剪辑音频：{full_path} [{start_time:.2f}s - {end_time:.2f}s] -> {output_for_ffmpeg}")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 执行失败：{result.stderr}")

        # 如果替换原文件，移动临时文件
        if replace_original:
            temp_path.replace(full_path)
            output_for_ffmpeg = output_path

        return {
            "success": True,
            "output_path": output_for_ffmpeg,
            "duration": end_time - start_time,
            "start_time": start_time,
            "end_time": end_time
        }

    def get_audio_waveform(
        self,
        audio_path: str,
        width: int = 1000,
        height: int = 200,
        samples: int = 500
    ) -> Dict[str, Any]:
        """
        生成音频波形数据

        Args:
            audio_path: 音频文件路径
            width: 波形宽度（像素）
            height: 波形高度（像素）
            samples: 采样点数

        Returns:
            波形数据：{peaks: [float], duration: float}
        """
        # 解析路径
        if audio_path.startswith("backend/"):
            full_path = self.base_dir / audio_path
        elif audio_path.startswith("uploads/") or audio_path.startswith("data/"):
            full_path = self.base_dir / audio_path
        else:
            full_path = Path(audio_path)

        if not full_path.exists():
            raise ValueError(f"音频文件不存在：{audio_path}")

        # 使用 ffmpeg 获取音频数据并计算波形
        # 先获取音频的 PCM 数据
        cmd = [
            "ffmpeg",
            "-i", str(full_path),
            "-f", "f32le",
            "-acodec", "pcm_f32le",
            "-ar", "44100",  # 采样率
            "-ac", "1",  # 单声道
            "pipe:1"
        ]

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 执行失败")

        # 解析 PCM 数据
        import struct
        pcm_data = result.stdout
        num_samples = len(pcm_data) // 4  # 32-bit float

        # 降采样到指定的 samples 数量
        step = max(1, num_samples // samples)
        peaks = []

        for i in range(0, num_samples, step):
            if len(peaks) >= samples:
                break
            # 读取 4 字节 float
            sample = struct.unpack('f', pcm_data[i*4:(i+1)*4])[0]
            peaks.append(abs(sample))

        # 归一化到 0-1
        max_peak = max(peaks) if peaks else 1
        if max_peak > 0:
            peaks = [p / max_peak for p in peaks]

        # 获取音频时长
        info = self.get_audio_info(audio_path)

        return {
            "peaks": peaks,
            "duration": info["duration"],
            "samples": len(peaks)
        }


# 单例服务实例
_media_clip_service: Optional[MediaClipService] = None


def get_media_clip_service() -> MediaClipService:
    """获取媒体剪辑服务单例"""
    global _media_clip_service
    if _media_clip_service is None:
        _media_clip_service = MediaClipService()
    return _media_clip_service
