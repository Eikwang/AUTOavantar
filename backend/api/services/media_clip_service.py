"""
音视频剪辑服务
提供视频/音频的精确剪辑功能
"""

import os
import logging
import subprocess
import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger("autoavantar-api.media_clip")

# Windows下隐藏subprocess弹出的CMD窗口
SUBPROCESS_EXTRA = {}
if sys.platform == "win32":
    SUBPROCESS_EXTRA["creationflags"] = 0x08000000  # CREATE_NO_WINDOW


class MediaClipService:
    """音视频剪辑服务类"""

    def __init__(self):
        # base_dir = 项目根目录 (D:\AI\AUTOavantar)
        self.base_dir = Path(__file__).resolve().parent.parent.parent.parent
        # backend_dir = backend目录 (D:\AI\AUTOavantar\backend)
        self.backend_dir = Path(__file__).resolve().parent.parent.parent

    def _normalize_path(self, file_path: str) -> str:
        """将Windows反斜杠路径转换为正斜杠"""
        return file_path.replace("\\", "/")

    def get_video_info(self, video_path: str) -> Dict[str, Any]:
        """
        获取视频信息（使用 ffprobe）

        Args:
            video_path: 视频文件路径（相对路径或绝对路径）

        Returns:
            包含视频信息的字典：duration, fps, width, height, total_frames
        """
        # 解析路径（先标准化反斜杠）
        video_path = self._normalize_path(video_path)
        if video_path.startswith("backend/"):
            full_path = self.base_dir / video_path
        elif video_path.startswith("uploads/") or video_path.startswith("data/"):
            # uploads/ 和 data/ 路径相对于 backend 目录
            full_path = self.backend_dir / video_path
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

        result = subprocess.run(cmd, capture_output=True, text=True, **SUBPROCESS_EXTRA)
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
        fps_expr = video_stream.get("r_frame_rate", "30/1")
        if "/" in fps_expr:
            num, den = fps_expr.split("/")
            fps = int(num) / int(den)
        else:
            fps = float(fps_expr)
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
        # 解析路径（先标准化反斜杠）
        audio_path = self._normalize_path(audio_path)
        if audio_path.startswith("backend/"):
            full_path = self.base_dir / audio_path
        elif audio_path.startswith("uploads/") or audio_path.startswith("data/"):
            full_path = self.backend_dir / audio_path
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

        result = subprocess.run(cmd, capture_output=True, text=True, **SUBPROCESS_EXTRA)
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
        # 解析路径（先标准化反斜杠）
        video_path = self._normalize_path(video_path)
        if video_path.startswith("backend/"):
            full_path = self.base_dir / video_path
        elif video_path.startswith("uploads/") or video_path.startswith("data/"):
            # uploads/ 和 data/ 路径相对于 backend 目录
            full_path = self.backend_dir / video_path
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

        # 构建 FFmpeg 命令 - 使用重新编码保证精确裁剪
        # -ss 放在 -i 之前用于快速定位，-t 指定输出时长
        clip_duration = end_time - start_time
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
            "-i", str(full_path),
            "-t", str(clip_duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "128k",
            "-avoid_negative_ts", "make_zero",
            output_for_ffmpeg
        ]

        logger.info(f"剪辑视频：{full_path} [{start_time:.2f}s - {end_time:.2f}s] -> {output_for_ffmpeg}")

        result = subprocess.run(cmd, capture_output=True, text=True, **SUBPROCESS_EXTRA)
        if result.returncode != 0:
            if replace_original and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg 执行失败：{result.stderr}")

        # 如果替换原文件，验证临时文件后再替换
        if replace_original:
            if not temp_path.exists() or temp_path.stat().st_size == 0:
                temp_path.unlink(missing_ok=True)
                raise RuntimeError("FFmpeg 输出文件无效")
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
        # 解析路径（先标准化反斜杠）
        audio_path = self._normalize_path(audio_path)
        if audio_path.startswith("backend/"):
            full_path = self.base_dir / audio_path
        elif audio_path.startswith("uploads/") or audio_path.startswith("data/"):
            full_path = self.backend_dir / audio_path
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

        # 构建 FFmpeg 命令 - 音频剪辑：-ss在-i之前保证精确seek，重新编码保证质量
        clip_duration = end_time - start_time
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(start_time),
            "-i", str(full_path),
            "-t", str(clip_duration),
            "-c:a", "aac",
            "-b:a", "128k",
            "-avoid_negative_ts", "make_zero",
            output_for_ffmpeg
        ]

        logger.info(f"剪辑音频：{full_path} [{start_time:.2f}s - {end_time:.2f}s] -> {output_for_ffmpeg}")

        result = subprocess.run(cmd, capture_output=True, text=True, **SUBPROCESS_EXTRA)
        if result.returncode != 0:
            if replace_original and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg 执行失败：{result.stderr}")

        # 如果替换原文件，验证临时文件后再替换
        if replace_original:
            if not temp_path.exists() or temp_path.stat().st_size == 0:
                temp_path.unlink(missing_ok=True)
                raise RuntimeError("FFmpeg 输出文件无效")
            temp_path.replace(full_path)
            output_for_ffmpeg = output_path

        return {
            "success": True,
            "output_path": output_for_ffmpeg,
            "duration": end_time - start_time,
            "start_time": start_time,
            "end_time": end_time
        }

    def crop_video(
        self,
        video_path: str,
        x: float,
        y: float,
        width: float,
        height: float,
        replace_original: bool = False
    ) -> Dict[str, Any]:
        """
        画面裁剪视频

        Args:
            video_path: 视频文件路径
            x: 裁剪区域左上角 X（百分比 0-1）
            y: 裁剪区域左上角 Y（百分比 0-1）
            width: 裁剪区域宽度（百分比 0-1）
            height: 裁剪区域高度（百分比 0-1）
            replace_original: 是否替换原文件

        Returns:
            裁剪结果：{success, output_path, original_width, original_height, crop_x, crop_y, crop_width, crop_height}
        """
        # 解析路径（先标准化反斜杠）
        video_path = self._normalize_path(video_path)
        if video_path.startswith("backend/"):
            full_path = self.base_dir / video_path
        elif video_path.startswith("uploads/") or video_path.startswith("data/"):
            # uploads/ 和 data/ 路径相对于 backend 目录
            full_path = self.backend_dir / video_path
        else:
            full_path = Path(video_path)

        if not full_path.exists():
            raise ValueError(f"视频文件不存在：{video_path}")

        # 获取视频信息以计算像素坐标
        video_info = self.get_video_info(video_path)
        orig_w = video_info["width"]
        orig_h = video_info["height"]

        # 百分比转像素，宽高必须是偶数（FFmpeg crop 要求）
        crop_x = int(round(orig_w * x))
        crop_y = int(round(orig_h * y))
        crop_w = int(round(orig_w * width))
        crop_h = int(round(orig_h * height))

        # 确保宽高为偶数
        crop_w = crop_w if crop_w % 2 == 0 else crop_w - 1
        crop_h = crop_h if crop_h % 2 == 0 else crop_h - 1

        if crop_w <= 0 or crop_h <= 0:
            raise ValueError("裁剪区域无效：宽或高小于等于0")

        # 确保裁剪区域不超出视频边界
        if crop_x + crop_w > orig_w:
            crop_x = orig_w - crop_w
        if crop_y + crop_h > orig_h:
            crop_y = orig_h - crop_h
        crop_x = max(0, crop_x)
        crop_y = max(0, crop_y)

        # 确定输出路径
        if replace_original:
            output_for_ffmpeg = str(full_path)
            temp_path = full_path.with_suffix(".temp.mp4")
            ffmpeg_output = str(temp_path)
        else:
            ffmpeg_output = str(full_path.with_name(f"{full_path.stem}_crop{full_path.suffix}"))

        # 构建 FFmpeg 命令 — 画面裁剪需要重新编码视频流
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(full_path),
            "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "copy",
            ffmpeg_output
        ]

        logger.info(f"画面裁剪视频：{full_path} [{crop_w}x{crop_h}+{crop_x}+{crop_y}] -> {ffmpeg_output}")

        result = subprocess.run(cmd, capture_output=True, text=True, **SUBPROCESS_EXTRA)
        if result.returncode != 0:
            # 清理临时文件
            if replace_original and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg 执行失败：{result.stderr}")

        # 替换原文件（验证输出有效性）
        if replace_original:
            if not temp_path.exists() or temp_path.stat().st_size == 0:
                temp_path.unlink(missing_ok=True)
                raise RuntimeError("FFmpeg 输出文件无效")
            temp_path.replace(full_path)
            output_for_ffmpeg = str(full_path)

        return {
            "success": True,
            "output_path": output_for_ffmpeg,
            "original_width": orig_w,
            "original_height": orig_h,
            "crop_x": crop_x,
            "crop_y": crop_y,
            "crop_width": crop_w,
            "crop_height": crop_h
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
        # 解析路径（先标准化反斜杠）
        audio_path = self._normalize_path(audio_path)
        if audio_path.startswith("backend/"):
            full_path = self.base_dir / audio_path
        elif audio_path.startswith("uploads/") or audio_path.startswith("data/"):
            full_path = self.backend_dir / audio_path
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

        result = subprocess.run(cmd, capture_output=True, **SUBPROCESS_EXTRA)
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
