"""
素材库管理路由
处理角色、场景、BGM 等素材的查询和管理
"""

from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query, Body, UploadFile, File
import logging
import os
import sys
import json
import uuid
import shutil
from pathlib import Path

# 首先定义logger
logger = logging.getLogger("autoavantar-api.materials")

# 添加项目根目录到sys.path，确保可以导入business模块
# materials.py 位于 backend/api/routers/，需要向上4级到达 AUTOavantar 根目录
# backend/api/routers/materials.py -> routers -> api -> backend -> AUTOavantar
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    logger.info(f"已添加项目根目录到 sys.path: {project_root}")

# 导入音频合并器
try:
    from business.audio.audio_merger import create_audio_merger
    AUDIO_MERGER = create_audio_merger()
    logger.info("音频合并器初始化成功")
except Exception as e:
    logger.warning(f"音频合并器初始化失败: {e}")
    import traceback
    logger.warning(f"详细错误: {traceback.format_exc()}")
    AUDIO_MERGER = None

router = APIRouter()


def extract_video_frame(video_path: Optional[str], frame_index: int = 0) -> Optional[str]:
    """
    从视频中提取指定帧

    Args:
        video_path: 视频文件路径
        frame_index: 帧索引，默认为第一帧

    Returns:
        base64 编码的图像数据，失败返回 None
    """
    import cv2
    import base64

    # 解析视频路径（支持相对路径）
    resolved_path = resolve_video_path(video_path)
    if not resolved_path:
        return None

    cap = None
    try:
        cap = cv2.VideoCapture(str(resolved_path))
        
        if not cap.isOpened():
            logger.warning(f"无法打开视频文件: {video_path}")
            return None
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()
        
        if not ret or frame is None:
            logger.warning(f"无法读取视频帧: {video_path}")
            return None
        
        max_width = 200
        if frame.shape[1] > max_width:
            scale = max_width / frame.shape[1]
            frame = cv2.resize(frame, None, fx=scale, fy=scale)
        
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frame_base64 = base64.b64encode(buffer).decode('utf-8')
        
        return frame_base64
        
    except Exception as e:
        logger.warning(f"提取视频帧失败: {e}")
        return None
    finally:
        if cap is not None:
            cap.release()


import random
import base64

# 使用已定义的 project_root 作为项目根目录（AUTOavantar）
BASE_DIR = project_root
THUMBNAIL_DIR = BASE_DIR / "backend" / "data" / "thumbnails"
THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
(THUMBNAIL_DIR / "roles").mkdir(exist_ok=True)
(THUMBNAIL_DIR / "scenes").mkdir(exist_ok=True)


def resolve_video_path(video_path: Optional[str]) -> Optional[Path]:
    """
    将视频路径转换为绝对路径

    Args:
        video_path: 可能是相对路径或绝对路径

    Returns:
        绝对路径 Path 对象，如果路径无效返回 None
    """
    if not video_path:
        return None

    path = Path(video_path)

    # 如果已经是绝对路径且存在，直接返回
    if path.is_absolute() and path.exists():
        return path

    # 尝试相对于 BASE_DIR 解析
    abs_path = BASE_DIR / video_path
    if abs_path.exists():
        return abs_path

    # 尝试原始路径（可能路径本身就是正确的）
    if path.exists():
        return path

    logger.warning(f"无法找到视频文件: {video_path}")
    return None


def generate_role_thumbnail(
    opening_video: Optional[str],
    loop_videos: List[dict],
    ending_video: Optional[str],
    role_id: str
) -> Optional[str]:
    """
    生成角色素材缩略图
    
    优先级：开场视频 > 随机选择其他视频
    
    Args:
        opening_video: 开场视频路径
        loop_videos: 循环视频列表
        ending_video: 结束视频路径
        role_id: 角色 ID
        
    Returns:
        缩略图路径，失败返回 None
    """
    video_path = None
    
    if opening_video:
        video_path = opening_video
    else:
        all_videos = []
        for video in loop_videos:
            if video.get('path'):
                all_videos.append(video['path'])
        if ending_video:
            all_videos.append(ending_video)
        
        if all_videos:
            video_path = random.choice(all_videos)
    
    if not video_path:
        return None
    
    frame_base64 = extract_video_frame(video_path, 0)
    if not frame_base64:
        return None
    
    thumbnail_path = THUMBNAIL_DIR / "roles" / f"{role_id}.jpg"
    try:
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        with open(thumbnail_path, 'wb') as f:
            f.write(base64.b64decode(frame_base64))
        # 返回相对路径，便于跨机器使用
        return f"backend/data/thumbnails/roles/{role_id}.jpg"
    except Exception as e:
        logger.warning(f"保存缩略图失败: {e}")
        return None


def generate_scene_thumbnail(
    scene_videos: List[dict],
    scene_id: str
) -> Optional[str]:
    """
    生成场景素材缩略图
    
    优先级：产品展示标签视频 > 随机选择其他视频
    
    Args:
        scene_videos: 场景视频列表，每项包含 path 和 tag
        scene_id: 场景 ID
        
    Returns:
        缩略图路径，失败返回 None
    """
    video_path = None
    
    for video in scene_videos:
        if video.get('tag') == 'product' and video.get('path'):
            video_path = video['path']
            break
    
    if not video_path:
        all_videos = []
        for video in scene_videos:
            if video.get('path'):
                all_videos.append(video['path'])
        
        if all_videos:
            video_path = random.choice(all_videos)
    
    if not video_path:
        return None
    
    frame_base64 = extract_video_frame(video_path, 0)
    if not frame_base64:
        return None
    
    thumbnail_path = THUMBNAIL_DIR / "scenes" / f"{scene_id}.jpg"
    try:
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        with open(thumbnail_path, 'wb') as f:
            f.write(base64.b64decode(frame_base64))
        # 返回相对路径，便于跨机器使用
        return f"backend/data/thumbnails/scenes/{scene_id}.jpg"
    except Exception as e:
        logger.warning(f"保存缩略图失败: {e}")
        return None


class RoleInfo(BaseModel):
    """角色信息"""
    role_id: str
    role_name: str
    description: Optional[str] = None
    video_count: int = 0
    thumbnail: Optional[str] = None
    opening_video: Optional[str] = None
    loop_videos: Optional[List] = None
    ending_video: Optional[str] = None
    audio_id: Optional[str] = None
    is_double_mode: bool = False
    left_audio_id: Optional[str] = None
    right_audio_id: Optional[str] = None
    left_audio_name: Optional[str] = None
    right_audio_name: Optional[str] = None
    # 画外音字段
    pip_video_path: Optional[str] = None
    pip_left_video_path: Optional[str] = None
    pip_right_video_path: Optional[str] = None


class SceneInfo(BaseModel):
    """场景信息"""
    scene_id: str
    scene_name: str
    scene_type: str
    description: Optional[str] = None
    video_count: int = 0
    thumbnail: Optional[str] = None
    scene_videos: Optional[List] = None


class BGMInfo(BaseModel):
    """BGM 信息"""
    bgm_id: str
    bgm_name: str
    duration: float = 0.0
    path: Optional[str] = None
    description: Optional[str] = None


