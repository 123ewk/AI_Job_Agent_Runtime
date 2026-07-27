"""v1 路由聚合。

所有 v1 路由在此挂载到 /api/v1 前缀下，main.py 仅 include 此 router。
新增业务模块时在此注册，保持入口清爽。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
