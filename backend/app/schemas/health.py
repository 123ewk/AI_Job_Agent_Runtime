"""健康检查相关 DTO。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ComponentStatus(BaseModel):
    """单个依赖组件的探测结果。"""

    status: Literal["ok", "error"]
    detail: str | None = None


class HealthResponse(BaseModel):
    """存活探针（liveness）响应：进程是否在运行。"""

    status: Literal["ok", "error"]
    app: str
    version: str
    env: str


class ReadinessResponse(BaseModel):
    """就绪探针（readiness）响应：依赖是否可用，可否接流量。"""

    status: Literal["ok", "error"]
    components: dict[str, ComponentStatus]
