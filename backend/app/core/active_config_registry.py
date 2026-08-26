"""活动配置注册表（进程内内存单例）。

方案 A（设置 local-first）的核心：Settings 唯一真源移到扩展本地后，后端不再
从 DB 读设置，改为读本注册表——由扩展在设置变更 / 建 WS 连接时经本机限定
端点 POST 进来，落内存供 Agent 运行时取用。

安全约定（防 api_key 泄漏，实现时必须遵守）：
- **只写不入出（HTTP 视角）**：提供内部 get_active_config() 供 Agent 运行时
  取明文 key（这正是本模块存在意义），但**绝无 HTTP GET 接口**能把 key 吐回。
- 永不落日志（见 logging 纪律），绝不写回任何持久化（DB/文件）。
- 进程重启即清空，依赖扩展在首个 WS 连接/建任务时重推补上。

线程安全：内存短临界区，用 threading.Lock 覆盖异步事件循环与线程池两种触碰路径。
"""

from __future__ import annotations

import threading
from typing import Any

# 允许的活动配置种类（key 白名单，防非法 kind 写入）
ALLOWED_KINDS: frozenset[str] = frozenset({"llm", "job_rule", "reply_style"})

_lock = threading.Lock()
_active: dict[str, dict[str, Any]] = {}


def set_active_config(kind: str, data: dict[str, Any]) -> None:
    """写入一类活动配置（浅拷贝，防止调用方后续改动污染注册表）。

    Args:
        kind: 配置种类，须在 ALLOWED_KINDS 白名单内，否则静默忽略。
        data: 该类的配置键值（llm 时含 api_key 明文，仅存内存）。
    """
    if kind not in ALLOWED_KINDS:
        return
    with _lock:
        _active[kind] = dict(data)


def get_active_config(kind: str) -> dict[str, Any]:
    """读取一类活动配置；未设置或未知 kind 返回空 dict。

    返回副本，调用方改返回值不影响注册表内部状态。
    """
    if kind not in ALLOWED_KINDS:
        return {}
    with _lock:
        return dict(_active.get(kind, {}))
