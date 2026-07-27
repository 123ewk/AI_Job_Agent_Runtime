"""健康检查接口测试。

只测不依赖外部服务的存活探针与根路径；
涉及 DB 的就绪探针由 scripts/check_services.py 在集成环境验证。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    # with 上下文触发 lifespan 启停
    with TestClient(app) as c:
        yield c


def test_root(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert "app" in body
    assert body["docs"] == "/docs"


def test_liveness(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "env" in body
