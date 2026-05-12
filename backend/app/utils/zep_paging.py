"""分页读取节点 / 边的兼容入口。

历史上这里包了 Zep 的 UUID-cursor 分页与重试。现在内部分页已经下沉到
`memory.MemoryBackend.get_all_nodes/edges` 内部，所以本模块只是 thin shim：
直接调用 backend，保留旧函数签名以避免大面积改动。

签名兼容性说明：
- 旧签名第一个参数是 `Zep client`。如果调用方仍传 Zep 客户端，这里会忽略它
  并使用 `get_memory_backend()`；新调用应直接传 MemoryBackend。
"""

from __future__ import annotations

from typing import Any, List

from ..services.memory import get_memory_backend
from ..services.memory.types import MemoryEdge, MemoryNode
from .logger import get_logger

logger = get_logger('mirofish.memory.paging')


def fetch_all_nodes(
    client: Any,  # 兼容历史调用：Zep client 或 MemoryBackend 或 None
    graph_id: str,
    page_size: int = 100,  # 保留参数兼容但忽略（分页在 backend 内）
    max_items: int = 2000,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> List[MemoryNode]:
    """分页获取图谱节点。最多 max_items 个。"""
    backend = client if hasattr(client, 'get_all_nodes') else get_memory_backend()
    return backend.get_all_nodes(graph_id, max_items=max_items)


def fetch_all_edges(
    client: Any,
    graph_id: str,
    page_size: int = 100,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> List[MemoryEdge]:
    """分页获取图谱边。"""
    backend = client if hasattr(client, 'get_all_edges') else get_memory_backend()
    return backend.get_all_edges(graph_id)
