"""
后期处理模块
实现字幕生成、BGM 混音、封面生成等功能
"""

import logging
import os
import platform
import random
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path as _Path

from api.utils.async_subprocess import async_run_subprocess, async_run_ffmpeg, async_run_ffprobe

from core.models.task import Task, TaskConfig, SubtitlePosition
from core.utils.video_utils import calculate_aspect_ratio, calculate_aspect_ratio_error
from business.audio.audio_mixer import AudioMixer
from business.postprocess.transition_effects import (
    ALL_TRANSITION_EFFECTS,
    is_valid_transition_effect
)

# ffmpeg/ffprobe 绝对路径（跨平台兼容）
_PROJECT_ROOT = _Path(__file__).parent.parent.parent
_FFMPEG_EXE = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
_FFPROBE_EXE = "ffprobe.exe" if platform.system() == "Windows" else "ffprobe"
FFMPEG_PATH = str(_PROJECT_ROOT / "runtime" / "ffmpeg" / "bin" / _FFMPEG_EXE)
FFPROBE_PATH = str(_PROJECT_ROOT / "runtime" / "ffmpeg" / "bin" / _FFPROBE_EXE)

logger = logging.getLogger(__name__)


@dataclass
class PostProcessResult:
    """后期处理结果"""
    output_path: Optional[str]
    subtitle_path: Optional[str] = None
    cover_path: Optional[str] = None
    status: str = "success"
    error_message: Optional[str] = None
    intermediate_files: List[str] = field(default_factory=list)


