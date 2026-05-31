import os
import sys
import cv2
import numpy as np

torch_lib_path = os.path.join(os.path.dirname(sys.executable), 'lib', 'site-packages', 'torch', 'lib')
if os.path.exists(torch_lib_path):
    os.environ['PATH'] = torch_lib_path + ';' + os.environ.get('PATH', '')

import onnxruntime as ort

class FaceEnhancer:
    def __init__(self, model_path, strength=1.0, padding_ratio=0.8, blur_size=51):
        """
        初始化 GFPGAN 人脸增强器

        Args:
            model_path: ONNX 模型路径
            strength: 增强强度 (0.0-2.0)
                     0.0 = 无增强（原图）
                     0.5 = 轻度增强
                     1.0 = 标准增强（默认）
                     1.5 = 强力增强
                     2.0 = 最大增强
            padding_ratio: 人脸区域扩展比例 (0.5-1.5)，越大处理区域越广
            blur_size: 过渡区域模糊核大小 (奇数，推荐21-101)，越小边缘越锐利
        """
        print(f"加载 GFPGAN 模型: {model_path}")
        self.strength = max(0.0, min(2.0, strength))
        self.padding_ratio = max(0.3, min(1.5, padding_ratio))
        self.blur_size = blur_size if blur_size % 2 == 1 else blur_size + 1
        self.blur_size = max(11, min(151, self.blur_size))

        print(f"   增强强度: {self.strength:.2f}")
        print(f"   区域扩展: {self.padding_ratio:.2f}x")
        print(f"   边缘模糊: {self.blur_size}px")

        self.session = ort.InferenceSession(model_path, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

        try:
            self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            print("✅ 人脸检测器加载成功")
        except:
            self.face_cascade = None
            print("⚠️ 人脸检测器加载失败，将使用整图模式")

    def detect_face(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, 1.1, 6, minSize=(100, 100))

        if len(faces) > 0:
            x, y, w, h = faces[0]
            padding = int(max(w, h) * self.padding_ratio)
            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(img.shape[1], x + w + padding)
            y2 = min(img.shape[0], y + h + padding)

            print(f"   👤 检测到人脸: ({x},{y}) 大小({w}x{h}), 扩展区域: ({x1},{y1})-({x2},{y2})")
            return (x1, y1, x2 - x1, y2 - y1)

        return None

    def enhance_face_region(self, img, face_bbox=None):
        if face_bbox is None:
            face_bbox = self.detect_face(img)
        
        if face_bbox is None:
            print("   ⚠️ 未检测到人脸，返回原图")
            return img.copy()

        x, y, w, h = face_bbox
        
        face_region = img[y:y+h, x:x+w]
        original_size = (w, h)
        
        input_size = (512, 512)
        face_resized = cv2.resize(face_region, input_size, interpolation=cv2.INTER_LANCZOS4)
        
        face_rgb = cv2.cvtColor(face_resized, cv2.COLOR_BGR2RGB)
        face_float = face_rgb.astype(np.float32) / 255.0
        face_norm = (face_float - 0.5) / 0.5
        face_tensor = np.transpose(face_norm, (2, 0, 1))
        face_batch = np.expand_dims(face_tensor, axis=0)
        
        outputs = self.session.run([self.output_name], {self.input_name: face_batch})
        result = outputs[0]
        
        enhanced = result.squeeze()
        enhanced = np.transpose(enhanced, (1, 2, 0))
        enhanced = (enhanced * 0.5 + 0.5) * 255.0
        enhanced = enhanced.clip(0, 255).astype(np.uint8)
        enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_RGB2BGR)
        
        enhanced_resized = cv2.resize(enhanced_bgr, original_size, interpolation=cv2.INTER_LANCZOS4)

        result_img = img.copy()

        center_x = x + w // 2
        center_y = y + h // 2

        mask = np.zeros((h, w), dtype=np.float32)
        cv2.ellipse(mask, (center_x - x, center_y - y),
                   (int(w*0.45), int(h*0.55)), 0, 0, 360, 255, -1)
        mask = cv2.GaussianBlur(mask, (self.blur_size, self.blur_size), 0) / 255.0

        if self.strength <= 1.0:
            alpha = mask * self.strength
        else:
            extra_strength = (self.strength - 1.0) * 0.5
            alpha = np.clip(mask * (1.0 + extra_strength), 0, 1)

        for c in range(3):
            result_img[y:y+h, x:x+w, c] = (
                img[y:y+h, x:x+w, c] * (1 - alpha) +
                enhanced_resized[:, :, c] * alpha
            ).astype(np.uint8)
        
        return result_img

def main():
    print("=" * 70)
    print("GFPGAN 人脸区域增强工具 (智能模式)")
    print("=" * 70)

    model_path = r'd:\AI\AUTOavantar\engines\heygem\gfpgan-1024.onnx'
    input_video = r'd:\AI\AUTOavantar\output\test-dw.mp4'
    output_video = r'd:\AI\AUTOavantar\output\test-dw_gfpgan_face_enhanced.mp4'

    strength = 0.4
    padding_ratio = 0.8
    blur_size = 81

    print(f"\n⚙️  增强参数:")
    print(f"   强度 (strength): {strength:.2f}")
    print(f"     0.0 = 无增强 | 0.5 = 轻度 | 1.0 = 标准 | 1.5 = 强力")
    print(f"   区域扩展 (padding): {padding_ratio:.2f}x")
    print(f"     越大处理区域越广，但可能影响背景")
    print(f"   边缘模糊 (blur): {blur_size}px")
    print(f"     越小边缘越锐利，越大过渡越自然")

    enhancer = FaceEnhancer(model_path, strength=strength, padding_ratio=padding_ratio, blur_size=blur_size)

    cap = cv2.VideoCapture(input_video)
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"\n视频信息:")
    print(f"  分辨率: {width}x{height}")
    print(f"  帧率: {fps:.2f} FPS")
    print(f"  总帧数: {total_frames}")

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_video, fourcc, fps, (width, height))

    print(f"\n开始处理视频...")
    print(f"✨ 使用智能人脸增强模式 (只增强人脸，背景保持原样)")
    
    start_time = time.time() if 'time' in dir() else __import__('time').time()

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        
        if frame_idx == 1 or frame_idx % 50 == 0:
            print(f"\n处理帧 [{frame_idx}/{total_frames}] ({frame_idx/total_frames*100:.1f}%)")

        enhanced_frame = enhancer.enhance_face_region(frame)
        out.write(enhanced_frame)

        if frame_idx == 1 or frame_idx % 50 == 0:
            elapsed = __import__('time').time() - start_time
            speed = frame_idx / elapsed if elapsed > 0 else 0
            print(f"   速度: {speed:.2f} FPS")

    cap.release()
    out.release()

    total_time = __import__('time').time() - start_time
    avg_speed = frame_idx / total_time if total_time > 0 else 0

    print(f"\n{'='*70}")
    print("✅ 视频处理完成!")
    print(f"  处理帧数: {frame_idx}")
    print(f"  总耗时: {total_time:.2f} 秒")
    print(f"  平均速度: {avg_speed:.2f} FPS")
    print(f"  输出文件: {output_video}")
    print(f"{'='*70}")
