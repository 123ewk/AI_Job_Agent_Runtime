# 2026-08-13 数据库惰性引擎初始化自死锁（冷启动首个 DB 请求挂死）

## 1. 问题背景（Background）

- **模块**：`backend/app/db/base.py`（惰性异步引擎 / 会话工厂单例）
- **正在实现的功能**：Phase 3 I11 岗位管理（JobsView）手动验证。所有 4 个 commit 已落地（后端 DTO、lib 工具、job store、views），pytest 88 passed / 7 skipped，`pnpm build` 0 错误。
- **系统架构**：FastAPI 分层（api → service → repository → database），异步 SQLAlchemy 2.0 + asyncpg，单机 uvicorn；PG/Redis/MinIO 由 docker 起，健康。
- **技术栈**：Python asyncio（Windows 下 ProactorEventLoop）、uvicorn、asyncpg、SQLAlchemy 2.0 `create_async_engine`、`threading.Lock` double-checked locking。

## 2. 问题现象（Symptoms）

- `/api/v1/health` 返回 200（不触 DB）。
- 首个触 DB 的请求 `GET /api/v1/jobs?page=1&page_size=10` 返回 HTTP:000，后端日志无该请求的访问日志。
- 重复复现：两次独立启动均如此，`/jobs` 必挂。
- `netstat` 显示 `:8000` 上 `CLOSE_WAIT`（服务端）堆积，连 `/health` 的连接也被卡在 `CLOSE_WAIT`——**整个事件循环被堵死**，不只是单个请求。
- 独立脚本直接查库（app 配置）可通（jobs 1 行）——排除「数据库本身不可达」。

## 3. 根因分析（Root Cause Analysis）

**现象 ≠ 根因**：现象是「事件循环挂死、/jobs 不响应」，但这不是网络/DB 不可达，而是**同步代码中的线程锁自死锁**。

调用链（`app/db/base.py`）：

```python
# get_session_factory：
if _state.session_factory is None:
    with _init_lock:                              # ① 同一线程第一次获取锁（成功）
        if _state.session_factory is None:
            _state.session_factory = async_sessionmaker(
                bind=get_engine(),                # ② 锁内调用 get_engine()
                ...
            )

# get_engine：
def get_engine() -> AsyncEngine:
    if _state.engine is None:
        with _init_lock:                          # ③ 同一线程再次获取「非重入」锁 → 永久阻塞
```

- `threading.Lock` 是**非重入**锁：同一线程在已持有期间再次 `acquire` 会**永久阻塞**（无 owner 记录，不抛异常）。
- 冷启动时 `get_session_factory` 是**第一个调用方**：先拿到 `_init_lock`，又在锁内调 `get_engine()`；`get_engine()` 发现 `_state.engine is None`，再次 acquire 同一把锁 → **同线程自死锁**。
- 这是**同步阻塞**（锁等待），不是 await 挂起——事件循环无法切走，所以连已建立连接的 /health 也无法完成关闭，表现为全进程僵死。
- 触发条件：任何首次调用 `get_session_factory()` 的 DB 请求（生产 = 冷启动后第一个触 DB 请求）。

**为何潜伏至今、测试未发现**：
- 死锁由 `98e3762`（Phase 2 M5「lazy engine」提交）引入。
- `tests/conftest.py` 用**自己的** `create_async_engine(TEST_DB_URL)`（copilot_test），并覆盖 `get_db` 依赖，**从未调用 app 的 `get_session_factory()`** → 死锁路径在 pytest 中零覆盖。
- Phase 2 之前的后端验证均在 pytest 层完成，从未用真实 PG + 冷 uvicorn 打过触 DB 的请求。

## 4. 排查过程（Debug Journey）

1. **先确认现象可复现**：/health 200、/jobs HTTP:000。看 `netstat`：不仅 /jobs，连 /health 的连接也在 `CLOSE_WAIT` → 判断为**整个事件循环被同步阻塞**，而非网络超时。
2. **排除业务代码**：读 `api/v1/jobs.py`、`service/job.py`、`repository/job.py`、`deps.py`、`main.py`——全部干净 async，无 `requests`/`time.sleep`/同步 socket。且 pytest 88 passed 覆盖 /jobs，说明**应用逻辑正确**。
3. **二分：独立 DB 探针**（精确复刻 app 的引擎/会话路径）。探针自身卡住 >60s → 问题在 DB 访问路径本身，与 uvicorn 无关。
4. **细分段插桩**：
   - `create_async_engine` 单独调用（同步上下文）→ 1s 内完成 → 引擎创建本身没问题。
   - 但在**运行中的事件循环内**走 `get_session_factory()` → 卡在 `get_session_factory()` 内部。
