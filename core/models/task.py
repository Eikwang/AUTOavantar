"""
任务数据模型
定义任务相关的实体类
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime
import uuid


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"           # 等待中
    PREPROCESSING = "preprocessing"  # 预处理中
    SCRIPT_GENERATING = "script_generating"  # 文案生成中
    TTS_SYNTHESIZING = "tts_synthesizing"  # TTS合成中
    HEYGEM_GENERATING = "heygem_generating"  # HeyGem生成中
    POST_PROCESSING = "post_processing"  # 后期处理中
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"            # 失败


class SceneType(Enum):
    """视频场景类型"""
    OPENING = "开场"     # 开场
    LOOP = "循环"       # 循环
    SCENE = "场景"      # 场景
    ENDING = "结束"     # 结束


class EmotionType(Enum):
    """情绪类型"""
    JOY = "喜"          # 高兴
    ANGER = "怒"        # 生气
    SADNESS = "哀"      # 伤心
    FEAR = "惧"         # 害怕
    DISGUST = "厌恶"    # 厌恶
    DEPRESSION = "低落"  # 低落
    SURPRISE = "惊喜"   # 惊喜
    CALM = "平静"       # 平静


class RoleSourceType(Enum):
    """角色来源类型"""
    UPLOAD = "upload"     # 上传
    MATERIAL = "material" # 素材库


class AudioSourceType(Enum):
    """音频来源类型"""
    UPLOAD = "upload"    # 上传
    EXTRACT = "extract"  # 提取
    MATERIAL = "material" # 素材库


class VideoGroupType(Enum):
    """视频分组类型"""
    OPENING = "opening"  # 开场
    LOOP = "loop"        # 循环
    SCENE = "scene"      # 场景
    ENDING = "ending"    # 结束


class ResolutionPreset(Enum):
    """分辨率预设"""
    ORIGINAL = "original"      # 原始分辨率
    HD_720P = "720p"           # 720P高清
    FHD_1080P = "1080p"        # 1080P全高清
    QHD_2K = "2k"              # 2K超高清
    UHD_4K = "4k"              # 4K超高清
    CUSTOM = "custom"          # 自定义


class AspectRatioType(Enum):
    """画面比例"""
    RATIO_9_16 = "9:16"        # 竖屏9:16
    RATIO_16_9 = "16:9"        # 横屏16:9
    RATIO_1_1 = "1:1"          # 方形1:1
    RATIO_4_3 = "4:3"          # 经典4:3
    RATIO_21_9 = "21:9"        # 宽屏21:9


class TransitionEffect(Enum):
    """转场效果"""
    NONE = "none"              # 无
    FADE = "fade"              # 淡入淡出
    SLIDE = "slide"            # 滑动
    ZOOM = "zoom"              # 缩放
    DISSOLVE = "dissolve"      # 溶解
    WIPE = "wipe"              # 擦除
    BLUR = "blur"              # 模糊


class SubtitlePosition(Enum):
    """字幕位置"""
    TOP = "top"                # 顶部
    CENTER = "center"          # 居中
    BOTTOM = "bottom"          # 底部


@dataclass
class VideoWithTag:
    """带标签的视频素材"""
    file_path: str
    emotion_tags: List[str] = field(default_factory=list)
    scene_tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "emotion_tags": self.emotion_tags,
            "scene_tags": self.scene_tags
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoWithTag":
        return cls(
            file_path=data.get("file_path", ""),
            emotion_tags=data.get("emotion_tags", []),
            scene_tags=data.get("scene_tags", [])
        )


@dataclass
class ScriptSegment:
    """文案段落"""
    segment_id: str
    text: str
    scene_type: SceneType
    emotion: EmotionType = EmotionType.CALM
    tone: str = "平静"
    emotion_weight: float = 0.3
    tone_weight: float = 0.2
    audio_path: Optional[str] = None
    video_path: Optional[str] = None
    output_path: Optional[str] = None
    duration: float = 0.0
    status: str = "pending"  # pending, processing, completed, failed
    error_message: Optional[str] = None
    audio_duration: float = 0.0
    speaker: str = ""  # 说话人标识，"left" 或 "right"（双人模式）
    emotion_params: Dict[str, float] = field(default_factory=dict)  # 情绪向量参数 vec1-vec8
    is_scene_label: bool = False  # 是否为场景标签（场景标签不需要情绪参数）
    pending_speaker_video: Optional[str] = None  # 画外音说话人视频路径
    scene_video_path: Optional[str] = None  # 画外音场景视频路径
    need_pip_overlay: bool = False  # 是否需要画外音叠加


@dataclass
class VideoAsset:
    """视频素材"""
    asset_id: str
    name: str
    file_path: str
    scene_type: SceneType
    emotion_tags: List[str] = field(default_factory=list)
    duration: float = 0.0
    thumbnail_path: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoleInfo:
    """角色信息"""
    role_source: RoleSourceType = RoleSourceType.UPLOAD
    role_id: Optional[str] = None
    video_group: VideoGroupType = VideoGroupType.SCENE
    source_video_path: Optional[str] = None
    face_image_path: Optional[str] = None
    character_name: Optional[str] = None


@dataclass
class AudioInfo:
    """音频信息"""
    audio_source: AudioSourceType = AudioSourceType.UPLOAD
    audio_file_path: Optional[str] = None
    denoise_config: Optional[Dict[str, Any]] = None
    speed: float = 1.0
    emotion_weight: float = 0.8
    volume: float = 1.0
    pitch: float = 0.0


@dataclass
class CopywritingInfo:
    """文案信息"""
    content: str = ""
    emotion_tags: List[str] = field(default_factory=list)
    generate_config: Optional[Dict[str, Any]] = None
    source: str = "manual"


@dataclass
class BGMConfig:
    """BGM配置"""
    enable: bool = True
    volume: float = 0.3
    fade_in: float = 0.0
    fade_out: float = 0.0
    voice_avoidance: bool = True
    voice_avoidance_threshold: float = 0.5
    loop_mode: bool = True


@dataclass
class SubtitleStyleConfig:
    """字幕样式配置"""
    font: str = "SimHei"
    font_size: int = 24
    color: str = "#FFFFFF"
    position: SubtitlePosition = SubtitlePosition.BOTTOM
    stroke_color: str = "#000000"
    stroke_width: float = 1.0
    background_alpha: float = 0.0
    line_spacing: float = 1.5


@dataclass
class VideoAdvanceConfig:
    """视频进阶配置"""
    frame_rate: int = 30
    bit_rate: str = "high"
    aspect_ratio: AspectRatioType = AspectRatioType.RATIO_9_16
    transition: TransitionEffect = TransitionEffect.NONE
    transition_duration: float = 0.5


@dataclass
class PostProcessConfig:
    """后处理配置"""
    bgm_config: BGMConfig = field(default_factory=BGMConfig)
    subtitle_config: SubtitleStyleConfig = field(default_factory=SubtitleStyleConfig)
    video_config: VideoAdvanceConfig = field(default_factory=VideoAdvanceConfig)


@dataclass
class StepProgress:
    """步骤进度"""
    step_name: str = ""
    progress: float = 0.0
    status: str = "pending"
    message: Optional[str] = None


@dataclass
class RuntimeInfo:
    """运行时信息"""
    current_step: str = ""
    total_progress: float = 0.0
    step_progresses: List[StepProgress] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0


@dataclass
class ResultInfo:
    """结果信息"""
    video_url: Optional[str] = None
    file_path: Optional[str] = None
    file_size: int = 0
    duration: float = 0.0
    resolution: Optional[str] = None
    download_url: Optional[str] = None
    thumbnail_url: Optional[str] = None


@dataclass
class ArchiveInfo:
    """归档信息"""
    is_archived: bool = False
    archive_time: Optional[datetime] = None
    archive_path: Optional[str] = None


@dataclass
class Task:
    """任务实体"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    title: str = ""  # 兼容数据库字段
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 1  # 1=低, 2=中, 3=高

    # 输入
    source_video_path: str = ""           # 源视频路径
    script_text: str = ""                # 文案文本
    prompt_audio_path: str = ""          # 音色参考音频（单人模式）
    left_prompt_audio_path: str = ""      # 左边说话人音色参考音频（双人模式）
    right_prompt_audio_path: str = ""     # 右边说话人音色参考音频（双人模式）

    # 素材（兼容旧接口 - 简单路径格式）
    opening_video: Optional[str] = None   # 开场视频（兼容）
    loop_videos: List[str] = field(default_factory=list)    # 循环视频列表（兼容）
    scene_videos: List[str] = field(default_factory=list)   # 场景视频列表（兼容）
    ending_video: Optional[str] = None   # 结束视频（兼容）
    
    # 素材（新接口 - 带标签格式）
    opening_video_with_tags: Optional[VideoWithTag] = None   # 开场视频（带标签）
    loop_videos_with_tags: List[VideoWithTag] = field(default_factory=list)    # 循环视频列表（带标签）
    scene_videos_with_tags: List[VideoWithTag] = field(default_factory=list)   # 场景视频列表（带标签）
    ending_video_with_tags: Optional[VideoWithTag] = None   # 结束视频（带标签）
    
    bgm_path: Optional[str] = None        # BGM路径

    # 输出
    segments: List[ScriptSegment] = field(default_factory=list)
    output_path: Optional[str] = None  # 兼容数据库字段
    output_video_path: Optional[str] = None
    output_audio_path: Optional[str] = None
    
    # 双人模式合并后的音频
    left_merged_audio_path: Optional[str] = None
    right_merged_audio_path: Optional[str] = None
    
    # 双人模式视频合成结果
    left_video_path: Optional[str] = None
    right_video_path: Optional[str] = None
    final_video_path: Optional[str] = None  # 双人模式最终合并视频

    # 画外音配置
    enable_pip: bool = False
    pip_video_path: Optional[str] = None
    pip_left_video_path: Optional[str] = None
    pip_right_video_path: Optional[str] = None
    pip_result_path: Optional[str] = None  # 画外音合成结果路径
    pip_speaker_videos: Optional[Dict[str, Dict[str, str]]] = None  # 画外音说话人视频路径，key=标签，value={left/right/scene: path}
    scene_pip_left_video: Optional[str] = None  # 场景画外音左说话人视频
    scene_pip_right_video: Optional[str] = None  # 场景画外音右说话人视频
    scene_pip_processed: Optional[Any] = None  # 已处理画外音场景标签集合

    # 元数据
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # 错误信息
    error_message: Optional[str] = None
    error_stage: Optional[str] = None

    # 进度
    progress: float = 0.0
    current_stage: str = ""

    # 角色信息
    role_info: Optional[RoleInfo] = None

    # 音频信息
    audio_info: Optional[AudioInfo] = None

    # 文案信息
    copywriting_info: Optional[CopywritingInfo] = None

    # 后处理配置
    post_process_config: Optional[PostProcessConfig] = None

    # 运行时信息
    runtime_info: Optional[RuntimeInfo] = None

    # 结果信息
    result_info: Optional[ResultInfo] = None

    # 归档信息
    archive_info: Optional[ArchiveInfo] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status.value,
            "priority": self.priority,
            "source_video_path": self.source_video_path,
            "script_text": self.script_text,
            "prompt_audio_path": self.prompt_audio_path,
            "left_prompt_audio_path": self.left_prompt_audio_path,
            "right_prompt_audio_path": self.right_prompt_audio_path,
            "progress": self.progress,
            "current_stage": self.current_stage,
            "error_message": self.error_message,
            "output_path": self.output_path,
            "output_video_path": self.output_video_path,
            "output_audio_path": self.output_audio_path,
            "left_merged_audio_path": self.left_merged_audio_path,
            "right_merged_audio_path": self.right_merged_audio_path,
            "left_video_path": self.left_video_path,
            "right_video_path": self.right_video_path,
            "final_video_path": self.final_video_path,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            # 兼容旧接口的视频素材
            "opening_video": self.opening_video,
            "loop_videos": self.loop_videos,
            "scene_videos": self.scene_videos,
            "ending_video": self.ending_video,
            # 新接口的带标签视频素材
            "opening_video_with_tags": self.opening_video_with_tags.to_dict() if self.opening_video_with_tags else None,
            "loop_videos_with_tags": [v.to_dict() for v in self.loop_videos_with_tags],
            "scene_videos_with_tags": [v.to_dict() for v in self.scene_videos_with_tags],
            "ending_video_with_tags": self.ending_video_with_tags.to_dict() if self.ending_video_with_tags else None
        }

        if self.role_info:
            result["role_info"] = {
                "role_source": self.role_info.role_source.value,
                "role_id": self.role_info.role_id,
                "video_group": self.role_info.video_group.value,
                "source_video_path": self.role_info.source_video_path,
                "face_image_path": self.role_info.face_image_path,
                "character_name": self.role_info.character_name
            }

        if self.audio_info:
            result["audio_info"] = {
                "audio_source": self.audio_info.audio_source.value,
                "audio_file_path": self.audio_info.audio_file_path,
                "denoise_config": self.audio_info.denoise_config,
                "speed": self.audio_info.speed,
                "emotion_weight": self.audio_info.emotion_weight,
                "volume": self.audio_info.volume,
                "pitch": self.audio_info.pitch
            }

        if self.copywriting_info:
            result["copywriting_info"] = {
                "content": self.copywriting_info.content,
                "emotion_tags": self.copywriting_info.emotion_tags,
                "generate_config": self.copywriting_info.generate_config,
                "source": self.copywriting_info.source
            }

        if self.post_process_config:
            result["post_process_config"] = {
                "bgm_config": {
                    "enable": self.post_process_config.bgm_config.enable,
                    "volume": self.post_process_config.bgm_config.volume,
                    "fade_in": self.post_process_config.bgm_config.fade_in,
                    "fade_out": self.post_process_config.bgm_config.fade_out,
                    "voice_avoidance": self.post_process_config.bgm_config.voice_avoidance,
                    "voice_avoidance_threshold": self.post_process_config.bgm_config.voice_avoidance_threshold,
                    "loop_mode": self.post_process_config.bgm_config.loop_mode
                },
                "subtitle_config": {
                    "font": self.post_process_config.subtitle_config.font,
                    "font_size": self.post_process_config.subtitle_config.font_size,
                    "color": self.post_process_config.subtitle_config.color,
                    "position": self.post_process_config.subtitle_config.position.value,
                    "stroke_color": self.post_process_config.subtitle_config.stroke_color,
                    "stroke_width": self.post_process_config.subtitle_config.stroke_width,
                    "background_alpha": self.post_process_config.subtitle_config.background_alpha,
                    "line_spacing": self.post_process_config.subtitle_config.line_spacing
                },
                "video_config": {
                    "frame_rate": self.post_process_config.video_config.frame_rate,
                    "bit_rate": self.post_process_config.video_config.bit_rate,
                    "aspect_ratio": self.post_process_config.video_config.aspect_ratio.value,
                    "transition": self.post_process_config.video_config.transition.value,
                    "transition_duration": self.post_process_config.video_config.transition_duration
                }
            }

        if self.runtime_info:
            result["runtime_info"] = {
                "current_step": self.runtime_info.current_step,
                "total_progress": self.runtime_info.total_progress,
                "step_progresses": [
                    {
                        "step_name": sp.step_name,
                        "progress": sp.progress,
                        "status": sp.status,
                        "message": sp.message
                    }
                    for sp in self.runtime_info.step_progresses
                ],
                "start_time": self.runtime_info.start_time.isoformat() if self.runtime_info.start_time else None,
                "end_time": self.runtime_info.end_time.isoformat() if self.runtime_info.end_time else None,
                "duration_seconds": self.runtime_info.duration_seconds
            }

        if self.result_info:
            result["result_info"] = {
                "video_url": self.result_info.video_url,
                "file_path": self.result_info.file_path,
                "file_size": self.result_info.file_size,
                "duration": self.result_info.duration,
                "resolution": self.result_info.resolution,
                "download_url": self.result_info.download_url,
                "thumbnail_url": self.result_info.thumbnail_url
            }

        if self.archive_info:
            result["archive_info"] = {
                "is_archived": self.archive_info.is_archived,
                "archive_time": self.archive_info.archive_time.isoformat() if self.archive_info.archive_time else None,
                "archive_path": self.archive_info.archive_path
            }

        return result


