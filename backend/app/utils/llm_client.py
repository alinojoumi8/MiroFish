"""
LLM客户端封装
统一使用OpenAI格式调用，运行时按激活的 provider profile（minimax / kimi / custom）解析参数。
"""

import json
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from . import llm_providers


class LLMClient:
    """LLM客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        # provider 优先：显式指定时锁定该 profile；否则读取运行时激活值
        if provider:
            profile = llm_providers.PROVIDERS.get(provider)
            if not profile:
                raise ValueError(f"Unknown provider: {provider}")
            self.api_key = api_key or self._resolve_env(profile.api_key_env)
            self.base_url = base_url or (
                profile.base_url if profile.name != "custom" else self._resolve_env("LLM_BASE_URL", "https://api.openai.com/v1")
            )
            self.model = model or (
                profile.default_model if profile.name != "custom" else self._resolve_env("LLM_MODEL_NAME", "gpt-4o-mini")
            )
            self.provider_name = profile.name
        else:
            self.api_key = api_key or llm_providers.get_active_api_key()
            self.base_url = base_url or llm_providers.get_active_base_url()
            self.model = model or llm_providers.get_active_model()
            self.provider_name = llm_providers.get_active_provider().name

        if not self.api_key:
            raise ValueError(
                f"LLM API key 未配置（provider={self.provider_name}）。"
                f"请在 .env 中设置对应的 API key。"
            )

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    @staticmethod
    def _resolve_env(name: str, default: str = "") -> str:
        import os
        return os.environ.get(name, default)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        发送聊天请求

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式（如JSON模式）

        Returns:
            模型响应文本
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        # 部分模型（MiniMax M2 / Kimi K2-Thinking 等）会在 content 中包含 <think> 思考内容，需要移除
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        发送聊天请求并返回JSON

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            解析后的JSON对象
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # 清理markdown代码块标记
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}")