class AudioInfo(BaseModel):
    """参考音频信息"""
    id: str
    name: str
    duration: float = 0.0
    path: Optional[str] = None
    description: Optional[str] = None


class DeleteResponse(BaseModel):
    """删除响应"""
    code: int
    message: str


# 默认角色和场景素材（仅在首次创建文件时使用）
DEFAULT_ROLES = [
    {"role_id": "r001", "role_name": "主播小明", "description": "默认主播角色", "video_count": 5},
    {"role_id": "r002", "role_name": "讲师小红", "description": "培训讲师角色", "video_count": 3},
]

DEFAULT_SCENES = [
    {"scene_id": "s001", "scene_name": "办公室场景", "scene_type": "场景", "description": "办公环境背景", "video_count": 2},
    {"scene_id": "s002", "scene_name": "产品特写", "scene_type": "产品", "description": "产品展示背景", "video_count": 3},
]

# 角色和场景素材列表（初始为空，由用户创建或从文件加载）
MOCK_ROLES = []
MOCK_SCENES = []

# BGM素材列表（初始为空，由用户创建）
MOCK_BGMS = []

# 参考音频和BGM独立存储（持久化到文件）
import json
import os
from pathlib import Path

MOCK_AUDIOS_FILE = Path(__file__).parent.parent.parent / "data" / "mock_audios.json"
MOCK_BGMS_FILE = Path(__file__).parent.parent.parent / "data" / "mock_bgms.json"
MOCK_ROLES_FILE = Path(__file__).parent.parent.parent / "data" / "mock_roles.json"
MOCK_SCENES_FILE = Path(__file__).parent.parent.parent / "data" / "mock_scenes.json"

def load_mock_audios():
    """从文件加载音频数据"""
    global MOCK_AUDIOS
    try:
        if MOCK_AUDIOS_FILE.exists():
            with open(MOCK_AUDIOS_FILE, 'r', encoding='utf-8') as f:
                MOCK_AUDIOS = json.load(f)
            logger.info(f"已加载 {len(MOCK_AUDIOS)} 个音频素材")
        else:
            MOCK_AUDIOS = []
    except Exception as e:
        logger.error(f"加载音频数据失败: {e}")
        MOCK_AUDIOS = []

