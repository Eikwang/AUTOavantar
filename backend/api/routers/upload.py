"""
文件上传路由
处理视频、音频等文件的上传
"""

import os
import uuid
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from config.settings import settings

logger = logging.getLogger("autoavantar-api.upload")

router = APIRouter()


def validate_file_extension(filename: str, allowed_extensions: list) -> bool:
    """验证文件扩展名"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in allowed_extensions


def validate_file_size(file_size: int) -> bool:
    """验证文件大小"""
    return file_size <= settings.MAX_FILE_SIZE


def get_video_save_path(group_type: str, purpose: str = "material", backend_root: Optional[Path] = None) -> Path:
    """
    获取视频保存路径
    
    Args:
        group_type: 视频分组类型 (opening/loop/scene/ending)
        purpose: 上传目的 (material=创建素材, task=创建任务)
        backend_root: backend 目录路径，默认自动检测
        
    Returns:
        保存目录的 Path 对象
        
    路径规则:
        - purpose=material 且 opening/loop/ending (角色素材) → backend/data/roles/
        - purpose=material 且 scene (场景素材) → backend/data/scenes/
        - purpose=task (创建任务) → backend/uploads/videos/{group_type}/
    """
    if backend_root is None:
        backend_root = Path(__file__).resolve().parent.parent.parent
    
    if purpose == "task":
        save_dir = backend_root / "uploads" / "videos" / group_type
    else:
        data_dir = backend_root / "data"
        
        if group_type in ("opening", "loop", "ending"):
            save_dir = data_dir / "roles"
        elif group_type == "scene":
            save_dir = data_dir / "scenes"
        else:
            save_dir = backend_root / "uploads" / "videos" / group_type
    
    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir


@router.post("/upload/video")
async def upload_video(
    file: UploadFile = File(..., description="视频文件"),
    group_type: str = Form("scene", description="视频分组类型: opening/loop/scene/ending"),
    purpose: str = Form("material", description="上传目的: material=创建素材, task=创建任务")
):
    """
    上传视频文件
    
    Args:
        file: 视频文件
        group_type: 视频分组类型
        purpose: 上传目的 (material=创建素材保存到data目录, task=创建任务保存到uploads目录)
        
    Returns:
        上传结果，包含文件路径
    """
    # 验证文件扩展名
    if not validate_file_extension(file.filename, settings.ALLOWED_VIDEO_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的视频格式。支持格式: {', '.join(settings.ALLOWED_VIDEO_EXTENSIONS)}"
        )
    
    # 生成唯一文件名
    ext = os.path.splitext(file.filename)[1].lower()
    unique_filename = f"{uuid.uuid4().hex[:8]}_{group_type}{ext}"
    
    # 获取保存目录
    backend_root = Path(__file__).resolve().parent.parent.parent
    save_dir = get_video_save_path(group_type, purpose, backend_root)
    
    # 保存文件
    file_path = save_dir / unique_filename
    
    try:
        content = await file.read()
        
        # 验证文件大小
        if not validate_file_size(len(content)):
            raise HTTPException(
                status_code=400,
                detail=f"文件大小超过限制 ({settings.MAX_FILE_SIZE / 1024 / 1024:.0f}MB)"
            )
        
        with open(file_path, "wb") as f:
            f.write(content)
        
        logger.info(f"视频上传成功: {file_path}")
        
        # 计算相对于 backend 目录的路径
        relative_path = str(file_path.relative_to(backend_root))
        
        return {
            "code": 200,
            "message": "上传成功",
            "data": {
                "file_path": relative_path,
                "filename": unique_filename,
                "original_filename": file.filename,
                "size": len(content),
                "group_type": group_type
            }
        }
        
    except Exception as e:
        logger.error(f"视频上传失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.post("/upload/audio")
async def upload_audio(
    file: UploadFile = File(..., description="音频文件"),
    audio_type: str = Form("reference", description="音频类型: reference/prompt/bgm")
):
    """
    上传音频文件
    
    Args:
        file: 音频文件
        audio_type: 音频类型
        
    Returns:
        上传结果，包含文件路径
    """
    # 验证文件扩展名
    if not validate_file_extension(file.filename, settings.ALLOWED_AUDIO_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的音频格式。支持格式: {', '.join(settings.ALLOWED_AUDIO_EXTENSIONS)}"
        )
    
    # 生成唯一文件名
    ext = os.path.splitext(file.filename)[1].lower()
    unique_filename = f"{uuid.uuid4().hex[:8]}_{audio_type}{ext}"
    
    # 根据音频类型确定保存目录
    if audio_type == "bgm":
        # BGM 保存到 uploads/audios/bgm 目录（与其他音频保持一致）
        upload_dir = os.path.join(settings.UPLOAD_DIR, "audios", "bgm")
        os.makedirs(upload_dir, exist_ok=True)
        file_path_obj = Path(upload_dir) / unique_filename
        base_dir = settings.UPLOAD_DIR
    else:
        # 其他音频类型保存到上传目录
        upload_dir = os.path.join(settings.UPLOAD_DIR, "audios", audio_type)
        os.makedirs(upload_dir, exist_ok=True)
        file_path_obj = Path(upload_dir) / unique_filename
        base_dir = settings.UPLOAD_DIR
    
    # 保存文件
    file_path = str(file_path_obj)
    
    try:
        content = await file.read()
        
        # 验证文件大小
        if not validate_file_size(len(content)):
            raise HTTPException(
                status_code=400,
                detail=f"文件大小超过限制 ({settings.MAX_FILE_SIZE / 1024 / 1024:.0f}MB)"
            )
        
        with open(file_path, "wb") as f:
            f.write(content)
        
        logger.info(f"音频上传成功: {file_path}")

        # 计算相对路径（统一使用 uploads/ 前缀，正斜杠）
        # os.path.relpath 在 Windows 上会返回反斜杠，需要转换
        relative_path = os.path.relpath(file_path, base_dir).replace("\\", "/")
        # 确保路径以 uploads/ 开头
        if not relative_path.startswith("uploads/"):
            relative_path = "uploads/" + relative_path

        return {
            "code": 200,
            "message": "上传成功",
            "data": {
                "file_path": relative_path,
                "filename": unique_filename,
                "original_filename": file.filename,
                "size": len(content),
                "audio_type": audio_type
            }
        }
        
    except Exception as e:
        logger.error(f"音频上传失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.get("/files/{file_path:path}")
async def get_file(file_path: str):
    """
    获取文件

    Args:
        file_path: 文件路径

    Returns:
        文件内容
    """
    backend_root = Path(__file__).resolve().parent.parent.parent
    
    # 检查路径是否指向 data 目录下的文件（包括 BGM 和 merged_audios）
    is_data_path = "backend/data" in file_path or file_path.startswith("data/")
    
    # 检查路径是否指向 uploads 目录
    is_uploads_path = file_path.startswith("uploads/")
    
    if is_data_path:
        # data 目录下的文件路径处理
        # 如果路径包含 backend/ 前缀，去掉它
        if file_path.startswith("backend/"):
            file_path = file_path[8:]
        full_path = (backend_root / file_path).resolve()
        
        # 确保路径在 data 目录内
        data_dir = backend_root / "data"
        if not str(full_path).startswith(str(data_dir)):
            raise HTTPException(status_code=403, detail="Access denied")
    elif is_uploads_path:
        # uploads 目录下的文件路径处理
        # 文件保存在 backend/uploads/ 目录下
        full_path = (backend_root / file_path).resolve()
        
        # 确保路径在 uploads 目录内
        uploads_dir = backend_root / "uploads"
        if not str(full_path).startswith(str(uploads_dir)):
            raise HTTPException(status_code=403, detail="Access denied")
    else:
        # 其他路径：兼容旧的相对路径方式
        base_path = Path(settings.UPLOAD_DIR).resolve()
        full_path = (base_path / file_path).resolve()
        
        # 确保路径在上传目录内
        if not str(full_path).startswith(str(base_path)):
            raise HTTPException(status_code=403, detail="Access denied")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(full_path)
