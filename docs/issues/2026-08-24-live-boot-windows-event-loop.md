# 后端首次真实启动失败问题复盘（2026-08-24）

> 说明：本文件按用户偏好，先用**大白话四段**讲清楚问题现象 → 根因 → 修改方案 → 修改结果；
> 末尾附**技术附录**保留底层细节供深挖。少贴代码、少用术语。

---

## 一、问题现象（大白话）

**一句话**：这个后端之前只通过"跑测试"验证过，从来没真正用启动命令启动过。这次第一次用
真命令启动，一上来就各种崩——要么报"事件循环类型不对"，要么报"数据库网址看不懂"，浏览器桥
（让后端驱动你真实打开的浏览器的那条通道）也起不来。结果是：后端起不来，什么功能都用不了。

> 注：本文记录的是当时这批导致崩掉的根因与修复。现在用修复后的命令已经能正常启动（健康检查
> 返回 200），本文是为了把"为什么当初起不来"沉淀下来，避免重蹈。

**三个具体表现**：
1. 数据库驱动报 `Psycopg cannot use the 'ProactorEventLoop'` —— 大白话：数据库驱动说"这个事件循环我用不了"。
2. 数据库网址报 `missing "=" after ...`（连接串解析失败）—— 大白话：程序不认我给它的网址写法。
3. 浏览器桥启动超时、后端自己拉浏览器子进程也拉不起来。

---

## 二、根因（一句话 + 人话解释）

**一句话**:在 Windows 上，后端框架、数据库驱动、浏览器子进程三件套对"该用哪种事件循环／哪种
网址格式／怎么开子进程"的默认想法不一样,撞在一起互相冲突。

**人话拆开**：
- **事件循环互斥（最关键）**：Windows 上有两种"事件循环"（可以理解为程序里处理异步任务的
  调度员）。数据库驱动只认其中一种（选择器型）；而后端框架在 Windows 上默认给定另一种
  （Proactor 型）。两者在同一程序里撞车，谁都没法正常干活。
- **网址方言**：项目里已有的数据库网址是给另一套驱动（asyncpg）写的，后缀不一样；新的存档
  驱动（psycopg）按自己的格式去解析这份网址就解析失败。
- **子进程方式**：后端想自己用"协程"方式拉浏览器子进程，但这套方式恰好跟前面那个"选择器型
  事件循环"水火不容，于是在 Windows 上拉不起来。

---

## 三、修改方案（思路,一句话一条）

1. **强制用"选择器型事件循环"**：给启动命令加一个参数,指定用数据库驱动认的那种循环,绕开
   Windows 默认强给的那种。
2. **浏览器子进程改用"后台线程"拉起**：不再用"协程"方式，改用更稳的后台线程去等子进程结束,
   这样既能自拉浏览器,又不跟选择器型循环打架。
3. **补一个 psycopg 认识的数据库网址**：多提供一个后缀正确的网址,给新存档驱动专用。
4. **浏览器桥失败不再拖垮整个应用**：改成"起不来就只降级浏览器能力,应用照常启动",后面自动重试。

---

## 四、修改结果

**现在启动正常**：健康检查接口返回 `200`、后端跑起来、数据库里自动建好了存档用的 5 张表、
浏览器桥能复用你本地已经开着的 MCP 通道。用户之前担心的"必须要装独立 MCP"也不需要——后端
自己就能拉起浏览器子进程。

---

## 五、技术附录（可选的深挖,不想看可跳过）

### 5.1 涉及文件与改动
- 新增 `backend/app/loops.py`：`selector_factory()` 返回一个 **SelectorEventLoop 实例**。
  ⚠️ 关键坑：uvicorn 的自定义 `--loop <模块:函数>` 拿到的是"函数本身"（不调用）交给 Runner 无参调用,
  所以工厂必须**返回实例**（`asyncio.SelectorEventLoop()`），返回类会让 `close() missing self` 崩。
- `backend/app/infra/browser_mcp.py`：新增 `_ThreadedPopen`（`subprocess.Popen` spawn、`wait`
  via `asyncio.to_thread`、`terminate/kill` 同步），把 `_spawn` 从 `asyncio.create_subprocess_exec`
  改为线程 Popen。Windows 上 `create_subprocess_exec` 依赖 Proactor，与 psycopg 需要的 Selector 不兼容。
- `backend/app/core/config.py`：新增 `database_dsn` 派生属性（`postgresql://...`,libpq 方言）。
  原 `database_url` 是 `postgresql+asyncpg://...`,psycopg 解析不了。
- `backend/app/agent/runtime/checkpoint_store.py`：存档器默认改用 `get_settings().database_dsn`。
- `backend/app/main.py`：启动期 `set_event_loop_policy`（import 期设策略被 uvicorn 覆盖,保留无害）；
  浏览器桥 start 改为 try/except 非 fatal。

### 5.2 启动命令（Windows 关键）
```
uv run uvicorn app.main:app --loop app.loops:selector_factory --port 8000
```

### 5.3 为什么政策没被覆盖 & 两个坑
- **政策覆盖**：uvicorn 0.51 在 win32 会通过自己的工厂强给 `ProactorEventLoop`,所以在 main.py
  import 期 `set_event_loop_policy(Selector)` 无效。必须用 `--loop` 自定义工厂直接提供实例。
- **实例 vs 类**：custom `--loop` 分支是"原样返回导入的函数"交给 Runner 无参调用。工厂必须
  `return asyncio.SelectorEventLoop()`,不能 `return asyncio.SelectorEventLoop`。
- **子进程 vs 循环**：`asyncio.create_subprocess_exec` 在 Windows 仅 Proactor 支持；与 psycopg
  的 Selector 同 loop 互斥。改线程 Popen 后两种需求并存（Selector 循环 + 自拉 Node 子进程）。

### 5.4 浏览器架构澄清（重要）
当前链路是**扩展驱动、没有 CDP**：后端 adapter → Chrome MCP Server(:12307) → 扩展 background
WS(`ws://127.0.0.1:12307/ws`,首条消息鉴权) → 扩展在你**手动打开的真实页面**里用
`chrome.scripting` 执行。**不需要 Chrome 9222/CDP 调试端口**。`browser_mcp.start()` 改为非 fatal：
端口已有健康 server 就复用,否则自己用线程 Popen 拉起(协作方无需另外装 MCP)。

### 5.5 验证
- 全量测试：修复后的引擎相关改动另见配套提交；本文聚焦启动链路,启动实测 health 200、agent DB 建表通过。

---

## 六、防止再次发生
- 启动命令加入 **`--loop app.loops:selector_factory`**（文档已写进 main.py docstring）。
- 改动事件循环/子进程/DSN 方言的代码,补一次**真实 uvicorn 启动**验证（仅跑 pytest 不够,本批问题
  全是 live boot 才会暴露的 Windows 特定坑）。
- 新增配置属性时同步补 `database_dsn`/`database_url` 两方言,并同步 test conftest 的 MockSettings。