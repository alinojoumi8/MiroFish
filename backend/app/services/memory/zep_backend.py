"""
Zep Cloud 适配器。行为与原 `Zep(api_key=...)` 直连保持一致。
"""

from __future__ import annotations

import time
import warnings
from typing import Any, Callable, Dict, List, Optional, TypeVar

from zep_cloud import EntityEdgeSourceTarget, EpisodeData, InternalServerError
from zep_cloud.client import Zep

from ...config import Config
from ...utils.logger import get_logger
from .backend import MemoryBackend
from .types import EpisodeStatus, MemoryEdge, MemoryNode, MemorySearchResult

logger = get_logger('mirofish.memory.zep')

T = TypeVar('T')

_DEFAULT_PAGE_SIZE = 100
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_DELAY = 2.0


def _retry(
    fn: Callable[..., T],
    *args: Any,
    op: str = "zep call",
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
    **kwargs: Any,
) -> T:
    last: Optional[BaseException] = None
    delay = retry_delay
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except (ConnectionError, TimeoutError, OSError, InternalServerError) as e:
            last = e
            if attempt < max_retries - 1:
                logger.warning(f"{op} attempt {attempt + 1} failed: {str(e)[:100]}, retry in {delay:.1f}s")
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"{op} failed after {max_retries}: {e}")
    assert last is not None
    raise last


def _node_from_zep(node: Any) -> MemoryNode:
    uuid_ = getattr(node, 'uuid_', None) or getattr(node, 'uuid', None) or ""
    created_at = getattr(node, 'created_at', None)
    return MemoryNode(
        uuid=str(uuid_) if uuid_ else "",
        name=getattr(node, 'name', '') or "",
        labels=list(getattr(node, 'labels', None) or []),
        summary=getattr(node, 'summary', '') or "",
        attributes=dict(getattr(node, 'attributes', None) or {}),
        created_at=str(created_at) if created_at else None,
    )


def _edge_from_zep(edge: Any) -> MemoryEdge:
    uuid_ = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
    episodes = getattr(edge, 'episodes', None) or getattr(edge, 'episode_ids', None) or []
    if episodes and not isinstance(episodes, list):
        episodes = [str(episodes)]
    else:
        episodes = [str(e) for e in episodes]
    return MemoryEdge(
        uuid=str(uuid_) if uuid_ else "",
        name=getattr(edge, 'name', '') or "",
        fact=getattr(edge, 'fact', '') or "",
        source_node_uuid=getattr(edge, 'source_node_uuid', '') or "",
        target_node_uuid=getattr(edge, 'target_node_uuid', '') or "",
        attributes=dict(getattr(edge, 'attributes', None) or {}),
        created_at=str(getattr(edge, 'created_at', None)) if getattr(edge, 'created_at', None) else None,
        valid_at=str(getattr(edge, 'valid_at', None)) if getattr(edge, 'valid_at', None) else None,
        invalid_at=str(getattr(edge, 'invalid_at', None)) if getattr(edge, 'invalid_at', None) else None,
        expired_at=str(getattr(edge, 'expired_at', None)) if getattr(edge, 'expired_at', None) else None,
        episodes=episodes,
        fact_type=getattr(edge, 'fact_type', None) or getattr(edge, 'name', '') or "",
    )


