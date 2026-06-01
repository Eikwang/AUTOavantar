"""
系统设置路由
处理 API Key、提示词模版、默认参数等配置的查询和更新
"""

import logging
import os
import shutil
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("autoavantar-api.settings")

router = APIRouter()  # 移除 prefix，在 main.py 中统一配置


# 使用绝对路径确保配置目录正确（backend/config 相对于项目根目录）
CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config"))
SECRETS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "secrets"))


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def get_cache_dirs() -> List[str]:
    """
    获取需要清理的缓存目录列表
    
    Returns:
        存在的缓存目录路径列表
    """
    cache_dirs = [
        PROJECT_ROOT / "tmp",
        PROJECT_ROOT / "temp",
        PROJECT_ROOT / "output" / "temp",
        PROJECT_ROOT / "backend" / "tmp",
        PROJECT_ROOT / "backend" / "temp",
        PROJECT_ROOT / "backend" / "output",
        PROJECT_ROOT / "backend" / "logs",
        PROJECT_ROOT / "backend" / "uploads",
        PROJECT_ROOT / "engines" / "heygem" / "result",
        PROJECT_ROOT / "engines" / "heygem" / "temp",
    ]
    
    return [str(d) for d in cache_dirs if d.exists()]


def clear_directory(directory: str) -> tuple:
    """
    清理目录中的文件
    
    Args:
        directory: 目录路径
        
    Returns:
        (删除文件数量, 删除文件大小)
    """
    if not os.path.exists(directory):
        return 0, 0
    
    deleted_count = 0
    deleted_size = 0
    
    try:
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            try:
                if os.path.isfile(item_path):
                    file_size = os.path.getsize(item_path)
                    os.remove(item_path)
                    deleted_count += 1
                    deleted_size += file_size
                elif os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for f in files:
                            fp = os.path.join(root, f)
                            try:
                                file_size = os.path.getsize(fp)
                                os.remove(fp)
                                deleted_count += 1
                                deleted_size += file_size
                            except PermissionError:
                                logger.warning(f"跳过被占用的文件: {fp}")
                            except Exception as e:
                                logger.warning(f"删除文件失败: {fp}, 错误: {e}")
            except PermissionError:
                logger.warning(f"跳过被占用的项目: {item_path}")
            except Exception as e:
                logger.warning(f"处理项目失败: {item_path}, 错误: {e}")
    except Exception as e:
        logger.error(f"清理目录失败: {directory}, 错误: {e}")
    
    return deleted_count, deleted_size


class ApiKeysRequest(BaseModel):
    """API Key 配置请求"""
    deepseek_api_key: str = ""
    aliyun_api_key: str = ""


class PromptTemplatesRequest(BaseModel):
    """提示词模版请求"""
    single_person_prompt_template: str = ""
    dual_person_prompt_template: str = ""
    cover_prompt_template: str = ""


class DefaultParamsRequest(BaseModel):
    """默认参数请求"""
    heygem_original: bool = True
    heygem_inference_steps: int = 16
    dual_mode: bool = False
    tts_speed: float = 1.0
    tts_emo_weight: float = 0.4
    enable_precise_subtitle: bool = False
    enable_pip: bool = False  # 画外音默认开关


class ThemeRequest(BaseModel):
    """主题设置请求"""
    theme: str = "dark"  # "dark" 或 "light"


class SettingsData(BaseModel):
    """设置数据"""
    deepseek_api_key: str = ""
    aliyun_api_key: str = ""
    single_person_prompt_template: str = ""
    dual_person_prompt_template: str = ""
    cover_prompt_template: str = ""
    heygem_original: bool = True
    heygem_inference_steps: int = 16
    dual_mode: bool = False
    tts_speed: float = 1.0
    tts_emo_weight: float = 0.4
    enable_pip: bool = False  # 画外音默认开关


class SettingsResponse(BaseModel):
    """设置响应"""
    code: int
    message: str
    data: SettingsData


class SaveResponse(BaseModel):
    """保存响应"""
    code: int
    message: str