@dataclass
class TaskConfig:
    """任务配置"""
    # TTS配置
    tts_speed: float = 1.0
    tts_emo_weight: float = 0.8
    left_tts_speed: Optional[float] = None
    right_tts_speed: Optional[float] = None
    left_tts_emo_weight: Optional[float] = None
    right_tts_emo_weight: Optional[float] = None

    # HeyGem配置
    heygem_steps: float = 16
    heygem_ifface: bool = True
    heygem_if_gfpgan: bool = False

    # 后期处理配置
    enable_subtitle: bool = True
    subtitle_font: str = "SimHei"
    subtitle_size: int = 24
    subtitle_color: str = "white"

    enable_bgm: bool = True
    bgm_volume: float = 0.3

    enable_cover: bool = False
    cover_prompt_template: str = "根据文案{summary}生成视频封面，风格简洁，突出主题"

    # 输出配置
    output_format: str = "mp4"
    output_quality: str = "high"  # low, medium, high

    # 推理批次设置
    inference_batch_size: int = 8
    max_batch_size: int = 32
    min_batch_size: int = 4

    # 分辨率配置
    use_original_resolution: bool = True
    custom_width: Optional[int] = None
    custom_height: Optional[int] = None
    resolution_preset: ResolutionPreset = ResolutionPreset.ORIGINAL

    # 降噪强度配置
    denoise_strength: float = 0.5
    enable_denoise: bool = False

    # BGM精细化配置
    bgm_fade_in: float = 0.0
    bgm_fade_out: float = 0.0
    bgm_voice_avoidance: bool = True
    bgm_voice_avoidance_threshold: float = 0.5
    bgm_loop: bool = True

    # 字幕样式配置
    subtitle_stroke_color: str = "#000000"
    subtitle_stroke_width: float = 1.0
    subtitle_position: SubtitlePosition = SubtitlePosition.BOTTOM
    subtitle_background_alpha: float = 0.0
    subtitle_line_spacing: float = 1.5

    # 视频进阶配置
    video_frame_rate: int = 30
    video_bit_rate: str = "high"
    video_aspect_ratio: AspectRatioType = AspectRatioType.RATIO_9_16

    # 转场效果配置
    enable_transition: bool = False
    transition_type: str = "淡入淡出"  # 淡入淡出/滑动擦除/图形变换/特效切片
    transition_effect: str = "fade"  # FFmpeg xfade 效果名称
    transition_random: bool = False
    transition_random_all: bool = False
    transition_duration: float = 0.5

    # 双人模式配置
    enable_double_mode: bool = False
    
    def __init__(
        self,
        tts_speed: float = 1.0,
        tts_emo_weight: float = 0.8,
        left_tts_speed: Optional[float] = None,
        right_tts_speed: Optional[float] = None,
        left_tts_emo_weight: Optional[float] = None,
        right_tts_emo_weight: Optional[float] = None,
        heygem_steps: float = 16,
        heygem_ifface: bool = True,
        heygem_if_gfpgan: bool = False,
        enable_subtitle: bool = True,
        subtitle_font: str = "SimHei",
        subtitle_size: int = 24,
        subtitle_color: str = "white",
        enable_bgm: bool = True,
        bgm_volume: float = 0.3,
        enable_cover: bool = False,
        cover_prompt_template: str = "根据文案{summary}生成视频封面，风格简洁，突出主题",
        output_format: str = "mp4",
        output_quality: str = "high",
        inference_batch_size: int = 8,
        max_batch_size: int = 32,
        min_batch_size: int = 4,
        use_original_resolution: bool = True,
        custom_width: Optional[int] = None,
        custom_height: Optional[int] = None,
        resolution_preset: ResolutionPreset = ResolutionPreset.ORIGINAL,
        denoise_strength: float = 0.5,
        enable_denoise: bool = False,
        bgm_fade_in: float = 0.0,
        bgm_fade_out: float = 0.0,
        bgm_voice_avoidance: bool = True,
        bgm_voice_avoidance_threshold: float = 0.5,
        bgm_loop: bool = True,
        subtitle_stroke_color: str = "#000000",
        subtitle_stroke_width: float = 1.0,
        subtitle_position: SubtitlePosition = SubtitlePosition.BOTTOM,
        subtitle_background_alpha: float = 0.0,
        subtitle_line_spacing: float = 1.5,
        video_frame_rate: int = 30,
        video_bit_rate: str = "high",
        video_aspect_ratio: AspectRatioType = AspectRatioType.RATIO_9_16,
        enable_transition: bool = False,
        transition_type: str = "淡入淡出",
        transition_effect: str = "fade",
        transition_random: bool = False,
        transition_random_all: bool = False,
        transition_duration: float = 0.5,
        enable_double_mode: bool = False,
        enable_pip: bool = False,
        pip_video_path: Optional[str] = None,
        pip_left_video_path: Optional[str] = None,
        pip_right_video_path: Optional[str] = None,
        **kwargs
    ):
        self.tts_speed = tts_speed
        self.tts_emo_weight = tts_emo_weight
        self.left_tts_speed = left_tts_speed
        self.right_tts_speed = right_tts_speed
        self.left_tts_emo_weight = left_tts_emo_weight
        self.right_tts_emo_weight = right_tts_emo_weight
        self.heygem_steps = heygem_steps
        self.heygem_ifface = heygem_ifface
        self.heygem_if_gfpgan = heygem_if_gfpgan
        self.enable_subtitle = enable_subtitle
        self.subtitle_font = subtitle_font
        self.subtitle_size = subtitle_size
        self.subtitle_color = subtitle_color
        self.enable_bgm = enable_bgm
        self.bgm_volume = bgm_volume
        self.enable_cover = enable_cover
        self.cover_prompt_template = cover_prompt_template
        self.output_format = output_format
        self.output_quality = output_quality
        self.inference_batch_size = inference_batch_size
        self.max_batch_size = max_batch_size
        self.min_batch_size = min_batch_size
        self.use_original_resolution = use_original_resolution
        self.custom_width = custom_width
        self.custom_height = custom_height
        self.resolution_preset = resolution_preset
        self.denoise_strength = denoise_strength
        self.enable_denoise = enable_denoise
        self.bgm_fade_in = bgm_fade_in
        self.bgm_fade_out = bgm_fade_out
        self.bgm_voice_avoidance = bgm_voice_avoidance
        self.bgm_voice_avoidance_threshold = bgm_voice_avoidance_threshold
        self.bgm_loop = bgm_loop
        self.subtitle_stroke_color = subtitle_stroke_color
        self.subtitle_stroke_width = subtitle_stroke_width
        
        if isinstance(subtitle_position, str):
            self.subtitle_position = SubtitlePosition(subtitle_position)
        else:
            self.subtitle_position = subtitle_position
            
        self.subtitle_background_alpha = subtitle_background_alpha
        self.subtitle_line_spacing = subtitle_line_spacing
        self.video_frame_rate = video_frame_rate
        self.video_bit_rate = video_bit_rate
        self.video_aspect_ratio = video_aspect_ratio
        self.enable_transition = enable_transition
        self.transition_type = transition_type
        self.transition_effect = transition_effect
        self.transition_random = transition_random
        self.transition_random_all = transition_random_all
        self.transition_duration = transition_duration
        self.enable_double_mode = enable_double_mode
        self.enable_pip = enable_pip
        self.pip_video_path = pip_video_path
        self.pip_left_video_path = pip_left_video_path
        self.pip_right_video_path = pip_right_video_path

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tts_speed": self.tts_speed,
            "tts_emo_weight": self.tts_emo_weight,
            "left_tts_speed": self.left_tts_speed,
            "right_tts_speed": self.right_tts_speed,
            "left_tts_emo_weight": self.left_tts_emo_weight,
            "right_tts_emo_weight": self.right_tts_emo_weight,
            "heygem_steps": self.heygem_steps,
            "heygem_ifface": self.heygem_ifface,
            "heygem_if_gfpgan": self.heygem_if_gfpgan,
            "enable_subtitle": self.enable_subtitle,
            "subtitle_font": self.subtitle_font,
            "subtitle_size": self.subtitle_size,
            "subtitle_color": self.subtitle_color,
            "enable_bgm": self.enable_bgm,
            "bgm_volume": self.bgm_volume,
            "enable_cover": self.enable_cover,
            "output_format": self.output_format,
            "output_quality": self.output_quality,
            "inference_batch_size": self.inference_batch_size,
            "max_batch_size": self.max_batch_size,
            "min_batch_size": self.min_batch_size,
            "use_original_resolution": self.use_original_resolution,
            "custom_width": self.custom_width,
            "custom_height": self.custom_height,
            "resolution_preset": self.resolution_preset.value,
            "denoise_strength": self.denoise_strength,
            "enable_denoise": self.enable_denoise,
            "bgm_fade_in": self.bgm_fade_in,
            "bgm_fade_out": self.bgm_fade_out,
            "bgm_voice_avoidance": self.bgm_voice_avoidance,
            "bgm_voice_avoidance_threshold": self.bgm_voice_avoidance_threshold,
            "bgm_loop": self.bgm_loop,
            "subtitle_stroke_color": self.subtitle_stroke_color,
            "subtitle_stroke_width": self.subtitle_stroke_width,
            "subtitle_position": self.subtitle_position.value,
            "subtitle_background_alpha": self.subtitle_background_alpha,
            "subtitle_line_spacing": self.subtitle_line_spacing,
            "video_frame_rate": self.video_frame_rate,
            "video_bit_rate": self.video_bit_rate,
            "video_aspect_ratio": self.video_aspect_ratio.value,
            "enable_transition": self.enable_transition,
            "transition_type": self.transition_type,
            "transition_effect": self.transition_effect,
            "transition_random": self.transition_random,
            "transition_random_all": self.transition_random_all,
            "transition_duration": self.transition_duration,
            "enable_double_mode": self.enable_double_mode,
            "enable_pip": self.enable_pip,
            "pip_video_path": self.pip_video_path,
            "pip_left_video_path": self.pip_left_video_path,
            "pip_right_video_path": self.pip_right_video_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskConfig":
        """从字典创建配置"""
        config = cls()
        config.tts_speed = data.get("tts_speed", 1.0)
        config.tts_emo_weight = data.get("tts_emo_weight", 0.8)
        config.left_tts_speed = data.get("left_tts_speed")
        config.right_tts_speed = data.get("right_tts_speed")
        config.left_tts_emo_weight = data.get("left_tts_emo_weight")
        config.right_tts_emo_weight = data.get("right_tts_emo_weight")
        config.heygem_steps = data.get("heygem_steps", 16)
        config.heygem_ifface = data.get("heygem_ifface", True)
        config.heygem_if_gfpgan = data.get("heygem_if_gfpgan", False)
        config.enable_subtitle = data.get("enable_subtitle", True)
        config.subtitle_font = data.get("subtitle_font", "SimHei")
        config.subtitle_size = data.get("subtitle_size", 24)
        config.subtitle_color = data.get("subtitle_color", "white")
        config.enable_bgm = data.get("enable_bgm", True)
        config.bgm_volume = data.get("bgm_volume", 0.3)
        config.enable_cover = data.get("enable_cover", False)
        config.output_format = data.get("output_format", "mp4")
        config.output_quality = data.get("output_quality", "high")
        config.inference_batch_size = data.get("inference_batch_size", 8)
        config.max_batch_size = data.get("max_batch_size", 32)
        config.min_batch_size = data.get("min_batch_size", 4)
        config.use_original_resolution = data.get("use_original_resolution", True)
        config.custom_width = data.get("custom_width")
        config.custom_height = data.get("custom_height")
        resolution_preset = data.get("resolution_preset", "original")
        config.resolution_preset = ResolutionPreset(resolution_preset) if resolution_preset else ResolutionPreset.ORIGINAL
        config.denoise_strength = data.get("denoise_strength", 0.5)
        config.enable_denoise = data.get("enable_denoise", False)
        config.bgm_fade_in = data.get("bgm_fade_in", 0.0)
        config.bgm_fade_out = data.get("bgm_fade_out", 0.0)
        config.bgm_voice_avoidance = data.get("bgm_voice_avoidance", True)
        config.bgm_voice_avoidance_threshold = data.get("bgm_voice_avoidance_threshold", 0.5)
        config.bgm_loop = data.get("bgm_loop", True)
        config.subtitle_stroke_color = data.get("subtitle_stroke_color", "#000000")
        config.subtitle_stroke_width = data.get("subtitle_stroke_width", 1.0)
        subtitle_position = data.get("subtitle_position", "bottom")
        config.subtitle_position = SubtitlePosition(subtitle_position) if subtitle_position else SubtitlePosition.BOTTOM
        config.subtitle_background_alpha = data.get("subtitle_background_alpha", 0.0)
        config.subtitle_line_spacing = data.get("subtitle_line_spacing", 1.5)
        config.video_frame_rate = data.get("video_frame_rate", 30)
        config.video_bit_rate = data.get("video_bit_rate", "high")
        aspect_ratio = data.get("video_aspect_ratio", "9:16")
        config.video_aspect_ratio = AspectRatioType(aspect_ratio) if aspect_ratio else AspectRatioType.RATIO_9_16
        config.enable_transition = data.get("enable_transition", False)
        config.transition_type = data.get("transition_type", "淡入淡出")
        config.transition_effect = data.get("transition_effect", "fade")
        config.transition_random = data.get("transition_random", False)
        config.transition_random_all = data.get("transition_random_all", False)
        config.transition_duration = data.get("transition_duration", 0.5)
        config.enable_double_mode = data.get("enable_double_mode", False)
        config.enable_pip = data.get("enable_pip", False)
        config.pip_video_path = data.get("pip_video_path")
        config.pip_left_video_path = data.get("pip_left_video_path")
        config.pip_right_video_path = data.get("pip_right_video_path")
        return config


# 便捷函数
def create_task(
    name: str,
    source_video_path: str,
    script_text: str,
    prompt_audio_path: str,
    priority: int = 2
) -> Task:
    """创建任务的便捷函数"""
    return Task(
        name=name,
        source_video_path=source_video_path,
        script_text=script_text,
        prompt_audio_path=prompt_audio_path,
        priority=priority
    )