class ZepBackend(MemoryBackend):
    """Zep Cloud 兜底实现。"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("MEMORY_BACKEND=zep 但 ZEP_API_KEY 未配置")
        self.client = Zep(api_key=self.api_key)
        logger.info("ZepBackend 初始化完成")

    # ----- 图谱生命周期 -----

    def create_graph(self, graph_id: str, name: str, description: str = "") -> str:
        self.client.graph.create(graph_id=graph_id, name=name, description=description)
        return graph_id

    def delete_graph(self, graph_id: str) -> None:
        self.client.graph.delete(graph_id=graph_id)

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        from pydantic import Field
        from zep_cloud.external_clients.ontology import EdgeModel, EntityModel, EntityText

        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')

        RESERVED = {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}

        def safe(n: str) -> str:
            return f"entity_{n}" if n.lower() in RESERVED else n

        entity_types: Dict[str, Any] = {}
        for ent in ontology.get("entity_types", []):
            nm = ent["name"]
            attrs: Dict[str, Any] = {"__doc__": ent.get("description", f"A {nm} entity.")}
            anns: Dict[str, Any] = {}
            for a in ent.get("attributes", []):
                an = safe(a["name"])
                attrs[an] = Field(description=a.get("description", an), default=None)
                anns[an] = Optional[EntityText]
            attrs["__annotations__"] = anns
            cls = type(nm, (EntityModel,), attrs)
            cls.__doc__ = attrs["__doc__"]
            entity_types[nm] = cls

        edge_defs: Dict[str, Any] = {}
        for ed in ontology.get("edge_types", []):
            nm = ed["name"]
            attrs = {"__doc__": ed.get("description", f"A {nm} relationship.")}
            anns = {}
            for a in ed.get("attributes", []):
                an = safe(a["name"])
                attrs[an] = Field(description=a.get("description", an), default=None)
                anns[an] = Optional[str]
            attrs["__annotations__"] = anns
            cls_name = ''.join(w.capitalize() for w in nm.split('_'))
            cls = type(cls_name, (EdgeModel,), attrs)
            cls.__doc__ = attrs["__doc__"]
            sts = []
            for st in ed.get("source_targets", []):
                sts.append(EntityEdgeSourceTarget(source=st.get("source", "Entity"), target=st.get("target", "Entity")))
            if sts:
                edge_defs[nm] = (cls, sts)

        if entity_types or edge_defs:
            self.client.graph.set_ontology(
                graph_ids=[graph_id],
                entities=entity_types or None,
                edges=edge_defs or None,
            )

    # ----- 写入 -----

    def add_episode(
        self,
        graph_id: str,
        data: str,
        episode_type: str = "text",
        name: Optional[str] = None,
    ) -> EpisodeStatus:
        resp = self.client.graph.add(graph_id=graph_id, type=episode_type, data=data)
        uuid_ = getattr(resp, 'uuid_', None) or getattr(resp, 'uuid', None) or ""
        return EpisodeStatus(uuid=str(uuid_), processed=False)

    def add_batch(self, graph_id: str, episodes: List[Dict[str, str]]) -> List[EpisodeStatus]:
        eps = [EpisodeData(data=e["data"], type=e.get("type", "text")) for e in episodes]
        batch = self.client.graph.add_batch(graph_id=graph_id, episodes=eps)
        out: List[EpisodeStatus] = []
        if batch and isinstance(batch, list):
            for ep in batch:
                u = getattr(ep, 'uuid_', None) or getattr(ep, 'uuid', None)
                if u:
                    out.append(EpisodeStatus(uuid=str(u), processed=False))
        return out

    def get_episode_processed(self, episode_uuid: str) -> bool:
        try:
            ep = self.client.graph.episode.get(uuid_=episode_uuid)
            return bool(getattr(ep, 'processed', False))
        except Exception:
            return False

    # ----- 读取 -----

    def get_all_nodes(self, graph_id: str, max_items: int = 2000) -> List[MemoryNode]:
        out: List[MemoryNode] = []
        cursor: Optional[str] = None
        page = 0
        while True:
            kw: Dict[str, Any] = {"limit": _DEFAULT_PAGE_SIZE}
            if cursor:
                kw["uuid_cursor"] = cursor
            page += 1
            batch = _retry(
                self.client.graph.node.get_by_graph_id,
                graph_id,
                op=f"zep nodes page {page} ({graph_id})",
                **kw,
            )
            if not batch:
                break
            out.extend(_node_from_zep(n) for n in batch)
            if len(out) >= max_items:
                out = out[:max_items]
                logger.warning(f"node count hit max_items={max_items} for {graph_id}")
                break
            if len(batch) < _DEFAULT_PAGE_SIZE:
                break
            cursor = getattr(batch[-1], 'uuid_', None) or getattr(batch[-1], 'uuid', None)
            if not cursor:
                break
        return out

    def get_all_edges(self, graph_id: str) -> List[MemoryEdge]:
        out: List[MemoryEdge] = []
        cursor: Optional[str] = None
        page = 0
        while True:
            kw: Dict[str, Any] = {"limit": _DEFAULT_PAGE_SIZE}
            if cursor:
                kw["uuid_cursor"] = cursor
            page += 1
            batch = _retry(
                self.client.graph.edge.get_by_graph_id,
                graph_id,
                op=f"zep edges page {page} ({graph_id})",
                **kw,
            )
            if not batch:
                break
            out.extend(_edge_from_zep(e) for e in batch)
            if len(batch) < _DEFAULT_PAGE_SIZE:
                break
            cursor = getattr(batch[-1], 'uuid_', None) or getattr(batch[-1], 'uuid', None)
            if not cursor:
                break
        return out

    def get_node(self, node_uuid: str) -> Optional[MemoryNode]:
        try:
            n = _retry(self.client.graph.node.get, uuid_=node_uuid, op=f"zep node.get {node_uuid[:8]}")
            return _node_from_zep(n) if n else None
        except Exception as e:
            logger.error(f"get_node failed: {e}")
            return None

    def get_entity_edges(self, node_uuid: str) -> List[MemoryEdge]:
        try:
            edges = _retry(
                self.client.graph.node.get_entity_edges,
                node_uuid=node_uuid,
                op=f"zep entity_edges {node_uuid[:8]}",
            )
            return [_edge_from_zep(e) for e in edges]
        except Exception as e:
            logger.warning(f"get_entity_edges failed for {node_uuid}: {e}")
            return []

    # ----- 搜索 -----

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> MemorySearchResult:
        result = _retry(
            self.client.graph.search,
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope=scope,
            reranker="cross_encoder",
            op=f"zep search ({graph_id})",
        )
        edges: List[MemoryEdge] = []
        nodes: List[MemoryNode] = []
        if hasattr(result, 'edges') and result.edges:
            edges = [_edge_from_zep(e) for e in result.edges]
        if hasattr(result, 'nodes') and result.nodes:
            nodes = [_node_from_zep(n) for n in result.nodes]
        return MemorySearchResult(edges=edges, nodes=nodes)
