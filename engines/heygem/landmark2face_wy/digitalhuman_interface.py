from landmark2face_wy.options.test_options import TestOptions
import torchvision.transforms as transforms
from landmark2face_wy.models.l2faceaudio_model import L2FaceAudioModel
from landmark2face_wy.util.util import *
import torch, time, math, os
import torch.nn.functional as F
from face_lib.face_restore import GFPGAN
from y_utils.config import GlobalConfig
import sys

class DigitalHumanModel:

    def __init__(self, blend_dynamic, chaofen_before, face_blur_detect=False):
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
        # weights_only=False 是为了兼容旧版保存的模型结构
        temp_model = torch.load(self.opt.model_path, weights_only=False)
        self.opt.netG = temp_model["model_name"]
        self.opt.dataloader_size = temp_model["model_input_size"][0]
        self.opt.ngf = temp_model["model_ngf"]
        self.img_size = temp_model["model_input_size"][0]
        self.fuse_mask = temp_model["fuse_mask"]
        self.fuse_mask = cv2.resize(self.fuse_mask, (self.img_size, self.img_size))
        
        # [修改] 强制使用 float() (FP32)，解决老显卡黑屏问题
        self.mask_re_cuda = torch.tensor(temp_model["input_mask_re"]).unsqueeze(0).unsqueeze(0).cuda().float()
        self.mask_cuda = torch.tensor(temp_model["input_mask"]).unsqueeze(0).unsqueeze(0).cuda().float()
        self.fuse_mask_cuda = torch.tensor(self.fuse_mask).unsqueeze(0).unsqueeze(0).cuda().repeat(1, 3, 1, 1).float()
        
        self.nblend = temp_model["nblend"]
        self.model = L2FaceAudioModel(self.opt)
        self.drivered_wh = temp_model["wh"]
        self.model.netG.load_state_dict(temp_model["face_G"])
        self.model.netG.cuda()
        
        # [修改] 确保模型权重为 float32
        self.model.netG.float()
        self.model.eval()
        
        if chaofen_before == 1:
            from face_lib.face_restore.gfpgan_onnx import gfpgan_onnx_api
            # 模型路径: 从 CWD 向上查找 models/gfpgan/GFPGANv1.4.onnx, 回退到默认路径
            _rel_path = os.path.join('models', 'gfpgan', 'GFPGANv1.4.onnx')
            _dir = os.getcwd()
            for _ in range(5):
                _candidate = os.path.join(_dir, _rel_path)
                if os.path.exists(_candidate):
                    gfpgan_onnx_api.MODEL_ZOO['GFPGANv1.4']['model_path'] = os.path.abspath(_candidate)
                    break
                _parent = os.path.dirname(_dir)
                if _parent == _dir:
                    break
                _dir = _parent
            self.gfpgan = GFPGAN(model_type="GFPGANv1.4", provider="gpu")
        self.face_blur_detect = face_blur_detect
        if self.face_blur_detect:
            from face_attr_detect.face_attr import FaceAttr
            self.face_attr = FaceAttr(model_name="face_attr_mbnv3", provider="gpu")
            
        # 初始化高斯核缓存字典
        self.gaussian_kernel_cache = {}

    def tensor_norm(self, img_tensor, mask=None):
        img_tensor = img_tensor / 127.5 - 1
        if mask is not None:
            return (img_tensor + 1) * mask - 1
        return img_tensor

    def tensor_norm_no_training(self, img_tensor, mask=None):
        img_tensor = img_tensor / 255.0
        if mask is not None:
            return img_tensor * mask
        return img_tensor

    def inference(self, audio_info, face_data_dict, this_batch, start_idx, params):
        (audio_idx, wenet_feature) = audio_info
        B_img_list = []
        B_img__list = []
        mask_B_list = []
        mask_B_pre_list = []
        lab_list = []
        for i in range(this_batch):
            img_idx = start_idx + i
            mask_B_pre = self.gfpgan.forward(face_data_dict[img_idx]["crop_img"])
            mask_B = mask_B_pre[int(0 * (self.img_size / 256)):int(-10 * (self.img_size / 256)),
             int(5 * (self.img_size / 256)):int(-5 * (self.img_size / 256))]
            B_img = mask_B.copy()
            mask_B = torch.from_numpy(mask_B[:, :, [2, 1, 0]].transpose(2, 0, 1))
            B_img_ = B_img.copy()
            B_img_ = torch.from_numpy(B_img_[:, :, [2, 1, 0]].transpose(2, 0, 1))
            B_img_list.append(torch.from_numpy(B_img.transpose(2, 0, 1)))
            B_img__list.append(B_img_)
            mask_B_pre_list.append(mask_B_pre)
            mask_B_list.append(mask_B)
            lab = wenet_feature.transpose(1, 0)[audio_idx[start_idx + i][0]:audio_idx[start_idx + i][1]][(np.newaxis, ...)]
            lab_list.append(lab)

        # model_st = time.time()
        torch.cuda.synchronize()
        if this_batch > 0:
            # [修改] 使用 .float() 替代 .half()
            lab = torch.tensor(lab_list).cuda().float()
            mask_B = torch.stack(mask_B_list).cuda().float()
            mask_B = self.tensor_norm(mask_B, mask=(self.mask_cuda.repeat(this_batch, 3, 1, 1)))
            B_img_ = torch.stack(B_img__list).cuda().float()
            B_img_ = self.tensor_norm(B_img_, mask=(self.mask_re_cuda.repeat(this_batch, 3, 1, 1)))
            B_img = torch.stack(B_img_list).cuda().float()
            B_img = self.tensor_norm(B_img)
            
            fake_B = self.model.netG(lab, torch.cat((mask_B, B_img_), 1))[:, [2, 1, 0], :, :]
            if self.nblend:
                fake_B = torch.where(self.mask_re_cuda == 0, B_img, fake_B)
            self.fuse_mask_cuda_copy = self.fuse_mask_cuda.repeat(this_batch, 1, 1, 1)
            fuse_res = fake_B * self.fuse_mask_cuda_copy + (1 - self.fuse_mask_cuda_copy) * B_img
            
            # [修改] 增加 clamp 确保数值在合法范围内，防止溢出
            fuse_res = torch.clamp(fuse_res, -1, 1)
            
        torch.cuda.synchronize()
        # model_et = time.time()
        output_img_list = []
        for i in range(this_batch):
            mask_B_pre_list[i][int(0 * (self.img_size / 256)):int(-10 * (self.img_size / 256)),
             int(5 * (self.img_size / 256)):int(-5 * (self.img_size / 256))] = ((fuse_res[i] + 1) * 127.5).permute(1, 2, 0).byte().cpu().numpy()
            output_img_list.append(mask_B_pre_list[i])

        return output_img_list

    def inference1(self, audio_info, face_data_dict, this_batch, start_idx, params):
        B_img_list = []
        B_img__list = []
        mask_B_list = []
        mask_B_pre_list = []
        lab_list = []
        for i in range(this_batch):
            img_idx = start_idx + i
            mask_B_pre = face_data_dict[img_idx]["crop_img"]
            mask_B = mask_B_pre[int(0 * (self.img_size / 256)):int(-10 * (self.img_size / 256)),
             int(5 * (self.img_size / 256)):int(-5 * (self.img_size / 256))]
            B_img = mask_B.copy()
            mask_B = torch.from_numpy(mask_B[:, :, [2, 1, 0]].transpose(2, 0, 1))
            B_img_ = B_img.copy()
            B_img_ = torch.from_numpy(B_img_[:, :, [2, 1, 0]].transpose(2, 0, 1))
            B_img_list.append(torch.from_numpy(B_img.transpose(2, 0, 1)))
            B_img__list.append(B_img_)
            mask_B_pre_list.append(mask_B_pre)
            mask_B_list.append(mask_B)
            lab = audio_info[start_idx + i][(np.newaxis, ...)]
            lab_list.append(lab)

        # model_st = time.time()
        torch.cuda.synchronize()
        if this_batch > 0:
            # [修改] 使用 .float() 替代 .half()
            lab = torch.tensor(lab_list).cuda().float()
            mask_B = torch.stack(mask_B_list).cuda().float()
            mask_B = self.tensor_norm(mask_B, mask=(self.mask_cuda.repeat(this_batch, 3, 1, 1)))
            B_img_ = torch.stack(B_img__list).cuda().float()
            B_img_ = self.tensor_norm(B_img_, mask=(self.mask_re_cuda.repeat(this_batch, 3, 1, 1)))
            B_img = torch.stack(B_img_list).cuda().float()
            B_img = self.tensor_norm(B_img)
            
            fake_B = self.model.netG(lab, torch.cat((mask_B, B_img_), 1))[:, [2, 1, 0], :, :]
            if self.nblend:
                fake_B = torch.where(self.mask_re_cuda == 0, B_img, fake_B)
            self.fuse_mask_cuda_copy = self.fuse_mask_cuda.repeat(this_batch, 1, 1, 1)
            fuse_res = fake_B * self.fuse_mask_cuda_copy + (1 - self.fuse_mask_cuda_copy) * B_img
            
            # [修改] 增加 clamp
            fuse_res = torch.clamp(fuse_res, -1, 1)
            
        torch.cuda.synchronize()
        # model_et = time.time()
        output_img_list = []
        for i in range(this_batch):
            mask_B_pre_list[i][int(0 * (self.img_size / 256)):int(-10 * (self.img_size / 256)),
             int(5 * (self.img_size / 256)):int(-5 * (self.img_size / 256))] = ((fuse_res[i] + 1) * 127.5).permute(1, 2, 0).byte().cpu().numpy()
            output_img_list.append(mask_B_pre_list[i])

        return output_img_list

    def get_face_mask(self, img, landmarks):
        imgshape = img.shape[0]
        landmarks = landmarks.astype(int)
        wanted_numpy = np.concatenate([landmarks[2:15], landmarks[29:30]])
        mask = np.zeros((imgshape, imgshape), dtype=(np.uint8))
        wanted_numpy = cv2.convexHull(wanted_numpy)
        cv2.fillConvexPoly(mask, wanted_numpy, 255)
        mid = (landmarks[5, :] + landmarks[11, :]) // 2
        cv2.ellipse(mask, (mid[0], mid[1]), ((landmarks[(11, 0)] - landmarks[(5, 0)] + 3 * (imgshape // 266)) // 2, 60 * (imgshape // 266)), 0, 0, 180, (255,
                                                                                                                                                         255,
                                                                                                                                                         255), -1)
        amask = (mask > 0).astype(np.uint8) * 255
        kernel_size = (
         5 * (imgshape // 266) + 1, 5 * (imgshape // 266) + 1)
        iterations = 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
        eroded_mask = cv2.dilate(amask, kernel, iterations=iterations)
        return eroded_mask

    def get_face_mask2(self, img, landmarks, delta):
        wanted_numpy = landmarks.astype(int)
        mask = np.zeros((img.shape[0], img.shape[1]), dtype=(np.uint8))
        wanted_numpy = cv2.convexHull(wanted_numpy)
        cv2.fillConvexPoly(mask, wanted_numpy, 255)
        amask = (mask > 0).astype(np.uint8) * 255
        kernel_size = (5, 5)
        iterations = 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
        amask = cv2.dilate(amask, kernel, iterations=iterations)
        eroded_mask = cv2.GaussianBlur(amask, (5, 5), 0)
        return amask

    def create_gaussian_kernel(self, kernel_size, sigma):
        """创建高斯核，带缓存优化"""
        cache_key = (kernel_size, sigma)
        if cache_key not in self.gaussian_kernel_cache:
            coords = torch.arange(kernel_size, dtype=torch.float32) - kernel_size // 2
            g = torch.exp(-(coords ** 2) / (2 * sigma ** 2))
            g = g / g.sum()
            
            # 创建2D核
            kernel_2d = g.outer(g)
            kernel = kernel_2d.unsqueeze(0).unsqueeze(0)
            self.gaussian_kernel_cache[cache_key] = kernel
        
        return self.gaussian_kernel_cache[cache_key]
    
    def gaussian_blur_batch(self, tensor, kernel_size, sigma):
        """
        批量高斯模糊，使用分离卷积优化
        tensor: (batch, channels, H, W)
        """
        batch_size, channels, height, width = tensor.shape
        
        # 创建1D高斯核（分离卷积更高效）
        coords = torch.arange(kernel_size, dtype=torch.float32, device=tensor.device) - kernel_size // 2
        g = torch.exp(-(coords ** 2) / (2 * sigma ** 2))
        g = g / g.sum()
        
        # 水平卷积核 (1, 1, 1, kernel_size)
        kernel_h = g.view(1, 1, 1, kernel_size).repeat(channels, 1, 1, 1)
        # 垂直卷积核 (1, 1, kernel_size, 1)
        kernel_v = g.view(1, 1, kernel_size, 1).repeat(channels, 1, 1, 1)
        
        padding = kernel_size // 2
        
        # 分离卷积：先水平后垂直
        blurred = F.conv2d(tensor, kernel_h, padding=(0, padding), groups=channels)
        blurred = F.conv2d(blurred, kernel_v, padding=(padding, 0), groups=channels)
        
        return blurred
        
    def optimized_weight_calculation_gpu_batch(self, blend_mask_list, this_batch):
        """
        GPU批量计算权重 - 优化版本
        """
        if this_batch == 0:
            return torch.empty(0, 3, self.img_size, self.img_size).cuda()
        
        # 批量转换numpy数组，减少内存分配
        blend_masks_np = np.stack(blend_mask_list, axis=0).astype(np.float32)
        
        # 一次性传输到GPU，注意保持 float32
        blend_masks_tensor = torch.from_numpy(blend_masks_np).cuda().float()
        
        # 添加通道维度 (batch, 1, H, W)
        blend_masks_tensor = blend_masks_tensor.unsqueeze(1)
        
        # 计算模糊参数
        kernel_size = 16 * int(self.img_size / 256) + 1
        # 确保kernel_size为奇数
        if kernel_size % 2 == 0:
            kernel_size += 1
        
        sigma = kernel_size / 6.0
        
        # 批量高斯模糊
        blurred_masks = self.gaussian_blur_batch(blend_masks_tensor, kernel_size, sigma)
        
        # 归一化到[0,1]
        weights = blurred_masks / 255.0
        
        # 扩展到3通道 (batch, 3, H, W)
        weights = weights.repeat(1, 3, 1, 1)
        
        return weights

    def inference_notraining(self, audio_info, face_data_dict, this_batch, start_idx, blend_dynamic, params, frameId):
        B_img_list = []
        B_img__list = []
        mask_B_list = []
        mask_B_pre_list = []
        blend_mask_list = []
        lab_list = []
        
        for i in range(this_batch):
            img_idx = start_idx + i
            
            mask_B_pre = face_data_dict[img_idx]["crop_img"]
            crop_size = int(5 * (self.img_size / 256))
            mask_B = mask_B_pre[crop_size:-crop_size, crop_size:-crop_size]
            B_img = mask_B.copy()
            
            mask_B_rgb = mask_B[:, :, [2, 1, 0]]
            mask_B = torch.from_numpy(mask_B_rgb.transpose(2, 0, 1))
            B_img_ = B_img.copy()
            B_img_rgb = B_img_[:, :, [2, 1, 0]]
            B_img_ = torch.from_numpy(B_img_rgb.transpose(2, 0, 1))
            
            lm = face_data_dict[img_idx]["crop_lm"]
            blend_mask = self.get_face_mask(mask_B_pre, lm)
            blend_mask = blend_mask[crop_size:-crop_size, crop_size:-crop_size]
            
            if blend_mask.shape[:2] != (self.img_size, self.img_size):
                blend_mask = cv2.resize(blend_mask, (self.img_size, self.img_size), 
                                    interpolation=cv2.INTER_LINEAR)
            
            blend_mask_list.append(blend_mask)
            B_img_list.append(torch.from_numpy(B_img[:, :, [2, 1, 0]].transpose(2, 0, 1)))
            B_img__list.append(B_img_)
            mask_B_pre_list.append(mask_B_pre)
            mask_B_list.append(mask_B)
            
            lab = audio_info[start_idx + i].transpose(1, 0)
            lab_list.append(lab)
        
        torch.cuda.synchronize()
        
        if this_batch > 0:
            # [修改] 显式转换为 float()
            lab = torch.tensor(lab_list).cuda().float()
            mask_B = torch.stack(mask_B_list).cuda().float()
            mask_B = self.tensor_norm_no_training(mask_B, mask=(self.mask_cuda.repeat(this_batch, 3, 1, 1)))
            
            B_img_ = torch.stack(B_img__list).cuda().float()
            B_img_ = self.tensor_norm_no_training(B_img_, mask=(self.mask_re_cuda.repeat(this_batch, 3, 1, 1)))
            
            B_img = torch.stack(B_img_list).cuda().float()
            B_img = self.tensor_norm_no_training(B_img)
            
            fake_B = self.model.netG(mask_B, B_img_, lab)
            
            if self.nblend:
                fake_B = torch.where(self.mask_re_cuda == 0, B_img, fake_B)
            
            self.fuse_mask_cuda_copy = self.optimized_weight_calculation_gpu_batch(blend_mask_list, this_batch)
            
            fuse_res = fake_B * self.fuse_mask_cuda_copy + (1 - self.fuse_mask_cuda_copy) * B_img
            
            # [修改] 增加 clamp
            fuse_res = torch.clamp(fuse_res, 0, 1)
        
        torch.cuda.synchronize()
        
        if this_batch > 0:
            fuse_res_cpu = (fuse_res * 255).permute(0, 2, 3, 1).byte().cpu().numpy()
            
            output_img_list = []
            crop_size = int(5 * (self.img_size / 256))
            
            for i in range(this_batch):
                mask_B_pre_list[i][crop_size:-crop_size, crop_size:-crop_size] = fuse_res_cpu[i][..., ::-1]
                output_img_list.append(mask_B_pre_list[i])
        else:
            output_img_list = []
        
        return output_img_list

    def blendImages(self, src, dst, featherAmount=0.1):
        torch.cuda.synchronize()
        src_gpu = src
        dst_gpu = dst
        composed_gpu = self.w_gpu * src_gpu + (1 - self.w_gpu) * dst_gpu
        composedImg = composed_gpu
        return composedImg