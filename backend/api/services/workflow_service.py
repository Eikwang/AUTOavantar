"""
工作流服务封装
封装 DigitalHumanWorkflow，提供异步任务执行和状态管理
支持数据库持久化和断点续传
"""

import asyncio
import json
import logging
import os
import shutil
import uuid
from typing import Dict, Optional, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from business.workflow import DigitalHumanWorkflow, WorkflowResult, create_workflow
from core.models.task import TaskConfig
from core.scheduler.task_scheduler import SimpleTaskScheduler
from api.services.database import get_database_service, DatabaseService

logger = logging.getLogger("workflow_service")

# 统一使用 backend/config 作为配置目录
# __file__ 位于 backend/api/services/workflow_service.py
# parent = services/, parent.parent = api/, parent.parent.parent = backend/
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def load_api_keys_config() -> Dict[str, Any]:
    """
    从 api_keys.yaml 加载 API 密钥配置

    Returns:
        包含 API 密钥配置的字典
    """
    config_path = CONFIG_DIR / "api_keys.yaml"
    default_config = {
        "deepseek_api_key": "",
        "aliyun_api_key": ""
    }

    if not config_path.exists():
        logger.warning(f"配置文件不存在: {config_path}，使用默认值")
        return default_config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        result = default_config.copy()
        # 兼容两种字段名格式
        # 新格式: deepseek_api_key, aliyun_api_key
        # 旧格式: deepseek, aliyun
        deepseek_key = config.get("deepseek_api_key", "") or config.get("deepseek", "")
        aliyun_key = config.get("aliyun_api_key", "") or config.get("aliyun", "")
        result.update({
            "deepseek_api_key": deepseek_key,
            "aliyun_api_key": aliyun_key
        })

        logger.info("已加载 API 密钥配置")
        return result

    except Exception as e:
        logger.error(f"加载 API 密钥配置失败: {e}")
        return default_config


def load_default_params_config() -> Dict[str, Any]:
    """
    从 default_params.yaml 加载默认参数配置
    
    Returns:
        包含默认参数配置的字典
    """
    config_path = CONFIG_DIR / "default_params.yaml"
    default_config = {
        "heygem_original": True,
        "heygem_inference_steps": 16,
        "dual_mode": False,
        "tts_speed": 1.0,
        "tts_emo_weight": 0.4
    }
    
    if not config_path.exists():
        logger.warning(f"配置文件不存在: {config_path}，使用默认值")
        return default_config
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        
        result = default_config.copy()
        result.update({
            "heygem_original": config.get("heygem_original", True),
            "heygem_inference_steps": config.get("heygem_inference_steps", 16),
            "dual_mode": config.get("dual_mode", False),
            "tts_speed": config.get("tts_speed", 1.0),
            "tts_emo_weight": config.get("tts_emo_weight", 0.4)
        })
        
        logger.info(f"已加载默认参数配置: 语速={result['tts_speed']}, 情感权重={result['tts_emo_weight']}")
        return result
        
    except Exception as e:
        logger.error(f"加载默认参数配置失败: {e}")
        return default_config


