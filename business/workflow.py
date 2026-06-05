"""
数字人视频生成工作流
整合所有模块，实现完整的视频生成流程
"""

import asyncio
import json
import logging
import os
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
import yaml

from core.models.task import Task, TaskStatus, TaskConfig, ScriptSegment, SceneType
from core.monitor import ResourceMonitor, get_monitor
from core.engines import create_engines_from_config
from core.paths import get_path_manager, init_path_manager
from business.preprocess import VideoPreprocessor, quick_check_video
from business.llm import ScriptParser, create_script_parser
from business.llm.llm_generator import LLMScriptGenerator
from business.audio import AudioProcessor, create_audio_processor
from business.video import VideoSynthesizer, create_video_synthesizer
from business.postprocess import PostProcessor, create_post_processor
from api.services.database import get_database_service

logger = logging.getLogger(__name__)

PROMPT_TEMPLATES_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "config", "prompt_templates.yaml")


def calculate_progress(
    stage: str,
    completed_items: int,
    total_items: int,
    sub_stage: str = None
) -> float:
    """
    计算任务进度

    Args:
        stage: 当前阶段（script/audio/video/postprocess）
        completed_items: 已完成的项目数
        total_items: 总项目数
        sub_stage: 子阶段（subtitle/bgm/cover）

    Returns:
        进度百分比（0-100）
    """
    stage_ranges = {
        "script": (0, 10),
        "audio": (10, 40),
        "video": (40, 85),
        "postprocess": (85, 100)
    }

    # 后期处理子阶段细分
    if stage == "postprocess" and sub_stage:
        sub_ranges = {
            "subtitle": (85, 90),
            "bgm": (90, 95),
            "cover": (95, 100),
            "merge": (85, 100)
        }
        sub_start, sub_end = sub_ranges.get(sub_stage, (85, 100))
        return min(100, max(0, sub_start))

    start, end = stage_ranges.get(stage, (0, 100))

    if total_items > 0:
        stage_progress = completed_items / total_items
        progress = start + (end - start) * stage_progress
    else:
        progress = start

    return min(100, max(0, round(progress, 1)))


def build_stage_description(
    stage: str,
    completed_items: int,
    total_items: int,
    current_tag: str = None,
    sub_stage: str = None
) -> str:
    """
    构建阶段描述

    Args:
        stage: 当前阶段
        completed_items: 已完成的项目数
        total_items: 总项目数
        current_tag: 当前处理的标签
        sub_stage: 子阶段

    Returns:
        阶段描述字符串
    """
    if stage == "script":
        return "文案生成中..."

    if stage == "audio":
        if current_tag:
            return f"语音合成中 ({completed_items}/{total_items}) - 处理标签：{current_tag}"
        return f"语音合成中 ({completed_items}/{total_items})"

    if stage == "video":
        if current_tag:
            return f"视频生成中 ({completed_items}/{total_items}) - 处理标签：{current_tag}"
        return f"视频生成中 ({completed_items}/{total_items})"

    if stage == "postprocess":
        sub_descriptions = {
            "subtitle": "添加字幕...",
            "bgm": "添加 BGM...",
            "cover": "生成封面...",
            "merge": "合并视频..."
        }
        return sub_descriptions.get(sub_stage, "后期处理中...")

    if stage == "completed":
        return "任务完成"

    return "处理中..."


@dataclass
class WorkflowResult:
    """工作流结果"""
    task_id: str
    status: str  # success, failed
    output_path: Optional[str] = None
    error_message: Optional[str] = None
    segments_completed: int = 0
    total_segments: int = 0


