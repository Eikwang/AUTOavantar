"""
SRT 格式转换工具 - 将强制对齐结果转换为 SRT 字幕格式

按标点符号拆分字幕条目，每条不超过 12 字

重要发现：qwen_asr 的 align() 方法返回的时间戳中不包含标点符号！
- 文案："哈喽大家好，我是老王！"
- 时间戳只返回：['哈', '喽', '大', '家', '好', '我', '是', '老', '王']
- 标点符号的时间戳不存在

因此需要使用 full_text 中的标点符号来确定分段点。
"""

from typing import List, Dict
from pathlib import Path
from dataclasses import dataclass
import re


# 字幕最大字符数
MAX_CHARS_PER_SUBTITLE = 12

# 中文字符标点符号（用于拆分字幕，但不显示在字幕中）
# 包含所有被 qwen_asr 的 is_kept_char 移除的字符
# qwen_asr 只保留 Unicode category L(字母)/N(数字) + 单引号，其余全部移除
CHINESE_PUNCTUATION = (
    "，。！？；：、,.!?;:）】》\"'』〟～~—…"
    "‘’“”「」『』"
    "《》〈〉"
    "（）【】"
    "·•–"
    " \t\n\r\u3000"
)

@dataclass
class SrtEntry:
    """SRT 字幕条目"""
    text: str
    start_time: float
    end_time: float

    @property
    def start_time_str(self) -> str:
        """SRT 格式的开始时间字符串"""
        return format_srt_timestamp(self.start_time)

    @property
    def end_time_str(self) -> str:
        """SRT 格式的结束时间字符串"""
        return format_srt_timestamp(self.end_time)


