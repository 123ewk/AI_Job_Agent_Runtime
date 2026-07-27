"""结构化日志配置。

设计动机：
- 禁止 print，统一走 structlog 输出 JSON/可读结构化日志，便于检索与排查。
- 每条日志自动携带 request_id/trace_id（由中间件注入）等服务端字段。
- dev 环境用可读控制台渲染，prod 用 JSON 渲染以便采集。
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO", json_render: bool = False) -> None:
    """初始化 structlog 与标准 logging。

    Args:
        log_level: 日志级别字符串（DEBUG/INFO/WARNING/ERROR）。
        json_render: True 使用 JSON 渲染（生产），False 使用控制台可读渲染（开发）。

    关键点：structlog 与 stdlib logging 通过 ProcessorFormatter 桥接，
    使得第三方库（uvicorn/sqlalchemy）的日志也走同一套格式。
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # stdlib logging 基础配置
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer() if json_render else structlog.dev.ConsoleRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    # 避免重复 handler 导致日志重复输出
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取一个绑定 logger。"""
    return structlog.stdlib.get_logger(name)
