"""
FastAPI 应用入口
AUTOavantar 数字人视频生成系统后端 API
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ============================================================================
# 【关键修复】在导入任何其他模块之前，先应用 multiprocessing patch
# 这会阻止 Windows 上 multiprocessing 子进程创建控制台窗口
# 必须在导入任何使用 multiprocessing 的模块之前执行
# ============================================================================
base_dir = Path(__file__).parent.parent.parent
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

# 应用 multiprocessing CREATE_NO_WINDOW patch
try:
    from core.utils.multiprocessing_no_window import patch_multiprocessing
    patch_multiprocessing()
except Exception as e:
    # 如果 patch 失败，继续运行（会有控制台窗口弹出的问题）
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.services.database import init_database, close_database
from api.services.workflow_service import init_workflow_service, shutdown_workflow_service
from api.routers.websocket import manager
from config.settings import settings

from core.config.logging_config import setup_logging

# 配置日志
setup_logging()

# 获取 logger
logger = logging.getLogger("autoavantar-api")


def suppress_asyncio_connection_errors():
    """
    抑制 Windows 平台上 asyncio ProactorEventLoop 的 ConnectionResetError

    这是 Windows 平台上 asyncio 的已知问题，发生在管道连接关闭时。
    参考: https://bugs.python.org/issue43254
    """
    if sys.platform == 'win32':
        # 保存原始的异常处理器
        original_handler = asyncio.get_event_loop().get_exception_handler()

        def custom_exception_handler(loop, context):
            """自定义异常处理器，忽略 ConnectionResetError"""
            exception = context.get('exception')
            if exception:
                # 忽略 ConnectionResetError (WinError 10054)
                if isinstance(exception, ConnectionResetError):
                    return
                # 忽略管道关闭相关的错误
                if 'ConnectionResetError' in str(exception) or 'WinError 10054' in str(exception):
                    return
            # 其他异常使用原始处理器
            if original_handler:
                original_handler(loop, context)
            else:
                loop.default_exception_handler(context)

        # 设置自定义异常处理器
        try:
            asyncio.get_event_loop().set_exception_handler(custom_exception_handler)
        except RuntimeError:
            # 如果没有事件循环，稍后在 lifespan 中设置
            pass


def setup_asyncio_exception_handler():
    """在事件循环创建后设置异常处理器"""
    if sys.platform == 'win32':
        try:
            loop = asyncio.get_running_loop()

            def custom_exception_handler(loop, context):
                """自定义异常处理器，忽略 ConnectionResetError"""
                exception = context.get('exception')
                if exception:
                    # 忽略 ConnectionResetError (WinError 10054)
                    if isinstance(exception, ConnectionResetError):
                        logger.debug(f"忽略预期的连接关闭异常: {exception}")
                        return
                    # 检查异常消息
                    exc_str = str(exception)
                    if 'ConnectionResetError' in exc_str or 'WinError 10054' in exc_str or '远程主机强迫关闭' in exc_str:
                        logger.debug(f"忽略预期的连接关闭异常: {exception}")
                        return
                # 其他异常使用默认处理器
                loop.default_exception_handler(context)

            loop.set_exception_handler(custom_exception_handler)
            logger.debug("已设置 asyncio 异常处理器，将忽略 ConnectionResetError")
        except RuntimeError:
            pass


async def websocket_heartbeat_checker():
    """WebSocket 心跳检测后台任务"""
    while True:
        try:
            # 增加超时时间到 120 秒，给浏览器更多时间
            await manager.check_inactive_connections(timeout_seconds=120)
            await asyncio.sleep(30)  # 每 30 秒检查一次
        except Exception as e:
            logger.error(f"WebSocket 心跳检测异常: {e}")
            await asyncio.sleep(5)


async def load_engines_background(db=None):
    """后台加载引擎（不阻塞 API 启动）"""
    try:
        logger.info("开始后台加载引擎...")
        from api.services.workflow_service import get_workflow_service, init_workflow_service

        # 检查服务是否已初始化
        service = get_workflow_service()
        if service is None:
            # 初始化工作流服务（会加载引擎）
            await init_workflow_service(
                output_dir="output",
                max_concurrent_tasks=3,
                database=db
            )
            logger.info("引擎后台加载完成")
        else:
            logger.info("工作流服务已存在，跳过引擎加载")
    except Exception as e:
        logger.error(f"后台加载引擎失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理

    启动顺序优化：
    1. 创建必要目录
    2. 初始化数据库（确保 API 立即可用）
    3. 启动 WebSocket 心跳检测
    4. 后台异步加载引擎（不阻塞 API 启动）
    """
    # 设置 asyncio 异常处理器（处理 Windows 平台的 ConnectionResetError）
    setup_asyncio_exception_handler()

    # 启动时执行
    logger.info("=" * 50)
    logger.info("AUTOavantar API 服务启动中...")

    # 1. 创建必要的目录
    os.makedirs("data", exist_ok=True)
    os.makedirs("output", exist_ok=True)
    os.makedirs("temp", exist_ok=True)
    os.makedirs("uploads", exist_ok=True)

    # 2. 初始化数据库（优先初始化，确保 API 立即可用）
    try:
        db = await init_database()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        db = None

    # 3. 启动 WebSocket 心跳检测任务
    heartbeat_task = asyncio.create_task(websocket_heartbeat_checker())
    logger.info("WebSocket 心跳检测已启动")

    # 3.1 清理过期临时文件（智能裁剪）
    try:
        from api.services.smart_cut_service import get_smart_cut_service
        smart_cut_service = get_smart_cut_service()
        await smart_cut_service.cleanup_temp_files(max_age_hours=24)
        logger.info("智能裁剪临时文件清理完成")
    except Exception as e:
        logger.warning(f"临时文件清理失败: {e}")

    # 4. 后台异步加载引擎（不阻塞 API 启动）
    engine_load_task = asyncio.create_task(load_engines_background(db))
    logger.info("引擎后台加载任务已启动")

    # API 已就绪，可以开始接收请求
    logger.info("=" * 50)
    logger.info("✅ AUTOavantar API 服务已就绪")
    logger.info("   引擎正在后台加载中，首次任务可能需要等待...")
    logger.info("=" * 50)

    yield

    # 关闭时执行
    logger.info("AUTOavantar API 服务关闭中...")

    # 取消后台任务
    heartbeat_task.cancel()
    engine_load_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    try:
        await engine_load_task
    except asyncio.CancelledError:
        pass
    logger.info("后台任务已停止")

    # 关闭工作流服务
    try:
        await shutdown_workflow_service()
        logger.info("工作流服务已关闭")
    except Exception as e:
        logger.error(f"工作流服务关闭失败: {e}")

    # 关闭数据库
    try:
        await close_database()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"数据库关闭失败: {e}")


