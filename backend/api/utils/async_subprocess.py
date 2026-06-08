"""
异步 subprocess 工具模块
提供非阻塞的 subprocess 执行，避免阻塞 FastAPI 事件循环
"""

import asyncio
import logging
import os
import platform
import signal
import subprocess
from typing import List, Optional, Tuple
from pathlib import Path as _Path

logger = logging.getLogger("async_subprocess")

# FFmpeg/FFprobe 绝对路径（跨平台兼容）
_PROJECT_ROOT = _Path(__file__).parent.parent.parent.parent
_FFMPEG_EXE = "ffmpeg.exe" if platform.system() == "Windows" else "ffmpeg"
_FFPROBE_EXE = "ffprobe.exe" if platform.system() == "Windows" else "ffprobe"
FFMPEG_PATH = str(_PROJECT_ROOT / "runtime" / "ffmpeg" / "bin" / _FFMPEG_EXE)
FFPROBE_PATH = str(_PROJECT_ROOT / "runtime" / "ffmpeg" / "bin" / _FFPROBE_EXE)

# Windows 平台静默创建进程的标志
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0


def _kill_process_tree(pid: int) -> None:
    """杀掉进程及其整个进程树，避免孤儿进程"""
    if platform.system() == "Windows":
        os.system(f"taskkill /F /T /PID {pid} >nul 2>&1")
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


async def async_run_subprocess(
    cmd: List[str],
    timeout: Optional[float] = None,
    check: bool = False,
    **kwargs
) -> Tuple[int, bytes, bytes]:
    """
    异步执行 subprocess 命令，替代 subprocess.run

    使用 asyncio.create_subprocess_exec 实现，不会阻塞事件循环。

    Args:
        cmd: 命令列表，如 ["ffmpeg", "-i", "input.mp4", "output.mp4"]
        timeout: 超时时间（秒），None 表示不超时
        check: 是否检查返回码（非0时抛出异常）
        **kwargs: 传递给 asyncio.create_subprocess_exec 的额外参数

    Returns:
        (returncode, stdout, stderr) 元组
    """
    creationflags = kwargs.pop("creationflags", CREATE_NO_WINDOW)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
            **kwargs
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.CancelledError:
            _kill_process_tree(process.pid)
            await process.wait()
            raise

        if check and process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode, cmd,
                stdout, stderr
            )

        return process.returncode, stdout, stderr

    except asyncio.TimeoutError:
        _kill_process_tree(process.pid)
        await process.wait()
        logger.warning(f"命令超时 ({timeout}s): {cmd[0]}")
        raise subprocess.TimeoutExpired(cmd, timeout)

    except subprocess.CalledProcessError as e:
        stderr_text = e.stderr.decode('utf-8', errors='replace')[:2000] if e.stderr else ''
        logger.error(f"命令执行失败 (code={e.returncode}): {stderr_text[:500]}")
        raise
    except Exception as e:
        logger.error(f"命令执行异常: {e}")
        raise


async def async_run_ffprobe(
    video_path: str,
    entries: str = "format=duration",
    output_format: str = "json"
) -> dict:
    """
    异步执行 ffprobe 获取视频信息

    Args:
        video_path: 视频文件路径
        entries: ffprobe show_entries 参数
        output_format: 输出格式

    Returns:
        解析后的 JSON 数据字典
    """
    cmd = [
        FFPROBE_PATH, "-v", "error",
        "-show_entries", entries,
        "-of", output_format,
        video_path
    ]

    returncode, stdout, stderr = await async_run_subprocess(cmd)

    if returncode != 0:
        logger.error(f"ffprobe 失败: {stderr.decode() if stderr else ''}")
        return {}

    import json
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        logger.error(f"ffprobe 输出 JSON 解析失败: {e}, raw: {stdout[:200]!r}")
        return {}
    except UnicodeDecodeError as e:
        logger.error(f"ffprobe 输出解码失败: {e}")
        return {}


async def async_run_ffmpeg(cmd: List[str], timeout: Optional[float] = None, check: bool = False) -> Tuple[int, bytes, bytes]:
    """
    异步执行 FFmpeg 命令

    自动添加 -y 参数（覆盖输出）和 Windows creationflags。

    Args:
        cmd: FFmpeg 命令列表（不含 -y）
        timeout: 超时时间（秒）
        check: 是否检查返回码（非0时抛出异常）

    Returns:
        (returncode, stdout, stderr) 元组
    """
    if not cmd or not cmd[0]:
        raise ValueError("ffmpeg 命令列表不能为空")
    # 确保包含 -y 参数（覆盖输出文件）
    if "-y" not in cmd:
        cmd = [cmd[0], "-y"] + cmd[1:]

    return await async_run_subprocess(cmd, timeout=timeout, check=check)