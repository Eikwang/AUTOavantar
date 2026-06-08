import gc
import multiprocessing
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
from enum import Enum
from multiprocessing import Process, set_start_method
from queue import Empty, Full

# ============================================================================
# 【备用修复】在模块导入时立即隐藏控制台窗口
# 当 multiprocessing 使用 spawn 方法启动子进程时，子进程会重新导入此模块。
# 此时控制台窗口已经被创建，我们需要在模块导入的最早期立即隐藏它。
# 这是备用方案，主要的修复在后端入口点应用 monkey patch
# ============================================================================
if platform.system() == "Windows":
    try:
        import ctypes
        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if console_window:
            ctypes.windll.user32.ShowWindow(console_window, 0)
            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass
import cv2
import librosa
import numpy as np
import json
import torch
from cv2box import CVImage
from cv2box.cv_gears import Linker, Queue, CVVideoWriterThread
from face_detect_utils.face_detect import FaceDetect, pfpld
from face_detect_utils.head_pose import Headpose
from face_lib.face_detect_and_align import FaceDetect5Landmarks
from face_lib.face_restore import GFPGAN
from h_utils.custom import CustomError
from h_utils.request_utils import download_file
#from h_utils.sweep_bot import sweep
from digitalhuman_interface_onnx import DigitalHumanModel  # ONNX版本
from preprocess_audio_and_3dmm import op
from wenet.compute_ctc_att_bnf import get_weget, load_ppg_model
from y_utils.config import GlobalConfig
from y_utils.logger import logger
from y_utils.lcr import check_lc
#from server import register_host, repost_host
from torch.cuda.amp import autocast
import itertools

# 【修改点1】移除了全局变量 need_chaofen_flag 和 get_firstface_frame


def _resolve_gfpgan_model_path():
    """
    解析 GFPGAN 模型路径。
    从 CWD 向上逐级查找 models/gfpgan/GFPGANv1.4.onnx,
    找到则返回绝对路径, 否则返回 None (回退到 GFPGAN 默认的 pretrain_models 路径)。
    """
    _rel_path = os.path.join('models', 'gfpgan', 'GFPGANv1.4.onnx')
    _dir = os.getcwd()
    for _ in range(5):  # 最多向上查找 5 级
        _candidate = os.path.join(_dir, _rel_path)
        if os.path.exists(_candidate):
            return os.path.abspath(_candidate)
        _parent = os.path.dirname(_dir)
        if _parent == _dir:
            break
        _dir = _parent
    return None


def run_silent(command, shell=True):
    """
    静默执行命令，不弹出控制台窗口

    Args:
        command: 要执行的命令（字符串或列表）
        shell: 是否使用 shell 执行

    Returns:
        subprocess.CompletedProcess 结果
    """
    creationflags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    return subprocess.run(command, shell=shell, creationflags=creationflags)


def set_console_window_hidden():
    """
    设置当前进程的控制台窗口隐藏状态

    在 Windows 上，此函数会隐藏当前进程的控制台窗口并释放控制台句柄。
    这应该在父进程中调用，以便子进程继承隐藏状态。
    """
    if platform.system() == "Windows":
        try:
            import ctypes
            # 获取控制台窗口句柄
            console_window = ctypes.windll.kernel32.GetConsoleWindow()
            if console_window:
                # SW_HIDE = 0, 隐藏窗口
                ctypes.windll.user32.ShowWindow(console_window, 0)
                # 释放控制台，彻底断开与控制台的连接
                ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass


def suppress_console_output():
    """
    抑制控制台输出，用于 multiprocessing 子进程

    在 Windows 打包后的 EXE 中，子进程的 print() 可能导致控制台窗口弹出。
    此函数将 sys.stdout 和 sys.stderr 重定向到 devnull，并禁用 logging 控制台输出。

    注意：控制台窗口的隐藏已在模块导入时完成，此函数仅处理输出重定向。
    """
    if platform.system() == "Windows":
        try:
            # 重定向 sys.stdout 和 sys.stderr
            sys.stdout = open(os.devnull, 'w', encoding='utf-8')
            sys.stderr = open(os.devnull, 'w', encoding='utf-8')

            # 禁用 logging 的控制台输出
            import logging
            # 获取根 logger 并移除所有 handler
            root_logger = logging.getLogger()
            for handler in root_logger.handlers[:]:
                if isinstance(handler, logging.StreamHandler):
                    root_logger.removeHandler(handler)
            # 添加一个 NullHandler
            root_logger.addHandler(logging.NullHandler())
        except Exception:
            pass


class FaceSelectWrapper:
    def __init__(self, detector, target_face_index=0, last_center=None):
        """
        detector: 原始检测器
        target_face_index: 目标索引 (用于初始锁定)
        last_center: 上一帧/上一批次的目标中心点 (x, y)，用于追踪
        """
        self.detector = detector
        self.target_face_index = target_face_index
        self.last_center = last_center # 核心状态：记录目标脸在哪里

    def get_bboxes(self, image, max_num=0):
        # 1. 调用原始检测
        bboxes, kpss = self.detector.get_bboxes(image, max_num=max_num)

        if len(bboxes) == 0:
            return bboxes, kpss

        # ---------------------------------------------------
        # 特殊情况: target_face_index == -1 表示驱动所有脸
        # ---------------------------------------------------
        if self.target_face_index == -1:
            # 多脸模式：按 X 坐标排序（从左到右），保持帧间顺序一致，减少抖动
            if len(bboxes) > 1:
                # 计算每个框的中心 X 坐标
                center_x = (bboxes[:, 0] + bboxes[:, 2]) / 2
                # 按中心 X 坐标排序（从左到右）
                sorted_indices = np.argsort(center_x)
                bboxes = bboxes[sorted_indices]
                kpss = kpss[sorted_indices]
            # 返回所有检测到的脸，不进行筛选
            return bboxes, kpss

        # 计算当前帧所有脸的中心点
        # bboxes: [x1, y1, x2, y2, score]
        centers = np.vstack([
            (bboxes[:, 0] + bboxes[:, 2]) / 2,
            (bboxes[:, 1] + bboxes[:, 3]) / 2
        ]).T  # shape: (N, 2)

        selected_idx = 0

        # ---------------------------------------------------
        # 情况 A: 还没有锁定过目标 (第一帧 或 刚启动)
        # -> 使用 "从上到下" 排序逻辑进行初始化锁定
        # ---------------------------------------------------
        if self.last_center is None:
            # 按 Y 轴坐标从小到大排序 (从上到下)
            sorted_indices = np.argsort(centers[:, 1])
            # 获取目标索引
            selected_idx = sorted_indices[min(self.target_face_index, len(bboxes) - 1)]

        # ---------------------------------------------------
        # 情况 B: 已经有上一帧的位置
        # -> 使用 "最短距离" 逻辑进行追踪
        # ---------------------------------------------------
        else:
            # 计算所有脸到 last_center 的欧氏距离
            distances = np.linalg.norm(centers - self.last_center, axis=1)
            # 选距离最近的那个
            selected_idx = np.argmin(distances)

        # 2. 更新中心点状态 (引入简单的平滑，防止剧烈跳变)
        current_center = centers[selected_idx]
        if self.last_center is None:
            self.last_center = current_center
        else:
            # 0.7 * 新位置 + 0.3 * 旧位置 (平滑更新)
            self.last_center = 0.7 * current_center + 0.3 * self.last_center

        # 3. 返回选中的那一张脸
        return bboxes[selected_idx:selected_idx+1], kpss[selected_idx:selected_idx+1]

    def __getattr__(self, name):
        return getattr(self.detector, name)


def drivered_video_pingpong(code, drivered_queue, drivered_path, audio_wenet_feature, batch_size, wh=0, chaofen_ctrl=0,target_face_id=0):
    """
    Reads a driver video, holds its frames in memory, and provides them in a
    ping-pong loop (0...n-1, n-2...1, 0...) to match the audio feature length.
    This is an efficient, in-memory replacement for drivered_video_pn.
    【修改点2】增加了 chaofen_ctrl 参数
    """
    suppress_console_output()  # 抑制控制台输出
    try:
        logger.info(f'[{code}]任务视频驱动队列启动 (Ping-Pong Mode) batch_size:{batch_size}, chaofen_ctrl:{chaofen_ctrl}')

        # 1. Read all frames from the driver video into a list in memory.
        cap = cv2.VideoCapture(drivered_path)
        frames_in_memory = []
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            frames_in_memory.append(frame)
        cap.release()

        if not frames_in_memory:
            raise ValueError("Could not read any frames from the driver video.")

        num_frames = len(frames_in_memory)
        logger.info(f'[{code}] Pre-loaded {num_frames} frames from driver video into memory.')

        # 2. Create an infinite iterator for the ping-pong frame indices.
        forward_indices = range(num_frames)
        backward_indices = range(num_frames - 2, 0, -1)  # from n-2 down to 1

        # Handle short videos (1 or 2 frames) where backward pass is not needed
        if num_frames <= 2:
            pingpong_indices_generator = itertools.cycle(forward_indices)
        else:
            pingpong_indices_generator = itertools.cycle(itertools.chain(forward_indices, backward_indices))

        # 3. Main loop to process frames based on audio length
        drivered_list = []
        wenet_feature_list = []
        total_audio_frames = len(audio_wenet_feature)

        for current_idx in range(total_audio_frames):
            # Get the next frame index from our ping-pong generator
            frame_index = next(pingpong_indices_generator)
            frame = frames_in_memory[frame_index]

            drivered_list.append(frame)
            wenet_feature_list.append(audio_wenet_feature[current_idx])

            # Check if a batch is ready to be sent or if it's the last frame
            if len(drivered_list) == batch_size or current_idx == total_audio_frames - 1:
                # 【修改点3】队列传输增加 chaofen_ctrl 和 batch_size
                drivered_queue.put([drivered_list, wenet_feature_list, code, wh, current_idx + 1, chaofen_ctrl, target_face_id, batch_size], block=True,
                                   timeout=60)
                logger.info(
                    f'drivered_video (Ping-Pong) >>> 发送数据大小:[{len(drivered_list)}], current_idx:{current_idx + 1}/{total_audio_frames}')
                # print("刘悦的技术博客(B站/Youtube 同名) https://t.zsxq.com/IrQPr")
                drivered_list = []
                wenet_feature_list = []

        logger.info('drivered_video (Ping-Pong) >>>>>>>>>>>>>>>>>>>> 发送数据结束')
        drivered_queue.put([True, 'success', code])
        logger.info(f'[{code}]任务预处理进程结束 (Ping-Pong Mode)')

    except Full:
        logger.error(f'[{code}]任务视频驱动队列满，严重阻塞，下游队列异常')
        drivered_queue.put([False, f'[{code}]任务视频驱动队列满', code])
    except Exception as e:
        error_msg = traceback.format_exc()
        logger.error(f'[{code}]任务视频驱动队列异常 (Ping-Pong)，异常信息:[{e.__str__()}]\n{error_msg}')
        drivered_queue.put([False, f'[{code}]任务视频驱动队列异常，异常信息:[{e.__str__()}]', code])


