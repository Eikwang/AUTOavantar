"""
功能接口路由
处理面部分析、音频提取、降噪、文案处理等核心功能
"""

import os
import logging
import json
import platform
import uuid
import asyncio
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from api.utils.async_subprocess import async_run_subprocess, async_run_ffmpeg

from config.settings import settings
from business.preprocess.video_preprocessor import VideoPreprocessor
from business.audio.gtcrn_denoiser import GTCDenoiser
from api.services.llm_service import LLMScriptGenerator, create_script_generator

logger = logging.getLogger("autoavantar-api.functions")

router = APIRouter()


# ============================================================================
# 异步面部分析任务存储 → AC-227
# ============================================================================
face_analysis_tasks: Dict[str, Dict] = {}
# 视频路径级别的防护锁：记录正在分析中的视频路径，防止重复分析
face_analysis_video_locks: Dict[str, str] = {}  # {视频完整路径: task_id}
# 视频路径级别的已完成记录：记录最近完成分析的视频路径及完成时间，防止5分钟内重复分析
face_analysis_completed_cache: Dict[str, datetime] = {}  # {视频完整路径: 完成时间}


def cleanup_expired_face_analysis_tasks(max_age_hours: int = 2):
    """
    清理过期的面部分析任务 → AC-227

    Args:
        max_age_hours: 最大保留时间（小时）
    """
    now = datetime.now()
    expired_task_ids = []

    for task_id, task in face_analysis_tasks.items():
        created_at = task.get("created_at")
        if created_at:
            age = now - created_at
            if age.total_seconds() > max_age_hours * 3600:
                expired_task_ids.append(task_id)

    for task_id in expired_task_ids:
        task = face_analysis_tasks.get(task_id)
        if task:
            # 同时清理对应的视频锁
            video_path = task.get("video_path")
            if video_path and face_analysis_video_locks.get(video_path) == task_id:
                del face_analysis_video_locks[video_path]
        del face_analysis_tasks[task_id]
        logger.info(f"清理过期面部分析任务: {task_id}")

    if expired_task_ids:
        logger.info(f"已清理 {len(expired_task_ids)} 个过期任务")

    # 清理过期的已完成缓存（超过5分钟的条目）
    expired_cache_keys = [
        path for path, completed_at in face_analysis_completed_cache.items()
        if (now - completed_at).total_seconds() > 300
    ]
    for key in expired_cache_keys:
        del face_analysis_completed_cache[key]
    if expired_cache_keys:
        logger.info(f"已清理 {len(expired_cache_keys)} 个过期已完成缓存")


class FaceAnalysisRequest(BaseModel):
    """面部分析请求"""
    video_path: str
    video_type: str = "opening"


class FaceAnalysisResponse(BaseModel):
    """面部分析响应"""
    status: str
    invalid_frame_count: int
    output_video_path: Optional[str] = None
    message: str


class ExtractAudioRequest(BaseModel):
    """提取音频请求"""
    video_path: str


class ExtractAudioResponse(BaseModel):
    """提取音频响应"""
    status: str
    audio_path: str
    duration: float
    message: str


class DenoiseRequest(BaseModel):
    """降噪请求"""
    audio_path: str


class DenoiseResponse(BaseModel):
    """降噪响应"""
    status: str
    output_audio_path: str
    message: str


class TextProcessRequest(BaseModel):
    """文案处理请求"""
    text: str
    mode: str = "single"
    gen_type: str = "manual"


class TextProcessResponse(BaseModel):
    """文案处理响应"""
    status: str
    parsed_script: Optional[Dict[str, Any]] = None
    tags: List[str] = []
    message: str


class GenerateScriptRequest(BaseModel):
    """生成文案请求"""
    topic: str
    prompt: str = ""
    mode: str = "single"


class ExtractFrameRequest(BaseModel):
    """提取视频首帧请求"""
    video_path: str


class ExtractFrameResponse(BaseModel):
    """提取视频首帧响应"""
    code: int = 200
    message: str = "success"
    data: Optional[Dict[str, Any]] = None


# ============================================================================
# 异步面部分析请求/响应模型 → AC-227, AC-230
# ============================================================================
class FaceAnalysisAsyncRequest(BaseModel):
    """异步面部分析请求"""
    video_path: str
    video_type: str = "opening"


class FaceAnalysisAsyncResponse(BaseModel):
    """异步面部分析响应"""
    task_id: str
    status: str


class FaceAnalysisStatusResponse(BaseModel):
    """面部分析任务状态响应"""
    task_id: str
    status: str
    progress: float
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


