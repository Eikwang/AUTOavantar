"""
API 数据模型模块
定义请求和响应的数据结构
遵循 Pydantic V2 规范
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, model_validator


# ============== 任务相关模型 ==============

class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class TaskStage(str, Enum):
    """任务阶段枚举"""
    PENDING = "pending"
    INITIALIZING = "initializing"
    PREPROCESSING = "preprocessing"
    SCRIPT_GENERATION = "script_generation"
    AUDIO_SYNTHESIS = "audio_synthesis"
    VIDEO_GENERATION = "video_generation"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoWithTag(BaseModel):
    """带标签的视频素材"""
    model_config = ConfigDict(from_attributes=True)

    file_path: str = Field(default="", description="视频文件路径")
    emotion_tags: List[str] = Field(default_factory=list, description="情绪标签列表")
    scene_tags: List[str] = Field(default_factory=list, description="场景标签列表")


class ScriptSegment(BaseModel):
    """文案段落模型"""
    model_config = ConfigDict(from_attributes=True)
    
    segment_id: str = Field(..., description="段落ID")
    text: str = Field(..., description="文本内容")
    scene_type: str = Field(default="general", description="场景类型")
    emotion: str = Field(default="neutral", description="情绪类型")
    tone: str = Field(default="normal", description="语调")
    emotion_weight: float = Field(default=0.8, ge=0.0, le=1.0, description="情绪权重")
    audio_path: Optional[str] = Field(None, description="生成的音频路径")
    video_path: Optional[str] = Field(None, description="生成的视频路径")
    status: str = Field(default="pending", description="段落状态")
    error_message: Optional[str] = Field(None, description="错误信息")


class TaskConfig(BaseModel):
    """任务配置模型"""
    model_config = ConfigDict(from_attributes=True)
    
    # 预处理配置
    enable_face_alignment: bool = Field(default=True, description="是否启用面部对齐")
    
    # TTS 配置
    tts_speed: float = Field(default=1.0, ge=0.8, le=1.2, description="语速 (0.8-1.2)")
    tts_emo_weight: float = Field(default=0.8, ge=0.1, le=1.2, description="情感权重")

    # 双人模式 TTS 配置
    enable_double_mode: bool = Field(default=False, description="是否启用双人模式")
    left_tts_speed: Optional[float] = Field(default=None, ge=0.8, le=1.2, description="左说话人语速 (双人模式)")
    right_tts_speed: Optional[float] = Field(default=None, ge=0.8, le=1.2, description="右说话人语速 (双人模式)")
    left_tts_emo_weight: Optional[float] = Field(default=None, ge=0.1, le=1.2, description="左说话人情感权重 (双人模式)")
    right_tts_emo_weight: Optional[float] = Field(default=None, ge=0.1, le=1.2, description="右说话人情感权重 (双人模式)")
    
    # HeyGem 配置
    heygem_steps: int = Field(default=16, ge=4, le=32, description="推理步数")
    heygem_ifface: bool = Field(default=True, description="是否使用原始分辨率")
    heygem_if_gfpgan: bool = Field(default=False, description="是否使用 GFPGAN")
    heygem_batch_size: int = Field(default=4, ge=1, le=16, description="推理批次大小")
    
    # 音频处理配置
    enable_denoise: bool = Field(default=True, description="是否启用降噪")
    denoise_strength: float = Field(default=0.7, ge=0.0, le=1.0, description="降噪强度")
    
    # 后期处理配置
    enable_postprocess: bool = Field(default=True, description="是否启用后期处理")
    enable_subtitle: bool = Field(default=True, description="是否添加字幕")
    enable_bgm: bool = Field(default=True, description="是否添加 BGM")
    bgm_volume: float = Field(default=0.3, ge=0.0, le=1.0, description="BGM 音量")
    enable_cover: bool = Field(default=False, description="是否生成封面")
    cover_prompt_template: str = Field(
        default="根据文案{summary}生成视频封面，风格简洁，突出主题",
        description="封面提示词模版，{summary} 会被替换为封面总结"
    )
    
    # 字幕样式配置
    subtitle_font: str = Field(default="SimHei", description="字幕字体")
    subtitle_size: int = Field(default=24, ge=10, le=72, description="字幕字号")
    subtitle_color: str = Field(default="white", description="字幕颜色")
    subtitle_stroke_color: str = Field(default="#000000", description="字幕描边颜色")
    subtitle_stroke_width: float = Field(default=1.0, ge=0.0, le=10.0, description="字幕描边宽度")
    subtitle_position: str = Field(default="bottom", description="字幕位置")
    subtitle_background_alpha: float = Field(default=0.0, ge=0.0, le=1.0, description="字幕背景透明度")
    
    # LLM 配置
    use_llm_generate: bool = Field(default=False, description="是否使用 LLM 生成文案")
    llm_prompt: Optional[str] = Field(None, description="LLM 提示词")

    # 画外音配置
    enable_pip: bool = Field(default=False, description="是否启用画外音")
    pip_video_path: Optional[str] = Field(None, description="画外音视频路径")
    pip_left_video_path: Optional[str] = Field(None, description="画外音左边视频路径")
    pip_right_video_path: Optional[str] = Field(None, description="画外音右边视频路径")


class TaskBase(BaseModel):
    """任务基础模型"""
    model_config = ConfigDict(from_attributes=True)
    
    task_id: str = Field(..., description="任务ID")
    name: str = Field(..., description="任务名称")
    status: TaskStatus = Field(..., description="任务状态")
    current_stage: TaskStage = Field(default=TaskStage.INITIALIZING, description="当前阶段")
    progress: float = Field(default=0.0, ge=0.0, le=100.0, description="进度百分比 (0-100)")


class TaskResponse(TaskBase):
    """任务响应模型"""
    model_config = ConfigDict(from_attributes=True)

    source_video_path: Optional[str] = Field(None, description="源视频路径")
    script_text: Optional[str] = Field(None, description="原始文案")
    prompt_audio_path: Optional[str] = Field(None, description="音色参考音频路径")
    bgm_path: Optional[str] = Field(None, description="BGM 路径")
    output_path: Optional[str] = Field(None, description="输出路径")
    error_message: Optional[str] = Field(None, description="错误信息")
    segments: List[ScriptSegment] = Field(default=[], description="文案段落列表")
    config: Optional[TaskConfig] = Field(None, description="任务配置")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    is_priority: bool = Field(default=False, description="是否为插队任务")


class TaskCreateRequest(BaseModel):
    """创建任务请求"""
    name: str = Field(..., min_length=1, max_length=200, description="任务名称")
    source_video_path: Optional[str] = Field(None, description="源视频路径（可选）")
    script_text: Optional[str] = Field(None, description="文案文本")
    topic: Optional[str] = Field(None, description="主题（用于 LLM 生成文案）")
    prompt_audio_path: Optional[str] = Field(None, description="音色参考音频路径（单人模式）")
    left_prompt_audio_path: Optional[str] = Field(None, description="左边说话人音色参考音频（双人模式）")
    right_prompt_audio_path: Optional[str] = Field(None, description="右边说话人音色参考音频（双人模式）")
    enable_double_mode: bool = Field(default=False, description="是否启用双人模式")
    role_id: Optional[str] = Field(None, description="角色素材ID（选择角色时自动填充双人模式参数）")
    bgm_path: Optional[str] = Field(None, description="BGM 路径")
    use_llm_generate: bool = Field(default=False, description="是否使用 LLM 生成文案")
    enable_postprocess: bool = Field(default=True, description="是否启用后期处理")
    enable_denoise: bool = Field(default=True, description="是否开启降噪")
    denoise_strength: float = Field(default=0.7, ge=0.0, le=1.0, description="降噪强度")
    tts_speed: float = Field(default=1.0, ge=0.8, le=1.2, description="语速 (0.8-1.2)")
    tts_emo_weight: float = Field(default=0.8, ge=0.1, le=1.2, description="情感权重")
    left_tts_speed: Optional[float] = Field(None, ge=0.8, le=1.2, description="左说话人语速 (0.8-1.2)")
    right_tts_speed: Optional[float] = Field(None, ge=0.8, le=1.2, description="右说话人语速 (0.8-1.2)")
    left_tts_emo_weight: Optional[float] = Field(None, ge=0.1, le=1.2, description="左说话人情感权重")
    right_tts_emo_weight: Optional[float] = Field(None, ge=0.1, le=1.2, description="右说话人情感权重")
    enable_subtitle: bool = Field(default=True, description="是否添加字幕")
    enable_bgm: bool = Field(default=True, description="是否添加 BGM")
    bgm_volume: float = Field(default=0.3, ge=0.0, le=1.0, description="BGM 音量")
    enable_cover: bool = Field(default=False, description="是否生成封面")
    
    # 字幕样式配置
    subtitle_font: str = Field(default="SimHei", description="字幕字体")
    subtitle_size: int = Field(default=24, ge=10, le=72, description="字幕字号")
    subtitle_color: str = Field(default="white", description="字幕颜色")
    subtitle_stroke_color: str = Field(default="#000000", description="字幕描边颜色")
    subtitle_stroke_width: float = Field(default=1.0, ge=0.0, le=10.0, description="字幕描边宽度")
    subtitle_position: str = Field(default="bottom", description="字幕位置")
    subtitle_background_alpha: float = Field(default=0.0, ge=0.0, le=1.0, description="字幕背景透明度")
    subtitle_line_spacing: float = Field(default=1.5, ge=1.0, le=3.0, description="字幕行间距")
    
    # HeyGem 配置
    heygem_steps: int = Field(default=16, ge=4, le=32, description="推理步数")
    heygem_batch_size: int = Field(default=4, ge=1, le=16, description="推理批次大小")

    # 转场效果配置
    enable_transition: bool = Field(default=False, description="是否启用转场效果")
    transition_type: str = Field(default="淡入淡出", description="转场分类")
    transition_effect: str = Field(default="fade", description="转场效果名称")
    transition_random: bool = Field(default=False, description="是否启用随机效果")
    transition_random_all: bool = Field(default=False, description="是否每次转场都随机")
    transition_duration: float = Field(default=0.5, ge=0.5, le=5.0, description="转场时长（秒）")

    # 兼容旧接口的视频素材（简单路径格式）
    opening_video: Optional[str] = Field(None, description="开场视频路径（兼容）")
    loop_videos: List[str] = Field(default_factory=list, description="循环视频列表（兼容）")
    scene_videos: List[str] = Field(default_factory=list, description="场景视频列表（兼容）")
    ending_video: Optional[str] = Field(None, description="结束视频路径（兼容）")
    
    # 新接口的带标签视频素材
    opening_video_with_tags: Optional[VideoWithTag] = Field(None, description="开场视频（带标签）")
    loop_videos_with_tags: List[VideoWithTag] = Field(default_factory=list, description="循环视频列表（带标签）")
    scene_videos_with_tags: List[VideoWithTag] = Field(default_factory=list, description="场景视频列表（带标签）")
    ending_video_with_tags: Optional[VideoWithTag] = Field(None, description="结束视频（带标签）")

    # 标签组 ID
    scene_tag_group_id: Optional[int] = Field(None, description="场景标签组 ID")

    # 画外音配置
    enable_pip: bool = Field(default=False, description="是否启用画外音功能")
    pip_video_path: Optional[str] = Field(None, description="画外音视频路径（单人模式）")
    pip_left_video_path: Optional[str] = Field(None, description="画外音左边视频路径（双人模式）")
    pip_right_video_path: Optional[str] = Field(None, description="画外音右边视频路径（双人模式）")

    @model_validator(mode='after')
    def validate_paths(self):
        """验证所有文件路径的安全性"""
        from core.paths import validate_path_in_allowed_dirs

        # 所有路径都是可选的，只检查安全性，不强制检查文件存在
        # 文件存在性检查在后续业务逻辑中处理
        optional_paths = [
            ('source_video_path', self.source_video_path, False),
            ('prompt_audio_path', self.prompt_audio_path, False),
            ('left_prompt_audio_path', self.left_prompt_audio_path, False),
            ('right_prompt_audio_path', self.right_prompt_audio_path, False),
            ('bgm_path', self.bgm_path, False),
            ('opening_video', self.opening_video, False),
            ('ending_video', self.ending_video, False),
            # 画外音路径
            ('pip_video_path', self.pip_video_path, False),
            ('pip_left_video_path', self.pip_left_video_path, False),
            ('pip_right_video_path', self.pip_right_video_path, False),
        ]

        # 验证可选路径
        for field_name, path, check_exists in optional_paths:
            if path:
                valid, result = validate_path_in_allowed_dirs(path, check_exists=check_exists)
                if not valid:
                    raise ValueError(f"{field_name}: {result}")

        # 验证列表路径
        for path in self.loop_videos:
            if path:
                valid, result = validate_path_in_allowed_dirs(path, check_exists=False)
                if not valid:
                    raise ValueError(f"loop_videos: {result}")

        for path in self.scene_videos:
            if path:
                valid, result = validate_path_in_allowed_dirs(path, check_exists=False)
                if not valid:
                    raise ValueError(f"scene_videos: {result}")

        # 验证带标签的视频路径
        for video in self.loop_videos_with_tags:
            if video.file_path:
                valid, result = validate_path_in_allowed_dirs(video.file_path, check_exists=False)
                if not valid:
                    raise ValueError(f"loop_videos_with_tags: {result}")

        for video in self.scene_videos_with_tags:
            if video.file_path:
                valid, result = validate_path_in_allowed_dirs(video.file_path, check_exists=False)
                if not valid:
                    raise ValueError(f"scene_videos_with_tags: {result}")

        if self.opening_video_with_tags and self.opening_video_with_tags.file_path:
            valid, result = validate_path_in_allowed_dirs(self.opening_video_with_tags.file_path, check_exists=False)
            if not valid:
                raise ValueError(f"opening_video_with_tags: {result}")

        if self.ending_video_with_tags and self.ending_video_with_tags.file_path:
            valid, result = validate_path_in_allowed_dirs(self.ending_video_with_tags.file_path, check_exists=False)
            if not valid:
                raise ValueError(f"ending_video_with_tags: {result}")

        return self


class TaskUpdateRequest(BaseModel):
    """更新任务请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=200, description="任务名称")
    script_text: Optional[str] = Field(None, description="文案文本")
    status: Optional[TaskStatus] = Field(None, description="任务状态")


