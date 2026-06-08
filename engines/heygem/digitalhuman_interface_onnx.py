"""
ONNX 版本的数字人模型推理（更新版）
自动检测 ONNX 模型格式并适配
支持并行推理加速
"""

import cv2
import numpy as np
import os
import sys
import onnxruntime as ort
from y_utils.config import GlobalConfig
from y_utils.logger import logger
from concurrent.futures import ThreadPoolExecutor
import threading


def _resolve_gfpgan_model_path():
    """
    解析 GFPGAN 模型路径。
    从 CWD 向上逐级查找 models/gfpgan/GFPGANv1.4.onnx,
    找到则返回绝对路径, 否则返回 None (回退到 GFPGAN 默认的 pretrain_models 路径)。
    """
    _rel_path = os.path.join('models', 'gfpgan', 'GFPGANv1.4.onnx')
    _dir = os.getcwd()
    for _ in range(5):
        _candidate = os.path.join(_dir, _rel_path)
        if os.path.exists(_candidate):
            return os.path.abspath(_candidate)
        _parent = os.path.dirname(_dir)
        if _parent == _dir:
            break
        _dir = _parent
    return None


class DigitalHumanModel:
    """使用 ONNX Runtime 的数字人模型类（自动适配不同格式）"""

    def __init__(self, blend_dynamic, chaofen_before, face_blur_detect=False):
        """
        初始化 ONNX 模型
        """
        from landmark2face_wy.options.test_options import TestOptions
        import torch

        self.blend = True

        # 保存原始 sys.argv 并临时替换，避免 argparse 解析 uvicorn 参数
        original_argv = sys.argv
        sys.argv = [sys.argv[0]]  # 只保留程序名

        try:
            self.opt = TestOptions().parse()
        finally:
            # 恢复原始 sys.argv
            sys.argv = original_argv

        self.opt.isTrain = False

        # 加载 checkpoint 配置
        temp_model = torch.load(self.opt.model_path, map_location='cpu', weights_only=False)
        self.img_size = temp_model["model_input_size"][0]
        self.fuse_mask = temp_model["fuse_mask"]
        self.fuse_mask = cv2.resize(self.fuse_mask, (self.img_size, self.img_size))
        self.nblend = temp_model["nblend"]
        self.drivered_wh = temp_model["wh"]

        # 转换 mask 为 numpy
        # 注意：这些可能是 2D 数组，需要处理维度
        self.mask_cuda = np.array(temp_model["input_mask"])
        self.mask_re_cuda = np.array(temp_model["input_mask_re"])

        # fuse_mask 通常是 2D (H, W)，需要转换为 (3, H, W) 以匹配 tensor 格式
        if len(self.fuse_mask.shape) == 2:
            # 2D (H, W) -> 扩展为 3 通道 -> (3, H, W)
            self.fuse_mask_cuda = np.stack([self.fuse_mask] * 3, axis=0)
        else:
            # 已经是 3D，假设是 (H, W, C)，转换为 (C, H, W)
            self.fuse_mask_cuda = self.fuse_mask.transpose(2, 0, 1)

        # 确定 ONNX 模型路径（优先使用 FP16）
        onnx_model_path_base = self.opt.model_path.replace('.pth', '_wrapped.onnx')
        onnx_model_path_fp16 = self.opt.model_path.replace('.pth', '_wrapped_fp16.onnx')

        # 优先使用 FP16 模型（如果存在）
        if os.path.exists(onnx_model_path_fp16):
            onnx_model_path = onnx_model_path_fp16
            logger.info("检测到 FP16 模型，将使用半精度优化（显存减半，速度提升）")
        elif os.path.exists(onnx_model_path_base):
            onnx_model_path = onnx_model_path_base
            logger.info("使用 FP32 模型")
        else:
            # 尝试使用未包装的版本
            onnx_model_path = self.opt.model_path.replace('.pth', '_fixed.onnx')
            if not os.path.exists(onnx_model_path):
                raise FileNotFoundError(
                    f"找不到 ONNX 模型！\n"
                    f"请先运行以下命令之一:\n"
                    f"  1. python switch_to_onnx.py\n"
                    f"  2. python dinet_wrapper.py"
                )

        logger.info(f"正在加载 ONNX 模型: {onnx_model_path}")

        # 配置 session options
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # 设置为0以隐藏性能警告（如Memcpy节点警告）
        sess_options.log_severity_level = 0
        # 禁用内存pattern优化（避免size不匹配警告）
        sess_options.enable_mem_pattern = False
        # 启用mem reuse模式（更高效的内存分配）
        sess_options.enable_mem_reuse = True

        # CUDA 提供器配置 - 限制显存使用避免溢出到共享内存
        # FP16 模式下可以用到更多显存（因为模型和中间结果都减半）
        is_fp16 = 'fp16' in onnx_model_path.lower()
        mem_limit = 23 * 1024 * 1024 * 1024 if is_fp16 else 22 * 1024 * 1024 * 1024

        cuda_provider_config = {
            'device_id': 0,
            'arena_extend_strategy': 'kNextPowerOfTwo',
            'gpu_mem_limit': mem_limit,  # FP16: 23GB, FP32: 22GB
            'cudnn_conv_algo_search': 'EXHAUSTIVE',  # 寻找最优算法
            'do_copy_in_default_stream': True,
        }

        if is_fp16:
            logger.info(f"FP16 显存限制: {mem_limit // (1024**3)}GB")
        else:
            logger.info(f"FP32 显存限制: {mem_limit // (1024**3)}GB")

        self.session = ort.InferenceSession(
            onnx_model_path,
            sess_options=sess_options,
            providers=[
                ('CUDAExecutionProvider', cuda_provider_config),  # CUDA with memory limit
                'CPUExecutionProvider'  # CPU (fallback)
            ]
        )

        # 获取输入输出信息
        self.input_names = [inp.name for inp in self.session.get_inputs()]
        self.output_names = [out.name for out in self.session.get_outputs()]

        # 获取实际使用的提供器
        available_providers = self.session.get_providers()
        actual_provider = available_providers[0] if available_providers else "Unknown"

        logger.info(f"ONNX 模型加载成功: {onnx_model_path}, 提供器: {actual_provider}")

        # 检测模型格式
        if 'audio_feature' in self.input_names and 'concat_images' in self.input_names:
            self.model_format = 'wrapped'  # 包装格式: netG(audio, concat)
            logger.debug(f"模型格式: 包装格式 (适配原始调用)")
        elif 'source_image' in self.input_names and 'reference_image' in self.input_names:
            self.model_format = 'standard'  # 标准格式: netG(source, ref, audio)
            logger.debug(f"模型格式: 标准格式 (DINetV1)")
        else:
            raise ValueError(f"未知的模型输入格式: {self.input_names}")

        # 初始化其他组件
        if chaofen_before == 1:
            from face_lib.face_restore import GFPGAN
            from face_lib.face_restore.gfpgan_onnx import gfpgan_onnx_api
            # 模型路径: 从 CWD 向上查找 models/gfpgan/GFPGANv1.4.onnx, 回退到默认路径
            _gfpgan_model_path = _resolve_gfpgan_model_path()
            if _gfpgan_model_path:
                gfpgan_onnx_api.MODEL_ZOO['GFPGANv1.4']['model_path'] = _gfpgan_model_path
                logger.info(f"GFPGAN 模型路径已更新: {_gfpgan_model_path}")
            else:
                logger.info("GFPGAN 使用默认模型路径 (pretrain_models)")
            self.gfpgan = GFPGAN(model_type="GFPGANv1.4", provider="gpu")

        self.face_blur_detect = face_blur_detect
        if self.face_blur_detect:
            from face_attr_detect.face_attr import FaceAttr
            self.face_attr = FaceAttr(model_name="face_attr_mbnv3", provider="gpu")

        # 初始化高斯核缓存字典
        self.gaussian_kernel_cache = {}

    def inference(self, audio_info, face_data_dict, this_batch, start_idx, params):
        """ONNX 推理"""
        (audio_idx, wenet_feature) = audio_info
        B_img_list = []
        B_img__list = []
        mask_B_list = []
        mask_B_pre_list = []
        lab_list = []

        # 准备批次数据
        for i in range(this_batch):
            img_idx = start_idx + i
            mask_B_pre = self.gfpgan.forward(face_data_dict[img_idx]["crop_img"])

            crop_h = int(0 * (self.img_size / 256))
            crop_h_end = int(-10 * (self.img_size / 256))
            crop_w = int(5 * (self.img_size / 256))
            crop_w_end = int(-5 * (self.img_size / 256))

            mask_B = mask_B_pre[crop_h:crop_h_end, crop_w:crop_w_end]
            B_img = mask_B.copy()

            # BGR -> RGB, HWC -> CHW
            mask_B = mask_B[:, :, [2, 1, 0]].transpose(2, 0, 1)
            B_img_ = B_img[:, :, [2, 1, 0]].transpose(2, 0, 1)
            B_img = B_img[:, :, [2, 1, 0]].transpose(2, 0, 1)

            B_img_list.append(B_img)
            B_img__list.append(B_img_)
            mask_B_pre_list.append(mask_B_pre)
            mask_B_list.append(mask_B)

            lab = wenet_feature.transpose(1, 0)[audio_idx[start_idx + i][0]:audio_idx[start_idx + i][1]][np.newaxis, ...]
            lab_list.append(lab)

        if this_batch > 0:
            # 转换为 numpy 并准备输入
            lab = np.array(lab_list, dtype=np.float32)
            mask_B_np = np.stack(mask_B_list, axis=0)
            B_img_np = np.stack(B_img__list, axis=0)
            B_img_orig = np.stack(B_img_list, axis=0)

            # 归一化到 [-1, 1]
            mask_B_norm = mask_B_np / 127.5 - 1
            B_img_norm = B_img_np / 127.5 - 1
            B_img_orig_norm = B_img_orig / 127.5 - 1

            # 应用 mask
            mask_B_norm = (mask_B_norm + 1) * self.mask_cuda - 1
            B_img_norm = (B_img_norm + 1) * self.mask_re_cuda - 1

            # 根据模型格式准备输入
            if self.model_format == 'wrapped':
                # 包装格式: netG(audio, concat(ref, source))
                # 原始调用: model.netG(lab, torch.cat((mask_B, B_img_), 1))
                # 所以 concat = [mask_B, B_img_] = [ref, source]
                concat_input = np.concatenate([mask_B_norm, B_img_norm], axis=1)
                onnx_inputs = {
                    'audio_feature': lab.astype(np.float32),
                    'concat_images': concat_input.astype(np.float32)
                }
            else:
                # 标准格式: netG(source, ref, audio)
                onnx_inputs = {
                    'source_image': B_img_orig.astype(np.float32),
                    'reference_image': mask_B_norm.astype(np.float32),
                    'audio_feature': lab.astype(np.float32)
                }

            # ONNX 推理
            fake_B = self.session.run(None, onnx_inputs)[0]

            # 后处理 - 转换通道顺序 RGB -> BGR
            fake_B = fake_B[:, [2, 1, 0], :, :]

            if self.nblend:
                fake_B = np.where(self.mask_re_cuda == 0, B_img_orig_norm, fake_B)

            fuse_mask_expanded = np.tile(self.fuse_mask_cuda[np.newaxis, :, :, :], (this_batch, 1, 1, 1))
            fuse_res = fake_B * fuse_mask_expanded + (1 - fuse_mask_expanded) * B_img_orig_norm
            fuse_res = np.clip(fuse_res, -1, 1)

            # 转换回图像
            output_img_list = []
            for i in range(this_batch):
                crop_h = int(0 * (self.img_size / 256))
                crop_h_end = int(-10 * (self.img_size / 256))
                crop_w = int(5 * (self.img_size / 256))
                crop_w_end = int(-5 * (self.img_size / 256))

                result = ((fuse_res[i] + 1) * 127.5).clip(0, 255).astype(np.uint8)
                result = result.transpose(1, 2, 0)[:, :, [2, 1, 0]]

                mask_B_pre_list[i][crop_h:crop_h_end, crop_w:crop_w_end] = result
                output_img_list.append(mask_B_pre_list[i])
        else:
            output_img_list = mask_B_pre_list

        return output_img_list

    def inference1(self, audio_info, face_data_dict, this_batch, start_idx, params):
        """推理方法1（不使用超分）- 简化版本，可根据需要实现"""
        # 类似 inference，但不使用 gfpgan
        return self.inference(audio_info, face_data_dict, this_batch, start_idx, params)

    def gaussian_blur_batch(self, tensor, kernel_size, sigma):
        """批量高斯模糊（使用 OpenCV）"""
        batch, channels, height, width = tensor.shape
        result = np.empty_like(tensor)

        for b in range(batch):
            for c in range(channels):
                # 转换为 HxW
                img = tensor[b, c].astype(np.uint8)
                blurred = cv2.GaussianBlur(img, (kernel_size, kernel_size), sigma)
                result[b, c] = blurred.astype(np.float32)

        return result

    def optimized_weight_calculation_gpu_batch(self, blend_mask_list, this_batch):
        """计算融合权重（numpy 版本）"""
        if this_batch == 0:
            return np.empty((0, 3, self.img_size, self.img_size), dtype=np.float32)

        # 批量堆叠
        blend_masks_np = np.stack(blend_mask_list, axis=0).astype(np.float32)

        # 添加通道维度 (batch, 1, H, W)
        blend_masks_tensor = blend_masks_np[:, np.newaxis, :, :]

        # 计算模糊参数
        kernel_size = 16 * int(self.img_size / 256) + 1
        if kernel_size % 2 == 0:
            kernel_size += 1

        sigma = kernel_size / 6.0

        # 批量高斯模糊
        blurred_masks = self.gaussian_blur_batch(blend_masks_tensor, kernel_size, sigma)

        # 归一化到[0,1]
        weights = blurred_masks / 255.0

        # 扩展到3通道 (batch, 3, H, W)
        weights = np.repeat(weights, 3, axis=1)

        return weights

    def inference_notraining(self, audio_info, face_data_dict, this_batch, start_idx, blend_dynamic, params, frameId):
        """不使用超分的推理方法"""
        B_img_list = []
        B_img__list = []
        mask_B_list = []
        mask_B_pre_list = []
        blend_mask_list = []
        lab_list = []

        # 检查是否为多脸模式
        is_multi_face = False
        if len(face_data_dict) > 0:
            first_key = list(face_data_dict.keys())[0]
            is_multi_face = 'orig_frame_idx' in face_data_dict[first_key]

        # 多脸模式：需要为每个音频帧找到对应的所有脸
        if is_multi_face:
            # 构建：audio_idx -> [face_data_indices]
            audio_to_faces = {}
            for face_idx in face_data_dict.keys():
                orig_frame_idx = face_data_dict[face_idx].get('orig_frame_idx', face_idx)
                if orig_frame_idx not in audio_to_faces:
                    audio_to_faces[orig_frame_idx] = []
                audio_to_faces[orig_frame_idx].append(face_idx)

            # 处理批次中的每个音频帧
            for audio_offset in range(this_batch):
                audio_idx = start_idx + audio_offset

                # 检查该音频帧是否有对应的脸
                if audio_idx not in audio_to_faces:
                    continue

                # 为该音频帧的所有脸进行推理
                for face_idx in audio_to_faces[audio_idx]:
                    if face_idx not in face_data_dict:
                        continue

                    mask_B_pre = face_data_dict[face_idx]["crop_img"]
                    crop_size = int(5 * (self.img_size / 256))
                    mask_B = mask_B_pre[crop_size:-crop_size, crop_size:-crop_size]
                    B_img = mask_B.copy()

                    # BGR -> RGB
                    mask_B_rgb = mask_B[:, :, [2, 1, 0]]
                    mask_B_chw = mask_B_rgb.transpose(2, 0, 1)
                    B_img_ = B_img.copy()
                    B_img_rgb = B_img_[:, :, [2, 1, 0]]
                    B_img_chw = B_img_rgb.transpose(2, 0, 1)

                    lm = face_data_dict[face_idx]["crop_lm"]
                    blend_mask = self.get_face_mask(mask_B_pre, lm)
                    blend_mask = blend_mask[crop_size:-crop_size, crop_size:-crop_size]

                    if blend_mask.shape[:2] != (self.img_size, self.img_size):
                        blend_mask = cv2.resize(blend_mask, (self.img_size, self.img_size),
                                              interpolation=cv2.INTER_LINEAR)

                    blend_mask_list.append(blend_mask)
                    B_img_list.append(B_img[:, :, [2, 1, 0]].transpose(2, 0, 1))
                    B_img__list.append(B_img_chw)
                    mask_B_pre_list.append(mask_B_pre)
                    mask_B_list.append(mask_B_chw)

                    lab = audio_info[audio_idx].transpose(1, 0)
                    lab_list.append(lab)

        # 单脸模式：原始逻辑
        else:
            for i in range(this_batch):
                img_idx = start_idx + i

                mask_B_pre = face_data_dict[img_idx]["crop_img"]
                crop_size = int(5 * (self.img_size / 256))
                mask_B = mask_B_pre[crop_size:-crop_size, crop_size:-crop_size]
                B_img = mask_B.copy()

                # BGR -> RGB
                mask_B_rgb = mask_B[:, :, [2, 1, 0]]
                mask_B_chw = mask_B_rgb.transpose(2, 0, 1)
                B_img_ = B_img.copy()
                B_img_rgb = B_img_[:, :, [2, 1, 0]]
                B_img_chw = B_img_rgb.transpose(2, 0, 1)

                lm = face_data_dict[img_idx]["crop_lm"]
                blend_mask = self.get_face_mask(mask_B_pre, lm)
                blend_mask = blend_mask[crop_size:-crop_size, crop_size:-crop_size]

                if blend_mask.shape[:2] != (self.img_size, self.img_size):
                    blend_mask = cv2.resize(blend_mask, (self.img_size, self.img_size),
                                          interpolation=cv2.INTER_LINEAR)

                blend_mask_list.append(blend_mask)
                B_img_list.append(B_img[:, :, [2, 1, 0]].transpose(2, 0, 1))
                B_img__list.append(B_img_chw)
                mask_B_pre_list.append(mask_B_pre)
                mask_B_list.append(mask_B_chw)

                lab = audio_info[img_idx].transpose(1, 0)
                lab_list.append(lab)

        if this_batch > 0:
            # 转换为 numpy 并准备输入
            lab = np.array(lab_list, dtype=np.float32)
            mask_B_np = np.stack(mask_B_list, axis=0)  # (B, 3, H, W) RGB
            B_img_np = np.stack(B_img__list, axis=0)  # (B, 3, H, W) RGB
            B_img_orig = np.stack(B_img_list, axis=0)  # (B, 3, H, W) RGB

            # 归一化到 [0, 1]
            mask_B_norm = mask_B_np / 255.0
            B_img_norm = B_img_np / 255.0
            B_img_orig_norm = B_img_orig / 255.0

            # 应用 mask - 注意mask是2D的，需要广播
            mask_B_norm = mask_B_norm * self.mask_cuda  # (B, 3, H, W) * (H, W) -> 自动广播
            B_img_norm = B_img_norm * self.mask_re_cuda  # (B, 3, H, W) * (H, W) -> 自动广播

            # 根据模型格式准备输入
            if self.model_format == 'wrapped':
                # 包装格式: netG(audio, concat(ref, source))
                # 原始调用: model.netG(mask_B, B_img_, lab)
                # 即调用 DINetV1.forward(source, ref, audio)
                # 所以 source=mask_B, ref=B_img_
                # concat输入 = [ref, source] = [B_img_, mask_B]
                # 等等，让我再确认包装器的定义...
                #
                # 包装器将 concat_images 分为：
                # - [:3] = mask_image -> 作为 ref_image
                # - [3:] = source_image -> 作为 source_image
                # 调用 DINetV1.forward(source_image, mask_image, audio)
                # 所以 DINetV1.forward(source=concat[3:], ref=concat[:3], audio)
                #
                # 原始调用是 model.netG(mask_B, B_img_, lab)
                # 即 DINetV1.forward(source=mask_B, ref=B_img_, audio=lab)
                #
                # 所以我们需要：concat[:3] = B_img_, concat[3:] = mask_B
                # 即 concat = [B_img_, mask_B]
                concat_input = np.concatenate([B_img_norm, mask_B_norm], axis=1)
                onnx_inputs = {
                    'audio_feature': lab.astype(np.float32),
                    'concat_images': concat_input.astype(np.float32)
                }
            else:
                # 标准格式: netG(source, ref, audio)
                onnx_inputs = {
                    'source_image': B_img_orig.astype(np.float32),
                    'reference_image': mask_B_norm.astype(np.float32),
                    'audio_feature': lab.astype(np.float32)
                }

            # ONNX 推理
            fake_B = self.session.run(None, onnx_inputs)[0]  # (B, 3, H, W) RGB

            # 不要在这里转换通道！保持RGB格式进行后续处理

            if self.nblend:
                # mask_re_cuda是2D的，需要广播
                fake_B = np.where(self.mask_re_cuda == 0, B_img_orig_norm, fake_B)

            # 计算融合权重
            fuse_mask_cuda_copy = self.optimized_weight_calculation_gpu_batch(blend_mask_list, this_batch)

            fuse_res = fake_B * fuse_mask_cuda_copy + (1 - fuse_mask_cuda_copy) * B_img_orig_norm
            fuse_res = np.clip(fuse_res, 0, 1)

            # 转换回图像
            output_img_list = []
            crop_size = int(5 * (self.img_size / 256))

            # 多脸模式：遍历所有生成的结果（可能比this_batch多）
            # 单脸模式：遍历this_batch个结果
            num_outputs = len(lab_list) if is_multi_face else this_batch

            for i in range(num_outputs):
                # 现在才转换通道：RGB -> BGR (用于OpenCV显示)
                result = (fuse_res[i] * 255).clip(0, 255).astype(np.uint8)  # (3, H, W) RGB
                result = result.transpose(1, 2, 0)  # (H, W, 3) RGB
                result = result[:, :, [2, 1, 0]]  # RGB -> BGR
                mask_B_pre_list[i][crop_size:-crop_size, crop_size:-crop_size] = result
                output_img_list.append(mask_B_pre_list[i])
        else:
            output_img_list = []

        return output_img_list

    def inference_notraining_parallel(self, audio_info, face_data_dict, this_batch, start_idx, blend_dynamic, params, frameId, num_threads=4):
        """
        并行推理版本 - 将batch拆分成多个小batch并行处理

        Args:
            num_threads: 并行线程数（建议2-4）

        原理: GPU内部已经并行化了，但我们可以通过多个线程同时提交推理请求
        让GPU的调度器能够更充分地利用计算资源
        """
        if this_batch <= 1:
            # batch太小，不值得并行
            return self.inference_notraining(audio_info, face_data_dict, this_batch, start_idx, blend_dynamic, params, frameId)

        # 将batch拆分成多个小batch
        batch_splits = []
        split_size = max(1, this_batch // num_threads)

        for i in range(0, this_batch, split_size):
            batch_splits.append((i, min(i + split_size, this_batch)))

        # 并行处理每个子batch
        results = [None] * len(batch_splits)

        def process_split(split_idx, start, end):
            """处理一个子batch"""
            # 计算实际需要处理的数量
            actual_batch = end - start
            actual_start_idx = start_idx + start

            # 调用原始推理方法
            split_results = self.inference_notraining(
                audio_info,
                face_data_dict,
                actual_batch,
                actual_start_idx,
                blend_dynamic,
                params,
                frameId
            )
            return split_idx, split_results

        # 使用线程池并行处理
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {
                executor.submit(process_split, idx, start, end): idx
                for idx, (start, end) in enumerate(batch_splits)
            }

            for future in futures:
                split_idx, split_results = future.result()
                results[split_idx] = split_results

        # 合并结果
        output_img_list = []
        for result in results:
            if result:
                output_img_list.extend(result)

        return output_img_list

    def get_face_mask(self, img, landmarks):
        """生成人脸 mask"""
        imgshape = img.shape[0]
        landmarks = landmarks.astype(int)
        wanted_numpy = np.concatenate([landmarks[2:15], landmarks[29:30]])
        mask = np.zeros((imgshape, imgshape), dtype=np.uint8)
        wanted_numpy = cv2.convexHull(wanted_numpy)
        cv2.fillConvexPoly(mask, wanted_numpy, 255)
        mid = (landmarks[5, :] + landmarks[11, :]) // 2
        cv2.ellipse(mask, (mid[0], mid[1]),
                   ((landmarks[11, 0] - landmarks[5, 0] + 3 * (imgshape // 266)) // 2,
                    60 * (imgshape // 266)), 0, 0, 180, (255, 255, 255), -1)
        amask = (mask > 0).astype(np.uint8) * 255
        kernel_size = (5 * (imgshape // 266) + 1, 5 * (imgshape // 266) + 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
        eroded_mask = cv2.dilate(amask, kernel, iterations=1)
        return eroded_mask