# 创建 FastAPI 应用
app = FastAPI(
    title="AUTOavantar API",
    version="1.0.0",
    description="数字人视频生成系统后端 API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)


# 添加验证错误处理器
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """
    捕获验证错误

    安全说明：生产环境不记录请求体，防止敏感信息泄露
    """
    # 仅记录错误类型，不记录具体内容
    error_types = [e.get("type", "unknown") for e in exc.errors()]
    logger.warning(f"请求验证失败: {error_types}")

    return JSONResponse(
        status_code=422,
        content={"detail": "请求参数验证失败"}
    )

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
if os.path.exists("uploads"):
    # 替换StaticFiles为自定义文件服务，禁用缓存
    from fastapi import Response
    from starlette.responses import FileResponse
    
    @app.get("/files/{file_path:path}")
    async def serve_files(file_path: str):
        """自定义文件服务，禁用浏览器缓存，支持多个目录"""
        import os
        from pathlib import Path
        
        # 标准化路径：替换反斜杠为正斜杠
        file_path = file_path.replace('\\', '/')
        
        # 确定后端根目录（相对于当前工作目录）
        # 后端从 backend/ 目录启动，所以需要向上找一级
        current_dir = Path.cwd()
        if current_dir.name == "backend":
            backend_root = current_dir
        else:
            backend_root = current_dir / "backend"
        
        # 如果路径已经包含 backend/ 前缀，需要去掉它
        if file_path.startswith('backend/'):
            file_path = file_path[8:]  # 去掉 "backend/" 前缀
        
        # 搜索路径列表（相对于后端根目录）
        search_paths = [
            backend_root / "uploads" / file_path,
            backend_root / file_path,
            backend_root / "data" / file_path,
            Path.cwd().parent / "uploads" / file_path,  # 项目根目录下的 uploads
            Path.cwd().parent / "backend" / file_path,  # 项目根目录下的 backend
            Path.cwd().parent / file_path,  # 项目根目录下直接查找（兼容 data/thumbnails 等路径）
        ]
        
        file_full_path = None
        for path in search_paths:
            if path.exists() and path.is_file():
                file_full_path = path
                break
        
        if not file_full_path:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
        
        # 使用FileResponse并设置缓存控制头，禁用缓存
        return FileResponse(
            path=file_full_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

# 注册路由 - 调整顺序，将具体路由放在通配符路由之前
from api.routers import tasks, materials, upload, health, websocket, settings, functions, tags, system, license, smart_cut, media_clip

# 1. 健康检查（最具体的路由）
app.include_router(health.router, prefix="/api", tags=["健康检查"])

# 1.1 系统配置路由
app.include_router(system.router, prefix="/api/system", tags=["系统配置"])

# 2. 功能接口（具体路由）
app.include_router(functions.router, prefix="/api", tags=["功能接口"])

# 3. 素材库（具体路由）
app.include_router(materials.router, prefix="/api", tags=["素材库"])

# 4. 上传（具体路由）
app.include_router(upload.router, prefix="/api", tags=["文件上传"])

# 5. WebSocket（具体路由）
app.include_router(websocket.router, prefix="/api", tags=["WebSocket"])

# 6. 设置（具体路由）
app.include_router(settings.router, prefix="/api/settings", tags=["系统设置"])

# 7. 标签管理（具体路由）
app.include_router(tags.router, prefix="/api/tags", tags=["标签管理"])

# 8. 智能裁剪（具体路由）
app.include_router(smart_cut.router, prefix="/api/smart-cut", tags=["智能裁剪"])

# 8.5 音视频剪辑（具体路由）
app.include_router(media_clip.router, prefix="/api/media-clip", tags=["音视频剪辑"])

# 8. 任务管理（包含通配符路由，放在最后）
app.include_router(tasks.router, prefix="/api/tasks", tags=["任务管理"])

# 9. 授权管理
app.include_router(license.router, prefix="/api/license", tags=["授权管理"])


# 挂载前端静态文件
def mount_frontend():
    """挂载前端静态文件"""
    # 查找前端 dist 目录
    current_dir = Path.cwd()
    possible_frontend_paths = [
        current_dir / "frontend" / "dist",
        current_dir.parent / "frontend" / "dist",
        current_dir / ".." / "frontend" / "dist",
    ]

    frontend_dist = None
    for path in possible_frontend_paths:
        if path.exists() and (path / "index.html").exists():
            frontend_dist = path
            break

    if frontend_dist:
        logger.info(f"挂载前端静态文件: {frontend_dist}")

        # 挂载静态资源目录（JS、CSS 等）
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        # 处理所有非 API 路由，返回 index.html（SPA 路由支持）
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """SPA 路由支持 - 所有非 API 路由返回 index.html"""
            from starlette.responses import FileResponse

            # 检查是否是 API 路由
            if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Not found")

            # 检查是否是静态文件请求
            file_path = frontend_dist / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(path=file_path)

            # 否则返回 index.html（SPA 路由）
            return FileResponse(path=frontend_dist / "index.html")

        return True

    logger.warning("未找到前端 dist 目录，前端服务未挂载")
    return False


frontend_mounted = mount_frontend()


@app.get("/")
async def root():
    """根路径"""
    if frontend_mounted:
        # 如果前端已挂载，返回 index.html
        from starlette.responses import FileResponse
        current_dir = Path.cwd()
        possible_frontend_paths = [
            current_dir / "frontend" / "dist",
            current_dir.parent / "frontend" / "dist",
            current_dir / ".." / "frontend" / "dist",
        ]
        for path in possible_frontend_paths:
            if path.exists() and (path / "index.html").exists():
                return FileResponse(path=path / "index.html")

    return {
        "name": "AUTOavantar API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "websocket": "/api/ws/{task_id}"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=9010,
        reload=True
    )