def feature_extraction_wenet(audio_file, fps, wenet_model, mfccnorm=True, section=560000):
    rate = 16000
    win_size = 20
    if type(audio_file) == str:
        sig, rate = librosa.load(audio_file, sr=16000, duration=None)
    else:
        sig = audio_file
    time_duration = len(sig) / rate
    cnts = range(int(time_duration * fps))
    indexs = []
    f_wenet_all = get_weget(audio_file, wenet_model, section)
    for cnt in cnts:
        c_count = int(cnt / cnts[-1] * (f_wenet_all.shape[0] - 20)) + win_size // 2
        indexs.append(f_wenet_all[c_count - win_size // 2:c_count + win_size // 2, ...])
    return indexs


def get_aud_feat1(wav_fragment, fps, wenet_model):
    return feature_extraction_wenet(wav_fragment, fps, wenet_model)


def warp_imgs(imgs_data):
    caped_img2 = {idx: {'imgs_data': it, 'idx': idx} for it, idx in zip(imgs_data, range(len(imgs_data)))}
    return caped_img2


def get_complete_imgs(output_img_list, start_index, params):
    out_shape, output_resize, drivered_imgs_data, Y1_list, Y2_list, X1_list, X2_list = params

    # 检查是否为多脸模式
    is_multi_face = isinstance(drivered_imgs_data, dict) and len(drivered_imgs_data) > 0 and 'orig_frame_idx' in list(drivered_imgs_data.values())[0]

    if not is_multi_face:
        # 单脸模式：原始逻辑
        complete_imgs = []
        for i, mask_B_pre in enumerate(output_img_list):
            img_idx = start_index + i
            image = drivered_imgs_data[img_idx]
            y1, y2, x1, x2 = (Y1_list[img_idx], Y2_list[img_idx], X1_list[img_idx], X2_list[img_idx])
            mask_B_pre_resize = cv2.resize(mask_B_pre, (y2 - y1, x2 - x1))
            if y1 < 0:
                mask_B_pre_resize = mask_B_pre_resize[:, -y1:]
                y1 = 0
            if y2 > image.shape[1]:
                mask_B_pre_resize = mask_B_pre_resize[:, :-(y2 - image.shape[1])]
                y2 = image.shape[1]
            if x1 < 0:
                mask_B_pre_resize = mask_B_pre_resize[-x1:, :]
                x1 = 0
            if x2 > image.shape[0]:
                mask_B_pre_resize = mask_B_pre_resize[:-(x2 - image.shape[0]), :]
                x2 = image.shape[0]
            image[x1:x2, y1:y2] = mask_B_pre_resize
            image = cv2.resize(image, (out_shape[1] // output_resize, out_shape[0] // output_resize))
            complete_imgs.append(image)
        return complete_imgs

    # 多脸模式：合并同一帧的多张脸
    # 收集每帧的所有脸数据
    frame_faces = {}  # {orig_frame_idx: [(face_idx, mask_B_pre, y1, y2, x1, x2), ...]}
    for i, mask_B_pre in enumerate(output_img_list):
        img_idx = start_index + i
        if img_idx not in drivered_imgs_data:
            continue
        face_data = drivered_imgs_data[img_idx]
        orig_idx = face_data.get('orig_frame_idx', img_idx)
        y1, y2, x1, x2 = (Y1_list[i], Y2_list[i], X1_list[i], X2_list[i])

        if orig_idx not in frame_faces:
            frame_faces[orig_idx] = []
        frame_faces[orig_idx].append((mask_B_pre, y1, y2, x1, x2))

    # 为每帧融合多张脸
    complete_imgs = []
    for orig_idx in sorted(frame_faces.keys()):
        # 获取原始图像
        first_face_data = None
        for img_idx in drivered_imgs_data.keys():
            if drivered_imgs_data[img_idx].get('orig_frame_idx', -1) == orig_idx:
                first_face_data = drivered_imgs_data[img_idx]
                break

        if first_face_data is None:
            continue

        image = first_face_data['imgs_data'].copy()

        # 融合该帧的所有脸
        for mask_B_pre, y1, y2, x1, x2 in frame_faces[orig_idx]:
            mask_B_pre_resize = cv2.resize(mask_B_pre, (y2 - y1, x2 - x1))
            if y1 < 0:
                mask_B_pre_resize = mask_B_pre_resize[:, -y1:]
                y1 = 0
            if y2 > image.shape[1]:
                mask_B_pre_resize = mask_B_pre_resize[:, :-(y2 - image.shape[1])]
                y2 = image.shape[1]
            if x1 < 0:
                mask_B_pre_resize = mask_B_pre_resize[-x1:, :]
                x1 = 0
            if x2 > image.shape[0]:
                mask_B_pre_resize = mask_B_pre_resize[:-(x2 - image.shape[0]), :]
                x2 = image.shape[0]
            image[x1:x2, y1:y2] = mask_B_pre_resize

        image = cv2.resize(image, (out_shape[1] // output_resize, out_shape[0] // output_resize))
        complete_imgs.append(image)

    return complete_imgs


def get_blend_imgs(batch_size, audio_data, face_data_dict, blend_dynamic, params, digital_human_model, frameId, target_face_id=0):
    result_img_list = []

    # 禁用并行推理：GPU 本身已经高效并行，多线程只会增加开销
    use_parallel = False

    for idx in range(len(audio_data) // batch_size + 1):
        # 每个 batch 前清理显存
        torch.cuda.empty_cache()
        # 每10个batch输出一次进度，减少I/O开销
        if idx % 10 == 0 or idx * batch_size >= len(audio_data) - batch_size:
            logger.debug(f'进度: {idx * batch_size + 1}/{len(audio_data)}')

        if idx < len(audio_data) // batch_size:
            start_index = idx * batch_size

            # 串行推理：GPU 内部已并行，无需多线程
            output_img_list = digital_human_model.inference_notraining(
                audio_data, face_data_dict, batch_size, start_index, blend_dynamic, params, frameId
            )

            complete_imgs = get_complete_imgs(output_img_list, start_index, params)
            result_img_list += complete_imgs

            # 每个 batch 后再次清理显存
            torch.cuda.empty_cache()
        else:
            # 处理剩余帧
            this_batch = len(audio_data) % batch_size
            if this_batch > 0:
                start_index = idx * batch_size

                output_img_list = digital_human_model.inference_notraining(
                    audio_data, face_data_dict, this_batch, start_index, blend_dynamic, params, frameId
                )

                complete_imgs = get_complete_imgs(output_img_list, start_index, params)
                result_img_list += complete_imgs

                torch.cuda.empty_cache()

    # 最终清理
    torch.cuda.empty_cache()
    return result_img_list


def drivered_video(code, drivered_queue, drivered_path, audio_wenet_feature, batch_size, wh=0, chaofen_ctrl=0,target_face_id=0):
    """
    【修改点4】增加了 chaofen_ctrl 参数
    """
    suppress_console_output()  # 抑制控制台输出
    try:
        logger.info(f'[{code}]任务视频驱动队列启动 batch_size:{batch_size}, len:{len(audio_wenet_feature)}, chaofen_ctrl:{chaofen_ctrl}')
        drivered_list = []
        wenet_feature_list = []
        count_f = 0
        current_idx = 0
        logger.debug('in template video function')
        cap = cv2.VideoCapture(drivered_path)
        logger.info('drivered_video >>>>>>>>>>>>>>>>>>>> 开始循环')
        while cap.isOpened():
            count_f += 1
            ret, frame = cap.read()
            if ret:
                drivered_list.append(frame)
                wenet_feature_list.append(audio_wenet_feature[current_idx])
                current_idx += 1
                if count_f % batch_size == 0:
                    # 【修改点5】队列传输增加 chaofen_ctrl 和 batch_size
                    drivered_queue.put([drivered_list, wenet_feature_list, code, wh, current_idx, chaofen_ctrl, target_face_id, batch_size], block=True, timeout=60)
                    logger.info(f'drivered_video >>>>>>>>>>>>>>>>>>>> 发送数据大小:[{len(drivered_list)}], current_idx:{current_idx}')
                    count_f = 0
                    drivered_list = []
                    wenet_feature_list = []
                if current_idx == len(audio_wenet_feature):
                    logger.info('append imgs over')
                    cap.release()
                    continue
            else:
                cap.release()
                continue
        if current_idx == len(audio_wenet_feature):
            cap.release()
        else:
            pass
        logger.info('drivered_video >>>>>>>>>>>>>>>>>>>> 发送数据结束')
        drivered_queue.put([True, 'success', code])
        logger.info(f'[{code}]任务预处理进程结束')
    except Full:
        logger.error(f'[{code}]任务视频驱动队列满，严重阻塞，下游队列异常')
    except Exception as e:
        traceback.format_exc()
        logger.error(f'[{code}]任务视频驱动队列异常，异常信息:[{e.__str__()}]')
        drivered_queue.put([False, f'[{code}]任务视频驱动队列异常，异常信息:[{e.__str__()}]', code])


def get_face_mask(mask_shape=(512, 512)):
    mask = np.zeros(mask_shape).astype(np.float32)
    cv2.ellipse(mask, (256, 256), (220, 160), 90, 0, 360, (255, 255, 255), -1)
    thres = 20
    mask[:thres, :] = 0
    mask[-thres:, :] = 0
    mask[:, :thres] = 0
    mask[:, -thres:] = 0
    mask = cv2.stackBlur(mask, (201, 201))
    mask = mask / 255
    mask = cv2.resize(mask, mask_shape)
    return mask[..., np.newaxis]

face_mask = get_face_mask()

def get_single_face(bboxes, kpss, image, crop_size, mode='mtcnn_512', apply_roi=True):
    from face_lib.face_detect_and_align.face_align_utils import apply_roi_func, norm_crop
    assert mode in ('default', 'mtcnn_512', 'mtcnn_256', 'arcface_512', 'arcface', 'default_95')
    if bboxes.shape[0] == 0:
        return (None, None, None)
    det_score = bboxes[..., 4]
    best_index = np.argmax(det_score)
    new_kpss = None
    if kpss is not None:
        new_kpss = kpss[best_index]
    if apply_roi:
        roi, roi_box, roi_kpss = apply_roi_func(image, bboxes[best_index], new_kpss)
        align_img, mat_rev = norm_crop(roi, roi_kpss, crop_size=crop_size, mode=mode)
        return (align_img, mat_rev, roi_box)
    align_img, M = norm_crop(image, new_kpss, crop_size=crop_size, mode=mode)
    return (align_img, M)


def chaofen_batch(frame_list, gfpgan, fd):
    """Applies super-resolution to a batch of frames."""
    new_frame_list = []
    for frame in frame_list:
        with autocast():
            bboxes_scrfd, kpss_scrfd = fd.get_bboxes(frame)
            if len(bboxes_scrfd) == 0:
                new_frame_list.append(frame)
                continue
            
            face_image_, mat_rev_, roi_box_ = get_single_face(bboxes_scrfd, kpss_scrfd, frame, crop_size=512, mode='mtcnn_512', apply_roi=True)
            if face_image_ is None:
                new_frame_list.append(frame)
                continue

            face_restore_out_ = gfpgan.forward(face_image_)
            torch.cuda.empty_cache()
            
            restore_roi = CVImage(None).recover_from_reverse_matrix(
                face_restore_out_,
                frame[roi_box_[1]:roi_box_[3], roi_box_[0]:roi_box_[2]],
                mat_rev_,
                img_fg_mask=face_mask
            )
            
            frame[roi_box_[1]:roi_box_[3], roi_box_[0]:roi_box_[2]] = restore_roi
            new_frame_list.append(frame)
    torch.cuda.empty_cache()
    return new_frame_list

# 【修改点6】chaofen_src 逻辑重构，接收 task_state 和 chaofen_ctrl
def chaofen_src(frame_list, gfpgan, fd, frame_id, face_blur_detect, code, task_state, chaofen_ctrl):
    """
    task_state: dict, {'checked': bool, 'need_chaofen': bool}
    chaofen_ctrl: int, 0=OFF, 1=AUTO/ON
    """
    s_chao = time.time()
    
    # 外部总开关控制
    if chaofen_ctrl == 0:
        return frame_list

    # 如果该任务还没检测过
    # if not task_state.get('checked', False):
    #     # 默认前几帧(例如第4帧)或者每批次都检测一次(原逻辑是 firstface_frame 标记，这里简化为每批次如果没检测过就检测)
    #     # 如果是分批处理，通常第一批就会完成检测
    #     is_4k = False
    #     need_restore = False
        
    #     # 遍历当前批次的帧进行判断
    #     for frame in frame_list:
    #         # if frame.shape[0] >= 3840 or frame.shape[1] >= 3840:
    #         #     logger.info(f'[{code}] -> video frame shape is 4k, skip chaofen')
    #         #     is_4k = True
    #         #     break
            
    #         bboxes_scrfd, kpss_scrfd = fd.get_bboxes(frame)
    #         if len(bboxes_scrfd) == 0:
    #             continue
                
    #         face_image_, mat_rev_, roi_box_ = get_single_face(bboxes_scrfd, kpss_scrfd, frame, crop_size=512, mode='mtcnn_512', apply_roi=True)
    #         if face_image_ is not None:
    #             face_attr_res = face_blur_detect.forward(face_image_)
    #             blur_threshold = face_attr_res[0][-2]
    #             logger.info(f'[{code}] -> frame_id:[{frame_id}] 模糊置信度:[{blur_threshold}]')
                
    #             if blur_threshold > GlobalConfig.instance().blur_threshold:
    #                 logger.info(f'[{code}] -> need chaofen (auto detected).')
    #                 need_restore = True
    #             # 只要检测到有效人脸，无论是否模糊，都算检测完成（除非要等模糊的出现，但原逻辑是break）
    #             break
        
    #     task_state['checked'] = True
    #     task_state['need_chaofen'] = (not is_4k) and need_restore

    # 判定不需要超分
    if chaofen_ctrl == 0:
        return frame_list

    # 执行超分
    new_frame_list = []
    for i in range(len(frame_list)):
        frame = frame_list[i]
        try:
            bboxes_scrfd, kpss_scrfd = fd.get_bboxes(frame)
            if len(bboxes_scrfd) == 0:
                new_frame_list.append(frame)
                continue
            face_image_, mat_rev_, roi_box_ = get_single_face(bboxes_scrfd, kpss_scrfd, frame, crop_size=512, mode='mtcnn_512', apply_roi=True)
            if face_image_ is None:
                 new_frame_list.append(frame)
                 continue
            
            face_restore_out_ = gfpgan.forward(face_image_)
            restore_roi = CVImage(None).recover_from_reverse_matrix(face_restore_out_, frame[:, roi_box_[1]:roi_box_[3], roi_box_[0]:roi_box_[2]], mat_rev_, img_fg_mask=face_mask)
            frame[:, roi_box_[1]:roi_box_[3], roi_box_[0]:roi_box_[2]] = restore_roi
            new_frame_list.append(frame)
        except Exception as e:
            logger.error(f'[{code}] Chaofen error: {e}')
            new_frame_list.append(frame)

    torch.cuda.empty_cache()
    logger.info(f'[{frame_id}] -> chaofen cost:{time.time() - s_chao}s')
    return new_frame_list


def audio_transfer(drivered_queue, output_imgs_queue, batch_size, terminate_event=None):
    """
    数字人图片处理进程

    Args:
        drivered_queue: 输入队列
        output_imgs_queue: 输出队列
        batch_size: 批处理大小
        terminate_event: 终止信号事件（可选）
    """
    # 先加载模型，再抑制控制台输出，以便捕获模型加载错误
    output_resize = 1
    try:
        logger.info('>>> audio_transfer: 开始加载模型...')
        digital_human_model = DigitalHumanModel(GlobalConfig.instance().blend_dynamic, GlobalConfig.instance().chaofen_before, face_blur_detect=False)
        logger.info('>>> audio_transfer: DigitalHumanModel 加载成功')
        scrfd_detector = FaceDetect(cpu=False, model_path='face_detect_utils/resources/')
        logger.info('>>> audio_transfer: FaceDetect 加载成功')
        scrfd_predictor = pfpld(cpu=False, model_path='face_detect_utils/resources/')
        logger.info('>>> audio_transfer: pfpld 加载成功')
        hp = Headpose(cpu=False, onnx_path='face_detect_utils/resources/model_float32.onnx')
        logger.info('>>> audio_transfer: Headpose 加载成功')
    except Exception as e:
        logger.error(f'>>> audio_transfer: 模型加载失败: {e}')
        logger.error(traceback.format_exc())
        # 通知主进程加载失败
        output_imgs_queue.put([False, f'模型加载失败: {e}', 'INIT'])
        return

    # 模型加载成功后，抑制控制台输出
    suppress_console_output()  # 抑制控制台输出

    # 【修改点7】状态字典，用于存储不同任务的超分状态
    task_chaofen_states = {}

    task_tracking_states = {}

    logger.info('>>> 数字人图片处理进程启动')

    # GPU 模型列表，用于清理时释放
    gpu_models = [digital_human_model, scrfd_detector, scrfd_predictor, hp]

    while True:
        # 检查终止信号
        if terminate_event is not None and terminate_event.is_set():
            logger.info('>>> 数字人图片处理进程收到终止信号，正在清理...')
            # 释放 GPU 模型
            for model in gpu_models:
                try:
                    if hasattr(model, 'cleanup'):
                        model.cleanup()
                    del model
                except Exception:
                    pass
            torch.cuda.empty_cache()
            gc.collect()
            logger.info('>>> 数字人图片处理进程已退出')
            break

        try:
            # 使用超时获取，避免永久阻塞
            try:
                queue_values = drivered_queue.get(timeout=1.0)
            except Empty:
                continue

            s_au = time.time()

            # 【修改点8】解析队列数据，处理结束/异常信号清理状态
            if len(queue_values) == 3:
                state, msg, code = queue_values
                # 清理任务状态
                if code in task_chaofen_states:
                    del task_chaofen_states[code]

                
                if code in task_tracking_states:
                    del task_tracking_states[code]
                    logger.info(f'[{code}] 已清理人脸追踪状态')

                if state is True:
                    logger.info(f'[{code}]任务数字人图片处理已完成')
                    output_imgs_queue.put([True, 'success', code])
                else:
                    logger.info(f'[{code}]任务数字人图片处理异常结束')
                    output_imgs_queue.put([False, msg, code])
                torch.cuda.empty_cache()
                continue
            
            # 正常数据处理
            # 解包队列数据，支持向后兼容
            target_face_id = 0
            # 优先使用队列中的 batch_size，如果没有则使用函数参数（向后兼容）
            this_batch_size = batch_size  # 默认值（向后兼容）

            if len(queue_values) >= 8:
                # 新格式：包含 batch_size
                img_list, audio_feature_list, code, wh, frameId, chaofen_ctrl, target_face_id, this_batch_size = queue_values
            elif len(queue_values) == 7:
                img_list, audio_feature_list, code, wh, frameId, chaofen_ctrl, target_face_id = queue_values
            elif len(queue_values) == 6:
                img_list, audio_feature_list, code, wh, frameId, chaofen_ctrl = queue_values
                target_face_id = 0  # 旧格式默认单人
            else:
                img_list, audio_feature_list, code, wh, frameId = queue_values
                target_face_id = 0  # 旧格式默认单人

            # 移除详细日志输出以提升性能（每个batch节省~40-50ms）
            # logger.info(f'>>> audio_transfer get message:{frameId}, ctrl:{chaofen_ctrl}, target_face_id:{target_face_id}, batch_size:{this_batch_size}')

            out_shape = img_list[0].shape
            last_center = task_tracking_states.get(code, None)

            detector_wrapper = FaceSelectWrapper(scrfd_detector,target_face_id,last_center=last_center)

            # 预处理超分已移除: 超分统一在口型渲染后由 write_video_chaofen 后处理阶段执行

            caped_drivered_img2 = warp_imgs(img_list)
            if wh == 0 or wh == -1:
                wh = digital_human_model.drivered_wh
            drivered_op = op(caped_drivered_img2, wh, detector_wrapper, scrfd_predictor, hp, None, digital_human_model.img_size, False, target_face_id)
            drivered_op.flow()


            if detector_wrapper.last_center is not None:
                task_tracking_states[code] = detector_wrapper.last_center

            drivered_face_dict = drivered_op.mp_dict

            # 检查是否为多脸模式
            is_multi_face = False
            if len(drivered_face_dict) > 0:
                first_bbox = drivered_face_dict[0].get('bounding_box', None)
                if first_bbox is not None:
                    # 如果是列表，说明是多脸模式
                    is_multi_face = isinstance(first_bbox, list)

            # 多脸模式：展开数据但保持原始帧索引的映射
            if is_multi_face:
                # logger.info(f'[多脸模式] 开始展开多脸数据')  # 移除日志提升性能
                # 创建新的字典来存储展开后的脸数据
                expanded_dict = {}
                new_idx = 0

                for orig_idx in range(len(drivered_face_dict)):
                    face_data = drivered_face_dict[orig_idx]
                    bounding_boxes = face_data.get('bounding_box', [])
                    landmarks = face_data.get('landmarks', [])
                    bounding_box_p = face_data.get('bounding_box_p', [])
                    crop_lms = face_data.get('crop_lm', [])
                    crop_imgs = face_data.get('crop_img', [])

                    if isinstance(bounding_boxes, list) and len(bounding_boxes) > 0:
                        # 多脸模式：展开每张脸
                        for face_idx in range(min(len(bounding_boxes), 2)):  # 最多2张脸
                            # 为每张脸创建独立的字典条目
                            expanded_dict[new_idx] = {
                                'imgs_data': face_data['imgs_data'],  # 保持原始图像引用
                                'orig_frame_idx': orig_idx,  # 记录原始帧索引
                                'face_idx_in_frame': face_idx,  # 记录是该帧的第几张脸
                                'bounding_box': bounding_boxes[face_idx],
                                'landmarks': landmarks[face_idx] if isinstance(landmarks, list) and face_idx < len(landmarks) else landmarks,
                                'bounding_box_p': bounding_box_p[face_idx] if isinstance(bounding_box_p, list) and face_idx < len(bounding_box_p) else bounding_box_p,
                                'crop_lm': crop_lms[face_idx] if isinstance(crop_lms, list) and face_idx < len(crop_lms) else None,
                                'crop_img': crop_imgs[face_idx] if isinstance(crop_imgs, list) and face_idx < len(crop_imgs) else None,
                            }
                            new_idx += 1
                    else:
                        # 单脸模式：保持原样
                        expanded_dict[orig_idx] = face_data

                # 替换原始字典
                drivered_face_dict = expanded_dict
                # logger.info(f'[多脸模式] 展开完成: {len(expanded_dict)} 个脸条目')  # 移除日志提升性能

                # 对展开后的数据进行平滑处理（按脸索引分组）
                if len(drivered_face_dict) > 1:
                    # 收集每帧的脸数量
                    face_counts = {}
                    for idx in drivered_face_dict.keys():
                        orig_idx = drivered_face_dict[idx].get('orig_frame_idx', idx)
                        face_in_frame = drivered_face_dict[idx].get('face_idx_in_frame', 0)
                        if face_in_frame not in face_counts:
                            face_counts[face_in_frame] = 0
                        face_counts[face_in_frame] += 1

                    # 对每张脸（第0张、第1张）分别平滑
                    for face_in_frame in face_counts.keys():
                        # 收集该脸的所有bounding_box
                        bbox_list = []
                        valid_indices = []

                        for idx in sorted(drivered_face_dict.keys()):
                            if drivered_face_dict[idx].get('face_idx_in_frame', -1) == face_in_frame:
                                bbox = drivered_face_dict[idx].get('bounding_box', None)
                                if bbox is not None and len(bbox) == 4:
                                    bbox_list.append(bbox)
                                    valid_indices.append(idx)
                                else:
                                    bbox_list.append(None)
                                    valid_indices.append(idx)

                        # 至少需要5帧才能平滑
                        valid_data = [b for b in bbox_list if b is not None]
                        if len(valid_data) > 5:
                            bbox_array = np.array(valid_data)

                            # 使用numpy的移动平均（比scipy.signal.convolve2d快）
                            window_size = 5
                            weights = np.ones(window_size) / window_size

                            # 对每个坐标应用移动平均
                            for coord_idx in range(4):
                                coord_data = bbox_array[:, coord_idx]
                                # 使用numpy的convolve（更快的1D卷积）
                                smoothed = np.convolve(coord_data, weights, mode='same')

                                # 边界处理：用原始值填充
                                half_window = window_size // 2
                                smoothed[:half_window] = coord_data[:half_window]
                                smoothed[-half_window:] = coord_data[-half_window:]

                                # 更新平滑后的坐标
                                valid_idx = 0
                                for i, idx in enumerate(valid_indices):
                                    if bbox_list[i] is not None:
                                        drivered_face_dict[idx]['bounding_box'][coord_idx] = smoothed[valid_idx]
                                        valid_idx += 1

            # 优化2: 合并多次遍历为一次（节省 ~20-30ms/batch）
            x1_list, x2_list, y1_list, y2_list = ([], [], [], [])
            keylist = sorted(drivered_face_dict.keys())

            # 记录上一个有效数据用于修复异常
            last_valid_data = None

            for i, it in enumerate(keylist):
                face_data = drivered_face_dict[it]

                # 1. 构建坐标列表
                facebox = face_data['bounding_box']
                x1_list.append(facebox[0])
                x2_list.append(facebox[1])
                y1_list.append(facebox[2])
                y2_list.append(facebox[3])

                # 2. 检测并修复异常数据（合并到同一循环）
                if len(face_data['bounding_box_p']) != 4:
                    if i > 0 and last_valid_data is not None:
                        # 使用上一个有效数据修复
                        face_data['bounding_box_p'] = last_valid_data['bounding_box_p']
                        face_data['bounding_box'] = last_valid_data['bounding_box']
                        face_data['crop_lm'] = last_valid_data['crop_lm']
                        face_data['crop_img'] = last_valid_data['crop_img']
                    else:
                        # 第一个就异常，尝试用下一个
                        if i + 1 < len(keylist):
                            next_key = keylist[i + 1]
                            next_data = drivered_face_dict[next_key]
                            face_data['bounding_box_p'] = next_data['bounding_box_p']
                            face_data['bounding_box'] = next_data['bounding_box']
                            face_data['crop_lm'] = next_data['crop_lm']
                            face_data['crop_img'] = next_data['crop_img']
                else:
                    # 记录当前有效数据供后续使用
                    last_valid_data = {
                        'bounding_box_p': face_data['bounding_box_p'],
                        'bounding_box': facebox,
                        'crop_lm': face_data['crop_lm'],
                        'crop_img': face_data['crop_img']
                    }
            # 构建params：多脸模式传入drivered_face_dict，单脸模式传入img_list
            if is_multi_face:
                params = [out_shape, output_resize, drivered_face_dict, y1_list, y2_list, x1_list, x2_list]
            else:
                params = [out_shape, output_resize, img_list, y1_list, y2_list, x1_list, x2_list]

            output_imgs = get_blend_imgs(this_batch_size, audio_feature_list, drivered_face_dict, GlobalConfig.instance().blend_dynamic, params, digital_human_model, frameId, target_face_id)
            if len(drivered_op.no_face) != 0:
                for id in drivered_op.no_face:
                    output_imgs[id] = img_list[id]
            output_imgs_queue.put([0, 0, output_imgs])
            # logger.info(f'audio_transfer >>>>>>>>>>> 发送完成数据大小:{len(output_imgs)}, frameId:{frameId}, cost:{time.time() - s_au}s')  # 移除日志提升性能
            torch.cuda.empty_cache()
        except Exception as e:
            logger.error(traceback.format_exc())
            output_imgs_queue.put([False, f'数字人处理失败，失败原因:[{e.__str__()}]', ''])
            time.sleep(1)
            torch.cuda.empty_cache()
    logger.info('数字人进程结束')


def write_video(output_imgs_queue, temp_dir, result_dir, work_id, audio_path, result_queue, width, height, fps, watermark_switch=0, digital_auth=0, output_path=None):
    suppress_console_output()  # 抑制控制台输出
    output_mp4 = os.path.join(temp_dir, f'{work_id}-t.mp4')
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    # 支持自定义输出路径，避免额外的文件复制
    if output_path:
        result_path = output_path
    else:
        result_path = os.path.join(result_dir, f'{work_id}-r.mp4')
    video_write = cv2.VideoWriter(output_mp4, fourcc, fps, (width, height))
    try:
        while True:
            state, reason, value_ = output_imgs_queue.get()
            if type(state) == bool and state == True:
                logger.info(f'[{work_id}]视频帧队列处理已结束')
                break
            if type(state) == bool and state == False:
                logger.error(f'[{work_id}]任务视频帧队列 -> 异常原因:[{reason}]')
                raise CustomError(reason)
            for result_img in value_:
                video_write.write(result_img)
        video_write.release()
        if watermark_switch == 1 and digital_auth == 1:
            logger.info(f'[{work_id}]任务需要水印和数字人标识')
            if width > height:
                command = f'ffmpeg -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().watermark_path} -i {GlobalConfig.instance().digital_auth_path} -filter_complex "overlay=(main_w-overlay_w)-10:(main_h-overlay_h)-10,overlay=(main_w-overlay_w)-10:10" -c:a aac -crf 15 -strict -2 {result_path}'
                logger.info(f'command:{command}')
            else:
                command = f'ffmpeg -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().watermark_path} -i {GlobalConfig.instance().digital_auth_path} -filter_complex "overlay=(main_w-overlay_w)-10:(main_h-overlay_h)-10,overlay=(main_w-overlay_w)-10:10" -c:a aac -crf 15 -strict -2 {result_path}'
                logger.info(f'command:{command}')
        elif watermark_switch == 1 and digital_auth == 0:
            logger.info(f'[{work_id}]任务需要水印')
            command = f'ffmpeg -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().watermark_path} -filter_complex "overlay=(main_w-overlay_w)-10:(main_h-overlay_h)-10" -c:a aac -crf 15 -strict -2 {result_path}'
            logger.info(f'command:{command}')
        elif watermark_switch == 0 and digital_auth == 1:
            logger.info(f'[{work_id}]任务需要数字人标识')
            if width > height:
                command = f'ffmpeg -loglevel warning -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().digital_auth_path} -filter_complex "overlay=(main_w-overlay_w)-10:10" -c:a aac -crf 15 -strict -2 {result_path}'
                logger.info(f'command:{command}')
            else:
                command = f'ffmpeg -loglevel warning -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().digital_auth_path} -filter_complex "overlay=(main_w-overlay_w)-10:10" -c:a aac -crf 15 -strict -2 {result_path}'
                logger.info(f'command:{command}')
        else:
            command = f'ffmpeg -loglevel warning -y -i {audio_path} -i {output_mp4} -c:a aac -c:v libx264 -crf 15 -strict -2 {result_path}'
            logger.info(f'command:{command}')
        run_silent(command)
        logger.debug('write over')
        result_queue.put([True, result_path])
    except Exception as e:
        logger.error(f'[{work_id}]视频帧队列处理异常结束，异常原因:[{e.__str__()}]')
        result_queue.put([False, f'[{work_id}]视频帧队列处理异常结束，异常原因:[{e.__str__()}]'])
    logger.info('后处理进程结束')


def save_video_ffmpeg(input_video_path, output_video_path):
    audio_file_path = input_video_path.replace('.mp4', '.aac')
    if not os.path.exists(audio_file_path):
        run_silent(f'ffmpeg -y -hide_banner -loglevel error -i "{str(input_video_path)}" -f wav -vn  "{str(audio_file_path)}"')
    if os.path.exists(audio_file_path):
        os.rename(output_video_path, output_video_path.replace('.mp4', '_no_audio.mp4'))
        start = time.time()
        run_silent(f'ffmpeg -y -hide_banner -loglevel error  -i "{str(output_video_path.replace(".mp4", "_no_audio.mp4"))}" -i "{str(audio_file_path)}" -c:v libx264 "{str(output_video_path)}"')
        logger.debug(f'add audio time cost: {time.time() - start:.2f}s')
        os.remove(output_video_path.replace('.mp4', '_no_audio.mp4'))
        os.remove(audio_file_path)
    return output_video_path


class FaceDetectThread(Linker):
    """人脸检测线程, 支持 target_face_id 选择指定人脸"""

    def __init__(self, queue_list, target_face_id=0):
        super().__init__(queue_list, fps_counter=False)
        self.fd = FaceDetect5Landmarks(mode='scrfd_500m')
        self.target_face_id = target_face_id
        self.last_center = None  # 用于帧间追踪

    def forward_func(self, something_in):
        frame = something_in
        bboxes_scrfd, kpss_scrfd = self.fd.get_bboxes(frame, min_bbox_size=64)
        if len(bboxes_scrfd) == 0:
            return [frame, None, None, None]

        # 根据 target_face_id 选择目标人脸
        if self.target_face_id == -1:
            # 超分所有检测到的人脸: 逐个处理, 只返回第一个(后续帧需多次调用)
            # 当前流水线架构只支持单脸超分, -1 模式下选择最大人脸
            selected_idx = np.argmax((bboxes_scrfd[:, 2] - bboxes_scrfd[:, 0]) *
                                     (bboxes_scrfd[:, 3] - bboxes_scrfd[:, 1]))
        else:
            # 计算所有人脸的中心点
            centers = np.vstack([
                (bboxes_scrfd[:, 0] + bboxes_scrfd[:, 2]) / 2,
                (bboxes_scrfd[:, 1] + bboxes_scrfd[:, 3]) / 2
            ]).T

            if self.last_center is None:
                # 第一帧: 按 Y 坐标从上到下排序选择
                sorted_indices = np.argsort(centers[:, 1])
                selected_idx = sorted_indices[min(self.target_face_id, len(bboxes_scrfd) - 1)]
            else:
                # 后续帧: 追踪距离最近的人脸
                distances = np.linalg.norm(centers - self.last_center, axis=1)
                selected_idx = np.argmin(distances)

            # 更新追踪状态(带平滑)
            current_center = centers[selected_idx]
            if self.last_center is None:
                self.last_center = current_center
            else:
                self.last_center = 0.7 * current_center + 0.3 * self.last_center

        # 只保留选中人脸的 bbox 和 kps
        self.fd.bboxes = bboxes_scrfd[selected_idx:selected_idx+1]
        self.fd.kpss = kpss_scrfd[selected_idx:selected_idx+1]
        face_image_, mat_rev_, roi_box_ = self.fd.get_single_face(crop_size=512, mode='mtcnn_512', apply_roi=True)
        return [frame, face_image_, mat_rev_, roi_box_]


class FaceRestoreThread(Linker):

    def __init__(self, queue_list):
        super().__init__(queue_list, fps_counter=False)
        # 模型路径: 优先使用项目根目录 models/gfpgan/, 回退到原有 pretrain_models 路径
        from face_lib.face_restore.gfpgan_onnx import gfpgan_onnx_api
        _gfpgan_model_path = _resolve_gfpgan_model_path()
        if _gfpgan_model_path and os.path.exists(_gfpgan_model_path):
            gfpgan_onnx_api.MODEL_ZOO['GFPGANv1.4']['model_path'] = _gfpgan_model_path
        self.gfp = GFPGAN(model_type='GFPGANv1.4', provider='gpu')

    def forward_func(self, something_in):
        src_face_image_ = something_in[1]
        if src_face_image_ is None:
            return [None] + something_in
        face_restore_out_ = self.gfp.forward(src_face_image_)
        torch.cuda.empty_cache()
        return [face_restore_out_] + something_in


class FaceParseThread(Linker):

    def __init__(self, queue_list):
        super().__init__(queue_list, fps_counter=False)
        self.face_mask_ = self.get_face_mask(mask_shape=(512, 512))

    def get_face_mask(self, mask_shape):
        mask = np.zeros((512, 512)).astype(np.float32)
        cv2.ellipse(mask, (256, 256), (220, 160), 90, 0, 360, (255, 255, 255), -1)
        thres = 20
        mask[:thres, :] = 0
        mask[-thres:, :] = 0
        mask[:, :thres] = 0
        mask[:, -thres:] = 0
        mask = cv2.stackBlur(mask, (201, 201))
        mask = mask / 255
        mask = cv2.resize(mask, mask_shape)
        return mask[..., np.newaxis]

    def forward_func(self, something_in):
        if something_in[0] is None:
            return something_in + [None]
        return something_in + [self.face_mask_]


class FaceReverseThread(Linker):

    def __init__(self, queue_list):
        super().__init__(queue_list, fps_counter=False)
        self.counter = 0
        self.start_time = time.time()

    def forward_func(self, something_in):
        face_restore_out = something_in[0]
        src_img_in = something_in[1]
        if face_restore_out is not None:
            mat_rev = something_in[3]
            roi_box = something_in[4]
            face_mask_ = something_in[5]
            restore_roi = CVImage(None).recover_from_reverse_matrix(face_restore_out, src_img_in[:, roi_box[1]:roi_box[3], roi_box[0]:roi_box[2]], mat_rev, img_fg_mask=face_mask_)
            src_img_in[:, roi_box[1]:roi_box[3], roi_box[0]:roi_box[2]] = restore_roi
        return [src_img_in]


def write_video_chaofen(output_imgs_queue, temp_dir, result_dir, work_id, audio_path, result_queue, width, height, fps, watermark_switch=0, digital_auth=0, output_path=None, target_face_id=0):
    suppress_console_output()  # 抑制控制台输出
    output_mp4 = os.path.join(temp_dir, f'{work_id}-t.mp4')
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    # 支持自定义输出路径，避免额外的文件复制
    if output_path:
        result_path = output_path
    else:
        result_path = os.path.join(result_dir, f'{work_id}-r.mp4')
    video_write = cv2.VideoWriter(output_mp4, fourcc, fps, (width, height))
    try:
        q0 = Queue(2)
        q1 = Queue(2)
        q2 = Queue(2)
        q3 = Queue(2)
        q4 = Queue(2)
        fdt = FaceDetectThread([q0, q1], target_face_id=target_face_id)
        frt = FaceRestoreThread([q1, q2])
        fpt = FaceParseThread([q2, q3])
        fret = FaceReverseThread([q3, q4])
        cvvwt = CVVideoWriterThread(video_write, [q4])
        threads_list = [fdt, frt, fpt, fret, cvvwt]
        for thread_ in threads_list:
            thread_.start()
        while True:
            state, reason, value_ = output_imgs_queue.get()
            if type(state) == bool and state == True:
                logger.info(f'[{work_id}]视频帧队列处理已结束')
                q0.put(None)
                for thread_ in threads_list:
                    thread_.join()
                break
            if type(state) == bool and state == False:
                logger.error(f'[{work_id}]任务视频帧队列 -> 异常原因:[{reason}]')
                q0.put(None)
                for thread_ in threads_list:
                    thread_.join()
                raise CustomError(reason)
            for result_img in value_:
                q0.put(result_img)
        video_write.release()
        if watermark_switch == 1 and digital_auth == 1:
            logger.info(f'[{work_id}]任务需要水印和数字人标识')
            if width > height:
                command = f'ffmpeg -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().watermark_path} -i {GlobalConfig.instance().digital_auth_path} -filter_complex "overlay=(main_w-overlay_w)-10:(main_h-overlay_h)-10,overlay=(main_w-overlay_w)-10:10" -c:a aac -crf 15 -strict -2 {result_path}'
                logger.info(f'command:{command}')
            else:
                command = f'ffmpeg -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().watermark_path} -i {GlobalConfig.instance().digital_auth_path} -filter_complex "overlay=(main_w-overlay_w)-10:(main_h-overlay_h)-10,overlay=(main_w-overlay_w)-10:10" -c:a aac -crf 15 -strict -2 {result_path}'
                logger.info(f'command:{command}')
        elif watermark_switch == 1 and digital_auth == 0:
            logger.info(f'[{work_id}]任务需要水印')
            command = f'ffmpeg -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().watermark_path} -filter_complex "overlay=(main_w-overlay_w)-10:(main_h-overlay_h)-10" -c:a aac -crf 15 -strict -2 {result_path}'
            logger.info(f'command:{command}')
        elif watermark_switch == 0 and digital_auth == 1:
            logger.info(f'[{work_id}]任务需要数字人标识')
            if width > height:
                command = f'ffmpeg -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().digital_auth_path} -filter_complex "overlay=(main_w-overlay_w)-10:10" -c:a aac -crf 15 -strict -2 {result_path}'
                logger.info(f'command:{command}')
            else:
                command = f'ffmpeg -y -i {audio_path} -i {output_mp4} -i {GlobalConfig.instance().digital_auth_path} -filter_complex "overlay=(main_w-overlay_w)-10:10" -c:a aac -crf 15 -strict -2 {result_path}'
                logger.info(f'command:{command}')
        else:
            command = f'ffmpeg -y -i {audio_path} -i {output_mp4} -c:a aac -c:v libx264 -crf 15 -strict -2 {result_path}'
            logger.info(f'command:{command}')
        run_silent(command)
        logger.debug('write over')
        result_queue.put([True, result_path])
    except Exception as e:
        logger.error(f'[{work_id}]视频帧队列处理异常结束，异常原因:[{e.__str__()}]')
        result_queue.put([False, f'[{work_id}]视频帧队列处理异常结束，异常原因:[{e.__str__()}]'])
    logger.info('后处理进程结束')


def video_synthesis(output_imgs_queue):
    img_id = 0
    st = time.time()
    while output_imgs_queue.empty():
        et = time.time()
        logger.debug(f'表情迁移首次出现耗时: {et - st:.2f}s')
        output_imgs = output_imgs_queue.get()
        for img in output_imgs:
            time.sleep(0.03125)
            cv2.imshow('output_imgs', img)
            cv2.waitKey(1)
        st = time.time()


def hy_fun(wenet_model, audio_path, drivered_path, output_dir, work_id):
    # 【关键修复】在创建子进程之前隐藏父进程的控制台窗口
    # 这样子进程会继承父进程的隐藏状态，避免窗口闪烁
    set_console_window_hidden()

    # 增大队列大小，避免长音频导致阻塞
    drivered_queue = multiprocessing.Queue(50)
    output_imgs_queue = multiprocessing.Queue(50)
    result_queue = multiprocessing.Queue(1)
    process_list = []
    audio_wenet_feature = get_aud_feat1(audio_path, fps=30, wenet_model=wenet_model)
    process_list.append(Process(target=drivered_video, args=(drivered_queue, drivered_path, audio_wenet_feature)))
    process_list.append(Process(target=audio_transfer, args=(drivered_queue, output_imgs_queue)))
    process_list.append(Process(target=write_video, args=(output_imgs_queue, output_dir, output_dir, work_id, audio_path, result_queue)))
    [p.start() for p in process_list]
    [p.join() for p in process_list]
    logger.debug('主进程结束')
    try:
        result_path = result_queue.get(timeout=10)
        return (0, result_path)
    except Empty:
        return (1, 'generate error')


class Status(Enum):
    run = 1
    success = 2
    error = 3


def init_wh_process(in_queue, out_queue, terminate_event=None):
    """
    初始化宽高进程

    Args:
        in_queue: 输入队列
        out_queue: 输出队列
        terminate_event: 终止信号事件（可选）
    """
    suppress_console_output()  # 抑制控制台输出
    try:
        logger.info('>>> init_wh_process 开始加载模型...')
        s_model = time.time()
        face_detector = FaceDetect(cpu=False, model_path='face_detect_utils/resources/')
        plfd = pfpld(cpu=False, model_path='face_detect_utils/resources/')
        logger.info(f'>>> init_wh_process 模型加载完成，耗时：{time.time() - s_model:.2f}s')
        logger.info('>>> init_wh_process 进程启动')

        # 发送就绪信号到输出队列
        out_queue.put(['__INIT_READY__', 0, False])
        logger.info('>>> init_wh_process 已发送就绪信号')
    except Exception as e:
        logger.error(f'>>> init_wh_process 模型加载失败：{e}')
        out_queue.put(['__INIT_ERROR__', str(e), False])
        return

    # GPU 模型列表，用于清理时释放
    gpu_models = [face_detector, plfd]

    while True:
        # 检查终止信号
        if terminate_event is not None and terminate_event.is_set():
            logger.info('>>> init_wh_process 收到终止信号，正在清理...')
            # 释放 GPU 模型
            for model in gpu_models:
                try:
                    if hasattr(model, 'cleanup'):
                        model.cleanup()
                    del model
                except Exception:
                    pass
            torch.cuda.empty_cache()
            gc.collect()
            logger.info('>>> init_wh_process 已退出')
            break

        try:
            # 使用超时获取，避免永久阻塞
            try:
                queue_data = in_queue.get(timeout=1.0)
            except Empty:
                continue
            code = queue_data[0]
            driver_path = queue_data[1]
            logger.info(f'[{code}] init_wh_process 开始处理: {driver_path}')
            s_task = time.time()
            # try:
            #     with open("face_lib/face.json", "r", encoding="utf-8") as file:
            #         target_face_id_data = json.load(file)
            #         target_face_id = int(target_face_id_data.get("face_id", 0))
            # except Exception as e:
            #     print(str(e))
            #     target_face_id = 0

            target_face_id = 0
            if len(queue_data) > 2:
                target_face_id = int(queue_data[2])

            logger.debug(f"target_face_id: {target_face_id}")

            s = time.time()
            wh_list = []
            cap = cv2.VideoCapture(driver_path)
            count = 0
            has_multi_face = False
            try:
                try:
                    while cap.isOpened() and count < 100:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        bboxes = []
                        try:
                            bboxes, kpss = face_detector.get_bboxes(frame)
                        except Exception as e:
                            logger.error(f'[{code}]init_wh exception: {e}')
                        
                        bboxes_len = len(bboxes)
                        if bboxes_len > 0:
                            if bboxes_len > 1:
                                has_multi_face = True
                            
                            # 【修改点2】核心排序逻辑：从上到下 (Top-to-Bottom)
                            # 计算每个 bbox 的中心点 Y 坐标
                            center_ys = (bboxes[:, 1] + bboxes[:, 3]) / 2
                            # argsort 返回从小到大(从上到下)的索引
                            sorted_indices = np.argsort(center_ys)
                            
                            # 获取目标索引，防止越界
                            idx = sorted_indices[min(target_face_id, bboxes_len - 1)]
                            
                            # 取出指定的那张脸
                            bbox = bboxes[idx]
                            
                            # --- 以下原有逻辑保持不变 ---
                            x1, y1, x2, y2, score = bbox.astype(int)
                            x1 = max(x1 - int((x2 - x1) * 0.1), 0)
                            x2 = x2 + int((x2 - x1) * 0.1)
                            y2 = y2 + int((y2 - y1) * 0.1)
                            y1 = max(y1, 0)
                            face_img = frame[y1:y2, x1:x2]
                            
                            # 只有当裁剪区域有效时才计算
                            if face_img.size != 0:
                                pots = plfd.forward(face_img)[0]
                                landmarks = np.array([[(x1 + x), (y1 + y)] for x, y in pots.astype(np.int32)])
                                xmin, ymin, w, h = cv2.boundingRect(np.array(landmarks))
                                if h > 0:
                                    wh_list.append(w / h)
                        count += 1
                except Exception as e1:
                    logger.error(f'[{code}]init_wh exception: {e1}')
            finally:
                cap.release()
            
            if len(wh_list) == 0:
                wh = 0
            else:
                wh = np.mean(np.array(wh_list))
                
            logger.info(f'[{code}]init_wh result :[{wh}], cost: {time.time() - s:.2f}s, 总耗时：{time.time() - s_task:.2f}s')
            torch.cuda.empty_cache()
            out_queue.put([code, wh, has_multi_face])
        except Exception as e:
            logger.error(f'init_wh 异常: {traceback.format_exc()}')
            out_queue.put([f'init_wh，失败原因:[{e.args}]', '', False])
            torch.cuda.empty_cache()


def init_wh(code, drivered_path, target_face_id=0):
    """
    计算驱动视频的人脸宽高比(WH)
    修改：增加 target_face_id，并支持按从上到下顺序选择人脸
    """

    # try:
    #     with open("face_lib/face.json", "r", encoding="utf-8") as file:
    #         target_face_id_data = json.load(file)
    #         target_face_id = int(target_face_id_data.get("face_id", 0))
    # except Exception as e:
    #     print(str(e))
    #     target_face_id = 0

    logger.debug(f"target_face_id: {target_face_id}")

    s = time.time()
    face_detector = FaceDetect(cpu=False, model_path='face_detect_utils/resources/')
    plfd = pfpld(cpu=False, model_path='face_detect_utils/resources/')
    wh_list = []
    cap = cv2.VideoCapture(drivered_path)
    count = 0
    try:
        try:
            # 只读取前100帧进行采样
            while cap.isOpened() and count < 100:
                ret, frame = cap.read()
                if not ret:
                    break
                try:
                    bboxes, kpss = face_detector.get_bboxes(frame)
                except Exception as e:
                    logger.error(f'[{code}]init_wh exception: {e}')
                    continue # 遇到检测异常跳过当前帧

                if len(bboxes) > 0:
                    # 【核心修改开始】 ---------------------------------------
                    # 计算所有检测框中心点的 Y 坐标 (y1 + y2) / 2
                    center_ys = (bboxes[:, 1] + bboxes[:, 3]) / 2
                    
                    # 按 Y 坐标从小到大排序 (即从上到下)
                    sorted_indices = np.argsort(center_ys)
                    
                    # 获取目标索引，防止越界（如果指定第3张脸但只有2张，则取最后一张）
                    idx = sorted_indices[min(target_face_id, len(bboxes) - 1)]
                    
                    # 锁定目标人脸
                    bbox = bboxes[idx]
                    # 【核心修改结束】 ---------------------------------------

                    x1, y1, x2, y2, score = bbox.astype(int)
                    x1 = max(x1 - int((x2 - x1) * 0.1), 0)
                    x2 = x2 + int((x2 - x1) * 0.1)
                    y2 = y2 + int((y2 - y1) * 0.1)
                    y1 = max(y1, 0)
                    
                    face_img = frame[y1:y2, x1:x2]
                    
                    # 确保裁剪区域有效
                    if face_img.size != 0:
                        pots = plfd.forward(face_img)[0]
                        landmarks = np.array([[(x1 + x), (y1 + y)] for x, y in pots.astype(np.int32)])
                        
                        # 计算 landmarks 的外接矩形
                        xmin, ymin, w, h = cv2.boundingRect(np.array(landmarks))
                        
                        if h > 0: # 防止除以0
                            wh_list.append(w / h)
                
                count += 1
        except Exception as e1:
            logger.error(f'[{code}]init_wh exception: {e1}')
    finally:
        cap.release()
        
    if len(wh_list) == 0:
        wh = 0
    else:
        wh = np.mean(np.array(wh_list))
        
    logger.info(f'[{code}]init_wh result :[{wh}], cost: {time.time() - s:.2f}s, 总耗时：{time.time() - s_task:.2f}s')
    torch.cuda.empty_cache()
    return wh


def get_video_info(video_file):
    cap = cv2.VideoCapture(video_file)
    fps = round(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    cap.release()
    return (fps, width, height, fourcc)


def format_video_audio(code, video_path, audio_path, fourcc):
    if fourcc == cv2.VideoWriter_fourcc(*'H264') or fourcc == cv2.VideoWriter_fourcc(*'avc1') or fourcc == cv2.VideoWriter_fourcc(*'h264'):
        ffmpeg_command = 'ffmpeg -loglevel warning -i %s -crf 15 -vcodec copy -an -y %s'
    else:
        ffmpeg_command = 'ffmpeg -loglevel warning -i %s -c:v libx264 -crf 15 -an -y %s'
    video_format = os.path.join(GlobalConfig.instance().temp_dir, code + '_format.mp4')
    ffmpeg_command = ffmpeg_command % (video_path, video_format)
    logger.info(f'[{code}] -> ffmpeg video: {ffmpeg_command}')
    run_silent(ffmpeg_command)
    if not os.path.exists(video_format):
        raise Exception('format video error')
    ffmpeg_command = 'ffmpeg -loglevel warning -i %s -ac 1 -ar 16000 -acodec pcm_s16le -y  %s'
    audio_format = os.path.join(GlobalConfig.instance().temp_dir, code + '_format.wav')
    ffmpeg_command = ffmpeg_command % (audio_path, audio_format)
    logger.info(f'[{code}] -> ffmpeg audio: {ffmpeg_command}')
    run_silent(ffmpeg_command)
    if not os.path.exists(audio_format):
        raise Exception('format audio error')
    return (video_format, audio_format)


def get_license():
    logger.info('license check start ...')
    while not check_lc():
        logger.info('license check failed')
        time.sleep(30)


def a():
    return
    # if GlobalConfig.instance().register_enable == 1:
    #     result = register_host()
    #     if not result:
    #         raise Exception('服务注册失败.')
    #     threading.Thread(target=repost_host).start()
    # else:
    #     logger.warning(' -> 服务不进行注册')


class TransDhTask(object):

    def __init__(self, *args, **kwargs):
        # 打包为 EXE 时需要调用 freeze_support()
        multiprocessing.freeze_support()
        logger.info('TransDhTask init')
        set_start_method('spawn', force=True)

        # 【关键修复】在创建子进程之前隐藏父进程的控制台窗口
        # 这样子进程会继承父进程的隐藏状态，避免窗口闪烁
        set_console_window_hidden()

        self.run_lock = threading.Lock()
        self.task_dic = {}
        self.run_flag = False
        self.face_id = 0
        self.batch_size = int(GlobalConfig.instance().batch_size)
        # 增大队列大小，避免长音频导致阻塞
        self.drivered_queue = multiprocessing.Queue(50)
        self.output_imgs_queue = multiprocessing.Queue(50)
        self.result_queue = multiprocessing.Queue(1)
        self.wenet_model = load_ppg_model('wenet/examples/aishell/aidata/conf/train_conformer_multi_cn.yaml', 'wenet/examples/aishell/aidata/exp/conformer/wenetmodel.pt', 'cuda')

        # 终止信号事件
        self._terminate_event = multiprocessing.Event()

        # 追踪任务执行中创建的临时子进程
        self._active_task_processes = {}  # {task_code: [Process, ...]}
        self._task_processes_lock = threading.Lock()

        # 保存子进程引用，用于后续终止（传递 terminate_event）
        self._audio_transfer_process = Process(
            target=audio_transfer,
            args=(self.drivered_queue, self.output_imgs_queue, self.batch_size, self._terminate_event),
            daemon=True
        )
        self._audio_transfer_process.start()

        self.init_wh_queue = multiprocessing.Queue(2)
        self.init_wh_queue_output = multiprocessing.Queue(2)
        self._init_wh_process = Process(
            target=init_wh_process,
            args=(self.init_wh_queue, self.init_wh_queue_output, self._terminate_event),
            daemon=True
        )
        self._init_wh_process.start()

        # 等待子进程就绪（模型加载完成）
        logger.info('TransDhTask 等待 init_wh_process 子进程就绪...')
        try:
            init_result = self.init_wh_queue_output.get(timeout=60)  # 60 秒超时
            if init_result[0] == '__INIT_READY__':
                logger.info('TransDhTask: init_wh_process 子进程已就绪')
            elif init_result[0] == '__INIT_ERROR__':
                logger.error(f'TransDhTask: init_wh_process 子进程初始化失败：{init_result[1]}')
        except Exception as e:
            logger.error(f'TransDhTask: 等待 init_wh_process 子进程就绪超时：{e}')

    @classmethod
    def instance(cls, *args, **kwargs):
        if not hasattr(TransDhTask, '_instance'):
            TransDhTask._instance = TransDhTask(*args, **kwargs)
        return TransDhTask._instance

    def work(self, audio_url, video_url, code, watermark_switch, digital_auth, chaofen, pn, target_face_id=0, batch_size=None, output_path=None):
        logger.info(f'任务:{code} -> audio_url:{audio_url}  video_url:{video_url}')
        st = time.time()
        self.run_flag = True
        # 使用传入的 batch_size 或默认值
        task_batch_size = batch_size if batch_size is not None else self.batch_size
        logger.info(f'[{code}] -> batch_size: {task_batch_size}')

        # 辅助函数：检查是否应该取消
        def should_cancel():
            return self._terminate_event is not None and self._terminate_event.is_set()

        try:
            try:
                # 检查取消
                if should_cancel():
                    logger.info(f'[{code}] 任务在开始前被取消')
                    return

                self.change_task_status(code, Status.run, 0, '', '')
                try:
                    s1 = time.time()
                    fps, width, height, fourcc = get_video_info(video_url)
                    _tmp_audio_path, _tmp_video_path = self.preprocess(audio_url, video_url, code)
                    _video_url, _audio_url = format_video_audio(code, _tmp_video_path, _tmp_audio_path, fourcc)
                    logger.info(f'[{code}] -> 预处理耗时:{time.time() - s1}s')
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'[{code}]预处理失败，异常信息:[{e.__str__()}]')
                    raise CustomError(f'[{code}]预处理失败，异常信息:[{e.__str__()}]')
                if not (os.path.exists(_video_url) and os.path.exists(_audio_url)):
                    raise Exception('视频入参或音频入参下载处理异常')

                # 检查取消
                if should_cancel():
                    logger.info(f'[{code}] 任务在预处理后被取消')
                    return

                self.change_task_status(code, Status.run, 10, '', '文件下载完成')
                self.init_wh_queue.put([code, _video_url, target_face_id])
                try:
                    logger.debug(f'fps: {fps}')
                    s = time.time()
                    audio_wenet_feature = get_aud_feat1(_audio_url, fps=fps, wenet_model=self.wenet_model)
                    logger.info(f'[{code}] -> get_aud_feat1 cost:{time.time() - s}s')
                except Exception as e:
                    logger.error(traceback.format_exc())
                    logger.error(f'[{code}]音频特征提取失败，异常信息:[{e.__str__()}]')
                    raise CustomError(f'[{code}]音频特征提取失败，异常信息:[{e.__str__()}]')

                # 检查取消
                if should_cancel():
                    logger.info(f'[{code}] 任务在音频特征提取后被取消')
                    return

                self.change_task_status(code, Status.run, 20, '', '音频特征提取完成')
                process_list = []
                wh = 0
                try:
                    # 循环获取队列数据，直到收到匹配当前 code 的结果或超时
                    # 原因：init_wh_process 是类级别单例，队列中可能残留之前任务的结果
                    start_time = time.time()
                    wh_output = None
                    while time.time() - start_time < 30:  # 总超时 30 秒
                        # 检查取消
                        if should_cancel():
                            logger.info(f'[{code}] 任务在人脸检测等待中被取消')
                            return

                        try:
                            wh_output = self.init_wh_queue_output.get(timeout=1.0)
                            logger.debug(f'[{code}] 收到 wh 结果：{wh_output}')

                            # 检查是否匹配当前任务
                            if wh_output[0] == code:
                                wh = wh_output[1]
                                logger.info(f'[{code}] 人脸检测成功：wh={wh}, 多人脸={wh_output[2] if len(wh_output) > 2 else False}')
                                break
                            else:
                                # 不匹配的结果丢弃，继续等待
                                logger.warning(f'[{code}] 收到不匹配的结果：{wh_output[0]}，继续等待...')
                        except Empty:
                            continue

                    # 检查是否超时
                    if wh_output is None or (len(wh_output) > 0 and wh_output[0] != code):
                        raise TimeoutError(f'[{code}] 人脸检测超时，未收到有效结果')

                except Exception as e1:
                    logger.error(f'[{code}] 人脸检测失败：{e1}')
                    logger.error(traceback.format_exc())
                    raise Exception(f'人脸检测失败：{e1}')
                logger.info(f'[{code}] -> wh: [{wh}]')

                # 检查人脸检测是否成功
                if wh == 0:
                    error_msg = '未在驱动视频中检测到人脸，请检查视频文件是否包含清晰的人脸'
                    logger.error(f'[{code}] {error_msg}')
                    self.change_task_status(code, Status.error, 0, '', error_msg)
                    # 清空队列中可能残留的数据
                    try:
                        while not self.init_wh_queue.empty():
                            self.init_wh_queue.get_nowait()
                        while not self.init_wh_queue_output.empty():
                            self.init_wh_queue_output.get_nowait()
                    except:
                        pass
                    return

                # 检查取消
                if should_cancel():
                    logger.info(f'[{code}] 任务在视频生成前被取消')
                    return

                logger.debug(f"超分控制: {chaofen}")

                # 【修改点10】参数透传，传入 chaofen 参数（转为int）
                chaofen_ctrl_val = int(chaofen)

                if pn == 1:
                    # Use our new, efficient ping-pong implementation
                    logger.info(f'[{code}] -> Starting process with Ping-Pong video logic, batch_size={task_batch_size}')
                    process_list.append(Process(target=drivered_video_pingpong,
                                                args=(code, self.drivered_queue, _video_url, audio_wenet_feature,
                                                      task_batch_size, wh, chaofen_ctrl_val, target_face_id),
                                                daemon=True))
                else:
                    # Use the original sequential video logic
                    logger.info(f'[{code}] -> Starting process with sequential video logic, batch_size={task_batch_size}')
                    process_list.append(Process(target=drivered_video,
                                                args=(code, self.drivered_queue, _video_url, audio_wenet_feature,
                                                      task_batch_size, wh, chaofen_ctrl_val, target_face_id),
                                                daemon=True))

                # 后处理: 超分由 write_video_chaofen 统一在口型渲染后执行
                if chaofen == 1:
                    process_list.append(Process(target=write_video_chaofen, args=(self.output_imgs_queue, GlobalConfig.instance().temp_dir, GlobalConfig.instance().result_dir, code, _tmp_audio_path, self.result_queue, width, height, fps, watermark_switch, digital_auth, output_path, target_face_id), daemon=True))
                else:
                    process_list.append(Process(target=write_video, args=(self.output_imgs_queue, GlobalConfig.instance().temp_dir, GlobalConfig.instance().result_dir, code, _tmp_audio_path, self.result_queue, width, height, fps, watermark_switch, digital_auth, output_path), daemon=True))

                # 追踪任务子进程，用于系统退出时清理
                with self._task_processes_lock:
                    self._active_task_processes[code] = process_list

                [p.start() for p in process_list]

                # 使用带超时的 join，以便检查取消信号
                for p in process_list:
                    while p.is_alive():
                        p.join(timeout=0.5)
                        if should_cancel():
                            logger.info(f'[{code}] 任务在视频生成中被取消，终止子进程')
                            for proc in process_list:
                                if proc.is_alive():
                                    proc.terminate()
                            # 等待子进程终止
                            for proc in process_list:
                                proc.join(timeout=2.0)
                            # 清空队列防止残留数据影响后续任务
                            try:
                                while not self.drivered_queue.empty():
                                    self.drivered_queue.get_nowait()
                                while not self.output_imgs_queue.empty():
                                    self.output_imgs_queue.get_nowait()
                            except:
                                pass
                            return

                try:
                    try:
                        state, result_path = self.result_queue.get(timeout=10)
                        logger.debug(f'任务结果: state={state}, path={result_path}')
                        if state:
                            self.change_task_status(code, Status.run, 90, result_path, '视频处理完成')
                            _remote_file = os.path.join(GlobalConfig.instance().result_dir, f'{code}.mp4')
                            _final_url = result_path
                            logger.info(f'[{code}]任务最终合成结果: {_final_url}')
                            self.change_task_status(code, Status.success, 100, _final_url, '任务完成')
                            #sweep([GlobalConfig.instance().result_dir], True if GlobalConfig.instance().result_clean_switch == '1' else False)
                        else:
                            self.change_task_status(code, Status.error, 0, '', result_path)
                    except Empty:
                        self.change_task_status(code, Status.error, 0, '', '**生成视频失败')
                finally:
                    # 清理任务子进程追踪记录
                    with self._task_processes_lock:
                        if code in self._active_task_processes:
                            del self._active_task_processes[code]
                    del audio_wenet_feature
                    gc.collect()
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error(f'[{code}]任务执行失败，异常信息:[{e.__str__()}]')
                self.change_task_status(code, Status.error, 0, '', e.__str__())
        finally:
            #sweep([GlobalConfig.instance().temp_dir], True if GlobalConfig.instance().temp_clean_switch == '1' else False)
            self.drivered_queue.empty()
            self.output_imgs_queue.empty()
            self.result_queue.empty()
            torch.cuda.empty_cache()
            self.run_flag = False
            logger.info(f'>>> 任务:{code} 耗时:{time.time() - st} ')

    def preprocess(self, audio_url, video_url, code):
        s_pre = time.time()
        try:
            if audio_url.startswith('http:') or audio_url.startswith('https:'):
                _tmp_audio_path = os.path.join(GlobalConfig.instance().temp_dir, f'{code}.wav')
                download_file(audio_url, _tmp_audio_path)
            else:
                _tmp_audio_path = audio_url
        except Exception as e:
            logger.error(traceback.format_exc())
            raise CustomError(f'[{code}]音频下载失败，异常信息:[{e.__str__()}]')
        try:
            if video_url.startswith('http:') or video_url.startswith('https:'):
                _tmp_video_path = os.path.join(GlobalConfig.instance().temp_dir, f'{code}.mp4')
                download_file(video_url, _tmp_video_path)
            else:
                _tmp_video_path = video_url
        except Exception as e:
            logger.error(traceback.format_exc())
            raise CustomError(f'[{code}]视频下载失败，异常信息:[{e.__str__()}]')
        logger.debug(f'download cost: {time.time() - s_pre:.2f}s')
        return (_tmp_audio_path, _tmp_video_path)

    def change_task_status(self, code, status, progress, result, msg=''):
        try:
            try:
                self.run_lock.acquire()
                if code in self.task_dic:
                    self.task_dic[code] = (status, progress, result, msg)
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error(f'[{code}]修改任务状态异常，异常信息:[{e.__str__()}]')
        finally:
            self.run_lock.release()

    def cleanup(self):
        """
        清理资源并释放 GPU 显存

        CR-026: 低显存模式支持
        释放以下资源：
        1. 发送终止信号给子进程
        2. 终止所有任务执行中的临时子进程
        3. 等待常驻子进程退出
        4. wenet_model - WeNet 模型
        5. 多进程队列
        6. CUDA 缓存
        7. 类级别单例
        """
        logger.info("TransDhTask cleanup 开始...")

        # 1. 发送终止信号给子进程
        if hasattr(self, '_terminate_event') and self._terminate_event is not None:
            logger.info("发送终止信号给子进程...")
            self._terminate_event.set()

        # 2. 终止所有任务执行中的临时子进程
        if hasattr(self, '_active_task_processes') and hasattr(self, '_task_processes_lock'):
            with self._task_processes_lock:
                for task_code, process_list in list(self._active_task_processes.items()):
                    logger.info(f"终止任务 {task_code} 的 {len(process_list)} 个子进程...")
                    for proc in process_list:
                        if proc is not None and proc.is_alive():
                            try:
                                proc.terminate()
                                proc.join(timeout=1.0)
                                if proc.is_alive():
                                    logger.warning(f"任务 {task_code} 的子进程未能终止，强制 kill")
                                    proc.kill()
                            except Exception as e:
                                logger.warning(f"终止任务 {task_code} 的子进程失败: {e}")
                    logger.info(f"任务 {task_code} 的子进程已终止")
                self._active_task_processes.clear()
                logger.info("所有任务子进程已终止")

        # 3. 等待常驻子进程退出（最多等待 5 秒）
        for proc_name in ['_audio_transfer_process', '_init_wh_process']:
            if hasattr(self, proc_name):
                proc = getattr(self, proc_name)
                if proc is not None and proc.is_alive():
                    try:
                        proc.join(timeout=5.0)
                        if proc.is_alive():
                            logger.warning(f"{proc_name} 未能在超时内退出，强制终止")
                            proc.terminate()
                            proc.join(timeout=1.0)
                        logger.info(f"{proc_name} 已退出")
                    except Exception as e:
                        logger.warning(f"等待 {proc_name} 退出失败: {e}")
                    try:
                        del proc
                    except Exception:
                        pass
                    setattr(self, proc_name, None)

        # 4. 释放 wenet_model
        if hasattr(self, 'wenet_model') and self.wenet_model is not None:
            try:
                # wenet_model 是一个元组 (model, configs)
                if isinstance(self.wenet_model, tuple) and len(self.wenet_model) > 0:
                    model = self.wenet_model[0]
                    if hasattr(model, 'cpu'):
                        model.cpu()
                    del model
                del self.wenet_model
                self.wenet_model = None
                logger.info("wenet_model 已释放")
            except Exception as e:
                logger.warning(f"释放 wenet_model 失败: {e}")

        # 5. 清理多进程队列
        for queue_name in ['drivered_queue', 'output_imgs_queue', 'result_queue', 'init_wh_queue', 'init_wh_queue_output']:
            if hasattr(self, queue_name):
                try:
                    queue = getattr(self, queue_name)
                    if queue is not None:
                        # 清空队列
                        while not queue.empty():
                            try:
                                queue.get_nowait()
                            except:
                                break
                        queue.close()
                        queue.join_thread()
                        del queue
                        setattr(self, queue_name, None)
                except Exception as e:
                    logger.debug(f"清理队列 {queue_name} 失败: {e}")

        # 6. 清理任务字典
        if hasattr(self, 'task_dic'):
            self.task_dic.clear()

        # 7. 清理终止事件
        if hasattr(self, '_terminate_event'):
            try:
                del self._terminate_event
                self._terminate_event = None
            except Exception:
                pass

        # 8. 清理 CUDA 缓存
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logger.info("CUDA 缓存已清理")
        except Exception as e:
            logger.debug(f"清理 CUDA 缓存失败: {e}")

        # 9. 清除类级别单例（关键！）
        if hasattr(TransDhTask, '_instance'):
            try:
                del TransDhTask._instance
                logger.info("TransDhTask 单例已清除")
            except Exception as e:
                logger.warning(f"清除 TransDhTask._instance 失败: {e}")

        # 10. 多次垃圾回收
        gc.collect()
        gc.collect()
        gc.collect()

        logger.info("TransDhTask cleanup 完成")


if __name__ == '__main__':
    set_start_method('spawn', force=True)
    wenet_model = load_ppg_model('wenet/examples/aishell/aidata/conf/train_conformer_multi_cn.yaml', 'wenet/examples/aishell/aidata/exp/conformer/wenetmodel.pt', 'cuda')
    st = time.time()
    result = hy_fun(wenet_model, 'test_data/audio/driver_add_valume.wav', './landmark2face_wy/checkpoints/hy/1.mp4', './result', 1001)
    logger.info(f'result: {result}, cost: {time.time() - st:.2f}s')