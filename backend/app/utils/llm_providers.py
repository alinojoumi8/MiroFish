"""
LLM Provider 注册表与运行时切换状态。

支持的 provider profile（每个 profile 描述一个 OpenAI 兼容端点的默认参数）:
- minimax: MiniMax M2
- kimi:    Moonshot Kimi K2 Thinking
- custom:  回退到 .env 中的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL_NAME

激活的 provider 写入磁盘上的 JSON 状态文件，重启后保留；进程内做了缓存。
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    base_url: str
    default_model: str
    api_key_env: str
    label: str
    # 部分 provider 要求客户端通过特定 User-Agent / 自定义 header 接入
    # （例如 Kimi For Coding 仅允许 Coding Agent 客户端访问）。
    # 使用 frozenset[tuple] 以保持 dataclass 的 frozen 不变性。
    extra_headers: tuple = ()


PROVIDERS: Dict[str, ProviderProfile] = {
    "minimax": ProviderProfile(
        name="minimax",
        base_url="https://api.minimax.io/v1",
        default_model="MiniMax-M2",
        api_key_env="MINIMAX_API_KEY",
        label="MiniMax M2",
    ),
    "kimi": ProviderProfile(
        name="kimi",
        # Kimi For Coding（Coding Plan）专用端点 —— 与 platform.moonshot.ai 不同。
        base_url="https://api.kimi.com/coding/v1",
        # 稳定模型 ID：自动指向最新版（当前 K2.6）
        default_model="kimi-for-coding",
        api_key_env="KIMI_API_KEY",
        label="Kimi K2.6 (For Coding)",
        # Coding Plan 仅授权给特定 Coding Agent 客户端（Claude Code / Kimi CLI / Roo Code 等）。
        # 用户授权下，MiroFish 以这些客户端的身份标识发起请求。
        extra_headers=(("User-Agent", "claude-cli/1.0.0"),),
    ),
    "openrouter": ProviderProfile(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        # Free, capable model; user can override via UI custom-model field
        default_model="deepseek/deepseek-chat-v3-0324:free",
        api_key_env="OPENROUTER_API_KEY",
        label="OpenRouter",
        # OpenRouter requires these headers for free-tier and attribution
        extra_headers=(
            ("HTTP-Referer", "https://mirofish.local"),
            ("X-Title", "MiroFish"),
        ),
    ),
    "custom": ProviderProfile(
        name="custom",
        base_url="",  # 运行时从 LLM_BASE_URL 读取
        default_model="",  # 运行时从 LLM_MODEL_NAME 读取
        api_key_env="LLM_API_KEY",
        label="Custom (.env LLM_*)",
    ),
}

DEFAULT_PROVIDER = "minimax"

_STATE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "uploads", ".llm_provider_state.json"
)
_state_lock = threading.Lock()
_cached_state: Optional[dict] = None


def _state_path() -> str:
    return os.path.abspath(_STATE_FILE)


def _load_state() -> dict:
    """加载激活状态。如果文件不存在或损坏，回退到环境变量 LLM_PROVIDER 或默认值。"""
    global _cached_state
    if _cached_state is not None:
        return _cached_state

    path = _state_path()
    state: dict = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            state = {}

    if "provider" not in state:
        state["provider"] = os.environ.get("LLM_PROVIDER", DEFAULT_PROVIDER)
    if state["provider"] not in PROVIDERS:
        state["provider"] = DEFAULT_PROVIDER
    state.setdefault("model_override", None)

    _cached_state = state
    return state


def _save_state(state: dict) -> None:
    global _cached_state
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    _cached_state = state


def get_active_provider() -> ProviderProfile:
    with _state_lock:
        state = _load_state()
        return PROVIDERS[state["provider"]]


def get_active_model() -> str:
    """返回当前激活 provider 的实际模型 ID（考虑用户的 model_override）。"""
    with _state_lock:
        state = _load_state()
        profile = PROVIDERS[state["provider"]]
        if state.get("model_override"):
            return state["model_override"]
        if profile.name == "custom":
            return os.environ.get("LLM_MODEL_NAME", "") or profile.default_model
        return profile.default_model


def get_active_base_url() -> str:
    profile = get_active_provider()
    if profile.name == "custom":
        return os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    return profile.base_url


def get_active_api_key() -> str:
    profile = get_active_provider()
    return os.environ.get(profile.api_key_env, "")


def get_active_extra_headers() -> Dict[str, str]:
    """返回当前激活 provider 需要附加的 HTTP header（如 User-Agent）。"""
    return dict(get_active_provider().extra_headers)


def set_active_provider(name: str, model_override: Optional[str] = None) -> ProviderProfile:
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Available: {list(PROVIDERS)}")
    with _state_lock:
        state = {"provider": name, "model_override": model_override or None}
        _save_state(state)
        return PROVIDERS[name]


def list_providers() -> List[dict]:
    """返回所有 provider 状态（含是否已配置 API key）。"""
    result = []
    active = get_active_provider().name
    for profile in PROVIDERS.values():
        configured = bool(os.environ.get(profile.api_key_env))
        if profile.name == "custom":
            # custom 还需要 base_url + model_name
            configured = configured and bool(os.environ.get("LLM_BASE_URL")) and bool(
                os.environ.get("LLM_MODEL_NAME")
            )
        entry = asdict(profile)
        entry["configured"] = configured
        entry["active"] = profile.name == active
        result.append(entry)
    return result


def invalidate_cache() -> None:
    """供测试或外部修改状态文件后调用。"""
    global _cached_state
    with _state_lock:
        _cached_state = None
