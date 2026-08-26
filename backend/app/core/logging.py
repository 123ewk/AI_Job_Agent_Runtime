"""结构化日志配置。

设计动机：
- 禁止 print，统一走 structlog 输出 JSON/可读结构化日志，便于检索与排查。
- 每条日志自动携带 request_id/trace_id（由中间件注入）等服务端字段。
- dev 环境用可读控制台渲染，prod 用 JSON 渲染以便采集。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog


def configured_log_dir() -> Path:
    """应用日志目录：backend/logs/（本文件在 backend/app/core/logging.py，向上 2 级=backend）。"""
    return Path(__file__).resolve().parents[2] / "logs"


def configure_logging(
    log_level: str = "INFO",
    json_render: bool = False,
    log_dir: Path | None = None,
) -> None:
    """初始化 structlog 与标准 logging。

    Args:
        log_level: 日志级别字符串（DEBUG/INFO/WARNING/ERROR）。
        json_render: True 使用 JSON 渲染（生产），False 使用控制台可读渲染（开发）。
        log_dir: 日志目录。默认 backend/logs/，自建并写 backend.log（按 5MB 轮转保留 5 份）。

    关键点：structlog 与 stdlib logging 通过 ProcessorFormatter 桥接，
    使得第三方库（uvicorn/sqlalchemy）的日志也走同一套格式。

    双 sink：stdout（终端/后台可看）+ RotatingFileHandler（磁盘持久，重启后可查）。
    安全：文件日志同样可能被检索，需确保 api_key 等秘密绝不进日志（见各写入点）。
    """
    sink_dir = log_dir or configured_log_dir()
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

    # stdout sink：终端/后台实时可读
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    # 文件 sink：磁盘持久，重启/无终端时排查用。按大小轮转防无限增长。
    sink_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        sink_dir / "backend.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # 避免重复 handler 导致日志重复输出
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取一个绑定 logger。"""
    return structlog.stdlib.get_logger(name)
