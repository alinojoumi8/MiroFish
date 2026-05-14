"""
记忆后端抽象层。

通过 `get_memory_backend()` 获取当前激活的后端实例。
后端选择由 `Config.MEMORY_BACKEND` 决定：
- "lightrag": LightRAG + FalkorDB（默认，推荐 — 最快，MIT 许可）
- "graphiti": 本地 Neo4j + Graphiti（兜底选项）
- "zep":      Zep Cloud（兜底）
"""

from __future__ import annotations

import threading
from typing import Optional

from .backend import MemoryBackend
from .types import MemoryNode, MemoryEdge, MemorySearchResult


_instance: Optional[MemoryBackend] = None
_lock = threading.Lock()


def get_memory_backend() -> MemoryBackend:
    """单例获取激活的记忆后端。线程安全。"""
    global _instance
    if _instance is not None:
        return _instance

    with _lock:
        if _instance is not None:
            return _instance

        from ...config import Config
        backend_name = (Config.MEMORY_BACKEND or 'graphiti').lower()

        if backend_name == 'zep':
            from .zep_backend import ZepBackend
            _instance = ZepBackend()
        elif backend_name == 'graphiti':
            from .graphiti_backend import GraphitiBackend
            _instance = GraphitiBackend()
        elif backend_name == 'lightrag':
            from .lightrag_backend import LightRAGBackend
            _instance = LightRAGBackend()
        else:
            raise ValueError(
                f"未知的 MEMORY_BACKEND: {backend_name}（支持 lightrag / graphiti / zep）"
            )
        return _instance


def reset_memory_backend() -> None:
    """主要用于测试。下次 get_memory_backend() 会重新构建。"""
    global _instance
    with _lock:
        if _instance is not None:
            try:
                _instance.close()
            except Exception:
                pass
        _instance = None


__all__ = [
    "MemoryBackend",
    "MemoryNode",
    "MemoryEdge",
    "MemorySearchResult",
    "get_memory_backend",
    "reset_memory_backend",
]
