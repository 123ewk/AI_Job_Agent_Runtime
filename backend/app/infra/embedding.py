"""向量 embedding 客户端（OpenAI 兼容 /embeddings 协议）。

MemoryService 在配置了向量模型时调用本客户端生成真实向量；
未配置或调用失败时由 Service 层降级到关键词 / 精确匹配（见 service/memory.py）。

协议约定（与 LLM 侧一致，OpenAI 兼容）：
- POST {base_url}/embeddings
- 请求体：{"model": ..., "input": ..., "dimensions": 512}
- 认证头：Authorization: Bearer {api_key}
- 响应：{"data": [{"embedding": [0.1, 0.2, ...]}]}

维度硬约束：记忆库 memory.embedding 列为 Vector(512)。本客户端强制
dimensions=512（OpenAI text-embedding-3 系列原生 1536，需靠该参数缩到 512）；
服务商不支持该参数时按协议报错 → EmbeddingError → 调用方降级并日志提示。
"""

from __future__ import annotations

import httpx

# 记忆库 embedding 列维度（隐式 512，设置表单不暴露 dimension 字段）
EMBEDDING_DIM = 512

# base_url 为空时兜底默认地址（OpenAI 官方）
_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class EmbeddingError(Exception):
    """embedding API 调用失败（网络 / HTTP 非 2xx / 响应畸形）。"""


async def generate_embedding(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    text: str,
    timeout: float = 10.0,
) -> list[float]:
    """生成文本 embedding 向量（OpenAI 兼容协议，512 维）。

    Args:
        api_key: API Key（已解密明文，来自活动配置注册表或 DB 解密）
        base_url: OpenAI 兼容 Base URL，为空兜底官方地址
        model: 向量模型名
        text: 待向量化文本
        timeout: HTTP 超时秒数（外部服务不可控，超时保护不让调用方无限阻塞）

    Returns:
        512 维浮点向量（服务端已 L2 归一化，pgvector 余弦距离可直接用）

    Raises:
        EmbeddingError: 网络异常 / 非 2xx / 响应体畸形 / 向量含非数值
    """
    base = (base_url or _DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}/embeddings"
    payload = {"model": model, "input": text, "dimensions": EMBEDDING_DIM}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError as exc:
        msg = f"embedding 请求失败: {exc}"
        raise EmbeddingError(msg) from exc

    if resp.status_code != 200:
        msg = f"embedding 接口 HTTP {resp.status_code}: {resp.text[:200]}"
        raise EmbeddingError(msg)

    try:
        data = resp.json()["data"][0]["embedding"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        msg = f"embedding 响应畸形: {resp.text[:200]}"
        raise EmbeddingError(msg) from exc

    try:
        return [float(x) for x in data]
    except (TypeError, ValueError) as exc:
        msg = "embedding 向量含非数值元素"
        raise EmbeddingError(msg) from exc