_face_analyzer: Optional[VideoPreprocessor] = None
_denoiser: Optional[GTCDenoiser] = None


def get_face_analyzer() -> VideoPreprocessor:
    """获取面部分析器实例"""
    global _face_analyzer
    if _face_analyzer is None:
        _face_analyzer = VideoPreprocessor()
    return _face_analyzer


def get_denoiser() -> GTCDenoiser:
    """获取降噪器实例"""
    global _denoiser
    if _denoiser is None:
        _denoiser = GTCDenoiser()
    return _denoiser


def get_script_generator() -> LLMScriptGenerator:
    """获取文案生成器实例（每次调用都重新读取配置以确保使用最新值）"""
    from api.services.workflow_service import load_api_keys_config
    api_config = load_api_keys_config()
    deepseek_api_key = api_config.get('deepseek_api_key', '')
    return create_script_generator(
        provider="astron",
        api_key=deepseek_api_key,
        model="astron-code-latest"
    )


def get_similar_tags(tag: str) -> List[str]:
    """
    获取情绪标签的相似标签
    
    Args:
        tag: 情绪标签
    
    Returns:
        相似标签列表
    """
    emotion_params = {
        "开心": {"vec1": 0.2},
        "高兴": {"vec1": 0.2, "vec7": 0.1},
        "生气": {"vec2": 0.2},
        "愤怒": {"vec2": 0.2, "vec5": 0.1},
        "激动": {"vec1": 0.2, "vec2": 0.2},
        "难过": {"vec3": 0.2},
        "悲伤": {"vec3": 0.2, "vec6": 0.1},
        "伤心": {"vec3": 0.2, "vec4": 0.2},
        "害怕": {"vec4": 0.3},
        "恐惧": {"vec4": 0.3, "vec6": 0.3},
        "惊慌": {"vec4": 0.3, "vec7": 0.3},
        "厌恶": {"vec5": 0.3},
        "讨厌": {"vec5": 0.3, "vec6": 0.2},
        "憎恨": {"vec5": 0.3, "vec2": 0.2},
        "低落": {"vec6": 0.3},
        "忧伤": {"vec6": 0.3, "vec3": 0.2},
        "沮丧": {"vec6": 0.3, "vec8": 0.2},
        "惊喜": {"vec7": 0.3},
        "兴奋": {"vec7": 0.3, "vec2": 0.2},
        "平淡": {"vec8": 0.2, "vec5": 0.2},
        "冷静": {"vec8": 0.3}
    }
    
    similar_tags = {
        "开心": ["惊喜", "高兴"],
        "高兴": ["开心", "惊喜"],
        "生气": ["愤怒", "激动"],
        "愤怒": ["生气", "激动"],
        "激动": ["生气", "愤怒", "惊喜"],
        "难过": ["悲伤", "伤心"],
        "悲伤": ["难过", "伤心"],
        "伤心": ["悲伤", "难过"],
        "害怕": ["恐惧", "惊慌"],
        "恐惧": ["害怕", "惊慌"],
        "惊慌": ["害怕", "恐惧"],
        "厌恶": ["讨厌", "憎恨"],
        "讨厌": ["厌恶", "憎恨"],
        "憎恨": ["讨厌", "厌恶"],
        "低落": ["忧伤", "沮丧"],
        "忧伤": ["沮丧", "低落"],
        "沮丧": ["忧伤", "低落"],
        "惊喜": ["开心", "兴奋", "激动"],
        "兴奋": ["激动", "惊喜"],
        "平淡": ["冷静"],
        "冷静": ["平淡"]
    }
    
    return similar_tags.get(tag, [])


