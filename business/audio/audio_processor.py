"""
音频处理模块
实现 TTS 合成、音频降噪、音频处理功能
"""

import logging
import os
import platform
import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from pathlib import Path

from api.utils.async_subprocess import async_run_subprocess, async_run_ffmpeg, async_run_ffprobe

from core.models.task import ScriptSegment, Task, TaskConfig

logger = logging.getLogger(__name__)


def create_audio_speed_processor(output_dir: str = "temp/audio"):
    """导入音频语速处理器"""
    try:
        from business.audio.audio_speed_processor import AudioSpeedProcessor
        return AudioSpeedProcessor(output_dir)
    except ImportError:
        logger.warning("无法导入 AudioSpeedProcessor，语速调节功能将不可用")
        return None


@dataclass
class AudioSegmentResult:
    """音频段落结果"""
    segment_id: str
    text: str
    audio_path: Optional[str]
    duration: float
    status: str  # success, failed
    error_message: Optional[str] = None
    speaker: Optional[str] = None  # 说话人标识（left/right，双人模式）
    tone: Optional[str] = None  # 标签/情绪标识（用于双人模式按标签分组对齐）


class AudioProcessor:
    """音频处理器 - 封装 IndexTTS、GTCRN 降噪和音频处理功能"""

    def __init__(
        self,
        tts_engine: Any,
        output_dir: str = "temp/audio",
        enable_denoise: bool = True,
        denoise_strength: float = 0.7
    ):
        """
        初始化音频处理器

        Args:
            tts_engine: TTSEngine 实例（必需）
            output_dir: 音频输出目录
            enable_denoise: 是否启用 GTCRN 降噪，默认 True
            denoise_strength: 降噪强度 (0.0-1.0)，默认 0.7
        """
        if tts_engine is None:
            raise ValueError("tts_engine 参数是必需的，请提供 TTSEngine 实例")

        self.tts_engine = tts_engine
        # 确保使用绝对路径
        self.output_dir = str(Path(output_dir).resolve())
        self.enable_denoise = enable_denoise
        self.denoise_strength = denoise_strength

        self.denoiser = None
        self.speed_processor = None

        # 创建输出目录
        os.makedirs(self.output_dir, exist_ok=True)

        logger.info(f"AudioProcessor 初始化成功，输出目录: {self.output_dir}")

        self._init_denoiser()
        self._init_speed_processor()

    def _init_speed_processor(self):
        """初始化音频语速处理器"""
        try:
            self.speed_processor = create_audio_speed_processor(self.output_dir)
            if self.speed_processor:
                logger.info("音频语速处理器初始化成功")
        except Exception as e:
            logger.warning(f"音频语速处理器初始化失败：{e}")
            self.speed_processor = None

    def _init_denoiser(self):
        """初始化 GTCRN 降噪器"""
        if self.enable_denoise:
            try:
                from business.audio.gtcrn_denoiser import GTCDenoiser
                self.denoiser = GTCDenoiser(
                    model_path="tools/stream/onnx_models/gtcrn_simple.onnx",
                    denoise_strength=self.denoise_strength
                )
                logger.info("GTCRN 降噪器初始化成功")
            except Exception as e:
                logger.warning(f"GTCRN 降噪器初始化失败：{e}，将不使用降噪功能")
                self.enable_denoise = False
                self.denoiser = None

    def denoise(self, audio_path: str) -> Dict[str, Any]:
        """
        音频降噪处理

        Args:
            audio_path: 音频文件路径

        Returns:
            降噪后的音频文件路径
        """
        try:
            logger.info(f"开始音频降噪: {audio_path}")
            
            if not self.denoiser:
                logger.info("降噪器未初始化，跳过降噪处理")
                return {"output_path": audio_path}

            # 构建完整的音频文件路径
            from config.settings import settings
            full_audio_path = os.path.join(settings.UPLOAD_DIR, audio_path)
            
            if not os.path.exists(full_audio_path):
                raise FileNotFoundError(f"音频文件不存在：{audio_path}")

            # 调用降噪器进行处理
            output_path = self.denoiser.denoise(full_audio_path)
            logger.info(f"音频降噪完成: {output_path}")
            
            # 替换原音频文件
            import shutil
            shutil.move(output_path, full_audio_path)
            logger.info(f"已用增强后的音频替换原音频文件: {full_audio_path}")
            
            return {"output_path": audio_path, "message": "音频降噪完成并已替换原文件"}
        except Exception as e:
            logger.error(f"音频降噪失败: {e}")
            raise

    async def _extract_audio_from_video(self, video_path: str) -> Optional[str]:
        """
        从视频中提取音频

        Args:
            video_path: 视频文件路径

        Returns:
            提取的音频文件路径，失败则返回 None
        """
        import os

        # 生成输出音频路径
        audio_filename = os.path.splitext(os.path.basename(video_path))[0] + ".wav"
        audio_path = os.path.join(self.output_dir, audio_filename)

        # 使用 ffmpeg 提取音频
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vn",  # 不包含视频
            "-acodec", "pcm_s16le",  # 音频编码
            "-ar", "16000",  # 采样率
            "-ac", "1",  # 声道数
            audio_path
        ]

        try:
            returncode, stdout, stderr = await async_run_ffmpeg(cmd)
            if returncode == 0:
                logger.info(f"从视频中提取音频成功：{audio_path}")
                return audio_path
            else:
                _err = stderr.decode() if stderr else ""
                logger.error(f"从视频中提取音频失败：{_err}")
                return None
        except Exception as e:
            logger.error(f"从视频中提取音频时发生异常：{e}")
            return None

    def _generate_subtitle(self, task: Task) -> Optional[str]:
        """
        生成字幕文件

        Args:
            task: 任务对象

        Returns:
            生成的字幕文件路径，失败则返回 None
        """
        import os
        
        # 生成输出字幕路径
        subtitle_filename = f"{task.task_id}.srt"
        subtitle_path = os.path.join(self.output_dir, subtitle_filename)
        
        try:
            with open(subtitle_path, 'w', encoding='utf-8') as f:
                start_time = 0.0
                for i, segment in enumerate(task.segments):
                    if segment.audio_path and segment.duration:
                        # 格式化为 SRT 时间格式
                        def format_time(seconds):
                            h = int(seconds // 3600)
                            m = int((seconds % 3600) // 60)
                            s = int(seconds % 60)
                            ms = int((seconds % 1) * 1000)
                            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                        
                        end_time = start_time + segment.duration
                        
                        # 写入 SRT 格式
                        f.write(f"{i + 1}\n")
                        f.write(f"{format_time(start_time)} --> {format_time(end_time)}\n")
                        f.write(f"{segment.text}\n")
                        f.write("\n")
                        
                        start_time = end_time
            
            logger.info(f"字幕生成成功：{subtitle_path}")
            return subtitle_path
        except Exception as e:
            logger.error(f"生成字幕时发生异常：{e}")
            return None

    def _synthesize_with_engine(
        self,
        segment: ScriptSegment,
        prompt_audio: str,
        output_path: str,
        emotion_label: Optional[str] = None,
        emotion_weight: float = 0.4
    ) -> Optional[str]:
        """
        使用 TTSEngine 进行语音合成

        Args:
            segment: 文案段落
            prompt_audio: 音色参考音频路径
            output_path: 输出音频路径
            emotion_label: 情绪标签
            emotion_weight: 情感强度

        Returns:
            生成的音频路径，失败返回 None
        """
        if not self.tts_engine:
            logger.error("TTSEngine 未初始化")
            return None

        try:
            # 确保引擎已加载
            if not self.tts_engine.is_loaded:
                logger.info("TTSEngine 未加载，正在加载...")
                if not self.tts_engine.load():
                    logger.error("TTSEngine 加载失败")
                    return None

            # 调用引擎合成
            result = self.tts_engine.synthesize(
                text=segment.text,
                voice_path=prompt_audio,
                output_path=output_path,
                emotion=emotion_label,
                intensity=emotion_weight
            )

            return result

        except Exception as e:
            logger.error(f"TTSEngine 合成失败: {e}")
            return None

    def synthesize_segment(
        self,
        segment: ScriptSegment,
        prompt_audio: str,
        speed: float = 1.0,
        emo_weight: Optional[float] = None,
        speaker: Optional[str] = None,
        task_id: Optional[str] = None
    ) -> AudioSegmentResult:
        """
        合成单个段落

        Args:
            segment: 文案段落
            prompt_audio: 音色参考音频
            speed: 语速
            emo_weight: 情感权重（覆盖 segment 中的值）
            speaker: 说话人标识（left/right，双人模式）
            task_id: 任务ID，用于文件命名前缀

        Returns:
            音频结果
        """
        # 确定情感权重（从配置中获取，或使用传入值）
        emotion_weight = emo_weight if emo_weight is not None else getattr(segment, 'emotion_weight', 0.4)
        # API 支持 0.0~1.6 的强度范围
        emotion_weight = min(max(emotion_weight, 0.0), 1.6)

        # 获取情绪标签（tone 字段），直接传递给 index-tts 处理
        emotion_label = getattr(segment, 'tone', None)

        # 生成文件名：使用 task_id 前缀，格式为 {task_id}_audio_{segment_id}.wav
        if task_id:
            audio_filename = f"{task_id}_audio_{segment.segment_id}.wav"
        else:
            audio_filename = f"{segment.segment_id}.wav"
        output_path = os.path.join(self.output_dir, audio_filename)

        try:
            # 记录情绪信息
            if emotion_label:
                logger.info(f"段落 {segment.segment_id} 标签: {emotion_label}, 强度: {emotion_weight}")
            else:
                logger.info(f"段落 {segment.segment_id} 无标签，使用默认情绪")

            # 使用 TTSEngine 引擎模式合成
            logger.info(f"使用 TTSEngine 引擎模式合成段落 {segment.segment_id}")
            audio_path = self._synthesize_with_engine(
                segment=segment,
                prompt_audio=prompt_audio,
                output_path=output_path,
                emotion_label=emotion_label,
                emotion_weight=emotion_weight
            )

            if audio_path and os.path.exists(audio_path):
                duration = self._get_audio_duration(audio_path)
                segment.audio_path = audio_path
                segment.duration = duration

                return AudioSegmentResult(
                    segment_id=segment.segment_id,
                    text=segment.text,
                    audio_path=audio_path,
                    duration=duration,
                    status="success",
                    speaker=speaker,
                    tone=getattr(segment, 'tone', None)
                )

            return AudioSegmentResult(
                segment_id=segment.segment_id,
                text=segment.text,
                audio_path=None,
                duration=0.0,
                status="failed",
                error_message="TTSEngine 合成失败，未生成音频文件",
                speaker=speaker,
                tone=getattr(segment, 'tone', None)
            )

        except Exception as e:
            logger.error(f"段落 {segment.segment_id} 合成失败: {e}")
            return AudioSegmentResult(
                segment_id=segment.segment_id,
                text=segment.text,
                audio_path=None,
                duration=0.0,
                status="failed",
                error_message=str(e),
                speaker=speaker,
                tone=getattr(segment, 'tone', None)
            )

    async def synthesize_all(
        self,
        task: Task,
        config: TaskConfig,
        cancel_callback: Optional[callable] = None,
        progress_callback: Optional[callable] = None
    ) -> List[AudioSegmentResult]:
        """
        合成任务所有段落

        Args:
            task: 任务
            config: 配置
            cancel_callback: 取消回调
            progress_callback: 进度回调函数，参数为 (progress, description)

        Returns:
            音频结果列表
        """
        results = []

        # 检查是否取消
        if cancel_callback and cancel_callback():
            logger.info("任务被取消，停止音频合成")
            for segment in task.segments:
                results.append(AudioSegmentResult(
                    segment_id=segment.segment_id,
                    text=segment.text,
                    audio_path=None,
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

        # 检查 TTSEngine 是否已加载
        if not self.tts_engine or not self.tts_engine.is_loaded:
            logger.error("TTSEngine 未加载")
            for segment in task.segments:
                results.append(AudioSegmentResult(
                    segment_id=segment.segment_id,
                    text=segment.text,
                    audio_path=None,
                    duration=0.0,
                    status="failed",
                    error_message="TTSEngine 未加载"
                ))
            return results

        # 处理双人模式
        logger.info(f"开始音频合成，双人模式: {config.enable_double_mode}")
        logger.info(f"task.left_prompt_audio_path: {task.left_prompt_audio_path}")
        logger.info(f"task.right_prompt_audio_path: {task.right_prompt_audio_path}")
        logger.info(f"task.prompt_audio_path: {task.prompt_audio_path}")
        
        if config.enable_double_mode:
            # 检查左右说话人的音频路径
            left_prompt_audio = task.left_prompt_audio_path
            right_prompt_audio = task.right_prompt_audio_path
            
            # 先规范化路径
            if left_prompt_audio:
                left_prompt_audio = os.path.normpath(left_prompt_audio.replace('\\', '/'))
            if right_prompt_audio:
                right_prompt_audio = os.path.normpath(right_prompt_audio.replace('\\', '/'))
            
            logger.info(f"规范化后 left_prompt_audio: {left_prompt_audio}")
            logger.info(f"规范化后 right_prompt_audio: {right_prompt_audio}")
            
            # 检查文件是否存在
            if left_prompt_audio:
                logger.info(f"left_prompt_audio 是否存在: {os.path.exists(left_prompt_audio)}")
            if right_prompt_audio:
                logger.info(f"right_prompt_audio 是否存在: {os.path.exists(right_prompt_audio)}")
            
            if not left_prompt_audio or not right_prompt_audio:
                logger.error("双人模式需要提供左右说话人的音频路径")
                for segment in task.segments:
                    results.append(AudioSegmentResult(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        audio_path=None,
                        duration=0.0,
                        status="failed",
                        error_message="双人模式需要提供左右说话人的音频路径"
                    ))
                return results
            
            if not os.path.exists(left_prompt_audio):
                logger.error(f"左边说话人音频文件不存在: {left_prompt_audio}")
                for segment in task.segments:
                    results.append(AudioSegmentResult(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        audio_path=None,
                        duration=0.0,
                        status="failed",
                        error_message=f"左边说话人音频文件不存在: {left_prompt_audio}"
                    ))
                return results
            
            if not os.path.exists(right_prompt_audio):
                logger.error(f"右边说话人音频文件不存在: {right_prompt_audio}")
                for segment in task.segments:
                    results.append(AudioSegmentResult(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        audio_path=None,
                        duration=0.0,
                        status="failed",
                        error_message=f"右边说话人音频文件不存在: {right_prompt_audio}"
                    ))
                return results
            
            # 合成每个段落的音频
            for i, segment in enumerate(task.segments):
                if cancel_callback and cancel_callback():
                    logger.info("任务被取消，停止双人模式音频合成")
                    break
                
                if segment.audio_path and os.path.exists(segment.audio_path):
                    logger.info(f"段落 {segment.segment_id} 音频已存在，跳过合成: {segment.audio_path}")
                    duration = self._get_audio_duration(segment.audio_path)
                    results.append(AudioSegmentResult(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        audio_path=segment.audio_path,
                        duration=duration,
                        status="success",
                        speaker=segment.speaker,
                        tone=getattr(segment, 'tone', None)
                    ))
                    continue
                
                max_retries = 3
                success = False
                
                for attempt in range(max_retries):
                    try:
                        # 根据说话人选择对应的参考音频
                        prompt_audio = left_prompt_audio if segment.speaker == "left" else right_prompt_audio

                        logger.info(f"合成段落 {segment.segment_id} (说话人: {segment.speaker}, 尝试 {attempt + 1}/{max_retries})")
                        # 根据说话人选择对应的语速和情感权重
                        segment_speed = config.tts_speed
                        segment_emo_weight = config.tts_emo_weight
                        if config.enable_double_mode:
                            logger.info(f"双人模式参数: left_tts_speed={config.left_tts_speed}, left_tts_emo_weight={config.left_tts_emo_weight}, right_tts_speed={config.right_tts_speed}, right_tts_emo_weight={config.right_tts_emo_weight}")
                            if segment.speaker == "left":
                                if config.left_tts_speed is not None:
                                    segment_speed = config.left_tts_speed
                                if config.left_tts_emo_weight is not None:
                                    segment_emo_weight = config.left_tts_emo_weight
                            elif segment.speaker == "right":
                                if config.right_tts_speed is not None:
                                    segment_speed = config.right_tts_speed
                                if config.right_tts_emo_weight is not None:
                                    segment_emo_weight = config.right_tts_emo_weight
                        logger.info(f"段落 {segment.segment_id} 使用的参数: segment_speed={segment_speed}, segment_emo_weight={segment_emo_weight}")

                        result = self.synthesize_segment(
                            segment=segment,
                            prompt_audio=prompt_audio,
                            speed=segment_speed,
                            emo_weight=segment_emo_weight,
                            speaker=segment.speaker,
                            task_id=task.task_id
                        )
                        
                        if result.status == "success":
                            results.append(result)
                            success = True
                            logger.info(f"段落 {segment.segment_id} 合成成功")
                            break
                        else:
                            logger.warning(f"段落 {segment.segment_id} 合成失败: {result.error_message}")
                            if attempt < max_retries - 1:
                                logger.info(f"等待 2 秒后重试...")
                                time.sleep(2)
                    except Exception as e:
                        logger.error(f"合成段落 {segment.segment_id} 时发生异常: {e}")
                        if attempt < max_retries - 1:
                            logger.info(f"等待 2 秒后重试...")
                            time.sleep(2)
                
                if not success:
                    logger.error(f"段落 {segment.segment_id} 在 {max_retries} 次尝试后仍失败")
                    results.append(AudioSegmentResult(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        audio_path=None,
                        duration=0.0,
                        status="failed",
                        error_message=f"在 {max_retries} 次尝试后仍失败"
                    ))

                # 保存中间产物
                if len(results) > 0 and results[-1].status == "success":
                    # 触发进度回调
                    if progress_callback:
                        total_segments = len(task.segments)
                        completed = i + 1
                        tag = getattr(segment, 'tone', None) or getattr(segment, 'emotion', None) or getattr(segment, 'tag', None)
                        progress_callback(completed, total_segments, tag)

                time.sleep(0.5)  # 避免并发过高

            # 合并同一说话人的音频并添加静音
            if results:
                try:
                    logger.info("合并同一说话人的音频...")
                    await self._merge_speaker_audios(task, results, config)
                except Exception as e:
                    logger.error(f"合并音频失败: {e}")
        else:
            # 单人模式
            # 如果有参考音频且启用了降噪，先对参考音频降噪
            prompt_audio = task.prompt_audio_path
            if not prompt_audio:
                logger.info("没有提供参考音频，尝试从开场视频中提取")
                # 从开场视频中提取音频
                video_path = task.opening_video or task.source_video_path
                if video_path and os.path.exists(video_path):
                    prompt_audio = await self._extract_audio_from_video(video_path)
                    if not prompt_audio:
                        logger.error("从开场视频中提取音频失败")
                        for segment in task.segments:
                            results.append(AudioSegmentResult(
                                segment_id=segment.segment_id,
                                text=segment.text,
                                audio_path=None,
                                duration=0.0,
                                status="failed",
                                error_message="从开场视频中提取音频失败"
                            ))
                        return results
                else:
                    logger.error("没有提供参考音频，也没有可用的开场视频")
                    for segment in task.segments:
                        results.append(AudioSegmentResult(
                            segment_id=segment.segment_id,
                            text=segment.text,
                            audio_path=None,
                            duration=0.0,
                            status="failed",
                            error_message="没有提供参考音频，也没有可用的开场视频"
                        ))
                    return results
            
            if not os.path.exists(prompt_audio):
                logger.error(f"参考音频文件不存在: {prompt_audio}")
                for segment in task.segments:
                    results.append(AudioSegmentResult(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        audio_path=None,
                        duration=0.0,
                        status="failed",
                        error_message=f"参考音频文件不存在: {prompt_audio}"
                    ))
                return results

            for i, segment in enumerate(task.segments):
                if cancel_callback and cancel_callback():
                    logger.info("任务被取消，停止单人模式音频合成")
                    break
                
                if segment.audio_path and os.path.exists(segment.audio_path):
                    logger.info(f"段落 {segment.segment_id} 音频已存在，跳过合成: {segment.audio_path}")
                    duration = self._get_audio_duration(segment.audio_path)
                    results.append(AudioSegmentResult(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        audio_path=segment.audio_path,
                        duration=duration,
                        status="success",
                        tone=getattr(segment, 'tone', None)
                    ))
                    continue
                
                max_retries = 3
                success = False
                
                for attempt in range(max_retries):
                    try:
                        logger.info(f"合成段落 {segment.segment_id} (尝试 {attempt + 1}/{max_retries})")
                        result = self.synthesize_segment(
                            segment=segment,
                            prompt_audio=prompt_audio,
                            speed=config.tts_speed,
                            emo_weight=config.tts_emo_weight,
                            task_id=task.task_id
                        )
                        
                        if result.status == "success":
                            results.append(result)
                            success = True
                            logger.info(f"段落 {segment.segment_id} 合成成功")
                            break
                        else:
                            logger.warning(f"段落 {segment.segment_id} 合成失败: {result.error_message}")
                            if attempt < max_retries - 1:
                                logger.info(f"等待 2 秒后重试...")
                                time.sleep(2)
                    except Exception as e:
                        logger.error(f"合成段落 {segment.segment_id} 时发生异常: {e}")
                        if attempt < max_retries - 1:
                            logger.info(f"等待 2 秒后重试...")
                            time.sleep(2)
                
                if not success:
                    logger.error(f"段落 {segment.segment_id} 在 {max_retries} 次尝试后仍失败")
                    results.append(AudioSegmentResult(
                        segment_id=segment.segment_id,
                        text=segment.text,
                        audio_path=None,
                        duration=0.0,
                        status="failed",
                        error_message=f"在 {max_retries} 次尝试后仍失败"
                    ))

                # 保存中间产物
                if len(results) > 0 and results[-1].status == "success":
                    # 触发进度回调
                    if progress_callback:
                        total_segments = len(task.segments)
                        completed = i + 1
                        tag = getattr(segment, 'tone', None) or getattr(segment, 'emotion', None) or getattr(segment, 'tag', None)
                        progress_callback(completed, total_segments, tag)

                time.sleep(0.5)  # 避免并发过高

        return results

    async def _merge_speaker_audios(self, task: Task, results: List[AudioSegmentResult], config: TaskConfig = None):
        """
        合并同一说话人的音频并添加静音（按标签分组对齐）

        根据需求实现按标签分组的时长对齐逻辑：
        - 每个标签下的左右说话人音频分别对齐
        - 例如"开场"标签：左边11秒 + 右边9秒 → 各对齐为20秒
        - 例如"开心"标签：左边8秒 + 右边7秒 → 各对齐为15秒

        转场效果缓冲：
        - 如果启用了转场效果，在音频前后各添加 transition_duration/2 秒静音
        - 这样转场效果不会"吞掉"音频内容

        最终将所有标签组的对齐后音频按顺序合并

        Args:
            task: 任务
            results: 音频结果列表
            config: 任务配置（用于获取转场时长）
        """
        import os
        from collections import defaultdict
        
        if not results:
            logger.warning("没有音频结果需要合并")
            return
        
        # 双人模式：检查是否已有 tone_audio_paths（从检查点恢复）
        if hasattr(task, 'tone_audio_paths') and task.tone_audio_paths:
            logger.info(f"双人模式：检测到已存在的 tone_audio_paths，跳过音频合并")
            logger.info(f"已存在的标签: {list(task.tone_audio_paths.keys())}")
            # 验证音频文件是否存在
            for tone, paths in task.tone_audio_paths.items():
                left_path = paths.get('left')
                right_path = paths.get('right')
                if left_path and os.path.exists(left_path):
                    logger.info(f"标签 '{tone}' 左音频已存在: {left_path}")
                if right_path and os.path.exists(right_path):
                    logger.info(f"标签 '{tone}' 右音频已存在: {right_path}")
            return
        
        try:
            # 按标签分组，每个标签下再按说话人分组
            tone_groups = defaultdict(lambda: {"left": [], "right": []})
            
            for result in results:
                if result.status == "success" and result.audio_path:
                    speaker = getattr(result, 'speaker', None)
                    tone = getattr(result, 'tone', 'default')
                    if speaker in ["left", "right"]:
                        tone_groups[tone][speaker].append(result)
            
            logger.info(f"按标签分组完成，共 {len(tone_groups)} 个标签组")
            
            # 导入标签匹配器判断场景标签
            from business.video.tag_matcher import get_tag_matcher
            tag_matcher = get_tag_matcher()
            
            # 存储每个标签组的音频路径（按标签分组，用于双人模式视频合成）
            tone_audio_paths = {}
            
            # 存储每个标签组对齐后的音频路径（用于最终合并）
            left_aligned_segments = []
            right_aligned_segments = []
            
            # 按原始顺序处理每个标签组
            processed_tones = set()
            for result in results:
                if result.status == "success" and result.audio_path:
                    tone = getattr(result, 'tone', 'default')
                    if tone in processed_tones:
                        continue
                    processed_tones.add(tone)
                    
                    try:
                        left_segments = tone_groups[tone]["left"]
                        right_segments = tone_groups[tone]["right"]
                        
                        if not left_segments and not right_segments:
                            continue
                        
                        # 计算该标签下每个说话人的总时长
                        left_duration = sum(getattr(r, 'duration', 0.0) for r in left_segments)
                        right_duration = sum(getattr(r, 'duration', 0.0) for r in right_segments)
                        
                        logger.info(f"标签 '{tone}': 左边 {left_duration:.2f}秒, 右边 {right_duration:.2f}秒")
                        
                        # 为该标签组创建对齐后的音频
                        left_aligned_path = None
                        right_aligned_path = None
                        
                        # 判断是否是场景标签
                        is_scene_tag = tag_matcher.is_scene_tag(tone)
                        
                        if is_scene_tag:
                            # 场景标签：不进行对齐，直接使用原始音频
                            logger.info(f"标签 '{tone}' 是场景标签，跳过音频对齐")
                            
                            # 合并左边说话人音频
                            if left_segments:
                                left_merged_for_scene = os.path.join(self.output_dir, f"left_{tone}_{task.task_id}.wav")
                                left_audio_paths = [seg.audio_path for seg in left_segments if seg.audio_path]
                                if left_audio_paths:
                                    if await self._concat_audio_files(left_audio_paths, left_merged_for_scene):
                                        left_aligned_path = left_merged_for_scene
                            
                            # 合并右边说话人音频
                            if right_segments:
                                right_merged_for_scene = os.path.join(self.output_dir, f"right_{tone}_{task.task_id}.wav")
                                right_audio_paths = [seg.audio_path for seg in right_segments if seg.audio_path]
                                if right_audio_paths:
                                    if await self._concat_audio_files(right_audio_paths, right_merged_for_scene):
                                        right_aligned_path = right_merged_for_scene
                        else:
                            # 非场景标签：进行音频对齐
                            # 计算转场缓冲时长：如果启用了转场效果，前后各添加 transition_duration/2 秒
                            transition_buffer = 0.0
                            if config and getattr(config, 'enable_transition', False):
                                transition_duration = getattr(config, 'transition_duration', 0.5)
                                transition_buffer = transition_duration / 2
                                logger.info(f"标签 '{tone}' 启用转场效果，缓冲时长: {transition_buffer:.2f}秒")

                            if left_segments:
                                left_aligned = await self._create_aligned_audio_for_tone(
                                    segments=left_segments,
                                    silence_duration=right_duration,
                                    speaker="left",
                                    tone=tone,
                                    task_id=task.task_id,
                                    prepend_silence=False,
                                    transition_buffer=transition_buffer
                                )
                                if left_aligned:
                                    left_aligned_segments.append(left_aligned)
                                    left_aligned_path = left_aligned
                                    logger.info(f"标签 '{tone}' 左边音频对齐完成: {left_aligned}")

                            if right_segments:
                                right_aligned = await self._create_aligned_audio_for_tone(
                                    segments=right_segments,
                                    silence_duration=left_duration,
                                    speaker="right",
                                    tone=tone,
                                    task_id=task.task_id,
                                    prepend_silence=True,
                                    transition_buffer=transition_buffer
                                )
                                if right_aligned:
                                    right_aligned_segments.append(right_aligned)
                                    right_aligned_path = right_aligned
                                    logger.info(f"标签 '{tone}' 右边音频对齐完成: {right_aligned}")
                        
                        # 保存该标签组的音频路径
                        if left_aligned_path or right_aligned_path:
                            tone_audio_paths[tone] = {
                                "left": left_aligned_path,
                                "right": right_aligned_path
                            }
                    except Exception as e:
                        logger.error(f"处理标签 '{tone}' 时发生异常：{e}")
                        # 即使当前标签处理失败，也继续处理后续标签
                        continue
        
            # 保存按标签分组的音频路径到 task（用于双人模式视频合成）
            task.tone_audio_paths = tone_audio_paths
            logger.info(f"按标签分组的音频路径已保存，共 {len(tone_audio_paths)} 个标签")
            
            # 注释：不再需要合并所有标签组的对齐音频
            # if left_aligned_segments:
            #     left_merged_path = os.path.join(self.output_dir, f"left_merged_{task.task_id}.wav")
            #     if self._concat_audio_files(left_aligned_segments, left_merged_path):
            #         task.left_merged_audio_path = left_merged_path
            #         logger.info(f"左边说话人所有标签音频合并完成: {left_merged_path}")
            # 
            # if right_aligned_segments:
            #     right_merged_path = os.path.join(self.output_dir, f"right_merged_{task.task_id}.wav")
            #     if self._concat_audio_files(right_aligned_segments, right_merged_path):
            #         task.right_merged_audio_path = right_merged_path
            #         logger.info(f"右边说话人所有标签音频合并完成: {right_merged_path}")
        except Exception as e:
            logger.error(f"音频合并流程发生异常：{e}")
            # 确保至少设置一个空的 tone_audio_paths
            if not hasattr(task, 'tone_audio_paths'):
                task.tone_audio_paths = {}
    
    async def _create_aligned_audio_for_tone(
        self,
        segments: List[AudioSegmentResult],
        silence_duration: float,
        speaker: str,
        tone: str,
        task_id: str,
        prepend_silence: bool = False,
        transition_buffer: float = 0.0
    ) -> Optional[str]:
        """
        为单个标签组创建时长对齐的音频文件

        Args:
            segments: 该标签下该说话人的音频段落列表
            silence_duration: 需要添加的静音时长（秒）
            speaker: 说话人标识（left/right）
            tone: 标签名称
            task_id: 任务ID
            prepend_silence: 是否在前面添加静音
            transition_buffer: 转场缓冲时长（秒），前后各添加此时长静音

        Returns:
            对齐后的音频文件路径，失败返回 None
        """
        
        if not segments:
            return None
        
        # 计算该标签下该说话人的音频总时长
        audio_total_duration = sum(getattr(s, 'duration', 0.0) for s in segments)

        # 计算转场缓冲时长（前后各添加 transition_buffer 秒）
        buffer_duration = transition_buffer

        logger.info(f"标签 '{tone}' {speaker} 说话人: 音频 {audio_total_duration:.2f}秒, 静音 {silence_duration:.2f}秒, 转场缓冲 {buffer_duration:.2f}秒")

        # 生成对齐后的音频文件名
        safe_tone = tone.replace("/", "_").replace("\\", "_") if tone else "default"
        output_filename = f"{speaker}_{safe_tone}_{task_id}.wav"
        output_path = os.path.join(self.output_dir, output_filename)

        try:
            # 步骤1：合并该标签下该说话人的所有音频段落
            temp_concat_file = os.path.join(self.output_dir, f"temp_concat_{speaker}_{safe_tone}_{task_id}.txt")

            with open(temp_concat_file, 'w', encoding='utf-8') as f:
                for seg in segments:
                    audio_path = seg.audio_path
                    # 转换为绝对路径
                    if not os.path.isabs(audio_path):
                        audio_path = os.path.abspath(audio_path)
                    if os.path.exists(audio_path):
                        # 安全检查：验证路径不包含危险字符
                        # ffmpeg concat 格式要求路径用单引号包裹，内部单引号需要转义
                        # 但更安全的方式是检查路径是否包含可能导致问题的字符
                        if "'" in audio_path:
                            # 使用 ffmpeg 的 -safe 0 选项配合正确的转义
                            # 单引号转义：' 替换为 '\''
                            escaped_path = audio_path.replace("'", "'\\''")
                        else:
                            escaped_path = audio_path
                        f.write(f"file '{escaped_path}'\n")

            temp_merged_path = os.path.join(self.output_dir, f"temp_merged_{speaker}_{safe_tone}_{task_id}.wav")

            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", temp_concat_file,
                "-c:a", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                temp_merged_path
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if os.path.exists(temp_concat_file):
                os.remove(temp_concat_file)

            if returncode != 0:
                _err = stderr.decode() if stderr else ""
                logger.error(f"合并标签 '{tone}' {speaker} 音频段落失败: {_err}")
                return None

            # 步骤2：添加静音（包括对齐静音和转场缓冲静音）
            # 新逻辑：
            # - 左边说话人：转场缓冲 + 音频 + 对齐静音 + 转场缓冲
            # - 右边说话人：转场缓冲 + 对齐静音 + 音频 + 转场缓冲

            # 计算各部分时长
            buffer_ms = int(buffer_duration * 1000)
            silence_ms = int(silence_duration * 1000)

            # 构建滤镜链
            # 使用 adelay 在前面添加静音，使用 apad 在后面添加静音
            # 注意：adelay 只是延迟起始时间，apad=whole_dur 设置的是最终总时长
            # 所以 whole_dur = 前置静音 + 音频时长 + 后置静音
            filter_parts = []

            if prepend_silence:
                # 右边说话人：前面需要转场缓冲 + 对齐静音，后面需要转场缓冲
                # 总前置静音 = buffer + silence
                total_prepend_ms = buffer_ms + silence_ms
                if total_prepend_ms > 0:
                    filter_parts.append(f"adelay={total_prepend_ms}|{total_prepend_ms}")

                # 最终总时长 = 前置静音 + 音频时长 + 后置转场缓冲
                # whole_dur 需要包含前置静音时长，因为 adelay 只是延迟，apad 需要填充到总时长
                total_duration = (total_prepend_ms / 1000) + audio_total_duration + buffer_duration
                filter_parts.append(f"apad=whole_dur={total_duration}")
            else:
                # 左边说话人：前面需要转场缓冲，后面需要对齐静音 + 转场缓冲
                # 前面添加转场缓冲
                if buffer_ms > 0:
                    filter_parts.append(f"adelay={buffer_ms}|{buffer_ms}")

                # 最终总时长 = 前置转场缓冲 + 音频时长 + 对齐静音 + 后置转场缓冲
                total_duration = buffer_duration + audio_total_duration + silence_duration + buffer_duration
                filter_parts.append(f"apad=whole_dur={total_duration}")

            if filter_parts:
                filter_complex = f"[0:a]{','.join(filter_parts)}[a]"
                cmd = [
                    "ffmpeg",
                    "-i", temp_merged_path,
                    "-filter_complex", filter_complex,
                    "-map", "[a]",
                    "-c:a", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    output_path
                ]
            else:
                # 不需要添加静音，直接重命名
                if os.path.exists(temp_merged_path):
                    os.rename(temp_merged_path, output_path)
                    return output_path

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if os.path.exists(temp_merged_path):
                os.remove(temp_merged_path)

            if returncode != 0:
                _err = stderr.decode() if stderr else ""
                logger.error(f"添加静音失败: {_err}")
                return None

            if os.path.exists(output_path):
                return output_path

            return None
            
        except Exception as e:
            logger.error(f"创建对齐音频时发生异常: {e}")
            return None
    
    async def _generate_silence_file(self, duration: float) -> Optional[str]:
        """
        生成静音音频文件

        Args:
            duration: 静音时长（秒）

        Returns:
            静音文件路径，失败返回 None
        """
        if duration <= 0:
            return None

        try:
            import tempfile
    
            # 创建临时静音文件
            silence_path = os.path.join(self.output_dir, f"silence_{uuid.uuid4().hex[:8]}.wav")

            cmd = [
                "ffmpeg",
                "-f", "lavfi",
                "-i", f"anullsrc=r=16000:cl=mono",
                "-t", str(duration),
                "-c:a", "pcm_s16le",
                silence_path
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)
            if returncode == 0 and os.path.exists(silence_path):
                # 追踪生成的静音文件，供后续清理
                if not hasattr(self, '_silence_files'):
                    self._silence_files = []
                self._silence_files.append(silence_path)
                return silence_path
            else:
                _err = stderr.decode() if stderr else ""
                logger.error(f"生成静音文件失败: {_err}")
                return None

        except Exception as e:
            logger.error(f"生成静音文件时发生异常: {e}")
            return None
    
    async def _concat_audio_files(self, audio_files: List[str], output_path: str) -> bool:
        """
        合并多个音频文件
        
        Args:
            audio_files: 音频文件路径列表
            output_path: 输出文件路径
            
        Returns:
            是否成功
        """
        
        if not audio_files:
            logger.warning("没有音频文件需要合并")
            return False
        
        try:
            # 方法1：使用 concat 协议
            concat_file = os.path.join(self.output_dir, f"concat_{uuid.uuid4().hex[:8]}.txt")
            
            with open(concat_file, 'w', encoding='utf-8') as f:
                for audio_path in audio_files:
                    # 转换为绝对路径
                    if not os.path.isabs(audio_path):
                        audio_path = os.path.abspath(audio_path)
                    if os.path.exists(audio_path):
                        # 安全处理路径中的单引号
                        if "'" in audio_path:
                            escaped_path = audio_path.replace("'", "'\\''")
                        else:
                            escaped_path = audio_path
                        f.write(f"file '{escaped_path}'\n")
            
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
                _err = stderr.decode() if stderr else ""
                logger.error(f"合并音频失败: {_err}")
                return False
                
        except Exception as e:
            logger.error(f"合并音频时发生异常: {e}")
            return False

    async def _create_aligned_audio(
        self,
        segments: List[AudioSegmentResult],
        silence_duration: float,
        speaker: str,
        task_id: str,
        prepend_silence: bool = False
    ) -> Optional[str]:
        """
        创建时长对齐的音频文件
        
        Args:
            segments: 音频段落列表
            silence_duration: 需要添加的静音时长（秒）
            speaker: 说话人标识（left/right）
            task_id: 任务ID
            prepend_silence: 是否在前面添加静音（True=前面静音后面声音，False=前面声音后面静音）
            
        Returns:
            合并后的音频文件路径，失败返回 None
        """
        import os
        
        if not segments:
            logger.error(f"{speaker} 说话人没有音频段落")
            return None
        
        # 计算所有音频的总时长
        audio_total_duration = sum(getattr(s, 'duration', 0.0) for s in segments)
        
        logger.info(f"{speaker} 说话人音频总时长: {audio_total_duration:.2f}秒, 静音时长: {silence_duration:.2f}秒")
        
        # 生成合并后的音频文件名
        output_filename = f"{speaker}_aligned_{task_id}.wav"
        output_path = os.path.join(self.output_dir, output_filename)
        
        try:
            # 构建 ffmpeg 命令
            # 方法：使用 amix 或 adelay 滤镜
            # 这里使用更简单的方法：先生成音频列表，然后用 adelay 添加静音
            
            # 步骤1：合并所有音频段落
            temp_concat_file = os.path.join(self.output_dir, f"temp_concat_{speaker}_{task_id}.txt")
            
            with open(temp_concat_file, 'w', encoding='utf-8') as f:
                for seg in segments:
                    if seg.audio_path and os.path.exists(seg.audio_path):
                        audio_path = seg.audio_path
                        # 安全处理路径中的单引号
                        if "'" in audio_path:
                            escaped_path = audio_path.replace("'", "'\\''")
                        else:
                            escaped_path = audio_path
                        f.write(f"file '{escaped_path}'\n")
            
            # 临时合并文件
            temp_merged_path = os.path.join(self.output_dir, f"temp_merged_{speaker}_{task_id}.wav")
            
            # 合并所有音频段落
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", temp_concat_file,
                "-c:a", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                temp_merged_path
            ]
            
            returncode, stdout, stderr = await async_run_ffmpeg(cmd)
            
            if returncode != 0:
                _err = stderr.decode() if stderr else ""
                logger.error(f"合并音频段落失败: {_err}")
                if os.path.exists(temp_concat_file):
                    os.remove(temp_concat_file)
                return None
            
            # 清理临时文件
            if os.path.exists(temp_concat_file):
                os.remove(temp_concat_file)
            
            # 步骤2：添加静音
            if silence_duration <= 0:
                # 如果不需要添加静音，直接返回合并后的音频
                if os.path.exists(temp_merged_path):
                    os.rename(temp_merged_path, output_path)
                    return output_path
            
            # 使用 adelay 滤镜添加静音
            # 对于左边说话人（prepend_silence=False）：前面声音，后面静音
            # 对于右边说话人（prepend_silence=True）：前面静音，后面声音
            
            silence_ms = int(silence_duration * 1000)
            
            if prepend_silence:
                # 前面添加静音，后面保持声音
                filter_complex = f"[0:a]adelay={silence_ms}|{silence_ms}[a]"
            else:
                # 前面保持声音，后面添加静音
                # 需要先获取音频时长，然后在后面添加静音
                # 使用 apad 滤镜在音频末尾添加静音
                filter_complex = f"[0:a]apad=whole_dur={audio_total_duration + silence_duration}[a]"
            
            cmd = [
                "ffmpeg",
                "-i", temp_merged_path,
                "-af", filter_complex,
                "-c:a", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                output_path
            ]
            
            returncode, stdout, stderr = await async_run_ffmpeg(cmd)
            
            # 清理临时文件
            if os.path.exists(temp_merged_path):
                os.remove(temp_merged_path)
            
            if returncode == 0 and os.path.exists(output_path):
                logger.info(f"{speaker} 说话人时长对齐音频生成成功: {output_path}")
                return output_path
            else:
                _err = stderr.decode() if stderr else ""
                logger.error(f"{speaker} 说话人时长对齐音频生成失败: {_err}")
                if os.path.exists(output_path):
                    os.remove(output_path)
                return None
                
        except Exception as e:
            logger.error(f"{speaker} 说话人时长对齐音频生成时发生异常: {e}")
            return None

    def _get_latest_audio(self, max_retries: int = 5, retry_delay: float = 2.0) -> Optional[str]:
        """
        获取最新生成的音频（带重试机制）
        
        Args:
            max_retries: 最大重试次数，默认 5 次
            retry_delay: 重试间隔（秒），默认 2.0 秒
            
        Returns:
            音频文件路径，如果获取失败则返回 None
        """
        for attempt in range(1, max_retries + 1):
            try:
                tasks, latest_player, latest_download = self.tts_client.refresh_outputs()
                
                # 尝试从 latest_download 中提取音频路径
                if latest_download:
                    audio_path = self._extract_audio_path(latest_download)
                    if audio_path:
                        logger.info(f"在第 {attempt} 次尝试时成功获取音频")
                        return audio_path
                
                # 尝试从 latest_player 中提取音频路径
                if latest_player:
                    audio_path = self._extract_audio_path(latest_player)
                    if audio_path:
                        logger.info(f"在第 {attempt} 次尝试时成功获取音频")
                        return audio_path
                
                # 尝试从任务列表中提取最新音频
                if tasks:
                    # 假设 tasks 是字典，尝试获取最新任务
                    for task_id, task_info in tasks.items():
                        if isinstance(task_info, dict):
                            output = task_info.get("output", {})
                            audio_path = self._extract_audio_path(output.get("audio", ""))
                            if audio_path:
                                logger.info(f"在第 {attempt} 次尝试时成功获取音频")
                                return audio_path
                
                # 如果没有获取到音频，继续重试
                if attempt < max_retries:
                    logger.warning(f"音频尚未生成完成（尝试 {attempt}/{max_retries}）")
                    logger.info(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                    
            except Exception as e:
                logger.error(f"第 {attempt} 次尝试时获取音频失败：{e}")
                if attempt < max_retries:
                    logger.info(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
        
        logger.error("尝试多次后仍未获取到音频")
        return None
    
    def _extract_audio_path(self, latest_audio) -> Optional[str]:
        """
        从不同格式的响应中提取音频路径
        
        Args:
            latest_audio: 从 TTS 服务返回的音频信息
            
        Returns:
            音频文件路径，如果无法提取则返回 None
        """
        if isinstance(latest_audio, dict):
            # 处理 {'value': None, '__type__': 'update'} 这种情况
            if latest_audio.get("__type__") == "update":
                value = latest_audio.get("value")
                if value is None:
                    return None
                elif isinstance(value, str):
                    return value
                elif isinstance(value, dict):
                    return self._get_path_from_dict(value)
            # 尝试直接获取文件路径
            return self._get_path_from_dict(latest_audio)
        elif isinstance(latest_audio, str):
            return latest_audio
        else:
            logger.warning(f"未知的音频路径类型：{type(latest_audio)}")
            return None
    
    def _get_path_from_dict(self, data: dict) -> Optional[str]:
        """
        从字典中提取路径信息
        
        Args:
            data: 包含路径信息的字典
            
        Returns:
            路径字符串，如果无法提取则返回 None
        """
        if "path" in data:
            return data["path"]
        elif "name" in data:
            return data["name"]
        else:
            logger.warning(f"无法从字典中提取音频路径：{data}")
            return None






    def _save_audio(self, source_path: str, filename: str) -> str:
        """保存音频到输出目录"""
        import shutil

        output_path = os.path.join(self.output_dir, filename)
        os.makedirs(self.output_dir, exist_ok=True)

        try:
            # 检查 source_path 是否为字符串
            if not isinstance(source_path, str):
                logger.error(f"音频源路径类型错误: {type(source_path)}, 值: {source_path}")
                # 如果是字典，尝试提取路径
                if isinstance(source_path, dict):
                    if "path" in source_path:
                        source_path = source_path["path"]
                    elif "name" in source_path:
                        source_path = source_path["name"]
                    else:
                        logger.error(f"无法从字典中提取路径: {source_path}")
                        return output_path
                else:
                    return output_path
            
            # 尝试找到源文件
            source_file = source_path
            if not os.path.exists(source_file):
                # 尝试不同的可能路径
                possible_paths = [
                    source_path,
                    os.path.join("outputs", source_path),  # IndexTTS outputs 目录
                    os.path.join("..", source_path),
                    os.path.join(os.getcwd(), source_path),
                    os.path.join(os.getcwd(), "outputs", source_path),
                ]
                for p in possible_paths:
                    if os.path.exists(p):
                        source_file = p
                        logger.debug(f"找到源音频文件: {source_file}")
                        break
            
            if os.path.exists(source_file):
                shutil.copy2(source_file, output_path)
                logger.info(f"音频已保存: {output_path}")
            else:
                logger.error(f"音频源文件不存在: {source_path}, 已尝试: {possible_paths}")
        except Exception as e:
            logger.error(f"保存音频失败: {e}")

        return output_path

    def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长"""
        try:
            import wave
            with wave.open(audio_path, 'r') as w:
                frames = w.getnframes()
                rate = w.getframerate()
                return frames / rate if rate > 0 else 0.0
        except wave.Error as e:
            logger.error(f"音频文件格式错误: {e}")
            return 0.0
        except Exception as e:
            logger.error(f"获取音频时长时发生异常: {e}")
            raise

    async def concatenate_audio(
        self,
        audio_paths: List[str],
        output_path: str
    ) -> bool:
        """
        合并多个音频文件

        Args:
            audio_paths: 音频路径列表
            output_path: 输出路径

        Returns:
            是否成功
        """
        if not audio_paths:
            return False

        try:
            # 使用 ffmpeg 合并
    
            # 创建临时文件列表
            list_file = os.path.join(self.output_dir, "concat_list.txt")
            with open(list_file, 'w', encoding='utf-8') as f:
                for path in audio_paths:
                    f.write(f"file '{path}'\n")

            cmd = [
                "ffmpeg", "-f", "concat", "-safe", "0",
                "-i", list_file, "-c", "copy", output_path
            ]

            await async_run_ffmpeg(cmd, check=True)
            os.remove(list_file)

            logger.info(f"音频合并成功: {output_path}")
            return True

        except Exception as e:
            logger.error(f"音频合并失败: {e}")
            return False

    async def add_fade(
        self,
        audio_path: str,
        fade_in: float = 0.02,
        fade_out: float = 0.02
    ) -> str:
        """
        添加淡入淡出

        Args:
            audio_path: 音频路径
            fade_in: 淡入时长（秒）
            fade_out: 淡出时长（秒）

        Returns:
            处理后的音频路径
        """

        output_path = audio_path.replace(".wav", "_fade.wav")

        cmd = [
            "ffmpeg", "-i", audio_path,
            "-af", f"afade=t=in:st=0:d={fade_in},afade=t=out:st=-{fade_out}:d={fade_out}",
            output_path
        ]

        try:
            await async_run_ffmpeg(cmd, check=True)
            return output_path
        except Exception as e:
            logger.error(f"添加淡入淡出失败: {e}")
            return audio_path

    def close(self):
        """关闭处理器，清理临时文件"""
        # 清理静音文件
        if hasattr(self, '_silence_files') and self._silence_files:
            for file_path in self._silence_files:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.debug(f"已清理静音文件: {file_path}")
                except Exception as e:
                    logger.warning(f"清理静音文件失败: {e}")
            self._silence_files = []
            logger.info(f"AudioProcessor 已清理 {len(self._silence_files)} 个静音文件")

        # 引擎模式下无需关闭客户端
        logger.info("AudioProcessor 已关闭")


def create_audio_processor(
    tts_engine: Any,
    output_dir: str = "temp/audio",
    enable_denoise: bool = True,
    denoise_strength: float = 0.7
) -> AudioProcessor:
    """创建音频处理器的便捷函数

    Args:
        tts_engine: TTSEngine 实例（必需）
        output_dir: 音频输出目录
        enable_denoise: 是否启用降噪
        denoise_strength: 降噪强度
    """
    return AudioProcessor(
        tts_engine=tts_engine,
        output_dir=output_dir,
        enable_denoise=enable_denoise,
        denoise_strength=denoise_strength
    )