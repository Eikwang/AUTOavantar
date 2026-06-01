"""
视频处理工具函数
"""


def calculate_aspect_ratio(width: int, height: int) -> float:
    """计算视频的宽高比（宽/高）"""
    if height == 0:
        return 0
    return width / height


def calculate_aspect_ratio_error(ratio1: float, ratio2: float) -> float:
    """计算两个宽高比之间的误差百分比"""
    if ratio1 == 0 or ratio2 == 0:
        return 100.0
    return abs(ratio1 - ratio2) / ratio2 * 100
