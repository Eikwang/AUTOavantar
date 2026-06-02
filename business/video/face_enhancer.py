"""
面部超分模块 - GFPGAN 人脸增强
用于数字人视频生成工作流中的人脸画质优化
"""

import os
import sys
import cv2
import numpy as np
import logging
from typing import Optional, Callable, List, Tuple

logger = logging.getLogger(__name__)

# 模型路径 - 向上3级到项目根目录，然后进入 models
GFPGAN_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models", "gfpgan-1024.onnx"
)


class FaceEnhancer:
    """GFPGAN 人脸增强器"""

    def __init__(
        self,
        model_path: str = None,
        strength: float = 0.5,
        padding_ratio: float = 0.8,
        blur_size: int = 51
    ):
        """
        初始化 GFPGAN 人脸增强器

        Args:
            model_path: ONNX 模型路径
            strength: 增强强度 (0.0-2.0)
            padding_ratio: 人脸区域扩展比例 (0.5-1.5)
            blur_size: 过渡区域模糊核大小 (奇数)
        """
        if model_path is None:
            model_path = GFPGAN_MODEL_PATH

        self.model_path = model_path
        self.strength = max(0.0, min(2.0, strength))
        self.padding_ratio = max(0.3, min(1.5, padding_ratio))
        self.blur_size = blur_size if blur_size % 2 == 1 else blur_size + 1
        self.blur_size = max(11, min(151, self.blur_size))

        self.session = None
        self.input_name = None
        self.output_name = None
        self.face_cascade = None
        self._loaded = False

    def load(self) -> bool:
        """加载模型"""
        if self._loaded:
            return True

        try:
            import onnxruntime as ort

            logger.info(f"加载 GFPGAN 模型: {self.model_path}")
            self.session = ort.InferenceSession(
                self.model_path,
                providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
            )
            self.input_name = self.session.get_inputs()[0].name
            self.output_name = self.session.get_outputs()[0].name

            # 加载人脸检测器
            self.face_cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            if self.face_cascade.empty():
                logger.warning("人脸检测器加载失败，将使用整图模式")
                self.face_cascade = None
            else:
                logger.info("人脸检测器加载成功")

            self._loaded = True
            logger.info(f"GFPGAN 模型加载完成 (strength={self.strength})")
            return True

        except Exception as e:
            logger.error(f"GFPGAN 模型加载失败: {e}")
            self._loaded = False
            return False

    def unload(self):
        """卸载模型，释放显存"""
        if self.session is not None:
            del self.session
            self.session = None

        if self.face_cascade is not None:
            del self.face_cascade
            self.face_cascade = None

        self._loaded = False
        logger.info("GFPGAN 模型已卸载")

    def detect_faces(self, img: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        检测图片中的所有人脸

        Args:
            img: BGR 格式的图片

        Returns:
            人脸区域列表 [(x, y, w, h), ...]
        """
        if self.face_cascade is None:
            return []

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 使用更宽松的参数检测多人脸
        faces = self.face_cascade.detectMultiScale(
            gray, 1.1, 4, minSize=(80, 80)
        )

        face_list = []
        for (x, y, w, h) in faces:
            # 扩展人脸区域
            padding = int(max(w, h) * self.padding_ratio)
            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(img.shape[1], x + w + padding)
            y2 = min(img.shape[0], y + h + padding)
            face_list.append((x1, y1, x2 - x1, y2 - y1))

        return face_list

    def enhance_face_region(
        self,
        img: np.ndarray,
        face_bbox: Tuple[int, int, int, int]
    ) -> np.ndarray:
        """
        增强单个人脸区域

        Args:
            img: BGR 格式的图片
            face_bbox: 人脸区域 (x, y, w, h)

        Returns:
            增强后的图片
        """
        x, y, w, h = face_bbox

        # 提取人脸区域
        face_region = img[y:y+h, x:x+w]
        if face_region.size == 0:
            return img.copy()

        original_size = (w, h)

        # 调整到模型输入尺寸
        input_size = (512, 512)
        face_resized = cv2.resize(face_region, input_size, interpolation=cv2.INTER_LANCZOS4)

        # 预处理
        face_rgb = cv2.cvtColor(face_resized, cv2.COLOR_BGR2RGB)
        face_float = face_rgb.astype(np.float32) / 255.0
        face_norm = (face_float - 0.5) / 0.5
        face_tensor = np.transpose(face_norm, (2, 0, 1))
        face_batch = np.expand_dims(face_tensor, axis=0)

        # 推理
        outputs = self.session.run([self.output_name], {self.input_name: face_batch})
        result = outputs[0]

        # 后处理
        enhanced = result.squeeze()
        enhanced = np.transpose(enhanced, (1, 2, 0))
        enhanced = (enhanced * 0.5 + 0.5) * 255.0
        enhanced = enhanced.clip(0, 255).astype(np.uint8)
        enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_RGB2BGR)
        enhanced_resized = cv2.resize(enhanced_bgr, original_size, interpolation=cv2.INTER_LANCZOS4)

        # 混合原图和增强图
        result_img = img.copy()

        center_x = w // 2
        center_y = h // 2

        # 创建椭圆蒙版
        mask = np.zeros((h, w), dtype=np.float32)
        cv2.ellipse(
            mask, (center_x, center_y),
            (int(w*0.45), int(h*0.55)), 0, 0, 360, 255, -1
        )
        mask = cv2.GaussianBlur(mask, (self.blur_size, self.blur_size), 0) / 255.0

        # 根据 strength 计算混合 alpha
        if self.strength <= 1.0:
            alpha = mask * self.strength
        else:
            extra_strength = (self.strength - 1.0) * 0.5
            alpha = np.clip(mask * (1.0 + extra_strength), 0, 1)

        # 逐通道混合
        for c in range(3):
            result_img[y:y+h, x:x+w, c] = (
                img[y:y+h, x:x+w, c] * (1 - alpha) +
                enhanced_resized[:, :, c] * alpha
            ).astype(np.uint8)

        return result_img

    def enhance_frame(self, img: np.ndarray) -> np.ndarray:
        """
        增强一帧图片中的所有人脸（多面孔支持）

        Args:
            img: BGR 格式的图片

        Returns:
            增强后的图片
        """
        if not self._loaded:
            return img.copy()

        # 检测所有人脸
        faces = self.detect_faces(img)

        if not faces:
            return img.copy()

        result_img = img.copy()
        for face_bbox in faces:
            result_img = self.enhance_face_region(result_img, face_bbox)

        return result_img


class VideoFaceEnhancer:
    """视频面部超分处理器"""

    def __init__(
        self,
        model_path: str = None,
        strength: float = 0.5,
        padding_ratio: float = 0.8,
        blur_size: int = 51
    ):
        """
        初始化视频面部超分处理器

        Args:
            model_path: ONNX 模型路径
            strength: 增强强度
            padding_ratio: 人脸区域扩展比例
            blur_size: 边缘模糊大小
        """
        self.enhancer = FaceEnhancer(
            model_path=model_path,
            strength=strength,
            padding_ratio=padding_ratio,
            blur_size=blur_size
        )

    def process_video(
        self,
        input_path: str,
        output_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """
        处理视频，对所有人脸进行超分

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            progress_callback: 进度回调 (current, total)

        Returns:
            是否成功
        """
        # 加载模型
        if not self.enhancer.load():
            logger.error("GFPGAN 模型加载失败，无法处理视频")
            return False

        try:
            cap = cv2.VideoCapture(input_path)
            if not cap.isOpened():
                logger.error(f"无法打开视频: {input_path}")
                return False

            # 获取视频属性
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # 创建视频写入器
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                frame_idx += 1

                # 增强当前帧
                enhanced_frame = self.enhancer.enhance_frame(frame)
                out.write(enhanced_frame)

                # 进度回调
                if progress_callback and frame_idx % 50 == 0:
                    progress_callback(frame_idx, total_frames)

                if frame_idx == 1 or frame_idx % 100 == 0:
                    logger.info(f"面部超分进度: {frame_idx}/{total_frames} ({frame_idx/total_frames*100:.1f}%)")

            cap.release()
            out.release()

            logger.info(f"面部超分完成: {output_path}")
            return True

        except Exception as e:
            logger.error(f"视频面部超分失败: {e}")
            return False

        finally:
            # 卸载模型释放显存
            self.enhancer.unload()


def enhance_video(
    input_path: str,
    output_path: str,
    strength: float = 0.5,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> bool:
    """
    便捷函数：对视频进行面部超分

    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        strength: 增强强度
        progress_callback: 进度回调

    Returns:
        是否成功
    """
    enhancer = VideoFaceEnhancer(strength=strength)
    return enhancer.process_video(input_path, output_path, progress_callback)


def copy_audio_to_video(
    input_video_path: str,
    output_video_path: str,
    audio_source_path: str = None
) -> bool:
    """
    复制音频流到目标视频

    Args:
        input_video_path: 源视频（将使用其音频）
        output_video_path: 输出视频路径
        audio_source_path: 可选的独立音频路径（优先使用）

    Returns:
        是否成功
    """
    import subprocess
    import platform

    if audio_source_path is None:
        audio_source_path = input_video_path

    try:
        # 使用 ffmpeg 复制音频流
        cmd = [
            'ffmpeg', '-y',
            '-i', output_video_path,
            '-i', audio_source_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-shortest',
            output_video_path + '.tmp'
        ]

        # Windows 下隐藏控制台窗口
        creationflags = 0
        if platform.system() == 'Windows':
            creationflags = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(
            cmd,
            capture_output=True,
            creationflags=creationflags
        )

        if result.returncode != 0:
            logger.error(f"音频复制失败: {result.stderr.decode()}")
            # 尝试简单方案：直接复制
            cmd_simple = [
                'ffmpeg', '-y',
                '-i', output_video_path,
                '-i', audio_source_path,
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-shortest',
                output_video_path + '.tmp'
            ]
            result = subprocess.run(
                cmd_simple,
                capture_output=True,
                creationflags=creationflags
            )
            if result.returncode != 0:
                logger.error(f"简单音频复制也失败: {result.stderr.decode()}")
                return False

        # 替换原文件
        import shutil
        shutil.move(output_video_path + '.tmp', output_video_path)
        logger.info(f"音频复制完成: {output_video_path}")
        return True

    except Exception as e:
        logger.error(f"复制音频流失败: {e}")
        return False


def get_video_resolution(video_path: str) -> Tuple[int, int]:
    """
    获取视频分辨率

    Args:
        video_path: 视频路径

    Returns:
        (width, height)
    """
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return (0, 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        return (width, height)
    except Exception as e:
        logger.error(f"获取视频分辨率失败: {e}")
        return (0, 0)


def calculate_strength_by_resolution(width: int, height: int) -> Tuple[float, bool]:
    """
    根据视频分辨率计算 strength 参数

    Args:
        width: 视频宽度
        height: 视频高度

    Returns:
        (strength, should_enhance): 是否需要启用超分
    """
    max_pixels = max(width, height)

    if max_pixels <= 1920:
        return (0.0, False)
    elif max_pixels <= 2560:
        return (0.3, True)
    elif max_pixels <= 3840:
        return (0.4, True)
    else:
        return (0.5, True)