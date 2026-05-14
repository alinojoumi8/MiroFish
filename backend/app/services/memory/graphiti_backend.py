"""
Graphiti + 本地 Neo4j 适配器（默认后端）。

Graphiti 文档: https://help.getzep.com/graphiti
Neo4j 驱动:    bolt://localhost:7687（docker-compose 自带）

设计要点：
- 实体抽取调用 LLM —— 复用 MiroFish 的 LLMClient（即用户当前激活的 provider）。
- 嵌入用本地 sentence-transformers（CPU-friendly），避免依赖云端 embedding 服务。
- 重排序用本地 BGE cross-encoder。
- 异步 API 通过 asyncio.run() 包装为同步调用，匹配既有调用方式。
- Zep 概念到 Graphiti 的映射：
    graph_id           → group_id
    create_graph       → no-op（group_id 是隐式分区）
    add_episode        → Graphiti.add_episode（同步）
    set_ontology       → 暂记录到本地，供 add_episode 传 entity_types 参数
    get_episode_processed → 总是 True
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...config import Config
from ...utils.logger import get_logger
from .backend import MemoryBackend
from .types import EpisodeStatus, MemoryEdge, MemoryNode, MemorySearchResult

logger = get_logger('mirofish.memory.graphiti')


# ===== 同步包装：在专用线程的 event loop 上跑 Graphiti 的 async API =====

class _AsyncRunner:
    """单线程 event loop，序列化 Graphiti 的 async 调用。"""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            name="graphiti-asyncio",
            daemon=True,
        )
        self._thread.start()

    _TIMEOUT = 600  # seconds; add_episode_bulk() over a large batch can take several minutes

    def run(self, coro):
        import concurrent.futures
        try:
            return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=self._TIMEOUT)
        except concurrent.futures.TimeoutError:
            raise RuntimeError(
                f"Graphiti operation timed out after {self._TIMEOUT}s "
                "(check Neo4j connectivity and LLM response time)"
            )

    def shutdown(self) -> None:
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            self._loop.close()


# ===== Embedder：本地 sentence-transformers =====

def _build_local_embedder():
    """返回 graphiti_core.embedder.EmbedderClient 接口兼容对象（本地 CPU 推理）。"""
    from sentence_transformers import SentenceTransformer
    from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig  # type: ignore

    class _STEmbedder(EmbedderClient):
        def __init__(self) -> None:
            self._model = SentenceTransformer(Config.EMBEDDING_MODEL)
            # 推断维度
            self._dim = self._model.get_sentence_embedding_dimension() or 384
            self.config = EmbedderConfig(embedding_dim=self._dim)

        async def create(self, input_data):  # type: ignore[override]
            if isinstance(input_data, list):
                if not input_data:
                    return []
                vecs = self._model.encode(input_data, normalize_embeddings=True)
                return [v.tolist() for v in vecs]
            vec = self._model.encode([input_data], normalize_embeddings=True)[0]
            return vec.tolist()

        async def create_batch(self, input_data_list):  # type: ignore[override]
            if not input_data_list:
                return []
            vecs = self._model.encode(input_data_list, normalize_embeddings=True)
            return [v.tolist() for v in vecs]

    return _STEmbedder()


# ===== Embedder：OpenRouter API（无需本地模型文件）=====

def _build_api_embedder():
    """
    OpenRouter / 任意 OpenAI 兼容 embeddings 端点。
    优点：跳过本地模型下载（~2GB），降低内存占用。
    配置：OPENROUTER_API_KEY、OPENROUTER_EMBEDDING_MODEL、OPENROUTER_EMBEDDING_DIM。
    """
    from openai import AsyncOpenAI  # type: ignore
    from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig  # type: ignore

    api_key = Config.OPENROUTER_API_KEY
    model   = Config.OPENROUTER_EMBEDDING_MODEL
    dim     = Config.OPENROUTER_EMBEDDING_DIM

    if not api_key:
        raise RuntimeError(
            "EMBEDDING_PROVIDER=openrouter but OPENROUTER_API_KEY is not set. "
            "Add it to your .env file."
        )

    _client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://mirofish.local",
            "X-Title": "MiroFish",
        },
    )

    class _APIEmbedder(EmbedderClient):
        def __init__(self) -> None:
            self.config = EmbedderConfig(embedding_dim=dim)

        async def _embed_texts(self, texts: list) -> list:
            resp = await _client.embeddings.create(model=model, input=texts)
            return [item.embedding for item in resp.data]

        async def create(self, input_data):  # type: ignore[override]
            if isinstance(input_data, list):
                if not input_data:
                    return []
                return await self._embed_texts(input_data)
            result = await self._embed_texts([input_data])
            return result[0]

        async def create_batch(self, input_data_list):  # type: ignore[override]
            if not input_data_list:
                return []
            return await self._embed_texts(input_data_list)

    logger.info(
        f"Using OpenRouter embedder: model={model}, dim={dim}"
    )
    return _APIEmbedder()


# ===== Cross-Encoder：本地 BGE reranker =====

def _build_local_reranker():
    from sentence_transformers import CrossEncoder
    from graphiti_core.cross_encoder.client import CrossEncoderClient  # type: ignore

    class _BGEReranker(CrossEncoderClient):
        def __init__(self) -> None:
            self._model = CrossEncoder(Config.RERANKER_MODEL)

        async def rank(self, query: str, passages: List[str]) -> List[tuple]:  # type: ignore[override]
            if not passages:
                return []
            pairs = [(query, p) for p in passages]
            scores = self._model.predict(pairs)
            # 返回 (passage, score) 倒序
            ranked = sorted(zip(passages, scores.tolist()), key=lambda x: x[1], reverse=True)
            return ranked

    return _BGEReranker()


# ===== LLM client：包装 MiroFish 的 LLMClient 为 Graphiti 接口 =====

def _build_graphiti_llm():
    """
    Graphiti 期待 graphiti_core.llm_client.LLMClient 接口。

    为什么不用默认的 OpenAIClient？
      OpenAIClient 走 `beta.chat.completions.parse()`（OpenAI 严格 structured-output），
      要求响应是纯 JSON，对非 OpenAI 兼容端点（MiniMax M2 / Kimi K2.6 等）会炸。
      改用 OpenAIGenericClient：plain chat completions + JSON mode，更兼容。

    为什么还要再 subclass？
      MiniMax M2 / Kimi K2.6 等会在 JSON 前后包 `<think>...</think>` 推理段或 markdown
      代码栅栏 (```json ... ```)。Generic 客户端直接 json.loads() 会抛错。
      下面的 _ThinkStrippingClient 在 json.loads 之前把这些噪声清掉。
    """
    import json
    import re

    from graphiti_core.llm_client import LLMConfig  # type: ignore
    from graphiti_core.llm_client.openai_generic_client import (  # type: ignore
        OpenAIGenericClient,
    )

    from ...utils import llm_providers

    _THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
    _FENCE_OPEN_RE = re.compile(r"^\s*```(?:json)?\s*\n?", re.IGNORECASE)
    _FENCE_CLOSE_RE = re.compile(r"\n?```\s*$")

    def _clean_json_text(raw: str) -> str:
        if not raw:
            return raw
        s = _THINK_RE.sub("", raw).strip()
        s = _FENCE_OPEN_RE.sub("", s)
        s = _FENCE_CLOSE_RE.sub("", s)
        return s.strip()

    def _schema_to_example(schema: dict, defs: dict | None = None) -> Any:
        """Convert a Pydantic JSON schema to a simple concrete example value.

        MiniMax-M2 and Kimi echo back the raw schema when given it as a format
        spec. A concrete example value teaches them what shape to produce.
        """
        if defs is None:
            defs = schema.get("$defs", {})
        if "$ref" in schema:
            ref_name = schema["$ref"].split("/")[-1]
            return _schema_to_example(defs.get(ref_name, {}), defs)
        typ = schema.get("type")
        if typ == "object":
            props = schema.get("properties", {})
            required = set(schema.get("required", list(props.keys())))
            return {k: _schema_to_example(v, defs) for k, v in props.items() if k in required}
        if typ == "array":
            items = schema.get("items", {})
            return [_schema_to_example(items, defs)]
        if typ == "string":
            desc = schema.get("description", "")
            return (desc[:30] if desc else "example text")
        if typ == "integer":
            return 0
        if typ == "number":
            return 0.0
        if typ == "boolean":
            return True
        if "anyOf" in schema:
            for opt in schema["anyOf"]:
                if opt.get("type") != "null":
                    return _schema_to_example(opt, defs)
        return None

    class _ThinkStrippingClient(OpenAIGenericClient):
        """OpenAIGenericClient + 输出清洗（剥离 <think> / markdown fence）。

        Two overrides:
        1. generate_response: replaces the raw Pydantic JSON schema instruction
           with a concrete example JSON, because MiniMax-M2 / Kimi echo the
           schema back verbatim instead of filling it with data.
        2. _generate_response: strips <think> tags and markdown fences from the
           model output before JSON-parsing, and uses raw_decode to tolerate
           trailing content after the first valid JSON object.
        """

        async def generate_response(  # type: ignore[override]
            self,
            messages,
            response_model=None,
            max_tokens=None,
            model_size=None,
        ):
            from graphiti_core.llm_client.client import MULTILINGUAL_EXTRACTION_RESPONSES  # type: ignore
            from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, ModelSize  # type: ignore
            from graphiti_core.prompts.models import Message as _Msg  # type: ignore

            if max_tokens is None:
                max_tokens = self.max_tokens
            if model_size is None:
                model_size = ModelSize.medium

            if response_model is not None:
                # Build a concrete example rather than the raw Pydantic schema.
                # The raw schema (full $defs / $ref / properties tree) confuses
                # MiniMax-M2 and Kimi: they echo the schema itself as their
                # "answer" instead of populating it with real data.
                example = _schema_to_example(response_model.model_json_schema())
                example_json = json.dumps(example, ensure_ascii=False)
                messages[-1].content += (
                    f"\n\nRespond with a JSON object in the following format:\n\n{example_json}"
                )

            messages[0].content += MULTILINGUAL_EXTRACTION_RESPONSES

            retry_count = 0
            last_error: Exception | None = None
            while retry_count <= self.MAX_RETRIES:
                try:
                    return await self._generate_response(
                        messages, response_model, max_tokens, model_size
                    )
                except Exception as e:
                    last_error = e
                    if retry_count >= self.MAX_RETRIES:
                        logger.error(
                            "Max retries (%d) exceeded. Last error: %s", self.MAX_RETRIES, e
                        )
                        raise
                    retry_count += 1
                    error_ctx = _Msg(
                        role="user",
                        content=(
                            f"The previous response was invalid. "
                            f"Error: {e.__class__.__name__}: {e}. "
                            "Please try again with a valid JSON response."
                        ),
                    )
                    messages.append(error_ctx)
                    logger.warning(
                        "Retrying after error (attempt %d/%d): %s",
                        retry_count, self.MAX_RETRIES, e,
                    )
            raise last_error or Exception("Max retries exceeded")

        async def _generate_response(self, messages, response_model=None, max_tokens=None, model_size=None):  # type: ignore[override]
            from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, ModelSize  # type: ignore
            from openai.types.chat import ChatCompletionMessageParam  # type: ignore

            if max_tokens is None:
                max_tokens = DEFAULT_MAX_TOKENS
            if model_size is None:
                model_size = ModelSize.medium

            openai_messages: list[ChatCompletionMessageParam] = []
            for m in messages:
                m.content = self._clean_input(m.content)
                if m.role == "user":
                    openai_messages.append({"role": "user", "content": m.content})
                elif m.role == "system":
                    openai_messages.append({"role": "system", "content": m.content})

            resp = await self.client.chat.completions.create(
                model=self.model or "gpt-4o-mini",
                messages=openai_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            cleaned = _clean_json_text(raw)
            try:
                obj, _ = json.JSONDecoder().raw_decode(cleaned)
                return obj
            except json.JSONDecodeError:
                # fallback: extract first {...} block
                start = cleaned.find("{")
                end = cleaned.rfind("}")
                if start != -1 and end != -1 and end > start:
                    return json.loads(cleaned[start : end + 1])
                logger.error(
                    "Graphiti LLM 返回的 JSON 无效（清洗后仍失败）。raw[:300]=%r",
                    raw[:300],
                )
                raise

    profile = llm_providers.get_active_provider()
    cfg = LLMConfig(
        api_key=llm_providers.get_active_api_key(),
        base_url=llm_providers.get_active_base_url(),
        model=llm_providers.get_active_model(),
        small_model=llm_providers.get_active_model(),
    )

    # 部分 provider（Kimi For Coding）需要自定义 HTTP header（如 User-Agent）才放行
    extra_headers = dict(profile.extra_headers)
    client = None
    if extra_headers:
        from openai import AsyncOpenAI  # type: ignore
        client = AsyncOpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            default_headers=extra_headers,
        )

    return _ThinkStrippingClient(config=cfg, client=client)


# ===== Backend 实现 =====

class GraphitiBackend(MemoryBackend):
    """Graphiti + Neo4j 实现。"""

    def __init__(self) -> None:
        self._runner = _AsyncRunner()
        self._ontology_cache: Dict[str, Dict[str, Any]] = {}

        # 延迟导入，避免在测试环境无依赖时报错
        from graphiti_core import Graphiti  # type: ignore

        if Config.EMBEDDING_PROVIDER == 'openrouter':
            embedder = _build_api_embedder()
        else:
            embedder = _build_local_embedder()
        reranker = _build_local_reranker()
        llm = _build_graphiti_llm()

        self._graphiti = Graphiti(
            uri=Config.NEO4J_URI,
            user=Config.NEO4J_USER,
            password=Config.NEO4J_PASSWORD,
            llm_client=llm,
            embedder=embedder,
            cross_encoder=reranker,
        )

        # 一次性建索引（幂等）
        try:
            self._runner.run(self._graphiti.build_indices_and_constraints())
        except Exception as e:
            logger.error(f"Neo4j 索引初始化失败（请确认 Neo4j 已启动并凭据正确）: {e}")
            raise
        logger.info(f"GraphitiBackend 初始化完成（Neo4j: {Config.NEO4J_URI}）")

    # ----- 图谱生命周期 -----

    def create_graph(self, graph_id: str, name: str, description: str = "") -> str:
        # Graphiti 中 graph_id == group_id，是隐式概念，无需创建
        logger.info(f"create_graph (no-op for graphiti): {graph_id}")
        return graph_id

    def delete_graph(self, graph_id: str) -> None:
        # 通过 driver 跑 Cypher 删除该 group_id 下所有节点和边
        async def _delete():
            driver = self._graphiti.driver
            async with driver.session() as session:
                await session.run(
                    "MATCH (n {group_id: $gid}) DETACH DELETE n",
                    gid=graph_id,
                )
        self._runner.run(_delete())

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]) -> None:
        # Graphiti 在 add_episode 时通过 entity_types 参数应用本体。
        # 这里缓存，add_episode 时取出。完整 Pydantic 类生成在 set_ontology() 中懒构建。
        self._ontology_cache[graph_id] = ontology
        logger.info(f"ontology cached for graph={graph_id} (entities={len(ontology.get('entity_types', []))})")

    # ----- 写入 -----

    def add_episode(
        self,
        graph_id: str,
        data: str,
        episode_type: str = "text",
        name: Optional[str] = None,
    ) -> EpisodeStatus:
        from graphiti_core.nodes import EpisodeType  # type: ignore

        ep_type_map = {
            "text": EpisodeType.text,
            "message": EpisodeType.message,
            "json": EpisodeType.json,
        }
        ep_type = ep_type_map.get(episode_type, EpisodeType.text)

        async def _add():
            result = await self._graphiti.add_episode(
                name=name or f"ep-{datetime.now(tz=timezone.utc).isoformat()}",
                episode_body=data,
                source=ep_type,
                source_description="mirofish",
                reference_time=datetime.now(tz=timezone.utc),
                group_id=graph_id,
            )
            return result

        result = self._runner.run(_add())
        ep_uuid = getattr(getattr(result, 'episode', None), 'uuid', None) or ""
        return EpisodeStatus(uuid=str(ep_uuid), processed=True)

    def add_batch(self, graph_id: str, episodes: List[Dict[str, str]]) -> List[EpisodeStatus]:
        """
        Bulk-add a batch of episodes using Graphiti's add_episode_bulk().

        add_episode_bulk() parallelises node/edge extraction and embedding across
        all episodes in the batch via asyncio.gather internally, which is 2-4x
        faster than the previous sequential add_episode() loop.

        Trade-off vs sequential add_episode():
        - No temporal edge invalidation (valid_at / invalid_at updates skipped)
        - Node deduplication uses embedding similarity rather than LLM; may be
          slightly less precise for ambiguous entity names
        Both trade-offs are acceptable for static document ingestion.
        """
        from graphiti_core.utils.bulk_utils import RawEpisode  # type: ignore
        from graphiti_core.nodes import EpisodeType  # type: ignore

        ep_type_map = {
            "text": EpisodeType.text,
            "message": EpisodeType.message,
            "json": EpisodeType.json,
        }

        raw_episodes = [
            RawEpisode(
                name=f"ep-{i}-{datetime.now(tz=timezone.utc).isoformat()}",
                content=ep["data"],
                source=ep_type_map.get(ep.get("type", "text"), EpisodeType.text),
                source_description="mirofish",
                reference_time=datetime.now(tz=timezone.utc),
            )
            for i, ep in enumerate(episodes)
        ]

        async def _bulk_add():
            await self._graphiti.add_episode_bulk(raw_episodes, group_id=graph_id)

        self._runner.run(_bulk_add())

        # add_episode_bulk doesn't return per-episode UUIDs; return placeholders
        return [EpisodeStatus(uuid="", processed=True) for _ in episodes]

    def get_episode_processed(self, episode_uuid: str) -> bool:
        # Graphiti 是同步处理，episode 返回时就已经入图
        return True

    # ----- 读取（Cypher 直查 Neo4j） -----

    def get_all_nodes(self, graph_id: str, max_items: int = 2000) -> List[MemoryNode]:
        async def _q():
            driver = self._graphiti.driver
            async with driver.session() as session:
                # Graphiti 实体节点标签是 Entity，group_id 区分图谱
                result = await session.run(
                    """
                    MATCH (n:Entity {group_id: $gid})
                    RETURN n
                    LIMIT $limit
                    """,
                    gid=graph_id,
                    limit=max_items,
                )
                rows = [r async for r in result]
                return rows

        rows = self._runner.run(_q())
        out: List[MemoryNode] = []
        for row in rows:
            n = row["n"]
            props = dict(n)
            labels = list(getattr(n, "labels", None) or [])
            out.append(MemoryNode(
                uuid=str(props.get("uuid") or props.get("id") or ""),
                name=str(props.get("name", "") or ""),
                labels=labels,
                summary=str(props.get("summary", "") or ""),
                attributes={k: v for k, v in props.items()
                           if k not in {"uuid", "name", "summary", "group_id", "name_embedding", "created_at"}},
                created_at=str(props["created_at"]) if props.get("created_at") else None,
            ))
        return out

    def get_all_edges(self, graph_id: str) -> List[MemoryEdge]:
        async def _q():
            driver = self._graphiti.driver
            async with driver.session() as session:
                result = await session.run(
                    """
                    MATCH (s:Entity {group_id: $gid})-[r:RELATES_TO]->(t:Entity {group_id: $gid})
                    RETURN r, s.uuid AS sid, t.uuid AS tid
                    """,
                    gid=graph_id,
                )
                rows = [r async for r in result]
                return rows

        rows = self._runner.run(_q())
        out: List[MemoryEdge] = []
        for row in rows:
            r = row["r"]
            props = dict(r)
            episodes = props.get("episodes") or []
            if episodes and not isinstance(episodes, list):
                episodes = [str(episodes)]
            else:
                episodes = [str(e) for e in episodes]
            out.append(MemoryEdge(
                uuid=str(props.get("uuid") or ""),
                name=str(props.get("name", "") or ""),
                fact=str(props.get("fact", "") or ""),
                source_node_uuid=str(row.get("sid") or ""),
                target_node_uuid=str(row.get("tid") or ""),
                attributes={k: v for k, v in props.items()
                           if k not in {"uuid", "name", "fact", "valid_at", "invalid_at",
                                       "expired_at", "created_at", "episodes", "fact_embedding"}},
                created_at=str(props["created_at"]) if props.get("created_at") else None,
                valid_at=str(props["valid_at"]) if props.get("valid_at") else None,
                invalid_at=str(props["invalid_at"]) if props.get("invalid_at") else None,
                expired_at=str(props["expired_at"]) if props.get("expired_at") else None,
                episodes=episodes,
                fact_type=str(props.get("fact_type") or props.get("name") or ""),
            ))
        return out

    def get_node(self, node_uuid: str) -> Optional[MemoryNode]:
        async def _q():
            driver = self._graphiti.driver
            async with driver.session() as session:
                result = await session.run(
                    "MATCH (n:Entity {uuid: $uid}) RETURN n LIMIT 1",
                    uid=node_uuid,
                )
                row = await result.single()
                return row

        row = self._runner.run(_q())
        if not row:
            return None
        n = row["n"]
        props = dict(n)
        return MemoryNode(
            uuid=str(props.get("uuid") or ""),
            name=str(props.get("name", "") or ""),
            labels=list(getattr(n, "labels", None) or []),
            summary=str(props.get("summary", "") or ""),
            attributes={k: v for k, v in props.items()
                       if k not in {"uuid", "name", "summary", "group_id", "name_embedding", "created_at"}},
            created_at=str(props["created_at"]) if props.get("created_at") else None,
        )

    def get_entity_edges(self, node_uuid: str) -> List[MemoryEdge]:
        async def _q():
            driver = self._graphiti.driver
            async with driver.session() as session:
                result = await session.run(
                    """
                    MATCH (n:Entity {uuid: $uid})-[r:RELATES_TO]-(m:Entity)
                    RETURN r,
                           startNode(r).uuid AS sid,
                           endNode(r).uuid AS tid
                    """,
                    uid=node_uuid,
                )
                rows = [r async for r in result]
                return rows

        rows = self._runner.run(_q())
        out: List[MemoryEdge] = []
        for row in rows:
            r = row["r"]
            props = dict(r)
            out.append(MemoryEdge(
                uuid=str(props.get("uuid") or ""),
                name=str(props.get("name", "") or ""),
                fact=str(props.get("fact", "") or ""),
                source_node_uuid=str(row.get("sid") or ""),
                target_node_uuid=str(row.get("tid") or ""),
                attributes={k: v for k, v in props.items()
                           if k not in {"uuid", "name", "fact"}},
                created_at=str(props["created_at"]) if props.get("created_at") else None,
                valid_at=str(props["valid_at"]) if props.get("valid_at") else None,
                invalid_at=str(props["invalid_at"]) if props.get("invalid_at") else None,
                expired_at=str(props["expired_at"]) if props.get("expired_at") else None,
            ))
        return out

    # ----- 搜索 -----

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> MemorySearchResult:
        async def _s():
            return await self._graphiti.search(
                query=query,
                group_ids=[graph_id],
                num_results=limit,
            )

        try:
            results = self._runner.run(_s())
        except Exception as e:
            logger.warning(f"graphiti search 失败，回退到 Cypher 关键词匹配: {e}")
            return self._fallback_search(graph_id, query, limit, scope)

        edges: List[MemoryEdge] = []
        nodes: List[MemoryNode] = []
        for r in results or []:
            # Graphiti 返回 EntityEdge 对象
            if hasattr(r, 'fact'):
                edges.append(MemoryEdge(
                    uuid=str(getattr(r, 'uuid', '') or ''),
                    name=str(getattr(r, 'name', '') or ''),
                    fact=str(getattr(r, 'fact', '') or ''),
                    source_node_uuid=str(getattr(r, 'source_node_uuid', '') or ''),
                    target_node_uuid=str(getattr(r, 'target_node_uuid', '') or ''),
                    created_at=str(getattr(r, 'created_at', None)) if getattr(r, 'created_at', None) else None,
                    valid_at=str(getattr(r, 'valid_at', None)) if getattr(r, 'valid_at', None) else None,
                    invalid_at=str(getattr(r, 'invalid_at', None)) if getattr(r, 'invalid_at', None) else None,
                    expired_at=str(getattr(r, 'expired_at', None)) if getattr(r, 'expired_at', None) else None,
                ))
            elif hasattr(r, 'summary'):
                nodes.append(MemoryNode(
                    uuid=str(getattr(r, 'uuid', '') or ''),
                    name=str(getattr(r, 'name', '') or ''),
                    labels=list(getattr(r, 'labels', None) or []),
                    summary=str(getattr(r, 'summary', '') or ''),
                ))
        return MemorySearchResult(edges=edges, nodes=nodes)

    def _fallback_search(self, graph_id: str, query: str, limit: int, scope: str) -> MemorySearchResult:
        """Cypher CONTAINS 关键词降级。"""
        async def _q():
            driver = self._graphiti.driver
            async with driver.session() as session:
                cy = """
                MATCH (s:Entity {group_id: $gid})-[r:RELATES_TO]->(t:Entity {group_id: $gid})
                WHERE toLower(r.fact) CONTAINS toLower($q)
                   OR toLower(r.name) CONTAINS toLower($q)
                RETURN r, s.uuid AS sid, t.uuid AS tid
                LIMIT $limit
                """
                result = await session.run(cy, gid=graph_id, q=query, limit=limit)
                rows = [r async for r in result]
                return rows
        rows = self._runner.run(_q())
        edges: List[MemoryEdge] = []
        for row in rows:
            r = row["r"]
            p = dict(r)
            edges.append(MemoryEdge(
                uuid=str(p.get("uuid") or ""),
                name=str(p.get("name", "") or ""),
                fact=str(p.get("fact", "") or ""),
                source_node_uuid=str(row.get("sid") or ""),
                target_node_uuid=str(row.get("tid") or ""),
            ))
        return MemorySearchResult(edges=edges, nodes=[])

    def close(self) -> None:
        try:
            async def _close():
                await self._graphiti.close()
            self._runner.run(_close())
        finally:
            self._runner.shutdown()
