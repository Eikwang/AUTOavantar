"""
音频提取工具 - 从视频中提取音频用于精准字幕对齐

使用 ffmpeg 从视频中提取音频轨道为 WAV 格式（16kHz 采样率，16bit 深度，单声道）
"""

import os
from pathlib import Path

from api.utils.async_subprocess import async_run_subprocess, async_run_ffmpeg, async_run_ffprobe


class AudioExtractionError(Exception):
    """音频提取失败异常"""
    pass


async def extract_audio_from_video(video_path: str, output_path: str = None, sample_rate: int = 16000) -> str:
    """
    从视频中提取音频

    Args:
        video_path: 视频文件路径
        output_path: 输出音频文件路径，默认为 None（自动生成）
        sample_rate: 采样率，默认 16000Hz

    Returns:
        str: 输出的音频文件路径

    Raises:
        AudioExtractionError: 视频文件不存在或 ffmpeg 提取失败时抛出
    """
    # 验证视频文件存在
    video_file = Path(video_path)
    if not video_file.exists():
        raise AudioExtractionError(f"视频文件不存在：{video_path}")

    # 自动生成输出路径
    if output_path is None:
        output_path = str(video_file.with_suffix('.wav').with_name(f"{video_file.stem}_audio.wav"))

    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # 构建 ffmpeg 命令
    # -i: 输入文件
    # -vn: 不处理视频
    # -acodec pcm_s16le: 16bit PCM 编码
    # -ar: 采样率
    # -ac: 声道数（1=单声道）
    cmd = [
        'ffmpeg',
        '-i', str(video_path),
        '-vn',
        '-acodec', 'pcm_s16le',
        '-ar', str(sample_rate),
        '-ac', '1',
        output_path
    ]

    try:
        # 执行 ffmpeg 命令
        returncode, stdout, stderr = await async_run_ffmpeg(cmd, check=True)
        return output_path
    except Exception as e:
        _err_msg = str(e)
        raise AudioExtractionError(f"音频提取失败：{_err_msg}")