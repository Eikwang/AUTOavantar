"""
智能裁剪服务
提供视频上传、识别、分割、合成等功能
"""

import os
import sys
import json
import logging
import platform
import shutil
import base64
import asyncio
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
import uuid

import cv2
import numpy as np

from api.utils.async_subprocess import async_run_subprocess, async_run_ffprobe, async_run_ffmpeg

# 添加 models 目录到路径
models_path = Path(__file__).resolve().parent.parent.parent.parent / "models" / "TransNetV2"
if models_path.exists():
    sys.path.insert(0, str(models_path))

logger = logging.getLogger("autoavantar-api.smart_cut_service")


class SmartCutService:
    """智能裁剪服务"""

    # 支持的视频格式
    SUPPORTED_FORMATS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv'}

    # 最大文件大小（2GB）
    MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024

    def __init__(self, base_dir: str = None):
        """
        初始化服务

        Args:
            base_dir: 基础目录，默认为 backend 目录
        """
        if base_dir is None:
            # 默认使用 backend 目录
            self.base_dir = Path(__file__).resolve().parent.parent.parent
        else:
            self.base_dir = Path(base_dir)

        # 临时目录
        self.temp_dir = self.base_dir / "temp" / "smart_cut"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"SmartCutService 初始化完成，临时目录: {self.temp_dir}")

    def _generate_video_id(self) -> str:
        """生成视频ID"""
        return f"tmp_{uuid.uuid4().hex[:12]}"

    def _get_video_temp_dir(self, video_id: str) -> Path:
        """获取视频临时目录"""
        return self.temp_dir / video_id

    def _validate_video_format(self, filename: str) -> bool:
        """验证视频格式"""
        ext = os.path.splitext(filename)[1].lower()
        return ext in self.SUPPORTED_FORMATS

    async def _get_video_info(self, video_path: str) -> Dict[str, Any]:
        """
        使用 ffprobe 获取视频信息（异步，不阻塞事件循环）

        Args:
            video_path: 视频文件路径

        Returns:
            包含 duration, fps, width, height, total_frames 的字典
        """
        try:
            data = await async_run_ffprobe(
                video_path,
                entries="stream=width,height,r_frame_rate,duration,nb_frames,format=duration",
                output_format="json"
            )

            if not data:
                return {}

            # 提取流信息
            stream = data.get("streams", [{}])[0] if data.get("streams") else {}
            format_info = data.get("format", {})

            # 解析帧率
            fps_str = stream.get("r_frame_rate", "30/1")
            if "/" in fps_str:
                num, den = fps_str.split("/")
                fps = float(num) / float(den) if float(den) > 0 else 30.0
            else:
                fps = float(fps_str)

            # 解析时长
            duration = float(stream.get("duration") or format_info.get("duration", 0))

            # 解析总帧数
            nb_frames = stream.get("nb_frames")
            if nb_frames:
                total_frames = int(nb_frames)
            else:
                total_frames = int(duration * fps) if duration > 0 and fps > 0 else 0

            return {
                "width": int(stream.get("width", 0)),
                "height": int(stream.get("height", 0)),
                "fps": round(fps, 2),
                "duration": round(duration, 2),
                "total_frames": total_frames
            }

        except Exception as e:
            logger.error(f"获取视频信息失败: {e}")
            return {}

    async def _generate_thumbnail(self, video_path: str, output_path: str, time_offset: float = 0) -> bool:
        """
        生成视频缩略图（异步，不阻塞事件循环）

        Args:
            video_path: 视频文件路径
            output_path: 输出图片路径
            time_offset: 时间偏移（秒），默认取第一帧

        Returns:
            是否成功
        """
        def _sync_generate():
            try:
                cap = cv2.VideoCapture(video_path)
                if not cap.isOpened():
                    return False

                if time_offset > 0:
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_number = int(time_offset * fps)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

                ret, frame = cap.read()
                cap.release()

                if not ret or frame is None:
                    return False

                max_width = 320
                if frame.shape[1] > max_width:
                    scale = max_width / frame.shape[1]
                    frame = cv2.resize(frame, None, fx=scale, fy=scale)

                cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return True
            except Exception:
                return False

        result = await asyncio.to_thread(_sync_generate)
        if result:
            logger.info(f"缩略图生成成功: {output_path}")
        else:
            logger.error(f"生成缩略图失败: {video_path}")
        return result

    async def _generate_thumbnail_base64(self, video_path: str, time_offset: float = 0) -> Optional[str]:
        """
        生成视频缩略图的 base64 编码（异步，不阻塞事件循环）

        Args:
            video_path: 视频文件路径
            time_offset: 时间偏移（秒）

        Returns:
            base64 编码的图片（data:image/jpeg;base64,...）
        """
        def _sync_generate():
            try:
                cap = cv2.VideoCapture(video_path)
                if not cap.isOpened():
                    return None

                if time_offset > 0:
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_number = int(time_offset * fps)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

                ret, frame = cap.read()
                cap.release()

                if not ret or frame is None:
                    return None

                max_width = 320
                if frame.shape[1] > max_width:
                    scale = max_width / frame.shape[1]
                    frame = cv2.resize(frame, None, fx=scale, fy=scale)

                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_base64 = base64.b64encode(buffer).decode('utf-8')
                return f"data:image/jpeg;base64,{frame_base64}"
            except Exception:
                return None

        result = await asyncio.to_thread(_sync_generate)
        if result is None:
            logger.error(f"生成缩略图 base64 失败: {video_path}")
        return result

    async def upload_video(
        self,
        file_content: bytes,
        filename: str,
        content_type: str = None
    ) -> Dict[str, Any]:
        """
        上传视频文件

        Args:
            file_content: 文件内容
            filename: 文件名
            content_type: 内容类型

        Returns:
            包含视频信息的字典

        Raises:
            ValueError: 格式不支持或文件过大
        """
        # 1. 验证格式
        if not self._validate_video_format(filename):
            raise ValueError(f"不支持的视频格式，请上传 mp4/avi/mov 文件")

        # 2. 验证大小
        file_size = len(file_content)
        if file_size > self.MAX_FILE_SIZE:
            raise ValueError(f"视频文件过大，请上传小于 2GB 的文件")

        # 3. 生成视频ID和临时目录
        video_id = self._generate_video_id()
        video_temp_dir = self._get_video_temp_dir(video_id)
        video_temp_dir.mkdir(parents=True, exist_ok=True)

        # 4. 保存视频文件
        video_path = video_temp_dir / "video.mp4"
        with open(video_path, "wb") as f:
            f.write(file_content)

        logger.info(f"视频保存成功: {video_path}")

        # 5. 获取视频信息
        try:
            video_info = await self._get_video_info(str(video_path))
        except Exception as e:
            # 清理临时文件
            await asyncio.to_thread(shutil.rmtree, video_temp_dir, ignore_errors=True)
            raise ValueError(f"视频文件损坏或无法读取")

        if not video_info.get("duration"):
            await asyncio.to_thread(shutil.rmtree, video_temp_dir, ignore_errors=True)
            raise ValueError(f"视频文件损坏或无法读取")

        # 6. 生成缩略图（保存为文件，DB 存路径而非 base64）
        thumbnail_base64 = await self._generate_thumbnail_base64(str(video_path))
        thumbnail_path = video_temp_dir / "thumb.jpg"
        thumbnail_relative = ""
        if thumbnail_base64:
            try:
                # 从 base64 解码保存为文件
                b64_data = re.sub(r'^data:image/\w+;base64,', '', thumbnail_base64)
                with open(thumbnail_path, "wb") as f:
                    f.write(base64.b64decode(b64_data))
                thumbnail_relative = str(thumbnail_path.relative_to(self.base_dir)).replace("\\", "/")
            except Exception as e:
                logger.warning(f"缩略图文件保存失败: {e}")

        # 7. 上传即保存历史记录
        try:
            from api.services.database import get_database_service
            db = get_database_service()
            relative_path = str(video_path.relative_to(self.base_dir)).replace("\\", "/")
            await db.smart_cut_task_create(
                task_id=video_id,
                video_path=relative_path,
                video_name=filename,
                video_duration=video_info.get("duration", 0),
                video_fps=video_info.get("fps", 0),
                video_width=video_info.get("width", 0),
                video_height=video_info.get("height", 0),
                total_frames=video_info.get("total_frames", 0),
                status="uploaded",
                thumbnail=thumbnail_relative
            )
            logger.info(f"上传视频历史记录已保存: {video_id}")
        except Exception as e:
            logger.warning(f"保存上传历史记录失败（不影响上传功能）: {e}")

        # 8. 返回结果
        return {
            "video_id": video_id,
            "video_path": str(video_path.relative_to(self.base_dir)).replace("\\", "/"),
            "video_name": filename,
            "duration": video_info.get("duration", 0),
            "fps": video_info.get("fps", 0),
            "width": video_info.get("width", 0),
            "height": video_info.get("height", 0),
            "total_frames": video_info.get("total_frames", 0),
            "thumbnail": thumbnail_base64 or "",
            "thumbnail_path": thumbnail_relative
        }

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务状态信息
        """
        from api.services.database import get_database_service

        db = get_database_service()
        task = await db.smart_cut_task_get_by_id(task_id)

        if not task:
            return None

        # 解析 config 和 segments_info
        config = json.loads(task.get("config") or "{}")
        segments_info = json.loads(task.get("segments_info") or "null")

        return {
            "task_id": task["task_id"],
            "status": task["status"],
            "progress": task["progress"],
            "current_stage": task["current_stage"] or "",
            "video_name": task["video_name"] or "",
            "total_frames": task["total_frames"] or 0,
            "processed_frames": int((task["progress"] or 0) / 100 * (task["total_frames"] or 0)),
            "config": config,
            "segments": segments_info,
            "created_at": task["created_at"],
            "updated_at": task["updated_at"]
        }

    async def get_segments(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取片段列表

        Args:
            task_id: 任务ID

        Returns:
            片段列表信息
        """
        from api.services.database import get_database_service

        db = get_database_service()
        task = await db.smart_cut_task_get_by_id(task_id)

        if not task:
            return None

        segments_info = json.loads(task.get("segments_info") or "null")
        # 规范化所有路径
        normalized_segments = []
        if segments_info:
            for seg in segments_info:
                normalized_seg = {
                    **seg,
                    "thumbnail": seg.get("thumbnail", "").replace("\\", "/") if seg.get("thumbnail") else "",
                    "video_path": seg.get("video_path", "").replace("\\", "/") if seg.get("video_path") else ""
                }
                normalized_segments.append(normalized_seg)

        return {
            "task_id": task_id,
            "video_path": task["video_path"].replace("\\", "/") if task.get("video_path") else "",
            "segments": normalized_segments or []
        }

    async def get_history(self) -> List[Dict[str, Any]]:
        """获取智能裁剪历史记录（包括已上传未裁剪的记录）"""
        from api.services.database import get_database_service

        db = get_database_service()
        # 获取所有状态的任务记录（不限制数量）
        tasks, _ = await db.smart_cut_task_list(limit=10000)

        history_list = []
        for task in tasks:
            segments_info = json.loads(task.get("segments_info") or "[]")
            # thumbnail: 文件路径（兼容旧 base64 数据，不再返回 base64 避免响应膨胀）
            thumbnail = task.get("thumbnail", "")
            if thumbnail and thumbnail.startswith("data:"):
                thumbnail = ""
            thumbnail = thumbnail.replace("\\", "/") if thumbnail else ""
            history_list.append({
                "task_id": task["task_id"],
                "video_path": task.get("video_path", "").replace("\\", "/"),
                "video_name": task["video_name"] or "未命名视频",
                "video_duration": task["video_duration"] or 0,
                "video_fps": task["video_fps"] or 0,
                "video_width": task["video_width"] or 0,
                "video_height": task["video_height"] or 0,
                "total_frames": task["total_frames"] or 0,
                "segments_count": len(segments_info),
                "segments_info": [
                    {**seg, "thumbnail": seg.get("thumbnail", "").replace("\\", "/") if seg.get("thumbnail") else "",
                     "video_path": seg.get("video_path", "").replace("\\", "/") if seg.get("video_path") else ""}
                    for seg in segments_info
                ],
                "thumbnail": thumbnail,
                "created_at": task["created_at"],
                "status": task["status"]
            })

        # 按创建时间倒序
        history_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return history_list

    async def delete_task(self, task_id: str) -> bool:
        """
        删除任务及所有相关文件

        Args:
            task_id: 任务ID

        Returns:
            是否删除成功
        """
        from api.services.database import get_database_service

        db = get_database_service()
        task = await db.smart_cut_task_get_by_id(task_id)

        if not task:
            return False

        # 删除数据库记录
        deleted = await db.smart_cut_task_delete(task_id)
        if not deleted:
            return False

        # 删除原视频临时目录
        video_path = task.get("video_path", "")
        if video_path:
            # 从 video_path 提取 video_id
            # video_path 格式: temp/smart_cut/tmp_xxx/video.mp4
            parts = Path(video_path).parts
            if len(parts) >= 3 and parts[0] == "temp" and parts[1] == "smart_cut":
                video_id = parts[2]
                temp_dir = self.temp_dir / video_id
                if temp_dir.exists():
                    await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True)
                    logger.info(f"已删除临时目录: {temp_dir}")

        # 删除片段临时目录（task_id 对应的整个目录）
        task_temp_dir = self.temp_dir / task_id
        if task_temp_dir.exists():
            await asyncio.to_thread(shutil.rmtree, task_temp_dir, ignore_errors=True)
            logger.info(f"已删除片段临时目录: {task_temp_dir}")

        # 删除片段视频和缩略图（处理不在临时目录内的片段）
        try:
            segments_info = json.loads(task.get("segments_info") or "[]")
            deleted_dirs = set()
            for segment in segments_info:
                segment_path = segment.get("video_path", "")
                thumbnail_path = segment.get("thumbnail", "")

                # 删除片段视频
                if segment_path:
                    full_path = self.base_dir / segment_path if not Path(segment_path).is_absolute() else Path(segment_path)
                    if full_path.exists():
                        full_path.unlink()
                        logger.info(f"已删除片段视频: {segment_path}")
                        deleted_dirs.add(full_path.parent)

                # 删除缩略图
                if thumbnail_path:
                    full_path = self.base_dir / thumbnail_path if not Path(thumbnail_path).is_absolute() else Path(thumbnail_path)
                    if full_path.exists():
                        full_path.unlink()
                        logger.info(f"已删除缩略图: {thumbnail_path}")
                        deleted_dirs.add(full_path.parent)

            # 清理空目录
            for dir_path in deleted_dirs:
                try:
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        # 继续向上清理空目录
                        parent = dir_path.parent
                        while parent != self.base_dir and parent.exists() and not any(parent.iterdir()):
                            parent.rmdir()
                            parent = parent.parent
                except OSError:
                    pass
        except Exception as e:
            logger.error(f"删除片段文件时出错: {e}")

        logger.info(f"任务 {task_id} 及其所有文件已删除")
        return True

    async def cleanup_temp_files(self, max_age_hours: int = 24):
        """清理过期的临时文件，但保留有数据库记录的目录"""
        import time

        # 获取所有有数据库记录的video_id
        active_video_ids = set()
        try:
            from api.services.database import get_database_service
            db = get_database_service()
            tasks, _ = await db.smart_cut_task_list(limit=10000)
            for task in tasks:
                # task_id 本身可能是 video_id（uploaded状态）
                active_video_ids.add(task["task_id"])
                # 从 video_path 提取 video_id（目录名）
                video_path = task.get("video_path", "")
                parts = Path(video_path).parts
                if len(parts) >= 3 and parts[0] == "temp" and parts[1] == "smart_cut":
                    active_video_ids.add(parts[2])
        except Exception as e:
            logger.warning(f"获取活跃任务列表失败: {e}")

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        for item in self.temp_dir.iterdir():
            if item.is_dir():
                # 跳过有数据库记录的目录
                if item.name in active_video_ids:
                    continue
                # 检查目录修改时间
                dir_mtime = item.stat().st_mtime
                if current_time - dir_mtime > max_age_seconds:
                    await asyncio.to_thread(shutil.rmtree, item, ignore_errors=True)
                    logger.info(f"已清理过期临时目录: {item}")

    async def execute_smart_cut(
        self,
        task_id: str,
        video_path: str,
        config: Dict[str, Any],
        progress_callback: Callable[[int, str, int, int], None] = None
    ) -> List[Dict[str, Any]]:
        """
        执行智能裁剪

        Args:
            task_id: 任务ID
            video_path: 视频文件路径
            config: 配置参数
                - min_segment_duration: 最短片段时长（秒）
                - enable_brightness: 是否启用亮度检测
                - enable_pose: 是否启用姿态检测
                - enable_motion: 是否启用动作检测
                - enable_silence: 是否启用静音检测
            progress_callback: 进度回调函数 (progress, stage, processed_frames, total_frames)

        Returns:
            片段列表
        """
        from api.services.database import get_database_service
        from api.routers.websocket import manager as ws_manager

        # 获取视频信息
        full_video_path = self.base_dir / video_path
        video_info = await self._get_video_info(str(full_video_path))

        if not video_info.get("duration"):
            raise ValueError("无法获取视频信息")

        fps = video_info.get("fps", 30)
        total_frames = video_info.get("total_frames", 0)
        min_segment_duration = config.get("min_segment_duration", 10)
        min_segment_frames = int(min_segment_duration * fps)

        # 更新任务状态
        db = get_database_service()
        await db.smart_cut_task_update(task_id, {
            "status": "processing",
            "current_stage": "初始化识别引擎"
        })

        try:
            # 导入 SmartVideoSegmenter
            try:
                from smart_segmenter import SmartVideoSegmenter
            except ImportError:
                # 尝试从 models 目录导入
                sys.path.insert(0, str(models_path))
                from smart_segmenter import SmartVideoSegmenter

            # 等待 WebSocket 连接建立（最多等待 3 秒）
            logger.info(f"等待 WebSocket 连接: {task_id}")
            connected = await ws_manager.wait_for_connection(task_id, timeout=3.0)
            if connected:
                logger.info(f"WebSocket 连接已建立: {task_id}")
            else:
                logger.warning(f"WebSocket 连接超时，继续执行任务: {task_id}")

            # 获取事件循环引用（用于在线程中调度回调）
            loop = asyncio.get_running_loop()

            # 创建分割器实例
            async def update_progress(progress: int, stage: str, processed: int, total: int):
                if progress_callback:
                    progress_callback(progress, stage, processed, total)
                # 更新数据库
                await self._update_task_progress(task_id, progress, stage, processed, total)
                # 推送 WebSocket 进度
                await ws_manager.broadcast_to_task(task_id, {
                    "type": "smart_cut_progress",
                    "task_id": task_id,
                    "progress": progress,
                    "current_stage": stage,
                    "processed_frames": processed,
                    "total_frames": total,
                    "timestamp": datetime.now().isoformat()
                })

            # 同步包装器，用于在 executor 中调用 async 回调
            def sync_progress_callback(progress: int, stage: str, processed: int, total: int):
                """同步进度回调，将 async 回调调度到主事件循环"""
                try:
                    # 使用 run_coroutine_threadsafe 从线程中调度 async 函数
                    future = asyncio.run_coroutine_threadsafe(
                        update_progress(progress, stage, processed, total),
                        loop
                    )
                    # 不等待结果，避免阻塞
                except Exception as e:
                    logger.warning(f"进度回调调度失败: {e}")

            # 初始化分割器
            await update_progress(5, "加载识别模型", 0, total_frames)

            segmenter = SmartVideoSegmenter(
                use_audio=config.get("enable_silence", False),
                use_motion=config.get("enable_motion", False),
                use_brightness=config.get("enable_brightness", False),
                use_pose=config.get("enable_pose", False),
                min_segment_frames=min_segment_frames,
                progress_callback=sync_progress_callback  # 传入同步回调
            )

            await update_progress(10, "开始智能识别", 0, total_frames)

            # 执行分割（在线程池中运行以避免阻塞）
            segments = await loop.run_in_executor(
                None,
                lambda: segmenter.segment_video(str(full_video_path))
            )

            # 过滤短片段（小于最小片段帧数）
            # 注意：default 片段是检测完成后的剩余部分，不过滤
            filtered_count = len(segments)
            if min_segment_frames > 0:
                original_count = len(segments)
                segments = [s for s in segments if s[2] == 'default' or (s[1] - s[0]) >= min_segment_frames]
                filtered_count = len(segments)
                logger.info(f"片段过滤：{original_count} -> {filtered_count}（最小帧数：{min_segment_frames}，保留 default 片段）")

            # 报告过滤后的片段数量
            await update_progress(80, f"分割完成，共 {filtered_count} 个片段", total_frames, total_frames)

            # 生成片段视频和缩略图
            segment_list = await self._generate_segment_files(
                task_id=task_id,
                video_path=str(full_video_path),
                segments=segments,
                fps=fps,
                progress_callback=update_progress
            )

            await update_progress(100, "识别完成", total_frames, total_frames)

            # 更新任务状态
            await db.smart_cut_task_update(task_id, {
                "status": "completed",
                "progress": 100,
                "current_stage": "识别完成",
                "segments_info": json.dumps(segment_list)
            })

            # 推送完成事件
            await ws_manager.broadcast_to_task(task_id, {
                "type": "smart_cut_completed",
                "task_id": task_id,
                "segments_count": len(segment_list),
                "segments": segment_list,
                "timestamp": datetime.now().isoformat()
            })

            logger.info(f"智能裁剪完成: {task_id}, 共 {len(segment_list)} 个片段")
            return segment_list

        except Exception as e:
            logger.error(f"智能裁剪失败: {e}")
            await db.smart_cut_task_update(task_id, {
                "status": "failed",
                "error_message": str(e)
            })

            # 推送失败事件
            try:
                from api.routers.websocket import manager as ws_manager
                await ws_manager.broadcast_to_task(task_id, {
                    "type": "smart_cut_failed",
                    "task_id": task_id,
                    "error_message": str(e),
                    "timestamp": datetime.now().isoformat()
                })
            except Exception:
                pass

            raise

    async def _update_task_progress(
        self,
        task_id: str,
        progress: int,
        stage: str,
        processed_frames: int,
        total_frames: int
    ):
        """更新任务进度"""
        from api.services.database import get_database_service

        db = get_database_service()
        await db.smart_cut_task_update(task_id, {
            "progress": progress,
            "current_stage": stage
        })

    async def _generate_segment_files(
        self,
        task_id: str,
        video_path: str,
        segments: List[tuple],
        fps: float,
        progress_callback: Callable = None
    ) -> List[Dict[str, Any]]:
        """
        生成片段视频文件和缩略图

        Args:
            task_id: 任务ID
            video_path: 原视频路径
            segments: 片段列表 [(start_frame, end_frame, reason), ...]
            fps: 帧率
            progress_callback: 进度回调

        Returns:
            片段信息列表
        """
        segment_list = []

        # 创建片段输出目录
        video_id = task_id
        output_dir = self.temp_dir / video_id / "segments"
        output_dir.mkdir(parents=True, exist_ok=True)

        total_segments = len(segments)

        for i, (start_frame, end_frame, reason) in enumerate(segments):
            segment_id = f"seg_{i+1:04d}"
            segment_path = output_dir / f"{segment_id}.mp4"
            thumbnail_path = output_dir / f"{segment_id}_thumb.jpg"

            # 计算时间（确保转换为 Python 原生类型）
            start_frame = int(start_frame)  # 转换 numpy int32 为 Python int
            end_frame = int(end_frame)
            start_time = start_frame / fps
            end_time = end_frame / fps
            duration = end_time - start_time

            # 使用 FFmpeg 提取片段
            if await self._extract_segment(video_path, str(segment_path), start_time, duration):
                # 生成缩略图
                await self._generate_thumbnail(str(segment_path), str(thumbnail_path))

                # 生成分段原因标签
                reason_label = self._get_reason_label(reason)

                segment_list.append({
                    "segment_id": segment_id,
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "start_time": round(start_time, 2),
                    "end_time": round(end_time, 2),
                    "duration": round(duration, 2),
                    "reason": reason,
                    "reason_label": reason_label,
                    "thumbnail": str(thumbnail_path.relative_to(self.base_dir)).replace("\\", "/"),
                    "video_path": str(segment_path.relative_to(self.base_dir)).replace("\\", "/")
                })

            # 更新进度（progress_callback 是 async 函数，需要 await）
            if progress_callback:
                progress = 80 + int((i + 1) / total_segments * 15)
                await progress_callback(progress, f"生成片段 {i+1}/{total_segments}", 0, 0)

        return segment_list

    async def _extract_segment(
        self,
        video_path: str,
        output_path: str,
        start_time: float,
        duration: float
    ) -> bool:
        """
        使用 FFmpeg 提取视频片段

        Args:
            video_path: 原视频路径
            output_path: 输出路径
            start_time: 开始时间（秒）
            duration: 时长（秒）

        Returns:
            是否成功
        """
        try:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-i", video_path,
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "fast",
                "-c:a", "aac",
                "-avoid_negative_ts", "make_zero",
                output_path
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if returncode != 0:
                logger.error(f"FFmpeg 提取片段失败: {stderr.decode() if stderr else ''}")
                return False

            return True

        except Exception as e:
            logger.error(f"提取片段失败: {e}")
            return False

    def _get_reason_label(self, reason: str) -> str:
        """获取分割原因的中文标签"""
        reason_map = {
            "scene_change": "场景切换",
            "silence": "说话停顿",
            "motion": "手势变化",
            "brightness": "光线变化",
            "pose": "肢体动作",
            "default": "自动分割"
        }
        return reason_map.get(reason, "自动分割")

    async def extract_audio_from_segment(
        self,
        segment_path: str,
        name: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        从片段中提取音频

        Args:
            segment_path: 片段视频路径
            name: 音频名称

        Returns:
            包含 audio_path 和 duration 的字典
        """
        try:
            # 生成音频文件名
            segment_name = Path(segment_path).stem
            audio_name = name or f"{segment_name}_audio"
            audio_path = Path(segment_path).parent / f"{audio_name}.wav"

            # 使用 FFmpeg 提取音频
            cmd = [
                "ffmpeg", "-y",
                "-i", segment_path,
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "44100",
                "-ac", "2",
                str(audio_path)
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if returncode != 0:
                logger.error(f"FFmpeg 提取音频失败: {stderr.decode() if stderr else ''}")
                return None

            # 获取音频时长
            duration = await self._get_audio_duration(str(audio_path))

            logger.info(f"音频提取成功: {audio_path}")

            return {
                "audio_path": str(audio_path.relative_to(self.base_dir)).replace("\\", "/"),
                "duration": duration,
                "name": audio_name
            }

        except Exception as e:
            logger.error(f"提取音频失败: {e}")
            return None

    async def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长（异步，不阻塞事件循环）"""
        try:
            data = await async_run_ffprobe(audio_path, entries="format=duration")
            return float(data.get("format", {}).get("duration", 0))

        except Exception as e:
            logger.error(f"获取音频时长失败: {e}")
            return 0.0

    async def merge_segments(
        self,
        segments: List[Dict[str, str]],
        output_name: str = "",
        resolution: str = "1080p",
        fps: int = 30,
        transition: str = "none",
        bgm_path: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        合成视频片段

        Args:
            segments: 片段列表 [{"video_path": "...", "segment_id": "..."}, ...]
            output_name: 输出文件名
            resolution: 分辨率 (720p/1080p/2K)
            fps: 帧率 (30/60)
            transition: 转场效果 (none/fade/wipe)

        Returns:
            包含 output_path, duration, file_size 的字典
        """
        try:
            # 创建输出目录（项目根目录下的 output）
            output_dir = self.base_dir.parent / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            # 生成输出文件名（避免同名覆盖）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_name = output_name or f"merged_{timestamp}"
            output_path = output_dir / f"{output_name}.mp4"
            # 如果文件已存在，添加序号避免覆盖
            if output_path.exists():
                counter = 1
                while output_path.exists():
                    output_path = output_dir / f"{output_name}_{counter}.mp4"
                    counter += 1

            # 分辨率映射
            resolution_map = {
                "720p": (1280, 720),
                "1080p": (1920, 1080),
                "2K": (2560, 1440)
            }
            width, height = resolution_map.get(resolution, (1920, 1080))

            # 构建片段文件列表
            segment_files = []
            for seg in segments:
                video_path = self.base_dir / seg["video_path"]
                if video_path.exists():
                    segment_files.append(str(video_path))

            if not segment_files:
                logger.error("没有有效的片段文件")
                return None

            # 检测片段实际宽高比，竖屏片段自动翻转输出分辨率
            try:
                probe_data = await async_run_ffprobe(
                    segment_files[0],
                    entries="stream=width,height"
                )
                if probe_data:
                    streams = probe_data.get("streams", [])
                    if streams:
                        src_w = int(streams[0].get("width", 0))
                        src_h = int(streams[0].get("height", 0))
                        if src_h > src_w and width > height:
                            width, height = height, width
                            logger.info(f"检测到竖屏片段({src_w}x{src_h})，输出分辨率调整为 {width}x{height}")
            except Exception as e:
                logger.warning(f"检测片段分辨率失败: {e}")

            # 根据转场效果选择合成方式
            if transition != "none" and len(segment_files) > 1:
                # 使用 xfade 滤镜实现转场效果
                result = await self._merge_with_transition(
                    segment_files=segment_files,
                    output_path=str(output_path),
                    width=width,
                    height=height,
                    fps=fps,
                    transition=transition
                )
                if not result:
                    # 转场合成失败，回退到基础拼接
                    logger.warning("转场合成失败，回退到基础拼接")
                    transition = "none"

            if transition == "none" or len(segment_files) == 1:
                # 基础拼接（无转场）
                result = await self._merge_basic(
                    segment_files=segment_files,
                    output_path=str(output_path),
                    width=width,
                    height=height,
                    fps=fps
                )

            if not result:
                return None

            # 如果有BGM，混入音频
            if bgm_path:
                try:
                    resolved_bgm = Path(bgm_path)
                    if not resolved_bgm.is_absolute():
                        project_root = self.base_dir.parent
                        candidate = project_root / bgm_path
                        if candidate.exists():
                            resolved_bgm = candidate
                        else:
                            candidate2 = self.base_dir / bgm_path
                            if candidate2.exists():
                                resolved_bgm = candidate2

                    if resolved_bgm.exists():
                        # 先提取合成视频的音频
                        video_audio = output_path.with_suffix('.audio.wav')
                        cmd_audio = [
                            'ffmpeg', '-y', '-i', str(output_path),
                            '-vn', '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                            str(video_audio)
                        ]
                        audio_rc, audio_out, audio_err = await async_run_ffmpeg(cmd_audio, timeout=60)

                        if audio_rc == 0 and video_audio.exists():
                            # 混合BGM和原音频
                            mixed_audio = output_path.with_suffix('.mixed.wav')
                            cmd_mix = [
                                'ffmpeg', '-y',
                                '-i', str(video_audio),
                                '-i', str(resolved_bgm),
                                '-filter_complex',
                                '[0:a]volume=1.0[a0];[1:a]volume=0.3[a1];[a0][a1]amix=inputs=2:duration=longest[aout]',
                                '-map', '[aout]', '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                                str(mixed_audio)
                            ]
                            mix_rc, mix_out, mix_err = await async_run_ffmpeg(cmd_mix, timeout=60)

                            if mix_rc == 0 and mixed_audio.exists():
                                # 用混合音频替换原视频音频
                                final_output = output_path.with_name(output_path.stem + '_final.mp4')
                                cmd_replace = [
                                    'ffmpeg', '-y',
                                    '-i', str(output_path),
                                    '-i', str(mixed_audio),
                                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                                    '-map', '0:v', '-map', '1:a',
                                    '-shortest',
                                    str(final_output)
                                ]
                                replace_rc, replace_out, replace_err = await async_run_ffmpeg(cmd_replace, timeout=120)

                                if replace_rc == 0 and final_output.exists():
                                    output_path.unlink()
                                    final_output.rename(output_path)
                                    logger.info(f"BGM已混入合成视频: {output_path}")
                                else:
                                    logger.warning(f"替换音频失败: {replace_err.decode() if replace_err else ''}")
                            else:
                                logger.warning(f"混合音频失败: {mix_err.decode() if mix_err else ''}")

                            video_audio.unlink(missing_ok=True)
                            mixed_audio.unlink(missing_ok=True)
                        else:
                            # 视频无音频轨道，直接将BGM作为唯一音频添加
                            logger.info(f"视频无音频轨道，直接添加BGM作为音频")
                            final_output = output_path.with_name(output_path.stem + '_bgm.mp4')
                            cmd_add_bgm = [
                                'ffmpeg', '-y',
                                '-i', str(output_path),
                                '-i', str(resolved_bgm),
                                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                                '-map', '0:v', '-map', '1:a',
                                '-shortest',
                                str(final_output)
                            ]
                            add_bgm_rc, add_bgm_out, add_bgm_err = await async_run_ffmpeg(cmd_add_bgm, timeout=120)

                            if add_bgm_rc == 0 and final_output.exists():
                                output_path.unlink()
                                final_output.rename(output_path)
                                logger.info(f"BGM已作为唯一音频添加到合成视频: {output_path}")
                            else:
                                logger.warning(f"添加BGM失败: {add_bgm_err.decode() if add_bgm_err else ''}")
                    else:
                        logger.warning(f"BGM文件不存在: {bgm_path}")
                except Exception as e:
                    logger.error(f"混入BGM失败: {e}")

            # 获取输出文件信息
            file_size = output_path.stat().st_size
            duration = await self._get_video_duration(str(output_path))

            logger.info(f"视频合成成功: {output_path}")

            return {
                "output_path": str(output_path.relative_to(self.base_dir.parent)).replace("\\", "/"),
                "duration": duration,
                "file_size": file_size
            }

        except Exception as e:
            logger.error(f"合成视频失败: {e}")
            return None

    async def _merge_basic(
        self,
        segment_files: List[str],
        output_path: str,
        width: int,
        height: int,
        fps: int
    ) -> bool:
        """基础拼接（无转场效果）"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        concat_file = Path(output_path).parent / f"concat_{timestamp}.txt"

        try:
            with open(concat_file, "w") as f:
                for seg_path in segment_files:
                    f.write(f"file '{seg_path}'\n")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "-r", str(fps),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                output_path
            ]

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if returncode != 0:
                logger.error(f"FFmpeg 基础合成失败: {stderr.decode() if stderr else ''}")
                return False

            return True

        finally:
            concat_file.unlink(missing_ok=True)

    async def _merge_with_transition(
        self,
        segment_files: List[str],
        output_path: str,
        width: int,
        height: int,
        fps: int,
        transition: str
    ) -> bool:
        """使用 xfade 滤镜实现转场效果"""
        try:
            # 转场映射
            transition_map = {
                "fade": "fade",
                "wipe": "wipeleft"
            }
            xfade_transition = transition_map.get(transition, "fade")
            transition_duration = 1.0  # 转场时长 1 秒

            # 获取每个片段的时长
            durations = []
            for seg_file in segment_files:
                duration = await self._get_video_duration(seg_file)
                durations.append(duration)

            if len(durations) < 2:
                return False

            # 构建复杂滤镜链
            # 第一步：将所有视频缩放到统一分辨率
            inputs = []
            filter_parts = []

            for i, seg_file in enumerate(segment_files):
                inputs.extend(["-i", seg_file])
                # 缩放并设置帧率
                filter_parts.append(
                    f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                    f"fps={fps},setpts=PTS-STARTPTS[v{i}]"
                )

            # 第二步：使用 xfade 链接视频
            # 第一个转场
            offset = durations[0] - transition_duration
            filter_parts.append(f"[v0][v1]xfade=transition={xfade_transition}:duration={transition_duration}:offset={offset}[v01]")

            # 后续转场
            prev_output = "v01"
            for i in range(2, len(segment_files)):
                # 计算偏移量：前面所有视频的总时长减去已使用的转场时长
                offset = sum(durations[:i]) - transition_duration * i
                curr_output = f"v0{i}" if i < 10 else f"v{i}"
                filter_parts.append(
                    f"[{prev_output}][v{i}]xfade=transition={xfade_transition}:"
                    f"duration={transition_duration}:offset={offset}[{curr_output}]"
                )
                prev_output = curr_output

            # 最终输出标签
            final_output = prev_output

            # 构建完整命令
            cmd = ["ffmpeg", "-y"]
            cmd.extend(inputs)
            cmd.extend([
                "-filter_complex", ";".join(filter_parts),
                "-map", f"[{final_output}]",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                output_path
            ])

            returncode, stdout, stderr = await async_run_ffmpeg(cmd)

            if returncode != 0:
                logger.error(f"FFmpeg 转场合成失败: {stderr.decode() if stderr else ''}")
                return False

            return True

        except Exception as e:
            logger.error(f"转场合成异常: {e}")
            return False

    async def _get_video_duration(self, video_path: str) -> float:
        """获取视频时长（异步，不阻塞事件循环）"""
        try:
            data = await async_run_ffprobe(video_path, entries="format=duration")
            return float(data.get("format", {}).get("duration", 0))
        except Exception as e:
            logger.error(f"获取视频时长失败: {e}")
            return 0.0


# 全局服务实例
_smart_cut_service: Optional[SmartCutService] = None


def get_smart_cut_service() -> SmartCutService:
    """获取智能裁剪服务实例"""
    global _smart_cut_service
    if _smart_cut_service is None:
        _smart_cut_service = SmartCutService()
    return _smart_cut_service
