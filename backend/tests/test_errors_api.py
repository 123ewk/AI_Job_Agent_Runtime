"""全局异常处理契约测试。

覆盖统一 ErrorResponse 格式（error/message/details）与语义化状态码：
- AppError 子类：NotFoundError(404) / BadRequestError(400)
- StarletteHTTPException：未知路由 404 统一为 ErrorResponse
- RequestValidationError：422 保留 FastAPI 默认 {"detail": [...]} 契约（有意不改）

背景：此前 service 层 raise ValueError 无全局 handler，一律变 500，前端无法区分
「资源不存在」与「服务器内部错误」。本次引入 app/core/exceptions 领域异常 + 全局
handler 后，状态码语义化、响应体统一，本测试锁定该契约防止回归。
"""

from __future__ import annotations

from httpx import AsyncClient

BASE = "/api/v1"


class TestErrorContract:
    """全局异常响应契约。"""

    async def test_not_found_conversation_returns_404(self, client: AsyncClient) -> None:
        """不存在的会话 -> 404 + error=not_found。"""
        resp = await client.get(f"{BASE}/conversations/99999")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"] == "not_found"
        assert "会话不存在" in data["message"]

    async def test_not_found_job_returns_404(self, client: AsyncClient) -> None:
        """不存在的职位（删除路径）-> 404 + error=not_found。"""
        resp = await client.delete(f"{BASE}/jobs/99999")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"] == "not_found"
        assert "职位不存在" in data["message"]

    async def test_unknown_route_returns_404_http_error(self, client: AsyncClient) -> None:
        """未注册路由 -> 404 + error=http_error（Starlette 异常统一格式）。"""
        resp = await client.get(f"{BASE}/no-such-route")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"] == "http_error"

    async def test_settings_invalid_category_returns_422(self, client: AsyncClient) -> None:
        """非法配置分类 -> 422（Pydantic schema 白名单校验）。

        D18 修复：分类白名单校验从 service 层 400 前移到 schema 层 422，
        与其他参数校验语义一致（FastAPI 默认 422 契约）。
        """
        resp = await client.put(
            f"{BASE}/settings/batch",
            json={"category": "bogus", "updates": [{"key": "k", "value": "v"}]},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data
        assert isinstance(data["detail"], list)
        assert any("不支持的配置分类" in str(item.get("msg", "")) for item in data["detail"])

    async def test_validation_error_keeps_default_422_contract(self, client: AsyncClient) -> None:
        """Pydantic 校验失败保留 FastAPI 默认 422 {"detail": [...]} 契约。"""
        resp = await client.post(f"{BASE}/conversations", json={})
        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data
        assert isinstance(data["detail"], list)