class AsyncTaskStatus(Enum):
    """异步任务状态"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AsyncTask:
    """异步任务"""
    task_id: str
    name: str
    status: AsyncTaskStatus = AsyncTaskStatus.PENDING
    progress: float = 0.0
    current_stage: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    result: Optional[WorkflowResult] = None
    config: Optional[TaskConfig] = None
    future: Optional[asyncio.Future] = None
    cancel_event: Optional[asyncio.Event] = None

    source_video_path: str = ""
    script_text: str = ""
    topic: str = ""
    prompt_audio_path: str = ""
    left_prompt_audio_path: str = ""
    right_prompt_audio_path: str = ""
    bgm_path: str = ""
    use_llm_generate: bool = False
    enable_postprocess: bool = True
    
    # 兼容旧接口的视频素材（简单路径格式）
    opening_video: Optional[str] = None
    loop_videos: List[str] = field(default_factory=list)
    scene_videos: List[str] = field(default_factory=list)
    ending_video: Optional[str] = None
    
    # 新接口的带标签视频素材
    opening_video_with_tags: Optional[Dict] = None
    loop_videos_with_tags: List[Dict] = field(default_factory=list)
    scene_videos_with_tags: List[Dict] = field(default_factory=list)
    ending_video_with_tags: Optional[Dict] = None
    
    # 标签组 ID
    scene_tag_group_id: Optional[int] = None

    # 插队标记
    is_priority: bool = False


@dataclass
class TaskCallback:
    """任务回调"""
    on_status_change: Optional[Callable] = None
    on_progress: Optional[Callable] = None
    on_complete: Optional[Callable] = None
    on_error: Optional[Callable] = None


class WorkflowService:
    """工作流服务"""

    def __init__(
        self,
        tts_engine=None,
        heygem_engine=None,
        llm_provider: str = "astron",
        llm_api_key: str = "",
        aliyun_api_key: str = "",
        output_dir: str = "output",
        max_concurrent_tasks: int = 3,
        low_memory_mode: bool = False
    ):
        """
        初始化工作流服务

        Args:
            tts_engine: TTSEngine 实例
            heygem_engine: HeyGemEngine 实例
            llm_provider: LLM 提供商
            llm_api_key: LLM API 密钥
            aliyun_api_key: 阿里云 API 密钥（用于封面生成）
            output_dir: 输出目录
            max_concurrent_tasks: 最大并发任务数
            low_memory_mode: 是否启用低显存模式（任务完成后卸载模型）
        """
        self.tts_engine = tts_engine
        self.heygem_engine = heygem_engine
        self.llm_provider = llm_provider
        self.llm_api_key = llm_api_key
        self.aliyun_api_key = aliyun_api_key
        self.output_dir = output_dir
        self.low_memory_mode = low_memory_mode

        self._tasks: Dict[str, AsyncTask] = {}
        self._callbacks: Dict[str, TaskCallback] = {}
        self._workflows: Dict[str, DigitalHumanWorkflow] = {}
        self._status_lock: Optional[asyncio.Lock] = None  # 延迟创建
        self._db: Optional[DatabaseService] = None
        self._db_initialized = False
        self._tasks_loaded_from_db = False
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

        self._scheduler = SimpleTaskScheduler()
        self._scheduler.set_executor(self._execute_task_callback)
        self._scheduler.start()

        logger.info(f"工作流服务初始化完成（引擎模式），低显存模式: {low_memory_mode}")

    def set_main_loop(self, loop: asyncio.AbstractEventLoop):
        """设置主事件循环"""
        self._main_loop = loop
        logger.info("主事件循环已设置")

    async def set_database(self, db: DatabaseService):
        """设置数据库实例"""
        self._db = db
        self._db_initialized = True
        logger.info("数据库已绑定到工作流服务")

    def _ensure_engines_loaded(self):
        """
        确保引擎已加载（低显存模式下按需加载）

        CR-026: Service 层不再预加载引擎
        引擎的按阶段加载由 Workflow 在各阶段自行管理：
        - 音频合成阶段：加载 TTSEngine
        - 视频合成阶段：加载 HeyGemEngine

        AC-226: 低显存模式按阶段加载模型
        """
        # Service 层不再预加载引擎
        # 实际的按需加载由 Workflow 在各阶段自行处理
        logger.debug("引擎加载由 Workflow 按阶段自行管理")

    def _release_engines_after_task(self):
        """
        任务完成后释放引擎（低显存模式下）

        CR-026: Service 层不再统一卸载引擎
        引擎的按阶段卸载由 Workflow 在各阶段完成后自行管理：
        - 音频合成完成后：卸载 TTSEngine
        - 视频合成完成后：卸载 HeyGemEngine

        AC-227: 低显存模式阶段完成后卸载模型
        AC-228: 低显存模式任务完成后卸载所有模型
        AC-229: 低显存模式关闭时模型常驻
        """
        # Service 层不再统一卸载引擎
        # 实际的按需卸载由 Workflow 在各阶段完成后自行处理
        logger.debug("引擎卸载由 Workflow 按阶段自行管理")

    def _create_workflow(self) -> DigitalHumanWorkflow:
        """创建工作流实例"""
        workflow = create_workflow(
            tts_engine=self.tts_engine,
            heygem_engine=self.heygem_engine,
            llm_provider=self.llm_provider,
            llm_api_key=self.llm_api_key,
            output_dir=self.output_dir,
            qwen_api_key=self.aliyun_api_key,
            low_memory_mode=self.low_memory_mode
        )
        if self._db:
            workflow.set_database(self._db)
        return workflow

    def _get_callback(self, task_id: str) -> Optional[TaskCallback]:
        """获取任务回调"""
        return self._callbacks.get(task_id)

    def register_callback(self, task_id: str, callback: TaskCallback):
        """
        注册任务回调

        Args:
            task_id: 任务ID
            callback: 回调对象
        """
        self._callbacks[task_id] = callback
        logger.info(f"任务 {task_id} 回调已注册")

    def unregister_callback(self, task_id: str):
        """取消注册任务回调"""
        if task_id in self._callbacks:
            del self._callbacks[task_id]

    async def create_task(
        self,
        name: str,
        source_video_path: Optional[str] = None,
        script_text: str = "",
        topic: str = "",
        prompt_audio_path: str = "",
        left_prompt_audio_path: str = "",
        right_prompt_audio_path: str = "",
        enable_double_mode: bool = False,
        bgm_path: str = "",
        use_llm_generate: bool = False,
        enable_postprocess: bool = True,
        enable_denoise: bool = True,
        denoise_strength: float = 0.7,
        tts_speed: float = 1.0,
        tts_emo_weight: float = 0.8,
        left_tts_speed: Optional[float] = None,
        right_tts_speed: Optional[float] = None,
        left_tts_emo_weight: Optional[float] = None,
        right_tts_emo_weight: Optional[float] = None,
        enable_subtitle: bool = True,
        enable_bgm: bool = True,
        bgm_volume: float = 0.3,
        enable_cover: bool = False,
        heygem_steps: int = 16,
        heygem_batch_size: int = 8,
        opening_video: Optional[str] = None,
        loop_videos: Optional[List[str]] = None,
        scene_videos: Optional[List[str]] = None,
        ending_video: Optional[str] = None,
        opening_video_with_tags: Optional[Dict] = None,
        loop_videos_with_tags: Optional[List[Dict]] = None,
        scene_videos_with_tags: Optional[List[Dict]] = None,
        ending_video_with_tags: Optional[Dict] = None,
        scene_tag_group_id: Optional[int] = None,
        **kwargs
    ) -> AsyncTask:
        """
        创建异步任务

        Args:
            name: 任务名称
            source_video_path: 源视频路径
            script_text: 文案文本
            topic: 主题
            prompt_audio_path: 音色参考音频路径（单人模式）
            left_prompt_audio_path: 左边说话人音色参考音频（双人模式）
            right_prompt_audio_path: 右边说话人音色参考音频（双人模式）
            enable_double_mode: 是否启用双人模式
            bgm_path: BGM 路径
            use_llm_generate: 是否使用 LLM 生成文案
            enable_postprocess: 是否启用后期处理
            enable_denoise: 是否开启降噪
            denoise_strength: 降噪强度
            tts_speed: 语速
            tts_emo_weight: 情感权重
            left_tts_speed: 左说话人语速（双人模式）
            right_tts_speed: 右说话人语速（双人模式）
            enable_subtitle: 是否添加字幕
            enable_bgm: 是否添加 BGM
            bgm_volume: BGM 音量
            enable_cover: 是否生成封面
            opening_video: 开场视频路径（兼容）
            loop_videos: 循环视频列表（兼容）
            scene_videos: 场景视频列表（兼容）
            ending_video: 结束视频路径（兼容）
            opening_video_with_tags: 开场视频（带标签）
            loop_videos_with_tags: 循环视频列表（带标签）
            scene_videos_with_tags: 场景视频列表（带标签）
            ending_video_with_tags: 结束视频（带标签）
            **kwargs: 其他参数

        Returns:
            AsyncTask 对象
        """
        task_id = str(uuid.uuid4())[:8]
        
        logger.info(f"create_task 参数: enable_double_mode={enable_double_mode}")
        logger.info(f"create_task 参数: left_prompt_audio_path={left_prompt_audio_path}")
        logger.info(f"create_task 参数: right_prompt_audio_path={right_prompt_audio_path}")

        task = AsyncTask(
            task_id=task_id,
            name=name,
            status=AsyncTaskStatus.PENDING,
            progress=0.0,
            current_stage="任务创建中",
            source_video_path=source_video_path,
            script_text=script_text,
            topic=topic,
            prompt_audio_path=prompt_audio_path,
            left_prompt_audio_path=left_prompt_audio_path,
            right_prompt_audio_path=right_prompt_audio_path,
            bgm_path=bgm_path,
            use_llm_generate=use_llm_generate,
            enable_postprocess=enable_postprocess,
            opening_video=opening_video,
            loop_videos=loop_videos or [],
            scene_videos=scene_videos or [],
            ending_video=ending_video,
            opening_video_with_tags=opening_video_with_tags,
            loop_videos_with_tags=loop_videos_with_tags or [],
            scene_videos_with_tags=scene_videos_with_tags or [],
            ending_video_with_tags=ending_video_with_tags,
            scene_tag_group_id=scene_tag_group_id
        )

        config = TaskConfig(
            tts_speed=tts_speed,
            tts_emo_weight=tts_emo_weight,
            left_tts_speed=left_tts_speed,
            right_tts_speed=right_tts_speed,
            left_tts_emo_weight=left_tts_emo_weight,
            right_tts_emo_weight=right_tts_emo_weight,
            enable_denoise=enable_denoise,
            denoise_strength=denoise_strength,
            enable_subtitle=enable_subtitle,
            enable_bgm=enable_bgm,
            bgm_volume=bgm_volume,
            enable_cover=enable_cover,
            bgm_fade_in=kwargs.get("bgm_fade_in", 0.0),
            bgm_fade_out=kwargs.get("bgm_fade_out", 0.0),
            subtitle_font=kwargs.get("subtitle_font", "SimHei"),
            subtitle_size=kwargs.get("subtitle_size", 14),
            subtitle_color=kwargs.get("subtitle_color", "white"),
            subtitle_stroke_color=kwargs.get("subtitle_stroke_color", "#000000"),
            subtitle_stroke_width=kwargs.get("subtitle_stroke_width", 0.2),
            subtitle_position=kwargs.get("subtitle_position", "bottom"),
            subtitle_background_alpha=kwargs.get("subtitle_background_alpha", 0.0),
            subtitle_line_spacing=kwargs.get("subtitle_line_spacing", 0.5),
            enable_double_mode=enable_double_mode,
            heygem_steps=heygem_steps,
            inference_batch_size=heygem_steps,  # 使用 heygem_steps 作为推理批次大小
            # 转场效果参数
            enable_transition=kwargs.get("enable_transition", False),
            transition_type=kwargs.get("transition_type", "淡入淡出"),
            transition_effect=kwargs.get("transition_effect", "fade"),
            transition_random=kwargs.get("transition_random", False),
            transition_random_all=kwargs.get("transition_random_all", False),
            transition_duration=kwargs.get("transition_duration", 0.5)
        )
        logger.info(f"TaskConfig 创建完成: tts_speed={tts_speed}, tts_emo_weight={tts_emo_weight}, left_tts_speed={left_tts_speed}, right_tts_speed={right_tts_speed}, left_tts_emo_weight={left_tts_emo_weight}, right_tts_emo_weight={right_tts_emo_weight}, enable_double_mode={enable_double_mode}")
        logger.info(f"转场效果配置: enable_transition={config.enable_transition}, transition_type={config.transition_type}, transition_effect={config.transition_effect}, transition_random={config.transition_random}, transition_random_all={config.transition_random_all}, transition_duration={config.transition_duration}")
        task.config = config

        self._tasks[task_id] = task

        # 任务持久化
        if self._db_initialized and self._db:
            try:
                await self._db.task_create(
                    task_id=task_id,
                    name=name,
                    status="pending",
                    source_video_path=source_video_path,
                    script_text=script_text,
                    topic=topic,
                    config=config.to_dict() if config else None,
                    current_stage="任务创建中",
                    prompt_audio_path=prompt_audio_path,
                    left_prompt_audio_path=left_prompt_audio_path,
                    right_prompt_audio_path=right_prompt_audio_path,
                    bgm_path=bgm_path,
                    use_llm_generate=use_llm_generate,
                    enable_postprocess=enable_postprocess,
                    opening_video=opening_video,
                    loop_videos=loop_videos,
                    scene_videos=scene_videos,
                    ending_video=ending_video,
                    opening_video_with_tags=opening_video_with_tags,
                    loop_videos_with_tags=loop_videos_with_tags,
                    scene_videos_with_tags=scene_videos_with_tags,
                    ending_video_with_tags=ending_video_with_tags
                )
                logger.info(f"任务 {task_id} 已持久化到数据库")
            except Exception as e:
                logger.error(f"任务持久化失败: {e}")

        logger.info(f"任务创建成功: {task_id} - {name}")

        return task

    async def start_task(self, task_id: str) -> bool:
        """
        启动任务（提交到调度器队列）

        Args:
            task_id: 任务ID

        Returns:
            是否启动成功
        """
        if task_id not in self._tasks:
            logger.error(f"任务 {task_id} 不存在")
            return False

        task = self._tasks[task_id]

        if task.status == AsyncTaskStatus.RUNNING:
            logger.warning(f"任务 {task_id} 已在运行中")
            return False

        task.status = AsyncTaskStatus.QUEUED
        task.current_stage = "排队等待"
        task.updated_at = datetime.now()
        task.cancel_event = asyncio.Event()

        config = self._build_task_config(task)
        success = self._scheduler.submit(task_id, config)
        
        if not success:
            logger.warning(f"任务 {task_id} 提交到调度器失败")
            task.status = AsyncTaskStatus.PENDING
            return False

        await self._notify_status_change(task_id)
        logger.info(f"任务 {task_id} 已提交到调度器队列")

        return True

    def _build_task_config(self, task: AsyncTask) -> Dict:
        """构建任务配置"""
        config = task.config if task.config else None
        
        enable_double_mode = getattr(config, 'enable_double_mode', False) if config else False
        logger.info(f"_build_task_config: task.config={config}, enable_double_mode={enable_double_mode}")
        if config:
            logger.info(f"config.enable_double_mode={getattr(config, 'enable_double_mode', 'NOT_FOUND')}")
            logger.info(f"config.enable_transition={getattr(config, 'enable_transition', 'NOT_FOUND')}")

        return {
            "source_video_path": getattr(task, 'source_video_path', ''),
            "script_text": getattr(task, 'script_text', ''),
            "topic": getattr(task, 'topic', ''),
            "prompt_audio_path": getattr(task, 'prompt_audio_path', ''),
            "left_prompt_audio_path": getattr(task, 'left_prompt_audio_path', ''),
            "right_prompt_audio_path": getattr(task, 'right_prompt_audio_path', ''),
            "enable_double_mode": enable_double_mode,
            "bgm_path": getattr(task, 'bgm_path', ''),
            "use_llm_generate": getattr(task, 'use_llm_generate', False),
            "enable_postprocess": getattr(task, 'enable_postprocess', True),
            "enable_denoise": getattr(config, 'enable_denoise', False) if config else False,
            "denoise_strength": getattr(config, 'denoise_strength', 0.5) if config else 0.5,
            "tts_speed": getattr(config, 'tts_speed', 1.0) if config else 1.0,
            "tts_emo_weight": getattr(config, 'tts_emo_weight', 0.8) if config else 0.8,
            "left_tts_speed": getattr(config, 'left_tts_speed', None) if config else None,
            "right_tts_speed": getattr(config, 'right_tts_speed', None) if config else None,
            "left_tts_emo_weight": getattr(config, 'left_tts_emo_weight', None) if config else None,
            "right_tts_emo_weight": getattr(config, 'right_tts_emo_weight', None) if config else None,
            "enable_subtitle": getattr(config, 'enable_subtitle', True) if config else True,
            "subtitle_font": getattr(config, 'subtitle_font', "SimHei") if config else "SimHei",
            "subtitle_size": getattr(config, 'subtitle_size', 24) if config else 24,
            "subtitle_color": getattr(config, 'subtitle_color', "white") if config else "white",
            "subtitle_stroke_color": getattr(config, 'subtitle_stroke_color', "#000000") if config else "#000000",
            "subtitle_stroke_width": getattr(config, 'subtitle_stroke_width', 1.0) if config else 1.0,
            "subtitle_position": getattr(config, 'subtitle_position', "bottom") if config else "bottom",
            "subtitle_background_alpha": getattr(config, 'subtitle_background_alpha', 0.0) if config else 0.0,
            "subtitle_line_spacing": getattr(config, 'subtitle_line_spacing', 1.5) if config else 1.5,
            "enable_bgm": getattr(config, 'enable_bgm', True) if config else True,
            "bgm_volume": getattr(config, 'bgm_volume', 0.3) if config else 0.3,
            "enable_cover": getattr(config, 'enable_cover', False) if config else False,
            "cover_prompt_template": getattr(config, 'cover_prompt_template', "根据文案{summary}生成视频封面，风格简洁，突出主题") if config else "根据文案{summary}生成视频封面，风格简洁，突出主题",
            "heygem_steps": getattr(config, 'heygem_steps', 16) if config else 16,
            "inference_batch_size": getattr(config, 'inference_batch_size', 8) if config else 8,
            "opening_video": getattr(task, 'opening_video', None),
            "loop_videos": getattr(task, 'loop_videos', []),
            "scene_videos": getattr(task, 'scene_videos', []),
            "ending_video": getattr(task, 'ending_video', None),
            "opening_video_with_tags": getattr(task, 'opening_video_with_tags', None),
            "loop_videos_with_tags": getattr(task, 'loop_videos_with_tags', []),
            "scene_videos_with_tags": getattr(task, 'scene_videos_with_tags', []),
            "ending_video_with_tags": getattr(task, 'ending_video_with_tags', None),
            "scene_tag_group_id": getattr(task, 'scene_tag_group_id', None),
            # 转场效果参数
            "enable_transition": getattr(config, 'enable_transition', False) if config else False,
            "transition_type": getattr(config, 'transition_type', "淡入淡出") if config else "淡入淡出",
            "transition_effect": getattr(config, 'transition_effect', "fade") if config else "fade",
            "transition_random": getattr(config, 'transition_random', False) if config else False,
            "transition_random_all": getattr(config, 'transition_random_all', False) if config else False,
            "transition_duration": getattr(config, 'transition_duration', 0.5) if config else 0.5,
        }

    def _execute_task_callback(self, task_id: str, config: Dict):
        """
        调度器执行回调（同步方法，由调度器线程调用）
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.error(f"任务 {task_id} 不存在")
            return

        task.status = AsyncTaskStatus.RUNNING
        task.current_stage = "任务启动"
        task.updated_at = datetime.now()

        # AC-219: 低显存模式开启时任务按需加载模型
        self._ensure_engines_loaded()

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_workflow_sync(task_id, config))
        except Exception as e:
            logger.error(f"任务 {task_id} 执行失败: {e}")
            task.status = AsyncTaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = datetime.now()
        finally:
            loop.close()

    async def _run_workflow_sync(self, task_id: str, config: Dict):
        """
        运行工作流（由调度器调用）

        Args:
            task_id: 任务ID
            config: 任务配置
        """
        task = self._tasks.get(task_id)
        if not task:
            return

        callback = self._get_callback(task_id)

        try:
            workflow = self._create_workflow()
            self._workflows[task_id] = workflow

            task.current_stage = "initializing"

            logger.info(f"开始执行任务 {task_id}")
            logger.info(f"_run_workflow_sync config: enable_double_mode={config.get('enable_double_mode')}")
            logger.info(f"_run_workflow_sync config: left_prompt_audio_path={config.get('left_prompt_audio_path')}")
            logger.info(f"_run_workflow_sync config: right_prompt_audio_path={config.get('right_prompt_audio_path')}")
            logger.info(f"_run_workflow_sync config: enable_transition={config.get('enable_transition')}, transition_type={config.get('transition_type')}, transition_effect={config.get('transition_effect')}")

            def schedule_progress(progress: float, stage: str):
                try:
                    task_obj = self._tasks.get(task_id)
                    if task_obj:
                        task_obj.progress = progress
                        task_obj.current_stage = stage
                        task_obj.updated_at = datetime.now()
                    
                    main_loop = self._main_loop
                    logger.info(f"schedule_progress: task_id={task_id}, progress={progress}, stage={stage}, main_loop={main_loop}, is_running={main_loop.is_running() if main_loop else None}")
                    
                    if main_loop and main_loop.is_running():
                        callback = self._get_callback(task_id)
                        logger.info(f"schedule_progress: callback={callback}, on_progress={callback.on_progress if callback else None}")
                        if callback and callback.on_progress:
                            try:
                                future = asyncio.run_coroutine_threadsafe(
                                    callback.on_progress(task_id, progress, stage),
                                    main_loop
                                )
                                logger.info(f"进度更新协程已提交: task_id={task_id}, progress={progress}, stage={stage}")
                            except Exception as cb_e:
                                logger.error(f"进度回调执行失败: {cb_e}", exc_info=True)
                        
                        if self._db_initialized and self._db:
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    self._db.task_update(
                                        task_id=task_id,
                                        progress=progress,
                                        current_stage=stage
                                    ),
                                    main_loop
                                )
                            except Exception as db_e:
                                logger.error(f"进度持久化失败: {db_e}", exc_info=True)
                    else:
                        logger.warning(f"主事件循环未运行，跳过进度更新: task_id={task_id}, main_loop={main_loop}")
                        
                except Exception as e:
                    logger.error(f"Progress update failed for task {task_id}: {e}", exc_info=True)

            task_config = TaskConfig(
                tts_speed=config.get("tts_speed", getattr(task, 'tts_speed', 1.0)),
                tts_emo_weight=config.get("tts_emo_weight", getattr(task, 'tts_emo_weight', 0.8)),
                left_tts_speed=config.get("left_tts_speed", getattr(task, 'left_tts_speed', None)),
                right_tts_speed=config.get("right_tts_speed", getattr(task, 'right_tts_speed', None)),
                left_tts_emo_weight=config.get("left_tts_emo_weight", getattr(task, 'left_tts_emo_weight', None)),
                right_tts_emo_weight=config.get("right_tts_emo_weight", getattr(task, 'right_tts_emo_weight', None)),
                heygem_steps=config.get("heygem_steps", getattr(task, 'heygem_steps', 16)),
                inference_batch_size=config.get("inference_batch_size", getattr(task.config, 'inference_batch_size', 8) if task.config else 8),
                enable_subtitle=config.get("enable_subtitle", getattr(task, 'enable_subtitle', True)),
                subtitle_font=config.get("subtitle_font", getattr(task, 'subtitle_font', "SimHei")),
                subtitle_size=config.get("subtitle_size", getattr(task, 'subtitle_size', 24)),
                subtitle_color=config.get("subtitle_color", getattr(task, 'subtitle_color', "white")),
                subtitle_stroke_color=config.get("subtitle_stroke_color", getattr(task, 'subtitle_stroke_color', "#000000")),
                subtitle_stroke_width=config.get("subtitle_stroke_width", getattr(task, 'subtitle_stroke_width', 1.0)),
                subtitle_position=config.get("subtitle_position", getattr(task, 'subtitle_position', "bottom")),
                subtitle_background_alpha=config.get("subtitle_background_alpha", getattr(task, 'subtitle_background_alpha', 0.0)),
                subtitle_line_spacing=config.get("subtitle_line_spacing", getattr(task, 'subtitle_line_spacing', 1.5)),
                enable_bgm=config.get("enable_bgm", getattr(task, 'enable_bgm', True)),
                bgm_volume=config.get("bgm_volume", getattr(task, 'bgm_volume', 0.3)),
                enable_cover=config.get("enable_cover", getattr(task, 'enable_cover', False)),
                cover_prompt_template=config.get("cover_prompt_template", getattr(task, 'cover_prompt_template', "根据文案{summary}生成视频封面，风格简洁，突出主题")),
                enable_denoise=config.get("enable_denoise", getattr(task, 'enable_denoise', False)),
                denoise_strength=config.get("denoise_strength", getattr(task, 'denoise_strength', 0.5)),
                enable_double_mode=config.get("enable_double_mode", False),
                # 转场效果参数
                enable_transition=config.get("enable_transition", False),
                transition_type=config.get("transition_type", "淡入淡出"),
                transition_effect=config.get("transition_effect", "fade"),
                transition_random=config.get("transition_random", False),
                transition_random_all=config.get("transition_random_all", False),
                transition_duration=config.get("transition_duration", 0.5),
            )

            # 直接 await workflow.run_async()，不再使用 asyncio.to_thread
            # 这样 FFmpeg 调用通过 asyncio.create_subprocess_exec 非阻塞执行
            result = await workflow.run_async(
                source_video_path=config.get("source_video_path", getattr(task, 'source_video_path', '')),
                script_text=config.get("script_text", getattr(task, 'script_text', '')),
                topic=config.get("topic", getattr(task, 'topic', '')),
                prompt_audio_path=config.get("prompt_audio_path", getattr(task, 'prompt_audio_path', '')),
                left_prompt_audio_path=config.get("left_prompt_audio_path", getattr(task, 'left_prompt_audio_path', '')),
                right_prompt_audio_path=config.get("right_prompt_audio_path", getattr(task, 'right_prompt_audio_path', '')),
                bgm_path=config.get("bgm_path", getattr(task, 'bgm_path', '')),
                config=task_config,
                use_llm_generate=config.get("use_llm_generate", getattr(task, 'use_llm_generate', False)),
                enable_postprocess=config.get("enable_postprocess", getattr(task, 'enable_postprocess', True)),
                opening_video=config.get("opening_video", getattr(task, 'opening_video', None)),
                loop_videos=config.get("loop_videos", getattr(task, 'loop_videos', [])),
                scene_videos=config.get("scene_videos", getattr(task, 'scene_videos', [])),
                ending_video=config.get("ending_video", getattr(task, 'ending_video', None)),
                opening_video_with_tags=config.get("opening_video_with_tags", getattr(task, 'opening_video_with_tags', None)),
                loop_videos_with_tags=config.get("loop_videos_with_tags", getattr(task, 'loop_videos_with_tags', [])),
                scene_videos_with_tags=config.get("scene_videos_with_tags", getattr(task, 'scene_videos_with_tags', [])),
                ending_video_with_tags=config.get("ending_video_with_tags", getattr(task, 'ending_video_with_tags', None)),
                scene_tag_group_id=config.get("scene_tag_group_id", getattr(task, 'scene_tag_group_id', None)),
                cancel_callback=task.cancel_event.is_set if task.cancel_event else None,
                existing_task_id=task_id,
                progress_callback=schedule_progress
            )

            if result.status == "success":
                task.status = AsyncTaskStatus.COMPLETED
                task.progress = 100.0
                task.current_stage = "completed"
                task.output_path = result.output_path
                task.result = result

                # CR-001: 任务成功完成时消耗配额
                try:
                    from api.services.license_service import get_license_service
                    license_service = get_license_service()
                    license_status = license_service.get_license_status()
                    if not license_status.is_activated:
                        license_service.consume_quota()
                        logger.info(f"任务 {task_id} 完成，配额已消耗")
                except Exception as quota_err:
                    logger.error(f"配额消耗失败: {quota_err}")

                if self._db_initialized and self._db:
                    try:
                        await self._db.task_update(
                            task_id=task_id,
                            status="completed",
                            progress=100.0,
                            current_stage="completed",
                            output_path=result.output_path
                        )
                        logger.info(f"任务 {task_id} 完成状态已持久化")
                    except Exception as e:
                        logger.error(f"完成状态持久化失败: {e}")

                logger.info(f"任务 {task_id} 执行成功: {result.output_path}")
                
                await self.cleanup_task_files(
                    task_id=task_id,
                    output_path=result.output_path
                )

                if callback and callback.on_complete:
                    try:
                        if asyncio.iscoroutinefunction(callback.on_complete):
                            await callback.on_complete(task_id, result)
                        else:
                            callback.on_complete(task_id, result)
                    except Exception as cb_err:
                        logger.error(f"完成回调执行失败: {cb_err}")

            else:
                # 判断是否为服务启动失败（可恢复错误）
                is_service_failure = (
                    "服务启动失败" in str(result.error_message) or
                    "IndexTTS 服务启动失败" in str(result.error_message) or
                    "HeyGem 服务启动失败" in str(result.error_message)
                )

                if "任务被取消" in str(result.error_message):
                    logger.info(f"任务 {task_id} 被用户取消，保持等待状态以便从检查点继续")
                    task.status = AsyncTaskStatus.PENDING
                    task.current_stage = "任务已取消，等待继续"
                    task.updated_at = datetime.now()

                    if self._db_initialized and self._db:
                        try:
                            await self._db.task_update(
                                task_id=task_id,
                                status="pending",
                                current_stage="任务已取消，等待继续",
                                progress=task.progress
                            )
                            logger.info(f"任务 {task_id} 取消状态已持久化")
                        except Exception as e:
                            logger.error(f"取消状态持久化失败: {e}")
                elif is_service_failure:
                    # 服务启动失败，回到待运行状态，用户可以重新启动
                    logger.warning(f"任务 {task_id} 因服务启动失败暂停，可从检查点继续: {result.error_message}")
                    task.status = AsyncTaskStatus.PENDING
                    task.error_message = result.error_message
                    task.current_stage = "服务启动失败，等待重试"
                    task.updated_at = datetime.now()

                    if self._db_initialized and self._db:
                        try:
                            await self._db.task_update(
                                task_id=task_id,
                                status="pending",
                                current_stage="服务启动失败，等待重试",
                                progress=task.progress,
                                error_message=result.error_message
                            )
                            logger.info(f"任务 {task_id} 服务失败状态已持久化，可重新运行")
                        except Exception as e:
                            logger.error(f"服务失败状态持久化失败: {e}")
                else:
                    task.status = AsyncTaskStatus.FAILED
                    task.error_message = result.error_message
                    task.current_stage = "failed"

                    if self._db_initialized and self._db:
                        try:
                            await self._db.task_update(
                                task_id=task_id,
                                status="failed",
                                current_stage="failed",
                                error_message=result.error_message
                            )
                        except Exception as e:
                            logger.error(f"失败状态持久化失败: {e}")

                    logger.error(f"任务 {task_id} 执行失败: {result.error_message}")

                    if callback and callback.on_error:
                        try:
                            if asyncio.iscoroutinefunction(callback.on_error):
                                await callback.on_error(task_id, result.error_message)
                            else:
                                callback.on_error(task_id, result.error_message)
                        except Exception as cb_err:
                            logger.error(f"错误回调执行失败: {cb_err}")

        except Exception as e:
            error_msg = str(e)

            # 判断是否为服务启动失败（可恢复错误）
            is_service_failure = (
                "服务启动失败" in error_msg or
                "IndexTTS 服务启动失败" in error_msg or
                "HeyGem 服务启动失败" in error_msg
            )

            if is_service_failure:
                # 服务启动失败，回到待运行状态
                logger.warning(f"任务 {task_id} 因服务启动失败暂停，可从检查点继续: {error_msg}")
                task.status = AsyncTaskStatus.PENDING
                task.error_message = error_msg
                task.current_stage = "服务启动失败，等待重试"
                task.updated_at = datetime.now()

                if self._db_initialized and self._db:
                    try:
                        await self._db.task_update(
                            task_id=task_id,
                            status="pending",
                            current_stage="服务启动失败，等待重试",
                            progress=task.progress,
                            error_message=error_msg
                        )
                        logger.info(f"任务 {task_id} 服务失败状态已持久化，可重新运行")
                    except Exception as db_err:
                        logger.error(f"服务失败状态持久化失败: {db_err}")
            else:
                task.status = AsyncTaskStatus.FAILED
                task.error_message = error_msg
                task.current_stage = "failed"

                logger.error(f"任务 {task_id} 执行异常: {e}")

                if callback and callback.on_error:
                    try:
                        if asyncio.iscoroutinefunction(callback.on_error):
                            await callback.on_error(task_id, error_msg)
                        else:
                            callback.on_error(task_id, error_msg)
                    except Exception as cb_err:
                        logger.error(f"错误回调执行失败: {cb_err}")

        finally:
            task.completed_at = datetime.now()
            task.updated_at = datetime.now()

            # AC-220: 低显存模式开启时任务完成后卸载模型
            self._release_engines_after_task()

            if task_id in self._workflows:
                del self._workflows[task_id]

    async def _run_workflow(self, task_id: str):
        """
        运行工作流（异步）

        Args:
            task_id: 任务ID
        """
        task = self._tasks.get(task_id)
        if not task:
            return

        callback = self._get_callback(task_id)

        try:
            loop = asyncio.get_event_loop()
            workflow = self._create_workflow()
            self._workflows[task_id] = workflow

            task.current_stage = "initializing"
            await self._notify_progress(task_id)

            logger.info(f"开始执行任务 {task_id}")

            result = await loop.run_in_executor(
                self._executor,
                self._execute_workflow_sync,
                task_id
            )

            if result.status == "success":
                task.status = AsyncTaskStatus.COMPLETED
                task.progress = 100.0
                task.current_stage = "completed"
                task.output_path = result.output_path
                task.result = result

                # 完成状态持久化
                if self._db_initialized and self._db:
                    try:
                        await self._db.task_update(
                            task_id=task_id,
                            status="completed",
                            progress=100.0,
                            current_stage="completed",
                            output_path=result.output_path
                        )
                        logger.info(f"任务 {task_id} 完成状态已持久化")
                    except Exception as e:
                        logger.error(f"完成状态持久化失败: {e}")

                logger.info(f"任务 {task_id} 执行成功: {result.output_path}")
                
                await self.cleanup_task_files(
                    task_id=task_id,
                    output_path=result.output_path
                )

                if callback and callback.on_complete:
                    await callback.on_complete(task_id, result)

                await self._notify_status_change(task_id)

            else:
                if "任务被取消" in str(result.error_message):
                    logger.info(f"任务 {task_id} 已被用户取消，保持等待状态以便从检查点继续")
                    task.status = AsyncTaskStatus.PENDING
                    task.current_stage = "任务已取消，等待继续"
                    task.updated_at = datetime.now()
                    
                    if self._db_initialized and self._db:
                        try:
                            await self._db.task_update(
                                task_id=task_id,
                                status="pending",
                                current_stage="任务已取消，等待继续",
                                progress=task.progress
                            )
                            logger.info(f"任务 {task_id} 取消状态已持久化")
                        except Exception as e:
                            logger.error(f"取消状态持久化失败: {e}")
                else:
                    task.status = AsyncTaskStatus.FAILED
                    task.error_message = result.error_message
                    task.current_stage = "任务失败"

                    if self._db_initialized and self._db:
                        try:
                            await self._db.task_update(
                                task_id=task_id,
                                status="failed",
                                current_stage="任务失败",
                                error_message=result.error_message
                            )
                            logger.info(f"任务 {task_id} 失败状态已持久化")
                        except Exception as e:
                            logger.error(f"失败状态持久化失败: {e}")

                    logger.error(f"任务 {task_id} 执行失败: {result.error_message}")
                    
                    await self.cleanup_task_files(
                        task_id=task_id,
                        output_path=None,
                        task_failed=True
                    )

                    if callback and callback.on_error:
                        await callback.on_error(task_id, result.error_message)

                    await self._notify_status_change(task_id)

        except asyncio.CancelledError:
            task.status = AsyncTaskStatus.CANCELLED
            task.current_stage = "任务取消"
            logger.info(f"任务 {task_id} 被取消")

            # 取消状态持久化
            if self._db_initialized and self._db:
                try:
                    await self._db.task_update(
                        task_id=task_id,
                        status="cancelled",
                        current_stage="任务取消"
                    )
                    logger.info(f"任务 {task_id} 取消状态已持久化")
                except Exception as e:
                    logger.error(f"取消状态持久化失败: {e}")

            if callback and callback.on_error:
                await callback.on_error(task_id, "任务被取消")

        except Exception as e:
            task.status = AsyncTaskStatus.FAILED
            task.error_message = str(e)
            task.current_stage = "任务异常"
            logger.error(f"任务 {task_id} 执行异常: {e}")

            # 异常状态持久化
            if self._db_initialized and self._db:
                try:
                    await self._db.task_update(
                        task_id=task_id,
                        status="failed",
                        current_stage="任务异常",
                        error_message=str(e)
                    )
                    logger.info(f"任务 {task_id} 异常状态已持久化")
                except Exception as db_error:
                    logger.error(f"异常状态持久化失败: {db_error}")

            if callback and callback.on_error:
                await callback.on_error(task_id, str(e))

        finally:
            task.completed_at = datetime.now()
            task.updated_at = datetime.now()

            if task_id in self._workflows:
                try:
                    self._workflows[task_id].close()
                except Exception as e:
                    logger.error(f"关闭工作流 {task_id} 失败: {e}")
                del self._workflows[task_id]

            await self._notify_status_change(task_id)

    def _execute_workflow_sync(self, task_id: str) -> WorkflowResult:
        """
        同步执行工作流（在线程池中运行）

        Args:
            task_id: 任务ID

        Returns:
            工作流结果
        """
        task = self._tasks.get(task_id)
        if not task:
            return WorkflowResult(
                task_id=task_id,
                status="failed",
                error_message="任务不存在"
            )

        workflow = self._workflows.get(task_id)
        if not workflow:
            return WorkflowResult(
                task_id=task_id,
                status="failed",
                error_message="工作流未初始化"
            )

        def check_cancelled() -> bool:
            """检查任务是否被取消"""
            if task.cancel_event and task.cancel_event.is_set():
                logger.info(f"任务 {task_id} 检测到取消信号")
                return True
            return False

        def schedule_progress(progress: float, stage: str):
            try:
                if check_cancelled():
                    return
                
                task_obj = self._tasks.get(task_id)
                if task_obj:
                    task_obj.progress = progress
                    task_obj.current_stage = stage
                    task_obj.updated_at = datetime.now()
                
                main_loop = self._main_loop
                logger.info(f"schedule_progress(2): task_id={task_id}, progress={progress}, stage={stage}, main_loop={main_loop}, is_running={main_loop.is_running() if main_loop else None}")
                
                if main_loop and main_loop.is_running():
                    callback = self._get_callback(task_id)
                    logger.info(f"schedule_progress(2): callback={callback}, on_progress={callback.on_progress if callback else None}")
                    if callback and callback.on_progress:
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                callback.on_progress(task_id, progress, stage),
                                main_loop
                            )
                            logger.info(f"进度更新协程已提交(2): task_id={task_id}, progress={progress}, stage={stage}")
                        except Exception as cb_e:
                            logger.error(f"进度回调执行失败: {cb_e}", exc_info=True)
                    
                    if self._db_initialized and self._db:
                        try:
                            asyncio.run_coroutine_threadsafe(
                                self._db.task_update(
                                    task_id=task_id,
                                    progress=progress,
                                    current_stage=stage
                                ),
                                main_loop
                            )
                        except Exception as db_e:
                            logger.error(f"进度持久化失败: {db_e}", exc_info=True)
                else:
                    logger.warning(f"主事件循环未运行，跳过进度更新(2): task_id={task_id}, main_loop={main_loop}")
                    
            except Exception as e:
                logger.error(f"Progress update failed for task {task_id}: {e}", exc_info=True)

        result = workflow.run(
            source_video_path=getattr(task, 'source_video_path', ''),
            script_text=getattr(task, 'script_text', ''),
            topic=getattr(task, 'topic', ''),
            prompt_audio_path=getattr(task, 'prompt_audio_path', ''),
            left_prompt_audio_path=getattr(task, 'left_prompt_audio_path', ''),
            right_prompt_audio_path=getattr(task, 'right_prompt_audio_path', ''),
            bgm_path=getattr(task, 'bgm_path', ''),
            config=task.config,
            use_llm_generate=getattr(task, 'use_llm_generate', False),
            enable_postprocess=getattr(task, 'enable_postprocess', True),
            opening_video=getattr(task, 'opening_video', None),
            loop_videos=getattr(task, 'loop_videos', []),
            scene_videos=getattr(task, 'scene_videos', []),
            ending_video=getattr(task, 'ending_video', None),
            opening_video_with_tags=getattr(task, 'opening_video_with_tags', None),
            loop_videos_with_tags=getattr(task, 'loop_videos_with_tags', []),
            scene_videos_with_tags=getattr(task, 'scene_videos_with_tags', []),
            ending_video_with_tags=getattr(task, 'ending_video_with_tags', None),
            cancel_callback=check_cancelled,
            existing_task_id=task_id,
            progress_callback=schedule_progress
        )

        return result

    async def _update_progress(self, task_id: str, progress: float, stage: str):
        """更新任务进度"""
        # 延迟创建锁，确保在异步上下文中创建
        if self._status_lock is None:
            self._status_lock = asyncio.Lock()
        async with self._status_lock:
            task = self._tasks.get(task_id)
            if task:
                task.progress = progress
                task.current_stage = stage
                task.updated_at = datetime.now()

        # 进度持久化
        if self._db_initialized and self._db:
            try:
                await self._db.task_update(
                    task_id=task_id,
                    progress=progress,
                    current_stage=stage
                )
            except Exception as e:
                logger.error(f"进度持久化失败: {e}")

        await self._notify_progress(task_id)

    async def get_task_status(self, task_id: str) -> Optional[AsyncTask]:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务对象或 None
        """
        # 先从内存获取
        task = self._tasks.get(task_id)
        if task:
            return task
        
        # 如果内存中没有，尝试从数据库读取
        if self._db_initialized and self._db:
            try:
                task_data = await self._db.task_get_by_id(task_id)
                if task_data:
                    # 从数据库数据创建 AsyncTask
                    task = AsyncTask(
                        task_id=task_data['task_id'],
                        name=task_data['name'],
                        status=AsyncTaskStatus(task_data['status']),
                        progress=task_data['progress'],
                        current_stage=task_data.get('current_stage', ''),
                        source_video_path=task_data.get('source_video_path', ''),
                        script_text=task_data.get('script_text', ''),
                        topic=task_data.get('topic', ''),
                        output_path=task_data.get('output_path', ''),
                        error_message=task_data.get('error_message', ''),
                        prompt_audio_path=task_data.get('prompt_audio_path', ''),
                        left_prompt_audio_path=task_data.get('left_prompt_audio_path', ''),
                        right_prompt_audio_path=task_data.get('right_prompt_audio_path', ''),
                        bgm_path=task_data.get('bgm_path', ''),
                        use_llm_generate=bool(task_data.get('use_llm_generate', False)),
                        enable_postprocess=bool(task_data.get('enable_postprocess', True)),
                        opening_video=task_data.get('opening_video'),
                        loop_videos=json.loads(task_data['loop_videos']) if task_data.get('loop_videos') else [],
                        scene_videos=json.loads(task_data['scene_videos']) if task_data.get('scene_videos') else [],
                        ending_video=task_data.get('ending_video'),
                        opening_video_with_tags=json.loads(task_data['opening_video_with_tags']) if task_data.get('opening_video_with_tags') else None,
                        loop_videos_with_tags=json.loads(task_data['loop_videos_with_tags']) if task_data.get('loop_videos_with_tags') else [],
                        scene_videos_with_tags=json.loads(task_data['scene_videos_with_tags']) if task_data.get('scene_videos_with_tags') else [],
                        ending_video_with_tags=json.loads(task_data['ending_video_with_tags']) if task_data.get('ending_video_with_tags') else None
                    )
                    
                    if task_data.get('created_at'):
                        task.created_at = datetime.fromisoformat(task_data['created_at'])
                    if task_data.get('updated_at'):
                        task.updated_at = datetime.fromisoformat(task_data['updated_at'])
                    if task_data.get('completed_at'):
                        task.completed_at = datetime.fromisoformat(task_data['completed_at'])
                    
                    config_dict = json.loads(task_data['config']) if task_data.get('config') else {}
                    if config_dict:
                        task.config = TaskConfig.from_dict(config_dict)
                    
                    self._tasks[task_id] = task
                    logger.info(f"从数据库加载任务: {task_id}")
                    return task
            except Exception as e:
                logger.error(f"从数据库读取任务 {task_id} 失败: {e}")
        
        return None

    async def list_tasks(
        self,
        status: Optional[AsyncTaskStatus] = None
    ) -> List[AsyncTask]:
        """
        列出所有任务（优先从数据库读取一次）

        Args:
            status: 可选的状态过滤

        Returns:
            任务列表
        """
        # 只在第一次调用时从数据库加载任务
        if not self._tasks_loaded_from_db and self._db_initialized and self._db:
            try:
                tasks_from_db, _ = await self._db.task_list(status=status.value if status else None, limit=1000, offset=0)
                
                # 将数据库任务转换为 AsyncTask 并同步到内存
                for task_data in tasks_from_db:
                    task_id = task_data['task_id']
                    
                    # 如果内存中已存在该任务，跳过（保持内存中的最新状态）
                    if task_id in self._tasks:
                        continue
                    
                    # 从数据库数据创建 AsyncTask
                    task = AsyncTask(
                        task_id=task_id,
                        name=task_data['name'],
                        status=AsyncTaskStatus(task_data['status']),
                        progress=task_data['progress'],
                        current_stage=task_data.get('current_stage', ''),
                        source_video_path=task_data.get('source_video_path', ''),
                        script_text=task_data.get('script_text', ''),
                        topic=task_data.get('topic', ''),
                        output_path=task_data.get('output_path', ''),
                        error_message=task_data.get('error_message', ''),
                        prompt_audio_path=task_data.get('prompt_audio_path', ''),
                        left_prompt_audio_path=task_data.get('left_prompt_audio_path', ''),
                        right_prompt_audio_path=task_data.get('right_prompt_audio_path', ''),
                        bgm_path=task_data.get('bgm_path', ''),
                        use_llm_generate=bool(task_data.get('use_llm_generate', False)),
                        enable_postprocess=bool(task_data.get('enable_postprocess', True)),
                        opening_video=task_data.get('opening_video'),
                        loop_videos=json.loads(task_data['loop_videos']) if task_data.get('loop_videos') else [],
                        scene_videos=json.loads(task_data['scene_videos']) if task_data.get('scene_videos') else [],
                        ending_video=task_data.get('ending_video'),
                        opening_video_with_tags=json.loads(task_data['opening_video_with_tags']) if task_data.get('opening_video_with_tags') else None,
                        loop_videos_with_tags=json.loads(task_data['loop_videos_with_tags']) if task_data.get('loop_videos_with_tags') else [],
                        scene_videos_with_tags=json.loads(task_data['scene_videos_with_tags']) if task_data.get('scene_videos_with_tags') else [],
                        ending_video_with_tags=json.loads(task_data['ending_video_with_tags']) if task_data.get('ending_video_with_tags') else None
                    )
                    
                    if task_data.get('created_at'):
                        task.created_at = datetime.fromisoformat(task_data['created_at'])
                    if task_data.get('updated_at'):
                        task.updated_at = datetime.fromisoformat(task_data['updated_at'])
                    if task_data.get('completed_at'):
                        task.completed_at = datetime.fromisoformat(task_data['completed_at'])
                    
                    config_dict = json.loads(task_data['config']) if task_data.get('config') else {}
                    if config_dict:
                        task.config = TaskConfig.from_dict(config_dict)
                    
                    self._tasks[task_id] = task

                self._tasks_loaded_from_db = True
                logger.info(f"从数据库加载了 {len(tasks_from_db)} 个任务")
            except Exception as e:
                logger.error(f"从数据库读取任务失败: {e}")

        # 从内存中获取任务列表
        tasks = list(self._tasks.values())

        if status:
            tasks = [t for t in tasks if t.status == status]

        # 从调度器获取 is_priority 信息
        if self._scheduler:
            for task in tasks:
                scheduler_status = self._scheduler.get_task_status(task.task_id)
                if scheduler_status:
                    task.is_priority = scheduler_status.get('is_priority', False)

        tasks.sort(key=lambda x: x.created_at, reverse=True)
        return tasks

    async def cancel_task(self, task_id: str) -> bool:
        """
        取消任务

        Args:
            task_id: 任务ID

        Returns:
            是否取消成功
        """
        if task_id not in self._tasks:
            logger.error(f"任务 {task_id} 不存在")
            return False

        task = self._tasks[task_id]

        if task.status == AsyncTaskStatus.COMPLETED:
            logger.warning(f"任务 {task_id} 已完成，无法取消")
            return False

        if task.status == AsyncTaskStatus.FAILED:
            logger.warning(f"任务 {task_id} 已失败，无法取消")
            return False

        if task.status == AsyncTaskStatus.PENDING:
            logger.warning(f"任务 {task_id} 已在等待状态")
            return False

        if task.status == AsyncTaskStatus.QUEUED:
            self._scheduler.cancel(task_id)
            task.status = AsyncTaskStatus.PENDING
            task.current_stage = "任务已取消，等待重新运行"
            task.updated_at = datetime.now()

            if self._db_initialized and self._db:
                try:
                    await self._db.task_update(
                        task_id=task_id,
                        status="pending",
                        current_stage="任务已取消，等待重新运行",
                        progress=task.progress
                    )
                except Exception as e:
                    logger.error(f"取消状态持久化失败: {e}")

            await self._notify_status_change(task_id)
            logger.info(f"排队任务 {task_id} 已取消，回到待运行状态")
            return True

        if task.cancel_event:
            task.cancel_event.set()

        # 检查是否需要卸载模型（低显存模式或超低显存模式开启时）
        low_memory_mode = self.low_memory_mode
        # 检查超低显存模式
        ultra_low_memory = False
        try:
            from core.system_config import get_config_manager
            config_manager = get_config_manager()
            ultra_low_memory = config_manager.get_ultra_low_memory()
        except Exception as e:
            logger.warning(f"读取超低显存模式配置失败: {e}")

        need_unload = low_memory_mode or ultra_low_memory
        current_stage = getattr(task, 'current_stage', '')

        # 调试日志：显示实际的 current_stage 值（仅 debug 级别，避免生产环境泄露配置信息）
        logger.debug(f"任务 {task_id} 取消时 current_stage={current_stage}, low_memory_mode={low_memory_mode}, ultra_low_memory={ultra_low_memory}, need_unload={need_unload}")

        if need_unload:
            logger.info(f"任务 {task_id} 被取消，低显存模式或超低显存模式开启，准备卸载引擎")

            # 卸载 TTS 引擎（如果已加载）
            # 注意：不再依赖 current_stage 判断，因为取消时 current_stage 可能不准确
            try:
                from core.engines.gpu_manager import get_gpu_manager, EngineType
                gpu_manager = get_gpu_manager()
                tts_unloaded = False
                if gpu_manager:
                    tts_engine = gpu_manager.get_engine(EngineType.TTS)
                    if tts_engine and tts_engine.is_loaded:
                        tts_engine.unload()
                        tts_unloaded = True
                        logger.info(f"任务 {task_id} 取消时 TTS 引擎已卸载")

                # 备用方案：直接尝试卸载 self.tts_engine
                if not tts_unloaded and self.tts_engine and self.tts_engine.is_loaded:
                    self.tts_engine.unload()
                    logger.info(f"任务 {task_id} 取消时 TTS 引擎已卸载（备用方案）")
            except Exception as e:
                logger.error(f"任务 {task_id} 取消时卸载 TTS 引擎失败: {e}")

            # 卸载 HeyGem 引擎（如果已加载）
            try:
                from core.engines.gpu_manager import get_gpu_manager, EngineType
                gpu_manager = get_gpu_manager()
                heygem_unloaded = False
                if gpu_manager:
                    heygem_engine = gpu_manager.get_engine(EngineType.HEYGEM)
                    if heygem_engine and heygem_engine.is_loaded:
                        heygem_engine.unload()
                        heygem_unloaded = True
                        logger.info(f"任务 {task_id} 取消时 HeyGem 引擎已卸载")

                if not heygem_unloaded:
                    # 备用方案：直接尝试清理 TransDhTask 单例
                    try:
                        import sys
                        if 'engines.heygem.service.trans_dh_service' in sys.modules:
                            from engines.heygem.service.trans_dh_service import TransDhTask
                            if hasattr(TransDhTask, '_instance') and TransDhTask._instance is not None:
                                logger.info(f"任务 {task_id} 尝试直接清理 TransDhTask 单例")
                                TransDhTask._instance.cleanup()
                    except Exception as e2:
                        logger.error(f"任务 {task_id} 备用清理失败: {e2}")
            except Exception as e:
                logger.error(f"任务 {task_id} 取消时卸载 HeyGem 引擎失败: {e}")
        else:
            logger.info(f"任务 {task_id} 被取消，低显存模式关闭，保持引擎加载")

        # 同步取消调度器中的任务状态
        try:
            self._scheduler.cancel(task_id)
            logger.info(f"任务 {task_id} 已从调度器取消")
        except Exception as e:
            logger.warning(f"任务 {task_id} 从调度器取消失败: {e}")

        task.status = AsyncTaskStatus.PENDING
        task.current_stage = "任务已取消，等待重新运行"
        task.updated_at = datetime.now()

        if self._db_initialized and self._db:
            try:
                await self._db.task_update(
                    task_id=task_id,
                    status="pending",
                    current_stage="任务已取消，等待重新运行",
                    progress=task.progress
                )
                logger.info(f"任务 {task_id} 取消状态已持久化")
            except Exception as e:
                logger.error(f"取消状态持久化失败: {e}")

        await self._notify_status_change(task_id)
        logger.info(f"任务 {task_id} 取消请求已发送，已回到等待状态")

        return True

    async def retry_task(self, task_id: str) -> bool:
        """
        重试任务（包括已取消的任务）

        Args:
            task_id: 任务ID

        Returns:
            是否重试成功
        """
        if task_id not in self._tasks:
            logger.error(f"任务 {task_id} 不存在")
            return False

        task = self._tasks[task_id]

        if task.status == AsyncTaskStatus.RUNNING:
            logger.warning(f"任务 {task_id} 正在运行，无法重试")
            return False

        # 重置取消事件
        task.cancel_event = asyncio.Event()

        task.status = AsyncTaskStatus.PENDING
        task.error_message = None
        task.current_stage = "等待从检查点继续"
        task.updated_at = datetime.now()

        if self._db_initialized and self._db:
            try:
                await self._db.task_update(
                    task_id=task_id,
                    status="pending",
                    current_stage="等待从检查点继续",
                    progress=task.progress
                )
            except Exception as e:
                logger.error(f"重置任务状态持久化失败: {e}")

        asyncio.create_task(self.start_task(task_id))

        logger.info(f"任务 {task_id} 正在从检查点继续")
        return True

    async def priority_task(self, task_id: str) -> bool:
        """
        将任务设置为插队任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功
        """
        if task_id not in self._tasks:
            logger.error(f"任务 {task_id} 不存在")
            return False

        task = self._tasks[task_id]

        # 同时接受 PENDING 和 QUEUED 状态的任务
        if task.status not in [AsyncTaskStatus.PENDING, AsyncTaskStatus.QUEUED]:
            logger.warning(f"任务 {task_id} 状态为 {task.status}，不是等待状态，无法调整优先级")
            return False

        # 调用调度器的 set_priority 方法
        if self._scheduler:
            success = self._scheduler.set_priority(task_id)
            if success:
                logger.info(f"任务 {task_id} 已设置为插队任务")
                return True
            else:
                logger.error(f"调度器设置插队任务失败: {task_id}")
                return False
        else:
            logger.warning("调度器未初始化")
            return False

    async def delete_task(self, task_id: str) -> bool:
        """
        删除任务

        Args:
            task_id: 任务ID

        Returns:
            是否删除成功
        """
        task = self._tasks.get(task_id)
        
        # 如果任务在内存中
        if task:
            if task.status == AsyncTaskStatus.RUNNING:
                await self.cancel_task(task_id)

            # 删除相关视频文件
            output_path = getattr(task, 'output_path', None)
            if output_path:
                try:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                        logger.info(f"已删除最终输出视频: {output_path}")
                except PermissionError as e:
                    logger.warning(f"跳过被占用的文件: {output_path}, 错误: {e}")
                except Exception as e:
                    logger.warning(f"删除最终输出视频失败: {output_path}, 错误: {e}")

            # 删除中间文件
            await self.cleanup_task_files(task_id, getattr(task, 'output_path', None), task_failed=False)

            del self._tasks[task_id]
            self.unregister_callback(task_id)
        else:
            # 任务不在内存中，从数据库读取并清理
            logger.info(f"任务 {task_id} 不在内存中，从数据库清理")
            
            if self._db_initialized and self._db:
                # 从数据库读取任务信息获取 output_path
                try:
                    task_data = await self._db.task_get_by_id(task_id)
                    if task_data:
                        output_path = task_data.get('output_path')
                        if output_path and os.path.exists(output_path):
                            try:
                                os.remove(output_path)
                                logger.info(f"已删除最终输出视频: {output_path}")
                            except PermissionError as e:
                                logger.warning(f"跳过被占用的文件: {output_path}, 错误: {e}")
                            except Exception as e:
                                logger.warning(f"删除最终输出视频失败: {output_path}, 错误: {e}")
                        
                        # 清理中间文件
                        await self.cleanup_task_files(task_id, output_path, task_failed=False)
                except Exception as e:
                    logger.error(f"从数据库读取任务 {task_id} 失败: {e}")

        # 从数据库删除任务
        if self._db_initialized and self._db:
            try:
                await self._db.task_delete(task_id)
                logger.info(f"任务 {task_id} 已从数据库删除")
            except Exception as e:
                logger.error(f"从数据库删除任务 {task_id} 失败: {e}")

        logger.info(f"任务 {task_id} 已删除")
        return True

    async def _notify_status_change(self, task_id: str):
        """通知状态变化"""
        callback = self._get_callback(task_id)
        if callback and callback.on_status_change:
            task = self._tasks.get(task_id)
            if task:
                try:
                    if asyncio.iscoroutinefunction(callback.on_status_change):
                        await callback.on_status_change(task_id, task)
                    else:
                        callback.on_status_change(task_id, task)
                except Exception as e:
                    logger.error(f"状态变化回调执行失败: {e}")

    async def _notify_progress(self, task_id: str):
        """通知进度更新"""
        callback = self._get_callback(task_id)
        if callback and callback.on_progress:
            task = self._tasks.get(task_id)
            if task:
                try:
                    if asyncio.iscoroutinefunction(callback.on_progress):
                        await callback.on_progress(task_id, task.progress, task.current_stage)
                    else:
                        callback.on_progress(task_id, task.progress, task.current_stage)
                except Exception as e:
                    logger.error(f"进度回调执行失败: {e}")

    def shutdown(self):
        """关闭服务

        无论哪种模式，退出系统都需要：
        1. 卸载所有引擎释放显存
        2. 清理 CUDA 缓存
        3. 结束后台进程
        """
        logger.info("正在关闭工作流服务...")

        # 取消所有运行中的任务
        for task_id, task in list(self._tasks.items()):
            if task.status == AsyncTaskStatus.RUNNING:
                if task.cancel_event:
                    task.cancel_event.set()

        # 等待线程池完成
        self._executor.shutdown(wait=True)

        # 关闭所有工作流
        for task_id, workflow in self._workflows.items():
            try:
                workflow.close()
            except Exception as e:
                logger.error(f"关闭工作流 {task_id} 失败: {e}")

        # 卸载所有引擎（无论哪种模式）
        logger.info("卸载所有引擎...")
        try:
            from core.engines.gpu_manager import get_gpu_manager, EngineType, reset_gpu_manager
            gpu_manager = get_gpu_manager()
            if gpu_manager:
                # 卸载 TTS 引擎
                tts_engine = gpu_manager.get_engine(EngineType.TTS)
                if tts_engine and tts_engine.is_loaded:
                    tts_engine.unload()
                    logger.info("TTS 引擎已卸载")

                # 卸载 HeyGem 引擎
                heygem_engine = gpu_manager.get_engine(EngineType.HEYGEM)
                if heygem_engine and heygem_engine.is_loaded:
                    heygem_engine.unload()
                    logger.info("HeyGem 引擎已卸载")

                # 重置 GPU 管理器
                reset_gpu_manager()
                logger.info("GPU 管理器已重置")
        except Exception as e:
            logger.error(f"卸载引擎失败: {e}")
            # 备用方案：直接卸载引擎实例
            try:
                if self.tts_engine and self.tts_engine.is_loaded:
                    self.tts_engine.unload()
                    logger.info("TTS 引擎已卸载（备用方案）")
            except Exception as e2:
                logger.error(f"备用卸载 TTS 引擎失败: {e2}")

            try:
                if self.heygem_engine and self.heygem_engine.is_loaded:
                    self.heygem_engine.unload()
                    logger.info("HeyGem 引擎已卸载（备用方案）")
            except Exception as e2:
                logger.error(f"备用卸载 HeyGem 引擎失败: {e2}")

        # 清理 CUDA 缓存
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("CUDA 缓存已清理")
        except ImportError:
            pass

        # 清理 TransDhTask 单例（如果存在）
        try:
            import sys
            if 'engines.heygem.service.trans_dh_service' in sys.modules:
                from engines.heygem.service.trans_dh_service import TransDhTask
                if hasattr(TransDhTask, '_instance') and TransDhTask._instance is not None:
                    TransDhTask._instance.cleanup()
                    logger.info("TransDhTask 单例已清理")
        except Exception as e:
            logger.error(f"清理 TransDhTask 单例失败: {e}")

        self._tasks.clear()
        self._workflows.clear()
        self._callbacks.clear()

        logger.info("工作流服务已关闭")

    async def recover_incomplete_tasks(self) -> List[str]:
        """
        恢复所有任务（用于服务重启）
        
        核心原则：断电、死机、结束后台等瞬间终止情况，系统无法执行任何保存逻辑。
        因此任务记录必须在启动时就持久化到数据库。
        
        实现方案：
        - 任务创建时已持久化到数据库（现有机制）
        - 系统启动时检测数据库中未完成的任务（状态为 running、pending、queued）
        - 将这些任务状态重置为 pending，显示在待运行列表
        - 用户可从检查点重启任务，或删除任务

        Returns:
            恢复的任务ID列表
        """
        if not self._db_initialized or not self._db:
            logger.warning("数据库未初始化，无法恢复任务")
            return []

        try:
            all_tasks_from_db, _ = await self._db.task_list(limit=1000, offset=0)
            recovered_ids = []
            reset_ids = []

            for task_data in all_tasks_from_db:
                task_id = task_data['task_id']

                if task_id in self._tasks:
                    continue

                original_status = task_data['status']
                needs_reset = original_status in ['running', 'queued', 'processing']
                
                if needs_reset:
                    task_data['status'] = 'pending'
                    reset_ids.append(task_id)
                    logger.info(f"任务 {task_id} 状态从 {original_status} 重置为 pending")

                task = AsyncTask(
                    task_id=task_id,
                    name=task_data['name'],
                    status=AsyncTaskStatus(task_data['status']),
                    progress=task_data['progress'],
                    current_stage=task_data.get('current_stage', ''),
                    source_video_path=task_data.get('source_video_path', ''),
                    script_text=task_data.get('script_text', ''),
                    topic=task_data.get('topic', ''),
                    output_path=task_data.get('output_path', ''),
                    error_message=task_data.get('error_message', ''),
                    prompt_audio_path=task_data.get('prompt_audio_path', ''),
                    left_prompt_audio_path=task_data.get('left_prompt_audio_path', ''),
                    right_prompt_audio_path=task_data.get('right_prompt_audio_path', ''),
                    bgm_path=task_data.get('bgm_path', ''),
                    use_llm_generate=bool(task_data.get('use_llm_generate', False)),
                    enable_postprocess=bool(task_data.get('enable_postprocess', True)),
                    opening_video=task_data.get('opening_video'),
                    loop_videos=json.loads(task_data['loop_videos']) if task_data.get('loop_videos') else [],
                    scene_videos=json.loads(task_data['scene_videos']) if task_data.get('scene_videos') else [],
                    ending_video=task_data.get('ending_video'),
                    opening_video_with_tags=json.loads(task_data['opening_video_with_tags']) if task_data.get('opening_video_with_tags') else None,
                    loop_videos_with_tags=json.loads(task_data['loop_videos_with_tags']) if task_data.get('loop_videos_with_tags') else [],
                    scene_videos_with_tags=json.loads(task_data['scene_videos_with_tags']) if task_data.get('scene_videos_with_tags') else [],
                    ending_video_with_tags=json.loads(task_data['ending_video_with_tags']) if task_data.get('ending_video_with_tags') else None
                )

                if task_data.get('created_at'):
                    task.created_at = datetime.fromisoformat(task_data['created_at'])
                if task_data.get('updated_at'):
                    task.updated_at = datetime.fromisoformat(task_data['updated_at'])
                if task_data.get('completed_at'):
                    task.completed_at = datetime.fromisoformat(task_data['completed_at'])

                config_dict = json.loads(task_data['config']) if task_data.get('config') else {}
                if config_dict:
                    task.config = TaskConfig.from_dict(config_dict)

                self._tasks[task_id] = task
                recovered_ids.append(task_id)
                logger.info(f"已恢复任务: {task_id}, 状态: {task.status}")

            if reset_ids:
                logger.info(f"共 {len(reset_ids)} 个未完成任务状态已重置为 pending")
                for task_id in reset_ids:
                    try:
                        await self._db.task_update(
                            task_id=task_id,
                            status="pending"
                        )
                    except Exception as e:
                        logger.error(f"更新任务 {task_id} 状态失败: {e}")

            if recovered_ids:
                logger.info(f"共恢复 {len(recovered_ids)} 个任务")
                self._tasks_loaded_from_db = True

            return recovered_ids

        except Exception as e:
            logger.error(f"恢复任务失败: {e}")
            return []

    async def retry_failed_task(self, task_id: str) -> bool:
        """
        重试失败的任务

        Args:
            task_id: 任务ID

        Returns:
            是否重试成功
        """
        if not self._db_initialized or not self._db:
            logger.warning("数据库未初始化，无法重试任务")
            return False

        task = self._tasks.get(task_id)
        if not task:
            task_data = await self._db.task_get_by_id(task_id)
            if not task_data:
                logger.error(f"任务 {task_id} 不存在")
                return False

            task = AsyncTask(
                task_id=task_id,
                name=task_data['name'],
                status=AsyncTaskStatus(task_data['status']),
                progress=task_data['progress'],
                current_stage=task_data.get('current_stage', ''),
                source_video_path=task_data.get('source_video_path', ''),
                script_text=task_data.get('script_text', ''),
                topic=task_data.get('topic', ''),
                output_path=task_data.get('output_path', ''),
                error_message=task_data.get('error_message', ''),
                prompt_audio_path=task_data.get('prompt_audio_path', ''),
                left_prompt_audio_path=task_data.get('left_prompt_audio_path', ''),
                right_prompt_audio_path=task_data.get('right_prompt_audio_path', ''),
                bgm_path=task_data.get('bgm_path', ''),
                use_llm_generate=bool(task_data.get('use_llm_generate', False)),
                enable_postprocess=bool(task_data.get('enable_postprocess', True)),
                opening_video=task_data.get('opening_video'),
                loop_videos=json.loads(task_data['loop_videos']) if task_data.get('loop_videos') else [],
                scene_videos=json.loads(task_data['scene_videos']) if task_data.get('scene_videos') else [],
                ending_video=task_data.get('ending_video'),
                opening_video_with_tags=json.loads(task_data['opening_video_with_tags']) if task_data.get('opening_video_with_tags') else None,
                loop_videos_with_tags=json.loads(task_data['loop_videos_with_tags']) if task_data.get('loop_videos_with_tags') else [],
                scene_videos_with_tags=json.loads(task_data['scene_videos_with_tags']) if task_data.get('scene_videos_with_tags') else [],
                ending_video_with_tags=json.loads(task_data['ending_video_with_tags']) if task_data.get('ending_video_with_tags') else None
            )

            config_dict = json.loads(task_data['config']) if task_data.get('config') else {}
            if config_dict:
                task.config = TaskConfig.from_dict(config_dict)

            self._tasks[task_id] = task

        if task.status == AsyncTaskStatus.RUNNING:
            logger.warning(f"任务 {task_id} 正在运行中，无法重试")
            return False

        task.status = AsyncTaskStatus.PENDING
        task.progress = 0.0
        task.error_message = None
        task.current_stage = "等待重试"
        task.updated_at = datetime.now()

        if self._db_initialized and self._db:
            await self._db.task_update(
                task_id=task_id,
                status="pending",
                progress=0.0,
                current_stage="等待重试",
                error_message=None
            )

        asyncio.create_task(self.start_task(task_id))
        logger.info(f"任务 {task_id} 正在重试")

        return True

    async def restart_from_checkpoint(self, task_id: str) -> bool:
        """
        从检查点重启任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否重启成功
        """
        if not self._db_initialized or not self._db:
            logger.warning("数据库未初始化，无法从检查点重启")
            return False
        
        task = self._tasks.get(task_id)
        if not task:
            task_data = await self._db.task_get_by_id(task_id)
            if not task_data:
                logger.error(f"任务 {task_id} 不存在")
                return False
            
            task = AsyncTask(
                task_id=task_id,
                name=task_data['name'],
                status=AsyncTaskStatus(task_data['status']),
                progress=task_data['progress'],
                current_stage=task_data.get('current_stage', ''),
                source_video_path=task_data.get('source_video_path', ''),
                script_text=task_data.get('script_text', ''),
                topic=task_data.get('topic', ''),
                output_path=task_data.get('output_path', ''),
                error_message=task_data.get('error_message', ''),
                prompt_audio_path=task_data.get('prompt_audio_path', ''),
                left_prompt_audio_path=task_data.get('left_prompt_audio_path', ''),
                right_prompt_audio_path=task_data.get('right_prompt_audio_path', ''),
                bgm_path=task_data.get('bgm_path', ''),
                use_llm_generate=bool(task_data.get('use_llm_generate', False)),
                enable_postprocess=bool(task_data.get('enable_postprocess', True)),
                opening_video=task_data.get('opening_video'),
                loop_videos=json.loads(task_data['loop_videos']) if task_data.get('loop_videos') else [],
                scene_videos=json.loads(task_data['scene_videos']) if task_data.get('scene_videos') else [],
                ending_video=task_data.get('ending_video'),
                opening_video_with_tags=json.loads(task_data['opening_video_with_tags']) if task_data.get('opening_video_with_tags') else None,
                loop_videos_with_tags=json.loads(task_data['loop_videos_with_tags']) if task_data.get('loop_videos_with_tags') else [],
                scene_videos_with_tags=json.loads(task_data['scene_videos_with_tags']) if task_data.get('scene_videos_with_tags') else [],
                ending_video_with_tags=json.loads(task_data['ending_video_with_tags']) if task_data.get('ending_video_with_tags') else None
            )
            
            config_dict = json.loads(task_data['config']) if task_data.get('config') else {}
            if config_dict:
                task.config = TaskConfig.from_dict(config_dict)
            
            self._tasks[task_id] = task
        
        if task.status == AsyncTaskStatus.RUNNING:
            logger.warning(f"任务 {task_id} 正在运行中，无法从检查点重启")
            return False
        
        checkpoint_json = await self._db.checkpoint_load(task_id)
        if not checkpoint_json:
            logger.info(f"任务 {task_id} 没有检查点数据，将从头开始")
            return await self.retry_failed_task(task_id)
        
        from core.models.checkpoint import CheckpointData
        checkpoint = CheckpointData.from_json(checkpoint_json)
        logger.info(f"任务 {task_id} 从检查点重启，阶段: {checkpoint.current_stage}")
        
        task.status = AsyncTaskStatus.PENDING
        task.progress = checkpoint.progress
        task.current_stage = f"从 {checkpoint.current_stage} 恢复"
        task.error_message = None
        task.updated_at = datetime.now()
        
        await self._db.task_update(
            task_id=task_id,
            status="pending",
            progress=checkpoint.progress,
            current_stage=f"从 {checkpoint.current_stage} 恢复",
            error_message=None
        )
        
        asyncio.create_task(self.start_task(task_id, existing_task_id=task_id))
        logger.info(f"任务 {task_id} 正在从检查点重启")
        
        return True

    async def extract_audio_from_video(self, video_id: str) -> Dict[str, Any]:
        """
        从视频中提取音频

        Args:
            video_id: 视频ID

        Returns:
            提取的音频信息
        """
        try:
            workflow = self._create_workflow()
            audio_info = workflow.extract_audio(video_id)
            return audio_info
        except Exception as e:
            logger.error(f"音频提取失败: {e}")
            raise

    async def denoise_audio(self, audio_id: str) -> Dict[str, Any]:
        """
        音频降噪

        Args:
            audio_id: 音频ID

        Returns:
            降噪后的音频信息
        """
        try:
            workflow = self._create_workflow()
            audio_info = workflow.denoise_audio(audio_id)
            return audio_info
        except Exception as e:
            logger.error(f"音频降噪失败: {e}")
            raise

    async def analyze_face(self, video_id: str) -> Dict[str, Any]:
        """
        面部分析

        Args:
            video_id: 视频ID

        Returns:
            面部分析结果
        """
        try:
            workflow = self._create_workflow()
            analysis_result = workflow.analyze_face(video_id)
            return analysis_result
        except Exception as e:
            logger.error(f"面部分析失败: {e}")
            raise

    def get_task_temp_dirs(self, task_id: str) -> List[str]:
        """
        获取任务相关的临时目录列表

        Args:
            task_id: 任务ID

        Returns:
            临时目录路径列表
        """
        project_root = Path(__file__).parent.parent.parent.parent

        temp_dirs = [
            str(project_root / "output" / "temp" / "audio"),
            str(project_root / "output" / "temp" / "video"),
            str(project_root / "voicel" / "outputs"),
            str(project_root / "voicel" / "tmp"),
            str(project_root / "Portrait" / "生成结果"),
            str(project_root / "Portrait" / "temp"),
            str(project_root / "Portrait" / "tmp"),
            str(project_root / "Portrait" / "change"),
            str(project_root / "backend" / "temp"),
            str(project_root / "backend" / "tmp"),
            # 添加 heygem temp 目录
            str(project_root / "engines" / "heygem" / "temp"),
        ]

        return [d for d in temp_dirs if os.path.exists(d)]

    def cleanup_task_temp_files(self, task_id: str, directory: str) -> int:
        """
        清理目录中与任务相关的临时文件

        Args:
            task_id: 任务ID
            directory: 目录路径

        Returns:
            删除的文件数量
        """
        if not os.path.exists(directory):
            return 0
        
        deleted_count = 0
        
        try:
            for filename in os.listdir(directory):
                if task_id in filename:
                    file_path = os.path.join(directory, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            deleted_count += 1
                            logger.debug(f"已删除临时文件: {file_path}")
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path, ignore_errors=True)
                            deleted_count += 1
                            logger.debug(f"已删除临时目录: {file_path}")
                    except PermissionError as e:
                        logger.warning(f"跳过被占用的文件: {file_path}, 错误: {e}")
                    except Exception as e:
                        logger.warning(f"删除文件失败: {file_path}, 错误: {e}")
        except Exception as e:
            logger.error(f"清理目录失败: {directory}, 错误: {e}")
        
        return deleted_count

    def _cleanup_heygem_temp_dir(self, directory: str) -> int:
        """
        清理 heygem temp 目录中的所有文件

        Args:
            directory: heygem temp 目录路径

        Returns:
            删除的文件数量
        """
        if not os.path.exists(directory):
            return 0

        deleted_count = 0

        try:
            for filename in os.listdir(directory):
                file_path = os.path.join(directory, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        deleted_count += 1
                        logger.debug(f"已清理 heygem temp 文件: {file_path}")
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path, ignore_errors=True)
                        deleted_count += 1
                        logger.debug(f"已清理 heygem temp 目录: {file_path}")
                except PermissionError as e:
                    logger.warning(f"跳过被占用的文件: {file_path}, 错误: {e}")
                except Exception as e:
                    logger.warning(f"删除文件失败: {file_path}, 错误: {e}")
        except Exception as e:
            logger.error(f"清理 heygem temp 目录失败: {directory}, 错误: {e}")

        return deleted_count

    async def cleanup_task_files(
        self,
        task_id: str,
        output_path: Optional[str],
        temp_dirs: Optional[List[str]] = None,
        task_failed: bool = False
    ) -> bool:
        """
        清理任务完成后的检查点和中间文件

        Args:
            task_id: 任务ID
            output_path: 最终输出文件路径
            temp_dirs: 需要清理的临时目录列表
            task_failed: 任务是否失败

        Returns:
            是否清理成功
        """
        if task_failed:
            logger.info(f"任务 {task_id} 失败，保留检查点数据以支持断点续传")
            return True
        
        deleted_files = 0
        
        # 先读取检查点数据，删除任务执行过程中生成的中间文件
        # 注意：只删除生成的中间文件，不删除用户上传的素材
        if self._db_initialized and self._db:
            try:
                checkpoint_json = await self._db.checkpoint_load(task_id)
                if checkpoint_json:
                    from core.models.checkpoint import CheckpointData
                    checkpoint = CheckpointData.from_json(checkpoint_json)
                    
                    # 只删除任务执行过程中生成的中间文件
                    files_to_delete = []
                    
                    # 音频路径 - 任务生成的音频文件
                    if checkpoint.audio_paths:
                        files_to_delete.extend([p for p in checkpoint.audio_paths.values() if p])
                    
                    # 视频路径 - 任务生成的视频片段
                    if checkpoint.video_paths:
                        files_to_delete.extend([p for p in checkpoint.video_paths.values() if p])
                    
                    # 双人模式中间文件
                    if hasattr(checkpoint, 'double_mode_files') and checkpoint.double_mode_files:
                        files_to_delete.extend([p for p in checkpoint.double_mode_files if p])
                        logger.info(f"双人模式中间文件: {len(checkpoint.double_mode_files)} 个")
                    
                    # 字幕文件
                    if hasattr(checkpoint, 'subtitle_path') and checkpoint.subtitle_path:
                        files_to_delete.append(checkpoint.subtitle_path)
                        logger.info(f"字幕文件: {checkpoint.subtitle_path}")
                    
                    # 标签组中间文件
                    if hasattr(checkpoint, 'tag_groups') and checkpoint.tag_groups:
                        for tg in checkpoint.tag_groups:
                            if hasattr(tg, 'intermediate_files') and tg.intermediate_files:
                                files_to_delete.extend([p for p in tg.intermediate_files if p])
                    
                    # 获取最终输出视频路径，避免误删
                    final_output_path = output_path
                    
                    # 删除文件
                    for file_path in files_to_delete:
                        if file_path and os.path.exists(file_path):
                            # 检查是否是最终输出视频
                            if final_output_path and os.path.abspath(file_path) == os.path.abspath(final_output_path):
                                logger.info(f"跳过最终输出视频: {file_path}")
                                continue
                            try:
                                os.remove(file_path)
                                deleted_files += 1
                                logger.debug(f"已删除中间文件: {file_path}")
                            except PermissionError as e:
                                logger.warning(f"跳过被占用的文件: {file_path}, 错误: {e}")
                            except Exception as e:
                                logger.warning(f"删除文件失败: {file_path}, 错误: {e}")
                    
                    if deleted_files > 0:
                        logger.info(f"从检查点删除 {deleted_files} 个中间文件")
            except Exception as e:
                logger.error(f"读取检查点数据失败: {task_id}, 错误: {e}")
        
        # 清理临时目录中包含 task_id 的文件
        if temp_dirs is None:
            temp_dirs = self.get_task_temp_dirs(task_id)

        for directory in temp_dirs:
            deleted_files += self.cleanup_task_temp_files(task_id, directory)

        # 清理 heygem temp 目录中的临时文件
        try:
            from pathlib import Path
            # 修复路径：__file__ 位于 backend/api/services/workflow_service.py
            # 需要向上4级到达项目根目录，然后进入 engines/heygem/temp
            heygem_temp_dir = Path(__file__).parent.parent.parent.parent / "engines" / "heygem" / "temp"
            if heygem_temp_dir.exists():
                heygem_deleted = self._cleanup_heygem_temp_dir(str(heygem_temp_dir))
                if heygem_deleted > 0:
                    deleted_files += heygem_deleted
                    logger.info(f"已清理 heygem temp 目录: {heygem_deleted} 个文件")
        except Exception as e:
            logger.warning(f"清理 heygem temp 目录失败: {e}")

        # 清除检查点记录
        if self._db_initialized and self._db:
            try:
                await self._db.checkpoint_clear(task_id)
                logger.info(f"任务 {task_id} 检查点已清除")
            except Exception as e:
                logger.error(f"清除检查点失败: {task_id}, 错误: {e}")
        
        logger.info(f"任务 {task_id} 清理完成: 删除 {deleted_files} 个文件")
        return True


_global_service: Optional[WorkflowService] = None


def get_workflow_service() -> Optional[WorkflowService]:
    """
    获取全局工作流服务实例

    Returns:
        WorkflowService 实例，如果未初始化则返回 None
    """
    global _global_service
    return _global_service


async def init_workflow_service(
    tts_engine=None,
    heygem_engine=None,
    llm_provider: str = "astron",
    llm_api_key: Optional[str] = None,
    output_dir: str = "output",
    max_concurrent_tasks: int = 3,
    database: Optional[DatabaseService] = None,
    low_memory_mode: Optional[bool] = None
) -> WorkflowService:
    """
    初始化全局工作流服务

    Args:
        tts_engine: TTSEngine 实例（如未指定，从配置创建）
        heygem_engine: HeyGemEngine 实例（如未指定，从配置创建）
        llm_provider: LLM 提供商
        llm_api_key: LLM API 密钥（如未指定，从配置文件读取）
        output_dir: 输出目录
        max_concurrent_tasks: 最大并发任务数
        database: 数据库服务实例
        low_memory_mode: 是否启用低显存模式（如未指定，从系统配置读取）

    Returns:
        WorkflowService 实例
    """
    global _global_service

    api_config = load_api_keys_config()

    if llm_api_key is None:
        llm_api_key = api_config.get("deepseek_api_key", "")

    aliyun_api_key = api_config.get("aliyun_api_key", "")

    # 读取低显存模式配置
    if low_memory_mode is None:
        try:
            from core.system_config import get_config_manager
            config_manager = get_config_manager()
            low_memory_mode = config_manager.get_low_memory_mode()
            ultra_low_memory = config_manager.get_ultra_low_memory()
        except Exception as e:
            logger.warning(f"读取低显存模式配置失败，使用默认值: {e}")
            low_memory_mode = False
            ultra_low_memory = False

    # 如果未提供引擎，从配置创建（强制使用 preload_model=False，避免阻塞事件循环）
    if tts_engine is None or heygem_engine is None:
        from core.engines import create_engines_from_config
        # 始终使用 preload_model=False，引擎将在后台线程中加载
        engines = create_engines_from_config(
            low_memory_mode=True,  # 强制不预加载
            ultra_low_memory=ultra_low_memory
        )
        tts_engine = tts_engine or engines.get("tts_engine")
        heygem_engine = heygem_engine or engines.get("heygem_engine")
        logger.info(f"引擎已创建（延迟加载模式），将在后台线程中加载模型，超低显存模式: {ultra_low_memory}")

    if _global_service is not None:
        _global_service.shutdown()

    _global_service = WorkflowService(
        tts_engine=tts_engine,
        heygem_engine=heygem_engine,
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        aliyun_api_key=aliyun_api_key,
        output_dir=output_dir,
        max_concurrent_tasks=max_concurrent_tasks,
        low_memory_mode=low_memory_mode
    )

    try:
        main_loop = asyncio.get_running_loop()
        _global_service.set_main_loop(main_loop)
    except RuntimeError:
        logger.warning("无法获取运行中的事件循环，进度更新可能无法正常工作")

    if database:
        await _global_service.set_database(database)

        # 恢复未完成的任务（断点续传）
        try:
            recovered = await _global_service.recover_incomplete_tasks()
            if recovered:
                logger.info(f"已恢复 {len(recovered)} 个未完成任务")
        except Exception as e:
            logger.error(f"恢复未完成任务失败: {e}")

    # 在后台线程中加载引擎模型（不阻塞事件循环）
    if not low_memory_mode:
        import threading
        def load_models_background():
            try:
                logger.info("后台线程开始加载引擎模型...")
                if tts_engine and hasattr(tts_engine, 'load'):
                    tts_engine.load()
                    logger.info("TTSEngine 模型加载完成")
                if heygem_engine and hasattr(heygem_engine, 'load'):
                    heygem_engine.load()
                    logger.info("HeyGemEngine 模型加载完成")
                logger.info("所有引擎模型后台加载完成")
            except Exception as e:
                logger.error(f"后台加载引擎模型失败: {e}")

        load_thread = threading.Thread(target=load_models_background, daemon=True)
        load_thread.start()
        logger.info("引擎模型后台加载线程已启动")

    logger.info(f"全局工作流服务已初始化（引擎模式），低显存模式: {low_memory_mode}")
    return _global_service


async def shutdown_workflow_service():
    """关闭全局工作流服务"""
    global _global_service

    if _global_service is not None:
        _global_service.shutdown()
        _global_service = None
        logger.info("全局工作流服务已关闭")
