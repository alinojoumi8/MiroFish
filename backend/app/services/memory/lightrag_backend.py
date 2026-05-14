"""
LightRAG + FalkorDB 记忆后端

写入路径：LightRAG.ainsert() — 每个 chunk 仅需 1 次 LLM 调用
         （Graphiti 需要 8-15 次；大幅减少 API 成本和延迟）
图存储  ：FalkorDB（MIT 许可，Rust 实现，内存约为 Neo4j 的 1/10）
向量存储：NanoVectorDB（LightRAG 内置 JSON 本地存储，无需额外服务）
读取路径：直接对 FalkorDB 执行 Cypher 查询
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...config import Config
from .backend import MemoryBackend
from .types import EpisodeStatus, MemoryEdge, MemoryNode, MemorySearchResult

logger = logging.getLogger("mirofish.lightrag_backend")

# LightRAG FalkorDB schema constants (from lightrag/kg/falkordb_impl.py)
_ENTITY_LABEL = "base"       # Cypher node label used by LightRAG
_RELATION_TYPE = "DIRECTED"  # Cypher relationship type used by LightRAG
_ENTITY_ID_KEY = "entity_id" # Node property that stores the entity name

# Generous timeout — LightRAG processes synchronously (no polling needed)
_TIMEOUT = 600  # seconds


# ---------------------------------------------------------------------------
# Async ↔ sync bridge
# ---------------------------------------------------------------------------

class _AsyncRunner:
    """
    Dedicated asyncio event-loop thread for bridging sync Flask ↔ async LightRAG.

    Same pattern as graphiti_backend._AsyncRunner.
    """

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="lightrag-async-runner",
        )
        self._thread.start()

    def run(self, coro):
        """Submit a coroutine and block until it completes (or times out)."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=_TIMEOUT)

    def stop(self):
        self._loop.call_soon_threadsafe(self._loop.stop)


# ---------------------------------------------------------------------------
# Module-level embedding model singleton (sentence-transformers)
# ---------------------------------------------------------------------------

_embed_model = None
_embed_dim: int = 384   # updated after model loads
_embed_lock = threading.Lock()


def _load_embed_model():
    """Lazy-load the embedding model (thread-safe singleton)."""
    global _embed_model, _embed_dim
    if _embed_model is not None:
        return _embed_model
    with _embed_lock:
        if _embed_model is not None:
            return _embed_model
        from sentence_transformers import SentenceTransformer

        model_name = Config.EMBEDDING_MODEL or "BAAI/bge-small-en-v1.5"
        logger.info(f"Loading embedding model: {model_name}")
        _embed_model = SentenceTransformer(model_name)
        # Detect actual output dimension
        sample = _embed_model.encode(["dim_probe"], normalize_embeddings=True)
        _embed_dim = sample.shape[1]
        logger.info(f"Embedding model loaded — dim={_embed_dim}")
        return _embed_model


def _build_embed_func():
    """Return a LightRAG-compatible async embedding function."""
    import numpy as np
    from lightrag.utils import EmbeddingFunc

    model = _load_embed_model()   # ensures _embed_dim is correct
    dim = _embed_dim

    async def _embed(texts: List[str]) -> np.ndarray:
        embeddings = model.encode(texts, normalize_embeddings=True)
        return np.array(embeddings, dtype=np.float32)

    return EmbeddingFunc(embedding_dim=dim, max_token_size=512, func=_embed)


# ---------------------------------------------------------------------------
# LLM function that wraps whichever provider is active in MiroFish
# ---------------------------------------------------------------------------