class TaskControlRequest(BaseModel):
    """任务控制请求"""
    action: str = Field(..., description="操作类型: pause, resume, cancel, retry")


class TaskListResponse(BaseModel):
    """任务列表响应"""
    items: List[TaskResponse] = Field(..., description="任务列表")
    total: int = Field(..., description="总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")


class TaskStatusUpdate(BaseModel):
    """任务状态更新（WebSocket）"""
    task_id: str = Field(..., description="任务ID")
    status: TaskStatus = Field(..., description="任务状态")
    stage: TaskStage = Field(..., description="当前阶段")
    progress: float = Field(..., ge=0.0, le=100.0, description="进度百分比 (0-100)")
    message: Optional[str] = Field(None, description="状态消息")
    output_path: Optional[str] = Field(None, description="输出路径")
    error_message: Optional[str] = Field(None, description="错误信息")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")


# ============== 素材相关模型 ==============

class MaterialType(str, Enum):
    """素材类型枚举"""
    ROLE = "role"
    BGM = "bgm"
    VIDEO = "video"
    SCENE = "scene"
    AUDIO = "audio"


class VideoItem(BaseModel):
    """视频项模型"""
    model_config = ConfigDict(from_attributes=True)
    
    file_path: str = Field(..., description="文件路径")
    duration: float = Field(default=0.0, description="时长")
    thumbnail: Optional[str] = Field(None, description="缩略图路径")


