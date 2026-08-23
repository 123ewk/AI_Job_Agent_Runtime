"""WorkflowEngine 进程内单例注册表（service-locator，doc 04 §5 装配）。

为什么需要：engine 在 FastAPI lifespan 中装配（依赖用户 LLM 配置、CheckpointStore、
后台消费循环），是**进程内单例**（持有执行锁与挂起态，V1 严格单任务）。而
ApprovalService 等按请求构造、拿不到 ``request.app.state``，却需要在审批决策到达时
经**同一引擎实例** resume() 续跑。故用模块级注册表暴露引擎：

- 对齐已有单例模式：``get_queue_client()``/``get_session_factory()`` 均用进程内
  单例/lru_cache，本注册表延续此风格。
- 生命周期由 lifespan 控制：装配成功调用 ``set_runtime_engine``，关闭期
  ``clear_runtime_engine``。未装配（引擎被跳过 / 已关闭）时 getter 返回 None，
  调用方据此降级（如 log + 跳过恢复），不抛异常。
- V1 单 worker 语义：挂起态在进程内，进程重启即丢（已文档化的局限）。多 worker
  扩容时改为 Redis 分布式锁 + 共享恢复，本注册表随之演进。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅类型注解，避免循环 import（registry 无运行时引擎依赖）
    from app.agent.runtime.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)

_ENGINE: WorkflowEngine | None = None


def set_runtime_engine(engine: WorkflowEngine) -> None:
    """装配期注册引擎单例。重复注册用日志提示（正常流程只会调用一次）。"""
    global _ENGINE  # noqa: PLW0603
    if _ENGINE is not None and _ENGINE is not engine:
        logger.warning("runtime engine replaced; existing suspend state lost")
    _ENGINE = engine


def get_runtime_engine() -> WorkflowEngine | None:
    """取引擎单例；未装配（被跳过/已关闭）返回 None，调用方据此降级。"""
    return _ENGINE


def clear_runtime_engine() -> None:
    """关闭期登出引擎，防止残留引用。"""
    global _ENGINE  # noqa: PLW0603
    _ENGINE = None
