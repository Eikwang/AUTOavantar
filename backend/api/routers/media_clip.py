"""
音视频剪辑路由
提供视频/音频的精确剪辑功能
"""

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.schemas import ApiResponse
from api.services.media_clip_service import get_media_clip_service

logger = logging.getLogger("autoavantar-api.media_clip")

router = APIRouter()


# ==================== 数据模型 ====================

class MediaClipRequest(BaseModel):
    """剪辑请求"""
    file_path: str = Field(..., description="文件路径")
    start_time: float = Field(..., description="开始时间（秒）")
    end_time: float = Field(..., description="结束时间（秒）")
    replace_original: bool = Field(default=True, description="是否替换原文件")


class MediaClipFrameRequest(BaseModel):
    """按帧剪辑请求（视频专用）"""
    file_path: str = Field(..., description="文件路径")
    start_frame: int = Field(..., description="开始帧号")
    end_frame: int = Field(..., description="结束帧号")
    replace_original: bool = Field(default=True, description="是否替换原文件")


class MediaInfoResponse(BaseModel):
    """媒体信息响应"""
    duration: float
    fps: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    total_frames: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


class MediaCropRequest(BaseModel):
    """画面裁剪请求"""
    file_path: str = Field(..., description="视频文件路径")
    x: float = Field(..., ge=0, le=1, description="裁剪区域左上角 X（百分比 0-1）")
    y: float = Field(..., ge=0, le=1, description="裁剪区域左上角 Y（百分比 0-1）")
    width: float = Field(..., gt=0, le=1, description="裁剪区域宽度（百分比 0-1）")
    height: float = Field(..., gt=0, le=1, description="裁剪区域高度（百分比 0-1）")
    replace_original: bool = Field(default=True, description="是否替换原文件")

    def is_valid(self) -> bool:
        return (self.x + self.width <= 1.0 + 1e-6 and
                self.y + self.height <= 1.0 + 1e-6)


class WaveformResponse(BaseModel):
    """波形数据响应"""
    peaks: list
    duration: float
    samples: int


# ==================== API 路由 ====================

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "media_clip"}


@router.post("/info", response_model=ApiResponse)
async def get_media_info(request: dict):
    """
    获取媒体文件信息

    Args:
        file_path: 文件路径

    Returns:
        媒体信息：duration, fps, width, height, total_frames 等
    """
    file_path = request.get("file_path")
    file_type = request.get("file_type", "auto")  # "video", "audio", "auto"

    if not file_path:
        return ApiResponse(code=400, message="缺少 file_path 参数")

    service = get_media_clip_service()

    try:
        if file_type == "audio" or (file_type == "auto" and file_path.endswith(('.mp3', '.wav', '.m4a', '.flac'))):
            info = service.get_audio_info(file_path)
            return ApiResponse(
                code=200,
                message="获取成功",
                data={
                    "duration": info["duration"],
                    "sample_rate": info["sample_rate"],
                    "channels": info["channels"]
                }
            )
        else:
            info = service.get_video_info(file_path)
            return ApiResponse(
                code=200,
                message="获取成功",
                data={
                    "duration": info["duration"],
                    "fps": info["fps"],
                    "width": info["width"],
                    "height": info["height"],
                    "total_frames": info["total_frames"]
                }
            )
    except ValueError as e:
        logger.warning(f"获取媒体信息失败：{e}")
        return ApiResponse(code=400, message=str(e))
    except Exception as e:
        logger.error(f"获取媒体信息异常：{e}")
        return ApiResponse(code=500, message=f"获取失败：{str(e)}")


@router.post("/clip", response_model=ApiResponse)
async def clip_media(request: MediaClipRequest):
    """
    剪辑媒体文件

    Args:
        file_path: 文件路径
        start_time: 开始时间（秒）
        end_time: 结束时间（秒）
        replace_original: 是否替换原文件

    Returns:
        剪辑结果
    """
    service = get_media_clip_service()

    try:
        # 检测文件类型
        file_path = request.file_path
        is_audio = file_path.endswith(('.mp3', '.wav', '.m4a', '.flac', '.ogg'))

        if is_audio:
            result = service.clip_audio(
                audio_path=file_path,
                start_time=request.start_time,
                end_time=request.end_time,
                replace_original=request.replace_original
            )
        else:
            result = service.clip_video(
                video_path=file_path,
                start_time=request.start_time,
                end_time=request.end_time,
                replace_original=request.replace_original
            )

        logger.info(f"剪辑完成：{result}")

        return ApiResponse(
            code=200,
            message="剪辑成功",
            data=result
        )

    except ValueError as e:
        logger.warning(f"剪辑失败：{e}")
        return ApiResponse(code=400, message=str(e))
    except Exception as e:
        logger.error(f"剪辑异常：{e}")
        return ApiResponse(code=500, message=f"剪辑失败：{str(e)}")


