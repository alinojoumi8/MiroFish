"""
记忆后端通用数据结构。

字段命名刻意贴近现有 Zep 调用方期望的属性
（uuid, name, fact, source_node_uuid, target_node_uuid, valid_at 等），
以最小化对调用点的改造。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryNode:
    """图谱节点"""
    uuid: str
    name: str
    labels: List[str] = field(default_factory=list)
    summary: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    # 兼容旧调用 (getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''))
    @property
    def uuid_(self) -> str:
        return self.uuid


@dataclass
class MemoryEdge:
    """图谱边（带时间戳的事实关系）"""
    uuid: str
    name: str
    fact: str = ""
    source_node_uuid: str = ""
    target_node_uuid: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None
    episodes: List[str] = field(default_factory=list)
    fact_type: Optional[str] = None

    @property
    def uuid_(self) -> str:
        return self.uuid


@dataclass
class MemorySearchResult:
    """搜索结果：边集合 + 节点集合"""
    edges: List[MemoryEdge] = field(default_factory=list)
    nodes: List[MemoryNode] = field(default_factory=list)


@dataclass
class EpisodeStatus:
    """add_episode/add_batch 的返回值。"""
    uuid: str
    processed: bool = True  # Graphiti 是同步的，默认 True；Zep 异步默认 False