5. **线程级看门狗 dump 主线程栈**（关键一步）：即使事件循环被同步阻塞，独立线程也能 dump `sys._current_frames()`。栈明确指向：
   ```
   db/base.py:94  get_session_factory → bind=get_engine(),
   db/base.py:71  get_engine → with _init_lock:
   ```
   主线程（唯一线程）阻塞在**获取 `_init_lock`** → 同线程重复获取非重入锁 = 自死锁。至此根因锁定。
6. **确认测试为何没抓到**：`tests/conftest.py:143` 直接 `create_async_engine(TEST_DB_URL)` 且 `get_db` 被覆盖 → app 的 `get_session_factory()` 在测试中从未执行。

> 排查过程中的弯路：曾怀疑「Windows ProactorEventLoop + asyncpg 不兼容」「localhost 解析到 ::1」「连接池 pre_ping 阻塞」——全部被探针排除。教训：**在同步阻塞事件循环的场景下，唯一可靠的工具是「独立线程 dump 主线程栈」**，比猜驱动快得多。

## 5. 技术选型分析（Technical Decision）

**为什么用 `threading.Lock` + double-checked locking**（原设计意图）：
- asyncio 单线程中协程仅在 await 点切换，`get_engine`/`get_session_factory` 内部无 await，理论上天然原子。
- 但 `TestClient` 会把 ASGI app 跑在独立线程的独立循环中，存在**跨线程首次调用**的可能 → 用锁防御多线程竞态。

**候选修复方案**：

| 方案 | 做法 | trade-off |
|---|---|---|
| A. `threading.RLock` | 锁改为可重入 | 一行改动；但全局放宽锁语义，未来任何意外嵌套会被「静默容忍」，掩盖同类 bug |
| B. 结构性修复 | `get_session_factory` **先调 `get_engine()`（自带锁）再持锁建工厂** | 改动 3 行；锁临界区只剩创建 `async_sessionmaker`（微秒级），严格符合原设计「持锁期间只做微秒级同步操作」；未来任何同款嵌套会**立即死锁暴露**（fail-loud） |

**结论：选 B**。理由：
- 直接移除嵌套本身（根因），而非放宽锁来容忍嵌套。
- 保持 `threading.Lock` 非重入语义不变，让未来的同款错误 fail-fast。
- `get_engine()` 自带 double-checked locking，先调用是线程安全的；锁外取 engine 不引入新竞态（`dispose_engine` 只在关闭/测试重置时运行，不并发于请求）。

## 6. 最终解决方案（Final Solution）

`backend/app/db/base.py` `get_session_factory()`：

```python
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _state.session_factory is None:
        # 先在锁外取 engine：get_engine() 自带 double-checked locking，线程安全。
        # 若在持有 _init_lock 时调用 get_engine()，冷启动首请求会因同一线程重复
        # 获取非重入 threading.Lock 而自死锁（2026-08-13 修复）。
        # 锁内只创建 async_sessionmaker（微秒级），符合惰性初始化设计意图。
        engine = get_engine()
        with _init_lock:
            if _state.session_factory is None:
                _state.session_factory = async_sessionmaker(
                    bind=engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                )
    return _state.session_factory
```

**为什么有效**：`get_engine()` 在锁外调用，其内部自己的 `_init_lock` 不会与 `get_session_factory` 的锁嵌套；锁临界区仅剩 `async_sessionmaker(...)`（微秒级、无锁嵌套）。

**回归测试** `tests/test_db_base.py`：
- `test_get_session_factory_cold_start_no_self_deadlock`：白盒复位 `_state`，用带 10s 超时的守护线程调用 `get_session_factory()`，断言不挂死且两个单例被初始化。回归时挂死 → 快速失败为断言错误（而非卡死套件）。
- `test_get_session_factory_returns_cached_singleton`：验证单例缓存语义。

**验证结果**：
- 修复后探针：`get_session_factory()` 0.12s、count=1、dispose 干净。
- 全量 pytest：88 passed / 7 skipped → 加 2 个回归测试后共 90 passed（见下方预防节）。
- 修复后重启 uvicorn，`GET /api/v1/jobs` 恢复正常响应。

## 7. 风险与副作用（Risks & Trade-offs）