def _build_llm_func(ontology: Optional[Dict] = None):
    """
    Build an async LLM function compatible with LightRAG's expected signature.

    Reads the active provider at call-time (so runtime switches work without
    recreating the LightRAG instance).
    """
    import re
    from openai import AsyncOpenAI
    from ...utils import llm_providers

    async def _llm(
        prompt: str,
        system_prompt: Optional[str] = None,
        history_messages: list = [],
        **kwargs,
    ) -> str:
        api_key = llm_providers.get_active_api_key()
        base_url = llm_providers.get_active_base_url()
        model = llm_providers.get_active_model()
        extra_headers = llm_providers.get_active_extra_headers()

        # Augment system prompt with ontology hints (entity-type guidance)
        parts: List[str] = []
        if system_prompt:
            parts.append(system_prompt)
        if ontology:
            raw_types = ontology.get("entity_types", [])
            names = [
                t.get("name", "") if isinstance(t, dict) else str(t)
                for t in raw_types
            ]
            names = [n for n in names if n]
            if names:
                parts.append(
                    f"Focus on these entity types when extracting knowledge: "
                    f"{', '.join(names)}."
                )
        final_sys = "\n".join(parts) if parts else "You are a helpful assistant."

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=extra_headers,
        )

        messages = [{"role": "system", "content": final_sys}]
        messages.extend(history_messages)
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
        )

        text = response.choices[0].message.content or ""
        # Strip <think>…</think> reasoning blocks (MiniMax M2, Kimi K2)
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
        return text

    return _llm


# ---------------------------------------------------------------------------
# FalkorDB helpers
# ---------------------------------------------------------------------------

def _get_falkordb_graph(graph_id: str):
    """Return a FalkorDB graph handle for the given graph_id."""
    import falkordb

    host = getattr(Config, "FALKORDB_HOST", None) or "localhost"
    port = int(getattr(Config, "FALKORDB_PORT", None) or 6379)
    client = falkordb.FalkorDB(host=host, port=port)
    return client.select_graph(graph_id)


def _extract_entity_name(props: dict) -> str:
    """
    Extract the entity name from node properties.
    LightRAG stores it as 'entity_id'; older/custom schemas may use 'id' or 'name'.
    """
    for key in (_ENTITY_ID_KEY, "id", "name"):
        val = props.get(key)
        if val:
            return str(val)
    return ""


def _node_obj_to_memory_node(node_obj) -> Optional[MemoryNode]:
    """Convert a falkordb.Node object to a MemoryNode."""
    props: dict = node_obj.properties if hasattr(node_obj, "properties") else {}
    raw_labels: list = list(node_obj.labels) if hasattr(node_obj, "labels") else []

    name = _extract_entity_name(props)
    if not name:
        return None

    entity_type = props.get("entity_type", "")

    # Remove the internal LightRAG label ('base'); use entity_type instead
    display_labels = [l for l in raw_labels if l != _ENTITY_LABEL]
    if entity_type and entity_type not in display_labels:
        display_labels.insert(0, entity_type)

    return MemoryNode(
        uuid=name,           # entity name IS the stable identifier in LightRAG
        name=name,
        labels=display_labels,
        summary=props.get("description", ""),
        attributes={
            k: v
            for k, v in props.items()
            if k not in (_ENTITY_ID_KEY, "id", "name", "entity_type", "description")
        },
        created_at=props.get("created_at"),
    )


def _edge_obj_to_memory_edge(
    src_obj, rel_obj, dst_obj
) -> Optional[MemoryEdge]:
    """Convert falkordb Node + Relationship + Node objects to a MemoryEdge."""
    a_props: dict = src_obj.properties if hasattr(src_obj, "properties") else {}
    b_props: dict = dst_obj.properties if hasattr(dst_obj, "properties") else {}
    r_props: dict = rel_obj.properties if hasattr(rel_obj, "properties") else {}

    src_name = _extract_entity_name(a_props)
    dst_name = _extract_entity_name(b_props)
    if not src_name or not dst_name:
        return None

    # Relationship type (always DIRECTED in LightRAG)
    rel_type: str = (
        rel_obj.relation if hasattr(rel_obj, "relation") else _RELATION_TYPE
    )

    description = r_props.get("description", "")
    keywords_raw = r_props.get("keywords", "")
    # Use first keyword as a human-readable edge name
    edge_name = keywords_raw.split(",")[0].strip() if keywords_raw else rel_type

    return MemoryEdge(
        uuid=f"{src_name}::{rel_type}::{dst_name}",
        name=edge_name,
        fact=description,
        source_node_uuid=src_name,
        target_node_uuid=dst_name,
        fact_type=rel_type,
        attributes={
            k: v
            for k, v in r_props.items()
            if k not in ("description", "keywords")
        },
        created_at=r_props.get("created_at"),
    )


