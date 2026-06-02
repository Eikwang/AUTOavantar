"""
智能视频分割器
结合 TransNetV2、音频检测、光流分析等多种方式
适用于口播视频、教学视频等场景
"""
import os
import sys
import numpy as np
import cv2
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

# 导入 TransNetV2
sys.path.insert(0, os.path.dirname(__file__))
from inference import TransNetV2Inference

# MediaPipe Pose 导入
MEDIAPIPE_AVAILABLE = False
try:
    from mediapipe.tasks.python import vision
    from mediapipe.tasks import python
    from mediapipe import Image as MPImage
    from mediapipe import ImageFormat
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    print("[PoseDetector] [!] MediaPipe 未安装，将使用简化检测")


@dataclass
class SegmentPoint:
    """分割点"""
    frame: int
    confidence: float
    reason: str  # 'scene_change', 'silence', 'motion', 'pose'
    metadata: Optional[Dict] = None


class PoseDetector:
    """
    完整的 MediaPipe 姿态检测器
    使用 pose_landmarker_full.task 模型进行 33 个关键点检测
    """
    
    # 关键点名称映射 (0-32)
    LANDMARK_NAMES = [
        "nose",
        "left_eye_inner", "left_eye", "left_eye_outer",
        "right_eye_inner", "right_eye", "right_eye_outer",
        "left_ear", "right_ear",
        "mouth_left", "mouth_right",
        "left_shoulder", "right_shoulder",
        "left_elbow", "right_elbow",
        "left_wrist", "right_wrist",
        "left_pinky", "right_pinky",
        "left_index", "right_index",
        "left_thumb", "right_thumb",
        "left_hip", "right_hip",
        "left_knee", "right_knee",
        "left_ankle", "right_ankle",
        "left_heel", "right_heel",
        "left_foot_index", "right_foot_index"
    ]
    
    def __init__(self, model_path: str = None, use_gpu: bool = True):
        """
        初始化姿态检测器
        
        Args:
            model_path: 模型文件路径，默认使用 models/pose_landmarker_full.task
            use_gpu: 是否使用 GPU 加速
        """
        self.detector = None
        
        # 如果未指定模型路径，使用默认路径
        if model_path is None:
            # smart_segmenter.py 在 models/TransNetV2/ 目录
            # pose_landmarker_full.task 在 models/ 目录
            self.model_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "pose_landmarker_full.task"
            )
        else:
            self.model_path = model_path
        
        self.use_gpu = use_gpu
        
        if MEDIAPIPE_AVAILABLE:
            self._init_detector()
    
    def _init_detector(self):
        """初始化 MediaPipe Pose Landmarker"""
        try:
            # 检查模型文件是否存在
            if not os.path.exists(self.model_path):
                raise FileNotFoundError(f"Pose Landmarker 模型文件不存在：{self.model_path}")
            
            print(f"[PoseDetector] 加载 MediaPipe Pose Landmarker 模型：{self.model_path}")
            print(f"[PoseDetector] 使用设备：{'GPU' if self.use_gpu else 'CPU'}")
            
            # MediaPipe 在 Windows 上的 GPU 支持有限
            # 尝试使用 GPU delegate，如果不可用则回退到 CPU
            if self.use_gpu:
                try:
                    # 尝试使用 GPU delegate（OpenGL/DirectX）
                    delegate = python.BaseOptions.Delegate.GPU
                    base_options = python.BaseOptions(
                        model_asset_path=self.model_path,
                        delegate=delegate
                    )
                    self.detector = vision.PoseLandmarker.create_from_options(
                        vision.PoseLandmarkerOptions(
                            base_options=base_options,
                            running_mode=vision.RunningMode.IMAGE,
                            num_poses=1,
                            min_pose_presence_confidence=0.5,
                            min_tracking_confidence=0.5
                        )
                    )
                    print(f"[PoseDetector] ✓ MediaPipe GPU 加速已启用 (GPU Delegate)")
                    return
                except Exception as gpu_error:
                    print(f"[PoseDetector] [!] GPU 加速不可用：{gpu_error}")
                    print(f"[PoseDetector] 回退到 CPU 模式")
            
            # 使用 CPU 模式（XNNPACK 加速）
            base_options = python.BaseOptions(
                model_asset_path=self.model_path,
                delegate=python.BaseOptions.Delegate.CPU
            )
            
            options = vision.PoseLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_presence_confidence=0.5,
                min_tracking_confidence=0.5
            )
            
            self.detector = vision.PoseLandmarker.create_from_options(options)
            print(f"[PoseDetector] ✓ MediaPipe Pose Landmarker 初始化成功 (CPU + XNNPACK 加速)")
            
        except Exception as e:
            print(f"[PoseDetector] ✗ 初始化失败：{e}")
            raise
    
    def detect_pose(self, frame) -> Optional[Dict]:
        """
        检测帧中的人体姿态关键点
        
        Args:
            frame: BGR 格式的图像帧
            
        Returns:
            pose_data: 包含关键点坐标的字典，如果未检测到则返回 None
        """
        if not MEDIAPIPE_AVAILABLE or self.detector is None:
            # 回退到简化检测
            return self._simple_detect(frame)
        
        try:
            # 转换为 RGB
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # 创建 MediaPipe 图像对象
            mp_image = MPImage(
                image_format=ImageFormat.SRGB,
                data=rgb_image
            )
            
            # 检测姿态
            detection_result = self.detector.detect(mp_image)
            
            # 解析结果
            if not detection_result.pose_landmarks or len(detection_result.pose_landmarks) == 0:
                return None
            
            # 提取关键点
            pose_landmarks = detection_result.pose_landmarks[0]
            pose_data = {}
            
            for idx, landmark in enumerate(pose_landmarks):
                landmark_name = self.LANDMARK_NAMES[idx] if idx < len(self.LANDMARK_NAMES) else f"point_{idx}"
                pose_data[landmark_name] = {
                    'x': landmark.x,
                    'y': landmark.y,
                    'z': landmark.z,
                    'visibility': landmark.visibility
                }
            
            # 添加置信度（从 landmarks 的 visibility 计算平均置信度）
            visibilities = [landmark.visibility for landmark in pose_landmarks if hasattr(landmark, 'visibility')]
            pose_data['confidence'] = sum(visibilities) / len(visibilities) if visibilities else 0.0
            
            return pose_data
            
        except Exception as e:
            print(f"[PoseDetector] ✗ 检测失败：{e}")
            return None
    
    def _simple_detect(self, frame) -> Optional[Dict]:
        """
        简化的姿态检测（当 MediaPipe 不可用时）
        
        Args:
            frame: BGR 图像
            
        Returns:
            center_region: 中心区域作为简化的"姿态"表示
        """
        h, w = frame.shape[:2]
        center_y, center_x = h // 2, w // 2
        region_size = min(h, w) // 4
        
        center_region = frame[
            center_y - region_size:center_y + region_size,
            center_x - region_size:center_x + region_size
        ]
        
        return {'center_region': center_region}
    
    def calculate_pose_distance(self, pose1: Optional[Dict], pose2: Optional[Dict]) -> float:
        """
        计算两个姿态之间的距离
        
        Args:
            pose1: 第一个姿态数据
            pose2: 第二个姿态数据
            
        Returns:
            distance: 距离值（0-1）
        """
        if pose1 is None or pose2 is None:
            return float('inf')
        
        # 如果使用 MediaPipe 检测
        if 'nose' in pose1 and 'nose' in pose2:
            return self._calculate_landmark_distance(pose1, pose2)
        
        # 简化检测
        if 'center_region' in pose1 and 'center_region' in pose2:
            return self._calculate_region_distance(pose1['center_region'], pose2['center_region'])
        
        return float('inf')
    
    def _calculate_landmark_distance(self, pose1: Dict, pose2: Dict) -> float:
        """
        计算 MediaPipe 关键点之间的距离
        
        Args:
            pose1: 第一个姿态
            pose2: 第二个姿态
            
        Returns:
            distance: 平均距离
        """
        # 使用关键关键点计算距离
        key_landmarks = ['nose', 'left_shoulder', 'right_shoulder', 'left_wrist', 'right_wrist']
        
        distances = []
        for landmark in key_landmarks:
            if landmark in pose1 and landmark in pose2:
                p1 = pose1[landmark]
                p2 = pose2[landmark]
                
                # 计算欧氏距离
                dist = np.sqrt((p1['x'] - p2['x'])**2 + (p1['y'] - p2['y'])**2)
                distances.append(dist)
        
        if distances:
            return np.mean(distances)
        return 0.0
    
    def _calculate_region_distance(self, region1: np.ndarray, region2: np.ndarray) -> float:
        """
        计算两个区域之间的差异（简化方法）
        
        Args:
            region1: 第一个区域
            region2: 第二个区域
            
        Returns:
            distance: 差异度
        """
        # 调整到相同大小
        region1 = cv2.resize(region1, (50, 50))
        region2 = cv2.resize(region2, (50, 50))
        
        # 转换为灰度
        gray1 = cv2.cvtColor(region1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(region2, cv2.COLOR_BGR2GRAY)
        
        # 计算差异
        diff = cv2.absdiff(gray1, gray2)
        distance = np.mean(diff) / 255.0  # 归一化到 0-1
        
        return distance
    
    def get_pose_angle(self, pose_data: Optional[Dict]) -> Optional[float]:
        """
        计算身体倾斜角度
        
        Args:
            pose_data: 姿态数据
            
        Returns:
            angle: 倾斜角度（度）
        """
        if pose_data is None or 'nose' not in pose_data:
            return None
        
        # 使用鼻子和肩膀计算角度
        if 'left_shoulder' in pose_data and 'right_shoulder' in pose_data:
            nose = pose_data['nose']
            left_shoulder = pose_data['left_shoulder']
            right_shoulder = pose_data['right_shoulder']
            
            # 计算肩膀中心
            shoulder_center_x = (left_shoulder['x'] + right_shoulder['x']) / 2
            shoulder_center_y = (left_shoulder['y'] + right_shoulder['y']) / 2
            
            # 计算角度
            dx = nose['x'] - shoulder_center_x
            dy = nose['y'] - shoulder_center_y
            
            if dx == 0:
                return 0.0
            
            angle = np.degrees(np.arctan(dy / dx))
            return abs(angle)
        
        return None
    
    def close(self):
        """释放资源"""
        if self.detector is not None:
            try:
                self.detector.close()
                print("[PoseDetector] ✓ MediaPipe 检测器已关闭")
            except Exception as e:
                print(f"[PoseDetector] ✗ 关闭失败：{e}")
            self.detector = None


class SmartVideoSegmenter:
    """
    智能视频分割器

    结合多种检测方式：
    1. TransNetV2 - 场景切换检测
    2. 音频沉默检测 - 停顿检测
    3. 光流分析 - 动作变化检测
    4. 亮度变化 - 场景变化辅助
    """

    def __init__(
        self,
        transnetv2_weights: Optional[str] = None,
        device: str = 'cuda',
        use_audio: bool = True,
        use_motion: bool = True,
        use_brightness: bool = True,
        use_pose: bool = True,
        min_segment_frames: int = 300,
        progress_callback: Optional[callable] = None
    ):
        """
        初始化分割器

        Args:
            transnetv2_weights: TransNetV2 权重路径
            device: 设备 ('cuda' 或 'cpu')
            use_audio: 是否使用音频检测
            use_motion: 是否使用光流检测
            use_brightness: 是否使用亮度检测
            use_pose: 是否使用姿态检测
            min_segment_frames: 最小片段帧数（用于融合分割点）
            progress_callback: 进度回调函数 (progress, stage, processed, total)
        """
        self.progress_callback = progress_callback
        self.min_segment_frames = min_segment_frames

        # TransNetV2 场景检测
        self.scene_detector = TransNetV2Inference(
            weights_path=transnetv2_weights,
            device=device,
            threshold=0.2  # 降低阈值以检测更多场景
        )

        # 设置场景检测器的进度回调
        if progress_callback:
            self.scene_detector.set_progress_callback(progress_callback)

        # 检测选项
        self.use_audio = use_audio
        self.use_motion = use_motion
        self.use_brightness = use_brightness
        self.use_pose = use_pose

        # 初始化姿态检测器
        self.pose_detector = None
        if use_pose:
            try:
                # 使用 CPU 模式（MediaPipe CUDA 可能不可用）
                self.pose_detector = PoseDetector(use_gpu=False)
                print(f"[SmartSegmenter] 姿态检测器初始化成功")
            except Exception as e:
                print(f"[SmartSegmenter] [!] 姿态检测器初始化失败：{e}")

        print(f"[SmartSegmenter] 初始化完成")
        print(f"  - 场景检测：[OK]")
        print(f"  - 音频检测：{'[OK]' if use_audio else '[X]'}")
        print(f"  - 光流检测：{'[OK]' if use_motion else '[X]'}")
        print(f"  - 亮度检测：{'[OK]' if use_brightness else '[X]'}")
        print(f"  - 姿态检测：{'[OK]' if self.pose_detector else '[X]'}")

    def _report_progress(self, progress: int, stage: str, processed: int = 0, total: int = 0):
        """报告进度"""
        if self.progress_callback:
            try:
                self.progress_callback(progress, stage, processed, total)
            except Exception as e:
                print(f"[SmartSegmenter] [!] 进度回调失败：{e}")
    
    def segment_video(self, video_path: str) -> List[Tuple[int, int, str]]:
        """
        分割视频

        Args:
            video_path: 视频文件路径

        Returns:
            segments: [(start_frame, end_frame, reason), ...]
        """
        print(f"\n[智能分割] 开始处理：{Path(video_path).name}")

        # 报告进度：开始处理
        self._report_progress(5, "加载视频帧", 0, 0)

        # 1. TransNetV2 场景检测
        print(f"\n[1/5] TransNetV2 场景检测...")
        self._report_progress(10, "场景识别", 0, 0)
        frames, single_pred, many_pred, fps = self.scene_detector.predict_video(video_path)
        total_frames = len(frames)
        self._report_progress(20, "场景识别完成", total_frames, total_frames)

        scenes = self.scene_detector.predictions_to_scenes(single_pred, threshold=0.2)

        segment_points = []
        for start, end in scenes:
            segment_points.append(SegmentPoint(
                frame=start,
                confidence=0.9,
                reason='scene_change',
                metadata={'single_pred': single_pred[start] if start < len(single_pred) else 0}
            ))

        print(f"      检测到 {len(scenes)} 个场景")
        self._report_progress(25, f"检测到 {len(scenes)} 个场景", total_frames, total_frames)

        # 2. 音频沉默检测
        if self.use_audio:
            print(f"\n[2/5] 音频沉默检测...")
            self._report_progress(30, "音频沉默检测", 0, total_frames)
            try:
                silence_points = self._detect_audio_silence(video_path, fps)
                segment_points.extend(silence_points)
                print(f"      检测到 {len(silence_points)} 个沉默点")
                self._report_progress(35, f"检测到 {len(silence_points)} 个沉默点", total_frames, total_frames)
            except Exception as e:
                print(f"      [!] 音频检测失败：{e}")
        else:
            self._report_progress(35, "跳过音频检测", total_frames, total_frames)

        # 3. 光流动作检测
        if self.use_motion:
            print(f"\n[3/5] 光流动作检测...")
            self._report_progress(40, "光流动作检测", 0, total_frames)
            try:
                motion_points = self._detect_motion_changes(frames, fps)
                segment_points.extend(motion_points)
                print(f"      检测到 {len(motion_points)} 个动作变化点")
                self._report_progress(50, f"检测到 {len(motion_points)} 个动作变化点", total_frames, total_frames)
            except Exception as e:
                print(f"      [!] 光流检测失败：{e}")
        else:
            self._report_progress(50, "跳过光流检测", total_frames, total_frames)

        # 4. 亮度变化检测
        if self.use_brightness:
            print(f"\n[4/5] 亮度变化检测...")
            self._report_progress(55, "亮度变化检测", 0, total_frames)
            try:
                brightness_points = self._detect_brightness_changes(frames, fps)
                segment_points.extend(brightness_points)
                print(f"      检测到 {len(brightness_points)} 个亮度变化点")
                self._report_progress(60, f"检测到 {len(brightness_points)} 个亮度变化点", total_frames, total_frames)
            except Exception as e:
                print(f"      [!] 亮度检测失败：{e}")
        else:
            print(f"\n[4/5] 跳过亮度变化检测")
            self._report_progress(60, "跳过亮度检测", total_frames, total_frames)

        # 5. 姿态检测
        if self.use_pose and self.pose_detector:
            print(f"\n[5/5] MediaPipe 姿态检测...")
            self._report_progress(65, "姿态检测", 0, total_frames)
            try:
                pose_points = self._detect_pose_changes(frames, fps)
                segment_points.extend(pose_points)
                print(f"      检测到 {len(pose_points)} 个姿态变化点")
                self._report_progress(75, f"检测到 {len(pose_points)} 个姿态变化点", total_frames, total_frames)
            except Exception as e:
                print(f"      [!] 姿态检测失败：{e}")
        else:
            print(f"\n[5/5] 跳过姿态检测")
            self._report_progress(75, "跳过姿态检测", total_frames, total_frames)

        # 6. 融合所有分割点
        print(f"\n[融合] 融合所有检测结果...")
        self._report_progress(80, "融合检测结果", total_frames, total_frames)
        final_segments = self._fuse_segment_points(segment_points, len(frames))

        print(f"\n[OK] 分割完成：共 {len(final_segments)} 个片段")
        self._report_progress(85, f"分割完成，共 {len(final_segments)} 个片段", total_frames, total_frames)

        return final_segments
    
    def _detect_audio_silence(
        self, 
        video_path: str, 
        fps: float,
        silence_threshold: float = 0.05,
        min_silence_duration: float = 0.5
    ) -> List[SegmentPoint]:
        """
        检测音频中的沉默区间
        
        Args:
            silence_threshold: 音量阈值
            min_silence_duration: 最小沉默时长（秒）
        """
        try:
            import librosa
        except ImportError:
            raise ImportError("需要安装 librosa: pip install librosa")
        
        # 提取音频
        cap = cv2.VideoCapture(video_path)
        audio_frames = []
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # 这里简化处理，实际应该使用 ffmpeg 提取音频
            # 为了演示，我们假设音频已经提取
        
        cap.release()
        
        # 使用 librosa 加载音频（实际应该从视频中提取）
        # 这里为了简化，直接使用视频路径（librosa 会自动提取音频）
        y, sr = librosa.load(video_path, sr=None)
        
        # 计算音量包络（RMS）
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        
        # 检测沉默区间
        silence_mask = rms < silence_threshold
        
        segment_points = []
        in_silence = False
        silence_start = 0
        min_silence_frames = int(min_silence_duration * fps)
        
        for i, is_silent in enumerate(silence_mask):
            frame_idx = int(i * 512 / sr * fps)
            
            if is_silent and not in_silence:
                silence_start = i
                in_silence = True
            elif not is_silent and in_silence:
                silence_end = i
                silence_duration = (silence_end - silence_start) * 512 / sr
                
                if silence_duration >= min_silence_duration:
                    segment_points.append(SegmentPoint(
                        frame=frame_idx,
                        confidence=0.7,
                        reason='silence',
                        metadata={'duration': silence_duration}
                    ))
                in_silence = False
        
        return segment_points
    
    def _detect_motion_changes(
        self,
        frames: np.ndarray,
        fps: float,
        threshold: float = 0.2,
        window_size: int = 30
    ) -> List[SegmentPoint]:
        """
        使用光流检测动作变化
        
        Args:
            threshold: 光流变化阈值
            window_size: 滑动窗口大小
        """
        if len(frames) < 2:
            return []
        
        motion_scores = []
        
        # 转换为灰度图
        prev_gray = cv2.cvtColor(frames[0], cv2.COLOR_RGB2GRAY)
        
        for i in range(1, len(frames)):
            gray = cv2.cvtColor(frames[i], cv2.COLOR_RGB2GRAY)
            
            # 计算光流
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2,
                flags=0
            )
            
            # 计算光流大小
            magnitude = np.sqrt(flow[:,:,0]**2 + flow[:,:,1]**2)
            motion_score = np.mean(magnitude)
            motion_scores.append(motion_score)
            
            prev_gray = gray
        
        motion_scores = np.array(motion_scores)
        
        # 归一化
        if motion_scores.max() > 0:
            motion_scores = motion_scores / motion_scores.max()
        
        # 检测峰值
        segment_points = []
        for i in range(window_size, len(motion_scores) - window_size):
            window_before = motion_scores[i-window_size:i]
            window_after = motion_scores[i:i+window_size]
            
            avg_before = np.mean(window_before)
            avg_after = np.mean(window_after)
            current = motion_scores[i]
            
            # 检测动作突变
            if current > threshold and current > avg_before * 1.5 and current > avg_after * 1.5:
                segment_points.append(SegmentPoint(
                    frame=i,
                    confidence=min(current, 1.0),
                    reason='motion',
                    metadata={'motion_score': float(current)}
                ))
        
        return segment_points
    
    def _detect_brightness_changes(
        self,
        frames: np.ndarray,
        fps: float,
        threshold: float = 0.3
    ) -> List[SegmentPoint]:
        """
        检测亮度变化
        
        Args:
            threshold: 亮度变化阈值
        """
        if len(frames) < 2:
            return []
        
        # 计算每帧的平均亮度
        brightness_scores = []
        for frame in frames:
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            brightness = np.mean(gray)
            brightness_scores.append(brightness)
        
        brightness_scores = np.array(brightness_scores)
        
        # 计算亮度变化率
        brightness_diff = np.abs(np.diff(brightness_scores))
        
        # 归一化
        if brightness_diff.max() > 0:
            brightness_diff = brightness_diff / brightness_diff.max()
        
        # 检测亮度突变
        segment_points = []
        for i in range(len(brightness_diff)):
            if brightness_diff[i] > threshold:
                segment_points.append(SegmentPoint(
                    frame=i,
                    confidence=min(brightness_diff[i], 1.0),
                    reason='brightness',
                    metadata={'brightness_change': float(brightness_diff[i])}
                ))
        
        return segment_points

    def _detect_pose_changes(
        self,
        frames: np.ndarray,
        fps: float,
        pose_threshold: float = 0.02,
        min_pose_gap: Optional[float] = 0.3
    ) -> List[SegmentPoint]:
        """
        使用 MediaPipe 检测姿态变化
        
        Args:
            frames: 帧列表
            fps: 帧率
            pose_threshold: 姿态变化阈值（关键点平均距离）
            min_pose_gap: 最小间隔时间（秒）
            
        Returns:
            List[SegmentPoint]: 姿态变化点
        """
        if not self.pose_detector:
            return []
        
        pose_points = []
        min_pose_gap_frames = int(fps * min_pose_gap) if min_pose_gap else 0
        
        prev_pose = None
        prev_pose_frame = -1
        
        print(f"      处理进度：", end='', flush=True)
        
        for i, frame in enumerate(frames):
            # 每 2 帧检测一次，平衡速度和精度
            if i % 2 != 0:
                continue
            
            # 检测姿态
            try:
                current_pose = self.pose_detector.detect_pose(frame)
            except Exception as e:
                if i % 60 == 0:  # 偶尔打印错误，避免刷屏
                    print(f"\n      [!] 检测失败：{e}")
                continue
            
            # 如果检测到姿态
            if current_pose is not None and prev_pose is not None:
                # 计算姿态距离
                pose_distance = self.pose_detector.calculate_pose_distance(prev_pose, current_pose)
                
                # 如果姿态变化超过阈值，且距离上一个检测点足够远
                if pose_distance > pose_threshold and (i - prev_pose_frame) >= min_pose_gap_frames:
                    frame_idx = i
                    
                    # 根据距离计算置信度
                    confidence = min(1.0, pose_distance * 15)  # 距离越大置信度越高
                    
                    # 尝试获取姿态角度
                    pose_angle = self.pose_detector.get_pose_angle(current_pose)
                    
                    metadata = {
                        'pose_distance': pose_distance,
                        'pose_angle': pose_angle
                    }
                    
                    pose_points.append(SegmentPoint(
                        frame=frame_idx,
                        confidence=confidence,
                        reason='pose',
                        metadata=metadata
                    ))
                    prev_pose_frame = i
            
            # 更新上一个姿态
            if current_pose is not None:
                prev_pose = current_pose
            
            # 更新进度
            if i % 30 == 0:
                progress = (i / len(frames)) * 240
                print(f"\r      处理进度：{progress:5.1f}% ({i}/{len(frames)})", end='', flush=True)
        
        print(f"\r      处理进度：100.0% ({len(frames)}/{len(frames)})")
        
        return pose_points

    def _fuse_segment_points(
        self,
        segment_points: List[SegmentPoint],
        total_frames: int
    ) -> List[Tuple[int, int, str]]:
        """
        融合所有分割点
        
        Args:
            segment_points: 所有检测到的分割点
            total_frames: 总帧数
            
        Returns:
            segments: [(start, end, reason), ...]
        """
        if not segment_points:
            return [(0, total_frames - 1, 'default')]
        
        # 按帧排序
        segment_points.sort(key=lambda x: x.frame)
        
        # 合并接近的分割点（距离小于最小帧数的合并）
        merged_points = []

        for point in segment_points:
            if not merged_points:
                merged_points.append(point)
            else:
                last_point = merged_points[-1]
                if point.frame - last_point.frame >= self.min_segment_frames:
                    merged_points.append(point)
                else:
                    # 保留置信度更高的
                    if point.confidence > last_point.confidence:
                        merged_points[-1] = point

        # 生成片段
        segments = []
        prev_frame = 0

        for point in merged_points:
            if point.frame > prev_frame + self.min_segment_frames:  # 至少满足最小帧数
                segments.append((prev_frame, point.frame - 1, point.reason))
            prev_frame = point.frame
        
        # 添加最后一个片段
        if prev_frame < total_frames - 1:
            segments.append((prev_frame, total_frames - 1, 'default'))
        
        return segments