class RoleMaterial(BaseModel):
    """角色素材模型"""
    model_config = ConfigDict(from_attributes=True)
    
    role_id: str = Field(..., description="角色ID")
    role_name: str = Field(..., description="角色名称")
    cover_url: Optional[str] = Field(None, description="封面URL")
    opening: List[VideoItem] = Field(default=[], description="开场视频列表")
    loop: List[VideoItem] = Field(default=[], description="循环视频列表")
    scene: List[VideoItem] = Field(default=[], description="场景视频列表")
    ending: List[VideoItem] = Field(default=[], description="结束视频列表")
    face_config: Optional[Dict[str, Any]] = Field(None, description="面部配置")
    audio_list: List[Dict[str, Any]] = Field(default=[], description="音频列表")
    use_count: int = Field(default=0, description="使用次数")
    remark: Optional[str] = Field(None, description="备注")
    permission: str = Field(default="private", description="权限")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")


class BgmMaterial(BaseModel):
    """BGM 素材模型"""
    model_config = ConfigDict(from_attributes=True)
    
    bgm_id: str = Field(..., description="BGM ID")
    bgm_name: str = Field(..., description="BGM 名称")
    file_path: str = Field(..., description="文件路径")
    duration: float = Field(default=0.0, description="时长")
    emotion_tags: List[str] = Field(default=[], description="情绪标签")
    scene_tags: List[str] = Field(default=[], description="场景标签")
    copyright_type: str = Field(default="free", description="版权类型")
    is_deleted: bool = Field(default=False, description="是否已删除")
    created_at: datetime = Field(..., description="创建时间")


