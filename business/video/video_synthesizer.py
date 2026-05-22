"""
视频合成模块
实现数字人视频生成功能（调用 HeyGem）
"""

import logging
import os
import platform

import time
import shutil
import random
import tempfile
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from core.models.task import ScriptSegment, Task, TaskConfig
from core.paths import get_path_manager

from api.utils.async_subprocess import async_run_subprocess, async_run_ffmpeg, async_run_ffprobe

# 导入转场效果常量
from business.postprocess.transition_effects import (
    ALL_TRANSITION_EFFECTS,
    is_valid_transition_effect
)

logger = logging.getLogger(__name__)


@dataclass
class VideoSegmentResult:
    """视频段落结果"""
    segment_id: str
    audio_path: str
    video_path: Optional[str]
    duration: float
    status: str  # success, failed
    error_message: Optional[str] = None
    intermediate_files: List[str] = field(default_factory=list)


class VideoSynthesizer:
    """视频合成器 - 封装 HeyGem 和视频处理功能"""

    def __init__(
        self,
        heygem_engine: Any,
        output_dir: str = "temp/video"
    ):
        """
        初始化视频合成器

        Args:
            heygem_engine: HeyGemEngine 实例（必需）
            output_dir: 视频输出目录
        """
        if heygem_engine is None:
            raise ValueError("heygem_engine 参数是必需的，请提供 HeyGemEngine 实例")

        self.heygem_engine = heygem_engine
        # 确保使用绝对路径
        from pathlib import Path
        self.output_dir = str(Path(output_dir).resolve())

        # 创建输出目录
        os.makedirs(self.output_dir, exist_ok=True)

        logger.info(f"VideoSynthesizer 初始化成功，输出目录: {self.output_dir}")

    async def generate_segment(
        self,
        segment: ScriptSegment,
        video_source: str,
        config: TaskConfig,
        task_id: Optional[str] = None
    ) -> VideoSegmentResult:
        """
        生成单个视频段落

        Args:
            segment: 文案段落（包含音频路径）
            video_source: 源视频路径
            config: 配置
            task_id: 任务ID，用于文件命名前缀

        Returns:
            视频结果
        """
        if not segment.audio_path:
            logger.error(f"段落 {segment.segment_id} 没有音频路径")
            return VideoSegmentResult(
                segment_id=segment.segment_id,
                audio_path="",
                video_path=None,
                duration=0.0,
                status="failed",
                error_message="没有音频文件"
            )

        # 检查音频文件是否存在
        audio_file_path = segment.audio_path
        if not os.path.exists(audio_file_path):
            logger.error(f"音频文件不存在: {audio_file_path}")
            # 使用路径管理器查找文件
            path_manager = get_path_manager()
            found_path = path_manager.find_audio_file(audio_file_path)

            if found_path:
                audio_file_path = found_path
                logger.info(f"找到音频文件: {audio_file_path}")
            else:
                # 额外的搜索路径作为后备
                current_dir = os.getcwd()
                project_root = os.path.dirname(current_dir) if os.path.basename(current_dir) == "backend" else current_dir

                possible_paths = [
                    audio_file_path,
                    audio_file_path.replace("\\", "/"),
                    os.path.join(path_manager.audio_temp_dir, os.path.basename(audio_file_path)),
                    os.path.join(path_manager.output_dir, audio_file_path),
                    os.path.join(project_root, "backend", "output", "temp", "audio", os.path.basename(audio_file_path)),
                ]

                for p in possible_paths:
                    if os.path.exists(p):
                        audio_file_path = p
                        logger.info(f"找到音频文件: {audio_file_path}")
                        found_path = p
                        break

                if not found_path:
                    return VideoSegmentResult(
                        segment_id=segment.segment_id,
                        audio_path=segment.audio_path,
                        video_path=None,
                        duration=0.0,
                        status="failed",
                        error_message=f"音频文件不存在: {segment.audio_path}"
                    )

        # 检查视频源文件是否存在
        if video_source and not os.path.exists(video_source):
            logger.error(f"视频源文件不存在: {video_source}")

        # 确保音频文件路径为绝对路径
        audio_file = os.path.abspath(audio_file_path).replace("\\", "/")

        # 根据场景类型选择视频，确保视频路径为绝对路径
        video_file = self._select_video(segment, video_source)
        if video_file and not os.path.isabs(video_file):
            video_file = os.path.abspath(video_file).replace("\\", "/")

        try:
            # 生成文件名：使用 task_id 前缀，格式为 {task_id}_video_{segment_id}.mp4
            if task_id:
                video_filename = f"{task_id}_video_{segment.segment_id}.mp4"
            else:
                video_filename = f"{segment.segment_id}.mp4"

            # 调用 HeyGem 生成视频（带自动重启功能），直接使用目标文件名
            video_path = self._run_heygem_with_auto_restart(
                audio_path=audio_file,
                video_source=video_file,
                config=config,
                face_id=0,
                cancel_callback=None,
                output_filename=video_filename
            )

            if video_path and os.path.exists(video_path):
                # 视频已直接保存到目标路径，无需再移动
                output_path = video_path

                # 获取视频时长
                duration = await self._get_video_duration(output_path)

                segment.video_path = output_path
                segment.duration = duration
                segment.output_path = output_path

                return VideoSegmentResult(
                    segment_id=segment.segment_id,
                    audio_path=segment.audio_path,
                    video_path=output_path,
                    duration=duration,
                    status="success"
                )

            return VideoSegmentResult(
                segment_id=segment.segment_id,
                audio_path=segment.audio_path,
                video_path=None,
                duration=0.0,
                status="failed",
                error_message="HeyGem生成失败或未返回视频"
            )

        except Exception as e:
            logger.error(f"段落 {segment.segment_id} 视频生成失败: {e}")
            return VideoSegmentResult(
                segment_id=segment.segment_id,
                audio_path=segment.audio_path,
                video_path=None,
                duration=0.0,
                status="failed",
                error_message=str(e)
            )

    def _select_video(self, segment: ScriptSegment, default_video: str) -> str:
        """根据场景和情感选择视频"""
        import os
        from core.models.task import SceneType
        
        # 情绪标签相似映射
        emotion_similarity = {
            "JOY": ["HAPPY", "EXCITED", "DELIGHTED"],
            "ANGER": ["ANGRY", "FRUSTRATED", "IRRITATED"],
            "SADNESS": ["SAD", "DEPRESSED", "GLOOMY"],
            "FEAR": ["SCARED", "AFRAID", "TERRIFIED"],
            "DISGUST": ["DISGUSTED", "REPULSED", "HORRIFIED"],
            "DEPRESSION": ["DEPRESSED", "SAD", "MELANCHOLY"],
            "SURPRISE": ["SURPRISED", "AMAZED", "ASTONISHED"],
            "CALM": ["CALM", "RELAXED", "PEACEFUL"]
        }
        
        # 场景类型到视频列表的映射
        scene_to_videos = {
            SceneType.OPENING: ["opening_video"],
            SceneType.ENDING: ["ending_video"],
            SceneType.LOOP: ["loop_videos"],
            SceneType.SCENE: ["scene_videos"]
        }
        
        # 获取当前场景类型对应的视频列表
        video_lists = scene_to_videos.get(segment.scene_type, ["loop_videos"])
        
        # 尝试根据情绪标签选择视频
        if hasattr(segment, 'emotion') and segment.emotion:
            emotion_name = segment.emotion.name
            
            # 遍历视频列表
            for video_list_name in video_lists:
                # 这里简化处理，实际应该从任务对象中获取视频列表
                # 假设任务对象有对应的视频列表属性
                pass
        
        # 如果没有找到匹配的视频，使用默认视频
        return default_video.replace("\\", "/")

    async def generate_all(
        self,
        task: Task,
        config: TaskConfig,
        cancel_callback: Optional[callable] = None,
        progress_callback: Optional[callable] = None
    ) -> List[VideoSegmentResult]:
        """
        生成任务所有视频段落

        Args:
            task: 任务
            config: 配置
            cancel_callback: 取消回调
            progress_callback: 进度回调函数，参数为 (completed, total, tag)

        Returns:
            视频结果列表
        """
        results = []

        # 检查是否取消
        if cancel_callback and cancel_callback():
            logger.info("任务被取消，停止视频生成")
            for segment in task.segments:
                results.append(VideoSegmentResult(
                    segment_id=segment.segment_id,
                    audio_path=segment.audio_path or "",
                    video_path=None,
                    duration=0.0,
                    status="failed",
                    error_message="任务被取消"
                ))
            return results

        # 检查任务和配置
        if not task:
            logger.error("任务对象为空")
            return results

        if not task.segments:
            logger.warning("任务没有段落")
            return results

        # 检查 HeyGemEngine 是否已加载
        if not self.heygem_engine or not self.heygem_engine.is_loaded:
            logger.error("HeyGemEngine 未加载")
            for segment in task.segments:
                results.append(VideoSegmentResult(
                    segment_id=segment.segment_id,
                    audio_path=segment.audio_path or "",
                    video_path=None,
                    duration=0.0,
                    status="failed",
                    error_message="HeyGemEngine 未加载"
                ))
            return results

        # 使用源视频或开场视频作为默认视频源
        source_video = task.source_video_path or task.opening_video
        if not source_video:
            logger.error("没有提供源视频")
            for segment in task.segments:
                results.append(VideoSegmentResult(
                    segment_id=segment.segment_id,
                    audio_path=segment.audio_path or "",
                    video_path=None,
                    duration=0.0,
                    status="failed",
                    error_message="没有提供源视频"
                ))
            return results

        if not os.path.exists(source_video):
            logger.error(f"源视频文件不存在: {source_video}")
            for segment in task.segments:
                results.append(VideoSegmentResult(
                    segment_id=segment.segment_id,
                    audio_path=segment.audio_path or "",
                    video_path=None,
                    duration=0.0,
                    status="failed",
                    error_message=f"源视频文件不存在: {source_video}"
                ))
            return results

        # 处理双人模式
        if config.enable_double_mode:
            # 获取按标签分组的音频路径
            tone_audio_paths = getattr(task, 'tone_audio_paths', None)
            
            if not tone_audio_paths:
                logger.error("双人模式需要按标签分组的音频路径")
                for segment in task.segments:
                    results.append(VideoSegmentResult(
                        segment_id=segment.segment_id,
                        audio_path=segment.audio_path or "",
                        video_path=None,
                        duration=0.0,
                        status="failed",
                        error_message="双人模式需要按标签分组的音频路径"
                    ))
                return results
            
            # 检查是否所有标签都已完成（不仅仅是最终视频存在）
            # 只有当所有标签的视频都已生成时才跳过
            all_tones_completed = True
            completed_tone_videos = getattr(task, 'completed_tone_videos', {})
            
            for tone in tone_audio_paths.keys():
                if tone not in completed_tone_videos or not os.path.exists(completed_tone_videos[tone]):
                    all_tones_completed = False
                    break
            
            if task.final_video_path and os.path.exists(task.final_video_path) and all_tones_completed:
                logger.info(f"双人模式最终视频已存在且所有标签已完成，跳过生成: {task.final_video_path}")
                for segment in task.segments:
                    results.append(VideoSegmentResult(
                        segment_id=segment.segment_id,
                        audio_path=segment.audio_path or "",
                        video_path=task.final_video_path,
                        duration=segment.duration or 0.0,
                        status="success"
                    ))
                return results
            
            # 如果最终视频存在但部分标签未完成，删除旧的最终视频，重新生成
            if task.final_video_path and os.path.exists(task.final_video_path) and not all_tones_completed:
                logger.warning(f"双人模式最终视频存在但部分标签未完成，将重新生成")
                # 不删除旧视频，而是重新生成并覆盖
            
            try:
                # 存储每个标签生成的视频路径（使用字典跟踪）
                tone_video_paths = []
                # 收集所有中间文件
                all_intermediate_files = []
                
                # 初始化或恢复已完成标签视频字典
                if not hasattr(task, 'completed_tone_videos'):
                    task.completed_tone_videos = {}
                
                # 确保源视频是绝对路径
                if not os.path.isabs(source_video):
                    source_video = os.path.abspath(source_video)
                
                # 导入标签匹配器
                from .tag_matcher import get_tag_matcher
                tag_matcher = get_tag_matcher()
                
                # 创建一个临时 segment 用于标签匹配
                @dataclass
                class TempSegment:
                    tone: str
                    segment_id: str = ""
                
                # 按标签顺序处理
                total_tones = len(tone_audio_paths)
                tone_index = 0
                for tone, audio_paths in tone_audio_paths.items():
                    tone_index += 1
                    # 检查是否取消
                    if cancel_callback and cancel_callback():
                        logger.info("任务被取消，停止双人模式视频生成")
                        break
                    
                    # 检查该标签是否已完成
                    if tone in completed_tone_videos and os.path.exists(completed_tone_videos[tone]):
                        logger.info(f"标签 '{tone}' 视频已完成，跳过: {completed_tone_videos[tone]}")
                        tone_video_paths.append(completed_tone_videos[tone])
                        continue
                    
                    left_audio = audio_paths.get("left")
                    right_audio = audio_paths.get("right")
                    
                    if not left_audio and not right_audio:
                        logger.warning(f"标签 '{tone}' 没有音频，跳过")
                        continue
                    
                    # 转换为绝对路径
                    if left_audio and not os.path.isabs(left_audio):
                        left_audio = os.path.abspath(left_audio)
                    if right_audio and not os.path.isabs(right_audio):
                        right_audio = os.path.abspath(right_audio)
                    
                    logger.info(f"处理标签 '{tone}': 左音频={left_audio}, 右音频={right_audio}")
                    
                    # 为当前标签匹配视频素材
                    temp_segment = TempSegment(tone=tone)
                    matched_video, is_scene_matched = self._get_scene_video(task, temp_segment)
                    
                    if not matched_video:
                        matched_video = source_video
                        is_scene_matched = False
                    
                    if not os.path.isabs(matched_video):
                        matched_video = os.path.abspath(matched_video)
                    
                    # 判断是否是场景标签且匹配成功
                    is_scene_tag = tag_matcher.is_scene_tag(tone)
                    
                    if is_scene_tag and is_scene_matched:
                        # 场景标签匹配成功：直接合并视频和音频，不调用 HeyGem
                        logger.info(f"标签 '{tone}' 场景视频匹配成功，直接合并视频和音频")
                        
                        # 合并左、右音频
                        scene_combined_audio = None
                        audio_list = []
                        if left_audio:
                            audio_list.append(left_audio)
                        if right_audio:
                            audio_list.append(right_audio)
                        
                        if audio_list:
                            scene_combined_audio = os.path.join(self.output_dir, f"scene_combined_{tone}_{task.task_id}.wav")
                            if len(audio_list) == 1:
                                scene_combined_audio = audio_list[0]
                            else:
                                if not await self._concat_audio_files(audio_list, scene_combined_audio):
                                    scene_combined_audio = None
                                else:
                                    # 记录中间文件
                                    all_intermediate_files.append(scene_combined_audio)
                        
                        if scene_combined_audio:
                            # 获取音频时长
                            audio_duration = await self._get_audio_duration(scene_combined_audio)
                            if audio_duration > 0:
                                # 输出文件名
                                scene_output_path = os.path.join(self.output_dir, f"scene_{tone}_{task.task_id}.mp4")
                                
                                # 使用 ffmpeg 处理：替换音频，并调整视频长度
                                success = await self._replace_audio_in_video(matched_video, scene_combined_audio, scene_output_path, audio_duration)
                                
                                if success and os.path.exists(scene_output_path):
                                    tone_video_paths.append(scene_output_path)
                                    # 记录已完成的标签视频
                                    task.completed_tone_videos[tone] = scene_output_path
                                    # 记录中间文件（如果不是最终输出）
                                    all_intermediate_files.append(scene_output_path)
                                    logger.info(f"标签 '{tone}' 场景视频生成完成: {scene_output_path}")
                                else:
                                    logger.error(f"标签 '{tone}' 场景视频生成失败")
                    else:
                        # 非场景标签：调用 HeyGem 合成，先左后右
                        current_source = matched_video
                        left_result = None
                        
                        # 第一次推理：左边说话人，使用 face_id=0
                        if left_audio and os.path.exists(left_audio):
                            logger.info(f"标签 '{tone}' 执行第一次 HeyGem 推理（左边说话人），视频源: {current_source}")
                            left_result = self._run_heygem_inference(left_audio, current_source, config, face_id=0, cancel_callback=cancel_callback)
                            # 如果任务被取消，跳出循环
                            if cancel_callback and cancel_callback():
                                logger.info(f"标签 '{tone}' 第一次推理后检测到任务已取消")
                                break
                            # 记录第一次推理结果作为中间文件
                            if left_result and os.path.exists(left_result):
                                all_intermediate_files.append(left_result)
                            current_source = left_result
                        else:
                            left_result = current_source
                            if left_audio:
                                logger.warning(f"标签 '{tone}' 左边音频文件不存在: {left_audio}")
                        
                        # 第二次推理：右边说话人，使用 face_id=1
                        if right_audio and os.path.exists(right_audio):
                            logger.info(f"标签 '{tone}' 执行第二次 HeyGem 推理（右边说话人）...")
                            right_result = self._run_heygem_inference(right_audio, left_result, config, face_id=1, cancel_callback=cancel_callback)
                            # 如果任务被取消，跳出循环
                            if cancel_callback and cancel_callback():
                                logger.info(f"标签 '{tone}' 第二次推理后检测到任务已取消")
                                break
                            # 记录第二次推理结果作为中间文件
                            if right_result and os.path.exists(right_result):
                                all_intermediate_files.append(right_result)
                            
                            # 方案 2：直接使用原始左右音频合并（新方案）
                            final_video_with_both_audio = None
                            if right_result and os.path.exists(right_result):
                                final_output_path = os.path.join(self.output_dir, f"final_{tone}_{task.task_id}.mp4")
                                final_video_with_both_audio = await self._merge_left_right_audio_to_video(
                                    video_path=right_result,
                                    left_audio_path=left_audio,
                                    right_audio_path=right_audio,
                                    output_path=final_output_path
                                )
                            
                            # 使用合并了两个声音的视频
                            if final_video_with_both_audio and os.path.exists(final_video_with_both_audio):
                                tone_video_paths.append(final_video_with_both_audio)
                                # 记录已完成的标签视频
                                task.completed_tone_videos[tone] = final_video_with_both_audio
                                # 记录中间文件
                                all_intermediate_files.append(final_output_path)
                                logger.info(f"标签 '{tone}' 视频生成完成（含左右声音）: {final_video_with_both_audio}")
                            else:
                                # 如果合并失败，回退到只有右边声音的视频
                                tone_video_paths.append(right_result)
                                # 记录已完成的标签视频
                                task.completed_tone_videos[tone] = right_result
                                logger.warning(f"标签 '{tone}' 音频合并失败，使用只有右边声音的视频: {right_result}")
                        else:
                            # 如果没有右边音频，使用左边结果
                            tone_video_paths.append(left_result)
                            # 记录已完成的标签视频
                            if left_result:
                                task.completed_tone_videos[tone] = left_result
                            if right_audio:
                                logger.warning(f"标签 '{tone}' 右边音频文件不存在: {right_audio}")

                    # 更新进度（双人模式）
                    if progress_callback:
                        progress_callback(tone_index, total_tones, tone)

                # 合并所有标签的视频
                if len(tone_video_paths) == 1:
                    final_video = tone_video_paths[0]
                elif len(tone_video_paths) > 1:
                    # 根据配置选择合并方式
                    if config.enable_transition:
                        # 使用转场效果合并
                        logger.info("双人模式启用转场效果，使用 xfade 滤镜合并")
                        final_video = await self._concat_videos_with_transition(
                            tone_video_paths, task.task_id, config
                        )
                        if not final_video:
                            # 转场合并失败，回退到普通合并
                            logger.warning("转场合并失败，回退到普通合并")
                            final_video = await self._concat_videos(tone_video_paths, task.task_id)
                    else:
                        # 使用普通合并
                        final_video = await self._concat_videos(tone_video_paths, task.task_id)
                    # 记录合并后的视频作为中间文件
                    if final_video:
                        merged_path = os.path.join(self.output_dir, f"merged_{task.task_id}.mp4")
                        if final_video == merged_path:
                            all_intermediate_files.append(merged_path)
                else:
                    final_video = None
                
                # 从中间文件列表中移除最终输出视频
                if final_video and final_video in all_intermediate_files:
                    all_intermediate_files.remove(final_video)
                
                if final_video:
                    task.final_video_path = final_video
                    logger.info(f"双人模式视频生成完成: {final_video}")
                    logger.info(f"双人模式中间文件: {all_intermediate_files}")
                    
                    # 为每个段落创建结果
                    for segment in task.segments:
                        results.append(VideoSegmentResult(
                            segment_id=segment.segment_id,
                            audio_path=segment.audio_path or "",
                            video_path=final_video,
                            duration=segment.duration or 0.0,
                            status="success",
                            intermediate_files=all_intermediate_files
                        ))
                else:
                    logger.error("双人模式视频生成失败：没有生成任何视频")
                    for segment in task.segments:
                        results.append(VideoSegmentResult(
                            segment_id=segment.segment_id,
                            audio_path=segment.audio_path or "",
                            video_path=None,
                            duration=0.0,
                            status="failed",
                            error_message="双人模式视频生成失败：没有生成任何视频"
                        ))
                
                task.progress = 90
            except Exception as e:
                logger.error(f"双人模式视频生成失败: {e}")
                for segment in task.segments:
                    results.append(VideoSegmentResult(
                        segment_id=segment.segment_id,
                        audio_path=segment.audio_path or "",
                        video_path=None,
                        duration=0.0,
                        status="failed",
                        error_message=str(e)
                    ))
        else:
            # 单人模式
            # 根据场景类型分配视频
            from .tag_matcher import get_tag_matcher
            tag_matcher = get_tag_matcher()
            
            for i, segment in enumerate(task.segments):
                if cancel_callback and cancel_callback():
                    logger.info("任务被取消，停止单人模式视频生成")
                    break
                
                if segment.output_path and os.path.exists(segment.output_path):
                    logger.info(f"段落 {segment.segment_id} 视频已存在，跳过生成: {segment.output_path}")
                    results.append(VideoSegmentResult(
                        segment_id=segment.segment_id,
                        audio_path=segment.audio_path or "",
                        video_path=segment.output_path,
                        duration=segment.duration or 0.0,
                        status="success"
                    ))
                    continue
                
                try:
                    # 检查段落是否有音频
                    if not segment.audio_path:
                        logger.error(f"段落 {segment.segment_id} 没有音频路径")
                        results.append(VideoSegmentResult(
                            segment_id=segment.segment_id,
                            audio_path="",
                            video_path=None,
                            duration=0.0,
                            status="failed",
                            error_message="没有音频文件"
                        ))
                        continue

                    # 检查音频文件是否存在
                    if not os.path.exists(segment.audio_path):
                        logger.error(f"音频文件不存在: {segment.audio_path}")
                        results.append(VideoSegmentResult(
                            segment_id=segment.segment_id,
                            audio_path=segment.audio_path,
                            video_path=None,
                            duration=0.0,
                            status="failed",
                            error_message=f"音频文件不存在: {segment.audio_path}"
                        ))
                        continue

                    # 选择对应场景的视频
                    video_source, is_scene_matched = self._get_scene_video(task, segment)
                    
                    # 检查是否是场景标签且匹配成功
                    tone = getattr(segment, 'tone', '')
                    if tag_matcher.is_scene_tag(tone) and is_scene_matched and video_source:
                        # 场景视频匹配成功：不需要调用 HeyGem 合成，直接使用匹配到的视频，然后合并音频
                        logger.info(f"段落 {segment.segment_id} 场景标签 '{tone}' 匹配成功，跳过 HeyGem 合成，直接使用匹配视频: {video_source}")
                        result = await self._process_scene_video(segment, video_source, task_id=task.task_id)
                        results.append(result)
                    else:
                        # 非场景视频或场景视频匹配失败：正常调用 HeyGem 合成
                        if tag_matcher.is_scene_tag(tone) and not is_scene_matched:
                            logger.info(f"段落 {segment.segment_id} 场景标签 '{tone}' 匹配失败，使用开场视频并调用 HeyGem 合成")
                        result = await self.generate_segment(
                            segment=segment,
                            video_source=video_source or source_video,
                            config=config,
                            task_id=task.task_id
                        )
                        results.append(result)

                    # 更新进度
                    if progress_callback:
                        total_segments = len(task.segments)
                        completed = i + 1
                        tag = getattr(segment, 'tone', None) or getattr(segment, 'scene', None) or getattr(segment, 'tag', None)
                        progress_callback(completed, total_segments, tag)

                    time.sleep(1)  # 避免并发过高
                except Exception as e:
                    logger.error(f"生成视频段落 {segment.segment_id} 时发生异常: {e}")
                    results.append(VideoSegmentResult(
                        segment_id=segment.segment_id,
                        audio_path=segment.audio_path or "",
                        video_path=None,
                        duration=0.0,
                        status="failed",
                        error_message=str(e)
                    ))

        return results
    
    async def _process_scene_video(self, segment: ScriptSegment, video_path: str, task_id: Optional[str] = None) -> VideoSegmentResult:
        """
        处理场景视频：不需要调用 HeyGem 合成，直接将音频合并到视频中并对齐长度

        Args:
            segment: 文案段落
            video_path: 匹配到的场景视频路径
            task_id: 任务ID，用于文件命名前缀

        Returns:
            处理结果
        """
        if not os.path.exists(video_path):
            logger.error(f"场景视频不存在: {video_path}")
            return VideoSegmentResult(
                segment_id=segment.segment_id,
                audio_path=segment.audio_path or "",
                video_path=None,
                duration=0.0,
                status="failed",
                error_message=f"场景视频不存在: {video_path}"
            )

        if not segment.audio_path or not os.path.exists(segment.audio_path):
            logger.error(f"音频文件不存在: {segment.audio_path}")
            return VideoSegmentResult(
                segment_id=segment.segment_id,
                audio_path=segment.audio_path or "",
                video_path=None,
                duration=0.0,
                status="failed",
                error_message="音频文件不存在"
            )

        try:
            # 获取音频时长
            audio_duration = await self._get_audio_duration(segment.audio_path)

            # 获取视频时长
            video_duration = await self._get_video_duration(video_path)

            if audio_duration <= 0 or video_duration <= 0:
                logger.error(f"无法获取音视频时长: 音频={audio_duration}, 视频={video_duration}")
                raise Exception(f"无法获取音视频时长: 音频={audio_duration}, 视频={video_duration}")

            logger.info(f"场景视频处理: 音频时长={audio_duration:.2f}s, 视频时长={video_duration:.2f}s")

            # 输出文件名：使用 task_id 前缀
            if task_id:
                output_filename = f"{task_id}_scene_{segment.segment_id}.mp4"
            else:
                output_filename = f"scene_{segment.segment_id}.mp4"
            output_path = os.path.join(self.output_dir, output_filename)

            # 使用 ffmpeg 处理：替换音频，并调整视频长度
            success = await self._replace_audio_in_video(video_path, segment.audio_path, output_path, audio_duration)

            if not success or not os.path.exists(output_path):
                logger.error(f"场景视频处理失败，输出文件不存在")
                raise Exception("场景视频处理失败，输出文件不存在")

            # 更新段落信息
            segment.video_path = output_path
            segment.duration = audio_duration
            segment.output_path = output_path

            logger.info(f"场景视频 {segment.segment_id} 处理完成: {output_path}")

            return VideoSegmentResult(
                segment_id=segment.segment_id,
                audio_path=segment.audio_path,
                video_path=output_path,
                duration=audio_duration,
                status="success"
            )

        except Exception as e:
            logger.error(f"处理场景视频 {segment.segment_id} 失败: {e}")
            return VideoSegmentResult(
                segment_id=segment.segment_id,
                audio_path=segment.audio_path or "",
                video_path=None,
                duration=0.0,
                status="failed",
                error_message=str(e)
            )
    
    async def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                audio_path
            ]

            logger.info(f"执行 ffprobe 获取音频时长: {' '.join(cmd)}")
            returncode, stdout, stderr = await async_run_subprocess(cmd, timeout=30)

            if returncode != 0:
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                logger.error(f"ffprobe 执行失败: {stderr_text}")
                return -1.0

            duration_str = stdout.decode('utf-8', errors='ignore').strip()
            if not duration_str:
                logger.error(f"ffprobe 返回空结果")
                return -1.0

            duration = float(duration_str)
            logger.info(f"音频时长获取成功: {duration:.2f}s")
            return duration

        except subprocess.TimeoutExpired:
            logger.error(f"获取音频时长超时: {audio_path}")
            return -1.0
        except ValueError as e:
            logger.error(f"解析音频时长失败: {e}")
            return -1.0
        except Exception as e:
            logger.error(f"获取音频时长失败: {e}")
            return -1.0
    
    async def _replace_audio_in_video(self, video_path: str, audio_path: str, output_path: str, target_duration: float) -> bool:
        """
        替换视频中的音频，并确保输出时长等于目标音频时长

        Args:
            video_path: 输入视频路径
            audio_path: 新音频路径
            output_path: 输出路径
            target_duration: 目标时长（音频时长）

        Returns:
            是否成功
        """
        video_duration = await self._get_video_duration(video_path)

        if video_duration <= 0:
            logger.error(f"无法获取视频时长: {video_duration}")
            return False

        logger.info(f"视频时长: {video_duration:.2f}s, 目标时长: {target_duration:.2f}s")

        if target_duration <= video_duration:
            # 音频时长小于等于视频时长：直接裁剪视频
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-i', audio_path,
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-t', str(target_duration),
                output_path
            ]
        else:
            # 音频时长大于视频时长：循环播放视频
            import math
            loop_count = int(math.ceil(target_duration / video_duration))
            logger.info(f"需要循环播放视频 {loop_count} 次")

            cmd = [
                'ffmpeg',
                '-stream_loop', str(loop_count - 1),
                '-i', video_path,
                '-i', audio_path,
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-t', str(target_duration),
                '-shortest',
                output_path
            ]

        logger.info(f"执行 ffmpeg 处理场景视频: {' '.join(cmd)}")
        returncode, stdout, stderr = await async_run_ffmpeg(cmd, timeout=120)

        if returncode != 0:
            stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
            logger.error(f"ffmpeg 执行失败: {stderr_text}")
            return False

        logger.info(f"ffmpeg 执行成功，输出: {output_path}")
        return True

    def _get_scene_video(self, task: Task, segment: ScriptSegment) -> tuple:
        """
        根据场景类型和文案标签获取匹配的视频素材
        按照需求文档重新实现匹配逻辑：
        1. 开场/结束标签 → 固定匹配开场/结束视频
        2. 情绪类标签 → 在循环视频区域匹配，映射到8个标准标签，相同标签随机选择
        3. 场景类标签 → 在场景视频区域匹配，支持相似标签，相同标签随机选择
        4. 如果没有匹配 → 使用开场视频作为后备
        
        Args:
            task: 任务对象
            segment: 文案段落，包含标签（tone）
            
        Returns:
            tuple: (视频路径, 是否匹配成功)
            - 视频路径：匹配的视频路径，如果没有匹配则返回后备的开场视频
            - 是否匹配成功：True 表示成功匹配到场景视频，False 表示回退到开场视频
        """
        from .tag_matcher import get_tag_matcher
        
        tag_matcher = get_tag_matcher()
        # 标签数据在服务启动时和设置变更时已加载，无需每次重新加载
        tone = getattr(segment, 'tone', '')
        
        if not tone:
            logger.warning(f"段落 {segment.segment_id} 没有标签，使用开场视频")
            return (self._get_fallback_video(task), False)
        
        # ==================== 规则 1: 开场/结束标签 ====================
        if tone == "开场":
            if task.opening_video_with_tags:
                return (task.opening_video_with_tags.file_path, False)
            elif task.opening_video:
                return (task.opening_video, False)
            else:
                return (self._get_fallback_video(task), False)
        
        if tone == "结束":
            if task.ending_video_with_tags:
                return (task.ending_video_with_tags.file_path, False)
            elif task.ending_video:
                return (task.ending_video, False)
            else:
                return (self._get_fallback_video(task), False)
        
        # ==================== 规则 2: 场景类标签 ====================
        if tag_matcher.is_scene_tag(tone):
            scene_video_list = self._collect_scene_videos(task)
            if not scene_video_list:
                logger.warning(f"段落 {segment.segment_id} 场景标签 '{tone}' 没有场景视频，使用开场视频")
                return (self._get_fallback_video(task), False)
            
            match_result = tag_matcher.match_scene_video(tone, scene_video_list)
            if match_result:
                return (match_result.video_path, True)
            
            logger.warning(f"段落 {segment.segment_id} 场景标签 '{tone}' 匹配失败，使用开场视频")
            return (self._get_fallback_video(task), False)
        
        # ==================== 规则 3: 情绪类标签 ====================
        if tag_matcher.is_emotion_tag(tone):
            loop_video_list = self._collect_loop_videos(task)
            if not loop_video_list:
                logger.warning(f"段落 {segment.segment_id} 情绪标签 '{tone}' 没有循环视频，使用开场视频")
                return (self._get_fallback_video(task), False)
            
            match_result = tag_matcher.match_emotion_video(tone, loop_video_list)
            if match_result:
                return (match_result.video_path, False)
            
            logger.warning(f"段落 {segment.segment_id} 情绪标签 '{tone}' 匹配失败，使用开场视频")
            return (self._get_fallback_video(task), False)
        
        # ==================== 未知标签 ====================
        logger.warning(f"段落 {segment.segment_id} 未知标签 '{tone}'，使用开场视频")
        return (self._get_fallback_video(task), False)
    
    def _collect_scene_videos(self, task: Task) -> List[Dict]:
        """
        收集所有场景视频，转换为统一格式
        
        Args:
            task: 任务对象
            
        Returns:
            场景视频列表，每个元素是 {'file_path': str, 'scene_tags': List[str]}
        """
        result = []
        
        # 处理带标签的场景视频
        if hasattr(task, 'scene_videos_with_tags') and task.scene_videos_with_tags:
            for video in task.scene_videos_with_tags:
                result.append({
                    'file_path': video.file_path,
                    'scene_tags': video.scene_tags
                })
        
        # 如果没有带标签的，尝试从旧接口获取
        if not result and hasattr(task, 'scene_videos') and task.scene_videos:
            for video_path in task.scene_videos:
                scene_tags = []
                # 从文件名提取标签
                for tag in ["环境展示", "产品展示", "细节展示", "功能介绍", "使用效果"]:
                    if tag in video_path:
                        scene_tags.append(tag)
                result.append({
                    'file_path': video_path,
                    'scene_tags': scene_tags
                })
        
        return result
    
    def _collect_loop_videos(self, task: Task) -> List[Dict]:
        """
        收集所有循环视频，转换为统一格式
        
        Args:
            task: 任务对象
            
        Returns:
            循环视频列表，每个元素是 {'file_path': str, 'emotion_tags': List[str]}
        """
        result = []
        
        # 处理带标签的循环视频
        if hasattr(task, 'loop_videos_with_tags') and task.loop_videos_with_tags:
            for video in task.loop_videos_with_tags:
                result.append({
                    'file_path': video.file_path,
                    'emotion_tags': video.emotion_tags
                })
        
        # 如果没有带标签的，尝试从旧接口获取
        if not result and hasattr(task, 'loop_videos') and task.loop_videos:
            standard_emotions = ["开心", "生气", "难过", "害怕", "厌恶", "低落", "惊喜", "冷静"]
            for video_path in task.loop_videos:
                emotion_tags = []
                # 从文件名提取标签
                for emotion in standard_emotions:
                    if emotion in video_path:
                        emotion_tags.append(emotion)
                result.append({
                    'file_path': video_path,
                    'emotion_tags': emotion_tags
                })
        
        return result
    
    def _get_fallback_video(self, task: Task) -> str:
        """
        获取后备视频（开场视频）
        
        Args:
            task: 任务对象
            
        Returns:
            后备视频路径
        """
        if task.opening_video_with_tags:
            return task.opening_video_with_tags.file_path
        if task.opening_video:
            return task.opening_video
        return task.source_video_path

    def _run_heygem_with_auto_restart(
        self,
        audio_path: str,
        video_source: str,
        config: TaskConfig,
        face_id: int = -1,
        cancel_callback=None,
        output_filename: str = None
    ) -> str:
        """
        使用 HeyGemEngine 进行视频生成

        Args:
            audio_path: 音频文件路径
            video_source: 视频源路径
            config: 任务配置
            face_id: 面部编号
            cancel_callback: 取消回调函数
            output_filename: 输出文件名（可选，如果提供则直接保存到目标路径）

        Returns:
            生成的视频路径

        Raises:
            Exception: 视频生成失败
        """
        # 使用引擎模式
        logger.info("使用 HeyGemEngine 引擎模式")
        result = self._run_heygem_inference_engine(
            audio_path=audio_path,
            video_source=video_source,
            config=config,
            face_id=face_id,
            cancel_callback=cancel_callback,
            output_filename=output_filename
        )
        if result:
            return result
        raise Exception("HeyGemEngine 视频生成失败")

    def _run_heygem_inference(
        self,
        audio_path: str,
        video_source: str,
        config: TaskConfig,
        face_id: int = -1,
        cancel_callback=None,
        output_filename: str = None
    ) -> Optional[str]:
        """
        使用 HeyGemEngine 进行视频推理（双人模式专用）

        Args:
            audio_path: 音频路径
            video_source: 视频源路径
            config: 配置
            face_id: 驱动人脸序号，0=第一张，1=第二张，-1=所有脸
            cancel_callback: 取消回调函数
            output_filename: 输出文件名（可选）

        Returns:
            生成的视频路径，失败返回 None
        """
        return self._run_heygem_inference_engine(
            audio_path=audio_path,
            video_source=video_source,
            config=config,
            face_id=face_id,
            cancel_callback=cancel_callback,
            output_filename=output_filename
        )

    def _run_heygem_inference_engine(
        self,
        audio_path: str,
        video_source: str,
        config: TaskConfig,
        face_id: int = -1,
        cancel_callback=None,
        output_filename: str = None
    ) -> Optional[str]:
        """
        使用 HeyGemEngine 进行视频生成

        Args:
            audio_path: 音频路径
            video_source: 视频源路径
            config: 配置
            face_id: 驱动人脸序号，0=第一张，-1=所有脸
            cancel_callback: 取消回调函数
            output_filename: 输出文件名（可选，如果提供则直接保存到目标路径）

        Returns:
            生成的视频路径，失败返回 None
        """
        if not self.heygem_engine:
            logger.error("HeyGemEngine 未初始化")
            return None

        try:
            # 确保引擎已加载
            if not self.heygem_engine.is_loaded:
                logger.info("HeyGemEngine 未加载，正在加载...")
                if not self.heygem_engine.load():
                    logger.error("HeyGemEngine 加载失败")
                    return None

            # 检查是否取消
            if cancel_callback and cancel_callback():
                logger.info("任务已取消")
                return None

            # 生成唯一的任务 ID 或使用指定的文件名
            if output_filename:
                # 使用指定的文件名（去掉 .mp4 后缀作为 task_id）
                task_id = output_filename.replace(".mp4", "")
            else:
                import uuid
                task_id = str(uuid.uuid4())[:8]

            # 调用引擎生成视频
            logger.info(f"使用 HeyGemEngine 引擎模式生成视频: task_id={task_id}")

            # 调试日志：追踪 batch_size 参数传递
            actual_batch_size = config.inference_batch_size if hasattr(config, 'inference_batch_size') else 8
            logger.info(f"VideoSynthesizer batch_size 配置: config.inference_batch_size={getattr(config, 'inference_batch_size', 'NOT_FOUND')}, 实际使用={actual_batch_size}")

            result = self.heygem_engine.generate_video_simple(
                audio_path=audio_path,
                video_path=video_source,
                task_id=task_id,
                output_dir=self.output_dir,
                face_id=face_id,
                steps=config.heygem_steps if hasattr(config, 'heygem_steps') else 16,
                batch_size=actual_batch_size
            )

            if result and os.path.exists(result):
                logger.info(f"HeyGemEngine 视频生成成功: {result}")
                return result
            else:
                logger.error("HeyGemEngine 视频生成失败")
                return None

        except Exception as e:
            logger.error(f"HeyGemEngine 视频生成异常: {e}")
            return None

    def _save_video(self, source_path: str, filename: str) -> str:
        """保存视频到输出目录（移动而非复制，避免磁盘空间浪费）"""
        output_path = os.path.join(self.output_dir, filename)

        try:
            if source_path != output_path:
                shutil.move(source_path, output_path)
                logger.info(f"视频已移动: {source_path} -> {output_path}")
        except Exception as e:
            logger.error(f"移动视频失败，尝试复制: {e}")
            try:
                shutil.copy2(source_path, output_path)
                logger.info(f"视频已复制: {source_path} -> {output_path}")
            except Exception as e2:
                logger.error(f"复制视频也失败: {e2}")
                raise

        return output_path

    async def _get_video_duration(self, video_path: str) -> float:
        """获取视频时长"""
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.release()
            return frames / fps if fps > 0 else 0.0
        except cv2.error as e:
            logger.error(f"视频文件格式错误: {e}")
            return 0.0
        except Exception as e:
            logger.error(f"获取视频时长时发生异常: {e}")
            raise

    async def concatenate_videos(
        self,
        video_paths: List[str],
        output_path: str,
        audio_paths: Optional[List[str]] = None
    ) -> bool:
        """
        合并多个视频片段

        Args:
            video_paths: 视频路径列表
            output_path: 输出路径
            audio_paths: 可选的独立音频列表

        Returns:
            是否成功
        """
        if not video_paths:
            return False

        try:
            # 如果有独立音频，先合并音频
            if audio_paths:
                temp_video = output_path.replace(".mp4", "_temp.mp4")
                await self._concat_videos_simple(video_paths, temp_video)

                # 合并音频
                await self._merge_audio_video(temp_video, audio_paths, output_path)

                # 清理临时文件
                if os.path.exists(temp_video):
                    os.remove(temp_video)
            else:
                # 直接合并视频
                await self._concat_videos_simple(video_paths, output_path)

            logger.info(f"视频合并成功: {output_path}")
            return True

        except Exception as e:
            logger.error(f"视频合并失败: {e}")
            return False

    async def _concat_videos(self, video_paths: List[str], task_id: str) -> Optional[str]:
        """
        合并多个视频文件

        Args:
            video_paths: 视频文件路径列表
            task_id: 任务ID

        Returns:
            合并后的视频路径，失败返回 None
        """
        if not video_paths:
            logger.warning("没有视频文件需要合并")
            return None
        
        if len(video_paths) == 1:
            return video_paths[0]
        
        try:
            output_path = os.path.join(self.output_dir, f"merged_{task_id}.mp4")
            
            # 第一步：收集所有视频的信息，确定目标分辨率和帧率
            video_infos = []
            target_width = 0
            target_height = 0
            target_fps = 30
            
            for path in video_paths:
                if not os.path.isabs(path):
                    path = os.path.abspath(path)
                info = await self._get_video_info(path)
                if info:
                    video_infos.append((path, info))
                    # 使用最大的分辨率作为目标
                    if info.get("width", 0) > target_width or info.get("height", 0) > target_height:
                        target_width = max(target_width, info.get("width", 0))
                        target_height = max(target_height, info.get("height", 0))
                    # 使用最常见的帧率
                    if info.get("fps", 0) > 0:
                        target_fps = info.get("fps", 30)
                else:
                    video_infos.append((path, None))
            
            logger.info(f"目标分辨率: {target_width}x{target_height}, 目标帧率: {target_fps}")
            
            # 第二步：检查是否所有视频参数一致
            needs_normalize_all = False
            for path, info in video_infos:
                if not info:
                    needs_normalize_all = True
                    logger.warning(f"无法获取视频信息，需要标准化: {path}")
                    break
                # 检查分辨率是否一致
                if info.get("width", 0) != target_width or info.get("height", 0) != target_height:
                    needs_normalize_all = True
                    logger.info(f"视频分辨率不一致: {info.get('width')}x{info.get('height')} vs {target_width}x{target_height}，需要标准化: {path}")
                    break
                # 检查编码
                if info.get("codec", "").lower() not in ["h264", "libx264"]:
                    needs_normalize_all = True
                    logger.info(f"视频编码不是 h264: {info.get('codec')}，需要标准化: {path}")
                    break
            
            # 第三步：对所有视频进行标准化处理
            normalized_paths = []
            for i, (path, info) in enumerate(video_infos):
                if needs_normalize_all or (info and self._check_video_needs_normalize(info)):
                    # 标准化视频
                    normalized_path = os.path.join(self.output_dir, f"normalized_{task_id}_{i}.mp4")
                    if await self._normalize_video_with_resolution(path, normalized_path, target_width, target_height, target_fps):
                        normalized_paths.append(normalized_path)
                        logger.info(f"视频标准化完成: {path} -> {normalized_path}")
                    else:
                        logger.warning(f"视频标准化失败，使用原始视频: {path}")
                        normalized_paths.append(path)
                else:
                    normalized_paths.append(path)
            
            # 创建临时文件列表
            list_file = os.path.join(self.output_dir, f"concat_list_{task_id}.txt")
            with open(list_file, 'w', encoding='utf-8') as f:
                for path in normalized_paths:
                    if not os.path.isabs(path):
                        path = os.path.abspath(path)
                    escaped_path = path.replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")
            
            # 使用重新编码的方式合并，确保所有视频参数一致
            # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
            cmd = [
                "ffmpeg", "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                output_path
            ]

            logger.info(f"执行视频合并命令: {' '.join(cmd)}")
            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            # 清理临时文件
            if os.path.exists(list_file):
                os.remove(list_file)

            # 清理标准化后的临时视频文件
            for path in normalized_paths:
                if "normalized_" in path and os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.debug(f"清理临时标准化视频: {path}")
                    except Exception as e:
                        logger.warning(f"清理临时文件失败: {path}, 错误: {e}")

            if returncode == 0:
                logger.info(f"视频合并成功: {output_path}")
                return output_path
            else:
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                logger.error(f"视频合并失败: {stderr_text}")
                return None

        except Exception as e:
            logger.error(f"视频合并时发生异常: {e}")
            return None

    async def _concat_videos_with_transition(
        self,
        video_paths: List[str],
        task_id: str,
        config: TaskConfig
    ) -> Optional[str]:
        """
        使用 FFmpeg xfade 滤镜合并视频（带转场效果）

        Args:
            video_paths: 视频路径列表
            task_id: 任务ID
            config: 任务配置（包含转场参数）

        Returns:
            合并后的视频路径，失败返回 None
        """
        if not video_paths:
            logger.warning("没有视频文件需要合并")
            return None

        if len(video_paths) < 2:
            logger.warning("转场效果需要至少 2 个视频片段")
            return video_paths[0] if video_paths else None

        try:
            output_path = os.path.join(self.output_dir, f"merged_{task_id}.mp4")
            temp_dir = tempfile.mkdtemp(prefix="video_transition_")

            try:
                # 1. 获取所有视频的信息，确定统一参数
                all_metadata = []
                for path in video_paths:
                    if os.path.exists(path):
                        info = await self._get_video_info(path)
                        if info:
                            all_metadata.append(info)

                if not all_metadata:
                    logger.error("无法获取任何视频的元数据")
                    return None

                target_width = max(m.get('width', 1920) for m in all_metadata)
                target_height = max(m.get('height', 1080) for m in all_metadata)
                target_fps = max(m.get('fps', 30.0) for m in all_metadata)

                logger.info(f"统一视频参数: 分辨率 {target_width}x{target_height}, 帧率 {target_fps}fps")

                # 2. 标准化所有视频
                normalized_paths = []
                video_durations = []

                for i, video_path in enumerate(video_paths):
                    if not os.path.exists(video_path):
                        logger.warning(f"视频文件不存在，跳过: {video_path}")
                        continue

                    info = await self._get_video_info(video_path)

                    # 标准化视频
                    normalized_path = os.path.join(temp_dir, f"normalized_{i:03d}.mp4")
                    needs_normalize = (
                        not info or
                        info.get('width', 0) != target_width or
                        info.get('height', 0) != target_height or
                        abs(info.get('fps', 30.0) - target_fps) > 0.1
                    )

                    if needs_normalize:
                        if await self._normalize_video_with_resolution(video_path, normalized_path, target_width, target_height, target_fps):
                            normalized_paths.append(normalized_path)
                        else:
                            logger.warning(f"视频标准化失败，使用原始视频: {video_path}")
                            normalized_paths.append(video_path)
                    else:
                        normalized_paths.append(video_path)

                    # 获取视频时长
                    duration = await self._get_video_duration(normalized_paths[-1])
                    video_durations.append(duration)

                if len(normalized_paths) < 2:
                    logger.error("标准化后有效视频不足 2 个")
                    return None

                # 3. 构建转场效果序列
                transition_duration = config.transition_duration
                effects = self._build_transition_effects(len(normalized_paths), config)

                # 4. 构建 xfade 滤镜链
                filter_complex = self._build_xfade_filter_chain(
                    normalized_paths,
                    video_durations,
                    effects,
                    transition_duration
                )

                if not filter_complex:
                    logger.error("构建 xfade 滤镜链失败")
                    return None

                # 构建音频合并滤镜（使用 acrossfade 与视频转场同步）
                if len(normalized_paths) == 2:
                    audio_filter = f"[0:a][1:a]acrossfade=d={transition_duration}:c1=tri:c2=tri[aout]"
                else:
                    # 多个视频：链式音频 acrossfade
                    audio_filter_parts = []
                    current_audio_input = "[0:a]"
                    for i in range(len(normalized_paths) - 1):
                        output_label = f"[a{i}]" if i < len(normalized_paths) - 2 else "[aout]"
                        audio_filter_part = f"{current_audio_input}[{i+1}:a]acrossfade=d={transition_duration}:c1=tri:c2=tri{output_label}"
                        audio_filter_parts.append(audio_filter_part)
                        current_audio_input = f"[a{i}]"
                    audio_filter = ";".join(audio_filter_parts)

                full_filter_complex = f"{filter_complex};{audio_filter}"

                # 5. 执行 FFmpeg 命令
                # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
                cmd = ["ffmpeg"]

                for path in normalized_paths:
                    cmd.extend(["-i", path])

                cmd.extend(["-filter_complex", full_filter_complex])
                cmd.extend([
                    "-map", "[vout]",
                    "-map", "[aout]",
                    "-c:v", "libx264",
                    "-crf", "18",
                    "-preset", "medium",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    output_path
                ])

                logger.info(f"转场合并命令: {' '.join(cmd)}")
                returncode, stdout, stderr = await async_run_ffmpeg(cmd)

                if returncode != 0:
                    stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                    logger.error(f"转场合并失败: {stderr_text}")
                    return None

                logger.info(f"转场合并成功: {output_path}")
                return output_path

            finally:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"转场合并失败: {e}")
            return None

    def _build_transition_effects(
        self,
        video_count: int,
        config: TaskConfig
    ) -> List[str]:
        """
        构建转场效果序列

        Args:
            video_count: 视频数量
            config: 任务配置

        Returns:
            转场效果名称列表
        """
        transition_count = video_count - 1

        if config.transition_random:
            if config.transition_random_all:
                effects = [random.choice(ALL_TRANSITION_EFFECTS) for _ in range(transition_count)]
                logger.info(f"随机转场效果（每次不同）: {effects}")
            else:
                effect = random.choice(ALL_TRANSITION_EFFECTS)
                effects = [effect] * transition_count
                logger.info(f"随机转场效果（统一）: {effect}")
        else:
            effect = config.transition_effect
            if not is_valid_transition_effect(effect):
                logger.warning(f"无效的转场效果 '{effect}'，使用默认 'fade'")
                effect = "fade"
            effects = [effect] * transition_count
            logger.info(f"指定转场效果: {effect}")

        return effects

    def _build_xfade_filter_chain(
        self,
        video_paths: List[str],
        video_durations: List[float],
        effects: List[str],
        transition_duration: float
    ) -> Optional[str]:
        """
        构建 xfade 滤镜链

        Args:
            video_paths: 视频路径列表
            video_durations: 视频时长列表
            effects: 转场效果名称列表
            transition_duration: 转场时长

        Returns:
            滤镜字符串，失败返回 None
        """
        try:
            n = len(video_paths)
            if n < 2:
                return None

            min_duration = min(video_durations)
            if transition_duration >= min_duration:
                logger.warning(f"转场时长 {transition_duration}s 超过最短视频时长 {min_duration}s，自动调整为 {min_duration * 0.4:.2f}s")
                transition_duration = min_duration * 0.4

            filter_parts = []
            accumulated_duration = 0.0
            current_input = "[0:v]"

            for i in range(n - 1):
                effect = effects[i] if i < len(effects) else "fade"
                output_label = f"[v{i}]" if i < n - 2 else "[vout]"

                accumulated_duration += video_durations[i]
                current_offset = accumulated_duration - transition_duration

                filter_part = f"{current_input}[{i+1}:v]xfade=transition={effect}:duration={transition_duration}:offset={current_offset:.3f}{output_label}"
                filter_parts.append(filter_part)

                current_input = f"[v{i}]"
                accumulated_duration -= transition_duration

            filter_complex = ";".join(filter_parts)
            logger.info(f"xfade 滤镜链: {filter_complex}")

            return filter_complex

        except Exception as e:
            logger.error(f"构建 xfade 滤镜链失败: {e}")
            return None

    async def _get_video_duration(self, video_path: str) -> float:
        """
        获取视频时长

        Args:
            video_path: 视频路径

        Returns:
            视频时长（秒）
        """
        info = await self._get_video_info(video_path)
        if info and 'duration' in info:
            return info['duration']

        # 备用方法：使用 ffprobe
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]
            returncode, stdout, stderr = await async_run_subprocess(cmd, timeout=30)
            if returncode == 0 and stdout:
                stdout_text = stdout.decode('utf-8', errors='ignore').strip()
                if stdout_text:
                    return float(stdout_text)
        except Exception as e:
            logger.warning(f"获取视频时长失败: {e}")

        return 0.0

    async def _concat_audio_files(self, audio_files: List[str], output_path: str) -> bool:
        """
        合并多个音频文件

        Args:
            audio_files: 音频文件路径列表
            output_path: 输出文件路径

        Returns:
            是否成功
        """
        import uuid

        if not audio_files:
            logger.warning("没有音频文件需要合并")
            return False

        try:
            # 使用 concat 协议
            concat_file = os.path.join(self.output_dir, f"concat_{uuid.uuid4().hex[:8]}.txt")

            with open(concat_file, 'w', encoding='utf-8') as f:
                for audio_path in audio_files:
                    # 转换为绝对路径
                    if not os.path.isabs(audio_path):
                        audio_path = os.path.abspath(audio_path)
                    if os.path.exists(audio_path):
                        # 路径中可能包含特殊字符，需要转义
                        escaped_path = audio_path.replace("'", "'\\''")
                        f.write(f"file '{escaped_path}'\n")

            # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c:a", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                output_path
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            # 清理临时文件
            if os.path.exists(concat_file):
                os.remove(concat_file)

            if returncode == 0:
                return True
            else:
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                logger.error(f"合并音频失败: {stderr_text}")
                return False

        except Exception as e:
            logger.error(f"合并音频时发生异常: {e}")
            return False

    async def _concat_videos_simple(self, video_paths: List[str], output_path: str):
        """简单合并视频（无音频）"""
        # 创建临时文件列表
        list_file = os.path.join(self.output_dir, "concat_list.txt")
        with open(list_file, 'w', encoding='utf-8') as f:
            for path in video_paths:
                f.write(f"file '{path}'\n")

        # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
        cmd = [
            "ffmpeg", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", output_path
        ]

        await async_run_ffmpeg(cmd, check=True)
        os.remove(list_file)

    async def _extract_audio_from_video(self, video_path: str, output_audio_path: str) -> bool:
        """
        从视频中提取音频

        Args:
            video_path: 视频文件路径
            output_audio_path: 输出音频文件路径

        Returns:
            是否成功
        """
        try:
            # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                output_audio_path
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if returncode == 0 and os.path.exists(output_audio_path):
                logger.info(f"从视频中提取音频成功: {output_audio_path}")
                return True
            else:
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                logger.error(f"从视频中提取音频失败: {stderr_text}")
                return False

        except Exception as e:
            logger.error(f"提取音频时发生异常: {e}")
            return False
    
    async def _merge_left_right_audio_to_video(
        self,
        video_path: str,
        left_audio_path: str,
        right_audio_path: str,
        output_path: str
    ) -> Optional[str]:
        """
        合并左右音频到视频（双人模式）

        Args:
            video_path: 第二次 HeyGem 生成的视频（只有右边声音）
            left_audio_path: 从第一次结果提取的左边音频
            right_audio_path: 原始的右边音频
            output_path: 最终输出视频路径

        Returns:
            最终视频路径，失败返回 None
        """
        try:
            # 先合并左右音频
            combined_audio = os.path.join(self.output_dir, f"combined_{os.path.basename(output_path).replace('.mp4', '')}.wav")

            if left_audio_path and right_audio_path:
                # 同时有左右音频，使用 amix 混合并保持音量
                # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
                cmd = [
                    "ffmpeg",
                    "-i", left_audio_path,
                    "-i", right_audio_path,
                    "-filter_complex", "amix=inputs=2:duration=longest,volume=2",
                    "-ac", "1",
                    "-ar", "16000",
                    combined_audio
                ]
            elif left_audio_path:
                # 只有左边音频
                import shutil
                shutil.copy2(left_audio_path, combined_audio)
            elif right_audio_path:
                # 只有右边音频
                import shutil
                shutil.copy2(right_audio_path, combined_audio)
            else:
                logger.error("没有可用的音频文件")
                return None

            # 执行音频合并（如果需要）
            if left_audio_path and right_audio_path:
                returncode, stdout, stderr = await async_run_ffmpeg(cmd)
                if returncode != 0:
                    stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                    logger.error(f"合并左右音频失败: {stderr_text}")
                    return None

            # 将合并后的音频替换到视频中
            final_output = output_path

            # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-i", combined_audio,
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                final_output
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            # 清理临时文件
            if os.path.exists(combined_audio):
                os.remove(combined_audio)

            if returncode == 0 and os.path.exists(final_output):
                logger.info(f"合并左右音频到视频成功: {final_output}")
                return final_output
            else:
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                logger.error(f"合并音频到视频失败: {stderr_text}")
                return None

        except Exception as e:
            logger.error(f"合并左右音频时发生异常: {e}")
            return None
    
    async def _merge_audio_video(
        self,
        video_path: str,
        audio_paths: List[str],
        output_path: str
    ):
        """合并音频和视频"""
        # 先合并所有音频
        concat_audio = os.path.join(self.output_dir, "concat_audio.wav")

        list_file = os.path.join(self.output_dir, "audio_list.txt")
        with open(list_file, 'w', encoding='utf-8') as f:
            for path in audio_paths:
                f.write(f"file '{path}'\n")

        # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
        cmd = [
            "ffmpeg", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", concat_audio
        ]
        await async_run_ffmpeg(cmd, check=True)
        os.remove(list_file)

        # 合并音频和视频
        cmd = [
            "ffmpeg", "-i", video_path, "-i", concat_audio,
            "-c:v", "copy", "-c:a", "aac", "-strict", "experimental",
            output_path
        ]
        await async_run_ffmpeg(cmd, check=True)

        # 清理临时音频
        if os.path.exists(concat_audio):
            os.remove(concat_audio)

    async def _get_video_info(self, video_path: str) -> Optional[Dict[str, Any]]:
        """
        获取视频信息（分辨率、帧率、编码等）

        Args:
            video_path: 视频文件路径

        Returns:
            视频信息字典，失败返回 None
        """
        import json

        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                video_path
            ]

            returncode, stdout, stderr = await async_run_subprocess(cmd, timeout=30)

            if returncode != 0:
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                logger.error(f"ffprobe 执行失败: {stderr_text}")
                return None

            stdout_text = stdout.decode('utf-8', errors='ignore') if stdout else ''
            data = json.loads(stdout_text)

            video_stream = None
            audio_stream = None

            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video" and video_stream is None:
                    video_stream = stream
                elif stream.get("codec_type") == "audio" and audio_stream is None:
                    audio_stream = stream

            if not video_stream:
                logger.error(f"视频文件中没有视频流: {video_path}")
                return None

            # 解析帧率
            fps_str = video_stream.get("r_frame_rate", "30/1")
            if "/" in fps_str:
                num, den = fps_str.split("/")
                fps = float(num) / float(den) if float(den) != 0 else 30.0
            else:
                fps = float(fps_str)

            return {
                "width": video_stream.get("width", 0),
                "height": video_stream.get("height", 0),
                "fps": fps,
                "codec": video_stream.get("codec_name", ""),
                "duration": float(data.get("format", {}).get("duration", 0)),
                "has_audio": audio_stream is not None,
                "audio_codec": audio_stream.get("codec_name", "") if audio_stream else None
            }

        except Exception as e:
            logger.error(f"获取视频信息失败: {e}")
            return None

    def _check_video_needs_normalize(self, video_info: Dict[str, Any]) -> bool:
        """
        检查视频是否需要标准化
        
        标准化条件：
        - 编码不是 h264
        - 分辨率不是标准分辨率（如 1080p, 720p）
        - 帧率不是常见帧率（如 24, 25, 30, 60）
        
        Args:
            video_info: 视频信息字典
            
        Returns:
            是否需要标准化
        """
        if not video_info:
            return True
        
        codec = video_info.get("codec", "")
        fps = video_info.get("fps", 0)
        
        # 检查编码
        if codec.lower() not in ["h264", "libx264"]:
            logger.info(f"视频编码不是 h264: {codec}，需要标准化")
            return True
        
        # 检查帧率（允许 24, 25, 30, 60 等常见帧率）
        common_fps = [23.976, 24, 25, 29.97, 30, 59.94, 60]
        fps_match = any(abs(fps - cfps) < 0.1 for cfps in common_fps)
        if not fps_match:
            logger.info(f"视频帧率不是常见帧率: {fps}，需要标准化")
            return True
        
        return False

    async def _normalize_video(self, input_path: str, output_path: str) -> bool:
        """
        标准化视频（统一编码、帧率）

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径

        Returns:
            是否成功
        """
        try:
            # 获取输入视频信息
            video_info = await self._get_video_info(input_path)
            if not video_info:
                logger.error(f"无法获取视频信息: {input_path}")
                return False

            # 标准化参数
            # 保持原始分辨率，统一编码为 h264，帧率保持原样或转为 30fps
            fps = video_info.get("fps", 30)
            if fps < 20 or fps > 60:
                fps = 30

            # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-r", str(fps),
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                output_path
            ]

            logger.info(f"执行视频标准化: {' '.join(cmd)}")
            returncode, stdout, stderr = await async_run_ffmpeg(cmd, timeout=600)

            if returncode == 0 and os.path.exists(output_path):
                logger.info(f"视频标准化成功: {output_path}")
                return True
            else:
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                logger.error(f"视频标准化失败: {stderr_text}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"视频标准化超时: {input_path}")
            return False
        except Exception as e:
            logger.error(f"视频标准化异常: {e}")
            return False

    async def _normalize_video_with_resolution(self, input_path: str, output_path: str, target_width: int, target_height: int, target_fps: float) -> bool:
        """
        标准化视频（统一分辨率、编码、帧率）

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            target_width: 目标宽度
            target_height: 目标高度
            target_fps: 目标帧率

        Returns:
            是否成功
        """
        try:
            # 使用 scale 滤镜缩放视频，同时统一编码和帧率
            # scale 参数：force_original_aspect_ratio=decrease 保持宽高比，不超过目标尺寸
            # pad 参数：填充到目标尺寸
            scale_filter = f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black"

            # 注意: async_run_ffmpeg 会自动添加 -y 参数，所以移除 cmd 中的 -y
            cmd = [
                "ffmpeg",
                "-i", input_path,
                "-vf", scale_filter,
                "-r", str(target_fps),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                output_path
            ]

            logger.info(f"执行视频标准化（分辨率: {target_width}x{target_height}, 帧率: {target_fps}）: {' '.join(cmd)}")
            returncode, stdout, stderr = await async_run_ffmpeg(cmd, timeout=600)

            if returncode == 0 and os.path.exists(output_path):
                logger.info(f"视频标准化成功: {output_path}")
                return True
            else:
                stderr_text = stderr.decode('utf-8', errors='ignore') if stderr else ''
                logger.error(f"视频标准化失败: {stderr_text}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"视频标准化超时: {input_path}")
            return False
        except Exception as e:
            logger.error(f"视频标准化异常: {e}")
            return False

    def close(self):
        """关闭合成器"""
        # 引擎模式下无需关闭客户端
        logger.info("VideoSynthesizer 已关闭")


def create_video_synthesizer(
    heygem_engine: Any,
    output_dir: str = "temp/video"
) -> VideoSynthesizer:
    """创建视频合成器的便捷函数

    Args:
        heygem_engine: HeyGemEngine 实例（必需）
        output_dir: 视频输出目录
    """
    return VideoSynthesizer(heygem_engine=heygem_engine, output_dir=output_dir)