def main():
    """命令行工具"""
    import argparse
    
    parser = argparse.ArgumentParser(description="智能视频分割器")
    parser.add_argument("video", type=str, help="视频文件路径")
    parser.add_argument("--output", type=str, help="输出片段文件路径")
    parser.add_argument("--no-audio", action="store_true", help="禁用音频检测")
    parser.add_argument("--no-motion", action="store_true", help="禁用光流检测")
    parser.add_argument("--no-brightness", action="store_true", help="禁用亮度检测")
    parser.add_argument("--cpu", action="store_true", help="使用 CPU 推理")
    
    args = parser.parse_args()
    
    # 检查视频文件
    if not os.path.exists(args.video):
        print(f"[X] 视频文件不存在：{args.video}")
        sys.exit(1)
    
    # 创建分割器
    device = 'cpu' if args.cpu else 'cuda'
    segmenter = SmartVideoSegmenter(
        device=device,
        use_audio=not args.no_audio,
        use_motion=not args.no_motion,
        use_brightness=not args.no_brightness
    )
    
    # 执行分割
    segments = segmenter.segment_video(args.video)
    
    # 输出结果
    output_path = args.output or Path(args.video).with_suffix(".segments.txt")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# 智能视频分割结果\n")
        f.write(f"# 视频：{Path(args.video).name}\n")
        f.write(f"# 总片段数：{len(segments)}\n\n")
        
        for i, (start, end, reason) in enumerate(segments):
            f.write(f"片段{i+1:03d}: {start:06d}-{end:06d} 帧 [{reason}]\n")
    
    print(f"\n(统计) 片段统计:")
    print(f"   总片段数：{len(segments)}")
    
    # 按原因统计
    reason_counts = {}
    for _, _, reason in segments:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    
    print(f"   按原因统计:")
    for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
        print(f"     - {reason}: {count} 个")
    
    print(f"\n[OK] 结果已保存到：{output_path}")
    
    # 显示前 5 个片段
    print(f"\n前 5 个片段:")
    for i, (start, end, reason) in enumerate(segments[:5]):
        print(f"   片段{i+1}: 帧 {start}-{end} [{reason}]")


if __name__ == "__main__":
    main()
