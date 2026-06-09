"""
系统配置 API 路由
提供低显存模式等系统级设置的获取和更新接口
以及 CUDA 检测和版本更新功能
"""

import logging
import subprocess
import urllib.request
import urllib.error
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys

from core.system_config import get_config_manager
from core.system.cuda_checker import get_cuda_checker, CUDACheckResult

logger = logging.getLogger("autoavantar-api")

router = APIRouter()

# 版本检测配置 - 使用 Gitee 仓库
VERSION_URL = "https://gitee.com/astink/autoavantar/raw/master/VERSION"
UPDATE_URL = "https://gitee.com/astink/autoavantar"


def get_app_dir() -> Path:
    """获取应用程序目录"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).parent.parent.parent.parent


def read_local_version() -> str:
    """读取本地版本号"""
    version_file = get_app_dir() / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding='utf-8').strip()
    return "1.0.0"


def fetch_remote_version() -> Optional[str]:
    """从 Gitee 获取远程版本号"""
    try:
        req = urllib.request.Request(VERSION_URL, method='GET')
        req.add_header('User-Agent', 'AUTOavantar-Version-Check')
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8').strip()
    except Exception as e:
        logger.debug(f"获取远程版本失败：{e}")
        return None


def compare_versions(v1: str, v2: str) -> int:
    """比较版本号，返回 -1/0/1"""
    def parse(v: str) -> tuple:
        return tuple(int(p) for p in v.split('.') if p.isdigit())
    try:
        p1, p2 = parse(v1), parse(v2)
        max_len = max(len(p1), len(p2))
        p1 = p1 + (0,) * (max_len - len(p1))
        p2 = p2 + (0,) * (max_len - len(p2))
        return (p1 > p2) - (p1 < p2)
    except Exception:
        return 0


class SystemConfigResponse(BaseModel):
    """系统配置响应模型"""
    low_memory_mode: bool
    ultra_low_memory: bool = False
    enable_precise_subtitle: bool = False


class SystemConfigUpdateRequest(BaseModel):
    """系统配置更新请求模型"""
    low_memory_mode: Optional[bool] = None
    ultra_low_memory: Optional[bool] = None
    enable_precise_subtitle: Optional[bool] = None


class VersionInfo(BaseModel):
    """版本信息模型"""
    local_version: str
    remote_version: Optional[str] = None
    has_update: bool = False
    update_url: str = UPDATE_URL


class UpdateResponse(BaseModel):
    """更新响应模型"""
    success: bool
    message: str


@router.get("/config", response_model=SystemConfigResponse)
async def get_system_config():
    """
    获取系统配置

    返回当前系统配置，包括低显存模式、超低显存模式和精准字幕功能状态
    → AC-218
    """
    try:
        config_manager = get_config_manager()
        low_memory_mode = config_manager.get_low_memory_mode()
        ultra_low_memory = config_manager.get_ultra_low_memory()
        enable_precise_subtitle = config_manager.get_enable_precise_subtitle()

        return SystemConfigResponse(
            low_memory_mode=low_memory_mode,
            ultra_low_memory=ultra_low_memory,
            enable_precise_subtitle=enable_precise_subtitle
        )
    except Exception as e:
        logger.error(f"获取系统配置失败：{e}")
        raise HTTPException(status_code=500, detail=f"获取系统配置失败：{str(e)}")


@router.put("/config", response_model=SystemConfigResponse)
async def update_system_config(request: SystemConfigUpdateRequest):
    """
    更新系统配置

    更新系统配置并持久化保存
    → AC-219
    """
    try:
        config_manager = get_config_manager()

        # 更新低显存模式
        if request.low_memory_mode is not None:
            success = config_manager.set_low_memory_mode(request.low_memory_mode)
            if not success:
                raise HTTPException(status_code=500, detail="保存配置失败")

            logger.info(f"系统配置已更新：low_memory_mode={request.low_memory_mode}")

        # 更新超低显存模式
        if request.ultra_low_memory is not None:
            success = config_manager.set_ultra_low_memory(request.ultra_low_memory)
            if not success:
                raise HTTPException(status_code=500, detail="保存配置失败")

            logger.info(f"系统配置已更新：ultra_low_memory={request.ultra_low_memory}")

        # 更新精准字幕功能
        if request.enable_precise_subtitle is not None:
            success = config_manager.set_enable_precise_subtitle(request.enable_precise_subtitle)
            if not success:
                raise HTTPException(status_code=500, detail="保存配置失败")

            logger.info(f"系统配置已更新：enable_precise_subtitle={request.enable_precise_subtitle}")

        # 返回更新后的配置
        return SystemConfigResponse(
            low_memory_mode=config_manager.get_low_memory_mode(),
            ultra_low_memory=config_manager.get_ultra_low_memory(),
            enable_precise_subtitle=config_manager.get_enable_precise_subtitle()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新系统配置失败：{e}")
        raise HTTPException(status_code=500, detail=f"更新系统配置失败：{str(e)}")


@router.get("/cuda-status", response_model=CUDACheckResult)
async def get_cuda_status():
    """
    获取 CUDA 状态

    检测 GPU 驱动版本、CUDA 版本、显存等信息
    结果会缓存 7 天，避免每次启动都检测
    → AC-001: 获取 CUDA 状态
    """
    try:
        from core.system.cuda_checker import get_cuda_checker

        # 获取检测器并执行检测（会使用缓存）
        checker = get_cuda_checker(get_app_dir())
        result = checker.check()
        return result
    except Exception as e:
        logger.error(f"CUDA 检测失败：{e}")
        return CUDACheckResult(
            available=False,
            is_supported=False,
            message=f"CUDA 检测失败：{str(e)}"
        )


@router.get("/version", response_model=VersionInfo)
async def get_version_info():
    """
    获取版本信息

    返回本地版本和远程版本信息，用于检测更新
    → AC-002: 获取版本信息
    """
    try:
        local_version = read_local_version()
        remote_version = fetch_remote_version()

        has_update = False
        if remote_version:
            has_update = compare_versions(remote_version, local_version) > 0

        return VersionInfo(
            local_version=local_version,
            remote_version=remote_version,
            has_update=has_update,
            update_url=UPDATE_URL
        )
    except Exception as e:
        logger.error(f"获取版本信息失败：{e}")
        return VersionInfo(
            local_version=read_local_version(),
            remote_version=None,
            has_update=False
        )


@router.post("/update", response_model=UpdateResponse)
async def trigger_update():
    """
    触发更新流程

    更新流程（优化后）：
    1. 创建 .update_pending 标记文件
    2. 启动独立更新脚本（分离进程，不依赖主程序）
    3. 退出当前程序
    4. 更新脚本等待主程序退出后执行 git 更新
    5. 更新完成后自动启动应用

    核心改进：更新脚本作为完全独立的进程运行，
    不再需要用户手动重启程序来触发更新。
    -> AC-003: 触发更新流程
    """
    import asyncio
    import platform as _platform

    try:
        app_dir = get_app_dir()
        update_flag_file = app_dir / ".update_pending"

        # 创建更新标记
        update_flag_file.write_text("pending", encoding='utf-8')
        logger.info("更新标记已创建")

        # 启动独立更新脚本（分离进程）
        update_script = app_dir / "tools" / "update_and_restart.py"
        python_exe = str(app_dir / "runtime" / "python.exe") if (app_dir / "runtime" / "python.exe").exists() else "python"

        if update_script.exists():
            try:
                creationflags = 0
                if _platform.system() == "Windows":
                    creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

                subprocess.Popen(
                    [python_exe, str(update_script), "--auto-start"],
                    cwd=str(app_dir),
                    creationflags=creationflags
                )
                logger.info("更新脚本已启动（分离进程）")
            except Exception as e:
                logger.warning(f"启动更新脚本失败: {e}")
        else:
            logger.warning(f"更新脚本不存在: {update_script}")

        # 异步延迟退出，给前端时间显示提示
        async def delayed_exit():
            await asyncio.sleep(3)
            logger.info("系统退出，更新脚本将接管更新流程...")

            # 先调用 shutdown 接口进行资源清理
            try:
                shutdown_url = f"http://127.0.0.1:8000/api/system/shutdown"
                req = urllib.request.Request(shutdown_url, method='POST')
                req.add_header('Content-Type', 'application/json')
                with urllib.request.urlopen(req, timeout=5) as response:
                    logger.info(f"清理接口调用完成：{response.status}")
            except Exception as e:
                logger.warning(f"清理接口调用失败：{e}")

            # 退出主程序，更新脚本已独立运行
            import os
            os._exit(0)

        # 启动延迟退出任务
        asyncio.create_task(delayed_exit())

        return UpdateResponse(
            success=True,
            message="更新已启动，系统将自动退出并完成更新"
        )
    except Exception as e:
        logger.error(f"触发更新失败：{e}")
        raise HTTPException(status_code=500, detail=f"触发更新失败：{str(e)}")


class ShutdownResponse(BaseModel):
    """关闭响应模型"""
    success: bool
    message: str


@router.post("/shutdown", response_model=ShutdownResponse)
async def shutdown_system():
    """
    系统关闭接口

    在系统退出前调用，确保所有引擎资源正确释放：
    1. 卸载 TTS 引擎
    2. 卸载 HeyGem 引擎
    3. 终止所有子进程
    4. 释放显存

    此接口由 desktop_launcher 在退出前调用。
    """
    try:
        logger.info("收到系统关闭请求，开始清理资源...")

        # 调用工作流服务的 shutdown 方法
        from api.services.workflow_service import get_workflow_service
        service = get_workflow_service()

        if service:
            logger.info("正在关闭工作流服务...")
            service.shutdown()
            logger.info("工作流服务已关闭")
        else:
            logger.info("工作流服务未初始化，跳过关闭")

        # 清理 CUDA 缓存
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logger.info("CUDA 缓存已清理")
        except ImportError:
            pass

        logger.info("系统资源清理完成")

        return ShutdownResponse(
            success=True,
            message="系统资源已清理"
        )
    except Exception as e:
        logger.error(f"系统关闭清理失败：{e}")
        # 即使失败也返回成功，因为后端进程会被强制终止
        return ShutdownResponse(
            success=True,
            message=f"清理过程出现异常但已忽略：{str(e)}"
        )
