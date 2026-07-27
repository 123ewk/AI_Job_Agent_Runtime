"""健康检查路由。

提供存活探针与就绪探针，供容器编排与监控系统判断流量调度。
- /health       liveness：进程是否在运行（不查依赖）
- /health/db    数据库连通性
- /health/ready readiness：关键依赖是否可用
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.deps import get_app_settings, get_db
from app.core.config import Settings
from app.core.logging import get_logger
from app.schemas.health import ComponentStatus, HealthResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])
logger = get_logger("app.api.health")

DBSession = Annotated[AsyncSession, Depends(get_db)]
AppCfg = Annotated[Settings, Depends(get_app_settings)]


async def _ping_postgres(db: AsyncSession) -> ComponentStatus:
    """探测 PostgreSQL 连通性。

    健康检查内部捕获异常并返回结构化状态，避免向调用方抛 500，
    让探针语义稳定（错误也是 200 + status=error）。
    """
    try:
        result = await db.execute(text("SELECT 1"))
        ok = result.scalar_one() == 1
        return ComponentStatus(status="ok" if ok else "error", detail=None if ok else "unexpected result")
    except Exception as exc:
        logger.warning("PostgreSQL ping failed", error=str(exc))
        return ComponentStatus(status="error", detail=str(exc))


@router.get("", response_model=HealthResponse)
async def liveness(settings: AppCfg) -> HealthResponse:
    """存活探针。"""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=__version__,
        env=settings.app_env.value,
    )


@router.get("/db", response_model=ComponentStatus)
async def db_ping(db: DBSession) -> ComponentStatus:
    """数据库连通性探测。"""
    return await _ping_postgres(db)


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(db: DBSession) -> ReadinessResponse:
    """就绪探针：聚合各依赖组件状态。

    Redis / MinIO 探测留待对应模块接入后补齐；当前仅 PostgreSQL。
    """
    components: dict[str, ComponentStatus] = {
        "postgres": await _ping_postgres(db),
    }
    overall = "ok" if all(c.status == "ok" for c in components.values()) else "error"
    return ReadinessResponse(status=overall, components=components)
