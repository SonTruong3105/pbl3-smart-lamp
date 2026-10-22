"""Parallel Search MCP Client - Tìm kiếm web miễn phí không cần API Key.

API mới (2026) yêu cầu: {"objective": "...", "search_queries": ["..."]}
"""
import asyncio
from typing import Optional
import json
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client as streamablehttp_client
from loguru import logger

PARALLEL_MCP_URL = "https://search.parallel.ai/mcp"


def _unwrap_exception_group(exc: BaseException) -> BaseException:
    """Trích xuất lỗi gốc từ ExceptionGroup."""
    if hasattr(exc, "exceptions") and exc.exceptions:
        return _unwrap_exception_group(exc.exceptions[0])
    return exc


def _build_arguments(query: str, max_results: int = 3) -> dict:
    """
    Xây dựng tham số theo schema mới của Parallel.
    - objective: Mục tiêu của việc tìm kiếm (mô tả ngữ cảnh)
    - search_queries: Danh sách các câu truy vấn cụ thể
    """
    return {
        "objective": f"Tìm thông tin chính xác và mới nhất về: {query}",
        "search_queries": [query],
        "max_results": max_results,
    }


def _extract_text(result) -> Optional[str]:
    """Trích xuất text từ kết quả MCP."""
    if not result or not result.content:
        return None
    parts = []
    for item in result.content:
        if hasattr(item, "text") and item.text:
            parts.append(item.text)
    return "\n".join(parts) if parts else None


async def _search_via_mcp_sdk(query: str, max_results: int) -> Optional[str]:
    """Phương pháp 1: Dùng MCP SDK."""
    args = _build_arguments(query, max_results)
    async with httpx.AsyncClient(timeout=20.0) as http_client:
        async with streamablehttp_client(
            PARALLEL_MCP_URL, http_client=http_client
        ) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("web_search", arguments=args)
                return _extract_text(result)


async def _search_via_http_post(query: str, max_results: int) -> Optional[str]:
    """Phương pháp 2: Gọi JSON-RPC 2.0 qua HTTP POST trực tiếp (fallback)."""
    args = _build_arguments(query, max_results)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "web_search", "arguments": args},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(PARALLEL_MCP_URL, json=payload, headers=headers)
        if r.status_code != 200:
            logger.warning(
                f"HTTP POST status {r.status_code}: {r.text[:200]}"
            )
            return None

        content_type = r.headers.get("content-type", "")
        if "application/json" in content_type:
            data = r.json()
            result = data.get("result", {})
            if result.get("isError"):
                logger.warning(f"Parallel báo lỗi: {result}")
                return None
            content = result.get("content", [])
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            return "\n".join(parts) if parts else None

        # SSE stream
        parts = []
        for line in r.text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                    result = data.get("result", {})
                    if result.get("isError"):
                        continue
                    content = result.get("content", [])
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            parts.append(item.get("text", ""))
                except Exception:
                    continue
        return "\n".join(parts) if parts else None


async def search_web(query: str, max_results: int = 3) -> Optional[str]:
    """Tìm kiếm web qua Parallel, tự động fallback qua HTTP POST nếu MCP lỗi."""
    # 1. Thử MCP SDK
    try:
        text = await _search_via_mcp_sdk(query, max_results)
        if text:
            logger.info(f"🔍 Parallel MCP: '{query}' → {len(text)} chars")
            return text
        logger.warning(f"⚠️ Parallel MCP trả về rỗng: '{query}'")
    except BaseExceptionGroup as eg:
        root = _unwrap_exception_group(eg)
        logger.warning(f"⚠️ MCP SDK lỗi gốc: {type(root).__name__}: {root}")
    except Exception as e:
        logger.warning(f"⚠️ MCP SDK lỗi: {type(e).__name__}: {e}")

    # 2. Fallback: HTTP POST
    logger.info("   ↻ Fallback HTTP POST → Parallel MCP endpoint")
    try:
        text = await _search_via_http_post(query, max_results)
        if text:
            logger.info(f"🔍 Parallel HTTP: '{query}' → {len(text)} chars")
            return text
    except Exception as e:
        logger.error(f"❌ HTTP POST lỗi: {type(e).__name__}: {e}")

    return None


async def fetch_url(url: str) -> Optional[str]:
    """Lấy nội dung chi tiết từ một URL."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as http_client:
            async with streamablehttp_client(
                PARALLEL_MCP_URL, http_client=http_client
            ) as streams:
                read_stream, write_stream = streams[0], streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "web_fetch", arguments={"url": url}
                    )
                    text = _extract_text(result)
                    if text:
                        logger.info(f"📄 Parallel Fetch: '{url}' → {len(text)} chars")
                    return text
    except BaseExceptionGroup as eg:
        root = _unwrap_exception_group(eg)
        logger.error(f"❌ Fetch lỗi gốc: {type(root).__name__}: {root}")
        return None
    except Exception as e:
        logger.error(f"❌ Fetch lỗi: {type(e).__name__}: {e}")
        return None