"""
TransNetV2 PyTorch 推理类（现代化版本）
支持 GPU 加速、批量处理、视频文件直接输入
"""
import os
import sys
import torch
import torch.nn as nn
import numpy as np
from pathlib import Path
from typing import Tuple, List, Optional, Union

# 导入模型定义
sys.path.insert(0, os.path.dirname(__file__))
from transnetv2_pytorch import TransNetV2


class TransNetV2Inference:
    """
    TransNetV2 PyTorch 2.8 推理类
    
    特性:
    - GPU 加速（CUDA）
    - 批量处理
    - 滑动窗口推理
    - 自动帧提取
    - 场景边界检测
    """
    
    def __init__(
        self,
        weights_path: Optional[str] = None,
        device: Optional[str] = None,
        threshold: float = 0.5
    ):
        """
        初始化推理类
        
        Args:
            weights_path: PyTorch 权重文件路径
            device: 设备 ('cuda', 'cpu', 或 None 自动选择)
            threshold: 场景检测阈值
        """
        # 设备配置
        if device is None:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        else:
            self.device = torch.device(device)
        
        print(f"[TransNetV2] 使用设备：{self.device}")
        if self.device.type == 'cuda' and torch.cuda.is_available():
            try:
                print(f"  - GPU: {torch.cuda.get_device_name(0)}")
                print(f"  - CUDA 版本：{torch.version.cuda}")
            except Exception as e:
                print(f"  [!] 无法获取 GPU 信息：{e}")
                self.device = torch.device('cpu')
                print(f"  → 回退到 CPU")

        # 查找权重文件
        if weights_path is None:
            weights_path = Path(__file__).parent / "transnetv2-pytorch-weights.pth"

        weights_path = Path(weights_path)
        if not weights_path.exists():
            raise FileNotFoundError(
                f"权重文件不存在：{weights_path}\n"
                f"请先运行转换脚本：python convert_weights_v2.py"
            )

        # 加载模型
        print(f"[TransNetV2] 加载权重：{weights_path}")
        self.model = TransNetV2()

        # PyTorch 2.8 兼容的权重加载
        state_dict = torch.load(
            weights_path,
            map_location=self.device,
            weights_only=True  # PyTorch 2.6+ 的安全特性
        )
        self.model.load_state_dict(state_dict)
        self.model.to(self.device)
        self.model.eval()

        # 配置
        self.threshold = threshold
        self.input_size = (27, 48, 3)  # (height, width, channels)
        self.window_size = 100  # 滑动窗口大小
        self.stride = 50  # 滑动步长
        self.progress_callback = None  # 进度回调函数

        print(f"[TransNetV2] 模型就绪")
        print(f"  - 输入尺寸：{self.input_size}")
        print(f"  - 窗口大小：{self.window_size} 帧")
        print(f"  - 滑动步长：{self.stride} 帧")
        print(f"  - 检测阈值：{self.threshold}")

    def set_progress_callback(self, callback):
        """设置进度回调函数"""
        self.progress_callback = callback

    def _report_progress(self, progress: int, stage: str, processed: int = 0, total: int = 0):
        """报告进度"""
        if self.progress_callback:
            try:
                self.progress_callback(progress, stage, processed, total)
            except Exception as e:
                print(f"[TransNetV2] [!] 进度回调失败：{e}")

    def _extract_frames_from_video(
        self,
        video_path: str,
        target_size: Tuple[int, int] = (48, 27)
    ) -> Tuple[np.ndarray, float]:
        """
        从视频中提取帧

        Args:
            video_path: 视频文件路径
            target_size: 目标尺寸 (width, height)

        Returns:
            frames: numpy 数组 [frames, height, width, 3], RGB 格式
            fps: 视频帧率
        """
        try:
            import cv2
        except ImportError:
            raise ImportError("需要安装 opencv-python: pip install opencv-python")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise IOError(f"无法打开视频：{video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frames = []

        print(f"[TransNetV2] 视频总帧数：{total_frames}")
        self._report_progress(5, "加载视频帧", 0, total_frames)

        frame_count = 0
        report_interval = max(100, total_frames // 20)  # 每 5% 报告一次进度

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # BGR 转 RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # 调整尺寸
            frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
            frames.append(frame)

            frame_count += 1
            # 定期报告进度
            if frame_count % report_interval == 0:
                progress = 5 + int((frame_count / total_frames) * 10)  # 5-15%
                self._report_progress(progress, f"加载视频帧 {frame_count}/{total_frames}", frame_count, total_frames)

        cap.release()
        print(f"[TransNetV2] 提取了 {len(frames)} 帧，FPS={fps:.2f}")
        self._report_progress(15, f"视频帧提取完成，共 {len(frames)} 帧", len(frames), total_frames)

        return np.array(frames, dtype=np.uint8), fps
    
    def _prepare_window_inputs(
        self, 
        frames: np.ndarray
    ) -> List[np.ndarray]:
        """
        准备滑动窗口输入
        
        Args:
            frames: 视频帧数组 [frames, height, width, 3]
            
        Returns:
            windows: 窗口列表，每个窗口 [1, window_size, height, width, 3]
        """
        no_padded_frames_start = 25
        no_padded_frames_end = 25 + 50 - (len(frames) % 50 if len(frames) % 50 != 0 else 50)
        
        # 填充首尾帧
        start_frame = np.expand_dims(frames[0], 0)
        end_frame = np.expand_dims(frames[-1], 0)
        padded_inputs = np.concatenate(
            [start_frame] * no_padded_frames_start + 
            [frames] + 
            [end_frame] * no_padded_frames_end, 
            axis=0
        )
        
        # 创建滑动窗口
        windows = []
        ptr = 0
        while ptr + self.window_size <= len(padded_inputs):
            window = padded_inputs[ptr:ptr + self.window_size]
            windows.append(window[np.newaxis])  # 添加 batch 维度
            ptr += self.stride
        
        return windows
    
    @torch.no_grad()
    def predict_frames(
        self, 
        frames: np.ndarray,
        batch_size: int = 1
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        预测帧级别的场景边界
        
        Args:
            frames: numpy 数组 [frames, height, width, 3], RGB 格式
            batch_size: 批处理大小
            
        Returns:
            single_pred: 单帧预测 [frames]
            many_pred: 多帧预测 [frames]
        """
        # 准备窗口
        windows = self._prepare_window_inputs(frames)
        
        single_predictions = []
        many_predictions = []
        
        # 批量推理
        for i in range(0, len(windows), batch_size):
            batch_windows = windows[i:i + batch_size]
            
            # 转换为 tensor
            batch_tensor = torch.from_numpy(np.concatenate(batch_windows, axis=0))
            batch_tensor = batch_tensor.to(self.device)
            
            # 推理
            single_out, many_out = self.model(batch_tensor)
            
            # 应用 sigmoid 并转换为 numpy
            single_pred = torch.sigmoid(single_out).cpu().numpy()
            many_pred = torch.sigmoid(many_out["many_hot"]).cpu().numpy()
            
            # 提取有效部分（去掉填充）
            for j in range(len(batch_windows)):
                single_predictions.append(single_pred[j, 25:75, 0])
                many_predictions.append(many_pred[j, 25:75, 0])
            
            # 进度显示
            processed_frames = min(len(single_predictions) * 50, len(frames))
            print(f"\r[TransNetV2] 处理进度：{processed_frames}/{len(frames)} 帧", end="", flush=True)
        
        print()  # 换行
        
        # 合并预测结果
        single_pred = np.concatenate(single_predictions)[:len(frames)]
        many_pred = np.concatenate(many_predictions)[:len(frames)]
        
        return single_pred, many_pred
    
    @torch.no_grad()
    def predict_video(
        self,
        video_path: str,
        batch_size: int = 1
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        """
        直接从视频文件预测

        Args:
            video_path: 视频文件路径
            batch_size: 批处理大小

        Returns:
            frames: 视频帧 [frames, height, width, 3]
            single_pred: 单帧预测 [frames]
            many_pred: 多帧预测 [frames]
            fps: 视频帧率
        """
        print(f"[TransNetV2] 从视频提取帧：{Path(video_path).name}")
        self._report_progress(5, "加载视频帧", 0, 0)
        frames, fps = self._extract_frames_from_video(video_path)
        print(f"      提取了 {len(frames)} 帧，FPS={fps:.2f}")

        self._report_progress(15, "执行场景检测", 0, len(frames))
        print(f"[TransNetV2] 执行场景检测...")
        single_pred, many_pred = self.predict_frames(frames, batch_size=batch_size)

        self._report_progress(20, "场景检测完成", len(frames), len(frames))

        return frames, single_pred, many_pred, fps
    
    @staticmethod
    def predictions_to_scenes(
        predictions: np.ndarray, 
        threshold: float = 0.5
    ) -> np.ndarray:
        """
        将预测转换为场景边界
        
        Args:
            predictions: 预测数组 [frames]
            threshold: 阈值
            
        Returns:
            scenes: 场景数组 [num_scenes, 2], 每行 [start, end]
        """
        predictions = (predictions > threshold).astype(np.uint8)
        
        scenes = []
        start = 0
        for i in range(1, len(predictions)):
            if predictions[i-1] == 1 and predictions[i] == 0:
                start = i
            if predictions[i-1] == 0 and predictions[i] == 1 and i != 0:
                scenes.append([start, i])
        
        if predictions[-1] == 0:
            scenes.append([start, len(predictions) - 1])
        
        if len(scenes) == 0:
            return np.array([[0, len(predictions) - 1]], dtype=np.int32)
        
        return np.array(scenes, dtype=np.int32)
    
    def visualize_predictions(
        self,
        frames: np.ndarray,
        predictions: Tuple[np.ndarray, np.ndarray],
        output_path: str = "predictions.png"
    ) -> str:
        """
        可视化预测结果
        
        Args:
            frames: 视频帧
            predictions: (single_pred, many_pred)
            output_path: 输出文件路径
            
        Returns:
            output_path: 保存的文件路径
        """
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            raise ImportError("需要安装 Pillow: pip install Pillow")
        
        single_pred, many_pred = predictions
        ih, iw, ic = frames.shape[1:]
        width = 25
        
        # 填充帧以便排列
        pad_with = width - len(frames) % width if len(frames) % width != 0 else 0
        frames = np.pad(frames, [(0, pad_with), (0, 1), (0, 2), (0, 0)])
        
        single_pred = np.pad(single_pred, (0, pad_with))
        many_pred = np.pad(many_pred, (0, pad_with))
        
        height = len(frames) // width
        
        # 创建图像
        img = frames.reshape([height, width, ih + 1, iw + 2, ic])
        img = np.concatenate(np.split(
            np.concatenate(np.split(img, height), axis=2)[0], width
        ), axis=2)[0, :-1]
        
        img = Image.fromarray(img)
        draw = ImageDraw.Draw(img)
        
        # 绘制预测线
        for i, (p1, p2) in enumerate(zip(single_pred, many_pred)):
            x, y = i % width, i // width
            x, y = x * (iw + 2) + iw, y * (ih + 1) + ih - 1
            
            # 绘制 single 预测（红色）
            value1 = round(p1 * (ih - 1))
            if value1 != 0:
                draw.line((x, y, x, y - value1), fill=(255, 0, 0), width=1)
            
            # 绘制 many 预测（绿色）
            value2 = round(p2 * (ih - 1))
            if value2 != 0:
                draw.line((x + 1, y, x + 1, y - value2), fill=(0, 255, 0), width=1)
        
        # 保存
        img.save(output_path)
        print(f"[TransNetV2] 可视化已保存到：{output_path}")
        
        return output_path


# 便捷函数
def predict_video_scenes(
    video_path: str,
    weights_path: Optional[str] = None,
    threshold: float = 0.5,
    use_cuda: bool = True
) -> np.ndarray:
    """
    便捷函数：检测视频场景边界
    
    Args:
        video_path: 视频文件路径
        weights_path: 权重文件路径（可选）
        threshold: 检测阈值
        use_cuda: 是否使用 GPU
        
    Returns:
        scenes: 场景数组 [num_scenes, 2]
    """
    device = 'cuda' if use_cuda and torch.cuda.is_available() else 'cpu'
    predictor = TransNetV2Inference(
        weights_path=weights_path,
        device=device,
        threshold=threshold
    )
    
    _, single_pred, _, _ = predictor.predict_video(video_path)
    scenes = predictor.predictions_to_scenes(single_pred, threshold=threshold)
    
    return scenes


if __name__ == "__main__":
    # 示例用法
    import argparse
    
    parser = argparse.ArgumentParser(description="TransNetV2 PyTorch 场景检测")
    parser.add_argument("video", type=str, help="视频文件路径")
    parser.add_argument("--output", type=str, help="输出场景文件路径")
    parser.add_argument("--threshold", type=float, default=0.5, help="检测阈值")
    parser.add_argument("--cpu", action="store_true", help="使用 CPU 推理")
    parser.add_argument("--visualize", action="store_true", help="生成可视化图")
    
    args = parser.parse_args()
    
    # 检查文件
    if not os.path.exists(args.video):
        print(f"[X] 视频文件不存在：{args.video}")
        sys.exit(1)
    
    # 创建推理器
    device = 'cpu' if args.cpu else None
    predictor = TransNetV2Inference(device=device, threshold=args.threshold)
    
    # 预测
    frames, single_pred, many_pred, fps = predictor.predict_video(args.video)
    
    # 转换为场景
    scenes = predictor.predictions_to_scenes(single_pred, threshold=args.threshold)
    
    # 输出结果
    output_path = args.output or Path(args.video).with_suffix(".scenes.txt")
    np.savetxt(output_path, scenes, fmt="%d")
    print(f"\n[OK] 检测到 {len(scenes)} 个场景")
    print(f"   结果已保存到：{output_path}")
    
    # 可视化
    if args.visualize:
        vis_path = Path(args.video).with_suffix(".vis.png")
        predictor.visualize_predictions(frames, (single_pred, many_pred), str(vis_path))
    
    # 统计信息
    total_frames = len(frames)
    total_duration = total_frames / fps if fps > 0 else 0
    avg_scene_length = np.mean([end - start + 1 for start, end in scenes])
    
    print(f"\n(统计) 统计信息:")
    print(f"   视频时长：{total_duration:.2f}秒 ({total_frames}帧)")
    print(f"   场景数量：{len(scenes)}")
    print(f"   平均场景长度：{avg_scene_length:.1f}帧 ({avg_scene_length/fps:.2f}秒)")