def _ensure_config_dir():
    """确保配置目录存在"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(SECRETS_DIR, exist_ok=True)


def _get_api_keys_path() -> str:
    """获取 API Key 配置路径"""
    return os.path.join(SECRETS_DIR, "api_keys.yaml")


def _get_prompt_templates_path() -> str:
    """获取提示词模版配置路径"""
    return os.path.join(CONFIG_DIR, "prompt_templates.yaml")


def _get_default_params_path() -> str:
    """获取默认参数配置路径"""
    return os.path.join(CONFIG_DIR, "default_params.yaml")


def _get_theme_path() -> str:
    """获取主题配置路径"""
    return os.path.join(CONFIG_DIR, "theme.yaml")


def _load_yaml(file_path: str, default: Dict = None) -> Dict:
    """加载 YAML 配置"""
    _ensure_config_dir()
    if default is None:
        default = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                return data if data else default
        except Exception as e:
            logger.error(f"加载配置文件失败 {file_path}: {e}")
    return default


def _save_yaml(file_path: str, data: Dict) -> bool:
    """保存 YAML 配置"""
    _ensure_config_dir()
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败 {file_path}: {e}")
        return False


async def _get_settings_impl():
    """获取设置的实现逻辑"""
    try:
        api_keys = _load_yaml(_get_api_keys_path(), {})
        prompt_templates = _load_yaml(_get_prompt_templates_path(), {})
        default_params = _load_yaml(_get_default_params_path(), {})

        # 兼容两种字段名格式
        # api_keys.yaml 可能使用:
        #   - 新格式: deepseek_api_key, aliyun_api_key
        #   - 旧格式: deepseek, aliyun
        deepseek_key = api_keys.get("deepseek_api_key", "") or api_keys.get("deepseek", "")
        aliyun_key = api_keys.get("aliyun_api_key", "") or api_keys.get("aliyun", "")

        return SettingsResponse(
            code=200,
            message="获取成功",
            data=SettingsData(
                deepseek_api_key=deepseek_key,
                aliyun_api_key=aliyun_key,
                single_person_prompt_template=prompt_templates.get("single_person_prompt_template", ""),
                dual_person_prompt_template=prompt_templates.get("dual_person_prompt_template", ""),
                cover_prompt_template=prompt_templates.get("cover_prompt_template", ""),
                heygem_original=default_params.get("heygem_original", True),
                heygem_inference_steps=default_params.get("heygem_inference_steps", 16),
                dual_mode=default_params.get("dual_mode", False),
                tts_speed=default_params.get("tts_speed", 1.0),
                tts_emo_weight=default_params.get("tts_emo_weight", 0.4)
            )
        )

    except Exception as e:
        logger.error(f"获取设置失败: {e}")
        return SettingsResponse(
            code=200,
            message="使用默认配置",
            data=SettingsData()
        )


@router.get("/", response_model=SettingsResponse)
async def get_settings():
    """
    获取所有设置
    """
    return await _get_settings_impl()


@router.get("", response_model=SettingsResponse)
async def get_settings_no_slash():
    """
    获取所有设置 (无斜杠版本)
    """
    return await _get_settings_impl()


@router.post("/api-keys", response_model=SaveResponse)
async def update_api_keys(request: ApiKeysRequest):
    """更新 API Key 配置"""
    try:
        data = {
            "deepseek_api_key": request.deepseek_api_key,
            "aliyun_api_key": request.aliyun_api_key
        }
        _save_yaml(_get_api_keys_path(), data)
        logger.info("API Key 配置已保存")
        return SaveResponse(code=200, message="API Key 配置已保存")
    except Exception as e:
        logger.error(f"保存失败: {e}")
        return SaveResponse(code=500, message=f"保存失败: {str(e)}")


@router.post("/prompt-templates", response_model=SaveResponse)
async def update_prompt_templates(request: PromptTemplatesRequest):
    """更新提示词模版"""
    try:
        data = {
            "single_person_prompt_template": request.single_person_prompt_template,
            "dual_person_prompt_template": request.dual_person_prompt_template,
            "cover_prompt_template": request.cover_prompt_template
        }
        _save_yaml(_get_prompt_templates_path(), data)
        logger.info("提示词模版已保存")
        return SaveResponse(code=200, message="提示词模版已保存")
    except Exception as e:
        logger.error(f"保存失败: {e}")
        return SaveResponse(code=500, message=f"保存失败: {str(e)}")


@router.post("/default-params", response_model=SaveResponse)
async def update_default_params(request: DefaultParamsRequest):
    """更新默认参数"""
    try:
        data = {
            "heygem_original": request.heygem_original,
            "heygem_inference_steps": request.heygem_inference_steps,
            "dual_mode": request.dual_mode,
            "tts_speed": request.tts_speed,
            "tts_emo_weight": request.tts_emo_weight,
            "enable_precise_subtitle": request.enable_precise_subtitle
        }
        _save_yaml(_get_default_params_path(), data)
        logger.info("默认参数已保存")
        return SaveResponse(code=200, message="默认参数已保存")
    except Exception as e:
        logger.error(f"保存失败: {e}")
        return SaveResponse(code=500, message=f"保存失败: {str(e)}")


class ThemeResponse(BaseModel):
    """主题响应"""
    code: int
    message: str
    data: Dict[str, str]


@router.get("/theme", response_model=ThemeResponse)
async def get_theme():
    """获取主题设置"""
    try:
        theme_data = _load_yaml(_get_theme_path(), {"theme": "dark"})
        return ThemeResponse(
            code=200,
            message="获取成功",
            data={"theme": theme_data.get("theme", "dark")}
        )
    except Exception as e:
        logger.error(f"获取主题失败: {e}")
        return ThemeResponse(
            code=200,
            message="使用默认主题",
            data={"theme": "dark"}
        )


@router.post("/theme", response_model=SaveResponse)
async def update_theme(request: ThemeRequest):
    """更新主题设置"""
    try:
        theme = request.theme.lower()
        if theme not in ["dark", "light"]:
            theme = "dark"
        _save_yaml(_get_theme_path(), {"theme": theme})
        logger.info(f"主题设置已保存: {theme}")
        return SaveResponse(code=200, message="主题设置已保存")
    except Exception as e:
        logger.error(f"保存主题失败: {e}")
        return SaveResponse(code=500, message=f"保存失败: {str(e)}")


async def _save_all_settings_impl(
    deepseek_api_key: str = "",
    aliyun_api_key: str = "",
    single_person_prompt_template: str = "",
    dual_person_prompt_template: str = "",
    cover_prompt_template: str = "",
    heygem_original: bool = True,
    heygem_inference_steps: int = 16,
    dual_mode: bool = False,
    tts_speed: float = 1.0,
    tts_emo_weight: float = 0.4
):
    """保存所有设置的实现逻辑"""
    try:
        _save_yaml(_get_api_keys_path(), {
            "deepseek_api_key": deepseek_api_key,
            "aliyun_api_key": aliyun_api_key
        })
        _save_yaml(_get_prompt_templates_path(), {
            "single_person_prompt_template": single_person_prompt_template,
            "dual_person_prompt_template": dual_person_prompt_template,
            "cover_prompt_template": cover_prompt_template
        })
        _save_yaml(_get_default_params_path(), {
            "heygem_original": heygem_original,
            "heygem_inference_steps": heygem_inference_steps,
            "dual_mode": dual_mode,
            "tts_speed": tts_speed,
            "tts_emo_weight": tts_emo_weight
        })
        logger.info("所有设置已保存")
        return SaveResponse(code=200, message="所有设置已保存")
    except Exception as e:
        logger.error(f"保存失败: {e}")
        return SaveResponse(code=500, message=f"保存失败: {str(e)}")


class SaveAllSettingsRequest(BaseModel):
    """保存所有设置请求"""
    deepseek_api_key: str = ""
    aliyun_api_key: str = ""
    single_person_prompt_template: str = ""
    dual_person_prompt_template: str = ""
    cover_prompt_template: str = ""
    heygem_original: bool = True
    heygem_inference_steps: int = 16
    dual_mode: bool = False
    tts_speed: float = 1.0
    tts_emo_weight: float = 0.4


@router.post("", response_model=SaveResponse)
async def save_all_settings(request: SaveAllSettingsRequest):
    """保存所有设置 (无斜杠版本 /api/settings)"""
    return await _save_all_settings_impl(
        request.deepseek_api_key, request.aliyun_api_key,
        request.single_person_prompt_template,
        request.dual_person_prompt_template,
        request.cover_prompt_template,
        request.heygem_original, request.heygem_inference_steps,
        request.dual_mode, request.tts_speed, request.emo_weight
    )


@router.post("/", response_model=SaveResponse)
async def save_all_settings_slash(request: SaveAllSettingsRequest):
    """保存所有设置 (有斜杠版本 /api/settings/)"""
    return await _save_all_settings_impl(
        request.deepseek_api_key, request.aliyun_api_key,
        request.single_person_prompt_template,
        request.dual_person_prompt_template,
        request.cover_prompt_template,
        request.heygem_original, request.heygem_inference_steps,
        request.dual_mode, request.tts_speed, request.tts_emo_weight
    )


class ClearCacheData(BaseModel):
    """清理缓存数据"""
    deleted_files: int = 0
    deleted_size: int = 0
    deleted_size_mb: float = 0.0
    errors: List[str] = []


class ClearCacheResponse(BaseModel):
    """清理缓存响应"""
    code: int
    message: str
    data: ClearCacheData


@router.post("/clear-cache", response_model=ClearCacheResponse)
async def clear_cache():
    """
    清理缓存
    
    清理所有临时目录中的文件，返回删除的文件数量和大小
    """
    try:
        cache_dirs = get_cache_dirs()
        total_deleted = 0
        total_size = 0
        errors = []
        
        for dir_path in cache_dirs:
            try:
                deleted, size = clear_directory(dir_path)
                total_deleted += deleted
                total_size += size
                logger.info(f"清理目录 {dir_path}: 删除 {deleted} 个文件, {size} 字节")
            except Exception as e:
                error_msg = f"清理目录失败 {dir_path}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        deleted_size_mb = total_size / (1024 * 1024)
        
        logger.info(f"清理缓存完成: 共删除 {total_deleted} 个文件, {deleted_size_mb:.2f} MB")
        
        return ClearCacheResponse(
            code=200,
            message=f"清理完成，共删除 {total_deleted} 个文件",
            data=ClearCacheData(
                deleted_files=total_deleted,
                deleted_size=total_size,
                deleted_size_mb=round(deleted_size_mb, 2),
                errors=errors
            )
        )
        
    except Exception as e:
        logger.error(f"清理缓存失败: {e}")
        return ClearCacheResponse(
            code=500,
            message=f"清理失败: {str(e)}",
            data=ClearCacheData()
        )
