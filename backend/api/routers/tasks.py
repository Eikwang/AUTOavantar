"""
任务管理路由
处理任务的创建、查询、状态轮询和删除
集成工作流服务和 WebSocket 通知
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import os

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, Query

from api.schemas import (
    TaskCreateRequest,
    TaskUpdateRequest,
    TaskControlRequest,
    TaskResponse,
    TaskListResponse,
    TaskStatusUpdate,
    TaskStatus,
    TaskStage,
    ApiResponse,
)
from api.services.workflow_service import (
    WorkflowService,
    AsyncTask,
    AsyncTaskStatus,
    get_workflow_service,
)
from api.services.websocket_notifier import (
    notifier,
    register_task_websocket
)

logger = logging.getLogger("autoavantar-api.tasks")

router = APIRouter()


def get_workflow_service_or_raise() -> WorkflowService:
    """
    获取工作流服务，如果未初始化则抛出异常

    用于 FastAPI Depends，确保服务已初始化
    """
    service = get_workflow_service()
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="服务正在初始化中，请稍后再试。引擎正在后台加载..."
        )
    return service


def _get_role_audio_info(role_id: str) -> Optional[Dict[str, Any]]:
    """
    获取角色的音频信息

    Args:
        role_id: 角色ID

    Returns:
        包含 is_double_mode, audio_path, left_audio_path, right_audio_path 的字典
        如果角色不存在返回 None
    """
    try:
        from api.routers.materials import MOCK_ROLES, MOCK_AUDIOS

        for role in MOCK_ROLES:
            if role.get("role_id") == role_id:
                is_double_mode = role.get("is_double_mode", False)

                if is_double_mode:
                    left_audio_id = role.get("left_audio_id")
                    right_audio_id = role.get("right_audio_id")

                    left_audio_path = None
                    right_audio_path = None

                    for audio in MOCK_AUDIOS:
                        if audio.get("id") == left_audio_id:
                            left_audio_path = audio.get("path")
                        if audio.get("id") == right_audio_id:
                            right_audio_path = audio.get("path")

                    logger.info(f"双人角色 {role_id}: left_audio_id={left_audio_id}, right_audio_id={right_audio_id}")
                    logger.info(f"双人角色 {role_id}: left_audio_path={left_audio_path}, right_audio_path={right_audio_path}")

                    return {
                        "is_double_mode": True,
                        "audio_path": None,
                        "left_audio_path": left_audio_path,
                        "right_audio_path": right_audio_path
                    }
                else:
                    # 单人模式
                    audio_id = role.get("audio_id")
                    audio_path = None

                    for audio in MOCK_AUDIOS:
                        if audio.get("id") == audio_id:
                            audio_path = audio.get("path")

                    logger.info(f"单人角色 {role_id}: audio_id={audio_id}, audio_path={audio_path}")

                    return {
                        "is_double_mode": False,
                        "audio_path": audio_path,
                        "left_audio_path": None,
                        "right_audio_path": None
                    }

        logger.warning(f"角色不存在: {role_id}")
        return None
    except Exception as e:
        logger.warning(f"获取角色音频信息失败: {e}")
        return None


@router.post("", response_model=ApiResponse)
async def create_task(
    request: TaskCreateRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    创建新任务（使用工作流服务异步执行）

    创建后会自动注册 WebSocket 通知回调

    Args:
        request: 任务创建请求参数

    Returns:
        创建的任务信息
    """
    # 配额检查（任务创建环节）
    from api.services.license_service import get_license_service
    license_service = get_license_service()
    license_status = license_service.get_license_status()

    # CR-001: 配额检查分散到四环节，任务创建时只检查不消耗
    if not license_status.is_activated:
        quota_result = license_service.check_quota_for_stage("create")
        if not quota_result.has_quota:
            raise HTTPException(
                status_code=403,
                detail=f"今日配额已用完，未激活用户每日限制 {quota_result.max_quota} 个任务。请激活后继续使用。"
            )
        logger.info(f"未激活用户配额检查通过，剩余配额: {quota_result.remaining}")

    # 画外音校验
    if request.enable_pip:
        if request.enable_double_mode:
            # 双人模式：左右两边画外音视频都必须提供
            if not request.pip_left_video_path or not request.pip_right_video_path:
                raise HTTPException(
                    status_code=422,
                    detail="双人模式需要同时上传左右两边画外音视频"
                )
        else:
            # 单人模式：至少需要提供画外音视频
            if not request.pip_video_path:
                raise HTTPException(
                    status_code=422,
                    detail="请上传画外音视频素材"
                )

    try:
        enable_double_mode = request.enable_double_mode
        left_prompt_audio_path = request.left_prompt_audio_path or ""
        right_prompt_audio_path = request.right_prompt_audio_path or ""
        prompt_audio_path = request.prompt_audio_path or ""
        
        if request.role_id:
            role_info = _get_role_audio_info(request.role_id)
            if role_info:
                if role_info["is_double_mode"]:
                    enable_double_mode = True
                    # 只有当前端没有传递音频路径时，才使用角色绑定的音频
                    if not left_prompt_audio_path and role_info.get("left_audio_path"):
                        left_prompt_audio_path = role_info["left_audio_path"]
                    if not right_prompt_audio_path and role_info.get("right_audio_path"):
                        right_prompt_audio_path = role_info["right_audio_path"]
                    logger.info(f"从双人角色自动设置: enable_double_mode=True, left={left_prompt_audio_path}, right={right_prompt_audio_path}")
                else:
                    # 单人模式：只有当前端没有传递音频路径时，才使用角色绑定的音频
                    if not prompt_audio_path and role_info.get("audio_path"):
                        prompt_audio_path = role_info["audio_path"]
                        logger.info(f"从单人角色自动设置: prompt_audio_path={prompt_audio_path}")
        
        logger.info(f"API create_task 请求参数: enable_double_mode={enable_double_mode}")
        logger.info(f"API create_task 请求参数: left_prompt_audio_path={left_prompt_audio_path}")
        logger.info(f"API create_task 请求参数: right_prompt_audio_path={right_prompt_audio_path}")
        logger.info(f"API create_task 请求参数: prompt_audio_path={prompt_audio_path}")
        logger.info(f"API create_task 请求参数: heygem_batch_size={request.heygem_batch_size}")

        task = await workflow_service.create_task(
            name=request.name,
            source_video_path=request.source_video_path or "",
            script_text=request.script_text or "",
            topic=request.topic or "",
            prompt_audio_path=prompt_audio_path,
            left_prompt_audio_path=left_prompt_audio_path,
            right_prompt_audio_path=right_prompt_audio_path,
            enable_double_mode=enable_double_mode,
            bgm_path=request.bgm_path or "",
            use_llm_generate=request.use_llm_generate,
            enable_postprocess=request.enable_postprocess,
            enable_denoise=request.enable_denoise,
            denoise_strength=request.denoise_strength,
            tts_speed=request.tts_speed,
            tts_emo_weight=request.tts_emo_weight,
            left_tts_speed=request.left_tts_speed,
            right_tts_speed=request.right_tts_speed,
            left_tts_emo_weight=request.left_tts_emo_weight,
            right_tts_emo_weight=request.right_tts_emo_weight,
            enable_subtitle=request.enable_subtitle,
            subtitle_font=request.subtitle_font,
            subtitle_size=request.subtitle_size,
            subtitle_color=request.subtitle_color,
            subtitle_stroke_color=request.subtitle_stroke_color,
            subtitle_stroke_width=request.subtitle_stroke_width,
            subtitle_position=request.subtitle_position,
            subtitle_background_alpha=request.subtitle_background_alpha,
            subtitle_line_spacing=request.subtitle_line_spacing,
            enable_bgm=request.enable_bgm,
            bgm_volume=request.bgm_volume,
            enable_cover=request.enable_cover,
            heygem_steps=request.heygem_steps,
            heygem_batch_size=request.heygem_batch_size,
            opening_video=request.opening_video,
            loop_videos=request.loop_videos,
            scene_videos=request.scene_videos,
            ending_video=request.ending_video,
            opening_video_with_tags=request.opening_video_with_tags.model_dump() if request.opening_video_with_tags else None,
            loop_videos_with_tags=[v.model_dump() for v in request.loop_videos_with_tags] if request.loop_videos_with_tags else [],
            scene_videos_with_tags=[v.model_dump() for v in request.scene_videos_with_tags] if request.scene_videos_with_tags else [],
            ending_video_with_tags=request.ending_video_with_tags.model_dump() if request.ending_video_with_tags else None,
            scene_tag_group_id=request.scene_tag_group_id,
            # 转场效果参数
            enable_transition=request.enable_transition,
            transition_type=request.transition_type,
            transition_effect=request.transition_effect,
            transition_random=request.transition_random,
            transition_random_all=request.transition_random_all,
            transition_duration=request.transition_duration,
            # 画外音参数
            enable_pip=request.enable_pip,
            pip_video_path=request.pip_video_path,
            pip_left_video_path=request.pip_left_video_path,
            pip_right_video_path=request.pip_right_video_path
        )

        await register_task_websocket(task.task_id, workflow_service)

        logger.info(f"任务创建成功: {task.task_id} - {request.name}")

        return ApiResponse(
            code=200,
            message="任务创建成功",
            data=TaskResponse(
                task_id=task.task_id,
                name=task.name,
                status=TaskStatus(task.status.value),
                current_stage=TaskStage.PENDING,
                progress=task.progress,
                source_video_path=task.source_video_path,
                script_text=task.script_text,
                prompt_audio_path=task.prompt_audio_path,
                bgm_path=task.bgm_path,
                output_path=task.output_path,
                error_message=task.error_message,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
        )
    except Exception as e:
        logger.error(f"创建任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("", response_model=ApiResponse)
async def get_tasks(
    status: Optional[str] = Query(None, description="任务状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    获取任务列表
    
    Args:
        status: 可选的任务状态过滤
        page: 页码
        page_size: 每页数量
        
    Returns:
        任务列表
    """
    try:
        task_filter = None
        if status:
            try:
                task_filter = AsyncTaskStatus(status)
            except ValueError:
                pass

        tasks = await workflow_service.list_tasks(status=task_filter)

        # 分页处理
        total = len(tasks)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_tasks = tasks[start:end]

        return ApiResponse(
            code=200,
            message="success",
            data=TaskListResponse(
                items=[
                    TaskResponse(
                        task_id=task.task_id,
                        name=task.name,
                        status=TaskStatus(task.status.value),
                        current_stage=(
                            TaskStage(task.current_stage)
                            if task.current_stage and task.current_stage in [s.value for s in TaskStage]
                            else TaskStage.INITIALIZING
                        ),
                        progress=task.progress,
                        source_video_path=task.source_video_path,
                        script_text=task.script_text,
                        prompt_audio_path=task.prompt_audio_path,
                        bgm_path=task.bgm_path,
                        output_path=task.output_path,
                        error_message=task.error_message,
                        created_at=task.created_at,
                        updated_at=task.updated_at,
                        is_priority=task.is_priority,
                    )
                    for task in paginated_tasks
                ],
                total=total,
                page=page,
                page_size=page_size,
            )
        )
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")


@router.get("/{task_id}", response_model=ApiResponse)
async def get_task(
    task_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    获取任务详情
    
    Args:
        task_id: 任务ID
        
    Returns:
        任务详情
    """
    try:
        task = await workflow_service.get_task_status(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        return ApiResponse(
            code=200,
            message="success",
            data=TaskResponse(
                task_id=task.task_id,
                name=task.name,
                status=TaskStatus(task.status.value),
                current_stage=(
                    TaskStage(task.current_stage) 
                    if task.current_stage and task.current_stage in [s.value for s in TaskStage] 
                    else TaskStage.INITIALIZING
                ),
                progress=task.progress,
                source_video_path=task.source_video_path,
                script_text=task.script_text,
                prompt_audio_path=task.prompt_audio_path,
                bgm_path=task.bgm_path,
                output_path=task.output_path,
                error_message=task.error_message,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取任务详情失败: {str(e)}")


@router.put("/{task_id}", response_model=ApiResponse)
async def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    更新任务信息
    
    Args:
        task_id: 任务ID
        request: 更新请求
        
    Returns:
        更新后的任务信息
    """
    try:
        task = await workflow_service.update_task(
            task_id=task_id,
            name=request.name,
            script_text=request.script_text,
            status=request.status.value if request.status else None
        )

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        return ApiResponse(
            code=200,
            message="任务更新成功",
            data=TaskResponse(
                task_id=task.task_id,
                name=task.name,
                status=TaskStatus(task.status.value),
                current_stage=(
                    TaskStage(task.current_stage) 
                    if task.current_stage and task.current_stage in [s.value for s in TaskStage] 
                    else TaskStage.INITIALIZING
                ),
                progress=task.progress,
                source_video_path=task.source_video_path,
                script_text=task.script_text,
                prompt_audio_path=task.prompt_audio_path,
                bgm_path=task.bgm_path,
                output_path=task.output_path,
                error_message=task.error_message,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新任务失败: {str(e)}")


@router.delete("/{task_id}", response_model=ApiResponse)
async def delete_task(
    task_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    删除任务
    
    Args:
        task_id: 任务ID
        
    Returns:
        删除结果
    """
    try:
        success = await workflow_service.delete_task(task_id)

        if not success:
            raise HTTPException(status_code=404, detail="任务不存在")

        logger.info(f"任务删除: {task_id}")

        return ApiResponse(
            code=200,
            message="任务删除成功",
            data={"task_id": task_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除任务失败: {str(e)}")


@router.post("/{task_id}/cancel", response_model=ApiResponse)
async def cancel_task(
    task_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    取消任务（独立接口，兼容前端调用）

    Args:
        task_id: 任务ID

    Returns:
        取消结果
    """
    try:
        # 先断开 WebSocket 连接，防止后续消息覆盖取消状态
        from api.routers.websocket import manager
        await manager.disconnect_task(task_id)

        success = await workflow_service.cancel_task(task_id)

        if not success:
            raise HTTPException(status_code=400, detail="任务取消失败")

        logger.info(f"任务取消: {task_id}")

        return ApiResponse(
            code=200,
            message="任务取消成功",
            data={"task_id": task_id, "action": "cancel"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")


@router.post("/{task_id}/control", response_model=ApiResponse)
async def control_task(
    task_id: str,
    request: TaskControlRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    控制任务（暂停、恢复、取消、重试、从检查点重启）
    
    Args:
        task_id: 任务ID
        request: 控制请求
        
    Returns:
        控制结果
    """
    try:
        action = request.action.lower()
        
        if action == "pause":
            success = await workflow_service.pause_task(task_id)
            message = "任务暂停成功"
        elif action == "resume":
            await register_task_websocket(task_id, workflow_service)
            success = await workflow_service.resume_task(task_id)
            message = "任务恢复成功"
        elif action == "cancel":
            # 先断开 WebSocket 连接，防止后续消息覆盖取消状态
            from api.routers.websocket import manager
            await manager.disconnect_task(task_id)
            success = await workflow_service.cancel_task(task_id)
            message = "任务取消成功"
        elif action == "retry":
            await register_task_websocket(task_id, workflow_service)
            success = await workflow_service.retry_task(task_id)
            message = "任务重试成功"
        elif action == "restart_checkpoint":
            await register_task_websocket(task_id, workflow_service)
            success = await workflow_service.restart_from_checkpoint(task_id)
            message = "任务从检查点重启成功"
        else:
            raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")

        if not success:
            raise HTTPException(status_code=400, detail="操作失败")

        logger.info(f"任务控制 {action}: {task_id}")

        return ApiResponse(
            code=200,
            message=message,
            data={"task_id": task_id, "action": action}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"控制任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"控制任务失败: {str(e)}")


@router.post("/{task_id}/start", response_model=ApiResponse)
async def start_task(
    task_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    启动任务

    Args:
        task_id: 任务ID

    Returns:
        启动结果
    """
    try:
        await register_task_websocket(task_id, workflow_service)

        # 不等待 WebSocket 连接，让任务立即启动
        # WebSocket 连接会在后台建立，状态更新通过轮询机制也能获取
        success = await workflow_service.start_task(task_id)

        if not success:
            raise HTTPException(status_code=400, detail="启动失败")

        logger.info(f"任务启动: {task_id}")

        return ApiResponse(
            code=200,
            message="任务启动成功",
            data={"task_id": task_id, "action": "start"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


@router.post("/{task_id}/priority", response_model=ApiResponse)
async def priority_task(
    task_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    将任务优先级提升到最前

    Args:
        task_id: 任务ID

    Returns:
        操作结果
    """
    try:
        success = await workflow_service.priority_task(task_id)

        if not success:
            raise HTTPException(status_code=400, detail="操作失败，任务可能不是等待状态")

        logger.info(f"任务置顶: {task_id}")

        return ApiResponse(
            code=200,
            message="任务已置顶",
            data={"task_id": task_id, "action": "priority"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"任务置顶失败: {e}")
        raise HTTPException(status_code=500, detail=f"任务置顶失败: {str(e)}")


@router.get("/{task_id}/logs", response_model=ApiResponse)
async def get_task_logs(
    task_id: str,
    lines: int = Query(100, ge=1, le=1000, description="日志行数"),
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    获取任务日志
    
    Args:
        task_id: 任务ID
        lines: 日志行数
        
    Returns:
        任务日志
    """
    try:
        logs = await workflow_service.get_task_logs(task_id, lines)
        
        return ApiResponse(
            code=200,
            message="success",
            data={
                "task_id": task_id,
                "logs": logs,
                "lines": len(logs)
            }
        )
    except Exception as e:
        logger.error(f"获取任务日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取任务日志失败: {str(e)}")


@router.post("/extract-audio", response_model=ApiResponse)
async def extract_audio(
    video_path: str
):
    """
    从视频中提取音频
    
    Args:
        video_path: 视频路径（相对于 backend 目录）
        
    Returns:
        提取的音频信息
    """
    from api.routers.functions import extract_audio as extract_audio_func
    from api.routers.functions import ExtractAudioRequest
    from pathlib import Path
    
    try:
        # 构建完整的视频路径（相对于 backend 目录）
        backend_root = Path(__file__).resolve().parent.parent.parent
        full_video_path = str(backend_root / video_path.replace("\\", "/"))
        
        request = ExtractAudioRequest(video_path=full_video_path)
        response = await extract_audio_func(request)
        
        return ApiResponse(
            code=200,
            message="音频提取成功",
            data={
                "audio_path": response.audio_path,
                "duration": response.duration
            }
        )
    except Exception as e:
        logger.error(f"音频提取失败: {e}")
        raise HTTPException(status_code=500, detail=f"音频提取失败: {str(e)}")


@router.post("/denoise-audio", response_model=ApiResponse)
async def denoise_audio(
    audio_id: str,
    workflow_service: WorkflowService = Depends(get_workflow_service_or_raise)
):
    """
    音频降噪
    
    Args:
        audio_id: 音频ID
        
    Returns:
        降噪后的音频信息
    """
    try:
        audio_info = await workflow_service.denoise_audio(audio_id)
        
        return ApiResponse(
            code=200,
            message="音频降噪成功",
            data=audio_info
        )
    except Exception as e:
        logger.error(f"音频降噪失败: {e}")
        raise HTTPException(status_code=500, detail=f"音频降噪失败: {str(e)}")


@router.post("/analyze-face", response_model=ApiResponse)
async def analyze_face(
    video_path: str,
    video_type: str = "opening"
):
    """
    面部分析
    
    Args:
        video_path: 视频路径（相对于 backend 目录）
        video_type: 视频类型
        
    Returns:
        面部分析结果
    """
    from api.routers.functions import get_face_analyzer
    from pathlib import Path
    
    try:
        analyzer = get_face_analyzer()
        
        # 构建完整的视频路径
        backend_root = Path(__file__).resolve().parent.parent.parent
        full_video_path = str(backend_root / video_path.replace("\\", "/"))
        
        if not os.path.exists(full_video_path):
            raise HTTPException(status_code=400, detail=f"视频文件不存在: {video_path}")

        result = analyzer.detect_faces(full_video_path)

        invalid_count = result.invalid_frames

        output_path = full_video_path
        if invalid_count > 0:
            name, ext = os.path.splitext(full_video_path)
            temp_output = f"{name}_temp{ext}"
            # 传递已有的检测结果，避免重复检测
            process_result = analyzer.process_video(full_video_path, temp_output, detect_result=result)
            
            try:
                if os.path.exists(temp_output):
                    os.replace(temp_output, full_video_path)
                logger.info(f"面部分析完成，已移除 {invalid_count} 帧不合格画面")
            except Exception as e:
                logger.error(f"替换视频时出错: {e}")
            finally:
                try:
                    if os.path.exists(temp_output):
                        os.remove(temp_output)
                except Exception as e:
                    logger.error(f"清理临时文件时出错: {e}")
        
        analysis_result = {
            "status": "success",
            "invalid_frame_count": invalid_count,
            "output_video_path": output_path,
            "message": f"分析完成，已移除 {invalid_count} 段不合格画面"
        }
        
        return ApiResponse(
            code=200,
            message="面部分析成功",
            data=analysis_result
        )
    except Exception as e:
        logger.error(f"面部分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"面部分析失败: {str(e)}")


@router.get("/transition-effects", response_model=ApiResponse)
async def get_transition_effects():
    """
    获取所有可用的转场效果列表

    Returns:
        按分类组织的转场效果字典
    """
    from business.postprocess.transition_effects import get_all_transition_effects

    effects = get_all_transition_effects()

    return ApiResponse(
        code=200,
        message="success",
        data=effects
    )
