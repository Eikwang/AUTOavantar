"""
CUDA 驱动检测服务
检测 GPU 驱动版本是否满足 CUDA 12.x 要求

特性：
- 检测结果缓存到文件，避免每次启动都检测
- 缓存有效期 7 天
- 首次检测或缓存过期时才执行实际检测
"""

import logging
import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

logger = logging.getLogger("autoavantar.cuda")

# 缓存文件路径（在应用数据目录下）
CACHE_FILE_NAME = "cuda_check_cache.json"
CACHE_EXPIRE_DAYS = 7  # 缓存有效期 7 天


class CUDACheckResult(BaseModel):
    """CUDA 检测结果"""
    available: bool
    driver_version: Optional[str] = None
    cuda_version: Optional[str] = None
    gpu_name: Optional[str] = None
    gpu_memory_gb: float = 0.0
    is_supported: bool = False
    minimum_driver: str = "525.60.13"
    minimum_memory_gb: float = 6.0
    message: str = ""
    cached: bool = False  # 是否来自缓存
    check_time: Optional[float] = None  # 检测时间戳


class CUDAChecker:
    """
    CUDA 驱动检测器

    检测规则：
    - PyTorch 2.8.0+cu128 要求 CUDA 12.x
    - 最低驱动版本：525.60.13（NVIDIA 官方 CUDA 12.x 要求）
    - 最低显存：6GB（建议 8GB+）

    缓存机制：
    - 检测结果缓存到文件，有效期 7 天
    - 首次运行或缓存过期时才执行实际检测
    """

    MINIMUM_DRIVER_VERSION = "525.60.13"
    MINIMUM_MEMORY_GB = 6.0

    def __init__(self, app_dir: Optional[Path] = None):
        self._torch = None
        self._torch_available = False
        self._app_dir = app_dir
        self._cache_file: Optional[Path] = None
        self._init_cache_file()
        # 延迟加载 PyTorch，只在需要时才加载
        logger.info("CUDA 检测器已初始化（延迟加载模式）")

    def _init_cache_file(self):
        """初始化缓存文件路径"""
        if self._app_dir:
            cache_dir = self._app_dir / "backend" / "data"
        else:
            # 尝试从当前工作目录推断
            cwd = Path.cwd()
            if (cwd / "backend").exists():
                cache_dir = cwd / "backend" / "data"
            elif cwd.name == "backend":
                cache_dir = cwd / "data"
            else:
                cache_dir = Path("backend/data")

        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = cache_dir / CACHE_FILE_NAME
        logger.debug(f"CUDA 缓存文件: {self._cache_file}")

    def _load_cache(self) -> Optional[CUDACheckResult]:
        """加载缓存的检测结果"""
        if not self._cache_file or not self._cache_file.exists():
            return None

        try:
            with open(self._cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            check_time = data.get('check_time', 0)
            age_days = (time.time() - check_time) / (24 * 3600)

            if age_days > CACHE_EXPIRE_DAYS:
                logger.info(f"CUDA 缓存已过期 ({age_days:.1f} 天)")
                return None

            data.pop('cached', None)
            result = CUDACheckResult(**data, cached=True)
            logger.info(f"使用缓存的 CUDA 检测结果 ({age_days:.1f} 天前)")
            return result

        except Exception as e:
            logger.warning(f"加载 CUDA 缓存失败: {e}")
            return None

    def _save_cache(self, result: CUDACheckResult):
        """保存检测结果到缓存"""
        if not self._cache_file:
            return

        try:
            result.check_time = time.time()
            with open(self._cache_file, 'w', encoding='utf-8') as f:
                json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)
            logger.info(f"CUDA 检测结果已缓存到: {self._cache_file}")
        except Exception as e:
            logger.warning(f"保存 CUDA 缓存失败: {e}")

    def _ensure_torch(self):
        """确保 PyTorch 已加载"""
        if self._torch is not None:
            return

        try:
            import torch
            self._torch = torch
            self._torch_available = torch.cuda.is_available()
            logger.info(f"PyTorch CUDA 可用: {self._torch_available}")
        except ImportError:
            logger.warning("PyTorch 未安装")
            self._torch_available = False

    def check(self, force: bool = False) -> CUDACheckResult:
        """
        执行 CUDA 检测

        Args:
            force: 是否强制重新检测（忽略缓存）

        Returns:
            CUDACheckResult: 检测结果
        """
        # 尝试从缓存加载
        if not force:
            cached = self._load_cache()
            if cached:
                return cached

        # 执行实际检测
        logger.info("开始执行 CUDA 检测...")
        self._ensure_torch()

        if not self._torch_available:
            result = CUDACheckResult(
                available=False,
                is_supported=False,
                message="PyTorch CUDA 不可用。请检查 CUDA 安装或 GPU 驱动。"
            )
            self._save_cache(result)
            return result

        try:
            # 获取 GPU 信息
            gpu_name = self._torch.cuda.get_device_name(0)
            gpu_memory_bytes = self._torch.cuda.get_device_properties(0).total_memory
            gpu_memory_gb = round(gpu_memory_bytes / (1024 ** 3), 1)

            # 获取 CUDA 版本
            cuda_version = self._torch.version.cuda

            # 获取驱动版本
            driver_version = self._get_driver_version()

            # 检查是否满足要求
            is_driver_ok = self._compare_driver_versions(
                driver_version,
                self.MINIMUM_DRIVER_VERSION
            ) >= 0 if driver_version else False

            is_memory_ok = gpu_memory_gb >= self.MINIMUM_MEMORY_GB

            is_supported = is_driver_ok and is_memory_ok

            # 生成提示信息
            if is_supported:
                message = "GPU 驱动正常"
            else:
                issues = []
                if not is_driver_ok:
                    issues.append(f"驱动版本过低（当前: {driver_version or '未知'}，需要: {self.MINIMUM_DRIVER_VERSION}+）")
                if not is_memory_ok:
                    issues.append(f"显存不足（当前: {gpu_memory_gb}GB，建议: {self.MINIMUM_MEMORY_GB}GB+）")
                message = "。".join(issues) + "。请更新显卡驱动或使用更高配置的 GPU。"

            result = CUDACheckResult(
                available=True,
                driver_version=driver_version,
                cuda_version=cuda_version,
                gpu_name=gpu_name,
                gpu_memory_gb=gpu_memory_gb,
                is_supported=is_supported,
                message=message
            )

            logger.info(f"CUDA 检测完成: {result.model_dump()}")
            self._save_cache(result)
            return result

        except Exception as e:
            logger.error(f"CUDA 检测失败: {e}")
            result = CUDACheckResult(
                available=False,
                is_supported=False,
                message=f"CUDA 检测失败: {str(e)}"
            )
            self._save_cache(result)
            return result

    def _get_driver_version(self) -> Optional[str]:
        """获取 NVIDIA 驱动版本"""
        # 方法1: Windows 注册表（最可靠，不依赖 PATH）
        try:
            version = self._get_driver_version_windows()
            if version:
                logger.debug(f"从注册表获取驱动版本: {version}")
                return version
        except Exception as e:
            logger.debug(f"注册表获取驱动版本失败: {e}")

        # 方法2: 通过 nvidia-smi 获取（需要系统 PATH）
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                if version:
                    logger.debug(f"从 nvidia-smi 获取驱动版本: {version}")
                    return version
        except Exception as e:
            logger.debug(f"nvidia-smi 获取驱动版本失败: {e}")

        return None

    def _get_driver_version_windows(self) -> Optional[str]:
        """Windows 平台通过注册表获取驱动版本"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY
            )

            for i in range(winreg.QueryInfoKey(key)[0]):
                subkey_name = winreg.EnumKey(key, i)
                if "NVIDIA" in subkey_name.upper() and "Display" in subkey_name.upper():
                    try:
                        subkey = winreg.OpenKey(key, subkey_name)
                        version, _ = winreg.QueryValueEx(subkey, "DisplayVersion")
                        winreg.CloseKey(subkey)
                        if version:
                            return version
                    except Exception:
                        continue

            winreg.CloseKey(key)
        except Exception:
            pass

        return None

    def _compare_driver_versions(self, v1: str, v2: str) -> int:
        """
        比较两个驱动版本号

        Returns:
            -1: v1 < v2
            0: v1 == v2
            1: v1 > v2
        """
        def parse_version(v: str) -> tuple:
            """解析版本号为元组"""
            parts = v.replace(',', '.').split('.')
            return tuple(int(p) for p in parts if p.isdigit())

        try:
            p1 = parse_version(v1)
            p2 = parse_version(v2)

            # 补齐长度
            max_len = max(len(p1), len(p2))
            p1 = p1 + (0,) * (max_len - len(p1))
            p2 = p2 + (0,) * (max_len - len(p2))

            if p1 < p2:
                return -1
            elif p1 > p2:
                return 1
            return 0
        except Exception:
            return 0


# 全局单例
_cuda_checker: Optional[CUDAChecker] = None


def get_cuda_checker(app_dir: Optional[Path] = None) -> CUDAChecker:
    """
    获取 CUDA 检测器单例

    Args:
        app_dir: 应用目录路径，用于确定缓存文件位置
    """
    global _cuda_checker
    if _cuda_checker is None:
        _cuda_checker = CUDAChecker(app_dir)
    return _cuda_checker


def init_cuda_checker(app_dir: Path) -> CUDAChecker:
    """
    初始化 CUDA 检测器（在应用启动时调用）

    Args:
        app_dir: 应用目录路径
    """
    global _cuda_checker
    _cuda_checker = CUDAChecker(app_dir)
    return _cuda_checker
