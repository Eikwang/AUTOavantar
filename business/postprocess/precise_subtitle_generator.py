"""
精准字幕生成器 - 使用 Qwen3-ForcedAligner 强制对齐技术生成精确时间轴字幕

核心流程：
1. 从视频提取音频
2. 加载 Qwen3ForcedAligner 模型（独立加载，不依赖 ASR 模型）
3. 执行强制对齐
4. 转换为 SRT 格式
5. 卸载模型释放显存
"""

import logging
import torch
from pathlib import Path
from typing import List, Optional

from .audio_extractor import extract_audio_from_video, AudioExtractionError
from .srt_converter import convert_and_write_srt, SrtEntry

logger = logging.getLogger(__name__)

# 延迟导入 qwen_asr，避免测试时导入失败
Qwen3ForcedAligner = None


def _import_qwen_asr():
    """延迟导入 Qwen3ForcedAligner"""
    global Qwen3ForcedAligner
    if Qwen3ForcedAligner is None:
        from qwen_asr import Qwen3ForcedAligner
    return Qwen3ForcedAligner


class ModelLoadError(Exception):
    """模型加载失败异常"""
    pass


class AlignmentError(Exception):
    """强制对齐失败异常"""
    pass


class PreciseSubtitleGenerator:
    """精准字幕生成器"""

    def __init__(self, model_path: str, device: str = "cuda:0"):
        """
        初始化精准字幕生成器

        Args:
            model_path: Qwen3-ForcedAligner 模型本地路径
            device: 推理设备，默认 "cuda:0"

        Raises:
            ModelLoadError: 模型加载失败时抛出
        """
        self.model_path = model_path
        self.device = device
        self.model: Optional[Qwen3ForcedAligner] = None

    def load_model(self):
        """
        加载 Qwen3ForcedAligner 模型

        使用独立加载方式（不加载 ASR 模型），节省显存（约 0.6GB）
        启用 flash_attention_2 加速和 bfloat16 精度

        Raises:
            ModelLoadError: 模型加载失败时抛出
        """
        try:
            logger.info(f"加载 Qwen3-ForcedAligner 模型：{self.model_path}")
            Qwen3ForcedAligner = _import_qwen_asr()
            self.model = Qwen3ForcedAligner.from_pretrained(
                self.model_path,
                dtype=torch.bfloat16,
                device_map=self.device,
                attn_implementation="flash_attention_2",
            )
            logger.info("模型加载成功")
        except Exception as e:
            logger.error(f"模型加载失败：{e}")
            raise ModelLoadError(f"Qwen3-ForcedAligner 模型加载失败：{str(e)}")

    async def generate(
        self,
        video_path: str,
        segments_text: List[str],
        output_srt_path: str,
        max_chars: int = 16
    ) -> str:
        """
        生成精准字幕

        Args:
            video_path: 视频文件路径
            segments_text: 分段文本列表（用于拼接完整文案）
            output_srt_path: 输出 SRT 文件路径
            max_chars: 每条字幕最大字符数，默认 16

        Returns:
            str: 输出的 SRT 文件路径

        Raises:
            ModelLoadError: 模型未加载或加载失败
            AlignmentError: 强制对齐失败
            AudioExtractionError: 音频提取失败
        """
        if self.model is None:
            logger.warning("模型未加载，自动加载模型")
            self.load_model()

        # 1. 从视频提取音频
        logger.info(f"从视频提取音频：{video_path}")
        try:
            audio_path = await extract_audio_from_video(video_path, sample_rate=16000)
            logger.info(f"音频提取完成：{audio_path}")
        except AudioExtractionError as e:
            logger.error(f"音频提取失败：{e}")
            raise

        # 2. 拼接完整文案
        full_text = "".join(segments_text)
        logger.info(f"拼接文案文本，总长度：{len(full_text)} 字")
        preview = full_text[:100] if len(full_text) > 100 else full_text
        logger.info(f"文案预览（前100字）：{preview}")
        # 检查是否包含中文标点符号
        import re
        chinese_punct_count = len(re.findall(r'[，。！？；：、]', full_text))
        logger.info(f"文案中包含 {chinese_punct_count} 个中文标点符号")

        # 3. 执行强制对齐
        logger.info("执行强制对齐...")
        try:
            results = self.model.align(
                audio=audio_path,
                text=full_text,
                language="Chinese",
            )
            # align() 返回 List[ForcedAlignResult]，每个 ForcedAlignResult 有 items 属性
            # items 是 List[ForcedAlignItem]，每个 ForcedAlignItem 有 text, start_time, end_time
            if not results or not results[0].items:
                raise AlignmentError("强制对齐返回空结果")
            time_stamps = results[0].items
            logger.info(f"强制对齐完成，获得 {len(time_stamps)} 个字/词级时间戳")

            # 添加调试日志：查看前10个时间戳的内容
            for i, item in enumerate(time_stamps[:10]):
                logger.info(f"  时间戳[{i}]: text='{item.text}', start={item.start_time:.3f}, end={item.end_time:.3f}")

            # 统计时间戳中的标点符号数量
            punct_count = sum(1 for item in time_stamps if item.text in '，。！？；：、,.!?;:）】》"\'」』～~—…')
            logger.info(f"时间戳中包含 {punct_count} 个标点符号")

            # 统计多字符 token 的数量
            multi_char_count = sum(1 for item in time_stamps if len(item.text) > 1)
            logger.info(f"时间戳中包含 {multi_char_count} 个多字符 token")

            # 显示几个多字符 token 的内容
            multi_char_items = [(item.text, item.start_time, item.end_time) for item in time_stamps if len(item.text) > 1][:5]
            for text, start, end in multi_char_items:
                logger.info(f"  多字符 token: '{text}' [{start:.3f} - {end:.3f}]")
        except Exception as e:
            logger.error(f"强制对齐失败：{e}")
            raise AlignmentError(f"Qwen3-ForcedAligner 对齐失败：{str(e)}")

        # 4. 转换为 SRT 格式
        logger.info(f"转换为 SRT 格式，输出路径：{output_srt_path}")
        try:
            convert_and_write_srt(
                time_stamps=time_stamps,
                full_text=full_text,
                output_path=output_srt_path,
                max_chars=max_chars
            )
            logger.info("SRT 文件生成完成")

            # 添加调试日志：查看生成的字幕内容
            import os
            if os.path.exists(output_srt_path):
                with open(output_srt_path, 'r', encoding='utf-8') as f:
                    srt_content = f.read()
                    # 只显示前500字符
                    preview = srt_content[:500] if len(srt_content) > 500 else srt_content
                    logger.info(f"SRT 文件内容预览:\n{preview}")
        except Exception as e:
            logger.error(f"SRT 转换失败：{e}")
            raise

        # 5. 清理临时音频文件
        try:
            Path(audio_path).unlink()
            logger.info(f"临时音频文件已清理：{audio_path}")
        except Exception as e:
            logger.warning(f"清理临时音频文件失败：{e}")

        return output_srt_path

    def unload(self):
        """
        卸载模型释放显存

        调用 torch.cuda.empty_cache() 清理 CUDA 缓存
        """
        if self.model is not None:
            logger.info("卸载模型释放显存...")
            del self.model
            self.model = None

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                logger.info("CUDA 缓存已清理")
        else:
            logger.debug("模型未加载，无需卸载")


# 便捷函数
async def generate_precise_subtitle(
    video_path: str,
    segments_text: List[str],
    output_srt_path: str,
    model_path: str,
    device: str = "cuda:0",
    max_chars: int = 12
) -> str:
    """
    一站式生成精准字幕

    Args:
        video_path: 视频文件路径
        segments_text: 分段文本列表
        output_srt_path: 输出 SRT 文件路径
        model_path: Qwen3-ForcedAligner 模型路径
        device: 推理设备，默认 "cuda:0"
        max_chars: 每条字幕最大字符数，默认 12

    Returns:
        str: 输出的 SRT 文件路径
    """
    generator = PreciseSubtitleGenerator(model_path, device)

    try:
        generator.load_model()
        return await generator.generate(video_path, segments_text, output_srt_path, max_chars)
    finally:
        generator.unload()