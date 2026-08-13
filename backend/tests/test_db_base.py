"""app/db/base.py 惰性引擎与会话工厂的回归测试。"""

from __future__ import annotations

import threading

from app.db import base as db_base


def test_get_session_factory_cold_start_no_self_deadlock() -> None:
    """回归：冷启动首次 get_session_factory() 不得自死锁。

    历史 bug（2026-08-13 修复，见 docs/issues/2026-08-13-db-engine-lazy-init-self-deadlock.md）：
    get_session_factory() 在持有非重入 threading.Lock `_init_lock` 期间调用 get_engine()，
    而 get_engine() 在冷启动（_state.engine 为空）时对同一把锁再次 acquire →
    同线程重复获取非重入锁永久阻塞。生产首个触 DB 的请求必现。

    用带超时的守护线程执行，使回归时「挂死」快速失败为断言错误，而非卡住测试套件。
    注意：get_settings 已被 conftest 在导入 app 前 patch 为测试库（copilot_test），
    因此此处创建 engine 不会触碰开发库（create_async_engine 不建立连接）。
    """
    # 白盒复位单例，模拟冷启动
    db_base._state.engine = None
    db_base._state.session_factory = None

    out: dict[str, object] = {}

    def _call() -> None:
        out["factory"] = db_base.get_session_factory()

    thread = threading.Thread(target=_call, daemon=True)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive(), "get_session_factory 自死锁：同线程重复获取非重入 threading.Lock"

    factory = out["factory"]
    assert factory is not None
    assert db_base._state.engine is not None
    assert db_base._state.session_factory is factory

    # 复位单例；engine 从未连接，无需 dispose。其他测试经 get_db 覆盖绕过 app 惰性 factory。
    db_base._state.engine = None
    db_base._state.session_factory = None


def test_get_session_factory_returns_cached_singleton() -> None:
    """会话工厂应缓存同一实例（惰性单例语义）。"""
    db_base._state.engine = None
    db_base._state.session_factory = None

    first = db_base.get_session_factory()
    second = db_base.get_session_factory()

    assert first is second
    assert db_base._state.engine is not None

    db_base._state.engine = None
    db_base._state.session_factory = None
