"""
路径管理模块
统一管理所有中间文件路径，确保使用绝对路径

路径规范：
- 音频中间文件：backend/output/temp/audio/
- 视频中间文件：backend/output/temp/video/
- 最终输出：output/
"""

import os
from pathlib import Path
from typing import Optional

# 全局路径管理器实例
_path_manager: Optional['PathManager'] = None


class PathManager:
    """路径管理器 - 统一管理所有文件路径"""

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化路径管理器

        Args:
            project_root: 项目根目录，None 则自动检测
        """
        if project_root:
            self._project_root = Path(project_root).resolve()
        else:
            self._project_root = self._detect_project_root()

        # 后端目录（后端从 backend/ 目录启动）
        self._backend_dir = self._project_root / "backend"
        if not self._backend_dir.exists():
            # 如果没有 backend 目录，使用项目根目录
            self._backend_dir = self._project_root

        # 输出目录
        self._output_dir = self._backend_dir / "output"
        self._temp_dir = self._output_dir / "temp"
        self._audio_temp_dir = self._temp_dir / "audio"
        self._video_temp_dir = self._temp_dir / "video"

        # 最终输出目录（项目根目录下的 output）
        self._final_output_dir = self._project_root / "output"

        # 确保目录存在
        self._ensure_directories()

    def _detect_project_root(self) -> Path:
        """自动检测项目根目录"""
        # 从当前工作目录向上查找
        current = Path.cwd()

        # 检查当前目录是否是 backend
        if current.name == "backend":
            return current.parent

        # 向上查找包含 backend 目录的目录
        for parent in current.parents:
            if (parent / "backend").exists():
                return parent

        # 如果找不到，使用当前目录
        return current

    def _ensure_directories(self):
        """确保所有目录存在"""
        self._audio_temp_dir.mkdir(parents=True, exist_ok=True)
        self._video_temp_dir.mkdir(parents=True, exist_ok=True)
        self._final_output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def project_root(self) -> str:
        """项目根目录"""
        return str(self._project_root)

    @property
    def backend_dir(self) -> str:
        """后端目录"""
        return str(self._backend_dir)

    @property
    def output_dir(self) -> str:
        """输出目录（backend/output）"""
        return str(self._output_dir)

    @property
    def temp_dir(self) -> str:
        """临时文件目录（backend/output/temp）"""
        return str(self._temp_dir)

    @property
    def audio_temp_dir(self) -> str:
        """音频临时目录（backend/output/temp/audio）"""
        return str(self._audio_temp_dir)

    @property
    def video_temp_dir(self) -> str:
        """视频临时目录（backend/output/temp/video）"""
        return str(self._video_temp_dir)

    @property
    def final_output_dir(self) -> str:
        """最终输出目录（项目根目录/output）"""
        return str(self._final_output_dir)

    @property
    def merged_dir(self) -> str:
        """合并输出目录（backend/output/merged）"""
        merged = self._output_dir / "merged"
        merged.mkdir(parents=True, exist_ok=True)
        return str(merged)

    def get_audio_path(self, filename: str) -> str:
        """获取音频文件路径"""
        return str(self._audio_temp_dir / filename)

    def get_video_path(self, filename: str) -> str:
        """获取视频文件路径"""
        return str(self._video_temp_dir / filename)

    def get_final_output_path(self, filename: str) -> str:
        """获取最终输出文件路径"""
        return str(self._final_output_dir / filename)

    def resolve_path(self, path: str) -> str:
        """
        解析路径为绝对路径
        支持相对路径和绝对路径
        """
        p = Path(path)
        if p.is_absolute():
            return str(p)

        # 尝试多种解析方式
        possible_paths = [
            p,  # 原始路径
            self._audio_temp_dir / path,  # 音频目录
            self._video_temp_dir / path,  # 视频目录
            self._output_dir / path,  # 输出目录
            self._backend_dir / path,  # 后端目录
            self._project_root / path,  # 项目根目录
        ]

        for pp in possible_paths:
            if pp.exists():
                return str(pp.resolve())

        # 如果都不存在，返回相对于后端目录的路径
        return str((self._backend_dir / path).resolve())

    def find_audio_file(self, filename: str) -> Optional[str]:
        """
        查找音频文件
        搜索多个可能的位置
        """
        # 如果是完整路径，直接检查
        if os.path.isabs(filename) and os.path.exists(filename):
            return filename

        # 提取文件名
        basename = os.path.basename(filename)

        # 搜索路径
        search_paths = [
            self._audio_temp_dir / filename,
            self._audio_temp_dir / basename,
            self._output_dir / filename,
            self._backend_dir / filename,
            Path(filename),  # 原始路径
        ]

        for path in search_paths:
            if path.exists():
                return str(path.resolve())

        return None


def get_path_manager() -> PathManager:
    """获取全局路径管理器实例"""
    global _path_manager
    if _path_manager is None:
        _path_manager = PathManager()
    return _path_manager


def init_path_manager(project_root: Optional[str] = None) -> PathManager:
    """初始化全局路径管理器"""
    global _path_manager
    _path_manager = PathManager(project_root)
    return _path_manager


# 便捷函数
def get_audio_temp_dir() -> str:
    """获取音频临时目录"""
    return get_path_manager().audio_temp_dir


def get_video_temp_dir() -> str:
    """获取视频临时目录"""
    return get_path_manager().video_temp_dir


def get_output_dir() -> str:
    """获取输出目录"""
    return get_path_manager().output_dir


def get_final_output_dir() -> str:
    """获取最终输出目录"""
    return get_path_manager().final_output_dir


def validate_path_in_allowed_dirs(
    path: str,
    allowed_dirs: Optional[list] = None,
    check_exists: bool = True
) -> tuple[bool, str]:
    """
    验证路径是否在允许的目录范围内，防止路径遍历攻击

    Args:
        path: 要验证的路径
        allowed_dirs: 允许的目录列表，None 则使用默认允许目录
        check_exists: 是否检查文件存在

    Returns:
        (是否有效, 错误消息或解析后的路径)
    """
    if not path:
        return False, "路径不能为空"

    # 默认允许的目录
    if allowed_dirs is None:
        pm = get_path_manager()
        allowed_dirs = [
            pm.project_root,
            pm.backend_dir,
            pm.output_dir,
            pm.temp_dir,
            pm.audio_temp_dir,
            pm.video_temp_dir,
            pm.final_output_dir,
            # 添加上传目录
            os.path.join(pm.backend_dir, "uploads"),
            os.path.join(pm.backend_dir, "uploads", "videos"),
            os.path.join(pm.backend_dir, "uploads", "audios"),
            # 添加数据目录
            os.path.join(pm.project_root, "data"),
        ]

    # 解析路径
    p = Path(path)

    # 如果是相对路径，相对于项目根目录解析
    if not p.is_absolute():
        pm = get_path_manager()
        p = Path(pm.project_root) / path

    # 规范化路径（去除 .. 等）
    try:
        resolved = p.resolve()
    except Exception as e:
        return False, f"路径解析失败: {e}"

    # 检查是否包含危险字符
    path_str = str(resolved)
    dangerous_patterns = ['..', '~', '$', '|', '&', ';', '`', '\n', '\r']
    for pattern in dangerous_patterns:
        if pattern in path:
            return False, f"路径包含不允许的字符: {pattern}"

    # 检查是否在允许的目录内
    is_allowed = False
    for allowed_dir in allowed_dirs:
        allowed_path = Path(allowed_dir).resolve()
        try:
            # 检查 resolved 是否是 allowed_path 的子路径
            resolved.relative_to(allowed_path)
            is_allowed = True
            break
        except ValueError:
            continue

    if not is_allowed:
        return False, f"路径不在允许的目录范围内: {path}"

    # 检查文件是否存在（可选）
    if check_exists and not resolved.exists():
        return False, f"文件不存在: {path}"

    return True, str(resolved)


def is_safe_path(path: str) -> bool:
    """
    快速检查路径是否安全

    Args:
        path: 要检查的路径

    Returns:
        是否安全
    """
    valid, _ = validate_path_in_allowed_dirs(path, check_exists=False)
    return valid