class SceneMaterial(BaseModel):
    """场景/产品素材模型"""
    model_config = ConfigDict(from_attributes=True)
    
    scene_id: str = Field(..., description="场景ID")
    scene_name: str = Field(..., description="场景名称")
    video_list: List[VideoItem] = Field(default=[], description="视频列表")
    use_count: int = Field(default=0, description="使用次数")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")


class ReferenceAudio(BaseModel):
    """参考音频素材模型"""
    model_config = ConfigDict(from_attributes=True)
    
    audio_id: str = Field(..., description="音频ID")
    audio_name: str = Field(..., description="音频名称")
    file_path: str = Field(..., description="文件路径")
    emotion_tag: Optional[str] = Field(None, description="情绪标签")
    duration: float = Field(default=0.0, description="时长")
    use_count: int = Field(default=0, description="使用次数")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")


class Tag(BaseModel):
    """标签模型"""
    model_config = ConfigDict(from_attributes=True)
    
    tag_id: str = Field(..., description="标签ID")
    tag_name: str = Field(..., description="标签名称")
    tag_type: str = Field(..., description="标签类型: emotion, scene")
    sort: int = Field(default=0, description="排序")
    created_at: datetime = Field(..., description="创建时间")


# ============== 响应模型 ==============

class ApiResponse(BaseModel):
    """通用 API 响应"""
    code: int = Field(default=200, description="状态码")
    message: str = Field(default="success", description="消息")
    data: Optional[Any] = Field(None, description="数据")