- **锁内代码变少**：`_init_lock` 现在的唯一临界区是 `async_sessionmaker` 创建，仍受 double-checked locking 保护，多线程首次调用语义不变。
- **`get_engine()` 提前调用**：`get_session_factory` 每次在 `session_factory is None` 时会先调 `get_engine()`——幂等且极快（首调 ~0.1s 含 asyncpg 导入，之后无开销），无性能影响。
- **未改 `dispose_engine`**：它仍持有 `_init_lock` 跨 await（`await engine.dispose()`）。这只在应用关闭/测试重置时执行，不与请求并发；若未来在请求路径调用 `dispose_engine`，需再审视（锁跨 await 是潜在阻塞点，已在注释标记为后续风险）。
- **成本**：修复 + 2 个回归测试，改动集中在 1 个文件，无架构变更。

## 8. 如何预防（Prevention）

1. **回归测试覆盖惰性初始化路径**（本次已加）：冷启动 `get_session_factory()` 不得死锁、单例缓存语义。
2. **测试基建对齐**：`tests/conftest.py` 覆盖 `get_db` 导致 app 的惰性 factory 零覆盖。后续新增「真实 uvicorn + 真实 PG 的冒烟测试」或在 conftest 增加一条「app 惰性 factory 也能在测试循环内初始化」的断言，避免惰性路径再次裸奔。
3. **代码评审检查项**：凡在 `with threading.Lock:` / `RLock` 内调用任何可能再次取同一把锁的函数，一律 flagged；跨线程共享的锁临界区只允许微秒级同步操作。
4. **启动冒烟**：`/api/v1/health` 之外，应把首个触 DB 的接口（`/jobs`、`/settings`）纳入部署/本地启动冒烟清单——本次 bug 正是「health 绿、首个 DB 请求红」的形态。

## 9. 学到的核心知识（Key Learnings）

- **`threading.Lock` 非重入**：同一线程重复 `acquire` 会永久阻塞，**不抛异常、无死锁检测**。这使它既是并发安全的工具，也是静默自死锁的温床。重入语义必须显式用 `RLock` 表达。
- **同步阻塞 vs 无限 await**：事件循环「挂死」要先区分二者——`asyncio.all_tasks()` 里的看门狗协程能跑 = 无限 await；看门狗也跑不了 = 同步阻塞。本次用「独立线程 dump `sys._current_frames()`」一锤定音。
- **pytest 全绿 ≠ 生产可用**：测试 fixture 为隔离而绕开（override）某些路径（如 `get_db`），会让生产专有路径（惰性初始化、真实 PG、uvicorn 启动）完全无覆盖。每个「测试专用替代」都应在 conftest 里注明它绕开了哪条生产路径。
- **惰性初始化与锁的耦合**：`get_session_factory → get_engine` 天然嵌套两次加锁意图，只要都用同一把非重入锁就必死锁。设计惰性单例时，子单例的获取应自带锁、父单例不要在锁内调用子单例的加锁入口。

## 10. 面试题沉淀（Interview Knowledge）

**题目 1：`threading.Lock` 在同一线程内重复 acquire 会发生什么？**
- 考察点：GIL、锁的语义、非重入锁 vs RLock。
- 标准答案：永久阻塞（deadlock）。`threading.Lock` 是互斥锁，无 owner 与递归计数，同一线程二次 acquire 会阻塞直到持有者释放，而持有者就是自己 → 死锁，且不抛异常。
- 延伸：为什么 asyncio 单线程下仍要锁？→ TestClient/多线程调用；协程只在 await 点切换，锁内无 await 时对协程原子，但对多线程不原子。

**题目 2：如何定位「事件循环被阻塞」而 CPU 并不高？**
- 考察点：asyncio 调度、阻塞 vs await、诊断工具。
- 标准答案：先区分同步阻塞与无限 await（异步看门狗协程能否触发）；同步阻塞时用独立线程 `sys._current_frames()` 或 `py-spy dump` 取主线程栈；看栈停在哪个同步函数（本次停在 `threading.Lock.acquire`）。
- 延伸：为什么 `asyncio.all_tasks()` 在同步阻塞下也不返回？→ 它本身也是协程，事件循环被堵死后根本调度不到它。

**题目 3：惰性单例 + double-checked locking 的坑？**
- 考察点：并发安全、可重入、锁的粒度。
- 标准答案：double-checked locking 需保证临界区无重入调用；父单例（session_factory）在锁内调用子单例（engine）的加锁入口，若共用非重入锁则自死锁。正确做法：子单例自带锁，父单例锁外先取子单例引用。
- 延伸：Python 中 double-checked locking 是否必要？→ asyncio 单线程内对「无 await 的检查-创建-赋值」天然原子，锁只为跨线程（TestClient）场景。