def save_mock_audios():
    """保存音频数据到文件"""
    try:
        MOCK_AUDIOS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MOCK_AUDIOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(MOCK_AUDIOS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存音频数据失败: {e}")

def load_mock_bgms():
    """从文件加载BGM数据"""
    global MOCK_BGMS
    try:
        if MOCK_BGMS_FILE.exists():
            with open(MOCK_BGMS_FILE, 'r', encoding='utf-8') as f:
                MOCK_BGMS = json.load(f)
            logger.info(f"已加载 {len(MOCK_BGMS)} 个BGM素材")
        else:
            MOCK_BGMS = []
            logger.info("BGM数据文件不存在，初始化为空列表")
    except Exception as e:
        logger.error(f"加载BGM数据失败: {e}")
        MOCK_BGMS = []

def save_mock_bgms():
    """保存BGM数据到文件"""
    try:
        MOCK_BGMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MOCK_BGMS_FILE, 'w', encoding='utf-8') as f:
            json.dump(MOCK_BGMS, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存BGM数据失败: {e}")

def normalize_thumbnail_path(thumbnail_path: str) -> str:
    """
    规范化缩略图路径，将绝对路径转换为相对路径

    Args:
        thumbnail_path: 原始缩略图路径（可能是绝对路径或相对路径）

    Returns:
        相对路径，如 "data/thumbnails/roles/r001.jpg"
    """
    if not thumbnail_path:
        return thumbnail_path

    # 如果已经是相对路径，直接返回
    if not os.path.isabs(thumbnail_path):
        return thumbnail_path

    # 提取关键部分：thumbnails/{type}/{id}.jpg
    import re
    # 匹配路径中的 thumbnails/roles 或 thumbnails/scenes 部分
    match = re.search(r'thumbnails[\\/]([^\\/]+)[\\/]([^\\/]+\.jpg)$', thumbnail_path)
    if match:
        type_name = match.group(1)  # roles 或 scenes
        filename = match.group(2)   # 如 r001.jpg
        return f"data/thumbnails/{type_name}/{filename}"

    # 如果无法匹配，尝试从路径中提取文件名
    filename = os.path.basename(thumbnail_path)
    # 根据文件名前缀判断类型（更精确的匹配：r + 数字 或 s + 数字）
    import re as _re
    if _re.match(r'^r\d+', filename):
        return f"data/thumbnails/roles/{filename}"
    elif _re.match(r'^s\d+', filename):
        return f"data/thumbnails/scenes/{filename}"

    # 无法转换，返回原路径
    logger.warning(f"无法规范化缩略图路径: {thumbnail_path}")
    return thumbnail_path

def load_mock_roles():
    """从文件加载角色数据"""
    global MOCK_ROLES
    try:
        if MOCK_ROLES_FILE.exists():
            with open(MOCK_ROLES_FILE, 'r', encoding='utf-8') as f:
                MOCK_ROLES = json.load(f)
            # 规范化缩略图路径：将绝对路径转换为相对路径
            for role in MOCK_ROLES:
                if 'thumbnail' in role and role['thumbnail']:
                    role['thumbnail'] = normalize_thumbnail_path(role['thumbnail'])
            logger.info(f"已加载 {len(MOCK_ROLES)} 个角色素材")
        else:
            MOCK_ROLES = DEFAULT_ROLES.copy()
            save_mock_roles()
            logger.info(f"已创建默认角色数据文件，包含 {len(MOCK_ROLES)} 个素材")
    except Exception as e:
        logger.error(f"加载角色数据失败: {e}")
        MOCK_ROLES = DEFAULT_ROLES.copy()

def save_mock_roles():
    """保存角色数据到文件"""
    try:
        MOCK_ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MOCK_ROLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(MOCK_ROLES, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存角色数据失败: {e}")

def load_mock_scenes():
    """从文件加载场景数据"""
    global MOCK_SCENES
    try:
        if MOCK_SCENES_FILE.exists():
            with open(MOCK_SCENES_FILE, 'r', encoding='utf-8') as f:
                MOCK_SCENES = json.load(f)
            # 规范化缩略图路径：将绝对路径转换为相对路径
            for scene in MOCK_SCENES:
                if 'thumbnail' in scene and scene['thumbnail']:
                    scene['thumbnail'] = normalize_thumbnail_path(scene['thumbnail'])
            logger.info(f"已加载 {len(MOCK_SCENES)} 个场景素材")
        else:
            MOCK_SCENES = DEFAULT_SCENES.copy()
            save_mock_scenes()
            logger.info(f"已创建默认场景数据文件，包含 {len(MOCK_SCENES)} 个素材")
    except Exception as e:
        logger.error(f"加载场景数据失败: {e}")
        MOCK_SCENES = DEFAULT_SCENES.copy()

def save_mock_scenes():
    """保存场景数据到文件"""
    try:
        MOCK_SCENES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MOCK_SCENES_FILE, 'w', encoding='utf-8') as f:
            json.dump(MOCK_SCENES, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存场景数据失败: {e}")

# 初始化时加载数据
load_mock_audios()
load_mock_bgms()
load_mock_roles()
load_mock_scenes()


@router.get("/materials/roles", response_model=List[RoleInfo])
async def get_roles():
    """
    获取角色列表
    
    Returns:
        角色列表
    """
    try:
        logger.info("=== get_roles 被调用 ===")
        logger.info(f"MOCK_ROLES 原始数据: {MOCK_ROLES}")
        
        role_list = []
        for role in MOCK_ROLES:
            role_data = dict(role)
            logger.info(f"处理角色: {role_data.get('role_id')}, is_double_mode: {role_data.get('is_double_mode')}")
            
            if role_data.get("is_double_mode"):
                left_audio_id = role_data.get("left_audio_id")
                right_audio_id = role_data.get("right_audio_id")
                logger.info(f"双人模式角色，left_audio_id: {left_audio_id}, right_audio_id: {right_audio_id}")
                
                for audio in MOCK_AUDIOS:
                    if audio.get("id") == left_audio_id:
                        role_data["left_audio_name"] = audio.get("name", "")
                    if audio.get("id") == right_audio_id:
                        role_data["right_audio_name"] = audio.get("name", "")
            
            role_list.append(RoleInfo(**role_data))
        
        logger.info(f"返回角色列表: {role_list}")
        return role_list
    except Exception as e:
        logger.error(f"获取角色列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取角色列表失败: {str(e)}")


@router.get("/materials/roles/{role_id}", response_model=RoleInfo)
async def get_role(role_id: str):
    """
    获取角色详情
    
    Args:
        role_id: 角色ID
        
    Returns:
        角色详情
    """
    for role in MOCK_ROLES:
        if role["role_id"] == role_id:
            role_data = dict(role)
            
            if role_data.get("is_double_mode"):
                left_audio_id = role_data.get("left_audio_id")
                right_audio_id = role_data.get("right_audio_id")
                
                for audio in MOCK_AUDIOS:
                    if audio.get("id") == left_audio_id:
                        role_data["left_audio_name"] = audio.get("name", "")
                    if audio.get("id") == right_audio_id:
                        role_data["right_audio_name"] = audio.get("name", "")
            
            return RoleInfo(**role_data)
    
    raise HTTPException(status_code=404, detail="角色不存在")


@router.get("/materials", response_model=List)
async def get_materials_by_type(type: str = Query(..., description="素材类型: role/scene/bgm/audio")):
    """
    根据类型获取素材列表（兼容前端调用）

    Args:
        type: 素材类型

    Returns:
        素材列表
    """
    try:
        logger.info(f"=== get_materials_by_type 被调用，type: {type} ===")
        
        if type == "role" or type == "character":
            logger.info(f"MOCK_ROLES 原始数据: {MOCK_ROLES}")
            role_list = []
            for role in MOCK_ROLES:
                role_data = dict(role)
                logger.info(f"处理角色: {role_data.get('role_id')}, is_double_mode: {role_data.get('is_double_mode')}")
                
                if role_data.get("is_double_mode"):
                    left_audio_id = role_data.get("left_audio_id")
                    right_audio_id = role_data.get("right_audio_id")
                    logger.info(f"双人模式角色，left_audio_id: {left_audio_id}, right_audio_id: {right_audio_id}")
                    
                    for audio in MOCK_AUDIOS:
                        if audio.get("id") == left_audio_id:
                            role_data["left_audio_name"] = audio.get("name", "")
                        if audio.get("id") == right_audio_id:
                            role_data["right_audio_name"] = audio.get("name", "")
                
                role_list.append(RoleInfo(**role_data))
            
            logger.info(f"返回角色列表: {role_list}")
            return role_list
        elif type == "scene":
            return [SceneInfo(**s) for s in MOCK_SCENES]
        elif type == "bgm":
            return [BGMInfo(**b) for b in MOCK_BGMS]
        elif type == "audio":
            return [AudioInfo(**a) for a in MOCK_AUDIOS]
        else:
            raise HTTPException(status_code=400, detail=f"不支持的素材类型: {type}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取素材列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取素材列表失败: {str(e)}")


@router.get("/materials/scenes", response_model=List[SceneInfo])
async def get_scenes(scene_type: Optional[str] = None):
    """
    获取场景列表
    
    Args:
        scene_type: 可选的场景类型过滤
        
    Returns:
        场景列表
    """
    try:
        scenes = MOCK_SCENES
        if scene_type:
            scenes = [s for s in scenes if s["scene_type"] == scene_type]
        
        return [SceneInfo(**s) for s in scenes]
    except Exception as e:
        logger.error(f"获取场景列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取场景列表失败: {str(e)}")


@router.get("/materials/scenes/{scene_id}", response_model=SceneInfo)
async def get_scene(scene_id: str):
    """
    获取场景详情
    
    Args:
        scene_id: 场景ID
        
    Returns:
        场景详情
    """
    for scene in MOCK_SCENES:
        if scene["scene_id"] == scene_id:
            return SceneInfo(**scene)
    
    raise HTTPException(status_code=404, detail="场景不存在")


@router.get("/materials/bgm", response_model=List[BGMInfo])
async def get_bgm_list():
    """
    获取 BGM 列表
    
    Returns:
        BGM 列表
    """
    try:
        return [BGMInfo(**b) for b in MOCK_BGMS]
    except Exception as e:
        logger.error(f"获取 BGM 列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取 BGM 列表失败: {str(e)}")


@router.get("/materials/bgm/{bgm_id}", response_model=BGMInfo)
async def get_bgm(bgm_id: str):
    """
    获取 BGM 详情
    
    Args:
        bgm_id: BGM ID
        
    Returns:
        BGM 详情
    """
    for bgm in MOCK_BGMS:
        if bgm["bgm_id"] == bgm_id:
            return BGMInfo(**bgm)
    
    raise HTTPException(status_code=404, detail="BGM 不存在")


@router.post("/materials", response_model=DeleteResponse)
async def create_material(data: dict = Body(...)):
    """
    创建素材（使用 JSON body）
    """
    try:
        global MOCK_ROLES, MOCK_SCENES, MOCK_BGMS, MOCK_AUDIOS

        type = data.get("type")
        name = data.get("name")

        if not type or not name:
            raise HTTPException(status_code=400, detail="缺少 type 或 name 参数")

        if type == "role":
            role_type = data.get("role_type")
            scenes = data.get("scenes", [])
            opening_video = data.get("opening_video")
            loop_videos = data.get("loop_videos", [])
            ending_video = data.get("ending_video")
            audio_id = data.get("audio_id")
            is_double_mode = data.get("is_double_mode", False)
            left_audio_id = data.get("left_audio_id")
            right_audio_id = data.get("right_audio_id")
            pip_video_path = data.get("pip_video_path")
            pip_left_video_path = data.get("pip_left_video_path")
            pip_right_video_path = data.get("pip_right_video_path")

            if is_double_mode:
                if not left_audio_id or not right_audio_id:
                    raise HTTPException(status_code=400, detail="双人模式必须选择两个参考音频")

                left_audio_exists = any(a.get("id") == left_audio_id for a in MOCK_AUDIOS)
                right_audio_exists = any(a.get("id") == right_audio_id for a in MOCK_AUDIOS)
                if not left_audio_exists:
                    raise HTTPException(status_code=400, detail=f"左边参考音频不存在: {left_audio_id}")
                if not right_audio_exists:
                    raise HTTPException(status_code=400, detail=f"右边参考音频不存在: {right_audio_id}")

            loop_videos_list = loop_videos if isinstance(loop_videos, list) else []

            # 将视频文件复制到 backend/data/roles/ 目录
            role_dir = BASE_DIR / "backend" / "data" / "roles"
            role_dir.mkdir(parents=True, exist_ok=True)

            def copy_video_to_role_dir(video_path_str: str) -> str:
                """将视频文件复制到 backend/data/roles/ 目录，返回相对路径"""
                if not video_path_str:
                    return ""
                resolved = resolve_video_path(video_path_str)
                if not resolved or not resolved.exists():
                    logger.warning(f"角色视频源文件不存在: {video_path_str}")
                    return video_path_str
                dest_filename = f"role_{uuid.uuid4().hex[:8]}{resolved.suffix}"
                dest_path = role_dir / dest_filename
                shutil.copy2(str(resolved), str(dest_path))
                logger.info(f"角色视频已复制到: {dest_path}")
                return f"backend/data/roles/{dest_filename}"

            # 复制开场视频
            saved_opening_video = copy_video_to_role_dir(opening_video) if opening_video else ""
            # 复制循环视频
            saved_loop_videos = []
            for lv in loop_videos_list:
                saved_path = copy_video_to_role_dir(lv.get("path", ""))
                saved_loop_videos.append({**lv, "path": saved_path})
            # 复制结尾视频
            saved_ending_video = copy_video_to_role_dir(ending_video) if ending_video else ""
            # 复制画外音视频
            saved_pip_video = copy_video_to_role_dir(pip_video_path) if pip_video_path else ""
            saved_pip_left_video = copy_video_to_role_dir(pip_left_video_path) if pip_left_video_path else ""
            saved_pip_right_video = copy_video_to_role_dir(pip_right_video_path) if pip_right_video_path else ""

            video_count = 0
            if saved_opening_video:
                video_count += 1
            video_count += len(saved_loop_videos)
            if saved_ending_video:
                video_count += 1

            new_role = {
                "role_id": f"r{len(MOCK_ROLES) + 1:03d}",
                "role_name": name,
                "role_type": role_type or "human",
                "scenes": scenes or [],
                "opening_video": saved_opening_video,
                "loop_videos": saved_loop_videos,
                "ending_video": saved_ending_video,
                "audio_id": audio_id or "",
                "description": "",
                "video_count": video_count,
                "is_double_mode": actual_is_double_mode,
                "left_audio_id": actual_left_audio_id if actual_is_double_mode else None,
                "right_audio_id": actual_right_audio_id if actual_is_double_mode else None,
                # 画外音字段
                "pip_video_path": saved_pip_video,
                "pip_left_video_path": saved_pip_left_video,
                "pip_right_video_path": saved_pip_right_video
            }

            thumbnail_path = generate_role_thumbnail(
                opening_video=saved_opening_video,
                loop_videos=saved_loop_videos,
                ending_video=saved_ending_video,
                role_id=new_role["role_id"]
            )
            new_role["thumbnail"] = thumbnail_path

            MOCK_ROLES.append(new_role)
            save_mock_roles()
            logger.info(f"创建角色素材: {new_role['role_id']}, 双人模式: {actual_is_double_mode}")
            return DeleteResponse(code=200, message="素材创建成功")

        elif type == "scene":
            # 解析场景视频列表
            scene_videos_list = []
            if scene_videos:
                try:
                    scene_videos_list = json.loads(scene_videos)
                except Exception as e:
                    logger.warning(f"解析场景视频列表失败: {e}")

            # 将视频文件复制到 backend/data/scenes/ 目录
            scene_dir = BASE_DIR / "backend" / "data" / "scenes"
            scene_dir.mkdir(parents=True, exist_ok=True)

            saved_scene_videos = []
            for sv in scene_videos_list:
                video_path_str = sv.get("path", "")
                if not video_path_str:
                    saved_scene_videos.append(sv)
                    continue
                resolved = resolve_video_path(video_path_str)
                if not resolved or not resolved.exists():
                    logger.warning(f"场景视频源文件不存在: {video_path_str}")
                    saved_scene_videos.append(sv)
                    continue
                dest_filename = f"scene_{uuid.uuid4().hex[:8]}{resolved.suffix}"
                dest_path = scene_dir / dest_filename
                shutil.copy2(str(resolved), str(dest_path))
                logger.info(f"场景视频已复制到: {dest_path}")
                saved_scene_videos.append({**sv, "path": f"backend/data/scenes/{dest_filename}"})

            new_scene = {
                "scene_id": f"s{len(MOCK_SCENES) + 1:03d}",
                "scene_name": name,
                "scene_type": "场景",
                "scene_videos": saved_scene_videos,
                "description": "",
                "video_count": len(saved_scene_videos)
            }

            thumbnail_path = generate_scene_thumbnail(
                scene_videos=saved_scene_videos,
                scene_id=new_scene["scene_id"]
            )
            new_scene["thumbnail"] = thumbnail_path

            MOCK_SCENES.append(new_scene)
            save_mock_scenes()
            logger.info(f"创建场景素材: {new_scene['scene_id']}")
            return DeleteResponse(code=200, message="素材创建成功")

        elif type == "bgm":
            # 使用bgm_path参数
            final_bgm_path = bgm_path or audio_path

            if not final_bgm_path:
                raise HTTPException(status_code=400, detail="请提供BGM文件路径")

            # 将BGM文件复制到 backend/data/BGM/ 目录
            bgm_dir = BASE_DIR / "backend" / "data" / "BGM"
            bgm_dir.mkdir(parents=True, exist_ok=True)

            source_path = resolve_video_path(final_bgm_path)
            if source_path and source_path.exists():
                bgm_filename = f"bgm_{uuid.uuid4().hex[:8]}{source_path.suffix}"
                bgm_dest = bgm_dir / bgm_filename
                shutil.copy2(str(source_path), str(bgm_dest))
                # 保存相对路径
                final_bgm_path = f"backend/data/BGM/{bgm_filename}"
                logger.info(f"BGM文件已复制到: {bgm_dest}")
            else:
                logger.warning(f"BGM源文件不存在: {final_bgm_path}，将保存原始路径")

            # 计算BGM时长
            bgm_duration = duration
            try:
                from pydub import AudioSegment

                resolved_bgm = resolve_video_path(final_bgm_path)
                if resolved_bgm and resolved_bgm.exists():
                    audio = AudioSegment.from_file(str(resolved_bgm))
                    bgm_duration = len(audio) / 1000.0
                    logger.info(f"BGM时长: {bgm_duration:.2f}秒")
            except Exception as e:
                logger.warning(f"无法计算BGM时长: {e}")

            new_bgm = {
                "bgm_id": f"b{len(MOCK_BGMS) + 1:03d}",
                "bgm_name": name,
                "duration": bgm_duration,
                "path": final_bgm_path,
                "description": ""
            }
            MOCK_BGMS.append(new_bgm)
            save_mock_bgms()
            logger.info(f"创建BGM素材: {new_bgm['bgm_id']}, 路径: {final_bgm_path}, 时长: {bgm_duration:.2f}秒")
            return DeleteResponse(code=200, message="素材创建成功")

        elif type == "audio":
            merged_audio_path = ""
            merged_duration = 0.0
            
            # 处理 audio_clips 参数
            if audio_clips:
                try:
                    clips = json.loads(audio_clips)
                    
                    if clips and isinstance(clips, list) and len(clips) > 0:
                        if AUDIO_MERGER:
                            # 修复文件路径：将相对路径转换为绝对路径
                            # 实际文件存储在 backend/uploads/ 目录下
                            fixed_clips = []
                            for clip in clips:
                                clip_path = clip.get('path', '')
                                
                                # 转换为 Path 对象
                                audio_path_obj = Path(clip_path)
                                
                                # 检查文件是否存在
                                if not audio_path_obj.exists():
                                    # 尝试添加 uploads/ 前缀
                                    if not str(audio_path_obj).startswith('uploads'):
                                        fixed_path = Path('uploads') / audio_path_obj
                                        if fixed_path.exists():
                                            clip_path = str(fixed_path)
                                            logger.info(f"路径修正: {clip['path']} -> {clip_path}")
                                    # 尝试使用绝对路径
                                    elif not Path.is_absolute(audio_path_obj):
                                        backend_root = Path(__file__).resolve().parent.parent
                                        abs_path = backend_root / clip_path
                                        if abs_path.exists():
                                            clip_path = str(abs_path)
                                            logger.info(f"使用绝对路径: {clip_path}")
                                
                                fixed_clips.append({
                                    **clip,
                                    'path': clip_path
                                })
                            
                            # 使用音频合并器合并多个音频片段
                            logger.info(f"开始合并 {len(fixed_clips)} 个音频片段")
                            
                            success, merged_path, merged_dur, error_msg = AUDIO_MERGER.merge_audio_clips(
                                fixed_clips,
                                output_filename=f"audio_{name}_{uuid.uuid4().hex[:8]}.wav"
                            )
                            
                            if success:
                                merged_audio_path = merged_path
                                merged_duration = merged_dur
                                logger.info(f"音频合并成功: {merged_path}, 时长: {merged_dur:.2f}秒")
                            else:
                                logger.error(f"音频合并失败: {error_msg}")
                                # 如果合并失败，至少使用第一个片段
                                if fixed_clips[0].get('path'):
                                    merged_audio_path = fixed_clips[0]['path']
                                    merged_duration = fixed_clips[0].get('duration', 0.0)
                        else:
                            # 如果没有音频合并器，使用第一个片段
                            if clips[0].get('path'):
                                merged_audio_path = clips[0]['path']
                                merged_duration = clips[0].get('duration', 0.0)
                    else:
                        logger.warning("音频片段列表为空或格式不正确")
                        
                except json.JSONDecodeError as e:
                    logger.error(f"音频剪辑列表解析失败: {audio_clips}, 错误: {e}")
                    raise HTTPException(status_code=400, detail=f"音频剪辑列表格式错误: {e}")
                except Exception as e:
                    logger.error(f"处理音频剪辑时发生错误: {e}")
                    raise HTTPException(status_code=500, detail=f"音频处理失败: {e}")
            else:
                logger.warning("未提供音频剪辑参数")
                raise HTTPException(status_code=400, detail="未提供音频文件")
            
            # 使用合并后的音频路径和时长，如果没有合并则使用传入的参数
            final_path = merged_audio_path or audio_path or ""
            final_duration = merged_duration if merged_duration > 0 else duration
            
            new_audio = {
                "id": f"a{len(MOCK_AUDIOS) + 1:03d}",
                "name": name,
                "duration": final_duration,
                "path": final_path,
                "description": ""
            }
            MOCK_AUDIOS.append(new_audio)
            save_mock_audios()  # 保存到文件
            logger.info(f"创建参考音频素材: {new_audio['id']}, 名称: {name}, 路径: {final_path}, 时长: {final_duration:.2f}秒")
            return DeleteResponse(code=200, message=f"素材创建成功（已合并{len(json.loads(audio_clips) if audio_clips else '[]')}个音频片段）")
        else:
            raise HTTPException(status_code=400, detail=f"不支持的素材类型: {type}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建素材失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建素材失败: {str(e)}")


@router.put("/materials/{material_id}", response_model=DeleteResponse)
async def update_material(
    material_id: str,
    type: str = Query(..., description="素材类型: role/scene/bgm/audio"),
    name: str = Query(None, description="素材名称（可选，audio/bgm类型可不传）"),
    role_type: str = Query(None, description="角色种类"),
    scenes: List[str] = Query(None, description="适用场景"),
    opening_video: str = Query(None, description="开场视频路径（仅角色类型使用）"),
    loop_videos: str = Query(None, description="循环视频列表（JSON格式，仅角色类型使用）"),
    ending_video: str = Query(None, description="结尾视频路径（仅角色类型使用）"),
    audio_id: str = Query(None, description="音频ID（仅角色类型使用）"),
    scene_videos: str = Query(None, description="场景视频列表（JSON格式，仅场景类型使用）"),
    duration: float = Query(None, description="音频/BGM时长（仅audio/bgm类型使用）"),
    path: str = Query(None, description="音频/BGM文件路径（仅audio/bgm类型使用）"),
    is_double_mode: bool = Query(None, description="是否开启双人模式（仅角色类型使用）"),
    left_audio_id: str = Query(None, description="左边说话人参考音频ID（双人模式）"),
    right_audio_id: str = Query(None, description="右边说话人参考音频ID（双人模式）"),
    # 画外音字段
    pip_video_path: str = Query(None, description="画外音视频路径（单人模式）"),
    pip_left_video_path: str = Query(None, description="画外音左边视频路径（双人模式）"),
    pip_right_video_path: str = Query(None, description="画外音右边视频路径（双人模式）")
):
    """
    更新素材
    
    Args:
        material_id: 素材ID
        type: 素材类型
        name: 素材名称
        role_type: 角色种类（仅角色类型使用）
        scenes: 适用场景（仅角色类型使用）
        opening_video: 开场视频路径（仅角色类型使用）
        loop_videos: 循环视频列表（JSON格式，仅角色类型使用）
        ending_video: 结尾视频路径（仅角色类型使用）
        audio_id: 音频ID（仅角色类型使用）
        scene_videos: 场景视频列表（JSON格式，仅场景类型使用）
        
    Returns:
        更新结果
    """
    try:
        # 更新模拟数据（后续替换为数据库操作）
        global MOCK_ROLES, MOCK_SCENES, MOCK_BGMS, MOCK_AUDIOS
        
        if type == "role":
            for role in MOCK_ROLES:
                if role["role_id"] == material_id:
                    if name is not None:
                        role["role_name"] = name
                    if role_type is not None:
                        role["role_type"] = role_type
                    if scenes is not None:
                        role["scenes"] = scenes
                    if opening_video is not None:
                        role["opening_video"] = opening_video
                    if ending_video is not None:
                        role["ending_video"] = ending_video
                    if audio_id is not None:
                        role["audio_id"] = audio_id
                    if loop_videos is not None:
                        try:
                            role["loop_videos"] = json.loads(loop_videos)
                        except Exception as e:
                            logger.warning(f"解析循环视频列表失败: {e}")
                    if is_double_mode is not None:
                        role["is_double_mode"] = is_double_mode
                    if left_audio_id is not None:
                        role["left_audio_id"] = left_audio_id
                    if right_audio_id is not None:
                        role["right_audio_id"] = right_audio_id
                    # 画外音字段更新（复制到角色目录，与创建逻辑一致）
                    if pip_video_path is not None:
                        role["pip_video_path"] = copy_video_to_role_dir(pip_video_path) if pip_video_path else ""
                    if pip_left_video_path is not None:
                        role["pip_left_video_path"] = copy_video_to_role_dir(pip_left_video_path) if pip_left_video_path else ""
                    if pip_right_video_path is not None:
                        role["pip_right_video_path"] = copy_video_to_role_dir(pip_right_video_path) if pip_right_video_path else ""
                    
                    # 重新计算视频总数
                    video_count = 0
                    if role.get("opening_video"):
                        video_count += 1
                    video_count += len(role.get("loop_videos", []))
                    if role.get("ending_video"):
                        video_count += 1
                    role["video_count"] = video_count
                    
                    save_mock_roles()
                    logger.info(f"更新角色素材: {material_id}")
                    return DeleteResponse(code=200, message="素材更新成功")
            raise HTTPException(status_code=404, detail="角色不存在")
            
        elif type == "scene":
            for scene in MOCK_SCENES:
                if scene["scene_id"] == material_id:
                    if name is not None:
                        scene["scene_name"] = name
                    if scene_videos is not None:
                        try:
                            scene["scene_videos"] = json.loads(scene_videos)
                            scene["video_count"] = len(scene["scene_videos"])
                        except Exception as e:
                            logger.warning(f"解析场景视频列表失败: {e}")
                    
                    save_mock_scenes()
                    logger.info(f"更新场景素材: {material_id}")
                    return DeleteResponse(code=200, message="素材更新成功")
            raise HTTPException(status_code=404, detail="场景不存在")
            
        elif type == "bgm":
            for bgm in MOCK_BGMS:
                if bgm["bgm_id"] == material_id:
                    if name is not None:
                        bgm["bgm_name"] = name
                    if duration is not None:
                        bgm["duration"] = duration
                    if path is not None:
                        bgm["path"] = path
                    save_mock_bgms()
                    logger.info(f"更新BGM素材: {material_id}, duration={duration}, path={path}")
                    return DeleteResponse(code=200, message="素材更新成功")
            raise HTTPException(status_code=404, detail="BGM不存在")
        elif type == "audio":
            for audio in MOCK_AUDIOS:
                if audio["id"] == material_id:
                    if name is not None:
                        audio["name"] = name
                    if duration is not None:
                        audio["duration"] = duration
                    if path is not None:
                        audio["path"] = path
                    save_mock_audios()
                    logger.info(f"更新音频素材: {material_id}, duration={duration}, path={path}")
                    return DeleteResponse(code=200, message="素材更新成功")
            raise HTTPException(status_code=404, detail="音频不存在")
        else:
            raise HTTPException(status_code=400, detail=f"不支持的素材类型: {type}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新素材失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新素材失败: {str(e)}")

def delete_video_file(video_path_str: str):
    """
    删除视频文件
    
    Args:
        video_path_str: 视频文件路径
    """
    if not video_path_str:
        return
        
    try:
        video_path = Path(video_path_str)
        
        if not video_path.is_absolute():
            # 计算正确的后端根目录：从当前文件向上找3级
            backend_root = Path(__file__).resolve().parent.parent.parent
            
            # 如果路径已经包含 backend/ 前缀，去掉它
            if video_path_str.startswith('backend\\') or video_path_str.startswith('backend/'):
                video_path_str = video_path_str[8:]
            
            video_path = backend_root / video_path_str
        
        logger.info(f"尝试删除视频文件: {video_path}")
        
        if video_path.exists():
            video_path.unlink()
            logger.info(f"成功删除视频文件: {video_path}")
        else:
            logger.warning(f"视频文件不存在，跳过文件删除: {video_path}")
    except Exception as file_error:
        logger.error(f"删除视频文件失败: {file_error}")
        raise HTTPException(
            status_code=500, 
            detail=f"删除视频文件失败: {str(file_error)}"
        )


@router.delete("/materials/{material_id}", response_model=DeleteResponse)
async def delete_material(material_id: str, type: str = Query(..., description="素材类型: role/scene/bgm/audio")):
    """
    删除素材
    
    Args:
        material_id: 素材ID
        type: 素材类型
        
    Returns:
        删除结果
    """
    try:
        # 从模拟数据中删除（后续替换为数据库操作）
        global MOCK_ROLES, MOCK_SCENES, MOCK_BGMS, MOCK_AUDIOS
        
        logger.info(f"收到删除请求: material_id={material_id}, type={type}")
        
        if type == "role":
            initial_count = len(MOCK_ROLES)
            role_to_delete = next((r for r in MOCK_ROLES if r["role_id"] == material_id), None)
            
            if role_to_delete:
                # 尝试删除角色相关视频文件
                try:
                    if role_to_delete.get("opening_video"):
                        delete_video_file(role_to_delete["opening_video"])
                    if role_to_delete.get("ending_video"):
                        delete_video_file(role_to_delete["ending_video"])
                    if role_to_delete.get("loop_videos"):
                        for video in role_to_delete["loop_videos"]:
                            delete_video_file(video.get("path"))
                    
                    thumbnail_path = THUMBNAIL_DIR / "roles" / f"{material_id}.jpg"
                    if thumbnail_path.exists():
                        thumbnail_path.unlink()
                except Exception as file_error:
                    logger.error(f"删除角色文件失败: {file_error}")
                    raise HTTPException(
                        status_code=500, 
                        detail=f"删除角色文件失败: {str(file_error)}"
                    )
            
            MOCK_ROLES = [r for r in MOCK_ROLES if r["role_id"] != material_id]
            if len(MOCK_ROLES) < initial_count:
                save_mock_roles()  # 保存到文件
                logger.info(f"删除角色素材: {material_id}")
                return DeleteResponse(code=200, message="素材删除成功")
            raise HTTPException(status_code=404, detail="角色不存在")
            
        elif type == "scene":
            initial_count = len(MOCK_SCENES)
            scene_to_delete = next((s for s in MOCK_SCENES if s["scene_id"] == material_id), None)
            
            if scene_to_delete:
                # 尝试删除场景相关视频文件
                try:
                    if scene_to_delete.get("scene_videos"):
                        for video in scene_to_delete["scene_videos"]:
                            delete_video_file(video.get("path"))
                    
                    thumbnail_path = THUMBNAIL_DIR / "scenes" / f"{material_id}.jpg"
                    if thumbnail_path.exists():
                        thumbnail_path.unlink()
                except Exception as file_error:
                    logger.error(f"删除场景文件失败: {file_error}")
                    raise HTTPException(
                        status_code=500, 
                        detail=f"删除场景文件失败: {str(file_error)}"
                    )
            
            MOCK_SCENES = [s for s in MOCK_SCENES if s["scene_id"] != material_id]
            if len(MOCK_SCENES) < initial_count:
                save_mock_scenes()  # 保存到文件
                logger.info(f"删除场景素材: {material_id}")
                return DeleteResponse(code=200, message="素材删除成功")
            raise HTTPException(status_code=404, detail="场景不存在")
            
        elif type == "bgm":
            # BGM类型从MOCK_BGMS中删除（使用bgm_id）
            initial_count = len(MOCK_BGMS)
            audio_to_delete = None
            for b in MOCK_BGMS:
                if b["bgm_id"] == material_id:
                    audio_to_delete = b
                    break
            
            if not audio_to_delete:
                logger.warning(f"BGM素材不存在: {material_id}")
                raise HTTPException(status_code=404, detail="BGM不存在")
            
            logger.info(f"找到要删除的BGM: {audio_to_delete}")
            
            # 首先尝试删除实际音频文件
            if audio_to_delete and audio_to_delete.get("path"):
                try:
                    audio_path_str = audio_to_delete["path"]
                    audio_path = Path(audio_path_str)
                    
                    if not audio_path.is_absolute():
                        # 计算正确的后端根目录：从当前文件向上找3级
                        # materials.py 位于 backend/api/routers/
                        # 需要到达 backend/ 目录
                        backend_root = Path(__file__).resolve().parent.parent.parent
                        logger.info(f"后端根目录: {backend_root}")
                        
                        # 如果路径已经包含 backend/ 前缀，去掉它
                        if audio_path_str.startswith('backend\\') or audio_path_str.startswith('backend/'):
                            audio_path_str = audio_path_str[8:]  # 去掉 "backend/" 或 "backend\"
                        
                        audio_path = backend_root / audio_path_str
                    
                    logger.info(f"尝试删除BGM文件: {audio_path}")
                    
                    if audio_path.exists():
                        audio_path.unlink()
                        logger.info(f"成功删除BGM文件: {audio_path}")
                except Exception as file_error:
                    logger.error(f"删除BGM文件失败: {file_error}")
                    raise HTTPException(
                        status_code=500, 
                        detail=f"删除音频文件失败: {str(file_error)}"
                    )
            
            # 文件删除成功后，再从列表中删除
            MOCK_BGMS = [b for b in MOCK_BGMS if b["bgm_id"] != material_id]
            if len(MOCK_BGMS) < initial_count:
                save_mock_bgms()
                logger.info(f"删除BGM素材: {material_id}")
                return DeleteResponse(code=200, message="素材删除成功")
            
            raise HTTPException(status_code=404, detail="BGM不存在")
            
        elif type == "audio":
            # 音频类型从MOCK_AUDIOS中删除（使用id）
            initial_count = len(MOCK_AUDIOS)
            logger.info(f"当前音频列表长度: {initial_count}")
            logger.info(f"要删除的音频ID: {material_id}")
            
            audio_to_delete = None
            for a in MOCK_AUDIOS:
                if a["id"] == material_id:
                    audio_to_delete = a
                    break
            
            if not audio_to_delete:
                logger.warning(f"音频素材不存在: {material_id}")
                raise HTTPException(status_code=404, detail="音频不存在")
            
            logger.info(f"找到要删除的音频: {audio_to_delete}")
            
            # 首先尝试删除实际音频文件
            if audio_to_delete and audio_to_delete.get("path"):
                try:
                    audio_path_str = audio_to_delete["path"]
                    audio_path = Path(audio_path_str)
                    
                    if not audio_path.is_absolute():
                        # 计算正确的后端根目录：从当前文件向上找3级
                        # materials.py 位于 backend/api/routers/
                        # 需要到达 backend/ 目录
                        backend_root = Path(__file__).resolve().parent.parent.parent
                        logger.info(f"后端根目录: {backend_root}")
                        
                        # 如果路径已经包含 backend/ 前缀，去掉它
                        if audio_path_str.startswith('backend\\') or audio_path_str.startswith('backend/'):
                            audio_path_str = audio_path_str[8:]  # 去掉 "backend/" 或 "backend\"
                        
                        audio_path = backend_root / audio_path_str
                    
                    logger.info(f"尝试删除音频文件: {audio_path}")
                    
                    if audio_path.exists():
                        audio_path.unlink()
                        logger.info(f"成功删除音频文件: {audio_path}")
                    else:
                        logger.warning(f"音频文件不存在，跳过文件删除: {audio_path}")
                except Exception as file_error:
                    logger.error(f"删除音频文件失败: {file_error}")
                    raise HTTPException(
                        status_code=500, 
                        detail=f"删除音频文件失败: {str(file_error)}"
                    )
            
            # 创建新的列表，排除要删除的项
            new_audios = []
            for a in MOCK_AUDIOS:
                if a["id"] != material_id:
                    new_audios.append(a)
            
            # 验证是否成功删除
            if len(new_audios) >= initial_count:
                logger.warning(f"没有从列表中删除任何项，原始长度: {initial_count}, 新长度: {len(new_audios)}")
                raise HTTPException(status_code=404, detail="音频不存在")
            
            # 更新全局变量并保存
            MOCK_AUDIOS = new_audios
            save_mock_audios()
            
            logger.info(f"删除音频素材成功: {material_id}")
            return DeleteResponse(code=200, message="素材删除成功")
            
        else:
            raise HTTPException(status_code=400, detail=f"不支持的素材类型: {type}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除素材失败: {str(e)}")
        import traceback
        logger.error(f"详细错误堆栈: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"删除素材失败: {str(e)}")


@router.post("/materials/audio/upload", response_model=dict)
async def upload_audio_files(
    files: List[UploadFile] = File(..., description="音频文件列表，支持多个文件"),
    name: str = Query(..., description="音频素材名称"),
    description: str = Query("", description="音频素材描述")
):
    """
    上传多个音频文件并合并为单个音频素材
    
    支持的文件格式: wav, mp3, flac, ogg, m4a
    最大文件数量: 50
    最大单个文件大小: 100MB
    最大总时长: 1小时
    
    Args:
        files: 音频文件列表
        name: 音频素材名称
        description: 音频素材描述
        
    Returns:
        创建结果，包含素材信息
    """
    from fastapi import UploadFile, File
    
    logger.info(f"接收到音频上传请求，文件数量: {len(files)}, 名称: {name}")
    
    try:
        if not files or len(files) == 0:
            raise HTTPException(status_code=400, detail="没有上传的文件")
        
        if len(files) > 50:
            raise HTTPException(status_code=400, detail="上传文件数量超过限制（最大50个）")
        
        if not AUDIO_MERGER:
            raise HTTPException(status_code=500, detail="音频处理服务未初始化")
        
        # 收集上传的文件
        uploaded_files = []
        
        for file in files:
            try:
                content = await file.read()
                
                if len(content) == 0:
                    logger.warning(f"跳过空文件: {file.filename}")
                    continue
                
                if len(content) > 100 * 1024 * 1024:
                    logger.warning(f"跳过过大文件: {file.filename} ({len(content)} bytes)")
                    continue
                
                uploaded_files.append((file.filename, content))
                logger.info(f"已读取文件: {file.filename}, 大小: {len(content)} bytes")
                
            except Exception as e:
                logger.error(f"读取文件失败: {file.filename}, 错误: {e}")
                continue
        
        if not uploaded_files:
            raise HTTPException(status_code=400, detail="没有可用的音频文件")
        
        # 生成输出文件名
        output_filename = f"audio_{name}_{uuid.uuid4().hex[:8]}.wav"
        
        # 合并音频文件
        logger.info(f"开始合并 {len(uploaded_files)} 个音频文件")
        
        success, merged_path, merged_duration, error_msg = AUDIO_MERGER.merge_uploaded_files(
            uploaded_files,
            output_filename=output_filename
        )
        
        if not success:
            logger.error(f"音频合并失败: {error_msg}")
            raise HTTPException(status_code=500, detail=f"音频合并失败: {error_msg}")
        
        # 保存到数据库/文件
        global MOCK_AUDIOS
        
        new_audio = {
            "id": f"a{len(MOCK_AUDIOS) + 1:03d}",
            "name": name,
            "duration": merged_duration,
            "path": merged_path,
            "description": description,
            "source_files": len(uploaded_files),
            "created_at": str(Path().resolve())
        }
        
        MOCK_AUDIOS.append(new_audio)
        save_mock_audios()
        
        logger.info(f"参考音频素材创建成功: {new_audio['id']}, 名称: {name}, "
                    f"路径: {merged_path}, 时长: {merged_duration:.2f}秒, "
                    f"源文件数量: {len(uploaded_files)}")
        
        return {
            "code": 200,
            "message": f"素材创建成功，已合并{len(uploaded_files)}个音频片段",
            "data": {
                "id": new_audio["id"],
                "name": new_audio["name"],
                "duration": new_audio["duration"],
                "path": new_audio["path"],
                "description": new_audio["description"],
                "source_files_count": new_audio["source_files"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传音频文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传音频文件失败: {str(e)}")


@router.post("/materials/audio/merge-and-save", response_model=dict)
async def merge_and_save_audio_clips(
    clips: List[dict] = Body(..., description="音频片段列表，每个元素包含 path 字段"),
    name: str = Query(..., description="音频素材名称"),
    description: str = Query("", description="音频素材描述")
):
    """
    合并已有的音频片段并保存为新的音频素材
    
    Args:
        clips: 音频片段列表，每个元素包含:
            - path: 音频文件路径（必需）
            - name: 音频名称（可选）
            - duration: 音频时长（可选）
        name: 音频素材名称
        description: 音频素材描述
        
    Returns:
        创建结果，包含素材信息
    """
    logger.info(f"接收到音频合并请求，片段数量: {len(clips)}, 名称: {name}")
    
    try:
        if not clips or len(clips) == 0:
            raise HTTPException(status_code=400, detail="音频片段列表为空")
        
        if not AUDIO_MERGER:
            raise HTTPException(status_code=500, detail="音频处理服务未初始化")
        
        # 生成输出文件名
        output_filename = f"audio_{name}_{uuid.uuid4().hex[:8]}.wav"
        
        # 修复文件路径：将相对路径转换为绝对路径
        fixed_clips = []
        for clip in clips:
            clip_path = clip.get('path', '')
            
            # 转换为 Path 对象
            audio_path_obj = Path(clip_path)
            
            # 检查文件是否存在
            if not audio_path_obj.exists():
                # 尝试添加 uploads/ 前缀
                if not str(audio_path_obj).startswith('uploads'):
                    fixed_path = Path('uploads') / audio_path_obj
                    if fixed_path.exists():
                        clip_path = str(fixed_path)
                        logger.info(f"路径修正: {clip['path']} -> {clip_path}")
                # 尝试使用绝对路径
                elif not Path.is_absolute(audio_path_obj):
                    backend_root = Path(__file__).resolve().parent.parent
                    abs_path = backend_root / clip_path
                    if abs_path.exists():
                        clip_path = str(abs_path)
                        logger.info(f"使用绝对路径: {clip_path}")
            
            fixed_clips.append({
                **clip,
                'path': clip_path
            })
        
        # 合并音频片段
        logger.info(f"开始合并 {len(fixed_clips)} 个音频片段")
        
        success, merged_path, merged_duration, error_msg = AUDIO_MERGER.merge_audio_clips(
            fixed_clips,
            output_filename=output_filename
        )
        
        if not success:
            logger.error(f"音频合并失败: {error_msg}")
            raise HTTPException(status_code=500, detail=f"音频合并失败: {error_msg}")
        
        # 保存到数据库/文件
        global MOCK_AUDIOS
        
        new_audio = {
            "id": f"a{len(MOCK_AUDIOS) + 1:03d}",
            "name": name,
            "duration": merged_duration,
            "path": merged_path,
            "description": description,
            "source_files": len(clips),
            "created_at": str(Path().resolve())
        }
        
        MOCK_AUDIOS.append(new_audio)
        save_mock_audios()
        
        logger.info(f"参考音频素材创建成功: {new_audio['id']}, 名称: {name}, "
                    f"路径: {merged_path}, 时长: {merged_duration:.2f}秒, "
                    f"源片段数量: {len(clips)}")
        
        return {
            "code": 200,
            "message": f"素材创建成功，已合并{len(clips)}个音频片段",
            "data": {
                "id": new_audio["id"],
                "name": new_audio["name"],
                "duration": new_audio["duration"],
                "path": new_audio["path"],
                "description": new_audio["description"],
                "source_files_count": new_audio["source_files"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"合并音频片段失败: {e}")
        raise HTTPException(status_code=500, detail=f"合并音频片段失败: {str(e)}")


@router.get("/materials/audio/validate", response_model=dict)
async def validate_audio_files(
    paths: str = Query(..., description="音频文件路径列表（逗号分隔）")
):
    """
    验证音频文件列表
    
    Args:
        paths: 音频文件路径列表（逗号分隔）
        
    Returns:
        验证结果
    """
    logger.info(f"接收到音频验证请求，路径数量: {len(paths.split(','))}")
    
    try:
        if not paths:
            raise HTTPException(status_code=400, detail="没有提供音频文件路径")
        
        path_list = [p.strip() for p in paths.split(',') if p.strip()]
        
        if not path_list:
            raise HTTPException(status_code=400, detail="音频文件路径列表为空")
        
        if not AUDIO_MERGER:
            raise HTTPException(status_code=500, detail="音频处理服务未初始化")
        
        # 验证每个文件
        validation_results = []
        total_duration = 0.0
        valid_count = 0
        
        for path in path_list:
            is_valid, error, info = AUDIO_MERGER.validate_audio_file(path)
            
            result = {
                "path": path,
                "valid": is_valid,
                "error": error if not is_valid else "",
                "info": info if is_valid else {}
            }
            
            validation_results.append(result)
            
            if is_valid:
                valid_count += 1
                total_duration += info.get("duration", 0.0)
        
        logger.info(f"音频验证完成: {valid_count}/{len(path_list)} 个文件有效，"
                    f"总时长: {total_duration:.2f}秒")
        
        return {
            "code": 200,
            "message": f"验证完成：{valid_count}/{len(path_list)} 个文件有效",
            "data": {
                "total_files": len(path_list),
                "valid_files": valid_count,
                "invalid_files": len(path_list) - valid_count,
                "total_duration": total_duration,
                "results": validation_results
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证音频文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"验证音频文件失败: {str(e)}")