# ---------------------------------------------------------------------------
# LightRAGBackend
# ---------------------------------------------------------------------------

class LightRAGBackend(MemoryBackend):
    """
    LightRAG + FalkorDB memory backend.

    Key properties vs Graphiti:
    - ✓ 1 LLM call per chunk  (vs 8-15 for Graphiti)
    - ✓ FalkorDB: MIT, Rust, ~80 MB RAM  (vs Neo4j JVM ~512 MB)
    - ✓ NanoVectorDB: no extra vector service needed
    - ✗ No temporal edge invalidation (no valid_at / invalid_at)
    - ✗ get_node(uuid) not supported without graph_id context (returns None)
    """

    def __init__(self):
        self._runner = _AsyncRunner()

        # Keyed by graph_id → LightRAG instance
        self._rag_cache: Dict[str, Any] = {}
        # Keyed by graph_id → ontology dict
        self._ontology_cache: Dict[str, Dict] = {}
        self._cache_lock = threading.Lock()

        # Working directory for LightRAG's local NanoVectorDB and KV state
        lightrag_dir = getattr(Config, "LIGHTRAG_WORKING_DIR", None)
        self._working_dir: str = lightrag_dir or os.path.join(
            os.path.dirname(__file__), "../../../../uploads/lightrag"
        )
        os.makedirs(self._working_dir, exist_ok=True)

        # Eagerly warm up the embedding model (avoids cold-start on first build)
        try:
            _load_embed_model()
        except Exception as exc:
            logger.warning(f"Embedding model warmup failed (will retry on demand): {exc}")

        # Probe FalkorDB connectivity
        try:
            g = _get_falkordb_graph("_mirofish_ping_")
            g.query("RETURN 1")
            logger.info("FalkorDB connection OK")
        except Exception as exc:
            logger.error(
                f"FalkorDB connection probe failed: {exc}  "
                f"(check FALKORDB_HOST/FALKORDB_PORT and that the container is running)"
            )

    # ------------------------------------------------------------------
    # LightRAG instance management
    # ------------------------------------------------------------------

    async def _make_rag_async(self, graph_id: str):
        """Create and initialise a LightRAG instance for the given graph_id."""
        from lightrag import LightRAG

        graph_dir = os.path.join(self._working_dir, graph_id)
        os.makedirs(graph_dir, exist_ok=True)

        ontology = self._ontology_cache.get(graph_id)
        llm_func = _build_llm_func(ontology)
        embed_func = _build_embed_func()

        host = getattr(Config, "FALKORDB_HOST", None) or "localhost"
        port = int(getattr(Config, "FALKORDB_PORT", None) or 6379)

        rag = LightRAG(
            working_dir=graph_dir,
            llm_model_func=llm_func,
            embedding_func=embed_func,
            graph_storage="FalkorDBStorage",
            vector_storage="NanoVectorDBStorage",
            kv_storage="JsonKVStorage",
            addon_params={
                "graph_name": graph_id,
                "falkordb_url": f"redis://{host}:{port}",
            },
        )

        # LightRAG ≥ 1.4 requires explicit storage initialisation
        try:
            await rag.initialize_storages()
        except AttributeError:
            pass  # LightRAG < 1.4 initialises lazily

        return rag

    def _get_or_create_rag(self, graph_id: str):
        """Return a (possibly cached) LightRAG instance for graph_id."""
        # Fast path — no lock needed for pure read
        if graph_id in self._rag_cache:
            return self._rag_cache[graph_id]

        # Slow path — create and cache
        with self._cache_lock:
            if graph_id in self._rag_cache:
                return self._rag_cache[graph_id]
            rag = self._runner.run(self._make_rag_async(graph_id))
            self._rag_cache[graph_id] = rag
            return rag

    # ------------------------------------------------------------------
    # Graph lifecycle
    # ------------------------------------------------------------------

    def create_graph(self, graph_id: str, name: str, description: str = "") -> str:
        """
        Create graph working-directory and metadata file.
        The FalkorDB graph is created lazily on first insert.
        """
        graph_dir = os.path.join(self._working_dir, graph_id)
        os.makedirs(graph_dir, exist_ok=True)
        meta = {
            "graph_id": graph_id,
            "name": name,
            "description": description,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        with open(os.path.join(graph_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return graph_id

    def delete_graph(self, graph_id: str) -> None:
        """Delete FalkorDB graph and local working directory."""
        with self._cache_lock:
            self._rag_cache.pop(graph_id, None)
            self._ontology_cache.pop(graph_id, None)

        # Drop FalkorDB graph
        try:
            g = _get_falkordb_graph(graph_id)
            g.delete()
        except Exception as exc:
            logger.warning(f"FalkorDB delete_graph({graph_id}) failed: {exc}")

        # Remove local NanoVectorDB / KV files
        graph_dir = os.path.join(self._working_dir, graph_id)
        if os.path.exists(graph_dir):
            shutil.rmtree(graph_dir, ignore_errors=True)

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        """
        Cache ontology; the LLM function will inject entity-type hints
        into every extraction prompt.  Invalidates the cached RAG instance
        so the new ontology flows through immediately.
        """
        with self._cache_lock:
            self._ontology_cache[graph_id] = ontology
            self._rag_cache.pop(graph_id, None)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_episode(
        self,
        graph_id: str,
        data: str,
        episode_type: str = "text",
        name: Optional[str] = None,
    ) -> EpisodeStatus:
        """Insert a single text chunk into the knowledge graph."""
        ep_id = str(uuid.uuid4())

        async def _insert():
            rag = self._get_or_create_rag(graph_id)
            await rag.ainsert(data)

        self._runner.run(_insert())
        return EpisodeStatus(uuid=ep_id, processed=True)

    def add_batch(
        self,
        graph_id: str,
        episodes: List[Dict[str, str]],
    ) -> List[EpisodeStatus]:
        """
        Bulk-insert a batch of text chunks.

        LightRAG accepts a list and processes chunks in parallel via
        asyncio.gather internally — this is the key speed improvement over
        Graphiti which processed episodes sequentially.
        """
        texts = [ep["data"] for ep in episodes if ep.get("data")]
        ids = [str(uuid.uuid4()) for _ in episodes]

        if not texts:
            return [EpisodeStatus(uuid=uid, processed=True) for uid in ids]

        async def _bulk():
            rag = self._get_or_create_rag(graph_id)
            await rag.ainsert(texts)   # list → parallel processing

        self._runner.run(_bulk())
        return [EpisodeStatus(uuid=uid, processed=True) for uid in ids]

    def get_episode_processed(self, episode_uuid: str) -> bool:
        """LightRAG processes synchronously — always done by return time."""
        return True

    # ------------------------------------------------------------------
    # Read: nodes
    # ------------------------------------------------------------------

    def get_all_nodes(
        self, graph_id: str, max_items: int = 2000
    ) -> List[MemoryNode]:
        """Query all entity nodes from FalkorDB."""
        try:
            g = _get_falkordb_graph(graph_id)
            result = g.query(
                f"MATCH (n:{_ENTITY_LABEL}) RETURN n LIMIT {max_items}"
            )
            nodes: List[MemoryNode] = []
            seen: set = set()
            for record in result.result_set:
                node_obj = record[0]
                mn = _node_obj_to_memory_node(node_obj)
                if mn and mn.name not in seen:
                    seen.add(mn.name)
                    nodes.append(mn)
            logger.debug(f"get_all_nodes({graph_id}): {len(nodes)} nodes")
            return nodes
        except Exception as exc:
            logger.warning(f"get_all_nodes({graph_id}) failed: {exc}")
            return []

    def get_node(self, node_uuid: str) -> Optional[MemoryNode]:
        """
        In LightRAG the 'uuid' is the entity name.  Without knowing which
        graph_id to query we cannot look it up.  Callers (zep_tools.py,
        zep_entity_reader.py) all handle None gracefully.
        """
        return None

    # ------------------------------------------------------------------
    # Read: edges
    # ------------------------------------------------------------------

    def get_all_edges(self, graph_id: str) -> List[MemoryEdge]:
        """Query all relationships from FalkorDB."""
        try:
            g = _get_falkordb_graph(graph_id)
            result = g.query(
                f"MATCH (a:{_ENTITY_LABEL})-[r:{_RELATION_TYPE}]->(b:{_ENTITY_LABEL}) "
                f"RETURN a, r, b LIMIT 5000"
            )
            edges: List[MemoryEdge] = []
            for record in result.result_set:
                me = _edge_obj_to_memory_edge(record[0], record[1], record[2])
                if me:
                    edges.append(me)
            logger.debug(f"get_all_edges({graph_id}): {len(edges)} edges")
            return edges
        except Exception as exc:
            logger.warning(f"get_all_edges({graph_id}) failed: {exc}")
            return []

    def get_entity_edges(self, node_uuid: str) -> List[MemoryEdge]:
        """
        Same graph_id limitation as get_node — returns empty list.
        The callers that matter (ZepToolsService.get_node_edges,
        ZepEntityReader.filter_defined_entities) both use get_all_edges+filter
        locally and do not call this method on the hot path.
        """
        return []

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> MemorySearchResult:
        """
        Keyword-based search directly in FalkorDB (no LLM call needed).

        Falls back to empty result on any error; ZepToolsService already has
        its own local keyword-fallback (_local_search).
        """
        try:
            g = _get_falkordb_graph(graph_id)
            edges: List[MemoryEdge] = []
            nodes: List[MemoryNode] = []

            if scope in ("edges", "both"):
                result = g.query(
                    f"MATCH (a:{_ENTITY_LABEL})-[r:{_RELATION_TYPE}]->(b:{_ENTITY_LABEL}) "
                    f"WHERE toLower(r.description) CONTAINS toLower($q) "
                    f"   OR toLower(r.keywords) CONTAINS toLower($q) "
                    f"RETURN a, r, b LIMIT {limit}",
                    params={"q": query},
                )
                for record in result.result_set:
                    me = _edge_obj_to_memory_edge(record[0], record[1], record[2])
                    if me:
                        edges.append(me)

            if scope in ("nodes", "both"):
                result = g.query(
                    f"MATCH (n:{_ENTITY_LABEL}) "
                    f"WHERE toLower(n.description) CONTAINS toLower($q) "
                    f"   OR toLower(n.{_ENTITY_ID_KEY}) CONTAINS toLower($q) "
                    f"RETURN n LIMIT {limit}",
                    params={"q": query},
                )
                for record in result.result_set:
                    mn = _node_obj_to_memory_node(record[0])
                    if mn:
                        nodes.append(mn)

            return MemorySearchResult(edges=edges, nodes=nodes)

        except Exception as exc:
            logger.warning(
                f"search({graph_id}, '{query[:40]}…') failed: {exc}"
            )
            return MemorySearchResult(edges=[], nodes=[])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Shut down the async runner thread."""
        self._runner.stop()