def convert_timestamps_to_srt(
    time_stamps: List[Dict],
    full_text: str = None,
    max_chars: int = MAX_CHARS_PER_SUBTITLE
) -> List[SrtEntry]:
    """
    将字/词级时间戳转换为 SRT 字幕条目

    策略：
    1. 使用 time_stamps 的时间信息（确保时间准确）
    2. 使用 full_text 中的标点符号来确定分段点（因为 qwen_asr 不返回标点的时间戳）
    3. 不显示标点符号（从字幕文本中移除）

    Args:
        time_stamps: 字/词级时间戳列表，每个元素包含 text, start_time, end_time
        full_text: 完整文案文本（用于确定标点符号位置）
        max_chars: 每条字幕最大字符数，默认 12

    Returns:
        List[SrtEntry]: SRT 字幕条目列表
    """
    import logging
    logger = logging.getLogger(__name__)

    if not time_stamps:
        return []

    # 如果没有提供 full_text，从时间戳重建
    if not full_text:
        full_text = "".join(ts.text for ts in time_stamps)

    # 第一步：从 time_stamps 构建非标点字符的时间映射
    # time_stamps 只包含非标点字符
    non_punct_times = []  # [(char, start_time, end_time)]
    for ts in time_stamps:
        token_text = ts.text
        token_start = ts.start_time
        token_end = ts.end_time

        if len(token_text) == 1:
            non_punct_times.append((token_text, token_start, token_end))
        else:
            # 多字符 token，按字符数均匀分配时间
            duration = token_end - token_start
            for i, ch in enumerate(token_text):
                ch_start = token_start + (i / len(token_text)) * duration
                ch_end = token_start + ((i + 1) / len(token_text)) * duration
                non_punct_times.append((ch, ch_start, ch_end))

    # 第二步：验证 full_text 和 time_stamps 的字符是否匹配
    # 从 full_text 中提取非标点字符
    full_text_non_punct = [char for char in full_text if char not in CHINESE_PUNCTUATION]
    time_stamps_chars = [item[0] for item in non_punct_times]

    logger.info(f"full_text 非标点字符数: {len(full_text_non_punct)}")
    logger.info(f"time_stamps 字符数: {len(time_stamps_chars)}")

    # 检查是否匹配
    if len(full_text_non_punct) != len(time_stamps_chars):
        logger.warning(f"字符数不匹配！full_text: {len(full_text_non_punct)}, time_stamps: {len(time_stamps_chars)}")

        # 找出不匹配的位置
        for i in range(min(len(full_text_non_punct), len(time_stamps_chars))):
            if full_text_non_punct[i] != time_stamps_chars[i]:
                logger.warning(f"位置 {i} 不匹配: full_text='{full_text_non_punct[i]}', time_stamps='{time_stamps_chars[i]}'")
                if i > 0:
                    logger.warning(f"  前面的字符: full_text='{full_text_non_punct[i-1]}', time_stamps='{time_stamps_chars[i-1]}'")
                break

        # 如果 time_stamps 比 full_text 多，显示多余的字符
        if len(time_stamps_chars) > len(full_text_non_punct):
            extra_chars = time_stamps_chars[len(full_text_non_punct):]
            logger.warning(f"time_starts 多余的字符: {extra_chars[:20]}")

        # 如果 full_text 比 time_stamps 多，显示多余的字符
        if len(full_text_non_punct) > len(time_stamps_chars):
            extra_chars = full_text_non_punct[len(time_stamps_chars):]
            logger.warning(f"full_text 多余的字符: {extra_chars[:20]}")

        # 关键修复：使用 time_stamps 的字符作为基准重建 full_text
        # 因为时间戳是准确的，而 full_text 可能包含音频中不存在的内容
        logger.warning("使用 time_stamps 的字符重建文本，忽略 full_text 中多余的内容")
        # 保留标点符号位置信息，但只使用 time_stamps 中存在的字符
        # fallback: 如果 full_text 中的非标点字符与 time_stamps_chars 不匹配，
        # 说明该字符被 qwen_asr 移除但不在 CHINESE_PUNCTUATION 中，跳过它
        rebuilt_text = ""
        time_idx = 0
        for char in full_text:
            if char in CHINESE_PUNCTUATION:
                rebuilt_text += char
            elif time_idx < len(time_stamps_chars) and char == time_stamps_chars[time_idx]:
                # full_text 字符与 time_stamps_chars 对应位置匹配
                rebuilt_text += char
                time_idx += 1
            elif time_idx < len(time_stamps_chars):
                # full_text 字符与 time_stamps_chars 不匹配
                # 说明该字符被 qwen_asr 移除但不在 CHINESE_PUNCTUATION 中
                # 跳过该字符，不消耗 time_idx
                logger.debug(f"跳过不可映射字符: '{char}' (期望 '{time_stamps_chars[time_idx]}')")
                continue
            # 如果 time_stamps 已经用完，跳过 full_text 中剩余的字符
        full_text = rebuilt_text
        logger.info(f"重建后的文本长度: {len(full_text)} 非标点字符: {time_idx}")

    # 第三步：建立 full_text 中非标点字符到时间的映射
    # 使用 time_stamps 的字符作为基准，因为时间戳是准确的
    char_time_map = {}  # full_text 中的索引 -> (start_time, end_time)
    time_idx = 0
    for i, char in enumerate(full_text):
        if char in CHINESE_PUNCTUATION:
            continue  # 跳过标点符号
        if time_idx < len(non_punct_times):
            # 使用 time_stamps 的时间
            char_time_map[i] = (non_punct_times[time_idx][1], non_punct_times[time_idx][2])
            time_idx += 1
        else:
            # 如果 time_stamps 不够，说明重建逻辑有问题，记录警告
            logger.warning(f"位置 {i} 字符 '{char}' 没有时间戳（time_idx={time_idx}, len(non_punct_times)={len(non_punct_times)}）")
            # 不再使用估算时间，因为这会导致时间轴漂移
            # 如果出现这种情况，说明前面的重建逻辑有问题

    # 第三步：按标点符号分段，生成字幕条目
    subtitle_entries: List[SrtEntry] = []
    current_chars = []  # 收集当前字幕的字符索引（full_text 中的索引）

    for i, char in enumerate(full_text):
        # 跳过标点符号（不添加到字幕文本中）
        if char in CHINESE_PUNCTUATION:
            # 标点符号触发分段
            if current_chars:
                # 生成字幕
                start_idx = current_chars[0]
                end_idx = current_chars[-1]
                start_time = char_time_map.get(start_idx, (0, 0.2))[0]
                end_time = char_time_map.get(end_idx, (0, 0.4))[1]
                subtitle_text = ''.join(full_text[idx] for idx in current_chars)
                subtitle_entries.append(SrtEntry(
                    text=subtitle_text,
                    start_time=start_time,
                    end_time=end_time
                ))
                current_chars = []
            continue

        # 添加字符到当前字幕
        current_chars.append(i)

        # 检查是否达到最大字符数
        if len(current_chars) >= max_chars:
            # 生成字幕
            start_idx = current_chars[0]
            end_idx = current_chars[-1]
            start_time = char_time_map.get(start_idx, (0, 0.2))[0]
            end_time = char_time_map.get(end_idx, (0, 0.4))[1]
            subtitle_text = ''.join(full_text[idx] for idx in current_chars)
            subtitle_entries.append(SrtEntry(
                text=subtitle_text,
                start_time=start_time,
                end_time=end_time
            ))
            current_chars = []

    # 处理剩余的字符
    if current_chars:
        start_idx = current_chars[0]
        end_idx = current_chars[-1]
        start_time = char_time_map.get(start_idx, (0, 0.2))[0]
        end_time = char_time_map.get(end_idx, (0, 0.4))[1]
        subtitle_text = ''.join(full_text[idx] for idx in current_chars)
        subtitle_entries.append(SrtEntry(
            text=subtitle_text,
            start_time=start_time,
            end_time=end_time
        ))

    return subtitle_entries


def format_srt_timestamp(seconds: float) -> str:
    """
    将秒数格式化为 SRT 时间格式 (HH:MM:SS,mmm)

    Args:
        seconds: 秒数（浮点数）

    Returns:
        str: SRT 格式时间字符串
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt_file(entries: List[SrtEntry], output_path: str) -> str:
    """
    将字幕条目写入 SRT 文件

    Args:
        entries: SRT 字幕条目列表
        output_path: 输出文件路径

    Returns:
        str: 输出的 SRT 文件路径
    """
    output_file = Path(output_path)

    # 确保输出目录存在
    output_dir = output_file.parent
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        for idx, entry in enumerate(entries, 1):
            # SRT 格式：
            # 序号
            # 开始时间 --> 结束时间
            # 字幕文本
            # 空行
            f.write(f"{idx}\n")
            f.write(f"{entry.start_time_str} --> {entry.end_time_str}\n")
            f.write(f"{entry.text}\n")
            f.write("\n")

    return str(output_file)


def convert_and_write_srt(
    time_stamps: List,
    full_text: str,
    output_path: str,
    max_chars: int = MAX_CHARS_PER_SUBTITLE
) -> str:
    """
    一站式转换：将字/词级时间戳转换为 SRT 文件

    Args:
        time_stamps: 字/词级时间戳列表
        full_text: 完整文案文本
        max_chars: 每条字幕最大字符数
        output_path: 输出 SRT 文件路径

    Returns:
        str: 输出的 SRT 文件路径
    """
    entries = convert_timestamps_to_srt(time_stamps, full_text, max_chars)
    return write_srt_file(entries, output_path)