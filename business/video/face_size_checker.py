"""
人脸区域大小快速检测模块

用于在视频生成前快速检测人脸区域大小，仅分析一帧来决定是否启用 HeyGem 超分
"""

import os
import cv2
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def quick_check_face_size(video_path: str, sample_frame: int = 0) -> int:
    """
    快速检测视频中的人脸区域大小（仅分析一帧）

    Args:
        video_path: 视频路径
        sample_frame: 采样帧索引（默认0，即首帧）

    Returns:
        最大人脸尺寸（宽或高的较大值），0表示无人脸或读取失败
    """
    if not os.path.exists(video_path):
        logger.warning(f"视频文件不存在: {video_path}")
        return 0

    try:
        # 使用 OpenCV 读取指定帧
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.warning(f"无法打开视频: {video_path}")
            return 0

        # 设置采样帧位置
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if sample_frame >= total_frames:
            sample_frame = 0  # 如果指定的帧超出范围，使用首帧

        cap.set(cv2.CAP_PROP_POS_FRAMES, sample_frame)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            logger.warning(f"无法读取视频帧: {video_path}")
            return 0

        # 转换为灰度图进行人脸检测
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 使用 Haar Cascade 检测人脸
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

        if face_cascade.empty():
            logger.warning("人脸检测器加载失败，无法检测人脸")
            return 0

        # 检测人脸
        faces = face_cascade.detectMultiScale(
            gray, 1.1, 4, minSize=(80, 80)
        )

        if len(faces) == 0:
            logger.info(f"视频 {video_path} 无人脸，sample_frame={sample_frame}")
            return 0

        # 返回最大人脸的尺寸（宽或高的较大值）
        max_size = 0
        for (x, y, w, h) in faces:
            size = max(w, h)
            if size > max_size:
                max_size = size

        logger.info(f"视频 {video_path} 最大人脸区域: {max_size}px")
        return max_size

    except Exception as e:
        logger.error(f"人脸区域检测失败: {e}")
        return 0


def should_enable_chaofen(video_path: str, min_face_size: int = 384) -> int:
    """
    判断视频是否需要启用超分

    Args:
        video_path: 视频路径
        min_face_size: 最小人脸尺寸阈值（默认384像素）

    Returns:
        1 表示启用超分，0 表示不启用
    """
    face_size = quick_check_face_size(video_path)

    if face_size == 0:
        logger.info(f"视频 {video_path} 无人脸，不启用超分")
        return 0
    elif face_size <= min_face_size:
        logger.info(f"视频 {video_path} 人脸区域过小({face_size}px)，不启用超分")
        return 0
    else:
        logger.info(f"视频 {video_path} 人脸区域({face_size}px)，启用超分")
        return 1