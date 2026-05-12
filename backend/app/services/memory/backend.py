"""
记忆后端协议（abstract base）。
所有后端必须实现这些方法，调用方代码不应直接 import 后端实现类。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .types import EpisodeStatus, MemoryEdge, MemoryNode, MemorySearchResult


class MemoryBackend(ABC):
    """通用记忆后端接口。"""

    # ----- 图谱生命周期 -----

    @abstractmethod
    def create_graph(self, graph_id: str, name: str, description: str = "") -> str:
        """创建图谱（如果后端有此概念）。返回 graph_id。Graphiti 实现为 no-op。"""

    @abstractmethod
    def delete_graph(self, graph_id: str) -> None:
        """删除图谱（含所有节点 / 边）。"""

    @abstractmethod
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        """
        设置实体 / 边类型。
        Zep 用动态 Pydantic 类；Graphiti 用类型提示参数。
        实现可以选择 best-effort 应用，或仅记录到本地用于 add_episode 时使用。
        """

    # ----- 写入 -----

    @abstractmethod
    def add_episode(
        self,
        graph_id: str,
        data: str,
        episode_type: str = "text",
        name: Optional[str] = None,
    ) -> EpisodeStatus:
        """添加一个 episode（文本/JSON）到图谱。返回 episode 的 uuid 与 processed 状态。"""

    @abstractmethod
    def add_batch(
        self,
        graph_id: str,
        episodes: List[Dict[str, str]],
    ) -> List[EpisodeStatus]:
        """批量添加。每个 dict 形如 {"data": "...", "type": "text"}。"""

    @abstractmethod
    def get_episode_processed(self, episode_uuid: str) -> bool:
        """查询某 episode 是否已处理完毕（Graphiti 始终返回 True）。"""

    # ----- 读取：节点 / 边 -----

    @abstractmethod
    def get_all_nodes(
        self,
        graph_id: str,
        max_items: int = 2000,
    ) -> List[MemoryNode]:
        """分页获取图谱所有节点。"""

    @abstractmethod
    def get_all_edges(self, graph_id: str) -> List[MemoryEdge]:
        """分页获取图谱所有边（含时间字段）。"""

    @abstractmethod
    def get_node(self, node_uuid: str) -> Optional[MemoryNode]:
        """按 UUID 获取单个节点。"""

    @abstractmethod
    def get_entity_edges(self, node_uuid: str) -> List[MemoryEdge]:
        """获取与某节点相连的所有边。"""

    # ----- 搜索 -----

    @abstractmethod
    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",  # "edges" | "nodes" | "both"
    ) -> MemorySearchResult:
        """语义 + 关键词混合搜索。可选 cross-encoder 重排。"""

    # ----- 生命周期 -----

    def close(self) -> None:
        """释放底层连接 / 驱动。默认无操作。"""
        return None
