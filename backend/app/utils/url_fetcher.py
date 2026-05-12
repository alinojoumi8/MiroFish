"""
URL 内容抓取 —— 通过 Jina Reader (r.jina.ai) 把任意网页转为干净 Markdown。

Jina Reader 是 Jina AI 的免费 hosted 服务，对任意 URL 返回 LLM-ready 的纯文本。
- 接口: GET https://r.jina.ai/{target_url}
- 返回: text/plain (Markdown 格式)
- 鉴权: 可选。无 token 已够日常使用；如需更高配额，设置 JINA_API_KEY。
- 文档: https://jina.ai/reader/

未来可以平滑切换到自托管 Firecrawl —— 只需替换本模块中的 fetch_url 实现。
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

import requests

from .logger import get_logger

logger = get_logger('mirofish.url_fetcher')

_JINA_READER_BASE = "https://r.jina.ai/"
_DEFAULT_TIMEOUT = 45  # Jina 抓取 JS-heavy 页面可能慢，给宽裕一些
_MAX_RETRIES = 2
_RETRY_BACKOFF = 2.0


@dataclass
class FetchedDocument:
    """已抓取的网页内容，作为 OntologyGenerator 的输入。"""
    url: str
    title: str
    text: str

    @property
    def display_name(self) -> str:
        """用于项目文件清单展示的友好名称。"""
        if self.title:
            # 截断过长标题
            short = self.title.strip()
            if len(short) > 80:
                short = short[:77] + "..."
            return short
        # 退化为 host + path
        try:
            p = urlparse(self.url)
            return f"{p.netloc}{p.path[:50]}"
        except Exception:
            return self.url[:100]


def _is_valid_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def _extract_title(markdown: str) -> str:
    """Jina Reader 在返回的 markdown 顶部用 `Title: ...` 行给出标题。如果没有则空字符串。"""
    if not markdown:
        return ""
    for line in markdown.splitlines()[:6]:
        m = re.match(r"^\s*Title:\s*(.+)$", line)
        if m:
            return m.group(1).strip()
        # 部分页面是 H1 直接开头
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip()
    return ""


def _strip_jina_header(markdown: str) -> str:
    """Jina 在正文前可能有 'Title:' / 'URL Source:' / 'Markdown Content:' 等元数据行，去掉。"""
    lines = markdown.splitlines()
    skip_prefixes = (
        "title:", "url source:", "markdown content:", "published time:", "warning:",
    )
    cleaned: list[str] = []
    body_started = False
    for line in lines:
        low = line.strip().lower()
        if not body_started:
            # 跳过元数据行 / 空行直到第一个非元数据内容
            if not low:
                continue
            if any(low.startswith(p) for p in skip_prefixes):
                continue
            body_started = True
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def fetch_url(url: str, timeout: int = _DEFAULT_TIMEOUT) -> FetchedDocument:
    """
    通过 Jina Reader 抓取单个 URL 并返回干净 Markdown。

    Raises:
        ValueError: URL 格式无效
        RuntimeError: 抓取失败（多次重试后仍失败 / 内容空）
    """
    if not _is_valid_url(url):
        raise ValueError(f"非法 URL（必须是 http/https）: {url}")

    api_key = os.environ.get("JINA_API_KEY", "").strip()
    headers = {
        "Accept": "text/plain, text/markdown, */*",
        "User-Agent": "MiroFish/1.0 (+https://github.com/666ghj/MiroFish)",
        # X-Return-Format: markdown 让 Jina 返回纯 markdown，而非渲染后的 HTML
        "X-Return-Format": "markdown",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    target = _JINA_READER_BASE + url
    delay = _RETRY_BACKOFF
    last_err: Optional[BaseException] = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            logger.info(f"Jina Reader fetching: {url} (attempt {attempt + 1})")
            resp = requests.get(target, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                snippet = (resp.text or "")[:300]
                raise RuntimeError(
                    f"Jina Reader HTTP {resp.status_code} for {url}: {snippet}"
                )
            raw = resp.text or ""
            title = _extract_title(raw)
            body = _strip_jina_header(raw)
            if not body or len(body) < 30:
                raise RuntimeError(
                    f"Jina Reader returned empty/very short content for {url} "
                    f"(len={len(body)})"
                )
            logger.info(
                f"Jina Reader OK: {url}  title={title!r}  body_len={len(body)}"
            )
            return FetchedDocument(url=url, title=title, text=body)
        except (requests.RequestException, RuntimeError) as e:
            last_err = e
            if attempt < _MAX_RETRIES:
                logger.warning(
                    f"Jina Reader attempt {attempt + 1} failed for {url}: "
                    f"{str(e)[:200]}, retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"Jina Reader gave up on {url}: {e}")

    assert last_err is not None
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def fetch_urls(urls: List[str]) -> List[FetchedDocument]:
    """
    顺序抓取多个 URL。某个失败时记录错误并继续，
    最后如果一个都没抓到则抛 RuntimeError；否则返回成功的部分。
    """
    docs: List[FetchedDocument] = []
    errors: List[str] = []
    for u in urls:
        try:
            docs.append(fetch_url(u))
        except Exception as e:
            errors.append(f"{u}: {e}")
            logger.warning(f"skipping {u}: {e}")
    if not docs:
        raise RuntimeError(
            "No URLs could be fetched. " + "; ".join(errors[:3])
        )
    return docs


def parse_url_list(raw: str) -> List[str]:
    """
    解析前端传来的 URL 文本（可能是换行 / 逗号 / 空格分隔），返回去重、保序的 URL 列表。
    """
    if not raw:
        return []
    parts = re.split(r"[\s,]+", raw.strip())
    seen: set[str] = set()
    out: List[str] = []
    for p in parts:
        p = p.strip().rstrip(",")
        if not p:
            continue
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out
