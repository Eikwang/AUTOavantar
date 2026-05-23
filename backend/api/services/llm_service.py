"""
LLM服务模块
使用 OpenAI SDK 调用 DeepSeek API 生成文案
"""

import asyncio
import json
import logging
import re
from typing import Optional

from openai import OpenAI

logger = logging.getLogger("autoavantar-api.llm")

# LLM API base URL
LLM_BASE_URL = "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2"


class LLMScriptGenerator:
    """LLM文案生成器，使用 OpenAI SDK"""

    def __init__(self, provider: str, api_key: str, model: str):
        """初始化LLM文案生成器"""
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self._client = None
        logger.info(f"LLM 文案生成器初始化成功，提供商: {provider}, 模型: {model}")

    def _get_client(self) -> OpenAI:
        """获取或创建 OpenAI 客户端"""
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=LLM_BASE_URL,
                timeout=180.0,
                max_retries=2
            )
        return self._client

    async def generate(self, prompt: str) -> str:
        """生成文案（异步方式，使用 asyncio.to_thread 避免阻塞事件循环）

        Args:
            prompt: 提示词（已包含主题的完整提示词）

        Returns:
            生成的文案（JSON格式）
        """
        return await asyncio.to_thread(self._generate_sync, prompt)

    def _generate_sync(self, prompt: str) -> str:
        """同步生成文案（内部方法，供 async generate 调用）

        Args:
            prompt: 提示词（已包含主题的完整提示词）

        Returns:
            生成的文案（JSON格式）
        """
        if not self.api_key:
            raise ValueError("DeepSeek API Key 未配置，请在设置中配置 API Key")

        logger.info(f"开始调用 DeepSeek API 生成文案，提示词: {prompt[:100]}...")

        client = self._get_client()

        try:
            kwargs = {}
            is_reasoning_model = "pro" in self.model.lower() or "reasoner" in self.model.lower()
            if is_reasoning_model:
                kwargs["reasoning_effort"] = "high"
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一位专业的文案策划师，擅长为数字人视频生成结构化的文案。请严格按照用户要求的JSON格式输出，不要添加多余的解释。"},
                    {"role": "user", "content": prompt}
                ],
                stream=False,
                temperature=0.7,
                max_tokens=2048,
                **kwargs
            )

            content = response.choices[0].message.content

            logger.info(f"DeepSeek API 调用成功，生成文案长度: {len(content)}")

            script = self._extract_json(content)

            return script

        except Exception as e:
            logger.error(f"DeepSeek API 调用失败: {e}")
            raise Exception(f"API 调用失败: {str(e)}")

    def _extract_json(self, content: str) -> str:
        """从返回内容中提取 JSON 字符串

        Args:
            content: API 返回的内容

        Returns:
            JSON 字符串
        """
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass

        json_pattern = r'```(?:json)?\s*([\s\S]*?)```'
        matches = re.findall(json_pattern, content)
        for match in matches:
            try:
                json.loads(match.strip())
                return match.strip()
            except json.JSONDecodeError:
                continue

        first_brace = content.find('{')
        last_brace = content.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            potential_json = content[first_brace:last_brace + 1]
            try:
                json.loads(potential_json)
                return potential_json
            except json.JSONDecodeError:
                pass

        logger.warning("无法从返回内容中提取 JSON，返回原始内容")
        return content


def create_script_generator(provider: str, api_key: str, model: str) -> LLMScriptGenerator:
    """创建LLM文案生成器实例

    Args:
        provider: LLM提供商
        api_key: API密钥
        model: 模型名称

    Returns:
        LLMScriptGenerator实例
    """
    return LLMScriptGenerator(provider, api_key, model)