def process_emotion_tags(emotion_tags: List[str]) -> List[Dict[str, Any]]:
    """
    处理情绪标签，添加相似标签和参数
    
    Args:
        emotion_tags: 情绪标签列表
    
    Returns:
        处理后的情绪标签列表，包含标签、参数和相似标签
    """
    emotion_params = {
        "开心": {"vec1": 0.2},
        "高兴": {"vec1": 0.2, "vec7": 0.1},
        "生气": {"vec2": 0.2},
        "愤怒": {"vec2": 0.2, "vec5": 0.1},
        "激动": {"vec1": 0.2, "vec2": 0.2},
        "难过": {"vec3": 0.2},
        "悲伤": {"vec3": 0.2, "vec6": 0.1},
        "伤心": {"vec3": 0.2, "vec4": 0.2},
        "害怕": {"vec4": 0.3},
        "恐惧": {"vec4": 0.3, "vec6": 0.3},
        "惊慌": {"vec4": 0.3, "vec7": 0.3},
        "厌恶": {"vec5": 0.3},
        "讨厌": {"vec5": 0.3, "vec6": 0.2},
        "憎恨": {"vec5": 0.3, "vec2": 0.2},
        "低落": {"vec6": 0.3},
        "忧伤": {"vec6": 0.3, "vec3": 0.2},
        "沮丧": {"vec6": 0.3, "vec8": 0.2},
        "惊喜": {"vec7": 0.3},
        "兴奋": {"vec7": 0.3, "vec2": 0.2},
        "平淡": {"vec8": 0.2, "vec5": 0.2},
        "冷静": {"vec8": 0.3}
    }
    
    similar_tags = {
        "开心": ["惊喜", "高兴"],
        "高兴": ["开心", "惊喜"],
        "生气": ["愤怒", "激动"],
        "愤怒": ["生气", "激动"],
        "激动": ["生气", "愤怒", "惊喜"],
        "难过": ["悲伤", "伤心"],
        "悲伤": ["难过", "伤心"],
        "伤心": ["悲伤", "难过"],
        "害怕": ["恐惧", "惊慌"],
        "恐惧": ["害怕", "惊慌"],
        "惊慌": ["害怕", "恐惧"],
        "厌恶": ["讨厌", "憎恨"],
        "讨厌": ["厌恶", "憎恨"],
        "憎恨": ["讨厌", "厌恶"],
        "低落": ["忧伤", "沮丧"],
        "忧伤": ["沮丧", "低落"],
        "沮丧": ["忧伤", "低落"],
        "惊喜": ["开心", "兴奋", "激动"],
        "兴奋": ["激动", "惊喜"],
        "平淡": ["冷静"],
        "冷静": ["平淡"]
    }
    
    processed_tags = []
    for tag in emotion_tags:
        if tag in emotion_params:
            processed_tags.append({
                "tag": tag,
                "params": emotion_params[tag],
                "similar_tags": similar_tags.get(tag, [])
            })
    
    return processed_tags