@router.post("/crop", response_model=ApiResponse)
async def crop_video(request: MediaCropRequest):
    """
    画面裁剪视频

    Args:
        file_path: 视频文件路径
        x: 裁剪区域左上角 X（百分比 0-1）
        y: 裁剪区域左上角 Y（百分比 0-1）
        width: 裁剪区域宽度（百分比 0-1）
        height: 裁剪区域高度（百分比 0-1）
        replace_original: 是否替换原文件

    Returns:
        裁剪结果
    """
    if not request.is_valid():
        return ApiResponse(code=400, message="裁剪区域无效：超出视频边界")

    service = get_media_clip_service()

    try:
        result = service.crop_video(
            video_path=request.file_path,
            x=request.x,
            y=request.y,
            width=request.width,
            height=request.height,
            replace_original=request.replace_original
        )

        logger.info(f"画面裁剪完成：{result}")

        return ApiResponse(
            code=200,
            message="裁剪成功",
            data=result
        )

    except ValueError as e:
        logger.warning(f"画面裁剪失败：{e}")
        return ApiResponse(code=400, message=str(e))
    except Exception as e:
        logger.error(f"画面裁剪异常：{e}")
        return ApiResponse(code=500, message=f"裁剪失败：{str(e)}")


@router.post("/clip-by-frame", response_model=ApiResponse)
async def clip_by_frame(request: MediaClipFrameRequest):
    """
    按帧剪辑视频（精确到帧）

    Args:
        file_path: 文件路径
        start_frame: 开始帧号
        end_frame: 结束帧号
        replace_original: 是否替换原文件

    Returns:
        剪辑结果
    """
    service = get_media_clip_service()

    try:
        # 获取视频信息
        video_info = service.get_video_info(request.file_path)
        fps = video_info["fps"]

        # 计算时间
        start_time = request.start_frame / fps
        end_time = request.end_frame / fps

        result = service.clip_video(
            video_path=request.file_path,
            start_time=start_time,
            end_time=end_time,
            replace_original=request.replace_original
        )

        logger.info(f"按帧剪辑完成：帧 {request.start_frame}-{request.end_frame} -> {start_time:.3f}s-{end_time:.3f}s")

        return ApiResponse(
            code=200,
            message="剪辑成功",
            data={
                **result,
                "start_frame": request.start_frame,
                "end_frame": request.end_frame,
                "fps": fps
            }
        )

    except ValueError as e:
        logger.warning(f"按帧剪辑失败：{e}")
        return ApiResponse(code=400, message=str(e))
    except Exception as e:
        logger.error(f"按帧剪辑异常：{e}")
        return ApiResponse(code=500, message=f"剪辑失败：{str(e)}")


@router.post("/waveform", response_model=ApiResponse)
async def get_waveform(request: dict):
    """
    获取音频波形数据

    Args:
        file_path: 音频文件路径
        samples: 采样点数（可选，默认 500）

    Returns:
        波形数据
    """
    file_path = request.get("file_path")
    samples = request.get("samples", 500)

    if not file_path:
        return ApiResponse(code=400, message="缺少 file_path 参数")

    service = get_media_clip_service()

    try:
        waveform = service.get_audio_waveform(
            audio_path=file_path,
            samples=samples
        )

        return ApiResponse(
            code=200,
            message="获取成功",
            data=waveform
        )

    except ValueError as e:
        logger.warning(f"获取波形失败：{e}")
        return ApiResponse(code=400, message=str(e))
    except Exception as e:
        logger.error(f"获取波形异常：{e}")
        return ApiResponse(code=500, message=f"获取失败：{str(e)}")


@router.post("/video/waveform", response_model=ApiResponse)
async def get_video_audio_waveform(request: dict):
    """
    获取视频的音频波形数据

    Args:
        file_path: 视频文件路径
        samples: 采样点数（可选，默认 500）

    Returns:
        波形数据
    """
    file_path = request.get("file_path")
    samples = request.get("samples", 500)

    if not file_path:
        return ApiResponse(code=400, message="缺少 file_path 参数")

    service = get_media_clip_service()

    try:
        waveform = service.get_audio_waveform(
            audio_path=file_path,
            samples=samples
        )

        return ApiResponse(
            code=200,
            message="获取成功",
            data=waveform
        )

    except ValueError as e:
        logger.warning(f"获取波形失败：{e}")
        return ApiResponse(code=400, message=str(e))
    except Exception as e:
        logger.error(f"获取波形异常：{e}")
        return ApiResponse(code=500, message=f"获取失败：{str(e)}")