class DigitalHumanWorkflow:
    """数字人视频生成工作流"""

    def __init__(
        self,
        tts_engine=None,
        heygem_engine=None,
        llm_config: Optional[Dict] = None,
        output_dir: str = "output",
        low_memory_mode: bool = False
    ):
        """
        初始化工作流

        Args:
            tts_engine: TTSEngine 实例
            heygem_engine: HeyGemEngine 实例
            llm_config: LLM 配置
            output_dir: 输出目录（已废弃，使用路径管理器）
            low_memory_mode: 是否启用低显存模式（开启时阶段完成后卸载模型）
        """
        self.tts_engine = tts_engine
        self.heygem_engine = heygem_engine
        self.llm_config = llm_config or {}
        self.low_memory_mode = low_memory_mode

        # 初始化路径管理器
        self.path_manager = get_path_manager()

        # 使用路径管理器的目录
        self.output_dir = self.path_manager.output_dir
        self.audio_temp_dir = self.path_manager.audio_temp_dir
        self.video_temp_dir = self.path_manager.video_temp_dir
        self.final_output_dir = self.path_manager.final_output_dir

        # 初始化各模块（使用绝对路径）
        self.video_preprocessor = VideoPreprocessor()
        self.llm_generator = LLMScriptGenerator(
            provider=self.llm_config.get("provider", "astron"),
            api_key=self.llm_config.get("api_key", ""),
            model=self.llm_config.get("model", "astron-code-latest")
        )
        self.script_parser = create_script_parser()
        self.audio_processor = create_audio_processor(
            tts_engine=self.tts_engine,
            output_dir=self.audio_temp_dir,
            enable_denoise=False  # 降噪由用户手动执行，不再自动执行
        )
        self.video_synthesizer = create_video_synthesizer(
            heygem_engine=self.heygem_engine,
            output_dir=self.video_temp_dir
        )
        self.post_processor = create_post_processor(
            intermediate_dir=self.output_dir,
            output_dir=self.final_output_dir
        )

        self.resource_monitor = get_monitor()

        self.db = None
        logger.info(f"数字人工作流初始化完成（引擎模式），低显存模式: {low_memory_mode}")
    
    def set_database(self, db):
        """设置数据库实例用于断点续传"""
        self.db = db

    async def run_async(
        self,
        source_video_path: str,
        script_text: str = "",
        topic: str = "",
        prompt_audio_path: str = "",
        left_prompt_audio_path: str = "",
        right_prompt_audio_path: str = "",
        bgm_path: str = "",
        config: Optional[TaskConfig] = None,
        use_llm_generate: bool = False,
        enable_postprocess: bool = True,
        opening_video: Optional[str] = None,
        loop_videos: Optional[List[str]] = None,
        scene_videos: Optional[List[str]] = None,
        ending_video: Optional[str] = None,
        opening_video_with_tags: Optional[Dict] = None,
        loop_videos_with_tags: Optional[List[Dict]] = None,
        scene_videos_with_tags: Optional[List[Dict]] = None,
        ending_video_with_tags: Optional[Dict] = None,
        scene_tag_group_id: Optional[int] = None,
        cancel_callback: Optional[callable] = None,
        existing_task_id: Optional[str] = None,
        progress_callback: Optional[callable] = None,
        # 画外音参数
        enable_pip: bool = False,
        pip_video_path: Optional[str] = None,
        pip_left_video_path: Optional[str] = None,
        pip_right_video_path: Optional[str] = None
    ) -> WorkflowResult:
        """
        运行完整的视频生成流程

        Args:
            source_video_path: 源视频路径
            script_text: 文案文本（可选）
            topic: 主题（用于 LLM 生成文案）
            prompt_audio_path: 音色参考音频路径（单人模式）
            left_prompt_audio_path: 左边说话人音色参考音频（双人模式）
            right_prompt_audio_path: 右边说话人音色参考音频（双人模式）
            bgm_path: BGM 音频路径
            config: 任务配置
            use_llm_generate: 是否使用 LLM 生成文案
            enable_postprocess: 是否启用后期处理

        Returns:
            工作流结果
        """
        if config is None:
            config = TaskConfig()

        # 检查系统资源
        if not self.resource_monitor.is_resources_available():
            status = self.resource_monitor.get_all_status()
            warning_parts = []
            if status.gpu_count > 0 and status.gpu_memory_percent > self.resource_monitor.gpu_memory_threshold:
                warning_parts.append(f"GPU显存({status.gpu_memory_percent:.1f}%)")
            if status.cpu_percent > self.resource_monitor.cpu_threshold:
                warning_parts.append(f"CPU({status.cpu_percent:.1f}%)")
            if status.memory_percent > self.resource_monitor.memory_threshold:
                warning_parts.append(f"内存({status.memory_percent:.1f}%)")
            warning_msg = ", ".join(warning_parts) if warning_parts else "系统资源紧张"
            logger.warning(f"系统资源不足，任务可能受影响：{warning_msg}")
            logger.info(f"资源详情：{self.resource_monitor.get_stats_summary()}")

        from core.models.task import VideoWithTag
        
        # 检查是否从检查点恢复
        task = None
        checkpoint = None
        skip_to_stage = None
        
        logger.info(f"检查点恢复检查: existing_task_id={existing_task_id}, db={self.db is not None}")
        
        if existing_task_id and self.db:
            logger.info(f"尝试加载检查点: {existing_task_id}")
            checkpoint = self.load_task_checkpoint(existing_task_id)
            if checkpoint:
                logger.info(f"从检查点恢复任务: {existing_task_id}, 阶段: {checkpoint.current_stage}")
                skip_to_stage = checkpoint.current_stage
            else:
                logger.info(f"未找到检查点，使用现有任务ID: {existing_task_id}")
        elif existing_task_id and not self.db:
            logger.warning(f"数据库实例未初始化，无法加载检查点: {existing_task_id}")
        
        # 创建或恢复任务
        if task is None:
            # 如果有检查点数据，优先使用检查点中的路径
            if checkpoint:
                source_video_path = checkpoint.source_video_path or source_video_path
                prompt_audio_path = checkpoint.prompt_audio_path or prompt_audio_path
                left_prompt_audio_path = checkpoint.left_prompt_audio_path or left_prompt_audio_path
                right_prompt_audio_path = checkpoint.right_prompt_audio_path or right_prompt_audio_path
                bgm_path = checkpoint.bgm_path or bgm_path
                logger.info(f"从检查点恢复路径: source_video={source_video_path}, prompt_audio={prompt_audio_path}")
            
            task = Task(
                name=f"task_{source_video_path.split('/')[-1].split('.')[0]}",
                source_video_path=source_video_path,
                prompt_audio_path=prompt_audio_path,
                left_prompt_audio_path=left_prompt_audio_path,
                right_prompt_audio_path=right_prompt_audio_path,
                bgm_path=bgm_path,
                priority=2
            )

            # 设置画外音参数
            task.enable_pip = enable_pip
            task.pip_video_path = pip_video_path
            task.pip_left_video_path = pip_left_video_path
            task.pip_right_video_path = pip_right_video_path
            logger.info(f"设置画外音参数: enable_pip={enable_pip}, pip_video_path={pip_video_path}, pip_left_video_path={pip_left_video_path}, pip_right_video_path={pip_right_video_path}")

            # 如果有 existing_task_id，使用它作为 task_id（无论是否有检查点）
            if existing_task_id:
                task.task_id = existing_task_id
                logger.info(f"使用现有任务ID: {task.task_id}")
        
        # 设置旧接口的视频素材
        # 优先使用检查点中的视频素材
        if checkpoint:
            if checkpoint.opening_video:
                task.opening_video = checkpoint.opening_video
            if checkpoint.loop_videos:
                task.loop_videos = checkpoint.loop_videos
            if checkpoint.scene_videos:
                task.scene_videos = checkpoint.scene_videos
            if checkpoint.ending_video:
                task.ending_video = checkpoint.ending_video
            
            # 从检查点恢复 segments 数据
            if checkpoint.segments_data:
                from core.models.checkpoint import deserialize_segments
                task.segments = deserialize_segments(checkpoint.segments_data)
                logger.info(f"从检查点恢复 {len(task.segments)} 个文案片段")
            
            # 从检查点恢复 tone_audio_paths（双人模式）
            if checkpoint.tag_groups:
                task.tone_audio_paths = {}
                task.completed_tone_videos = {}
                for tg in checkpoint.tag_groups:
                    if tg.audio_paths:
                        task.tone_audio_paths[tg.tone] = tg.audio_paths
                    # 恢复已完成的标签视频
                    if tg.video_completed and tg.video_path:
                        task.completed_tone_videos[tg.tone] = tg.video_path
                        logger.info(f"从检查点恢复已完成标签 '{tg.tone}' 的视频: {tg.video_path}")
                
                if task.tone_audio_paths:
                    logger.info(f"从检查点恢复 tone_audio_paths: {list(task.tone_audio_paths.keys())}")
                
                # 只有当所有标签都完成时才设置 final_video_path
                if task.completed_tone_videos and len(task.completed_tone_videos) == len(task.tone_audio_paths):
                    # 所有标签都已完成，使用最后一个标签的视频作为最终视频
                    for tg in checkpoint.tag_groups:
                        if tg.video_completed and tg.video_path:
                            task.final_video_path = tg.video_path
                            logger.info(f"所有标签已完成，从检查点恢复 final_video_path: {task.final_video_path}")
                            break

            # 恢复画外音相关数据
            if checkpoint.pip_speaker_videos:
                task.pip_speaker_videos = checkpoint.pip_speaker_videos
                logger.info(f"从检查点恢复 pip_speaker_videos: {list(checkpoint.pip_speaker_videos.keys())}")
            if checkpoint.scene_pip_left_video:
                task.scene_pip_left_video = checkpoint.scene_pip_left_video
            if checkpoint.scene_pip_right_video:
                task.scene_pip_right_video = checkpoint.scene_pip_right_video
            if checkpoint.scene_pip_processed:
                task.scene_pip_processed = set(checkpoint.scene_pip_processed)
                logger.info(f"从检查点恢复 scene_pip_processed: {checkpoint.scene_pip_processed}")
        else:
            if opening_video:
                task.opening_video = opening_video
            if loop_videos:
                task.loop_videos = loop_videos
            if scene_videos:
                task.scene_videos = scene_videos
            if ending_video:
                task.ending_video = ending_video
        
        # 设置新接口的带标签视频素材
        if opening_video_with_tags:
            task.opening_video_with_tags = VideoWithTag.from_dict(opening_video_with_tags)
        if loop_videos_with_tags:
            task.loop_videos_with_tags = [VideoWithTag.from_dict(v) for v in loop_videos_with_tags]
        if scene_videos_with_tags:
            task.scene_videos_with_tags = [VideoWithTag.from_dict(v) for v in scene_videos_with_tags]
        if ending_video_with_tags:
            task.ending_video_with_tags = VideoWithTag.from_dict(ending_video_with_tags)

        logger.info(f"开始任务 {task.task_id}")
        if bgm_path:
            logger.info(f"添加 BGM: {bgm_path}")

        try:
            # 检查是否取消
            if cancel_callback and cancel_callback():
                logger.info(f"任务 {task.task_id} 在启动前被取消")
                return WorkflowResult(
                    task_id=task.task_id,
                    status="failed",
                    error_message="任务被取消"
                )
            
            # 标签匹配器在服务启动时和设置变更时已加载，无需在任务执行时重新加载
            # 如果指定了标签组ID，通过同步方式加载
            try:
                from business.video.tag_matcher import get_tag_matcher, _load_scene_tags_from_db
                tag_matcher = get_tag_matcher()
                if scene_tag_group_id is not None:
                    # 使用同步 sqlite3 加载指定标签组
                    loaded = _load_scene_tags_from_db(group_id=scene_tag_group_id)
                    if loaded:
                        tag_matcher._scene_similarity = loaded
                        tag_matcher._scene_tags_loaded = True
                        logger.info(f"任务 {task.task_id} 已加载指定标签组: {scene_tag_group_id}")
                    else:
                        logger.warning(f"标签组 {scene_tag_group_id} 加载失败，使用当前配置")
            except Exception as e:
                logger.error(f"加载标签组失败，使用默认配置: {e}")
            
            # 步骤 1: 路径标准化和默认值设置
            if skip_to_stage and skip_to_stage in ["script_generating", "tts_synthesizing", "heygem_generating", "post_processing"]:
                logger.info(f"跳过初始化阶段，从 {skip_to_stage} 继续")
                # 即使跳过初始化，也需要标准化路径
                self._normalize_task_paths(task)
            else:
                logger.info("步骤 1/5: 初始化任务配置")
                # 标准化所有文件路径
                self._normalize_task_paths(task)

                # 检查开场视频
                if not source_video_path:
                    raise Exception("创建任务至少需要上传一个开场视频")

                # 标准化开场视频路径
                source_video_path = self._normalize_video_path(source_video_path)

                # 如果其他视频区域为空，使用开场视频作为默认视频
                if not task.opening_video:
                    task.opening_video = source_video_path
                if not task.ending_video:
                    task.ending_video = source_video_path
                if not task.loop_videos:
                    task.loop_videos = [source_video_path]
                if not task.scene_videos:
                    task.scene_videos = [source_video_path]

                # CR-030: 面部超分功能已移至 HeyGem 引擎，根据人脸区域大小自动决定是否启用超分
                # 不再需要基于分辨率的检测逻辑

                # 保存检查点
                self.save_task_checkpoint(task, config)

            # 检查是否取消
            if cancel_callback and cancel_callback():
                logger.info(f"任务 {task.task_id} 在初始化后被取消")
                return WorkflowResult(
                    task_id=task.task_id,
                    status="failed",
                    error_message="任务被取消"
                )
            
            # 步骤 2: 文案生成
            if skip_to_stage and skip_to_stage in ["tts_synthesizing", "heygem_generating", "post_processing"]:
                logger.info(f"跳过文案生成阶段，从 {skip_to_stage} 继续")
            else:
                logger.info("步骤 2/5: 文案生成")
                task.status = TaskStatus.SCRIPT_GENERATING
                task.progress = 5
                if progress_callback:
                    progress_callback(5, "文案生成中")
                segments = self._generate_script(
                    script_text=script_text,
                    topic=topic,
                    use_llm=use_llm_generate,
                    config=config
                )
                # 返回值是 (segments, raw_script) 元组
                if isinstance(segments, tuple):
                    segments, raw_script = segments
                else:
                    raw_script = script_text
                task.segments = segments
                # 保存原始文案文本到 task.script_text，用于封面生成等后续功能
                if raw_script:
                    task.script_text = raw_script
                elif script_text:
                    task.script_text = script_text
                task.progress = 10
                if progress_callback:
                    progress_callback(10, "文案生成完成")

                # 保存检查点
                self.save_task_checkpoint(task, config)

            # 检查是否取消
            if cancel_callback and cancel_callback():
                logger.info(f"任务 {task.task_id} 在文案生成后被取消")
                return WorkflowResult(
                    task_id=task.task_id,
                    status="failed",
                    error_message="任务被取消"
                )
            
            # 如果从检查点恢复，恢复已生成的音频和视频路径
            if checkpoint and task.segments:
                # 恢复音频路径
                if checkpoint.audio_paths:
                    for seg in task.segments:
                        if seg.segment_id in checkpoint.audio_paths:
                            seg.audio_path = checkpoint.audio_paths[seg.segment_id]
                            logger.info(f"恢复段落 {seg.segment_id} 音频路径: {seg.audio_path}")
                # 恢复视频路径
                if checkpoint.video_paths:
                    for seg in task.segments:
                        if seg.segment_id in checkpoint.video_paths:
                            seg.output_path = checkpoint.video_paths[seg.segment_id]
                            logger.info(f"恢复段落 {seg.segment_id} 视频路径: {seg.output_path}")
            
            # 检查音频路径
            if config.enable_double_mode:
                if not left_prompt_audio_path or not right_prompt_audio_path:
                    raise Exception("双人模式需要提供左右说话人的音频路径")
            else:
                if not prompt_audio_path:
                    raise Exception("需要提供音色参考音频")

            # 步骤 2.5: 参考音频语速调节
            logger.info("步骤 2.5/5: 参考音频语速调节")
            from business.audio.audio_speed_processor import create_audio_speed_processor

            # 创建语速处理器（使用路径管理器的音频目录）
            speed_processor = create_audio_speed_processor(self.audio_temp_dir)

            if speed_processor:
                if config.enable_double_mode:
                    # 双人模式：调节左右说话人的参考音频
                    # 使用已标准化的 task 对象中的路径
                    left_audio_path = task.left_prompt_audio_path
                    right_audio_path = task.right_prompt_audio_path

                    left_speed = config.left_tts_speed if config.left_tts_speed is not None else config.tts_speed
                    right_speed = config.right_tts_speed if config.right_tts_speed is not None else config.tts_speed

                    # 调节左说话人参考音频
                    if left_speed != 1.0:
                        logger.info(f"调节左说话人参考音频语速: {left_speed}x, 路径: {left_audio_path}")
                        adjusted_left_audio = await speed_processor.adjust_speed(left_audio_path, left_speed)
                        if adjusted_left_audio:
                            left_prompt_audio_path = adjusted_left_audio
                            task.left_prompt_audio_path = adjusted_left_audio
                            logger.info(f"左说话人参考音频语速调节完成: {adjusted_left_audio}")
                        else:
                            logger.warning(f"左说话人参考音频语速调节失败，使用原始音频")

                    # 调节右说话人参考音频
                    if right_speed != 1.0:
                        logger.info(f"调节右说话人参考音频语速: {right_speed}x, 路径: {right_audio_path}")
                        adjusted_right_audio = await speed_processor.adjust_speed(right_audio_path, right_speed)
                        if adjusted_right_audio:
                            right_prompt_audio_path = adjusted_right_audio
                            task.right_prompt_audio_path = adjusted_right_audio
                            logger.info(f"右说话人参考音频语速调节完成: {adjusted_right_audio}")
                        else:
                            logger.warning(f"右说话人参考音频语速调节失败，使用原始音频")
                else:
                    # 单人模式：调节参考音频
                    # 使用已标准化的 task 对象中的路径
                    audio_path = task.prompt_audio_path
                    if config.tts_speed != 1.0:
                        logger.info(f"调节参考音频语速: {config.tts_speed}x, 路径: {audio_path}")
                        adjusted_audio = await speed_processor.adjust_speed(audio_path, config.tts_speed)
                        if adjusted_audio:
                            prompt_audio_path = adjusted_audio
                            task.prompt_audio_path = adjusted_audio
                            logger.info(f"参考音频语速调节完成: {adjusted_audio}")
                        else:
                            logger.warning(f"参考音频语速调节失败，使用原始音频")

            # 检查是否取消
            if cancel_callback and cancel_callback():
                logger.info(f"任务 {task.task_id} 在音频调节后被取消")
                return WorkflowResult(
                    task_id=task.task_id,
                    status="failed",
                    error_message="任务被取消"
                )
            
            # 步骤 3: TTS 语音合成
            # 先检查检查点中音频是否已完成，再决定是否启动服务
            audio_already_completed = False
            if checkpoint and checkpoint.audio_paths and task.segments:
                # 检查所有段落的音频是否都已完成
                all_audio_done = all(
                    seg.segment_id in checkpoint.audio_paths and checkpoint.audio_paths[seg.segment_id]
                    for seg in task.segments
                )
                if all_audio_done:
                    audio_already_completed = True
                    logger.info("检查点显示音频合成已完成，跳过 IndexTTS 启动")
            
            if skip_to_stage and skip_to_stage in ["heygem_generating", "post_processing"]:
                logger.info(f"跳过音频合成阶段，从 {skip_to_stage} 继续")
            elif audio_already_completed:
                logger.info("音频已从检查点恢复完成，跳过音频合成阶段")
            else:
                # 确保引擎已加载
                if self.tts_engine and not self.tts_engine.is_loaded:
                    logger.info("加载 TTSEngine...")
                    if not self.tts_engine.load():
                        raise Exception("TTSEngine 加载失败，无法进行音频合成")

                logger.info("步骤 3/5: 语音合成")
                task.status = TaskStatus.TTS_SYNTHESIZING
                task.progress = 10
                if progress_callback:
                    progress_callback(10, "语音合成中...")

                # 定义音频合成进度回调
                def audio_progress_callback(completed, total, tag):
                    if progress_callback:
                        progress = calculate_progress("audio", completed, total)
                        description = build_stage_description("audio", completed, total, tag)
                        progress_callback(progress, description)

                # 不设置 TTSEngine 的内部进度回调，只使用外层的 audio_progress_callback
                # 这样进度条会稳定显示 "生成音频 X/X 处理标签 xxx"
                if self.tts_engine and hasattr(self.tts_engine, 'set_progress_callback'):
                    self.tts_engine.set_progress_callback(None)

                # 记录双人模式配置参数
                if config.enable_double_mode:
                    logger.info(f"双人模式音频合成配置: left_tts_speed={config.left_tts_speed}, right_tts_speed={config.right_tts_speed}, left_tts_emo_weight={config.left_tts_emo_weight}, right_tts_emo_weight={config.right_tts_emo_weight}")

                audio_results = await self.audio_processor.synthesize_all(
                    task, config,
                    cancel_callback=cancel_callback,
                    progress_callback=audio_progress_callback
                )

                failed_audio = [r for r in audio_results if r.status == "failed"]
                if failed_audio:
                    logger.warning(f"部分段落合成失败：{len(failed_audio)}/{len(audio_results)}")
                
                # 收集双人模式音频对齐中间文件
                if config.enable_double_mode and hasattr(task, 'tone_audio_paths') and task.tone_audio_paths:
                    aligned_audio_files = []
                    for tone, paths in task.tone_audio_paths.items():
                        if paths.get('left'):
                            aligned_audio_files.append(paths['left'])
                        if paths.get('right'):
                            aligned_audio_files.append(paths['right'])
                    if aligned_audio_files:
                        task._aligned_audio_files = aligned_audio_files
                        logger.info(f"收集双人模式音频对齐文件: {len(aligned_audio_files)} 个")
                
                task.progress = 45
                if progress_callback:
                    progress_callback(45, "语音合成完成")
                
                # 保存检查点（音频路径）
                self.save_task_checkpoint(task, config)

            # 检查是否取消
            if cancel_callback and cancel_callback():
                logger.info(f"任务 {task.task_id} 在音频合成后被取消")
                return WorkflowResult(
                    task_id=task.task_id,
                    status="failed",
                    error_message="任务被取消"
                )
            
            # 步骤 3.5: 卸载 TTS 引擎，释放 GPU 显存给 HeyGem
            # CR-026: 只在低显存模式开启时才卸载
            # 注意：无论音频阶段是新执行还是从检查点恢复，都需要检查是否需要卸载
            if self.low_memory_mode:
                logger.info("步骤 3.5/5: 卸载 TTS 引擎，释放 GPU 显存")
                self._unload_tts_if_low_memory_mode()
                # 等待 GPU 显存完全释放
                import time
                time.sleep(1.0)
                logger.info("GPU 显存已释放，准备加载 HeyGem")
            else:
                logger.info("步骤 3.5/5: 低显存模式关闭，保持 TTS 引擎加载")
            
            # 检查是否取消
            if cancel_callback and cancel_callback():
                logger.info(f"任务 {task.task_id} 在模型卸载后被取消")
                return WorkflowResult(
                    task_id=task.task_id,
                    status="failed",
                    error_message="任务被取消"
                )

            # 步骤 4: HeyGem 视频生成
            # 先检查检查点中视频是否已完成，再决定是否启动服务
            video_already_completed = False
            if checkpoint and checkpoint.video_paths and task.segments:
                # 检查所有段落的视频是否都已完成
                all_video_done = all(
                    seg.segment_id in checkpoint.video_paths and checkpoint.video_paths[seg.segment_id]
                    for seg in task.segments
                )
                if all_video_done:
                    video_already_completed = True
                    logger.info("检查点显示视频生成已完成，跳过 HeyGem 启动")
            
            # 双人模式：检查所有标签的视频是否已完成
            if not video_already_completed and checkpoint and checkpoint.tag_groups:
                all_tag_videos_done = all(
                    tg.video_completed and tg.video_path
                    for tg in checkpoint.tag_groups
                )
                if all_tag_videos_done:
                    video_already_completed = True
                    logger.info("检查点显示双人模式所有标签视频已完成，跳过 HeyGem 启动")
            
            if skip_to_stage and skip_to_stage in ["post_processing"]:
                logger.info(f"跳过视频生成阶段，从 {skip_to_stage} 继续")
                # CR-026: 即使跳过视频阶段，也需要检查是否卸载 HeyGem
                # 如果从检查点恢复且视频已完成，HeyGem 可能已加载，需要卸载
                if self.low_memory_mode:
                    logger.info("步骤 4.5/5: 卸载 HeyGem 引擎（视频阶段已跳过）")
                    self._cleanup_heygem_gpu()
            elif video_already_completed:
                logger.info("视频已从检查点恢复完成，跳过视频生成阶段")
                # CR-026: 视频已完成，需要卸载 HeyGem
                if self.low_memory_mode:
                    logger.info("步骤 4.5/5: 卸载 HeyGem 引擎（视频已完成）")
                    self._cleanup_heygem_gpu()
            else:
                # 确保引擎已加载
                if self.heygem_engine and not self.heygem_engine.is_loaded:
                    logger.info("加载 HeyGemEngine...")
                    if not self.heygem_engine.load():
                        raise Exception("HeyGemEngine 加载失败，无法进行视频生成")

                logger.info("步骤 4/5: 视频生成")
                task.status = TaskStatus.HEYGEM_GENERATING
                task.progress = 40
                if progress_callback:
                    progress_callback(40, "视频生成中...")

                # 定义视频生成进度回调
                def video_progress_callback(completed, total, tag):
                    if progress_callback:
                        progress = calculate_progress("video", completed, total)
                        description = build_stage_description("video", completed, total, tag)
                        progress_callback(progress, description)

                video_results = await self.video_synthesizer.generate_all(
                    task, config,
                    cancel_callback=cancel_callback,
                    progress_callback=video_progress_callback
                )
                failed_video = [r for r in video_results if r.status == "failed"]
                if failed_video:
                    logger.warning(f"部分视频生成失败：{len(failed_video)}/{len(video_results)}")
                
                # 收集双人模式中间文件
                double_mode_intermediate_files = []
                for result in video_results:
                    if hasattr(result, 'intermediate_files') and result.intermediate_files:
                        double_mode_intermediate_files.extend(result.intermediate_files)
                if double_mode_intermediate_files:
                    # 去重
                    double_mode_intermediate_files = list(set(double_mode_intermediate_files))
                    # 保存到 task 中，供后续检查点保存使用
                    task._double_mode_intermediate_files = double_mode_intermediate_files
                    logger.info(f"收集双人模式中间文件: {len(double_mode_intermediate_files)} 个")
                
                task.progress = 90
                if progress_callback:
                    progress_callback(90, "视频生成完成")
                
                # 检查是否取消
                if cancel_callback and cancel_callback():
                    logger.info(f"任务 {task.task_id} 在视频生成后被取消")
                    # 保存检查点后立即返回
                    self._cleanup_heygem_gpu()
                    self.save_task_checkpoint(task, config)
                    return WorkflowResult(
                        task_id=task.task_id,
                        status="failed",
                        error_message="任务被取消"
                    )
                
                # 所有视频生成完成后，释放 HeyGem GPU 显存
                self._cleanup_heygem_gpu()
                
                # 保存检查点（视频路径）
                self.save_task_checkpoint(task, config)

            # 步骤 4.5: 面部超分（已移除，超分由 HeyGem 引擎在生成时一并完成）
            # CR-030: 面部超分功能已集成到 HeyGem 引擎中，根据人脸区域大小自动决定是否启用超分

            # 步骤 5: 后期处理（视频合并是必须的，字幕等是可选的）
            # 进度范围：86-100%
            logger.info("步骤 5/5: 后期处理")
            task.status = TaskStatus.POST_PROCESSING
            task.progress = 86
            if progress_callback:
                progress_callback(86, "后期处理中...")

            # 后期处理子阶段进度更新
            def post_progress_callback(progress: float, stage: str):
                """后期处理进度回调"""
                if progress_callback:
                    # 将 85-100% 的进度映射到后期处理的子阶段
                    # 字幕：85-87%，BGM：87-89%，封面生成：89-94%，插入封面：94-97%，完成：97-100%
                    if "字幕" in stage:
                        progress_callback(85 + (progress * 0.02), stage)
                    elif "背景音乐" in stage or "BGM" in stage:
                        progress_callback(87 + (progress * 0.02), stage)
                    elif "封面" in stage:
                        progress_callback(89 + (progress * 0.05), stage)
                    elif "合成" in stage or "插入" in stage:
                        progress_callback(94 + (progress * 0.03), stage)
                    else:
                        progress_callback(85 + (progress * 0.15), stage)

            post_result = await self.post_processor.process(task, config, progress_callback=post_progress_callback)

            if post_result.status == "success":
                task.output_video_path = post_result.output_path
                logger.info(f"后期处理成功: {task.output_video_path}")
                # 保存字幕文件路径
                if post_result.subtitle_path:
                    task._subtitle_path = post_result.subtitle_path
                    logger.info(f"字幕文件: {post_result.subtitle_path}")
                # 保存后期处理中间文件
                if post_result.intermediate_files:
                    if not hasattr(task, '_double_mode_intermediate_files'):
                        task._double_mode_intermediate_files = []
                    task._double_mode_intermediate_files.extend(post_result.intermediate_files)
                    logger.info(f"后期处理中间文件: {len(post_result.intermediate_files)} 个")
            else:
                logger.warning(f"后期处理失败：{post_result.error_message}")
                # 如果后期处理失败，尝试从视频合成结果中获取
                if not task.output_video_path:
                    if config.enable_double_mode:
                        # 双人模式：使用第一个可用的视频
                        if hasattr(task, 'left_video_path') and task.left_video_path:
                            task.output_video_path = task.left_video_path
                        elif hasattr(task, 'right_video_path') and task.right_video_path:
                            task.output_video_path = task.right_video_path
                    else:
                        # 单人模式：使用第一个成功生成的视频片段
                        for result in video_results:
                            if result.status == "success" and result.video_path:
                                task.output_video_path = result.video_path
                                break
                        # 如果没有片段，尝试从 segments 中获取
                        if not task.output_video_path:
                            for segment in task.segments:
                                if hasattr(segment, 'output_path') and segment.output_path:
                                    task.output_video_path = segment.output_path
                                    break
            
            # 保存最终结果
            self.save_task_checkpoint(task, config)

            task.progress = 95
            if progress_callback:
                progress_callback(95, build_stage_description("postprocess", 0, 0, None, "merge"))

            # 画外音功能已在视频合成阶段按场景标签处理，无需全局后处理

            # 任务完成
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            if progress_callback:
                progress_callback(100, build_stage_description("completed", 0, 0))

            logger.info(f"任务 {task.task_id} 完成: {task.output_video_path}")

            # 清理双人模式中间文件
            self._cleanup_intermediate_files(task)

            # CR-026: 低显存模式下，任务完成后卸载所有模型
            if self.low_memory_mode:
                logger.info("步骤 6/5: 任务完成，卸载所有模型释放显存")
                self._cleanup_all_engines()

            return WorkflowResult(
                task_id=task.task_id,
                status="success",
                output_path=task.output_video_path,
                segments_completed=len([r for r in video_results if r.status == "success"]),
                total_segments=len(video_results)
            )

        except Exception as e:
            logger.error(f"任务 {task.task_id} 失败: {e}")
            task.status = TaskStatus.FAILED
            task.error_message = str(e)

            # 保存失败状态
            self.save_task_checkpoint(task, config)

            # CR-026: 低显存模式下，任务失败后也要卸载所有模型
            if self.low_memory_mode:
                logger.info("任务失败，卸载所有模型释放显存")
                self._cleanup_all_engines()

            return WorkflowResult(
                task_id=task.task_id,
                status="failed",
                error_message=str(e)
            )

    def run(self, **kwargs) -> WorkflowResult:
        """同步包装：在独立事件循环中运行 run_async"""
        return asyncio.run(self.run_async(**kwargs))

    def _normalize_video_path(self, video_path: str) -> str:
        """
        标准化视频路径，将相对路径转换为绝对路径

        Args:
            video_path: 原始视频路径（可能是相对路径或绝对路径）

        Returns:
            标准化后的绝对路径
        """
        if not video_path:
            return video_path

        # 如果已经是绝对路径，直接返回
        if os.path.isabs(video_path):
            return video_path

        # 处理可能的路径格式问题（Windows 反斜杠）
        video_path = video_path.replace('\\', '/')

        # 如果路径以 backend/ 开头，去掉它，使用项目根目录作为基准
        if video_path.startswith('backend/'):
            video_path = video_path[8:]
        
        # 如果路径以 videos/ 开头，添加 uploads 前缀
        if video_path.startswith('videos/'):
            video_path = 'uploads/' + video_path

        # 获取项目根目录（business 的父目录的父目录 = 项目根目录）
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 获取 backend 根目录
        backend_root = os.path.join(project_root, "backend")

        # 定义可能的基准目录
        base_dirs = [
            os.path.join(backend_root, "uploads"),
            os.path.join(backend_root, "data", "videos"),
            os.path.join(project_root, "uploads"),
            os.path.join(backend_root),
        ]

        # 尝试不同的路径组合
        for base_dir in base_dirs:
            full_path = os.path.join(base_dir, video_path)
            if os.path.exists(full_path):
                logger.debug(f"路径标准化: {video_path} -> {full_path}")
                return full_path

        # 如果都找不到，尝试相对于 backend 根目录
        full_path = os.path.join(backend_root, video_path)
        logger.debug(f"路径标准化（备用）: {video_path} -> {full_path}")
        return full_path

    def _normalize_audio_path(self, audio_path: str) -> str:
        """
        标准化音频路径，将相对路径转换为绝对路径

        Args:
            audio_path: 原始音频路径（可能是相对路径或绝对路径）

        Returns:
            标准化后的绝对路径
        """
        if not audio_path:
            return audio_path

        # 先统一路径分隔符（Windows 反斜杠 -> 正斜杠）
        audio_path = audio_path.replace('\\', '/')

        # 如果已经是绝对路径，先规范化后再返回
        if os.path.isabs(audio_path):
            # 转换为 os.path 规范的路径格式
            return os.path.normpath(audio_path)

        # 处理可能的路径格式问题（Windows 反斜杠）
        # （已经在上面处理过了）

        # 如果路径以 backend/ 开头，去掉它，使用项目根目录作为基准
        if audio_path.startswith('backend/'):
            audio_path = audio_path[8:]

        # 获取项目根目录（business 的父目录的父目录 = 项目根目录）
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 获取 backend 根目录
        backend_root = os.path.join(project_root, "backend")

        # 定义可能的基准目录（注意：优先搜索 uploads，避免重复路径问题）
        base_dirs = [
            os.path.join(backend_root, "uploads"),  # 优先在 uploads 目录下搜索
            os.path.join(backend_root, "data", "merged_audios"),
            os.path.join(backend_root, "data", "BGM"),
            os.path.join(backend_root),
            os.path.join(project_root, "uploads"),
        ]

        # 尝试不同的路径组合
        for base_dir in base_dirs:
            full_path = os.path.join(base_dir, audio_path)
            if os.path.exists(full_path):
                logger.debug(f"音频路径标准化: {audio_path} -> {full_path}")
                return full_path

        # 如果都找不到，尝试相对于 backend 根目录
        full_path = os.path.join(backend_root, audio_path)
        logger.debug(f"音频路径标准化（备用）: {audio_path} -> {full_path}")
        return full_path

    def _normalize_task_paths(self, task: Any) -> None:
        """
        标准化任务中所有文件路径

        Args:
            task: 任务对象
        """
        # 标准化视频路径
        if task.source_video_path:
            task.source_video_path = self._normalize_video_path(task.source_video_path)
        if task.opening_video:
            task.opening_video = self._normalize_video_path(task.opening_video)
        if task.ending_video:
            task.ending_video = self._normalize_video_path(task.ending_video)
        if task.loop_videos:
            task.loop_videos = [self._normalize_video_path(v) for v in task.loop_videos]
        if task.scene_videos:
            task.scene_videos = [self._normalize_video_path(v) for v in task.scene_videos]
        
        # 标准化带标签的视频路径
        if task.opening_video_with_tags:
            task.opening_video_with_tags.file_path = self._normalize_video_path(task.opening_video_with_tags.file_path)
        if task.loop_videos_with_tags:
            for video in task.loop_videos_with_tags:
                video.file_path = self._normalize_video_path(video.file_path)
        if task.scene_videos_with_tags:
            for video in task.scene_videos_with_tags:
                video.file_path = self._normalize_video_path(video.file_path)
        if task.ending_video_with_tags:
            task.ending_video_with_tags.file_path = self._normalize_video_path(task.ending_video_with_tags.file_path)

        # 标准化音频路径
        if task.prompt_audio_path:
            task.prompt_audio_path = self._normalize_audio_path(task.prompt_audio_path)
        if task.left_prompt_audio_path:
            task.left_prompt_audio_path = self._normalize_audio_path(task.left_prompt_audio_path)
        if task.right_prompt_audio_path:
            task.right_prompt_audio_path = self._normalize_audio_path(task.right_prompt_audio_path)
        if task.bgm_path:
            task.bgm_path = self._normalize_audio_path(task.bgm_path)

        # 标准化画外音视频路径
        if task.pip_video_path:
            task.pip_video_path = self._normalize_video_path(task.pip_video_path)
        if task.pip_left_video_path:
            task.pip_left_video_path = self._normalize_video_path(task.pip_left_video_path)
        if task.pip_right_video_path:
            task.pip_right_video_path = self._normalize_video_path(task.pip_right_video_path)

    def _preprocess_video(self, video_path: str) -> Dict[str, Any]:
        """预处理视频"""
        normalized_path = self._normalize_video_path(video_path)
        return quick_check_video(normalized_path)

    def _preprocess_face_alignment(self, video_path: str) -> Optional[str]:
        """
        面部对齐预处理 - 确保视频符合 HeyGem 要求

        Args:
            video_path: 原始视频路径

        Returns:
            处理后的视频路径，如果不需要处理则返回 None
        """
        try:
            # 标准化路径
            normalized_path = self._normalize_video_path(video_path)

            # 延迟导入避免循环依赖
            from business.preprocess.heygem_preprocessor import (
                HeyGemFacePreprocessor,
                quick_validate_heygem
            )

            # 先快速验证
            validation = quick_validate_heygem(normalized_path)

            if validation.get("valid"):
                # 视频已经符合要求，不需要处理
                logger.info(f"视频 {video_path} 已符合 HeyGem 要求，跳过预处理")
                return None

            logger.info(f"视频 {video_path} 不符合 HeyGem 要求，进行面部对齐处理")
            logger.warning(f"验证失败原因: {validation.get('reason')}")

            # 执行面部对齐处理
            preprocessor = HeyGemFacePreprocessor()
            result = preprocessor.process_video(
                video_path,
                output_path=video_path + ".aligned.mp4"
            )

            if result.is_qualified:
                logger.info(
                    f"面部对齐完成: {result.processed_frames}/{result.total_frames} 帧处理成功"
                )
                return result.output_path
            else:
                logger.warning(
                    f"面部对齐后仍不符合要求: {result.reasons}"
                )
                # 返回原始路径，让 HeyGem 尝试处理
                return None

        except Exception as e:
            logger.error(f"面部预处理失败: {e}")
            # 出错时返回原路径
            return None

    def _preprocess_all_videos(self, task: Task) -> None:
        """
        预处理任务中的所有视频源

        Args:
            task: 任务对象
        """
        video_paths = []

        # 收集所有需要处理的视频路径
        if task.source_video_path:
            video_paths.append(("source", self._normalize_video_path(task.source_video_path)))
        if task.opening_video:
            video_paths.append(("opening", self._normalize_video_path(task.opening_video)))
        if task.ending_video:
            video_paths.append(("ending", self._normalize_video_path(task.ending_video)))
        for i, v in enumerate(task.loop_videos or []):
            video_paths.append((f"loop_{i}", self._normalize_video_path(v)))
        for i, v in enumerate(task.scene_videos or []):
            video_paths.append((f"scene_{i}", self._normalize_video_path(v)))

        # 预处理每个视频
        for video_type, video_path in video_paths:
            if not video_path or not os.path.exists(video_path):
                logger.warning(f"视频文件不存在或路径无效: {video_type} = {video_path}")
                continue

            processed_path = self._preprocess_face_alignment(video_path)
            if processed_path and processed_path != video_path:
                # 更新任务中的视频路径
                if video_type == "source":
                    task.source_video_path = processed_path
                elif video_type == "opening":
                    task.opening_video = processed_path
                elif video_type == "ending":
                    task.ending_video = processed_path
                elif video_type.startswith("loop_"):
                    idx = int(video_type.split("_")[1])
                    if task.loop_videos and idx < len(task.loop_videos):
                        task.loop_videos[idx] = processed_path
                elif video_type.startswith("scene_"):
                    idx = int(video_type.split("_")[1])
                    if task.scene_videos and idx < len(task.scene_videos):
                        task.scene_videos[idx] = processed_path

                logger.info(f"视频 {video_type} 已预处理: {video_path} -> {processed_path}")

    def _generate_script(
        self,
        script_text: str,
        topic: str,
        use_llm: bool,
        config: Optional[TaskConfig] = None
    ) -> tuple:
        """生成文案

        支持两种模式：
        1. JSON 格式文案：直接解析
        2. 非 JSON 格式主题：调用 LLM 生成文案（当 use_llm=True 时）

        Returns:
            (segments, raw_script) 元组
            - segments: 解析后的文案段落列表
            - raw_script: 原始 JSON 文案文本，用于封面生成等功能
        """
        logger.info(f"开始处理文案: script_text长度={len(script_text) if script_text else 0}, use_llm={use_llm}, topic={topic[:50] if topic else 'N/A'}...")

        if script_text:
            logger.info("尝试解析提供的文案")
            segments = self.script_parser.parse(script_text)
            if segments:
                logger.info(f"文案解析完成，段落数: {len(segments)}")
                return segments, script_text
            else:
                logger.warning("文案解析失败")

        if use_llm and topic:
            logger.info(f"调用 LLM 生成文案，主题: {topic[:50]}...")
            try:
                generated_script = self._generate_script_with_llm(topic, config)
                if generated_script:
                    segments = self.script_parser.parse(generated_script)
                    if segments:
                        logger.info(f"LLM 文案生成完成，段落数: {len(segments)}")
                        return segments, generated_script
                    else:
                        logger.warning("LLM 生成的文案解析失败")
            except Exception as e:
                logger.error(f"LLM 文案生成失败: {e}")

        logger.warning("使用默认文案")
        segments = self.script_parser._get_default_segments()

        if config and config.enable_double_mode:
            for i, segment in enumerate(segments):
                segment.speaker = "left" if i % 2 == 0 else "right"

        return segments, None
    
    def _generate_script_with_llm(
        self,
        topic: str,
        config: Optional[TaskConfig] = None
    ) -> Optional[str]:
        """使用 LLM 生成文案
        
        Args:
            topic: 主题内容
            config: 任务配置（包含双人模式等）
            
        Returns:
            生成的 JSON 格式文案，失败返回 None
        """
        if not self.llm_config or not self.llm_config.get("api_key"):
            logger.warning("LLM API Key 未配置，无法生成文案")
            return None
        
        mode = "dual" if config and config.enable_double_mode else "single"
        
        prompt_template = self._load_prompt_template(mode)
        
        if prompt_template:
            prompt = prompt_template.replace("{theme}", topic)
            logger.info(f"使用配置文件中的提示词模版，模式: {mode}")
        else:
            logger.warning("未找到提示词模版，使用默认提示词")
            if mode == "single":
                prompt = f"根据主题「{topic}」生成单人讲解文案，包含开场、情绪标签、场景标签、结束部分。请以 JSON 格式返回。"
            else:
                prompt = f"根据主题「{topic}」生成双人对话文案，包含开场、左边说话人、右边说话人、情绪标签、场景标签、结束部分。请以 JSON 格式返回。"
        
        try:
            result = self.llm_generator.generate_sync(prompt)
            logger.info(f"LLM 生成文案成功，长度: {len(result) if result else 0}")

            # 保存到历史记录
            if result:
                try:
                    db = get_database_service()
                    asyncio.create_task(db.script_history_create(user_input=topic, script_content=result))
                except Exception as e:
                    logger.warning(f"保存文案历史记录失败: {e}")

            return result
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return None
    
    def _load_prompt_template(self, mode: str) -> Optional[str]:
        """从配置文件加载提示词模版
        
        Args:
            mode: 模式，"single" 或 "dual"
            
        Returns:
            提示词模版，失败返回 None
        """
        try:
            if os.path.exists(PROMPT_TEMPLATES_PATH):
                with open(PROMPT_TEMPLATES_PATH, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data:
                        if mode == "dual":
                            return data.get("dual_person_prompt_template", "")
                        else:
                            return data.get("single_person_prompt_template", "")
        except Exception as e:
            logger.error(f"加载提示词模版失败: {e}")
        return None

    def denoise_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        音频降噪处理

        Args:
            audio_path: 音频文件路径

        Returns:
            降噪结果
        """
        try:
            logger.info(f"开始音频降噪: {audio_path}")
            result = self.audio_processor.denoise(audio_path)
            logger.info(f"音频降噪完成: {result.get('output_path')}")
            return result
        except Exception as e:
            logger.error(f"音频降噪失败: {e}")
            raise

    def run_with_topic(
        self,
        source_video_path: str,
        topic: str,
        prompt_audio_path: str = "",
        left_prompt_audio_path: str = "",
        right_prompt_audio_path: str = "",
        bgm_path: str = "",
        config: Optional[TaskConfig] = None
    ) -> WorkflowResult:
        """使用主题运行（自动生成文案）"""
        return self.run(
            source_video_path=source_video_path,
            topic=topic,
            prompt_audio_path=prompt_audio_path,
            left_prompt_audio_path=left_prompt_audio_path,
            right_prompt_audio_path=right_prompt_audio_path,
            bgm_path=bgm_path,
            config=config,
            use_llm_generate=True
        )

    def run_with_script(
        self,
        source_video_path: str,
        script_text: str,
        prompt_audio_path: str = "",
        left_prompt_audio_path: str = "",
        right_prompt_audio_path: str = "",
        bgm_path: str = "",
        config: Optional[TaskConfig] = None
    ) -> WorkflowResult:
        """使用自定义文案运行"""
        return self.run(
            source_video_path=source_video_path,
            script_text=script_text,
            prompt_audio_path=prompt_audio_path,
            left_prompt_audio_path=left_prompt_audio_path,
            right_prompt_audio_path=right_prompt_audio_path,
            bgm_path=bgm_path,
            config=config,
            use_llm_generate=False
        )

    def _unload_tts_if_low_memory_mode(self):
        """
        在低显存模式下卸载 TTS 引擎

        AC-227: 低显存模式开启时音频合成完成后卸载 TTS 模型
        AC-229: 低显存模式关闭时 TTS 模型保持常驻
        """
        if not self.low_memory_mode:
            logger.debug("[Workflow] 低显存模式关闭，保持 TTS 引擎加载")
            return

        try:
            if self.tts_engine and self.tts_engine.is_loaded:
                self.tts_engine.unload()
                logger.info("[Workflow] TTSEngine 已卸载，GPU 显存已释放")
        except Exception as e:
            logger.debug(f"[Workflow] TTS 引擎卸载失败（不影响主流程）: {e}")

    def _cleanup_heygem_gpu(self):
        """
        释放 HeyGem 引擎的 GPU 显存（工作流级别，所有视频生成完成后调用一次）

        CR-026: 只在低显存模式开启时才卸载
        AC-228: 低显存模式开启时视频合成完成后卸载 HeyGem 模型
        AC-229: 低显存模式关闭时 HeyGem 模型保持常驻
        """
        if not self.low_memory_mode:
            logger.debug("[Workflow] 低显存模式关闭，保持 HeyGem 引擎加载")
            return

        try:
            if self.heygem_engine and self.heygem_engine.is_loaded:
                self.heygem_engine.unload()
                logger.info("[Workflow] HeyGemEngine 已卸载，GPU 显存已释放")
                # 等待 GPU 显存完全释放
                import time
                time.sleep(1.0)
        except Exception as e:
            logger.debug(f"[Workflow] HeyGem 引擎卸载失败（不影响主流程）: {e}")

    def _cleanup_all_engines(self):
        """
        卸载所有引擎（任务完成后调用）

        CR-026: 低显存模式下，任务完成后卸载所有模型
        确保显存完全释放到基准水平
        """
        import gc
        import time

        logger.info("[Workflow] 开始卸载所有引擎...")

        # 1. 卸载 TTS 引擎
        try:
            if self.tts_engine and self.tts_engine.is_loaded:
                self.tts_engine.unload()
                logger.info("[Workflow] TTSEngine 已卸载")
        except Exception as e:
            logger.warning(f"[Workflow] TTS 引擎卸载失败: {e}")

        # 2. 卸载 HeyGem 引擎
        try:
            if self.heygem_engine and self.heygem_engine.is_loaded:
                self.heygem_engine.unload()
                logger.info("[Workflow] HeyGemEngine 已卸载")
        except Exception as e:
            logger.warning(f"[Workflow] HeyGem 引擎卸载失败: {e}")

        # 3. 清理 CUDA 缓存
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logger.info("[Workflow] CUDA 缓存已清理")
        except ImportError:
            pass

        # 4. 多次垃圾回收
        gc.collect()
        gc.collect()
        gc.collect()

        # 5. 等待 GPU 显存完全释放
        time.sleep(1.5)

        logger.info("[Workflow] 所有引擎已卸载，显存已完全释放")

    def _cleanup_intermediate_files(self, task: Task):
        """
        清理任务产生的中间文件

        包括：
        - 双人模式中间文件
        - 静音文件
        - 其他临时文件

        Args:
            task: 任务对象
        """
        cleaned_count = 0

        # 1. 清理双人模式中间文件
        if hasattr(task, '_double_mode_intermediate_files') and task._double_mode_intermediate_files:
            for file_path in task._double_mode_intermediate_files:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        cleaned_count += 1
                        logger.debug(f"已清理中间文件: {file_path}")
                except Exception as e:
                    logger.warning(f"清理中间文件失败 {file_path}: {e}")
            logger.info(f"已清理 {cleaned_count} 个双人模式中间文件")
            task._double_mode_intermediate_files = []

        # 2. 清理静音文件（UUID 命名的临时文件）
        if hasattr(task, '_silence_files') and task._silence_files:
            for file_path in task._silence_files:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.debug(f"已清理静音文件: {file_path}")
                except Exception as e:
                    logger.warning(f"清理静音文件失败 {file_path}: {e}")

        # 3. 清理画外音说话人视频中间文件
        pip_cleaned = 0
        # 清理 pip_speaker_videos 中的说话人视频
        if task.pip_speaker_videos:
            for tone, tone_data in task.pip_speaker_videos.items():
                for key in ('left', 'right'):
                    file_path = tone_data.get(key)
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            pip_cleaned += 1
                            logger.debug(f"已清理画外音说话人视频: {file_path}")
                        except Exception as e:
                            logger.warning(f"清理画外音说话人视频失败 {file_path}: {e}")
        # 清理单人模式 Segment 上的说话人视频
        if task.segments:
            for seg in task.segments:
                if seg.pending_speaker_video and os.path.exists(seg.pending_speaker_video):
                    try:
                        os.remove(seg.pending_speaker_video)
                        pip_cleaned += 1
                        logger.debug(f"已清理段落说话人视频: {seg.pending_speaker_video}")
                    except Exception as e:
                        logger.warning(f"清理段落说话人视频失败 {seg.pending_speaker_video}: {e}")
        # 清理 Task 级别的画外音视频路径
        for attr in ('scene_pip_left_video', 'scene_pip_right_video'):
            file_path = getattr(task, attr, None)
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    pip_cleaned += 1
                    logger.debug(f"已清理画外音视频: {file_path}")
                except Exception as e:
                    logger.warning(f"清理画外音视频失败 {file_path}: {e}")
        if pip_cleaned > 0:
            logger.info(f"已清理 {pip_cleaned} 个画外音说话人中间文件")

    def close(self):
        """关闭所有模块"""
        self.audio_processor.close()
        self.video_synthesizer.close()
        logger.info("工作流已关闭")
    
    def save_task_checkpoint(self, task: Task, config: TaskConfig):
        """
        保存任务检查点
        
        Args:
            task: 任务对象
            config: 任务配置
        """
        if not self.db:
            logger.warning("数据库实例未初始化，无法保存检查点")
            return
        
        try:
            from core.models.checkpoint import CheckpointData, TagGroupCheckpoint, serialize_segments
            
            # 收集已完成的段落音频路径
            audio_paths = {}
            video_paths = {}
            if task.segments:
                for seg in task.segments:
                    if seg.audio_path:
                        audio_paths[seg.segment_id] = seg.audio_path
                    if hasattr(seg, 'output_path') and seg.output_path:
                        video_paths[seg.segment_id] = seg.output_path
            
            checkpoint = CheckpointData(
                task_id=task.task_id,
                current_stage=task.status.value if hasattr(task.status, 'value') else str(task.status),
                current_tone_index=getattr(task, 'current_tone_index', 0),
                completed_segments=[seg.segment_id for seg in task.segments if seg.audio_path] if task.segments else []
            )
            
            # 保存音频路径到检查点
            checkpoint.audio_paths = audio_paths
            checkpoint.video_paths = video_paths
            
            # 保存 segments 数据
            if task.segments:
                checkpoint.segments_data = serialize_segments(task.segments)
                logger.info(f"保存 {len(checkpoint.segments_data)} 个文案片段到检查点")
            
            # 保存任务级别的路径信息
            checkpoint.source_video_path = task.source_video_path
            checkpoint.prompt_audio_path = task.prompt_audio_path
            checkpoint.left_prompt_audio_path = getattr(task, 'left_prompt_audio_path', None)
            checkpoint.right_prompt_audio_path = getattr(task, 'right_prompt_audio_path', None)
            checkpoint.bgm_path = task.bgm_path
            checkpoint.opening_video = task.opening_video
            checkpoint.loop_videos = task.loop_videos if task.loop_videos else []
            checkpoint.scene_videos = task.scene_videos if task.scene_videos else []
            checkpoint.ending_video = task.ending_video
            
            if config.enable_double_mode and hasattr(task, 'tone_audio_paths'):
                # 获取已完成的标签视频
                completed_tone_videos = getattr(task, 'completed_tone_videos', {})
                
                for tone, audio_paths in task.tone_audio_paths.items():
                    # 检查该标签的视频是否已完成
                    video_completed = tone in completed_tone_videos and os.path.exists(completed_tone_videos[tone])
                    video_path = completed_tone_videos.get(tone) if video_completed else None
                    
                    tg_checkpoint = TagGroupCheckpoint(
                        tone=tone,
                        audio_completed=bool(audio_paths.get('left') or audio_paths.get('right')),
                        video_completed=video_completed,
                        video_path=video_path,
                        audio_paths=audio_paths
                    )
                    checkpoint.tag_groups.append(tg_checkpoint)
                    if video_completed:
                        logger.info(f"保存已完成标签 '{tone}' 的视频: {video_path}")
            
            # 注意：不再自动将所有 tag_groups 的 video_completed 设置为 True
            # 因为 final_video_path 存在只表示最终视频已生成，不代表所有标签都已完成
            # 如果任务被中断，应该只恢复已完成的标签状态
            
            # 保存双人模式中间文件
            if hasattr(task, '_double_mode_intermediate_files') and task._double_mode_intermediate_files:
                checkpoint.double_mode_files = task._double_mode_intermediate_files
                logger.info(f"保存双人模式中间文件到检查点: {len(checkpoint.double_mode_files)} 个")
            
            # 保存双人模式音频对齐文件
            if hasattr(task, '_aligned_audio_files') and task._aligned_audio_files:
                # 合并到 double_mode_files 中
                if not checkpoint.double_mode_files:
                    checkpoint.double_mode_files = []
                checkpoint.double_mode_files.extend(task._aligned_audio_files)
                logger.info(f"保存双人模式音频对齐文件到检查点: {len(task._aligned_audio_files)} 个")
            
            # 保存字幕文件路径
            if hasattr(task, '_subtitle_path') and task._subtitle_path:
                checkpoint.subtitle_path = task._subtitle_path
                logger.info(f"保存字幕文件路径到检查点: {checkpoint.subtitle_path}")

            # 保存画外音相关数据
            if task.pip_speaker_videos:
                checkpoint.pip_speaker_videos = task.pip_speaker_videos
                logger.info(f"保存画外音说话人视频到检查点: {list(task.pip_speaker_videos.keys())}")
            if task.scene_pip_left_video:
                checkpoint.scene_pip_left_video = task.scene_pip_left_video
            if task.scene_pip_right_video:
                checkpoint.scene_pip_right_video = task.scene_pip_right_video
            if task.scene_pip_processed:
                checkpoint.scene_pip_processed = list(task.scene_pip_processed)
                logger.info(f"保存已处理画外音场景标签到检查点: {checkpoint.scene_pip_processed}")
            
            checkpoint_json = checkpoint.to_json()

            # 统一使用同步数据库操作，避免 asyncio.run() 和线程池带来的问题
            # aiosqlite 连接不是线程安全的，直接使用原生 sqlite3 更可靠
            result = self._sync_checkpoint_save(task.task_id, checkpoint_json)
            if result:
                logger.info(f"检查点保存成功: {task.task_id}")
            else:
                logger.warning(f"检查点保存失败，但不阻塞主流程: {task.task_id}")
            
            logger.info(f"检查点已保存: {task.task_id}, 阶段: {checkpoint.current_stage}")
            
        except Exception as e:
            logger.error(f"保存检查点失败: {e}")

    def _sync_checkpoint_save(self, task_id: str, checkpoint_json: str) -> bool:
        """
        同步保存检查点（用于在线程池中执行）

        使用独立的数据库连接来避免线程安全问题

        Args:
            task_id: 任务ID
            checkpoint_json: 检查点JSON数据

        Returns:
            是否保存成功
        """
        import sqlite3
        from datetime import datetime

        try:
            # 使用同步 sqlite3 创建独立连接
            db_path = self.db.db_path if hasattr(self.db, 'db_path') else "data/app.db"
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute(
                """UPDATE tasks
                   SET checkpoint_data = ?, updated_at = ?
                   WHERE task_id = ?""",
                (checkpoint_json, now, task_id)
            )
            conn.commit()
            conn.close()

            logger.info(f"检查点保存成功（同步）: {task_id}")
            return True
        except Exception as e:
            logger.error(f"同步保存检查点失败: {e}")
            return False

    def load_task_checkpoint(self, task_id: str) -> Optional[Any]:
        """
        加载任务检查点
        
        Args:
            task_id: 任务 ID
            
        Returns:
            CheckpointData 或 None
        """
        if not self.db:
            logger.warning("数据库实例未初始化，无法加载检查点")
            return None
        
        try:
            import asyncio
            import concurrent.futures
            checkpoint_json = None
            
            if asyncio.iscoroutinefunction(self.db.checkpoint_load):
                try:
                    loop = asyncio.get_running_loop()
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            self.db.checkpoint_load(task_id)
                        )
                        checkpoint_json = future.result(timeout=30)
                except RuntimeError:
                    checkpoint_json = asyncio.run(self.db.checkpoint_load(task_id))
            else:
                checkpoint_json = self.db.checkpoint_load(task_id)
            
            if checkpoint_json:
                from core.models.checkpoint import CheckpointData
                checkpoint = CheckpointData.from_json(checkpoint_json)
                logger.info(f"检查点已加载: {task_id}, 阶段: {checkpoint.current_stage}")
                return checkpoint
            else:
                logger.info(f"未找到检查点数据: {task_id}")
            return None
            
        except Exception as e:
            logger.error(f"加载检查点失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def clear_task_checkpoint(self, task_id: str):
        """
        清除任务检查点（任务完成后调用）
        
        Args:
            task_id: 任务 ID
        """
        if not self.db:
            return
        
        try:
            import asyncio
            
            if asyncio.iscoroutinefunction(self.db.checkpoint_clear):
                try:
                    loop = asyncio.get_running_loop()
                    asyncio.create_task(self.db.checkpoint_clear(task_id))
                except RuntimeError:
                    asyncio.run(self.db.checkpoint_clear(task_id))
            else:
                self.db.checkpoint_clear(task_id)
            
            logger.info(f"检查点已清除: {task_id}")
            
        except Exception as e:
            logger.error(f"清除检查点失败: {e}")
    
    def recover_task(self, task_id: str) -> Optional[tuple]:
        """
        恢复任务
        
        Args:
            task_id: 任务 ID
            
        Returns:
            (Task, TaskConfig) 或 None
        """
        if not self.db:
            logger.warning("数据库实例未初始化，无法恢复任务")
            return None
        
        try:
            result = self.db.load_task(task_id)
            if result:
                logger.info(f"任务 {task_id} 已恢复")
            return result
        except Exception as e:
            logger.error(f"恢复任务失败：{e}")
            return None
    
    def get_incomplete_tasks(self) -> List[tuple]:
        """
        获取所有未完成任务
        
        Returns:
            [(Task, TaskConfig), ...] 列表
        """
        if not self.db:
            logger.warning("数据库实例未初始化，无法获取未完成任务")
            return []
        
        try:
            return self.db.get_incomplete_tasks()
        except Exception as e:
            logger.error(f"获取未完成任务失败：{e}")
            return []


# 便捷函数
def create_workflow(
    tts_engine=None,
    heygem_engine=None,
    llm_provider: str = "astron",
    llm_api_key: str = "",
    output_dir: str = "output",
    low_memory_mode: bool = False,
    ultra_low_memory: bool = False
) -> DigitalHumanWorkflow:
    """创建工作流的便捷函数（引擎模式）

    Args:
        tts_engine: TTSEngine 实例，如果为 None 则从配置创建
        heygem_engine: HeyGemEngine 实例，如果为 None 则从配置创建
        llm_provider: LLM 提供商
        llm_api_key: LLM API 密钥
        output_dir: 输出目录
        low_memory_mode: 是否启用低显存模式
        ultra_low_memory: 是否启用超低显存模式

    Returns:
        DigitalHumanWorkflow 实例
    """
    # 如果未提供引擎，从配置创建
    if tts_engine is None or heygem_engine is None:
        engines = create_engines_from_config(
            low_memory_mode=low_memory_mode,
            ultra_low_memory=ultra_low_memory
        )
        tts_engine = tts_engine or engines.get("tts_engine")
        heygem_engine = heygem_engine or engines.get("heygem_engine")

    return DigitalHumanWorkflow(
        tts_engine=tts_engine,
        heygem_engine=heygem_engine,
        llm_config={
            "provider": llm_provider,
            "api_key": llm_api_key
        },
        output_dir=output_dir,
        low_memory_mode=low_memory_mode
    )


# 简单使用示例
def main():
    """简单示例"""
    # 创建工作流（引擎模式）
    workflow = create_workflow(
        llm_provider="astron",
        llm_api_key="your-api-key"
    )

    # 使用主题生成
    result = workflow.run_with_topic(
        source_video_path="materials/videos/sample.mp4",
        topic="智能数字人介绍",
        prompt_audio_path="materials/voices/ref.wav"
    )

    print(f"任务 {result.task_id}: {result.status}")
    if result.output_path:
        print(f"输出: {result.output_path}")
    if result.error_message:
        print(f"错误: {result.error_message}")

    workflow.close()


if __name__ == "__main__":
    main()