class PostProcessor:
    """后期处理器"""

    CONFIG_DIR = "backend/config"

    def __init__(
        self,
        intermediate_dir: str = "backend/output",
        output_dir: str = "output",
        **kwargs
    ):
        """
        初始化后期处理器

        Args:
            intermediate_dir: 中间处理目录（字幕、BGM、合并等中间文件存放处）
            output_dir: 最终输出目录（只有完成全部后期处理的视频才存放此处）
        """
        self.intermediate_dir = intermediate_dir
        self.output_dir = output_dir
        self.audio_mixer = AudioMixer(temp_dir=os.path.join(intermediate_dir, "temp"))
        self.cover_prompt_template = self._load_cover_prompt_template()

        os.makedirs(intermediate_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

    def _load_cover_prompt_template(self) -> str:
        """从系统设置加载封面提示词模版"""
        default_template = "根据文案{summary}生成视频封面，风格简洁，突出主题"
        try:
            # 使用项目根目录加载配置文件
            # post_processor.py 位于 business/postprocess/, 需要向上回溯三层到项目根目录
            # business/postprocess -> business -> 项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(project_root, 'backend', 'config', 'prompt_templates.yaml')
            
            if os.path.exists(config_path):
                import yaml
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data and 'cover_prompt_template' in data:
                        template = data['cover_prompt_template']
                        logger.info(f'封面提示词模版加载成功：{config_path}')
                        return template
            else:
                logger.warning(f'配置文件不存在：{config_path}')
        except Exception as e:
            logger.warning(f'加载封面提示词模版失败：{e}')
        return default_template

    async def process(
        self,
        task: Task,
        config: TaskConfig,
        progress_callback=None
    ) -> PostProcessResult:
        """
        执行后期处理

        Args:
            task: 任务
            config: 配置
            progress_callback: 进度回调函数 (progress: float, stage: str)

        Returns:
            处理结果
        """
        try:
            # 1. 检查是否有需要画外音叠加的片段（单人模式新流程）
            # 流程：生成音频→生成视频→视频标准化→叠加头像
            pip_segments = []
            if not config.enable_double_mode and hasattr(task, 'segments'):
                for seg in task.segments:
                    if getattr(seg, 'need_pip_overlay', False):
                        pip_segments.append(seg)
                        logger.info(f"发现待叠加画外音片段: {seg.segment_id}")

            # 2. 合并视频片段
            video_paths = []
            
            # 处理双人模式
            if config.enable_double_mode:
                # 检查是否有需要画外音叠加的双人模式
                has_pip = task.scene_pip_left_video or task.scene_pip_right_video

                if has_pip:
                    # 双人模式画外音：对每个 tone 的场景视频执行 PIP 叠加
                    # 修复：按原始 tone 顺序构建 video_paths，场景标签用叠加后的视频，
                    # 非场景标签用 completed_tone_videos 中的原始视频，避免重复包含
                    logger.info("双人模式：检测到画外音，启用标准化后叠加流程")
                    pip_speaker_videos = task.pip_speaker_videos
                    # 叠加结果映射：tone -> 叠加后路径
                    pip_overlay_map = {}

                    if pip_speaker_videos:
                        # 遍历所有 tone，对每个 tone 的场景视频执行 PIP 叠加
                        for tone, tone_data in pip_speaker_videos.items():
                            scene_video_path = tone_data.get('scene')
                            if not scene_video_path or not os.path.exists(scene_video_path):
                                logger.warning(f"双人模式 PIP：tone '{tone}' 场景视频不存在，跳过")
                                continue
                            processed_path = await self._process_double_pip(
                                task,
                                scene_video_path,
                                config
                            )
                            if processed_path:
                                pip_overlay_map[tone] = processed_path
                                logger.info(f"双人模式 PIP：tone '{tone}' 叠加完成")
                            else:
                                logger.warning(f"双人模式 PIP：tone '{tone}' 叠加失败")

                    # 按原始 tone 顺序构建 video_paths
                    completed_tone_videos = getattr(task, 'completed_tone_videos', {})
                    if completed_tone_videos:
                        for tone, tone_path in completed_tone_videos.items():
                            if tone in pip_overlay_map:
                                # 场景标签：使用叠加后的视频
                                video_paths.append(pip_overlay_map[tone])
                                logger.info(f"双人模式 PIP：tone '{tone}' 使用叠加后视频: {pip_overlay_map[tone]}")
                            elif tone_path and os.path.exists(tone_path):
                                # 非场景标签：使用原始视频
                                video_paths.append(tone_path)
                                logger.info(f"双人模式：tone '{tone}' 使用原始视频: {tone_path}")
                    elif pip_overlay_map:
                        # 没有 completed_tone_videos，直接用叠加结果
                        video_paths.extend(pip_overlay_map.values())

                    if not video_paths:
                        # 回退：尝试使用 final_video_path
                        if hasattr(task, 'final_video_path') and task.final_video_path:
                            video_paths.append(task.final_video_path)
                            logger.warning("双人模式 PIP：无法按 tone 顺序构建，回退使用 final_video_path")
                else:
                    # 无画外音的双人模式：使用 final_video_path
                    if hasattr(task, 'final_video_path') and task.final_video_path:
                        video_paths.append(task.final_video_path)
                        logger.info(f"双人模式：使用已合并的视频: {task.final_video_path}")
                    # 检查是否有左右说话人的视频（备选方案）
                    elif hasattr(task, 'left_video_path') and hasattr(task, 'right_video_path'):
                        if task.left_video_path:
                            video_paths.append(task.left_video_path)
                        if task.right_video_path:
                            video_paths.append(task.right_video_path)
            else:
                # 单人模式：收集片段并处理画外音叠加
                # 对于需要 PIP 叠加的片段，先标准化再叠加
                processed_paths = await self._process_pip_segments(
                    task.segments,
                    config
                )
                # 收集处理后的路径（processed_paths 键是 segment_id）
                video_paths = []
                for seg in task.segments:
                    if not seg.output_path:
                        continue
                    # 如果片段需要 PIP 且已处理完成，使用处理后的路径
                    if getattr(seg, 'need_pip_overlay', False) and seg.segment_id in processed_paths:
                        video_paths.append(processed_paths[seg.segment_id])
                    # 如果片段不需要 PIP，直接使用原路径
                    elif not getattr(seg, 'need_pip_overlay', False):
                        video_paths.append(seg.output_path)
                    # 画外音叠加失败时回退使用对齐后的场景视频
                    else:
                        logger.warning(f"段落 {seg.segment_id} 画外音叠加失败，回退使用场景视频: {seg.output_path}")
                        video_paths.append(seg.output_path)
            
            if not video_paths:
                return PostProcessResult(
                    output_path=None,
                    status="failed",
                    error_message="没有视频片段可合并"
                )

            # 如果只有一个视频片段，直接使用该视频，避免不必要的合并
            intermediate_files = []
            if len(video_paths) == 1:
                logger.info(f"只有一个视频片段，直接使用原视频: {video_paths[0]}")
                output_path = video_paths[0]
                # 复制到中间处理目录，避免修改原文件
                import shutil
                intermediate_output_path = os.path.join(
                    self.intermediate_dir,
                    f"{task.task_id}.mp4"
                )
                try:
                    shutil.copy2(output_path, intermediate_output_path)
                    # 记录原始视频作为中间文件（双人模式的 merged_*.mp4）
                    if output_path != intermediate_output_path:
                        intermediate_files.append(output_path)
                    output_path = intermediate_output_path
                    logger.info(f"已复制视频到中间处理目录: {output_path}")
                except Exception as e:
                    logger.warning(f"复制视频失败，将使用原路径: {e}")
            else:
                # 多个视频片段，需要合并
                # 合并输出到中间处理目录
                intermediate_output_path = os.path.join(
                    self.intermediate_dir,
                    f"{task.task_id}.mp4"
                )

                # 根据配置选择合并方式
                logger.info(f"检查转场配置: enable_transition={config.enable_transition}, video_count={len(video_paths)}")
                success = False
                if config.enable_transition:
                    # 使用转场效果合并
                    logger.info("启用转场效果，使用 xfade 滤镜合并")
                    success = await self._concat_videos_with_transition(video_paths, intermediate_output_path, config)
                    if not success:
                        # 转场合并失败，回退到普通合并
                        logger.warning("转场合并失败，回退到普通合并")
                        success = await self._concat_videos(video_paths, intermediate_output_path)
                else:
                    # 使用普通合并
                    success = await self._concat_videos(video_paths, intermediate_output_path)

                if not success:
                    logger.error("视频合并失败")
                    return PostProcessResult(
                        output_path=None,
                        status="failed",
                        error_message="视频合并失败"
                    )

                if not os.path.exists(intermediate_output_path):
                    logger.error(f"视频合并成功，但文件不存在: {intermediate_output_path}")
                    return PostProcessResult(
                        output_path=None,
                        status="failed",
                        error_message="视频合并后文件不存在"
                    )

                logger.info(f"视频合并成功: {intermediate_output_path}")
                output_path = intermediate_output_path

            # 2. 添加字幕
            subtitle_path = None
            if config.enable_subtitle:
                if progress_callback:
                    progress_callback(0.0, "正在添加字幕")
                logger.info("开始添加字幕...")
                subtitle_path = await self._add_subtitle(
                    output_path,
                    task,
                    config
                )
                if progress_callback:
                    progress_callback(1.0, "字幕添加完成")
            else:
                logger.info("字幕功能已禁用，跳过字幕添加步骤")

            # 3. 添加 BGM
            if task.bgm_path:
                if progress_callback:
                    progress_callback(0.0, "正在添加背景音乐")
                logger.info(f"开始添加 BGM: {task.bgm_path}")
                output_path = await self._add_bgm(
                    output_path,
                    task.bgm_path,
                    config.bgm_volume
                )
                if progress_callback:
                    progress_callback(1.0, "背景音乐添加完成")

            # 4. 生成封面并插入帧
            cover_path = None
            if config.enable_cover:
                if progress_callback:
                    progress_callback(0.0, "正在生成封面")
                logger.info("开始生成封面...")
                cover_path = await self._generate_cover(output_path, task, config)

                if cover_path and os.path.exists(cover_path):
                    if progress_callback:
                        progress_callback(0.6, "封面生成完成，正在插入视频")
                    logger.info(f"封面生成成功: {cover_path}，开始插入封面帧...")
                    output_path = await self._insert_cover_frames(output_path, cover_path)
                    if progress_callback:
                        progress_callback(1.0, "封面插入完成")
                else:
                    logger.warning("封面生成失败或封面文件不存在，跳过帧插入")

            logger.info(f"后期处理完成，中间输出路径: {output_path}")

            # 将最终结果复制到最终输出目录（根目录 output/）
            final_output_path = os.path.join(self.output_dir, f"{task.task_id}.mp4")
            try:
                import shutil
                if os.path.abspath(output_path) != os.path.abspath(final_output_path):
                    shutil.copy2(output_path, final_output_path)
                    # 中间文件加入清理列表
                    intermediate_files.append(output_path)
                    logger.info(f"最终视频已复制到输出目录: {final_output_path}")
                else:
                    final_output_path = output_path
            except Exception as e:
                logger.warning(f"复制最终视频到输出目录失败，使用中间路径: {e}")
                final_output_path = output_path

            return PostProcessResult(
                output_path=final_output_path,
                subtitle_path=subtitle_path,
                cover_path=cover_path,
                status="success",
                intermediate_files=intermediate_files
            )

        except Exception as e:
            logger.error(f"后期处理失败: {e}")
            return PostProcessResult(
                output_path=None,
                status="failed",
                error_message=str(e)
            )

    async def _get_video_metadata(self, video_path: str) -> Dict[str, Any]:
        """
        获取视频元数据（分辨率、帧率等）

        Args:
            video_path: 视频文件路径

        Returns:
            包含元数据的字典
        """
        import json

        try:
            cmd = [
                FFPROBE_PATH,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                video_path
            ]

            returncode, stdout, stderr = await async_run_subprocess(cmd, check=True)
            data = json.loads(stdout.decode())

            video_stream = None
            audio_stream = None
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    video_stream = stream
                elif stream.get('codec_type') == 'audio':
                    audio_stream = stream

            if not video_stream:
                return {}

            metadata = {
                'width': int(video_stream.get('width', 1920)),
                'height': int(video_stream.get('height', 1080)),
                'r_frame_rate': video_stream.get('r_frame_rate', '30/1'),
                'duration': float(data.get('format', {}).get('duration', 0)),
                'bit_rate': data.get('format', {}).get('bit_rate'),
                'codec_name': video_stream.get('codec_name')
            }

            # 处理 SAR（Sample Aspect Ratio）：计算真实显示分辨率
            # SAR 定义：display_width = pixel_width * SAR_num / SAR_den，高度不变
            # 例如 2560x2498 [SAR 4096:4095] 的显示宽度 = 2560 * 4096/4095 ≈ 2560.6
            sar_str = video_stream.get('sample_aspect_ratio', '1:1')
            try:
                sar_num, sar_den = map(int, sar_str.split('/'))
                if sar_den > 0 and (sar_num != sar_den):
                    display_width = round(metadata['width'] * sar_num / sar_den)
                    logger.debug(f"视频 SAR={sar_str}, 像素尺寸={metadata['width']}x{metadata['height']}, 显示尺寸={display_width}x{metadata['height']}")
                    # 使用显示尺寸作为 width，确保后续比较和缩放基于显示尺寸
                    metadata['pixel_width'] = metadata['width']
                    metadata['pixel_height'] = metadata['height']
                    metadata['width'] = display_width
                    metadata['sar'] = sar_str
            except (ValueError, ZeroDivisionError):
                pass

            # 添加音频参数（如果存在音频流）
            if audio_stream:
                metadata['sample_rate'] = int(audio_stream.get('sample_rate', 44100))
                metadata['channels'] = int(audio_stream.get('channels', 2))

            try:
                num, den = map(int, metadata['r_frame_rate'].split('/'))
                metadata['fps'] = num / den if den > 0 else 30.0
            except:
                metadata['fps'] = 30.0

            return metadata
            
        except Exception as e:
            logger.error(f"获取视频元数据失败: {e}")
            return {}
    
    async def _normalize_video(self, video_path: str, target_width: int, target_height: int, target_fps: float, output_path: str, error_threshold: float = 10.0) -> bool:
        """
        标准化视频（统一分辨率和帧率），根据画面比例智能选择缩放方式

        缩放策略：
        - 比例误差 <= error_threshold: 拉伸缩放（scale 到目标尺寸）
        - 比例误差 > error_threshold: 填充缩放（等比缩放 + 模糊背景填充）

        Args:
            video_path: 输入视频路径
            target_width: 目标宽度
            target_height: 目标高度
            target_fps: 目标帧率
            output_path: 输出路径
            error_threshold: 比例误差阈值（默认10%）

        Returns:
            是否成功
        """
        try:
            # 获取输入视频的实际尺寸
            meta = await self._get_video_metadata(video_path)
            if not meta:
                logger.warning(f"无法获取视频信息，使用默认拉伸缩放: {video_path}")
                scale_filter = f"scale={target_width}:{target_height},setsar=1:1,fps={target_fps}"
            else:
                src_width = meta.get('width', 0)
                src_height = meta.get('height', 0)
                target_ratio = calculate_aspect_ratio(target_width, target_height)
                src_ratio = calculate_aspect_ratio(src_width, src_height)
                ratio_error = calculate_aspect_ratio_error(src_ratio, target_ratio)

                if src_width == target_width and src_height == target_height:
                    # 尺寸完全一致，只需统一帧率
                    scale_filter = f"fps={target_fps}"
                    logger.info(f"视频尺寸已一致 {src_width}x{src_height}，仅统一帧率")
                elif ratio_error <= error_threshold:
                    # 比例误差小，拉伸缩放
                    scale_filter = f"scale={target_width}:{target_height},setsar=1:1,fps={target_fps}"
                    logger.info(f"视频 {src_width}x{src_height} 比例误差 {ratio_error:.2f}% <= {error_threshold}%，拉伸缩放到 {target_width}x{target_height}")
                else:
                    # 比例误差大，填充缩放：等比缩放 + 模糊背景填充
                    # force_original_aspect_ratio 缩放后像素尺寸可能不等于目标尺寸，
                    # 需要在 overlay 后强制裁剪到精确目标尺寸并设置 SAR=1:1
                    scale_filter = (
                        f"split[original][bg];"
                        f"[bg]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
                        f"crop={target_width}:{target_height},"
                        f"boxblur=50:5,format=yuv420p[blurred_bg];"
                        f"[original]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                        f"format=yuv420p[fg];"
                        f"[blurred_bg][fg]overlay=(W-w)/2:(H-h)/2,"
                        f"crop={target_width}:{target_height},setsar=1:1,fps={target_fps}"
                    )
                    logger.info(f"视频 {src_width}x{src_height} 比例误差 {ratio_error:.2f}% > {error_threshold}%，填充缩放到 {target_width}x{target_height}")

            cmd = [
                FFMPEG_PATH,
                '-i', video_path,
                '-vf', scale_filter,
                '-c:v', 'libx264',
                '-crf', '18',
                '-preset', 'medium',
                '-c:a', 'aac',
                '-b:a', '192k',
                output_path
            ]

            logger.info(f"标准化视频: {video_path} -> {output_path} ({target_width}x{target_height}@{target_fps}fps)")
            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if returncode != 0:
                logger.error(f"视频标准化失败: {stderr.decode() if stderr else ''}")
                return False

            logger.info(f"视频标准化成功: {output_path}")
            return True

        except Exception as e:
            logger.error(f"视频标准化异常: {e}")
            return False
    
    async def _concat_videos(self, video_paths: List[str], output_path: str) -> bool:
        """
        合并视频（包含分辨率和帧率对齐）

        Args:
            video_paths: 视频路径列表
            output_path: 输出路径

        Returns:
            是否成功
        """
        if not video_paths:
            logger.warning("没有视频文件需要合并")
            return False

        try:
            import tempfile

            temp_dir = tempfile.mkdtemp(prefix="video_normalize_")

            try:
                all_metadata = []
                for path in video_paths:
                    if os.path.exists(path):
                        meta = await self._get_video_metadata(path)
                        if meta:
                            all_metadata.append(meta)

                if not all_metadata:
                    logger.error("无法获取任何视频的元数据")
                    return False

                # 选择面积最大（像素数最多）的视频作为基准
                # 横竖屏混合时，按多数方向过滤候选视频
                landscape_metas = [m for m in all_metadata if m.get('width', 0) >= m.get('height', 0)]
                portrait_metas = [m for m in all_metadata if m.get('width', 0) < m.get('height', 0)]
                if len(landscape_metas) >= len(portrait_metas):
                    candidates = landscape_metas if landscape_metas else all_metadata
                else:
                    candidates = portrait_metas if portrait_metas else all_metadata
                base_meta = max(candidates, key=lambda m: m.get('width', 0) * m.get('height', 0))
                target_width = base_meta['width']
                target_height = base_meta['height']
                target_fps = max(m.get('fps', 30.0) for m in all_metadata)

                logger.info(f"统一视频参数: 基准视频 {target_width}x{target_height}（面积最大）, 帧率 {target_fps}fps")

                normalized_paths = []
                for i, video_path in enumerate(video_paths):
                    if not os.path.exists(video_path):
                        logger.warning(f"视频文件不存在，跳过: {video_path}")
                        continue

                    meta = await self._get_video_metadata(video_path)

                    if not meta or meta['width'] != target_width or meta['height'] != target_height or abs(meta.get('fps', 30.0) - target_fps) > 0.1:
                        normalized_path = os.path.join(temp_dir, f"normalized_{i:03d}.mp4")
                        if await self._normalize_video(video_path, target_width, target_height, target_fps, normalized_path):
                            normalized_paths.append(normalized_path)
                        else:
                            logger.warning(f"视频标准化失败，使用原始视频: {video_path}")
                            normalized_paths.append(video_path)
                    else:
                        normalized_paths.append(video_path)

                list_file = os.path.join(self.intermediate_dir, "concat_list.txt")
                with open(list_file, 'w', encoding='utf-8') as f:
                    for path in normalized_paths:
                        f.write(f"file '{os.path.abspath(path)}'\n")

                # 检查是否所有视频参数完全一致，如果一致则可以使用 -c copy 快速合并
                all_same_params = all(
                    meta['width'] == target_width and
                    meta['height'] == target_height and
                    abs(meta.get('fps', 30.0) - target_fps) < 0.1
                    for meta in all_metadata
                )

                if all_same_params:
                    # 所有视频参数一致，使用 -c copy 快速合并
                    cmd = [
                        FFMPEG_PATH, "-f", "concat", "-safe", "0",
                        "-i", list_file, "-c", "copy", output_path
                    ]
                    logger.info(f"合并视频命令（快速模式）: {' '.join(cmd)}")
                else:
                    # 视频参数不一致，需要重新编码合并
                    cmd = [
                        FFMPEG_PATH, "-f", "concat", "-safe", "0",
                        "-i", list_file,
                        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        output_path
                    ]
                    logger.info(f"合并视频命令（重新编码模式）: {' '.join(cmd)}")

                await async_run_ffmpeg(cmd, check=True)
                os.remove(list_file)
                
                logger.info(f"视频合并成功: {output_path}")
                return True
                
            finally:
                import shutil
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    
        except Exception as e:
            logger.error(f"视频合并失败: {e}")
            return False

    async def _calculate_target_resolution(
        self,
        segments: List[Any]
    ) -> Tuple[int, int]:
        """
        从非场景标签的片段中计算目标分辨率

        从 task 的 segments 中收集非场景标签（开场/结束/情绪/loop）的视频 output_path，
        用 _get_video_metadata 获取尺寸，取面积最大者。
        场景素材不参与采样。

        Args:
            segments: 片段列表

        Returns:
            (target_width, target_height) 元组
        """
        max_area = 0
        target_width = 0
        target_height = 0
        found_any = False

        for seg in segments:
            # 跳过场景标签(场景素材不参与采样)
            if getattr(seg, 'is_scene_label', False):
                continue

            # 获取视频路径
            video_path = getattr(seg, 'output_path', None)
            if not video_path or not os.path.exists(video_path):
                continue

            try:
                meta = await self._get_video_metadata(video_path)
                if not meta:
                    continue

                width = meta.get('width', 0)
                height = meta.get('height', 0)
                area = width * height

                if area > max_area:
                    max_area = area
                    target_width = width
                    target_height = height
                    found_any = True
                    logger.info(f"更新目标分辨率: {target_width}x{target_height} (面积={area}, 来源={video_path})")

            except Exception as e:
                logger.warning(f"获取视频元数据失败: {video_path}, 错误: {e}")
                continue

        if not found_any:
            # 没有非场景标签视频，从场景标签视频中采样目标分辨率
            for seg in segments:
                video_path = getattr(seg, 'output_path', None)
                if not video_path or not os.path.exists(video_path):
                    continue

                try:
                    meta = await self._get_video_metadata(video_path)
                    if not meta:
                        continue

                    width = meta.get('width', 0)
                    height = meta.get('height', 0)
                    area = width * height

                    if area > max_area:
                        max_area = area
                        target_width = width
                        target_height = height
                        found_any = True
                        logger.info(f"从场景标签更新目标分辨率: {target_width}x{target_height} (面积={area}, 来源={video_path})")

                except Exception as e:
                    logger.warning(f"获取视频元数据失败: {video_path}, 错误: {e}")
                    continue

        if not found_any:
            logger.warning("未找到任何视频，使用默认分辨率 1920x1080")
            target_width = 1920
            target_height = 1080

        logger.info(f"最终目标分辨率: {target_width}x{target_height}")
        return target_width, target_height

    async def _process_pip_segments(
        self,
        segments: List[Any],
        config: TaskConfig
    ) -> Dict[str, str]:
        """
        处理需要 PIP 叠加的片段：先标准化场景视频，再叠加说话人视频

        Args:
            segments: 片段列表
            config: 任务配置

        Returns:
            segment_id 到处理后输出路径的映射
        """
        result_paths = {}

        # 收集需要 PIP 叠加的片段
        pip_segments = []
        for seg in segments:
            if getattr(seg, 'need_pip_overlay', False):
                pip_segments.append(seg)

        if not pip_segments:
            logger.info("没有需要 PIP 叠加的片段")
            return result_paths

        # 动态计算目标分辨率（从非场景标签的视频中取面积最大者）
        target_width, target_height = await self._calculate_target_resolution(segments)
        target_fps = 30.0

        logger.info(f"开始处理 {len(pip_segments)} 个 PIP 片段，目标分辨率: {target_width}x{target_height}@{target_fps}fps")

        for seg in pip_segments:
            speaker_video = getattr(seg, 'pending_speaker_video', None)
            scene_video = getattr(seg, 'scene_video_path', None)

            if not speaker_video or not scene_video:
                logger.warning(f"段落 {seg.segment_id} 缺少说话人或场景视频路径，跳过叠加")
                continue

            if not os.path.exists(speaker_video):
                logger.warning(f"段落 {seg.segment_id} 说话人视频不存在: {speaker_video}")
                continue

            if not os.path.exists(scene_video):
                logger.warning(f"段落 {seg.segment_id} 场景视频不存在: {scene_video}")
                continue

            try:
                # 步骤1：标准化场景视频到目标分辨率
                normalized_scene = os.path.join(
                    self.intermediate_dir,
                    f"scene_norm_{seg.segment_id}_{os.path.basename(scene_video)}"
                )

                scene_success = await self._normalize_video(
                    scene_video,
                    target_width,
                    target_height,
                    target_fps,
                    normalized_scene
                )

                if not scene_success or not os.path.exists(normalized_scene):
                    logger.warning(f"段落 {seg.segment_id} 场景视频标准化失败，跳过叠加")
                    continue

                # 步骤2：说话人视频不标准化，直接在 overlay 的 filter_complex 中 scale 到 PIP 大小

                # 步骤3：执行 PIP 叠加（说话人视频直接使用原始路径）
                output_path = os.path.join(
                    self.output_dir,
                    f"scene_pip_{seg.segment_id}.mp4"
                )

                merge_success = await self._merge_pip_video(
                    scene_video_path=normalized_scene,
                    pip_video_path=speaker_video,  # 直接使用原始说话人视频
                    output_path=output_path,
                    position="bottom-left",
                    pip_size=0.25,
                    circle_mask=True,
                    mix_audio=True,
                    remove_scene_audio=True
                )

                if merge_success and os.path.exists(output_path):
                    # 更新 segment 的 output_path
                    seg.output_path = output_path
                    seg.video_path = output_path
                    result_paths[seg.segment_id] = output_path
                    logger.info(f"段落 {seg.segment_id} PIP 叠加完成: {output_path}")
                else:
                    logger.error(f"段落 {seg.segment_id} PIP 叠加失败")

            except Exception as e:
                logger.error(f"段落 {seg.segment_id} PIP 处理异常: {e}")
                continue

        logger.info(f"PIP 片段处理完成: {len(result_paths)}/{len(pip_segments)}")
        return result_paths

    async def _process_double_pip(
        self,
        task: Any,
        scene_video_path: str,
        config: TaskConfig
    ) -> Optional[str]:
        """
        处理双人模式画外音叠加：先标准化场景视频，再叠加说话人视频

        Args:
            task: 任务对象
            scene_video_path: 场景视频路径
            config: 任务配置

        Returns:
            叠加后的视频路径，失败返回 None
        """
        if not scene_video_path or not os.path.exists(scene_video_path):
            logger.error(f"双人模式 PIP：场景视频不存在: {scene_video_path}")
            return None

        # 从 pip_speaker_videos 字典查找与场景视频匹配的说话人
        left_video = None
        right_video = None
        current_tone = "unknown"
        pip_speaker_videos = task.pip_speaker_videos
        if pip_speaker_videos:
            for tone, tone_data in pip_speaker_videos.items():
                if tone_data.get('scene') == scene_video_path:
                    left_video = tone_data.get('left')
                    right_video = tone_data.get('right')
                    current_tone = tone
                    logger.info(f"双人模式 PIP：从 pip_speaker_videos 匹配 tone '{tone}' 的说话人视频")
                    break
            # 如果未找到精确匹配，使用第一个 tone 的说话人
            if not left_video and not right_video:
                first_tone = next(iter(pip_speaker_videos))
                tone_data = pip_speaker_videos[first_tone]
                left_video = tone_data.get('left')
                right_video = tone_data.get('right')
                current_tone = first_tone
                logger.info(f"双人模式 PIP：未找到精确匹配，使用第一个 tone '{first_tone}' 的说话人视频")
        else:
            # 回退到 Task 平面属性
            left_video = task.scene_pip_left_video
            right_video = task.scene_pip_right_video

        if not left_video and not right_video:
            logger.warning("双人模式 PIP：没有说话人视频")
            return None

        # 动态计算目标分辨率（从非场景标签的视频中取面积最大者）
        segments = getattr(task, 'segments', [])
        target_width, target_height = await self._calculate_target_resolution(segments)
        target_fps = 30.0

        try:
            # 步骤1：标准化场景视频
            normalized_scene = os.path.join(
                self.intermediate_dir,
                f"scene_double_norm_{os.path.basename(scene_video_path)}"
            )

            scene_success = await self._normalize_video(
                scene_video_path,
                target_width,
                target_height,
                target_fps,
                normalized_scene
            )

            if not scene_success or not os.path.exists(normalized_scene):
                logger.error("双人模式 PIP：场景视频标准化失败")
                return None

            # 步骤2：说话人视频不标准化，直接在 overlay 的 filter_complex 中 scale 到 PIP 大小

            # 步骤3：执行叠加（说话人视频直接使用原始路径）
            output_path = os.path.join(
                self.output_dir,
                f"scene_pip_double_{task.task_id}_{current_tone}.mp4"
            )

            if left_video and os.path.exists(left_video) and right_video and os.path.exists(right_video):
                # 双人叠加：使用 merge_dual_pip_video
                success = await self._merge_dual_pip_video(
                    scene_video_path=normalized_scene,
                    left_pip_path=left_video,  # 直接使用原始说话人视频
                    right_pip_path=right_video,  # 直接使用原始说话人视频
                    output_path=output_path,
                    left_position="bottom-left",
                    right_position="bottom-right",
                    pip_size=0.25,
                    circle_mask=True,
                    remove_scene_audio=True
                )
            elif left_video and os.path.exists(left_video):
                # 只有左说话人
                success = await self._merge_pip_video(
                    scene_video_path=normalized_scene,
                    pip_video_path=left_video,  # 直接使用原始说话人视频
                    output_path=output_path,
                    position="bottom-left",
                    pip_size=0.25,
                    circle_mask=True,
                    mix_audio=True,
                    remove_scene_audio=True
                )
            elif right_video and os.path.exists(right_video):
                # 只有右说话人
                success = await self._merge_pip_video(
                    scene_video_path=normalized_scene,
                    pip_video_path=right_video,  # 直接使用原始说话人视频
                    output_path=output_path,
                    position="bottom-right",
                    pip_size=0.25,
                    circle_mask=True,
                    mix_audio=True,
                    remove_scene_audio=True
                )
            else:
                logger.error("双人模式 PIP：没有可用的说话人视频")
                return None

            if success and os.path.exists(output_path):
                logger.info(f"双人模式 PIP 叠加完成: {output_path}")
                return output_path
            else:
                logger.error("双人模式 PIP 叠加失败")
                return None

        except Exception as e:
            logger.error(f"双人模式 PIP 处理异常: {e}")
            return None

    async def _merge_dual_pip_video(
        self,
        scene_video_path: str,
        left_pip_path: str,
        right_pip_path: str,
        output_path: str,
        left_position: str = "bottom-left",
        right_position: str = "bottom-right",
        pip_size: float = 0.25,
        circle_mask: bool = True,
        remove_scene_audio: bool = True
    ) -> bool:
        """
        将左右两个画外音视频叠加到场景视频(先左后右切换)

        Args:
            scene_video_path: 场景视频路径
            left_pip_path: 左说话人视频路径
            right_pip_path: 右说话人视频路径
            output_path: 输出路径
            left_position: 左说话人位置
            right_position: 右说话人位置
            pip_size: PIP 大小比例
            circle_mask: 是否使用圆形遮罩
            remove_scene_audio: 是否移除场景音频(仅保留说话人音频)

        Returns:
            是否成功
        """
        try:
            # 获取场景视频信息
            scene_info = await self._get_video_metadata(scene_video_path)
            if not scene_info:
                logger.error(f"无法获取场景视频信息: {scene_video_path}")
                return False

            scene_width = scene_info.get('width', 1920)
            scene_height = scene_info.get('height', 1080)

            # 计算 PIP 尺寸
            pip_width = int(scene_width * pip_size)
            pip_height = int(pip_width * 1.0)

            # 根据位置计算坐标
            if left_position == "bottom-left":
                left_x, left_y = 20, scene_height - pip_height - 20
            else:
                left_x, left_y = 20, scene_height - pip_height - 20

            if right_position == "bottom-right":
                right_x, right_y = scene_width - pip_width - 20, scene_height - pip_height - 20
            else:
                right_x, right_y = scene_width - pip_width - 20, scene_height - pip_height - 20

            # 构建滤镜链 - PIP 视频在 filter_complex 中直接 scale 到 PIP 大小
            filters = []

            if circle_mask:
                # 缩放左 PIP + 圆形遮罩(format=yuva420p + geq alpha 通道)
                # 注意: geq 滤镜中冒号是 filter 选项分隔符, 必须用 \: 转义
                # 使用 lum='p(X,Y)' 保持亮度通道原值, a= 表达式实现圆形遮罩
                filters.append(
                    f"[1:v]scale={pip_width}:{pip_height}:force_original_aspect_ratio=decrease,"
                    f"pad={pip_width}:{pip_height}:(ow-iw)/2:(oh-ih)/2,"
                    f"setsar=1,format=yuva420p,"
                    f"geq=lum='p(X,Y)'\\:a='if(gt((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2),(W/2)*(W/2)),0,255)'[pip_left]"
                )
                # 缩放右 PIP + 圆形遮罩
                filters.append(
                    f"[2:v]scale={pip_width}:{pip_height}:force_original_aspect_ratio=decrease,"
                    f"pad={pip_width}:{pip_height}:(ow-iw)/2:(oh-ih)/2,"
                    f"setsar=1,format=yuva420p,"
                    f"geq=lum='p(X,Y)'\\:a='if(gt((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2),(W/2)*(W/2)),0,255)'[pip_right]"
                )
            else:
                # 缩放左 PIP(无遮罩)
                filters.append(
                    f"[1:v]scale={pip_width}:{pip_height}:force_original_aspect_ratio=decrease,"
                    f"pad={pip_width}:{pip_height}:(ow-iw)/2:(oh-ih)/2,setsar=1[pip_left]"
                )
                # 缩放右 PIP(无遮罩)
                filters.append(
                    f"[2:v]scale={pip_width}:{pip_height}:force_original_aspect_ratio=decrease,"
                    f"pad={pip_width}:{pip_height}:(ow-iw)/2:(oh-ih)/2,setsar=1[pip_right]"
                )

            # 先叠加左 PIP
            filters.append(f"[0:v][pip_left]overlay={left_x}:{left_y}[v_with_left]")

            # 再叠加右 PIP(在左边叠加后的结果上)
            filters.append(f"[v_with_left][pip_right]overlay={right_x}:{right_y}[outv]")

            filter_complex = ";".join(filters)

            # 音频映射: 使用 amix 滤镜真正混合音频, 而非多轨道映射
            if remove_scene_audio:
                # 画外音模式: 混合左右说话人音频为单轨道, 移除场景音频
                filter_complex += ";[1:a][2:a]amix=inputs=2:duration=longest:dropout_transition=2[aout]"
                audio_args = ["-map", "[aout]"]
            else:
                # 保留场景音频: 混合场景+左+右说话人音频为单轨道
                filter_complex += ";[0:a][1:a][2:a]amix=inputs=3:duration=first:dropout_transition=2[aout]"
                audio_args = ["-map", "[aout]"]

            # 构建命令
            cmd = [
                FFMPEG_PATH,
                "-stream_loop", "-1",
                "-i", scene_video_path,
                "-i", left_pip_path,
                "-i", right_pip_path,
                "-filter_complex", filter_complex,
                "-map", "[outv]",
            ]
            cmd.extend(audio_args)

            cmd.extend([
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                "-movflags", "+faststart",
                output_path
            ])

            logger.info(f"双人 PIP 叠加命令: {' '.join(cmd)}")
            await async_run_ffmpeg(cmd, check=True)

            if os.path.exists(output_path):
                logger.info(f"双人 PIP 叠加成功: {output_path}")
                return True
            else:
                logger.error(f"双人 PIP 叠加后文件不存在: {output_path}")
                return False

        except Exception as e:
            logger.error(f"双人 PIP 叠加失败: {e}")
            return False

    async def _apply_pip_overlay(
        self,
        segments: List[Any],
        target_width: int,
        target_height: int,
        target_fps: float
    ) -> Dict[str, str]:
        """
        对需要画外音叠加的片段进行标准化后的 PIP 叠加

        Args:
            segments: 包含 pending_speaker_video 和 scene_video_path 的片段列表
            target_width: 目标宽度
            target_height: 目标高度
            target_fps: 目标帧率

        Returns:
            segment_id 到叠加后视频路径的映射
        """
        result_paths = {}

        # 获取说话人视频的基准分辨率（用于确定叠加位置）
        # 由于场景视频已被标准化到目标分辨率，叠加位置也基于目标分辨率

        for segment in segments:
            # 检查是否需要 PIP 叠加
            if not getattr(segment, 'need_pip_overlay', False):
                continue

            speaker_video = getattr(segment, 'pending_speaker_video', None)
            scene_video = getattr(segment, 'scene_video_path', None)

            if not speaker_video or not scene_video:
                logger.warning(f"段落 {segment.segment_id} 缺少说话人或场景视频路径，跳过叠加")
                continue

            if not os.path.exists(speaker_video):
                logger.warning(f"段落 {segment.segment_id} 说话人视频不存在: {speaker_video}")
                continue

            if not os.path.exists(scene_video):
                logger.warning(f"段落 {segment.segment_id} 场景视频不存在: {scene_video}")
                continue

            try:
                # 标准化说话人视频到目标分辨率
                normalized_speaker = os.path.join(
                    self.intermediate_dir,
                    f"pip_normalized_{segment.segment_id}_{os.path.basename(speaker_video)}"
                )

                # 标准化说话人视频
                speaker_normalized = await self._normalize_video(
                    speaker_video,
                    target_width,
                    target_height,
                    target_fps,
                    normalized_speaker
                )

                if not speaker_normalized:
                    logger.warning(f"段落 {segment.segment_id} 说话人视频标准化失败，跳过叠加")
                    continue

                # 标准化场景视频到目标分辨率
                normalized_scene = os.path.join(
                    self.intermediate_dir,
                    f"scene_normalized_{segment.segment_id}_{os.path.basename(scene_video)}"
                )

                scene_normalized = await self._normalize_video(
                    scene_video,
                    target_width,
                    target_height,
                    target_fps,
                    normalized_scene
                )

                if not scene_normalized:
                    logger.warning(f"段落 {segment.segment_id} 场景视频标准化失败，跳过叠加")
                    continue

                # 执行 PIP 叠加（基于标准化后的分辨率）
                output_path = os.path.join(
                    self.intermediate_dir,
                    f"scene_pip_{segment.segment_id}.mp4"
                )

                success = await self._merge_pip_video(
                    scene_video_path=scene_normalized,
                    pip_video_path=speaker_normalized,
                    output_path=output_path,
                    position="bottom-left",
                    pip_size=0.25,
                    circle_mask=True,
                    mix_audio=True,
                    remove_scene_audio=True
                )

                if success and os.path.exists(output_path):
                    result_paths[segment.segment_id] = output_path
                    logger.info(f"段落 {segment.segment_id} PIP 叠加完成: {output_path}")
                else:
                    logger.error(f"段落 {segment.segment_id} PIP 叠加失败")

            except Exception as e:
                logger.error(f"段落 {segment.segment_id} PIP 叠加异常: {e}")
                continue

        return result_paths

    async def _merge_pip_video(
        self,
        scene_video_path: str,
        pip_video_path: str,
        output_path: str,
        position: str = "bottom-left",
        pip_size: float = 0.25,
        circle_mask: bool = True,
        mix_audio: bool = False,
        remove_scene_audio: bool = False
    ) -> bool:
        """
        将画外音视频叠加到场景视频(使用 -stream_loop -1 保持画面持续)

        Args:
            scene_video_path: 场景视频路径
            pip_video_path: 画外音视频路径
            output_path: 输出路径
            position: 位置
            pip_size: PIP 大小比例
            circle_mask: 是否使用圆形遮罩
            mix_audio: 是否混合音频
            remove_scene_audio: 是否移除场景音频

        Returns:
            是否成功
        """
        try:
            # 获取场景视频信息
            scene_info = await self._get_video_metadata(scene_video_path)
            if not scene_info:
                logger.error(f"无法获取场景视频信息: {scene_video_path}")
                return False

            scene_width = scene_info.get('width', 1920)
            scene_height = scene_info.get('height', 1080)

            # 计算 PIP 尺寸和位置
            pip_width = int(scene_width * pip_size)
            pip_height = int(pip_width * 1.0)  # 保持 1:1 比例

            # 根据位置计算坐标
            if position == "bottom-left":
                pip_x = 20
                pip_y = scene_height - pip_height - 20
            elif position == "bottom-right":
                pip_x = scene_width - pip_width - 20
                pip_y = scene_height - pip_height - 20
            elif position == "top-left":
                pip_x = 20
                pip_y = 20
            elif position == "top-right":
                pip_x = scene_width - pip_width - 20
                pip_y = 20
            else:
                pip_x = 20
                pip_y = scene_height - pip_height - 20

            # 构建 filter_complex - PIP 视频在 filter 中直接 scale 到 PIP 大小
            pw = pip_width
            ph = pip_height

            if circle_mask:
                # 圆形遮罩: format=yuva420p + geq alpha 通道
                # 注意: geq 滤镜中冒号是 filter 选项分隔符, 必须用 \: 转义
                # 使用 lum='p(X,Y)' 保持亮度通道原值, a= 表达式实现圆形遮罩
                pip_filter_chain = (
                    f"[1:v]scale={pw}:{ph}:force_original_aspect_ratio=decrease,"
                    f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2,"
                    f"setsar=1,format=yuva420p,"
                    f"geq=lum='p(X,Y)'\\:a='if(gt((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2),(W/2)*(W/2)),0,255)'[pip]"
                )
            else:
                # 无遮罩: 直接 scale + pad
                pip_filter_chain = (
                    f"[1:v]scale={pw}:{ph}:force_original_aspect_ratio=decrease,"
                    f"pad={pw}:{ph}:(ow-iw)/2:(oh-ih)/2,setsar=1[pip]"
                )

            # overlay 滤镜: 场景视频 + PIP 视频
            overlay_filter = f"[0:v][pip]overlay={pip_x}:{pip_y}[outv]"
            filter_complex = f"{pip_filter_chain};{overlay_filter}"

            # 音频映射逻辑: 使用 amix 滤镜真正混合音频, 而非多轨道映射
            if mix_audio and remove_scene_audio:
                # 画外音模式: 只保留说话人音频, 移除场景音频
                audio_args = ["-map", "1:a"]
            elif mix_audio:
                # 混合场景音频和说话人音频(使用 amix 真正混音为单轨道)
                filter_complex += ";[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2[aout]"
                audio_args = ["-map", "[aout]"]
            elif remove_scene_audio:
                # 不混合 + 移除场景音频: 无音频
                audio_args = ["-an"]
            else:
                # 不混合 + 不移除: 只保留场景音频(0:a)
                audio_args = ["-map", "0:a"]

            # 构建命令
            cmd = [
                FFMPEG_PATH,
                "-stream_loop", "-1",
                "-i", scene_video_path,
                "-i", pip_video_path,
                "-filter_complex", filter_complex,
                "-map", "[outv]",
            ]
            cmd.extend(audio_args)

            cmd.extend([
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                "-movflags", "+faststart",
                output_path
            ])

            logger.info(f"PIP 叠加命令: {' '.join(cmd)}")
            await async_run_ffmpeg(cmd, check=True)

            if os.path.exists(output_path):
                logger.info(f"PIP 叠加成功: {output_path}")
                return True
            else:
                logger.error(f"PIP 叠加后文件不存在: {output_path}")
                return False

        except Exception as e:
            logger.error(f"PIP 叠加失败: {e}")
            return False

    async def _concat_videos_with_transition(
        self,
        video_paths: List[str],
        output_path: str,
        config: TaskConfig
    ) -> bool:
        """
        使用 FFmpeg xfade 滤镜合并视频（带转场效果）

        Args:
            video_paths: 视频路径列表
            output_path: 输出路径
            config: 任务配置（包含转场参数）

        Returns:
            是否成功
        """
        if not video_paths:
            logger.warning("没有视频文件需要合并")
            return False

        if len(video_paths) < 2:
            logger.warning("转场效果需要至少 2 个视频片段")
            return False

        try:
            import tempfile

            temp_dir = tempfile.mkdtemp(prefix="video_transition_")

            try:
                # 1. 获取所有视频的元数据，确定统一参数
                all_metadata = []
                for path in video_paths:
                    if os.path.exists(path):
                        meta = await self._get_video_metadata(path)
                        if meta:
                            all_metadata.append(meta)

                if not all_metadata:
                    logger.error("无法获取任何视频的元数据")
                    return False

                # 选择面积最大（像素数最多）的视频作为基准
                # 横竖屏混合时，按多数方向过滤候选视频
                landscape_metas = [m for m in all_metadata if m.get('width', 0) >= m.get('height', 0)]
                portrait_metas = [m for m in all_metadata if m.get('width', 0) < m.get('height', 0)]
                if len(landscape_metas) >= len(portrait_metas):
                    candidates = landscape_metas if landscape_metas else all_metadata
                else:
                    candidates = portrait_metas if portrait_metas else all_metadata
                base_meta = max(candidates, key=lambda m: m.get('width', 0) * m.get('height', 0))
                target_width = base_meta['width']
                target_height = base_meta['height']
                target_fps = max(m.get('fps', 30.0) for m in all_metadata)

                logger.info(f"转场合并统一视频参数: 基准视频 {target_width}x{target_height}（面积最大）, 帧率 {target_fps}fps")

                # 2. 标准化所有视频
                normalized_paths = []
                video_durations = []

                for i, video_path in enumerate(video_paths):
                    if not os.path.exists(video_path):
                        logger.warning(f"视频文件不存在，跳过: {video_path}")
                        continue

                    meta = await self._get_video_metadata(video_path)

                    # 标准化视频
                    normalized_path = os.path.join(temp_dir, f"normalized_{i:03d}.mp4")
                    if not meta or meta['width'] != target_width or meta['height'] != target_height or abs(meta.get('fps', 30.0) - target_fps) > 0.1:
                        if await self._normalize_video(video_path, target_width, target_height, target_fps, normalized_path):
                            normalized_paths.append(normalized_path)
                        else:
                            logger.warning(f"视频标准化失败，使用原始视频: {video_path}")
                            normalized_paths.append(video_path)
                    else:
                        normalized_paths.append(video_path)

                    # 获取视频时长
                    duration = await self._get_media_duration(normalized_paths[-1])
                    video_durations.append(duration)

                if len(normalized_paths) < 2:
                    logger.error("标准化后有效视频不足 2 个")
                    return False

                # 3. 构建转场效果序列
                transition_duration = config.transition_duration
                effects = self._build_transition_effects(
                    len(normalized_paths),
                    config
                )

                # 4. 构建 xfade 滤镜链
                filter_complex = self._build_xfade_filter_chain(
                    normalized_paths,
                    video_durations,
                    effects,
                    transition_duration
                )

                if not filter_complex:
                    logger.error("构建 xfade 滤镜链失败")
                    return False

                # 构建音频合并滤镜（使用 acrossfade 与视频转场同步）
                # 音频的 acrossfade 需要与视频的 xfade 时间轴匹配
                audio_filter_parts = []
                if len(normalized_paths) == 2:
                    # 两个视频：简单的音频交叉淡入淡出
                    audio_filter = f"[0:a][1:a]acrossfade=d={transition_duration}:c1=tri:c2=tri[aout]"
                else:
                    # 多个视频：链式音频 acrossfade
                    # 与视频 xfade 的 offset 计算逻辑相同
                    current_audio_input = "[0:a]"
                    accumulated_duration = 0.0

                    for i in range(len(normalized_paths) - 1):
                        accumulated_duration += video_durations[i]

                        output_label = f"[a{i}]" if i < len(normalized_paths) - 2 else "[aout]"
                        # 使用 acrossfade 进行音频交叉淡入淡出
                        audio_filter_part = f"{current_audio_input}[{i+1}:a]acrossfade=d={transition_duration}:c1=tri:c2=tri{output_label}"
                        audio_filter_parts.append(audio_filter_part)
                        current_audio_input = f"[a{i}]"

                        # 从累计时长中减去转场时长（与视频 xfade 逻辑一致）
                        accumulated_duration -= transition_duration

                    audio_filter = ";".join(audio_filter_parts)

                # 合并视频和音频滤镜
                full_filter_complex = f"{filter_complex};{audio_filter}"

                # 5. 执行 FFmpeg 命令
                cmd = [
                    FFMPEG_PATH
                ]

                # 添加输入文件
                for path in normalized_paths:
                    cmd.extend(["-i", path])

                # 添加滤镜
                cmd.extend(["-filter_complex", full_filter_complex])

                # 输出设置 - 同时映射视频和音频
                cmd.extend([
                    "-map", "[vout]",
                    "-map", "[aout]",
                    "-c:v", "libx264",
                    "-crf", "18",
                    "-preset", "medium",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    output_path
                ])

                logger.info(f"转场合并命令: {' '.join(cmd)}")
                returncode, stdout, stderr = await async_run_ffmpeg(cmd)

                if returncode != 0:
                    logger.error(f"转场合并失败: {stderr.decode() if stderr else ''}")
                    return False

                logger.info(f"转场合并成功: {output_path}")
                return True

            finally:
                import shutil
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"转场合并失败: {e}")
            return False

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
                # 每次转场都随机选择效果
                effects = [random.choice(ALL_TRANSITION_EFFECTS) for _ in range(transition_count)]
                logger.info(f"随机转场效果（每次不同）: {effects}")
            else:
                # 整个视频统一使用一个随机效果
                effect = random.choice(ALL_TRANSITION_EFFECTS)
                effects = [effect] * transition_count
                logger.info(f"随机转场效果（统一）: {effect}")
        else:
            # 使用用户指定的效果
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

            # 验证转场时长不超过最短视频时长
            min_duration = min(video_durations)
            if transition_duration >= min_duration:
                logger.warning(f"转场时长 {transition_duration}s 超过最短视频时长 {min_duration}s，自动调整为 {min_duration * 0.4:.2f}s")
                transition_duration = min_duration * 0.4

            filter_parts = []

            # 第一个转场：[0:v][1:v]xfade=transition=fade:duration=0.5:offset=X[v0]
            # 第二个转场：[v0][2:v]xfade=transition=fade:duration=0.5:offset=Y[v1]
            # ...

            # 正确的 offset 计算：
            # 第一个转场 offset = 第一个视频时长 - 转场时长
            # 第二个转场 offset = 第一个视频时长 + 第二个视频时长 - 2 * 转场时长
            # 即：累计时长 - (转场次数 * 转场时长)

            accumulated_duration = 0.0
            current_input = "[0:v]"

            for i in range(n - 1):
                effect = effects[i] if i < len(effects) else "fade"
                output_label = f"[v{i}]" if i < n - 2 else "[vout]"

                # 累加当前视频时长
                accumulated_duration += video_durations[i]

                # 计算当前转场的 offset
                # offset = 累计时长 - (已完成的转场数 + 1) * 转场时长
                current_offset = accumulated_duration - transition_duration

                filter_part = f"{current_input}[{i+1}:v]xfade=transition={effect}:duration={transition_duration}:offset={current_offset:.3f}{output_label}"
                filter_parts.append(filter_part)

                # 更新下一个转场的输入
                current_input = f"[v{i}]"

                # 从累计时长中减去转场时长（因为转场期间两个视频重叠）
                accumulated_duration -= transition_duration

            filter_complex = ";".join(filter_parts)
            logger.info(f"xfade 滤镜链: {filter_complex}")

            return filter_complex

        except Exception as e:
            logger.error(f"构建 xfade 滤镜链失败: {e}")
            return None

    def _split_text_to_sentences(self, text: str, max_chars: int = 12) -> List[str]:
        """
        将文本按标点符号拆分

        改进策略：
        1. 按所有标点符号拆分（句末标点 + 逗号类标点）
        2. 单条字幕限制为 max_chars 字（默认12字）
        3. 避免单独的标点符号成为一条字幕

        Args:
            text: 原始文本
            max_chars: 单条字幕最大字数

        Returns:
            句子列表
        """
        import re

        if not text:
            return []

        # 按所有标点符号拆分（中英文标点）
        # 包括：句末标点（。！？.!?）和逗号类标点（，,；;：:）
        sentences = re.split(r'([。！？.!?，,；;：:])', text)

        # 合并标点符号和句子
        result = []
        for i in range(0, len(sentences), 2):
            if i + 1 < len(sentences):
                sentence = sentences[i].strip() + sentences[i + 1].strip()
            else:
                sentence = sentences[i].strip()

            if sentence:
                # 跳过只有标点符号的片段
                if all(c in '，,；;：:。！？.!?' for c in sentence.strip()):
                    continue

                # 如果句子超过字数限制，进一步拆分
                if len(sentence) > max_chars:
                    sub_sentences = self._split_by_char_limit(sentence, max_chars)
                    result.extend(sub_sentences)
                else:
                    result.append(sentence)

        # 如果没有拆分出句子，返回原文本作为一个句子
        if not result and text.strip():
            if len(text.strip()) > max_chars:
                result = self._split_by_char_limit(text.strip(), max_chars)
            else:
                result = [text.strip()]

        return result

    def _split_by_char_limit(self, text: str, max_chars: int) -> List[str]:
        """
        按字数限制分割文本

        策略：
        1. 严格按字数限制分割，确保每段不超过 max_chars
        2. 尽量在标点符号后分割，保留标点
        3. 避免单独的标点符号成为一条字幕
        """
        if len(text) <= max_chars:
            return [text]

        chunks = []
        remaining = text

        while len(remaining) > max_chars:
            # 默认在 max_chars 位置分割
            split_pos = max_chars

            # 尝试在 max_chars 位置附近找一个标点作为分割点
            for i in range(min(max_chars, len(remaining)) - 1, max(0, max_chars - 5), -1):
                if remaining[i] in '，,；;：:。！？.!?':
                    split_pos = i + 1
                    break

            # 确保分割位置不超过 max_chars
            split_pos = min(split_pos, max_chars)

            chunk = remaining[:split_pos]
            # 只有当 chunk 不只是标点符号时才添加
            if chunk.strip() and not all(c in '，,；;：:。！？.!?' for c in chunk.strip()):
                chunks.append(chunk)

            remaining = remaining[split_pos:]

        if remaining:
            if remaining.strip() and not all(c in '，,；;：:。！？.!?' for c in remaining.strip()):
                chunks.append(remaining)

        return chunks if chunks else [text]

    async def _add_subtitle(
        self,
        video_path: str,
        task: Task,
        config: TaskConfig
    ) -> Optional[str]:
        """
        添加字幕 - 使用精确字幕时间轴同步器

        Args:
            video_path: 视频路径
            task: 任务对象
            config: 配置对象

        Returns:
            SRT 文件路径，如果失败返回 None
        """
        try:
            # 字幕文件保存到临时目录，而不是跟随视频路径
            from core.paths import get_path_manager
            path_manager = get_path_manager()
            srt_path = os.path.join(path_manager.temp_dir, f"{task.task_id}.srt")

            # 准备段落文本和时长信息
            segments_text = []
            segment_durations = []
            segment_offsets = []

            current_offset = 0.0
            for segment in task.segments:
                if segment.text:
                    segments_text.append(segment.text)
                    duration = getattr(segment, 'duration', 0.0)
                    segment_durations.append(duration)
                    segment_offsets.append(current_offset)
                    current_offset += duration

            if not segments_text:
                logger.info("没有文本内容，跳过字幕生成")
                return None

            # 检查是否启用精准字幕
            use_precise = self._should_use_precise_subtitle()

            if use_precise:
                logger.info("使用精准字幕生成模式")
                current_srt_path = await self._generate_precise_subtitle(
                    video_path=video_path,
                    segments_text=segments_text,
                    output_srt_path=srt_path
                )
                if not current_srt_path:
                    logger.warning("精准字幕失败，回退到默认字幕")
                    use_precise = False

            if not use_precise:
                # 使用默认字幕生成
                current_srt_path = self._generate_default_subtitle(
                    segments_text=segments_text,
                    segment_durations=segment_durations,
                    segment_offsets=segment_offsets,
                    output_srt_path=srt_path,
                    task=task
                )

            if not current_srt_path:
                logger.warning("字幕生成失败")
                return None
            logger.info(f"字幕生成成功：{current_srt_path}")

            # 烧录字幕到视频
            output_path = video_path.replace(".mp4", "_subtitled.mp4")

            srt_path_abs = current_srt_path.replace("\\", "/")

            # 检查 SRT 文件是否存在
            if not os.path.exists(current_srt_path):
                logger.error(f"SRT 文件不存在: {current_srt_path}")
                return None

            logger.info(f"SRT 文件存在，大小: {os.path.getsize(current_srt_path)} bytes")

            # 构建字幕滤镜，需要正确处理 Windows 路径中的冒号
            # ffmpeg 的 subtitles 滤镜中，冒号是选项分隔符，需要转义为 \\:
            srt_path_escaped = srt_path_abs.replace(":", "\\:")

            # 构建字幕样式参数 (force_style)
            # 从 config 中获取字幕样式配置
            style_params = []

            # 字体
            if hasattr(config, 'subtitle_font') and config.subtitle_font:
                style_params.append(f"FontName={config.subtitle_font}")

            # 字号
            if hasattr(config, 'subtitle_size'):
                style_params.append(f"FontSize={config.subtitle_size}")

            # 颜色 (需要转换为 ASS 格式，BGR 顺序)
            if hasattr(config, 'subtitle_color') and config.subtitle_color:
                ass_color = self._hex_to_ass_color(config.subtitle_color)
                style_params.append(f"PrimaryColour={ass_color}")

            # 描边颜色
            if hasattr(config, 'subtitle_stroke_color') and config.subtitle_stroke_color:
                ass_stroke_color = self._hex_to_ass_color(config.subtitle_stroke_color)
                style_params.append(f"OutlineColour={ass_stroke_color}")

            # 描边宽度
            if hasattr(config, 'subtitle_stroke_width'):
                style_params.append(f"Outline={config.subtitle_stroke_width}")

            # 背景透明度 (使用 BackColour 和 Alpha)
            if hasattr(config, 'subtitle_background_alpha') and config.subtitle_background_alpha > 0:
                # 有背景时设置黑色半透明背景
                alpha = int((1 - config.subtitle_background_alpha) * 255)
                style_params.append(f"BackColour=&H{alpha:02X}000000")
                style_params.append("BorderStyle=3")

            # 字幕位置 (通过 MarginV 控制垂直距离)
            if hasattr(config, 'subtitle_position'):
                position = config.subtitle_position
                if hasattr(position, 'value'):
                    position_value = position.value
                else:
                    position_value = str(position)

                # 根据位置设置垂直边距
                if position_value == "top":
                    # 顶部：设置较大的 MarginV 使字幕靠近顶部
                    style_params.append("MarginV=50")
                    style_params.append("Alignment=6")  # 顶部居中
                elif position_value == "center":
                    # 居中：使用默认对齐
                    style_params.append("MarginV=0")
                    style_params.append("Alignment=10")  # 垂直居中
                else:  # bottom
                    # 底部：默认位置
                    style_params.append("MarginV=30")
                    style_params.append("Alignment=2")  # 底部居中

            # 构建 force_style 参数
            if style_params:
                force_style = ",".join(style_params)
                subtitle_filter = f"subtitles='{srt_path_escaped}':force_style='{force_style}'"
            else:
                subtitle_filter = f"subtitles='{srt_path_escaped}'"

            logger.info(f"字幕滤镜: {subtitle_filter}")

            # 构建 ffmpeg 命令列表
            cmd = [
                FFMPEG_PATH,
                "-i", video_path,
                "-vf", subtitle_filter,
                "-c:v", "libx264",
                "-crf", "18",
                "-c:a", "aac",
                "-b:a", "192k",
                output_path
            ]

            logger.info(f"添加字幕命令: {' '.join(cmd)}")
            try:
                returncode, stdout, stderr = await async_run_ffmpeg(cmd, check=True)
            except Exception as e:
                stderr_text = stderr.decode() if stderr else ''
                stdout_text = stdout.decode() if stdout else ''
                logger.error(f"ffmpeg 错误输出: {stderr_text}")
                logger.error(f"ffmpeg 标准输出: {stdout_text}")
                raise

            os.replace(output_path, video_path)

            logger.info(f"字幕添加成功: {srt_path}")
            return srt_path

        except Exception as e:
            logger.error(f"添加字幕失败: {e}")
            import traceback
            logger.error(f"字幕添加失败详情: {traceback.format_exc()}")
            return None

    def _hex_to_ass_color(self, hex_color: str) -> str:
        """
        将十六进制颜色转换为 ASS 格式颜色

        ASS 格式使用 BGR 顺序，格式为 &HAABBGGRR
        其中 AA 是透明度 (00=不透明, FF=完全透明)

        Args:
            hex_color: 十六进制颜色，如 "#FFFFFF" 或 "white" 或 "rgb(255,255,255)"

        Returns:
            ASS 格式颜色字符串，如 "&H00FFFFFF"
        """
        # 处理颜色名称
        color_names = {
            "white": "#FFFFFF",
            "black": "#000000",
            "red": "#FF0000",
            "green": "#00FF00",
            "blue": "#0000FF",
            "yellow": "#FFFF00",
            "cyan": "#00FFFF",
            "magenta": "#FF00FF",
        }

        hex_color = hex_color.strip()

        # 如果是颜色名称，转换为十六进制
        if hex_color.lower() in color_names:
            hex_color = color_names[hex_color.lower()]

        # 处理 rgb() 格式
        if hex_color.startswith("rgb("):
            import re
            match = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", hex_color)
            if match:
                r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
                return f"&H00{b:02X}{g:02X}{r:02X}"

        # 处理十六进制格式
        if hex_color.startswith("#"):
            hex_color = hex_color[1:]

        # 确保是6位十六进制
        if len(hex_color) == 3:
            hex_color = hex_color[0] * 2 + hex_color[1] * 2 + hex_color[2] * 2

        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            # ASS 格式: BGR 顺序，前缀 &H00 表示不透明
            return f"&H00{b:02X}{g:02X}{r:02X}"

        # 默认返回白色
        return "&H00FFFFFF"

    def _format_srt_time(self, seconds: float) -> str:
        """格式化 SRT 时间"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    async def _add_bgm(
        self,
        video_path: str,
        bgm_path: str,
        volume: float = 0.3
    ) -> str:
        """
        添加 BGM（支持循环播放对齐视频长度）

        正确逻辑：
        1. 视频比 BGM 长 → 循环 BGM
        2. 视频比 BGM 短 → 截取 BGM
        3. 输出时长始终等于视频时长

        Args:
            video_path: 视频文件路径
            bgm_path: BGM 音频文件路径
            volume: BGM 音量（0.0-1.0）

        Returns:
            处理后的视频路径
        """
        try:
            logger.info(f"开始添加 BGM: {bgm_path} 到视频 {video_path}")

            if not os.path.exists(bgm_path):
                logger.error(f"BGM 文件不存在: {bgm_path}")
                return video_path

            output_path = video_path.replace(".mp4", "_bgm.mp4")

            video_duration = await self._get_media_duration(video_path)
            bgm_duration = await self._get_media_duration(bgm_path)

            logger.info(f"视频时长: {video_duration}s, BGM时长: {bgm_duration}s")

            if video_duration <= 0:
                logger.error(f"无法获取视频时长，跳过 BGM 添加")
                return video_path

            if bgm_duration <= 0:
                logger.error(f"无法获取 BGM 时长，跳过 BGM 添加")
                return video_path

            # 核心修复：使用 -shortest 确保输出时长等于最短的输入
            # 同时使用 -t 参数明确指定输出时长为视频时长

            if bgm_duration < video_duration:
                # BGM 比视频短：需要循环 BGM
                loop_count = int(video_duration / bgm_duration) + 1
                logger.info(f"BGM 需要循环 {loop_count} 次以覆盖视频时长")

                cmd = [
                    FFMPEG_PATH,
                    "-i", video_path,
                    "-stream_loop", str(loop_count),
                    "-i", bgm_path,
                    "-filter_complex",
                    f"[1:a]volume={volume}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",  # 确保输出时长等于最短的输入（视频）
                    output_path
                ]
            else:
                # BGM 比视频长或相等：截取 BGM
                logger.info(f"BGM 时长足够，截取前 {video_duration}s")

                cmd = [
                    FFMPEG_PATH,
                    "-i", video_path,
                    "-i", bgm_path,
                    "-filter_complex",
                    f"[1:a]volume={volume},atrim=0:{video_duration},asetpts=PTS-STARTPTS[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]",
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    output_path
                ]

            logger.info(f"BGM 添加命令: {' '.join(cmd)}")
            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if returncode != 0:
                logger.error(f"BGM 添加失败: {stderr.decode() if stderr else ''}")
                return video_path

            # 验证输出文件
            if not os.path.exists(output_path):
                logger.error(f"BGM 添加后输出文件不存在: {output_path}")
                return video_path

            output_duration = await self._get_media_duration(output_path)
            logger.info(f"BGM 添加成功，输出时长: {output_duration}s (原视频: {video_duration}s)")

            # 验证时长是否正确（允许 0.5 秒误差）
            if abs(output_duration - video_duration) > 0.5:
                logger.warning(f"输出时长与原视频时长不匹配，可能存在问题")

            os.replace(output_path, video_path)

            return video_path

        except Exception as e:
            logger.error(f"添加 BGM 失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            return video_path

    async def _get_media_duration(self, media_path: str) -> float:
        """获取媒体文件时长"""
        try:
            cmd = [
                FFPROBE_PATH, '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                media_path
            ]
            returncode, stdout, stderr = await async_run_subprocess(cmd, check=True)
            return float(stdout.decode().strip())
        except Exception as e:
            logger.error(f"获取媒体时长失败: {e}")
            return 0.0

    async def _generate_cover(self, video_path: str, task: Task, config=None) -> Optional[str]:
        """
        生成视频封面（从开场视频截取帧，调用本地 AI 模型）

        功能：
        1. 从开场视频提取参考帧
        2. 调用本地 Qwen-Image-Edit 模型生成封面
        3. 保存封面到独立文件（output/{task_id}_cover.jpg）
        4. 返回封面路径供后续插入视频开头
        """
        try:
            opening_video = getattr(task, 'opening_video', None)
            opening_video_with_tags = getattr(task, 'opening_video_with_tags', None)

            if opening_video_with_tags and hasattr(opening_video_with_tags, 'file_path'):
                opening_video = opening_video_with_tags.file_path

            if not opening_video or not os.path.exists(opening_video):
                logger.warning(f"开场视频不存在，跳过封面生成: {opening_video}")
                return None

            reference_path = video_path.replace(".mp4", "_reference.jpg")
            cmd = [
                FFMPEG_PATH,
                "-i", opening_video,
                "-ss", "00:00:01",
                "-vframes", "1",
                "-q:v", "2",
                reference_path
            ]
            await async_run_ffmpeg(cmd, check=True)

            if not os.path.exists(reference_path):
                logger.error("从开场视频截取帧失败")
                return None

            logger.info(f"从开场视频截取参考帧成功: {reference_path}")

            cover_summary = self._extract_cover_summary(task)
            cover_prompt = self._build_cover_prompt(cover_summary, config)
            logger.info(f"封面提示词: {cover_prompt}")

            # 调用本地 AI 模型生成封面
            output_dir = os.path.join(self.output_dir, "covers")
            os.makedirs(output_dir, exist_ok=True)
            cover_path = os.path.join(output_dir, f"{task.task_id}_cover.jpg")

            logger.info(f"开始调用本地 AI 模型生成封面...")

            from business.postprocess.local_cover_generator import generate_cover_from_reference

            generated_cover_path = generate_cover_from_reference(
                reference_image_path=reference_path,
                prompt=cover_prompt,
                output_path=cover_path,
            )

            # 清理参考帧
            if os.path.exists(reference_path):
                os.remove(reference_path)

            if generated_cover_path and os.path.exists(generated_cover_path):
                logger.info(f"封面生成成功：{generated_cover_path}")
                # 卸载模型释放显存
                try:
                    from business.postprocess.local_cover_generator import get_cover_generator
                    cover_gen = get_cover_generator()
                    if cover_gen:
                        cover_gen.unload()
                        logger.info("封面模型已卸载，显存已释放")
                except Exception as unload_error:
                    logger.warning(f"卸载模型失败：{unload_error}")
                return generated_cover_path
            else:
                logger.error("本地 AI 封面生成失败")
                return None

        except Exception as e:
            logger.error(f"封面生成失败: {e}")
            return None

    def _extract_cover_summary(self, task: Task) -> str:
        """从文案中提取封面总结"""
        import re
        import json

        # 使用正确的属性名 script_text
        script_text = getattr(task, 'script_text', '') or getattr(task, 'script', '')

        logger.info(f"提取封面总结 - script_text 长度: {len(script_text) if script_text else 0}")
        if script_text:
            logger.info(f"script_text 前 200 字符: {script_text[:200]}...")

        if not script_text:
            logger.warning("script_text 为空，返回默认值 '视频封面'")
            return "视频封面"

        try:
            parsed = json.loads(script_text)
            if isinstance(parsed, dict) and "封面总结" in parsed:
                result = str(parsed["封面总结"]).strip()
                logger.info(f"从 JSON 中提取到封面总结: {result}")
                return result
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"JSON 解析失败: {e}")

        match = re.search(r'封面总结[：:]\s*(.+?)(?:\n|$)', script_text)
        if match:
            result = match.group(1).strip()
            logger.info(f"通过正则匹配提取到封面总结: {result}")
            return result

        if task.segments and len(task.segments) > 0:
            first_segment = task.segments[0]
            if hasattr(first_segment, 'text') and first_segment.text:
                result = first_segment.text[:50]
                logger.info(f"从 segments 提取封面总结: {result}")
                return result

        logger.warning("未能提取封面总结，返回默认值")
        return "视频封面"

    def _build_cover_prompt(self, cover_summary: str, config=None) -> str:
        """构建封面提示词（使用系统设置中的模版）"""
        template = self.cover_prompt_template
        prompt = template.replace("{summary}", cover_summary)
        return prompt

    async def _insert_cover_frames(self, video_path: str, cover_path: str, frame_count: int = 5) -> str:
        """
        在视频开头插入封面帧
        
        注意：
        - 封面生成固定出图尺寸：竖屏 768*1376 或 横屏 1376*768
        - 此方法会将封面图缩放到与视频一致的分辨率，不改变视频尺寸
        """
        try:
            logger.info(f"开始插入封面帧：{cover_path} 到视频 {video_path}")

            if not os.path.exists(cover_path):
                logger.warning(f"封面图片不存在，跳过帧插入：{cover_path}")
                return video_path

            # 获取视频元数据（分辨率、帧率、音频参数）
            video_meta = await self._get_video_metadata(video_path)
            video_width = video_meta.get('width', 1920)
            video_height = video_meta.get('height', 1080)
            video_fps = video_meta.get('fps', 30.0)

            # 获取原视频的音频参数，确保封面视频的音频与之匹配
            audio_sample_rate = video_meta.get('sample_rate', 44100)
            audio_channels = video_meta.get('channels', 2)

            # 根据声道数生成对应的 channel_layout
            if audio_channels == 1:
                channel_layout = "mono"
            elif audio_channels == 2:
                channel_layout = "stereo"
            else:
                channel_layout = "stereo"  # 默认

            logger.info(f"视频分辨率：{video_width}x{video_height}, 帧率：{video_fps}fps, 音频：{audio_sample_rate}Hz/{channel_layout}")

            output_path = video_path.replace(".mp4", "_with_cover.mp4")

            cover_duration = frame_count / video_fps

            # 修复后的命令：
            # 使用 -t 控制封面输入时长，避免复杂的 trim 滤镜
            # 使用 concat 协议（非滤镜）更稳定
            # 方法：先创建封面视频文件，再用 concat demuxer 合并
            cover_video_path = video_path.replace(".mp4", "_cover_temp.mp4")

            # 步骤1: 将封面图片转换为短视频（含静音音频轨道，确保 concat 时流结构一致）
            cmd_cover = [
                FFMPEG_PATH,
                "-loop", "1",
                "-i", cover_path,
                "-f", "lavfi", "-i", f"anullsrc=channel_layout={channel_layout}:sample_rate={audio_sample_rate}",
                "-t", str(cover_duration),
                "-vf", f"scale={video_width}:{video_height}:force_original_aspect_ratio=decrease,pad={video_width}:{video_height}:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", str(video_fps),
                "-c:a", "aac",
                "-b:a", "192k",
                cover_video_path
            ]

            logger.info(f"封面转视频命令：{' '.join(cmd_cover)}")
            stdout = b''
            stderr = b''
            try:
                await async_run_ffmpeg(cmd_cover, check=True)
                logger.info(f"封面转视频成功：{cover_video_path}")
            except Exception as e:
                stderr_text = stderr.decode('utf-8', errors='replace') if stderr else '(无 stderr)'
                logger.error(f"封面转视频失败：{stderr_text}")
                return video_path

            # 步骤2: 使用 concat demuxer 合并视频
            concat_list_path = video_path.replace(".mp4", "_concat.txt")
            with open(concat_list_path, 'w', encoding='utf-8') as f:
                f.write(f"file '{cover_video_path}'\n")
                f.write(f"file '{video_path}'\n")

            cmd_concat = [
                FFMPEG_PATH,
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-c:v", "libx264",
                "-crf", "18",
                "-preset", "medium",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                output_path
            ]

            logger.info(f"视频合并命令：{' '.join(cmd_concat)}")
            try:
                returncode, stdout, stderr = await async_run_ffmpeg(cmd_concat, check=True)
                logger.info(f"封面帧插入成功 (已缩放到{video_width}x{video_height})")
            except Exception as e:
                stderr_text = stderr.decode('utf-8', errors='replace') if stderr else '(无 stderr)'
                logger.error(f"视频合并失败：{e}, stderr: {stderr_text}")
                return video_path
            finally:
                # 清理临时文件
                if os.path.exists(cover_video_path):
                    os.remove(cover_video_path)
                if os.path.exists(concat_list_path):
                    os.remove(concat_list_path)

            # 替换原视频
            if os.path.exists(output_path):
                os.replace(output_path, video_path)

            return video_path

        except Exception as e:
            logger.error(f"插入封面帧失败：{e}")
            return video_path
    
    def _should_use_precise_subtitle(self) -> bool:
        """
        判断是否应该使用精准字幕

        检查系统配置中的 enable_precise_subtitle 设置
        同时检查 ultra_low_memory 模式是否关闭（精准字幕需要较多显存）

        Returns:
            bool: 是否使用精准字幕
        """
        try:
            from core.system_config import get_config_manager
            config_manager = get_config_manager()

            # 检查超低显存模式
            ultra_low_memory = config_manager.get_ultra_low_memory()
            if ultra_low_memory:
                logger.info("超低显存模式开启，无法使用精准字幕")
                return False

            # 检查精准字幕开关
            enable_precise_subtitle = config_manager.get_enable_precise_subtitle()
            if enable_precise_subtitle:
                logger.info("精准字幕功能已启用")
                return True

            logger.info("精准字幕功能未启用，使用默认字幕")
            return False

        except Exception as e:
            logger.error(f"检查精准字幕配置失败：{e}")
            return False

    async def _generate_precise_subtitle(
        self,
        video_path: str,
        segments_text: List[str],
        output_srt_path: str
    ) -> Optional[str]:
        """
        使用 Qwen3-ForcedAligner 生成精准字幕

        Args:
            video_path: 视频路径
            segments_text: 分段文本列表
            output_srt_path: 输出 SRT 文件路径

        Returns:
            SRT 文件路径，失败返回 None
        """
        try:
            from business.postprocess.precise_subtitle_generator import generate_precise_subtitle
            import os

            # 使用项目根目录的相对路径
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            model_path = os.path.join(project_root, "models", "Qwen3-ForcedAligner-0.6B")

            srt_path = await generate_precise_subtitle(
                video_path=video_path,
                segments_text=segments_text,
                output_srt_path=output_srt_path,
                model_path=model_path
            )

            return srt_path

        except Exception as e:
            logger.error(f"精准字幕生成失败：{e}")
            return None

    def _generate_default_subtitle(
        self,
        segments_text: List[str],
        segment_durations: List[float],
        segment_offsets: List[float],
        output_srt_path: str,
        task: Task
    ) -> Optional[str]:
        """
        使用 UnifiedSubtitleSynchronizer 生成默认字幕

        Args:
            segments_text: 分段文本列表
            segment_durations: 分段时长列表
            segment_offsets: 分段偏移列表
            output_srt_path: 输出 SRT 文件路径
            task: 任务对象

        Returns:
            SRT 文件路径，失败返回 None
        """
        try:
            # 使用统一精确字幕同步器
            from business.postprocess.unified_subtitle_synchronizer import UnifiedSubtitleSynchronizer

            synchronizer = UnifiedSubtitleSynchronizer(
                padding_ms=100,      # 字幕提前 100ms 显示
                buffer_ms=100,      # 段落末尾缓冲
                overlap_ms=20,      # 字幕重叠，避免闪烁
            )

            success = synchronizer.synchronize(
                segments_text=segments_text,
                segment_durations=segment_durations,
                segment_offsets=segment_offsets,
                output_srt_path=output_srt_path,
            )

            if not success:
                logger.warning("精确字幕同步失败，使用备用方法")
                # 备用方法：基于时长分配
                return self._generate_subtitle_fallback(
                    segments_text=segments_text,
                    segment_durations=segment_durations,
                    segment_offsets=segment_offsets,
                    output_srt_path=output_srt_path,
                    task=task
                )

            return output_srt_path

        except Exception as e:
            logger.error(f"默认字幕生成失败：{e}")
            return None

    def _generate_subtitle_fallback(
        self,
        segments_text: List[str],
        segment_durations: List[float],
        segment_offsets: List[float],
        output_srt_path: str,
        task: Task
    ) -> Optional[str]:
        """
        备用字幕生成方法（基于时长分配）

        Args:
            segments_text: 分段文本列表
            segment_durations: 分段时长列表
            segment_offsets: 分段偏移列表
            output_srt_path: 输出 SRT 文件路径
            task: 任务对象

        Returns:
            SRT 文件路径
        """
        # 备用方法
        subtitle_index = 1
        accumulated_time = 0.0

        with open(output_srt_path, 'w', encoding='utf-8') as f:
            for segment in task.segments:
                if not segment.text:
                    continue

                segment_duration = getattr(segment, 'duration', 0.0)
                if segment_duration <= 0:
                    segment_duration = 2.0

                sentences = self._split_text_to_sentences(segment.text)

                if not sentences:
                    continue

                num_sentences = len(sentences)
                total_chars = sum(len(s) for s in sentences)

                available_duration = segment_duration * 0.95

                for sentence in sentences:
                    if total_chars > 0:
                        sentence_duration = available_duration * (len(sentence) / total_chars)
                    else:
                        sentence_duration = available_duration / num_sentences

                    if sentence_duration < 0.8:
                        sentence_duration = 0.8

                    start_time = accumulated_time - 0.08
                    if start_time < 0:
                        start_time = 0.0
                    end_time = accumulated_time + sentence_duration

                    f.write(f"{subtitle_index}\n")
                    f.write(f"{self._format_srt_time(start_time)} --> {self._format_srt_time(end_time)}\n")
                    f.write(f"{sentence}\n\n")

                    subtitle_index += 1
                    accumulated_time += sentence_duration

        return output_srt_path


def create_post_processor(
    intermediate_dir: str = "backend/output",
    output_dir: str = "output",
    **kwargs
) -> PostProcessor:
    """创建后期处理器的便捷函数

    Args:
        intermediate_dir: 中间处理目录（字幕、BGM、合并等中间文件存放处）
        output_dir: 最终输出目录（只有完成全部后期处理的视频才存放此处）
    """
    return PostProcessor(
        intermediate_dir=intermediate_dir,
        output_dir=output_dir
    )