class PaginatedResponse(ApiResponse):
    """分页响应"""
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页数量")


# ============== 系统相关模型 ==============

class SystemStatus(BaseModel):
    """系统状态"""
    model_config = ConfigDict(from_attributes=True)
    
    status: str = Field(..., description="系统状态")
    version: str = Field(..., description="系统版本")
    uptime: float = Field(..., description="运行时间（秒）")
    tasks: Dict[str, int] = Field(..., description="任务统计")
    services: Dict[str, bool] = Field(..., description="服务状态")


class ServiceConfig(BaseModel):
    """服务配置"""
    model_config = ConfigDict(from_attributes=True)
    
    tts_host: str = Field(..., description="TTS 服务地址")
    heygem_host: str = Field(..., description="HeyGem 服务地址")
    llm_provider: str = Field(..., description="LLM 提供商")
    llm_model: Optional[str] = Field(None, description="LLM 模型")
    max_concurrent_tasks: int = Field(default=3, description="最大并发任务数")


__all__ = [
    # 任务相关
    "TaskStatus",
    "TaskStage", 
    "ScriptSegment",
    "TaskConfig",
    "TaskBase",
    "TaskResponse",
    "TaskCreateRequest",
    "TaskUpdateRequest",
    "TaskControlRequest",
    "TaskListResponse",
    "TaskStatusUpdate",
    # 素材相关
    "MaterialType",
    "VideoItem",
    "RoleMaterial",
    "BgmMaterial",
    "SceneMaterial",
    "ReferenceAudio",
    "Tag",
    # 响应模型
    "ApiResponse",
    "PaginatedResponse",
    # 系统相关
    "SystemStatus",
    "ServiceConfig",
]