@router.post("/face-analysis", response_model=FaceAnalysisResponse)
async def analyze_face(request: FaceAnalysisRequest):
    """
    面部分析接口

    处理逻辑：
    1. 使用 SCRFD/MediaPipe 检测视频每一帧的面部关键点
    2. 判定规则：
       - 合格：检测到人脸 + 头部姿态角度在范围内（yaw <= 45°, pitch <= 30°）
       - 不合格：未检测到人脸或头部姿态角度超限
    3. 删除不合格帧，直接替换原视频
    4. 返回结果：分析状态、不合格帧数、视频路径
    """
    video_path = request.video_path

    if not os.path.exists(video_path):
        raise HTTPException(status_code=400, detail=f"视频文件不存在: {video_path}")

    try:
        analyzer = get_face_analyzer()

        # 检测面部
        result = analyzer.detect_faces(video_path)

        invalid_count = result.invalid_frames

        if invalid_count > 0:
            # 生成临时输出文件
            temp_output_path = video_path.replace(".mp4", "_temp_processed.mp4")
            # 处理视频，删除不合格帧
            process_result = analyzer.process_video(video_path, temp_output_path)

            # 处理成功后，替换原视频
            if process_result and os.path.exists(temp_output_path):
                # 删除原视频
                os.remove(video_path)
                # 重命名临时文件为原视频路径
                os.rename(temp_output_path, video_path)
                logger.info(f"面部分析完成，已移除 {invalid_count} 帧不合格画面，已替换原视频: {video_path}")
            elif os.path.exists(temp_output_path):
                # 处理失败但临时文件存在，清理临时文件
                os.remove(temp_output_path)

        return FaceAnalysisResponse(
            status="success",
            invalid_frame_count=invalid_count,
            output_video_path=video_path,  # 返回原路径（已替换）
            message=f"分析完成，已移除 {invalid_count} 段不合格画面"
        )

    except Exception as e:
        logger.error(f"面部分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"面部分析失败: {str(e)}")


# ============================================================================
# 异步面部分析接口 → AC-227, AC-230
# ============================================================================

def run_face_analysis_task(task_id: str, video_path: str):
    """
    后台执行面部分析任务 → AC-227

    Args:
        task_id: 任务 ID
        video_path: 视频路径
    """
    task = face_analysis_tasks.get(task_id)
    if not task:
        return

    # 检查是否已被取消
    if task["status"] == "cancelled":
        logger.info(f"任务 {task_id} 已取消，停止执行")
        return

    try:
        task["status"] = "running"
        task["progress"] = 0.1

        # 检查取消状态
        if task["status"] == "cancelled":
            logger.info(f"任务 {task_id} 在初始化阶段被取消")
            return

        # 获取面部分析器
        analyzer = get_face_analyzer()

        task["progress"] = 0.2

        # 检查取消状态
        if task["status"] == "cancelled":
            logger.info(f"任务 {task_id} 在获取分析器后被取消")
            return

        # 检测面部
        result = analyzer.detect_faces(video_path)

        task["progress"] = 0.6

        # 检查取消状态
        if task["status"] == "cancelled":
            logger.info(f"任务 {task_id} 在面部检测后被取消")
            return

        invalid_count = result.invalid_frames

        output_path = video_path
        if invalid_count > 0:
            # 生成临时输出文件
            temp_output_path = video_path.replace(".mp4", "_temp_processed.mp4")
            # 传递已有的检测结果，避免重复检测
            process_result = analyzer.process_video(video_path, temp_output_path, detect_result=result)

            # 处理成功后，替换原视频
            if process_result and os.path.exists(temp_output_path):
                # 删除原视频
                os.remove(video_path)
                # 重命名临时文件为原视频路径
                os.rename(temp_output_path, video_path)
                logger.info(f"已替换原视频: {video_path}")
            elif os.path.exists(temp_output_path):
                # 处理失败但临时文件存在，清理临时文件
                os.remove(temp_output_path)

        # 检查取消状态（处理视频后）
        if task["status"] == "cancelled":
            logger.info(f"任务 {task_id} 在视频处理后被取消")
            return

        task["progress"] = 0.9

        # 更新任务状态
        task["status"] = "completed"
        task["progress"] = 1.0
        task["result"] = {
            "invalid_frame_count": invalid_count,
            "output_video_path": output_path,
            "message": f"分析完成，已移除 {invalid_count} 段不合格画面"
        }

        # 记录到已完成缓存，防止5分钟内重复分析
        face_analysis_completed_cache[video_path] = datetime.now()

        logger.info(f"面部分析任务 {task_id} 完成")

    except Exception as e:
        # 如果是取消状态，不记录为失败
        if task["status"] == "cancelled":
            logger.info(f"任务 {task_id} 已取消，不记录错误")
            return
        logger.error(f"面部分析任务 {task_id} 失败: {e}")
        task["status"] = "failed"
        task["error"] = str(e)
        # 失败也记录到缓存，防止短时间内反复重试同一失败视频
        face_analysis_completed_cache[video_path] = datetime.now()
    finally:
        # 释放视频锁（无论成功、失败还是取消）
        face_analysis_video_locks.pop(video_path, None)


@router.post("/face-analysis-async", response_model=FaceAnalysisAsyncResponse)
async def analyze_face_async(
    body: FaceAnalysisAsyncRequest,
    background_tasks: BackgroundTasks,
    request: Request = None
):
    """
    异步面部分析接口 → AC-227

    立即返回 task_id，分析在后台执行
    """
    video_path = body.video_path

    # 记录请求来源
    client_info = f"{request.client.host}:{request.client.port}" if request and request.client else "unknown"
    logger.info(f"收到面部分析请求: video_path={video_path}, client={client_info}")

    # 构建完整的视频路径（处理相对路径），并规范化确保同一文件映射到同一 key
    backend_root = Path(__file__).resolve().parent.parent.parent
    full_video_path = video_path
    if not os.path.isabs(video_path):
        full_video_path = str(backend_root / video_path.replace("\\", "/"))
    full_video_path = os.path.normpath(os.path.abspath(full_video_path))

    if not os.path.exists(full_video_path):
        raise HTTPException(status_code=400, detail=f"视频文件不存在: {video_path}")

    # 防护检查：同一视频不允许重复分析
    # 1. 检查是否有正在分析中的任务
    existing_task_id = face_analysis_video_locks.get(full_video_path)
    if existing_task_id:
        existing_task = face_analysis_tasks.get(existing_task_id)
        if existing_task and existing_task["status"] in ("pending", "running"):
            logger.warning(f"拒绝重复面部分析请求: 视频 {full_video_path} 已有进行中的任务 {existing_task_id}")
            raise HTTPException(
                status_code=409,
                detail=f"该视频正在分析中（任务 {existing_task_id[:8]}...），请等待完成"
            )
        # 任务已完成/失败/取消，清理旧锁
        del face_analysis_video_locks[full_video_path]

    # 2. 检查是否有最近完成的任务（5分钟内）— O(1) 缓存查找
    completed_at = face_analysis_completed_cache.get(full_video_path)
    if completed_at:
        if (datetime.now() - completed_at).total_seconds() < 300:
            logger.warning(f"拒绝重复面部分析请求: 视频 {full_video_path} 已在 {completed_at} 完成分析")
            raise HTTPException(
                status_code=409,
                detail="该视频已完成面部分析，无需重复分析"
            )
        # 过期条目，惰性清理
        del face_analysis_completed_cache[full_video_path]

    # 生成任务 ID
    task_id = str(uuid.uuid4())

    # 加锁：标记该视频正在分析
    face_analysis_video_locks[full_video_path] = task_id

    try:
        # 初始化任务状态
        face_analysis_tasks[task_id] = {
            "task_id": task_id,
            "video_path": full_video_path,  # 使用完整路径
            "original_path": video_path,    # 保存原始路径用于返回
            "status": "pending",
            "progress": 0.0,
            "result": None,
            "error": None,
            "created_at": datetime.now()
        }

        # 添加后台任务
        background_tasks.add_task(
            run_face_analysis_task,
            task_id=task_id,
            video_path=full_video_path  # 使用完整路径
        )
    except Exception:
        # 任务初始化或后台任务添加失败时，释放锁避免永久阻塞
        face_analysis_video_locks.pop(full_video_path, None)
        raise

    logger.info(f"创建异步面部分析任务: {task_id}, 视频: {full_video_path}")

    return FaceAnalysisAsyncResponse(task_id=task_id, status="pending")


@router.get("/face-analysis-status/{task_id}", response_model=FaceAnalysisStatusResponse)
async def get_face_analysis_status(task_id: str):
    """
    查询面部分析任务状态 → AC-227
    """
    task = face_analysis_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return FaceAnalysisStatusResponse(
        task_id=task_id,
        status=task["status"],
        progress=task["progress"],
        result=task["result"],
        error=task["error"]
    )


@router.post("/face-analysis-cancel/{task_id}")
async def cancel_face_analysis(task_id: str):
    """
    取消面部分析任务 → AC-230
    """
    task = face_analysis_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task["status"] in ["completed", "failed", "cancelled"]:
        raise HTTPException(status_code=400, detail="任务已结束，无法取消")

    # 标记为已取消
    task["status"] = "cancelled"

    logger.info(f"取消面部分析任务: {task_id}")

    return {"task_id": task_id, "status": "cancelled"}


@router.post("/extract-audio", response_model=ExtractAudioResponse)
async def extract_audio(request: ExtractAudioRequest):
    """
    提取音频接口

    处理逻辑：
    1. 使用 FFmpeg 从视频中提取音频（格式：mp3）
    2. 返回结果：音频路径、音频时长
    """
    from pathlib import Path
    from config.settings import settings
    
    full_video_path = request.video_path

    if not os.path.exists(full_video_path):
        raise HTTPException(status_code=400, detail=f"视频文件不存在: {full_video_path}")

    try:
        base_name = os.path.splitext(os.path.basename(full_video_path))[0]
        
        # 构建音频保存路径
        backend_root = Path(__file__).resolve().parent.parent.parent
        audio_dir = backend_root / settings.UPLOAD_DIR / "audios" / "reference"
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        audio_path = str(audio_dir / f"{base_name}_extracted.wav")
        
        # 计算相对于 UPLOAD_DIR 的路径
        relative_audio_path = os.path.relpath(audio_path, str(backend_root / settings.UPLOAD_DIR))

        cmd = [
            "ffmpeg", "-i", full_video_path,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            "-y", audio_path
        ]
        await async_run_ffmpeg(cmd, timeout=120, check=True)

        duration = 0.0
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        try:
            returncode, stdout, stderr = await async_run_subprocess(probe_cmd)
            if returncode == 0 and stdout:
                duration = float(stdout.decode().strip())
        except:
            pass

        return ExtractAudioResponse(
            status="success",
            audio_path=relative_audio_path,
            duration=duration,
            message="音频提取成功"
        )

    except Exception as e:
        logger.error(f"音频提取失败: {e}")
        raise HTTPException(status_code=500, detail=f"音频提取失败: {str(e)}")


@router.post("/audio-denoise", response_model=DenoiseResponse)
async def denoise_audio(request: DenoiseRequest):
    """
    降噪增强接口

    处理逻辑：
    1. 调用 GTCRN 音频降噪模块处理音频
    2. 替换原音频文件，返回处理后音频路径
    """
    audio_path = request.audio_path

    # 使用路径管理器查找音频文件
    from core.paths import get_path_manager
    path_manager = get_path_manager()

    # 尝试多种路径查找音频文件
    backend_root = Path(__file__).resolve().parent.parent.parent
    project_root = path_manager.project_root

    # 标准化路径：替换反斜杠为正斜杠
    audio_path_normalized = audio_path.replace('\\', '/')

    possible_paths = [
        # 绝对路径
        Path(audio_path) if os.path.isabs(audio_path) else None,
        # 相对于项目根目录（audio_merger 返回的格式）
        Path(project_root) / audio_path_normalized,
        # 相对于后端目录
        backend_root / audio_path_normalized,
        # uploads 目录下的路径
        backend_root / settings.UPLOAD_DIR / audio_path_normalized,
        backend_root / "uploads" / audio_path_normalized,
        # 直接路径
        Path(audio_path_normalized),
        # 去掉 backend/ 前缀的路径
        backend_root / audio_path_normalized.replace('backend/', ''),
    ]

    # 过滤掉 None 值
    possible_paths = [p for p in possible_paths if p is not None]

    full_audio_path = None
    for path in possible_paths:
        if path.exists():
            full_audio_path = str(path.resolve())
            logger.info(f"找到音频文件: {full_audio_path}")
            break

    if not full_audio_path:
        # 使用路径管理器的查找功能作为后备
        found = path_manager.find_audio_file(audio_path)
        if found:
            full_audio_path = found
        else:
            raise HTTPException(
                status_code=400,
                detail=f"音频文件不存在: {audio_path}，已搜索路径: {[str(p) for p in possible_paths]}"
            )

    try:
        denoiser = get_denoiser()
        output_path = denoiser.denoise(full_audio_path)

        return DenoiseResponse(
            status="success",
            output_audio_path=output_path,
            message="降噪增强完成"
        )

    except Exception as e:
        logger.error(f"降噪处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"降噪处理失败: {str(e)}")


@router.post("/text-process", response_model=TextProcessResponse)
async def process_text(request: TextProcessRequest):
    """
    文案处理接口

    处理逻辑：
    - 智能生成模式：
      1. 解析 JSON 格式文案，提取字段（开场、情绪标签、场景标签、结束，双人模式额外提取左/右说话人）
      2. 按标签打组（开场、循环、结束），双人模式按说话人分组
    - 手动输入模式：直接返回原文本，不解析
    - 返回结果：解析后的文案结构、标签列表
    """
    try:
        text = request.text
        mode = request.mode
        gen_type = request.gen_type

        if gen_type == "llm" or gen_type == "smart":
            try:
                parsed = json.loads(text)

                tags = []
                emotions = []
                scenes = []

                # 情绪标签列表
                emotion_tags = ["开心", "高兴", "生气", "愤怒", "激动", "难过", "悲伤", "伤心", "害怕", "恐惧", "惊慌", "厌恶", "讨厌", "憎恨", "低落", "忧伤", "沮丧", "惊喜", "兴奋", "平淡", "冷静"]
                # 场景标签列表
                scene_tags = ["环境展示", "产品展示", "细节展示", "功能介绍", "使用效果"]
                # 场景标签相似标签映射
                scene_similar_tags = {
                    "环境展示": ["产品展示", "细节展示"],
                    "产品展示": ["功能介绍", "使用效果"],
                    "细节展示": ["产品展示", "功能介绍"],
                    "功能介绍": ["细节展示", "使用效果"],
                    "使用效果": ["产品展示", "功能介绍"]
                }
                
                # 情绪参数映射
                emotion_params = {
                    "开心": {"vec1": 0.2},
                    "高兴": {"vec1": 0.2, "vec7": 0.1},
                    "生气": {"vec2": 0.2},
                    "愤怒": {"vec2": 0.2, "vec5": 0.1},
                    "激动": {"vec1": 0.2, "vec2": 0.2},
                    "难过": {"vec3": 0.2},
                    "悲伤": {"vec3": 0.2, "vec6": 0.1},
                    "伤心": {"vec3": 0.2, "vec4": 0.2},
                    "害怕": {"vec4": 0.3},
                    "恐惧": {"vec4": 0.3, "vec6": 0.3},
                    "惊慌": {"vec4": 0.3, "vec7": 0.3},
                    "厌恶": {"vec5": 0.3},
                    "讨厌": {"vec5": 0.3, "vec6": 0.2},
                    "憎恨": {"vec5": 0.3, "vec2": 0.2},
                    "低落": {"vec6": 0.3},
                    "忧伤": {"vec6": 0.3, "vec3": 0.2},
                    "沮丧": {"vec6": 0.3, "vec8": 0.2},
                    "惊喜": {"vec7": 0.3},
                    "兴奋": {"vec7": 0.3, "vec2": 0.2},
                    "平淡": {"vec8": 0.2, "vec5": 0.2},
                    "冷静": {"vec8": 0.3}
                }
                
                # 相似标签映射
                similar_tags = {
                    "开心": ["惊喜", "高兴"],
                    "高兴": ["开心", "惊喜"],
                    "生气": ["愤怒", "激动"],
                    "愤怒": ["生气", "激动"],
                    "激动": ["生气", "愤怒", "惊喜"],
                    "难过": ["悲伤", "伤心"],
                    "悲伤": ["难过", "伤心"],
                    "伤心": ["悲伤", "难过"],
                    "害怕": ["恐惧", "惊慌"],
                    "恐惧": ["害怕", "惊慌"],
                    "惊慌": ["害怕", "恐惧"],
                    "厌恶": ["讨厌", "憎恨"],
                    "讨厌": ["厌恶", "憎恨"],
                    "憎恨": ["讨厌", "厌恶"],
                    "低落": ["忧伤", "沮丧"],
                    "忧伤": ["沮丧", "低落"],
                    "沮丧": ["忧伤", "低落"],
                    "惊喜": ["开心", "兴奋", "激动"],
                    "兴奋": ["激动", "惊喜"],
                    "平淡": ["冷静"],
                    "冷静": ["平淡"]
                }

                # 提取开场和结束
                opening = parsed.get("opening", parsed.get("开场", ""))
                ending = parsed.get("ending", parsed.get("结束", ""))

                # 提取情绪标签和场景标签
                emotion_details = []
                scene_details = []
                for key, value in parsed.items():
                    if key in emotion_tags:
                        emotions.append(key)
                        # 添加情绪详情，包括参数和相似标签
                        emotion_detail = {
                            "tag": key,
                            "content": value,
                            "params": emotion_params.get(key, {}),
                            "similar_tags": similar_tags.get(key, [])
                        }
                        emotion_details.append(emotion_detail)
                    elif key in scene_tags:
                        scenes.append(key)
                        # 添加场景详情，包括相似标签
                        scene_detail = {
                            "tag": key,
                            "content": value,
                            "similar_tags": scene_similar_tags.get(key, [])
                        }
                        scene_details.append(scene_detail)

                tags = emotions + scenes

                # 构建解析后的文案结构
                parsed_script = {
                    "opening": opening,
                    "ending": ending,
                    "segments": [],
                    "emotions": emotions,
                    "emotion_details": emotion_details,
                    "scenes": scenes,
                    "scene_details": scene_details,
                    "similar_tags_mapping": {
                        "emotion": similar_tags,
                        "scene": scene_similar_tags
                    }
                }

                # 处理双人模式
                if mode == "dual":
                    left_speaker = []
                    right_speaker = []
                    segments = []
                    
                    # 提取左边说话人和右边说话人内容
                    for key, value in parsed.items():
                        if isinstance(value, list):
                            for i, item in enumerate(value):
                                if isinstance(item, dict):
                                    if "左边说话人" in item:
                                        left_text = item["左边说话人"]
                                        left_speaker.append(left_text)
                                        segments.append({
                                            "text": left_text,
                                            "speaker": "left",
                                            "index": i
                                        })
                                    if "右边说话人" in item:
                                        right_text = item["右边说话人"]
                                        right_speaker.append(right_text)
                                        segments.append({
                                            "text": right_text,
                                            "speaker": "right",
                                            "index": i
                                        })
                    
                    # 按索引排序，确保顺序正确
                    segments.sort(key=lambda x: x["index"])
                    
                    parsed_script["left_speaker"] = left_speaker
                    parsed_script["right_speaker"] = right_speaker
                    parsed_script["segments"] = segments

                # 按标签打组（开场、循环、结束）
                grouped_script = {
                    "开场": opening,
                    "循环": [],
                    "结束": ending
                }

                # 填充循环部分（情绪标签和场景标签）
                for key, value in parsed.items():
                    if key in emotion_tags or key in scene_tags:
                        grouped_script["循环"].append({"标签": key, "内容": value})

                parsed_script["grouped"] = grouped_script

                # 提取封面总结
                if "封面总结" in parsed:
                    parsed_script["cover_summary"] = parsed["封面总结"]

                return TextProcessResponse(
                    status="success",
                    parsed_script=parsed_script,
                    tags=tags,
                    message="文案解析成功"
                )

            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析失败: {e}")
                return TextProcessResponse(
                    status="error",
                    message=f"智能生成模式需要 JSON 格式的文案: {str(e)}"
                )
        else:
            return TextProcessResponse(
                status="success",
                parsed_script={
                    "full_text": text,
                    "segments": [{"text": text, "emotion": "calm", "scene": "default"}]
                },
                tags=[],
                message="手动输入模式，文案已接收"
            )

    except Exception as e:
        logger.error(f"文案处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"文案处理失败: {str(e)}")


@router.post("/generate-script")
async def generate_script(request: GenerateScriptRequest):
    """
    LLM 生成文案接口

    Args:
        request: 生成文案请求，包含主题、提示词模板和模式

    Returns:
        生成的文案内容
    """
    try:
        topic = request.topic
        prompt_template = request.prompt
        mode = request.mode
        generator = get_script_generator()

        # 构建最终提示词
        if prompt_template:
            # 如果有自定义模板，替换其中的 {theme} 变量
            final_prompt = prompt_template.replace("{theme}", topic)
        else:
            # 如果没有自定义模板，使用默认模板
            if mode == "single":
                final_prompt = f"根据主题{topic}生成单人讲解文案，包含开场、情绪标签、场景标签、结束部分。请以 JSON 格式返回。"
            else:
                final_prompt = f"根据主题{topic}生成双人对话文案，包含开场、左边说话人、右边说话人、情绪标签、场景标签、结束部分。请以 JSON 格式返回。"
        
        result = await generator.generate(final_prompt)
        
        # 确保返回的是有效的JSON字符串
        try:
            # 验证JSON格式
            json.loads(result)
            script = result
        except json.JSONDecodeError:
            # 如果不是有效的JSON，返回错误
            raise HTTPException(status_code=500, detail="生成的文案格式错误")

        return {
            "code": 200,
            "message": "文案生成成功",
            "data": {
                "script": script,
                "topic": topic,
                "prompt": prompt_template,
                "mode": mode
            }
        }

    except Exception as e:
        logger.error(f"文案生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"文案生成失败: {str(e)}")


@router.post("/extract-frame", response_model=ExtractFrameResponse)
async def extract_frame(request: ExtractFrameRequest):
    """
    提取视频首帧接口

    Args:
        request: 提取首帧请求，包含视频路径

    Returns:
        base64 编码的首帧图像
    """
    import cv2
    import base64
    
    video_path = request.video_path
    
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"视频文件不存在: {video_path}")
    
    try:
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            raise HTTPException(status_code=500, detail=f"无法打开视频文件: {video_path}")
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            raise HTTPException(status_code=500, detail="无法读取视频帧")
        
        max_width = 400
        if frame.shape[1] > max_width:
            scale = max_width / frame.shape[1]
            frame = cv2.resize(frame, None, fx=scale, fy=scale)
        
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frame_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return ExtractFrameResponse(
            code=200,
            message="首帧提取成功",
            data={
                "frame_base64": f"data:image/jpeg;base64,{frame_base64}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提取首帧失败: {e}")
        raise HTTPException(status_code=500, detail=f"提取首帧失败: {str(e)}")


@router.post("/open-output-dir")
async def open_output_dir():
    """
    打开输出目录接口

    使用系统默认文件管理器打开 AUTOavantar/output 目录
    """
    import platform

    # 获取输出目录路径
    output_dir = Path(__file__).resolve().parent.parent.parent.parent / "output"

    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"创建输出目录: {output_dir}")

    output_dir_absolute = str(output_dir.absolute())

    try:
        if platform.system() == "Windows":
            asyncio.create_task(async_run_subprocess(["explorer", output_dir_absolute]))
        elif platform.system() == "Darwin":  # macOS
            asyncio.create_task(async_run_subprocess(["open", output_dir_absolute]))
        else:  # Linux
            asyncio.create_task(async_run_subprocess(["xdg-open", output_dir_absolute]))

        logger.info(f"打开输出目录: {output_dir_absolute}")
        return {
            "code": 200,
            "message": "输出目录已打开",
            "data": {"path": output_dir_absolute}
        }
    except Exception as e:
        logger.error(f"打开输出目录失败: {e}")
        raise HTTPException(status_code=500, detail=f"打开输出目录失败: {str(e)}")
