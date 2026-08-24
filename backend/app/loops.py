"""uvicorn 自定义事件循环工厂（Windows 强制 Selector）。

uvicorn 0.51 的 ``asyncio_loop_factory`` 在 Windows 直接返回 ``ProactorEventLoop``
（asyncio 子进程需要它）。但本项目 psycopg async 连库（CheckpointStore / planner
读 settings 表）依赖 ``SelectorEventLoop`` 的 ``add_reader`` 收 IO 事件，与
Proactor 在单个 loop 上互斥。

后端已改用线程 Popen 托管 Node MCP 子进程（见 browser_mcp._ThreadedPopen，不再
依赖 Proactor），故整环可安全切 Selector。uvicorn 支持 ``--loop <module:func>``
注入自定义工厂，这里返回 SelectorEventLoop 类即可。
"""

from __future__ import annotations

import asyncio


def selector_factory() -> asyncio.SelectorEventLoop:
    """创建并返回一个 ``SelectorEventLoop`` 实例。

    uvicorn 对自定义 ``--loop <module:func>`` 的分支是 ``import_from_string(self.loop)``
    原样返回该函数（不调用），由 ``asyncio.Runner`` 以无参方式 ``loop_factory()`` 调用。
    因此这里必须返回**实例**——若返回类，Runner 会拿类去 ``.close()`` 而崩
    (``BaseSelectorEventLoop.close() missing self``)。
    """
    return asyncio.SelectorEventLoop()